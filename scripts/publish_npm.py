"""Validate a verified npm artifact set; publish only with the explicit --publish flag."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from prepare_upstream import ROOT, safe_path, version
from release_info import read_release

REGISTRY = "https://registry.npmjs.org"
TARGETS = {"x86_64-pc-windows-msvc": "win32-x64", "x86_64-unknown-linux-gnu": "linux-x64",
           "aarch64-apple-darwin": "darwin-arm64", "x86_64-apple-darwin": "darwin-x64"}


def file_hash(path, algorithm="sha256"):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, algorithm)


def registry_package(name):
    try:
        request = Request(f"{REGISTRY}/{quote(name, safe='@')}", headers={"Cache-Control": "no-cache"})
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as error:
        if error.code == 404:
            return {"versions": {}, "dist-tags": {}}
        raise


def wait_for_published(package, tag, *, lookup=registry_package, timeout=600,
                       clock=time.monotonic, sleep=time.sleep):
    """Wait for npm's accepted upload to become public; never republish it."""
    expected = "sha512-" + base64.b64encode(file_hash(package["path"], "sha512").digest()).decode()
    deadline = clock() + timeout
    name, release_version = package["name"], package["version"]
    while True:
        try:
            data = lookup(name)
            published = data.get("versions", {}).get(release_version)
            actual = (published or {}).get("dist", {}).get("integrity")
            current = data.get("dist-tags", {}).get(tag)
            if actual and actual != expected:
                raise ValueError(f"Published checksum mismatch for {name}@{release_version}: expected {expected}, got {actual}")
            if actual == expected and current == release_version:
                print(f"Verified public npm archive: {name}@{release_version}", flush=True)
                return
            reason = (f"version {release_version} is not public yet" if not published else
                      "archive integrity is not visible yet" if not actual else
                      f"{tag} is {current!r}, waiting for {release_version}")
        except HTTPError as error:
            if error.code != 429 and error.code < 500:
                raise
            reason = f"registry returned HTTP {error.code}"
        except (URLError, TimeoutError) as error:
            reason = f"registry lookup failed: {error}"
        remaining = deadline - clock()
        if remaining <= 0:
            raise TimeoutError(f"Could not verify {name}@{release_version}: {reason}. "
                               "The upload may still be processing. Retry with --verify-only; do not rebuild or republish.")
        print(f"Waiting for npm: {name}: {reason}", flush=True)
        sleep(min(10, remaining))


def verify_published(release, packages, *, lookup=registry_package):
    for package in packages:
        wait_for_published(package, release.get("npm_tag", "latest"), lookup=lookup)


