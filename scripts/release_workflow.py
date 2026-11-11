"""Select release inputs and expose publication state without masking real failures."""
import argparse
import base64
import json
import os
from pathlib import Path
import subprocess

from prepare_upstream import ROOT, version


def api(endpoint, data=None):
    args = ["gh", "api", endpoint]
    if data is not None:
        args += ["--method", "POST", "--input", "-"]
    result = subprocess.run(args, input=json.dumps(data) if data is not None else None,
                            capture_output=True, text=True, check=True)
    return json.loads(result.stdout) if result.stdout.strip() else None


def output(values):
    if os.environ.get("GITHUB_OUTPUT"):
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
            for key, value in values.items():
                stream.write(f"{key}={str(value).lower() if isinstance(value, bool) else value}\n")


def summary(text):
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as stream:
            stream.write(text + "\n")


def artifact(repository, run_id, name):
    records = api(f"repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100")["artifacts"]
    return next((item for item in records if item["name"] == name and not item["expired"]), None)


def select(root=ROOT):
    release = json.loads((root / "release.json").read_bytes())
    lock = json.loads((root / "upstream.lock.json").read_bytes())
    repository = os.environ["GITHUB_REPOSITORY"]
    if release.get("repository") != repository:
        raise ValueError("Release repository differs from the workflow repository")
    current = version(release["version"])
    resume = os.environ.get("RESUME_RUN", "").strip()
    source_sha = os.environ["GITHUB_SHA"]
    if os.environ["GITHUB_EVENT_NAME"] == "workflow_dispatch":
        if os.environ.get("REQUESTED_VERSION") != release["version"]:
            raise ValueError("Requested version differs from the checked-out source")
        changed = True
    else:
        before = os.environ.get("BEFORE", "")
        if not before or set(before) == {"0"}:
            raise ValueError("First publication must be started manually")
        old = json.loads(subprocess.check_output(["git", "show", before + ":release.json"], cwd=root))
        previous = version(old["version"])
        if current < previous:
            raise ValueError("Release version must not decrease")
        changed = current > previous
    receipt_run = ""
    if resume:
        if not resume.isdecimal() or int(resume) <= 0:
            raise ValueError("Resume run must be a positive workflow run ID")
        run = api(f"repos/{repository}/actions/runs/{resume}")
        if (run["path"] != ".github/workflows/publish-npm.yml" or run["status"] != "completed"
                or run["head_branch"] != os.environ["DEFAULT_BRANCH"]
                or run["head_repository"]["full_name"] != repository):
            raise ValueError("Resume requires a completed release run from this repository's default branch")
        source_sha = run["head_sha"]
        # A workflow-only change is safe; changed build inputs require a new release.
        for name in ("release.json", "upstream.lock.json"):
            record = api(f"repos/{repository}/contents/{name}?ref={source_sha}")
            if json.loads(base64.b64decode(record["content"])) != json.loads((root / name).read_bytes()):
                raise ValueError("Resume release inputs differ from the current source")
        if not artifact(repository, resume, "npm-release-candidate"):
            raise ValueError("Verified release artifacts are missing or expired; do not rebuild a partly published version")
        if not artifact(repository, resume, "npm-publication-state"):
            raise ValueError("Upload receipt missing; inspect the legacy run before retrying publication")
        receipt_run = resume
    elif int(os.environ.get("GITHUB_RUN_ATTEMPT", "1")) > 1:
        if artifact(repository, os.environ["GITHUB_RUN_ID"], "npm-publication-state"):
            receipt_run = os.environ["GITHUB_RUN_ID"]
    result = {"publish": changed, "version": release["version"], "upstream": lock["version"],
              "artifact_run": resume or os.environ["GITHUB_RUN_ID"], "receipt_run": receipt_run,
              "source_sha": source_sha, "resume": bool(resume)}
    output(result)
    summary(f"## Codux {release['version']} / Codex {lock['version']}\n\n"
            f"{'Resume verified archives; no rebuild.' if resume else 'Build and verify before publishing.'}\n\n"
            "The release is complete only when the publication summary says **Published**.")
    return result


