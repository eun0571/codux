"""Recover an unpublished Windows release by removing only the duplicate executor."""
import argparse
import base64
import copy
import hashlib
import io
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import queue
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time

from package_npm import check_archive_size, json_bytes
from prepare_upstream import version
from publish_npm import PublicationState, file_hash, registry_package, validate

EXECUTOR = "package/runtime/bin/codex-exec-server.exe"
MANIFEST = "package/runtime/codex-package.json"


def check_executor(executable, env):
    """Run a real child through the main CLI's stdio executor, without a daemon."""
    messages = queue.Queue()
    marker = "codux-integrated-executor-ok"
    with tempfile.TemporaryFile(mode="w+b") as errors:
        process = subprocess.Popen([str(executable), "exec-server", "--listen", "stdio"],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors,
                                   env=env, text=True, encoding="utf-8")

        def read():
            try:
                for line in process.stdout:
                    messages.put(json.loads(line))
            except Exception as error:
                messages.put(error)
            finally:
                messages.put(None)

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        deadline = time.monotonic() + 60

        def receive():
            try:
                message = messages.get(timeout=max(0.01, deadline - time.monotonic()))
            except queue.Empty:
                raise RuntimeError("Integrated executor smoke check timed out") from None
            if not isinstance(message, dict) or "error" in message:
                raise RuntimeError(f"Integrated executor failed: {message}")
            return message

        def send(method, params, request_id=None):
            message = {"jsonrpc": "2.0", "method": method, "params": params}
            if request_id is not None:
                message["id"] = request_id
            process.stdin.write(json.dumps(message) + "\n")
            process.stdin.flush()

        try:
            send("initialize", {"clientName": "codux-package-check"}, 1)
            while True:
                message = receive()
                if message.get("id") == 1:
                    if not message.get("result", {}).get("sessionId"):
                        raise RuntimeError("Executor did not initialize a session")
                    break
            send("initialized", {})
            send("process/start", {"processId": "package-check", "argv": [sys.executable, "-I", "-c",
                 f"print({marker!r})"], "cwd": executable.parent.resolve().as_uri(), "env": env,
                 "tty": False, "pipeStdin": False}, 2)
            output = bytearray()
            started, exited = False, False
            while not (started and exited):
                message = receive()
                if message.get("id") == 2:
                    started = message.get("result", {}).get("processId") == "package-check"
                    if not started:
                        raise RuntimeError("Executor did not start the smoke process")
                params = message.get("params", {})
                if params.get("processId") != "package-check":
                    continue
                if message.get("method") == "process/output":
                    output.extend(base64.b64decode(params["chunk"], validate=True))
                if message.get("method") == "process/exited":
                    if params.get("exitCode") != 0:
                        raise RuntimeError(f"Executor child failed: {params}")
                    exited = True
            if marker.encode() not in output:
                raise RuntimeError("Executor child output was missing")
            print("PASS: codux exec-server initialized and executed a child without the standalone helper.", flush=True)
        finally:
            process.stdin.close()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            reader.join(timeout=5)
            process.stdout.close()
            if process.returncode:
                errors.seek(0)
                print(errors.read(8192).decode("utf-8", errors="replace"), file=sys.stderr)


def inventory(path):
    result = {}
    with tarfile.open(path, "r:gz") as tar:
        for member in tar:
            name = member.name
            if (not member.isfile() or name in result or not name.startswith("package/")
                    or ".." in PurePosixPath(name).parts or "\\" in name or PureWindowsPath(name).drive):
                raise ValueError(f"Unsafe archive member: {name}")
            with tar.extractfile(member) as stream:
                result[name] = (member.size, member.mode, hashlib.file_digest(stream, "sha256").hexdigest())
    return result


def repack_native(source, destination):
    before = inventory(source)
    if EXECUTOR not in before or MANIFEST not in before:
        raise ValueError("Expected the original Windows package with a standalone executor")
    if destination.exists():
        raise ValueError("Refusing to overwrite an archive")
    with tarfile.open(source, "r:gz") as original:
        old_manifest = json.load(original.extractfile(MANIFEST))
        if old_manifest.get("execServer") != "bin/codex-exec-server.exe":
            raise ValueError("Unexpected standalone executor manifest path")
        manifest = {key: value for key, value in old_manifest.items() if key != "execServer"}
        with tarfile.open(destination, "w:gz", compresslevel=6) as updated:
            for member in original:
                if member.name == EXECUTOR:
                    continue
                if member.name == MANIFEST:
                    data = json_bytes(manifest)
                    member = copy.copy(member)
                    member.size = len(data)
                    updated.addfile(member, io.BytesIO(data))
                else:
                    with original.extractfile(member) as stream:
                        updated.addfile(member, stream)
    after = inventory(destination)
    if set(after) != set(before) - {EXECUTOR} or any(
            before[name] != record for name, record in after.items() if name != MANIFEST):
        raise ValueError("Repackaging changed a retained file")
    with tarfile.open(destination, "r:gz") as tar:
        if json.load(tar.extractfile(MANIFEST)) != manifest:
            raise ValueError("Repackaging changed unexpected manifest fields")
    check_archive_size(destination)
    return {"archive": destination.name, "old_bytes": source.stat().st_size,
            "new_bytes": destination.stat().st_size, "unchanged_files": len(after) - 1,
            "old_sha256": file_hash(source).hexdigest(), "new_sha256": file_hash(destination).hexdigest()}


def require_unpublished(receipt, release, packages, *, lookup=registry_package):
    if not receipt.is_file():
        raise ValueError("The original upload receipt is required")
    state = PublicationState(receipt, release, packages)
    if state.data.get("status") != "failed" or state.data["accepted"]:
        raise ValueError("Only a failed release with zero accepted uploads can be repackaged")
    for package in packages:
        data = lookup(package["name"])
        if package["version"] in data.get("versions", {}):
            raise ValueError(f"Cannot repackage a public version: {package['name']}")
        current = data.get("dist-tags", {}).get(release.get("npm_tag", "latest"))
        if current and version(current) > version(release["version"]):
            raise ValueError("A newer release is already public")


def repackage(artifacts, receipt, output):
    release, packages = validate(artifacts, allow_oversize=True)
    if {p["name"] for p in packages} != {release["npm_package"], release["npm_package"] + "-win32-x64"}:
        raise ValueError("Recovery currently supports the verified Windows release only")
    require_unpublished(receipt, release, packages)
    output.mkdir(parents=True, exist_ok=False)
    report = {"version": release["version"], "operation": "remove duplicate Windows executor", "archives": []}
    archives = []
    for package in packages:
        source = package["path"]
        destination = output / source.name
        if package["name"] == release["npm_package"]:
            shutil.copyfile(source, destination)
            if file_hash(source).digest() != file_hash(destination).digest():
                raise ValueError("Command archive changed")
        else:
            report["archives"].append(repack_native(source, destination))
        archives.append(destination)
    (output / "SHA256SUMS.txt").write_text("".join(
        f"{file_hash(path).hexdigest()}  {path.name}\n" for path in sorted(archives)), encoding="utf-8")
    validate(output)
    from npm_smoke import smoke
    smoke(archives)
    report["verified"] = "isolated npm installation, integrated executor, updater, and Mermaid renderers"
    (output / "repackage-report.json").write_bytes(json_bytes(report))
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repackage(args.artifacts.resolve(), args.receipt.resolve(), args.output.resolve())
