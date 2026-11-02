"""Package verified native builds for npm; never publishes or changes global installs."""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import tarfile
import tempfile

import manage
import mermaid_runtime
from release_info import read_release, display_version

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    "x86_64-pc-windows-msvc": ("win32", "x64"),
    "x86_64-unknown-linux-gnu": ("linux", "x64"),
    "aarch64-apple-darwin": ("darwin", "arm64"),
    "x86_64-apple-darwin": ("darwin", "x64"),
}
NAME = re.compile(r"(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*")


def json_bytes(value):
    return (json.dumps(value, indent=2) + "\n").encode("utf-8")


def archive(output, entries):
    if output.exists():
        raise ValueError(f"Keep existing artifact: {output.name}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, suffix=".tgz", delete=False) as temporary:
        pending = Path(temporary.name)
    try:
        with tarfile.open(pending, "w:gz", compresslevel=6) as tar:
            for name, value in sorted(entries.items()):
                if PureWindowsPath(name).drive or name.startswith("/") or ".." in PurePosixPath(name).parts or "\\" in name:
                    raise ValueError("Unsafe npm archive path")
                info = tarfile.TarInfo("package/" + name)
                info.mode = 0o755 if name.endswith(".mjs") or "/bin/" in name else 0o644
                if isinstance(value, Path):
                    if value.is_symlink() or not value.is_file():
                        raise ValueError(f"Unsafe package input: {name}")
                    info.size = value.stat().st_size
                    if value.stat().st_mode & 0o111:
                        info.mode = 0o755
                    with value.open("rb") as stream:
                        tar.addfile(info, stream)
                else:
                    info.size = len(value)
                    tar.addfile(info, io.BytesIO(value))
        pending.rename(output)
    finally:
        pending.unlink(missing_ok=True)


def package_name(release, name=None):
    name = name or release.get("npm_package")
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise ValueError("Set npm_package in release.json or pass --name")
    return name


def native(package, output, name=None, *, verify=True):
    release, lock = read_release(), manage.read_lock()
    name = package_name(release, name)
    build = json.loads((package / "codux-build.json").read_text(encoding="utf-8"))
    target = build["target"]
    if target not in TARGETS:
        raise ValueError(f"Unverified npm target: {target}")
    for key, value in {"release_name": release["name"], "release_version": release["version"], "package_version": lock["package_version"],
                       "profile": "release", "patch_sha256": lock["patch_sha256"], "commit": lock["commit"]}.items():
        if build.get(key) != value:
            raise ValueError(f"Build does not match release inputs: {key}")
    platform, arch = TARGETS[target]
    suffix = ".exe" if platform == "win32" else ""
    executable = package / "bin" / (release["name"] + suffix)
    expected = f"codux {display_version(release, lock)}"
    if manage.run(str(executable.resolve()), "--version", capture=True) != expected:
        raise ValueError("Native executable version mismatch")
    if verify:
        mermaid_runtime.validate_mermaid_runtime(package)
        mermaid_runtime.verify_renderers(package, ROOT / ".build")
    native_name = f"{name}-{platform}-{arch}"
    metadata = {"name": native_name, "version": release["version"], "description": f"Codux native runtime for {platform} {arch}",
                "license": "Apache-2.0", "os": [platform], "cpu": [arch],
                "codux_target": target}
    if release.get("repository"):
        metadata["repository"] = {"type": "git", "url": f"git+https://github.com/{release['repository']}.git"}
    if platform == "linux":
        metadata["libc"] = ["glibc"]
    entries = {"package.json": json_bytes(metadata), "LICENSE": ROOT / "LICENSE", "NOTICE": ROOT / "NOTICE"}
    required = [f"bin/codux{suffix}", f"bin/codex-code-mode-host{suffix}", "codex-package.json", "codux-build.json", "migration-checksums.json"]
    for relative in required:
        if not (package / relative).is_file():
            raise ValueError(f"Missing native file: {relative}")
        entries["runtime/" + relative] = package / relative
    for directory in ["codex-path", "codex-resources"]:
        if not (package / directory).is_dir():
            raise ValueError(f"Missing native directory: {directory}")
        for path in (package / directory).rglob("*"):
            if path.is_file():
                if path.is_symlink() or not path.resolve().is_relative_to(package.resolve()):
                    raise ValueError(f"Unsafe native input: {path.name}")
                # npm is the only updater for npm-managed installations.
                if path.name == "codux-update.ps1":
                    continue
                entries["runtime/" + path.relative_to(package).as_posix()] = path
    upstream = json.loads((package / "codex-package.json").read_text(encoding="utf-8"))
    upstream.update(version=release["version"], entrypoint=f"bin/codux{suffix}")
    entries["runtime/codex-package.json"] = json_bytes(upstream)
    entries["runtime/release.json"] = json_bytes({**release, "target": target})
    entries["runtime/codux-npm.json"] = json_bytes({"package": name, "native_package": native_name,
        "version": release["version"], "tag": release.get("npm_tag", "latest")})
    entries["runtime/codex-resources/codux-npm-update.mjs"] = ROOT / "npm/update.mjs"
    filename = native_name.removeprefix("@").replace("/", "-") + "-" + release["version"] + ".tgz"
    destination = output / filename
    archive(destination, entries)
    print(f"Prepared npm native package: {destination}")
    return destination


def launcher(natives, output, name=None):
    release, lock = read_release(), manage.read_lock()
    name = package_name(release, name)
    platforms = {}
    for file in natives:
        with tarfile.open(file, "r:gz") as tar:
            def read(relative):
                member = tar.getmember("package/" + relative)
                if not member.isfile() or member.size > 1024 * 1024:
                    raise ValueError("Invalid native metadata")
                return json.load(tar.extractfile(member))
            metadata = read("package.json")
            build = read("runtime/codux-build.json")
            install = read("runtime/codux-npm.json")
        platform, arch = TARGETS[build["target"]]
        key = f"{platform}-{arch}"
        expected = f"{name}-{key}"
        if (metadata["name"] != expected or metadata["version"] != release["version"]
                or metadata.get("os") != [platform] or metadata.get("cpu") != [arch]
                or install != {"package": name, "native_package": expected, "version": release["version"],
                               "tag": release.get("npm_tag", "latest")}):
            raise ValueError("Native npm package name/version mismatch")
        if (any(build.get(k) != v for k, v in {"patch_sha256": lock["patch_sha256"], "commit": lock["commit"],
                "profile": "release", "release_version": release["version"]}.items()) or key in platforms):
            raise ValueError("Native package has a different patch, profile, or duplicated target")
        platforms[key] = expected
    if not platforms:
        raise ValueError("Supply at least one verified native npm archive")
    metadata = {"name": name, "version": release["version"], "description": "Customizable conversation UI for Codex CLI",
                "type": "module", "bin": {"codux": "cli.mjs"}, "engines": {"node": ">=22"}, "license": "Apache-2.0",
                "optionalDependencies": {native: release["version"] for native in platforms.values()},
                "codux": {"platforms": platforms}}
    if release.get("repository"):
        metadata["repository"] = {"type": "git", "url": f"git+https://github.com/{release['repository']}.git"}
    entries = {"package.json": json_bytes(metadata), "cli.mjs": ROOT / "npm/cli.mjs", "update.mjs": ROOT / "npm/update.mjs",
               "LICENSE": ROOT / "LICENSE", "NOTICE": ROOT / "NOTICE",
               "README.md": f"# Codux\n\nInstall: `npm install -g {name}`\n\nRun: `codux`\n\nUpdate: `codux update` or `npm install -g {name}@{release.get('npm_tag', 'latest')}`\n\nIncludes prebuilt native binaries. No Rust compiler is needed. Node.js 22+ is required; Mermaid images also require Chrome or Edge.\n".encode()}
    destination = output / (name.removeprefix("@").replace("/", "-") + "-" + release["version"] + ".tgz")
    archive(destination, entries)
    print(f"Prepared npm command package: {destination}")
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, action="append", default=[])
    parser.add_argument("--assemble", type=Path, nargs="*", default=[])
    parser.add_argument("--native-only", action="store_true")
    parser.add_argument("--name")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--smoke", action="store_true", help="Install and run from an isolated localhost npm registry")
    args = parser.parse_args()
    output = args.output or ROOT / "dist/npm" / read_release()["version"]
    if args.smoke and args.native_only:
        parser.error("--smoke requires a command package")
    natives = [native(package.resolve(), output, args.name) for package in args.package]
    for source in args.assemble:
        destination = output / source.name
        if source.resolve() != destination.resolve():
            if destination.exists():
                raise ValueError(f"Keep existing artifact: {destination}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        natives.append(destination)
    paths = natives if args.native_only else natives + [launcher(natives, output, args.name)]
    sums = []
    for file in paths:
        with file.open("rb") as stream:
            sums.append(f"{hashlib.file_digest(stream, 'sha256').hexdigest()}  {file.name}")
    (output / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8")
    if args.smoke:
        from npm_smoke import smoke
        smoke(paths)
    print("Nothing was published. Publish native packages first, then the command package.")


if __name__ == "__main__":
    main()