def report(root=ROOT):
    release = json.loads((root / "release.json").read_bytes())
    lock = json.loads((root / "upstream.lock.json").read_bytes())
    receipt = root / ".build/npm-state/publication.json"
    result = json.loads(receipt.read_bytes()) if receipt.exists() else {}
    # Job failure (including a failed state upload) always wins over an earlier receipt.
    job = os.environ.get("PUBLISH_RESULT", "failure")
    state = result.get("status") if job == "success" else "failed"
    if result and (result.get("repository") != release["repository"] or result.get("version") != release["version"]):
        state = "failed"
        result["detail"] = "Publication receipt does not match the current release."
    if state not in ("pending", "published"):
        state = "failed"
    label = {"pending": "Waiting for npm - NOT published", "published": "Published",
             "failed": "Failed - inspect the failed job"}[state]
    description = {"pending": "Waiting for npm; accepted uploads retained for recheck",
                   "published": "Published; all npm archives and tags verified",
                   "failed": "Build or publication failed; inspect the release summary"}[state]
    repository = os.environ["GITHUB_REPOSITORY"]
    run_url = f"https://github.com/{repository}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    context = f"Codux / npm {release['version']}"
    for sha in dict.fromkeys((os.environ["SOURCE_SHA"], os.environ["GITHUB_SHA"])):
        api(f"repos/{repository}/statuses/{sha}", {
            "state": {"pending": "pending", "published": "success", "failed": "failure"}[state],
            "context": context, "description": description, "target_url": run_url,
        })
    detail = result.get("detail", "See the failed build or publication step.")
    summary(f"## Codux {release['version']}: {label}\n\n"
            f"| Item | Result |\n| --- | --- |\n| Codex source | {lock['version']} |\n"
            f"| npm publication | **{label}** |\n| Build | {'Verified artifacts' if job == 'success' else 'See job results'} |\n\n"
            f"{detail}\n\n"
            + ("The workflow handled the delay successfully; that does **not** mean the release is published. "
               "The npm commit status remains pending. The six-hour maintenance check will resume these exact archives. "
               f"To recheck sooner, run **1. Release to npm** with version `{release['version']}` and "
               f"resume_run `{os.environ['GITHUB_RUN_ID']}`.\n" if state == "pending" else ""))
    return state


def retry(root=ROOT):
    """Reuse the existing maintenance schedule; never retry real publication failures."""
    release = json.loads((root / "release.json").read_bytes())
    repository = os.environ["GITHUB_REPOSITORY"]
    branch = os.environ["DEFAULT_BRANCH"]
    records = api(f"repos/{repository}/actions/workflows/publish-npm.yml/runs?branch={branch}&per_page=30")["workflow_runs"]
    if any(run["status"] != "completed" for run in records):
        summary("## npm release\n\nA release is already running or queued. No additional run was started.")
        return False
    context = f"Codux / npm {release['version']}"
    seen = set()
    for run in records:
        if run["head_sha"] in seen:
            continue
        seen.add(run["head_sha"])
        statuses = api(f"repos/{repository}/commits/{run['head_sha']}/status?per_page=100")["statuses"]
        status = next((s for s in statuses if s["context"] == context), None)
        if status is None:
            continue
        if status["state"] != "pending" or not status["description"].startswith("Waiting for npm;"):
            summary(f"## npm release\n\n{status['description']}\n\n[Release details]({status['target_url']})")
            return False
        receipt_run = status["target_url"].removeprefix(f"https://github.com/{repository}/actions/runs/")
        if not receipt_run.isdecimal() or not artifact(repository, receipt_run, "npm-publication-state"):
            raise ValueError("Pending publication receipt is missing; manual inspection required")
        api(f"repos/{repository}/actions/workflows/publish-npm.yml/dispatches", {
            "ref": branch, "inputs": {"version": release["version"], "resume_run": receipt_run},
        })
        summary(f"## npm release\n\nRechecking Codux {release['version']} using the accepted upload receipt "
                f"from run {receipt_run}. No rebuild or duplicate upload was requested.")
        return True
    summary("## npm release\n\nNo pending npm receipt for the current version. No release was started.")
    return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("select", "report", "retry"))
    action = parser.parse_args().action
    result = globals()[action]()
    if action == "report" and result == "failed":
        raise SystemExit(1)
