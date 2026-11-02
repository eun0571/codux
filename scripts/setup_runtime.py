"""Install pinned renderer libraries with npm on the native build host."""
from pathlib import Path
import os
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm or not shutil.which("node"):
        raise RuntimeError("Install Node.js with npm before preparing renderers")
    for name in ["mermaid-product", "mermaid-live", "mermaid-text"]:
        runtime = ROOT / ".build" / f"{name}-runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        for filename in ["package.json", "package-lock.json"]:
            shutil.copy2(ROOT / "renderers" / name / filename, runtime / filename)
        subprocess.run([npm, "ci", "--prefix", str(runtime), "--ignore-scripts", "--no-audit", "--no-fund",
                        "--cache", str(ROOT / ".build/npm-cache")], check=True)
    print("Pinned renderer libraries are ready. Chrome or Edge is required for image verification.")


if __name__ == "__main__":
    main()
