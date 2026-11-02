"""Public version is independent of the pinned Codex and internal patch revision."""
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
BUILD_TARGETS = {"x86_64-pc-windows-msvc", "x86_64-unknown-linux-gnu", "aarch64-apple-darwin", "x86_64-apple-darwin"}

def read_release(root: Path = ROOT) -> dict:
    value = json.loads((root / "release.json").read_text(encoding="utf-8"))
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,39}", value["name"]):
        raise ValueError("Invalid release command name")
    if not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[a-z0-9.-]+)?", value["version"]):
        raise ValueError("Use a release version such as 0.1.0")
    if value["target"] not in BUILD_TARGETS:
        raise ValueError("Unknown release target")
    if "npm_package" in value and not re.fullmatch(r"(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*", value["npm_package"]):
        raise ValueError("Invalid npm package name")
    if "npm_tag" in value and not re.fullmatch(r"[a-z][a-z0-9-]*", value["npm_tag"]):
        raise ValueError("Invalid npm dist-tag")
    repository = value.get("repository")
    if repository is not None and (not isinstance(repository, str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)):
        raise ValueError("Use a repository name such as owner/project, or null")
    return value

def display_version(release: dict, lock: dict) -> str:
    return f"{release['version']} (Codex {lock['version']}; patch {lock['patch_version']})"

def package_url(release: dict) -> str:
    return f"https://www.npmjs.com/package/{release['npm_package']}"
