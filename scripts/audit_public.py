"""Check the exact public source set, English text, and Git ignore rules."""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from public_source import ROOT, source_files


def ignore_text(names):
    directories = {parent.as_posix() for name in names for parent in Path(name).parents
                   if parent.as_posix() != "."}
    lines = ["# Public source allowlist. Everything else stays local.",
             "# Regenerate intentionally with: python scripts/audit_public.py --write-ignore",
             "# Build output, screenshots, credentials, sessions, and Korean notes stay ignored.",
             "*", ""]
    lines += [f"!/{name}/" for name in sorted(directories, key=lambda s: (s.count('/'), s))]
    lines += [f"!/{name}" for name in sorted(names)]
    return "\n".join(lines) + "\n"


def audit(root=ROOT, write_ignore=False):
    root = root.resolve()
    files = source_files(root)
    names = {p.relative_to(root).as_posix() for p in files}
    lock = json.loads((root / "upstream.lock.json").read_text(encoding="utf-8"))
    expected_ignore = ignore_text(names)
    if write_ignore:
        (root / ".gitignore").write_text(expected_ignore, encoding="utf-8")
    if (root / ".gitignore").read_text(encoding="utf-8") != expected_ignore:
        raise ValueError("Public file list changed; review it, then run --write-ignore")
    for path in files:
        content = path.read_text(encoding="utf-8")
        if re.search(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7a3]", content):
            raise ValueError(f"Non-English public text: {path.relative_to(root)}")
        if str(root) in content or root.as_posix() in content:
            raise ValueError(f"Local workspace path in public source: {path.relative_to(root)}")
    # Use a disposable Git database, never initialize or change the working repo.
    with tempfile.TemporaryDirectory(prefix="codux-public-audit-") as directory:
        subprocess.run(["git", "init", "--quiet", directory], check=True)
        command = ["git", "-c", f"safe.directory={root.as_posix()}",
                   f"--git-dir={Path(directory) / '.git'}", f"--work-tree={root}"]
        result = subprocess.run(command + ["ls-files", "--others", "--exclude-standard", "-z"],
                                check=True, capture_output=True)
        actual = {p for p in result.stdout.decode("utf-8").split("\0") if p}
        if actual != names:
            raise ValueError(f"Git/source mismatch: unexpected={sorted(actual-names)}, missing={sorted(names-actual)}")
        if "patch" in lock:
            patch_path = root / lock["patch"]
            raw = subprocess.check_output(command + ["hash-object", "--no-filters", str(patch_path)])
            filtered = subprocess.check_output(command + ["hash-object", f"--path={lock['patch']}", str(patch_path)])
            if raw != filtered:
                raise ValueError("Git would change patch bytes; mark patches as -text in .gitattributes")
            import hashlib
            if hashlib.sha256(patch_path.read_bytes()).hexdigest() != lock["patch_sha256"]:
                raise ValueError("Patch checksum does not match upstream.lock.json")
    if (root / ".git").exists():
        tracked = subprocess.run(["git", "-c", f"safe.directory={root.as_posix()}", "-C", str(root),
                                  "ls-files", "-z"], check=True, capture_output=True)
        extra = set(tracked.stdout.decode("utf-8").split("\0")) - names - {""}
        if extra:
            raise ValueError(f"Tracked files outside public allowlist: {sorted(extra)}")
    print(f"Public audit passed: {len(names)} English source files; patch {lock['patch_version']}.")
    print("Git matches the public source allowlist. Local development data is excluded.")
    return sorted(names)


def stage_source(destination, root=ROOT):
    names = audit(root)
    destination = destination.resolve()
    # A fresh folder avoids overwriting files or mixing in an old export.
    destination.mkdir(parents=True, exist_ok=False)
    for name in names:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / name, target)
    audit(destination)
    print(f"Prepared {len(names)} public files in {destination}. Nothing was uploaded.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-ignore", action="store_true", help="Regenerate .gitignore from the reviewed source set")
    parser.add_argument("--stage", type=Path, help="Copy the audited public files into a new folder")
    args = parser.parse_args()
    try:
        audit(write_ignore=args.write_ignore)
        if args.stage:
            stage_source(args.stage)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"ERROR: {error}\n")