def validate(artifacts, root=ROOT):
    release = read_release(root)
    lock = json.loads((root / "upstream.lock.json").read_bytes())
    if file_hash(safe_path(root, lock["patch"])).hexdigest() != lock["patch_sha256"]:
        raise ValueError("Source patch checksum differs from upstream.lock.json")
    version(release["version"])
    repository = release.get("repository")
    if not repository:
        raise ValueError("Set release.json repository to the public GitHub owner/repository before publishing")
    if os.environ.get("GITHUB_REPOSITORY", repository).lower() != repository.lower():
        raise ValueError("Package repository differs from the publishing workflow repository")
    sums = list(artifacts.rglob("SHA256SUMS.txt"))
    if len(sums) != 1:
        raise ValueError("Expected exactly one SHA256SUMS.txt")
    folder = sums[0].parent
    expected = {}
    for line in sums[0].read_text(encoding="utf-8").splitlines():
        checksum, name = line.split("  ", 1)
        if (name != Path(name).name or "/" in name or "\\" in name or ":" in name
                or not name.endswith(".tgz") or name in expected):
            raise ValueError("Unsafe or duplicate checksum entry")
        expected[name] = checksum
    paths = sorted(artifacts.rglob("*.tgz"))
    if not paths or {p.name for p in paths} != set(expected) or any(p.parent != folder for p in paths):
        raise ValueError("Archives do not match the checksum manifest")
    packages, platforms, command = [], {}, None
    repo_metadata = {"type": "git", "url": f"git+https://github.com/{repository}.git"}
    for path in paths:
        if path.is_symlink() or file_hash(path).hexdigest() != expected[path.name]:
            raise ValueError(f"Archive checksum mismatch: {path.name}")
        with tarfile.open(path, "r:gz") as tar:
            names = tar.getnames()
            if len(names) != len(set(names)):
                raise ValueError("Duplicate archive members")

            def read(relative):
                member = tar.getmember("package/" + relative)
                if not member.isfile() or member.size > 1024 * 1024:
                    raise ValueError("Invalid package metadata")
                return tar.extractfile(member).read()

            metadata = json.loads(read("package.json"))
            if metadata["version"] != release["version"] or metadata.get("repository") != repo_metadata:
                raise ValueError("Package release version or repository mismatch")
            if metadata["name"] == release["npm_package"]:
                if command is not None:
                    raise ValueError("Duplicate command package")
                command = metadata
                if metadata.get("bin") != {"codux": "cli.mjs"}:
                    raise ValueError("Command entrypoint mismatch")
                for script in ("cli.mjs", "update.mjs"):
                    if read(script) != (root / "npm" / script).read_bytes():
                        raise ValueError("Command scripts differ from the release source")
            else:
                build = json.loads(read("runtime/codux-build.json"))
                target = build["target"]
                key = TARGETS[target]
                platform, arch = key.split("-")
                native_name = f"{release['npm_package']}-{key}"
                if (key in platforms or metadata["name"] != native_name or metadata.get("codux_target") != target
                        or metadata.get("os") != [platform] or metadata.get("cpu") != [arch]):
                    raise ValueError("Native target mismatch or duplicate")
                if any(build.get(k) != v for k, v in {
                    "release_name": release["name"], "release_version": release["version"],
                    "package_version": lock["package_version"], "commit": lock["commit"],
                    "patch_sha256": lock["patch_sha256"], "profile": "release",
                }.items()):
                    raise ValueError("Native build differs from the release inputs")
                if json.loads(read("runtime/codux-npm.json")) != {
                    "package": release["npm_package"], "native_package": native_name,
                    "version": release["version"], "tag": release.get("npm_tag", "latest"),
                }:
                    raise ValueError("Native install metadata mismatch")
                platforms[key] = native_name
        packages.append({"path": path, "name": metadata["name"], "version": metadata["version"]})
    if (command is None or "win32-x64" not in platforms
            or command.get("codux", {}).get("platforms") != platforms
            or command.get("optionalDependencies") != {name: release["version"] for name in platforms.values()}):
        raise ValueError("Command package must reference exactly the verified targets, including Windows x64")
    # Native dependencies must exist before users can see the new command version.
    packages.sort(key=lambda p: (p["name"] == release["npm_package"], p["name"]))
    return release, packages


def publish(release, packages, *, lookup=registry_package, run=subprocess.run, wait=wait_for_published):
    pending = []
    tag = release.get("npm_tag", "latest")
    for package in packages:
        data = lookup(package["name"])
        current = data.get("dist-tags", {}).get(tag)
        if current and version(current) > version(release["version"]):
            raise ValueError(f"Refusing to downgrade {package['name']}@{tag}")
        if package["name"] == release["npm_package"] and current:
            old_targets = data.get("versions", {}).get(current, {}).get("codux", {}).get("platforms", {})
            new_names = {p["name"] for p in packages}
            if any(name not in new_names for name in old_targets.values()):
                raise ValueError("Refusing to drop previously published platforms; build all supported targets")
        existing = data.get("versions", {}).get(package["version"])
        if existing:
            integrity = "sha512-" + base64.b64encode(file_hash(package["path"], "sha512").digest()).decode()
            if existing.get("dist", {}).get("integrity") != integrity:
                raise ValueError(f"Immutable version already contains different bytes: {package['name']}@{package['version']}")
            if current != package["version"]:
                raise ValueError(f"Existing version is not tagged {tag}; inspect npm dist-tags before retrying")
            print(f"Already published identical archive: {package['name']}")
        else:
            pending.append(package)
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm:
        raise ValueError("npm is required")
    # Preflight every archive/version before publishing the first package.
    for package in pending:
        run([npm, "publish", str(package["path"].resolve()), "--access", "public", "--tag", tag,
             "--registry", REGISTRY], check=True)
        # npm can return HTTP 202 before the archive is downloadable. Make each
        # native dependency public before exposing its command package.
        wait(package, tag, lookup=lookup)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--publish", action="store_true")
    mode.add_argument("--verify-only", action="store_true", help="Wait for public versions, tags and checksums without uploading")
    args = parser.parse_args()
    release, packages = validate(args.artifacts)
    for package in packages:
        print(f"{package['name']}@{package['version']}: {package['path']}")
    if args.publish:
        publish(release, packages)
    elif args.verify_only:
        verify_published(release, packages)
    else:
        print("Validated only. Nothing was published.")


if __name__ == "__main__":
    main()
