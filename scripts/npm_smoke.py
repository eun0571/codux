"""Verify npm archives using a disposable local registry and installation prefix."""
import argparse
import base64
import hashlib
import http.server
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import threading
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def smoke(archives):
    packages = {}
    command = None
    for file in archives:
        with tarfile.open(file, "r:gz") as tar:
            metadata = json.load(tar.extractfile("package/package.json"))
        with file.open("rb") as stream:
            integrity = "sha512-" + base64.b64encode(hashlib.file_digest(stream, "sha512").digest()).decode()
        if metadata["name"] in packages:
            raise ValueError("Duplicate npm package")
        packages[metadata["name"]] = (file, metadata, integrity)
        if metadata.get("bin", {}).get("codux"):
            if command:
                raise ValueError("Supply only one command package")
            command = metadata
    if not command:
        raise ValueError("Supply the command package and its native archives")
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js with npm is required")
    module = (ROOT / "npm/update.mjs").as_uri()
    npm = subprocess.check_output([node, "--input-type=module", "-e",
        f"import {{npmCli}} from {json.dumps(module)}; process.stdout.write(npmCli());"], text=True)

    class Registry(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            name = unquote(urlsplit(self.path).path).removeprefix("/")
            if name.startswith("tar/"):
                found = next((p for p, _, _ in packages.values() if p.name == name[4:]), None)
                if not found:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(found.stat().st_size))
                self.end_headers()
                with found.open("rb") as stream:
                    shutil.copyfileobj(stream, self.wfile)
                return
            if name not in packages:
                self.send_error(404)
                return
            file, metadata, integrity = packages[name]
            version = {**metadata, "dist": {
                "tarball": f"http://127.0.0.1:{self.server.server_port}/tar/{file.name}", "integrity": integrity}}
            data = json.dumps({"name": name, "dist-tags": {"latest": metadata["version"], "preview": metadata["version"]},
                               "versions": {metadata["version"]: version}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    scratch = ROOT / ".build"
    scratch.mkdir(exist_ok=True)
    # Windows file scanners can retain handles after npm exits. Cleanup must not
    # replace a useful install or renderer failure with a directory-removal error.
    with tempfile.TemporaryDirectory(prefix="npm-smoke-", dir=scratch, ignore_cleanup_errors=True) as temporary:
        work = Path(temporary)
        # Exercise the archive without the maintainer's renderer overrides or UI fixtures.
        env = {k: v for k, v in os.environ.items()
               if not k.lower().startswith(("npm_config_", "codux_", "mycodx_", "mycodex_"))}
        for name in ["user.npmrc", "global.npmrc"]:
            (work / name).write_text("")
        prefix = work / "fresh user \u2603 space" / "npm prefix"
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Registry)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        env.update(NPM_CONFIG_PREFIX=str(prefix), NPM_CONFIG_REGISTRY=f"http://127.0.0.1:{server.server_port}",
                   NPM_CONFIG_USERCONFIG=str(work / "user.npmrc"), NPM_CONFIG_GLOBALCONFIG=str(work / "global.npmrc"),
                   NPM_CONFIG_CACHE=str(work / "cache"), CODEX_HOME=str(work / "home"),
                   CODUX_MERMAID_PROTOCOL="off")
        (work / "home").mkdir()
        try:
            print("Checking isolated npm installation...", flush=True)
            subprocess.run([node, npm, "install", "-g", f"{command['name']}@{command['version']}",
                "--ignore-scripts", "--no-audit", "--no-fund"], cwd=work, env=env, check=True, timeout=240)
            modules = prefix / ("node_modules" if os.name == "nt" else "lib/node_modules")
            launcher = modules.joinpath(*command["name"].split("/"), "cli.mjs")
            print("Checking installed command and update lookup...", flush=True)
            output = subprocess.check_output([node, str(launcher), "--version"], cwd=work, env=env, text=True).strip()
            if not output.startswith(f"codux {command['version']} (Codex "):
                raise RuntimeError(f"Unexpected installed version: {output}")
            print(output)
            # Terminal hints alone must not trigger probes or create UI state for --version.
            for terminal, hints in [
                ("Windows Terminal", {"WT_SESSION": "isolated-smoke"}),
                ("VS Code", {"TERM_PROGRAM": "vscode"}),
                ("Git Bash / mintty", {"TERM_PROGRAM": "mintty"}),
                ("plain console", {}),
            ]:
                clean = {k: v for k, v in env.items() if k not in
                         {"TERM_PROGRAM", "TERM_PROGRAM_VERSION", "WT_SESSION", "TMUX", "ZELLIJ"}}
                clean.update(hints)
                result = subprocess.check_output([node, str(launcher), "--version"], cwd=work,
                                                 env=clean, text=True, timeout=30)
                if result.strip() != output or "\x1b" in result:
                    raise RuntimeError(f"Noninteractive output changed for {terminal}")
            # Upstream initializes helper aliases in CODEX_HOME/tmp before parsing
            # --version. That runtime directory is not a saved UI/configuration.
            unexpected = [p.name for p in (work / "home").iterdir()
                          if p.name != "tmp" or not p.is_dir()]
            if unexpected:
                raise RuntimeError(f"Version lookup unexpectedly saved home state: {unexpected}")
            subprocess.run([node, str(launcher), "update"], cwd=work, env=env, check=True, timeout=60)
            shim = prefix / ("codux.cmd" if os.name == "nt" else "bin/codux")
            subprocess.run([str(shim), "--version"], cwd=work, env=env, check=True, timeout=30)
            markers = list(prefix.rglob("codux-npm.json"))
            if len(markers) != 1:
                raise RuntimeError("npm did not select exactly one native runtime")
            runtime = markers[0].parent
            required = runtime / "codex-resources/codux-mermaid/node_modules/puppeteer-core/package.json"
            if not required.is_file():
                raise RuntimeError("npm dropped bundled renderer dependencies")
            import mermaid_runtime
            print("Checking relocated Mermaid renderers...", flush=True)
            mermaid_runtime.verify_renderers(runtime, scratch, env=env)
            print("PASS: isolated npm installation, spaced/Unicode path, terminal hints, command, updater, and relocated renderers.")
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archives", nargs="+", type=Path)
    smoke(parser.parse_args().archives)
