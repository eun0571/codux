"""Port the existing patch to an official stable tag without resolving conflicts."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = "https://github.com/openai/codex.git"
STABLE = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")


def version(value):
    if not isinstance(value, str) or not STABLE.fullmatch(value):
        raise ValueError(f"Expected a stable version, got {value!r}")
    return tuple(map(int, value.split(".")))


def git(directory, *args):
    result = subprocess.run(["git", "-c", "core.autocrlf=false", "-c", "core.longpaths=true", "-C", str(directory), *args],
                            capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip())
    return result.stdout.decode("utf-8").strip()


def safe_path(root, name):
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name
            or path.as_posix() != name):
        raise ValueError(f"Unsafe path: {name}")
    result = root / name
    if result.is_symlink() or not result.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Unsafe path: {name}")
    return result


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded_json(value):
    return (json.dumps(value, indent=2) + "\n").encode("utf-8")


def patch_for(before, after):
    parts = []
    for name, updated in after.items():
        previous = before[name]
        if previous == updated:
            continue
        parts.append(f"diff --git a/{name} b/{name}\n")
        if previous is None:
            parts.append("new file mode 100644\n")
        for line in difflib.unified_diff(
            (previous or b"").decode("utf-8").splitlines(keepends=True),
            updated.decode("utf-8").splitlines(keepends=True),
            fromfile=f"a/{name}" if previous is not None else "/dev/null", tofile=f"b/{name}",
        ):
            parts.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
    return "".join(parts).encode("utf-8")


def release_lockfile(data, next_version):
    """Refresh only local workspace versions; preserve all external dependency pins."""
    version(next_version)
    parts = data.decode("utf-8").split("[[package]]")
    for index, part in enumerate(parts[1:], 1):
        package = tomllib.loads(part)
        if "source" not in package and package["version"] == "0.0.0":
            parts[index] = part.replace('version = "0.0.0"', f'version = "{next_version}"', 1)
    return "[[package]]".join(parts).encode("utf-8")


def prepare(root, tag, repository=None, *, fetch_repository=UPSTREAM):
    """Only commit local inputs after a complete apply/reverse/reapply verification.

    fetch_repository is injectable for offline fixture tests; the CLI always uses OpenAI.
    The candidate checkout is retained under .build for inspecting failures.
    """
    root = root.resolve()
    lock_path, release_path = root / "upstream.lock.json", root / "release.json"
    lock = json.loads(lock_path.read_bytes())
    release = json.loads(release_path.read_bytes())
    if lock["repository"] != UPSTREAM or not tag.startswith("rust-v"):
        raise ValueError("Expected an official Codex stable tag")
    next_version = tag.removeprefix("rust-v")
    if version(next_version) <= version(lock["version"]):
        raise ValueError("Candidate must be newer than the pinned Codex version")
    major, minor, patch = version(release["version"])
    if repository is not None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("Expected a GitHub owner/repository")
        if release.get("repository") not in (None, repository):
            raise ValueError("release.json points to a different GitHub repository")
        release["repository"] = repository
    patch_path = safe_path(root, lock["patch"])
    if not patch_path.is_relative_to(root / "patches") or digest(patch_path.read_bytes()) != lock["patch_sha256"]:
        raise ValueError("Invalid current patch or checksum")
    build = root / ".build"
    build.mkdir(exist_ok=True)
    candidate = Path(tempfile.mkdtemp(prefix="upstream-port-", dir=build))
    print(f"Candidate checkout: {candidate}", flush=True)
    git(candidate, "init")
    git(candidate, "fetch", "--depth=1", fetch_repository, f"refs/tags/{tag}")
    commit = git(candidate, "rev-parse", "FETCH_HEAD^{commit}")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Expected a full upstream commit SHA")
    git(candidate, "checkout", "--detach", commit)
    paths = {name: safe_path(candidate, name) for name in lock["patched_sha256"]}
    before = {name: path.read_bytes() if path.exists() else None for name, path in paths.items()}
    # Cargo.lock release versions belong to this candidate, not the previous tag.
    # Apply the UI patch strictly and regenerate just that mechanical lock change.
    apply_args = ["--exclude=codex-rs/Cargo.lock"] if "codex-rs/Cargo.lock" in before else []
    git(candidate, "apply", *apply_args, "--check", str(patch_path))
    git(candidate, "apply", *apply_args, str(patch_path))
    if "codex-rs/Cargo.lock" in before:
        paths["codex-rs/Cargo.lock"].write_bytes(release_lockfile(before["codex-rs/Cargo.lock"], next_version))
    for name, path in paths.items():
        if name.endswith(".rs"):
            path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n"))
    after = {name: path.read_bytes() for name, path in paths.items()}
    toolchain = tomllib.loads((candidate / "codex-rs/rust-toolchain.toml").read_text(encoding="utf-8"))["toolchain"]["channel"]
    version(toolchain)
    updated_patch = patch_for(before, after)
    regenerated = candidate.parent / (candidate.name + ".patch")
    regenerated.write_bytes(updated_patch)
    git(candidate, "apply", "--reverse", str(regenerated))
    for name, path in paths.items():
        if (path.read_bytes() if path.exists() else None) != before[name]:
            raise ValueError(f"Regenerated patch does not restore upstream: {name}")
    if git(candidate, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("Patch changed files outside the tracked patch inputs")
    git(candidate, "apply", str(regenerated))
    if any(path.read_bytes() != after[name] for name, path in paths.items()):
        raise ValueError("Regenerated patch changed the candidate contents")
    revision = lock["patch_version"] + 1
    lock.update(version=next_version, tag=tag, commit=commit, rust_toolchain=toolchain,
                source_directory=f"upstream-{next_version}", patch_version=revision,
                package_version=f"{next_version}-codux.{revision}", patch_sha256=digest(updated_patch),
                source_sha256={name: digest(data) for name, data in before.items() if data is not None},
                patched_sha256={name: digest(data) for name, data in after.items()})
    release["version"] = f"{major}.{minor}.{patch + 1}"
    writes = {patch_path: updated_patch, lock_path: encoded_json(lock), release_path: encoded_json(release)}
    files = [lock["patch"], "upstream.lock.json", "release.json"]
    catalog_path = root / "playground/catalog.json"
    if catalog_path.exists():
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        native_hashes = {name: lock["patched_sha256"].get(name)
                         for name in catalog["native_sha256"]}
        if (native_hashes != catalog["native_sha256"]
                or digest((root / "playground/palettes.js").read_bytes()) != catalog["catalog_sha256"]):
            raise ValueError("Playground UI inputs changed; export the catalog from the candidate's native tests before publishing")
        # The catalog is still byte-for-byte backed by the same native UI sources.
        # Advance its provenance with the pin so the Pages verification remains valid.
        catalog["upstream_commit"] = commit
        writes[catalog_path] = encoded_json(catalog)
        files.append("playground/catalog.json")
    previous = {path: path.read_bytes() for path in writes}
    try:
        for path, data in writes.items():
            path.write_bytes(data)
    except Exception:
        for path, data in previous.items():
            path.write_bytes(data)
        raise
    return {"tag": tag, "commit": commit, "codux_version": release["version"],
            "patch_version": revision, "checkout": str(candidate),
            "files": files}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", help="Official stable tag, for example rust-v0.164.0")
    parser.add_argument("--repository", help="GitHub owner/repository for npm metadata")
    args = parser.parse_args()
    print(json.dumps(prepare(ROOT, args.tag, args.repository), indent=2))


if __name__ == "__main__":
    main()
