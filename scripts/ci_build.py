"""Build and verify a native npm package on its own operating system. Never publishes."""
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    os.chdir(ROOT)
    env = {**os.environ, "CARGO_TARGET_DIR": str(ROOT / ".build/target"), "CARGO_INCREMENTAL": "0", "PYTHONUTF8": "1"}
    logs = ROOT / ".build/logs"
    logs.mkdir(parents=True, exist_ok=True)
    env["MYCODX_BUILD_LOG"] = str(logs / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-native-ci.log"))
    subprocess.run([sys.executable, "scripts/audit_public.py"], env=env, check=True)
    subprocess.run([sys.executable, "scripts/setup_runtime.py"], env=env, check=True)
    command = (["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "scripts/build.ps1", "-Profile", "release"]
               if os.name == "nt" else [sys.executable, "scripts/manage.py", "build", "--profile", "release"])
    subprocess.run(command, env=env, check=True)
    current = json.loads((ROOT / ".build/current.json").read_text(encoding="utf-8"))
    package = Path(current["executable"]).parent.parent
    build = json.loads((package / "codux-build.json").read_text(encoding="utf-8"))
    output = ROOT / "dist/npm" / build["release_version"]
    subprocess.run([sys.executable, "scripts/package_npm.py", "--package", str(package),
                    "--output", str(output), "--smoke"], env=env, check=True)


if __name__ == "__main__":
    main()
