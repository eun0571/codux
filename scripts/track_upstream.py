"""Detect a stable Codex release and create an update PR using the GitHub token."""
import json
import os
from pathlib import Path
import subprocess

from prepare_upstream import ROOT, encoded_json, git, prepare, version


def api(endpoint, data=None):
    args = ["gh", "api", endpoint]
    if data is not None:
        args.extend(["--method", "POST", "--input", "-"])
    result = subprocess.run(args, input=encoded_json(data) if data is not None else None,
                            capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip())
    return json.loads(result.stdout)


def track(root=ROOT):
    repository = os.environ["GITHUB_REPOSITORY"]
    upstream = api("repos/openai/codex/releases/latest")
    tag = upstream["tag_name"]
    if upstream["draft"] or upstream["prerelease"] or not tag.startswith("rust-v"):
        raise ValueError("Latest upstream release is not an official stable Codex tag")
    lock = json.loads((root / "upstream.lock.json").read_bytes())
    candidate = tag.removeprefix("rust-v")
    if version(candidate) <= version(lock["version"]):
        return {"changed": False, "reason": "Pinned Codex is current"}
    opened = api(f"repos/{repository}/pulls?state=open&per_page=100")
    for pr in opened:
        if pr["head"]["ref"].startswith("automation/codex-") and pr["head"]["repo"]["full_name"] == repository:
            return {"changed": False, "reason": f"Review the existing upstream PR first: {pr['html_url']}"}
    base = git(root, "rev-parse", "HEAD")
    # Include the base commit so a changed patch or release version gets a fresh PR.
    branch = f"automation/codex-{candidate}-{base[:12]}"
    existing = api(f"repos/{repository}/git/matching-refs/heads/{branch}")
    if any(item["ref"] == "refs/heads/" + branch for item in existing):
        return {"changed": False, "reason": f"Candidate branch already exists: {branch}"}
    info = api(f"repos/{repository}")
    default = info["default_branch"]
    current = api(f"repos/{repository}/commits/{default}")
    if current["sha"] != base:
        raise ValueError("Default branch changed; rerun the tracker on its current head")
    result = prepare(root, tag, repository)
    tree = api(f"repos/{repository}/git/trees", {
        "base_tree": current["commit"]["tree"]["sha"],
        "tree": [{"path": name, "mode": "100644", "type": "blob",
                  "content": (root / name).read_bytes().decode("utf-8")} for name in result["files"]],
    })
    commit = api(f"repos/{repository}/git/commits", {
        "message": f"Update Codex to {candidate}", "tree": tree["sha"], "parents": [base],
    })
    api(f"repos/{repository}/git/refs", {"ref": "refs/heads/" + branch, "sha": commit["sha"]})
    run_url = f"https://github.com/{repository}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    body = (f"Updates the pinned Codex source to `{tag}` (`{result['commit']}`) and prepares "
            f"Codux `{result['codux_version']}`. The existing patch applied without conflict; "
            "its source and output checksums have been regenerated and verified.\n\n"
            f"[Windows regression tests, release build, and npm installation check]({run_url}) "
            "run against this PR's exact commit. Review that result and test the UI before merging. "
            "Merging a release version change starts the npm release workflow when publication is enabled.")
    pr = api(f"repos/{repository}/pulls", {
        "title": f"Update Codex to {candidate}", "head": branch, "base": default, "body": body,
    })
    return {**result, "changed": True, "head_sha": commit["sha"], "pr_number": pr["number"],
            "pr_url": pr["html_url"], "branch": branch}


def main():
    from release_workflow import summary

    report = ROOT / ".build/upstream-report.json"
    report.parent.mkdir(exist_ok=True)
    try:
        result = track()
    except Exception as error:
        report.write_bytes(encoded_json({"changed": False, "error": str(error)}))
        summary("## Codex update check failed\n\nNo new release was published. "
                "Inspect the failed step and upstream-report artifact for the conflict or error.")
        raise
    lock = json.loads((ROOT / "upstream.lock.json").read_bytes())
    release = json.loads((ROOT / "release.json").read_bytes())
    result.setdefault("codux_version", release["version"])
    result.setdefault("upstream_version", lock["version"])
    report.write_bytes(encoded_json(result))
    if os.environ.get("GITHUB_OUTPUT"):
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
            for key in ("changed", "head_sha", "pr_number", "codux_version", "upstream_version"):
                value = result.get(key, "")
                stream.write(f"{key}={str(value).lower() if isinstance(value, bool) else value}\n")
    if result["changed"]:
        summary(f"## Update candidate: Codux {result['codux_version']} / Codex {result['upstream_version']}\n\n"
                f"[Review the update PR]({result['pr_url']}). The patch applies; Windows verification runs next. "
                "This candidate is **not published**. Review and merge after verification passes.")
    else:
        summary(f"## Codex update check\n\nPinned source: Codex {lock['version']} / Codux {release['version']}.\n\n"
                f"{result.get('reason', 'No update prepared')}\n\nNo build or publication was started by this check.")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
