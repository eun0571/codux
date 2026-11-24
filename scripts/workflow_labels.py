"""Keep Actions run titles tied to the release files in the same commit."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
# GitHub evaluates run-name before checkout; it cannot read files or job outputs.
# Commit these labels with the version inputs instead of relying on commit prose
# or mutable repository variables that can describe a different release.
PREFIXES = {
    "publish-npm.yml": "${{ inputs.repackage_run && 'npm repackage' || inputs.resume_run && 'npm recheck' || 'npm release' }}",
    "playground.yml": "${{ github.event_name == 'pull_request' && format('Playground check PR #{0}', github.event.pull_request.number) || github.ref_name == github.event.repository.default_branch && 'Playground deploy' || 'Playground check' }}",
    "track-upstream.yml": "Maintenance | current",
    "verify-pr.yml": "PR #${{ github.event.pull_request.number }} check (not published)",
    "native-build.yml": "Native ${{ inputs.platform || 'windows' }} check (not published)",
}


def identity(root=ROOT, release=None, lock=None):
    release = release if release is not None else json.loads((root / "release.json").read_bytes())
    lock = lock if lock is not None else json.loads((root / "upstream.lock.json").read_bytes())
    for value in (release["version"], lock["version"]):
        if not isinstance(value, str) or not re.fullmatch(r"\d+\.\d+\.\d+(?:-[a-z0-9.-]+)?", value):
            raise ValueError("Invalid version for Actions label")
    patch = lock["patch_version"]
    if type(patch) is not int or patch < 0:
        raise ValueError("Invalid patch revision for Actions label")
    return {"version": release["version"], "upstream": lock["version"], "patch": patch,
            "label": f"Codux {release['version']} | Codex {lock['version']} | patch {patch}"}


def updates(root=ROOT, release=None, lock=None):
    directory = root / ".github/workflows"
    if not directory.exists():
        return {}  # Minimal patch-preparation fixtures do not contain workflows.
    label = identity(root, release, lock)["label"]
    changed = {}
    for name, prefix in PREFIXES.items():
        path = directory / name
        text = path.read_text(encoding="utf-8")
        suffix = ("${{ inputs.repackage_run && format(' | repackage run {0}', inputs.repackage_run) || "
                  "inputs.resume_run && format(' | reuse run {0}', inputs.resume_run) || '' }}") if name == "publish-npm.yml" else ""
        line = "run-name: " + json.dumps(f"{prefix} | {label}{suffix}")
        if len(re.findall(r"^run-name:.*$", text, re.M)) != 1:
            raise ValueError(f"Expected one single-line run-name in {name}")
        updated = re.sub(r"^run-name:.*$", lambda _: line, text, flags=re.M)
        if updated != text:
            changed[path] = updated.encode("utf-8")
    return changed


def sync(root=ROOT, *, write=False):
    changed = updates(root)
    if changed and not write:
        names = ", ".join(path.name for path in changed)
        raise ValueError(f"Actions version labels are stale ({names}); run python scripts/workflow_labels.py --write")
    for path, data in changed.items():
        path.write_bytes(data)
    return changed


def describe(root=ROOT, purpose="Workflow inputs", *, outputs=True):
    value = identity(root)
    try:
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        sha = ""
    value["source_sha"] = sha
    if outputs and os.environ.get("GITHUB_OUTPUT"):
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
            for key, item in value.items():
                stream.write(f"{key}={item}\n")
    source = f"`{sha}`" if sha else "Local working copy"
    text = (f"## {purpose}\n\n"
            f"| Input | Value |\n| --- | --- |\n| Codux | **{value['version']}** |\n"
            f"| Codex source | {value['upstream']} |\n| UI patch | {value['patch']} |\n"
            f"| Source commit | {source} |\n")
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as stream:
            stream.write(text + "\n")
    return value


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--write", action="store_true")
    group.add_argument("--describe", action="store_true")
    parser.add_argument("--purpose", default="Workflow inputs")
    args = parser.parse_args()
    if args.describe:
        describe(purpose=args.purpose)
    else:
        changed = sync(write=args.write)
        print(f"Actions labels match {identity()['label']} ({len(changed)} updated).")
