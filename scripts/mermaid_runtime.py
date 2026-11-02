"""Stage only the pinned runtime dependencies used by the packaged renderers."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

IMAGE_PAIRS = [
    ("renderers/mermaid/product-worker.mjs", "worker.mjs"),
    ("renderers/mermaid/official-config.mjs", "official-config.mjs"),
    ("renderers/mermaid/frame.html", "frame.html"),
    ("renderers/mermaid/frame.js", "frame.js"),
]


def validate_mermaid_runtime(package: Path, root: Path = Path(__file__).resolve().parents[1]):
    """Verify the exact staged renderer resources before npm packaging."""
    runtime = package / "codex-resources/codux-mermaid"
    for source, bundled in IMAGE_PAIRS:
        path = runtime / bundled
        if not path.is_file() or path.read_bytes() != (root / source).read_bytes():
            raise ValueError(f"Missing or stale Mermaid resource: {bundled}; rebuild release")
    version = json.loads((runtime / "mermaid-live-package.json").read_text(encoding="utf-8"))["version"]
    if version != "12.2.0":
        raise ValueError("Release requires Mermaid 12.2.0")
    for name in ["live-dist/mermaid.esm.min.mjs", "mermaid-live-LICENSE", "node_modules/puppeteer-core/package.json", "runtime-files.json"]:
        if not (runtime / name).is_file():
            raise ValueError(f"Missing Mermaid resource: {name}")
    for directory in (runtime, package / "codex-resources/codux-mermaid-text"):
        manifest = json.loads((directory / "runtime-files.json").read_text(encoding="utf-8"))
        actual = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file() and p.name != "runtime-files.json"}
        if set(manifest["files"]) != actual:
            raise ValueError("Runtime file list changed after staging")
        for name, digest in manifest["files"].items():
            if hashlib.sha256((directory / name).read_bytes()).hexdigest() != digest:
                raise ValueError(f"Runtime resource changed: {name}")


def dependency_tree(runtime: Path, names):
    """Resolve dependencies like Node, including nested package versions."""
    modules = (runtime / "node_modules").resolve()
    found = {}

    def visit(name, parent):
        current = parent
        while current.is_relative_to(runtime.resolve()):
            folder = current / "node_modules" / name
            if (folder / "package.json").is_file():
                break
            current = current.parent
        else:
            raise RuntimeError(f"Missing runtime dependency: {name}; run scripts/setup-runtime.ps1")
        folder = folder.resolve()
        if not folder.is_relative_to(modules) or folder.is_symlink():
            raise RuntimeError(f"Dependency escaped runtime: {name}")
        if folder in found:
            return
        meta = json.loads((folder / "package.json").read_text(encoding="utf-8"))
        found[folder] = meta
        for child in meta.get("dependencies", {}):
            visit(child, folder)

    for name in names:
        visit(name, runtime.resolve())
    return found


def copy_dependencies(runtime, target, manifest_dir):
    manifest = json.loads((manifest_dir / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((manifest_dir / "package-lock.json").read_text(encoding="utf-8"))
    packages = dependency_tree(runtime, manifest["dependencies"])
    for folder, meta in packages.items():
        relative = folder.relative_to(runtime.resolve())
        pinned = lock["packages"].get(relative.as_posix(), {})
        if pinned.get("version") != meta["version"]:
            raise RuntimeError(f"Runtime pin mismatch: {meta['name']}; run scripts/setup-runtime.ps1")
        for path in folder.rglob("*"):
            if not path.is_file():
                continue
            inside = path.relative_to(folder)
            cjs_only = meta["name"] in {"puppeteer-core", "@puppeteer/browsers", "chromium-bidi"}
            if "node_modules" in inside.parts or any(p in inside.parts for p in ("test", "tests", "__tests__")):
                continue
            if cjs_only and any(p in inside.parts for p in ("esm", "es5-iife")):
                continue
            legal = path.name.lower().startswith(("license", "notice", "copying", "copyright"))
            if not legal and (path.suffix not in {".js", ".cjs", ".mjs", ".json", ".wasm", ".node"}
                              or ".test." in path.name or ".spec." in path.name):
                continue
            if path.is_symlink() or not path.resolve().is_relative_to(runtime.resolve()):
                raise RuntimeError("Unsafe dependency file")
            destination = target / relative / inside
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
    for name in ("package.json", "package-lock.json"):
        shutil.copy2(manifest_dir / name, target / name)


def stamp(target):
    files = {p.relative_to(target).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(target.rglob("*")) if p.is_file() and p.name != "runtime-files.json"}
    (target / "runtime-files.json").write_text(json.dumps({"format": 1, "files": files}, indent=2) + "\n", encoding="utf-8")


def stage(root: Path, package: Path) -> bool:
    runtime = root / ".build/mermaid-product-runtime"
    if not (runtime / "node_modules/puppeteer-core/package.json").is_file():
        # Existing development installs contain the same pinned core. A clean
        # checkout installs only product dependencies with setup-runtime.ps1.
        runtime = root / ".build/mermaid-runtime"
    if not runtime.is_dir():
        return False
    target = package / "codex-resources/codux-mermaid"
    target.mkdir(parents=True, exist_ok=False)
    copy_dependencies(runtime, target, root / "renderers/mermaid-product")
    prepare_image_runtime(root, target)
    stamp(target)
    return True


def prepare_image_runtime(root: Path, target: Path) -> None:
    live = root / ".build/mermaid-live-runtime/node_modules/mermaid"
    manifest = live / "package.json"
    if not manifest.is_file() or json.loads(manifest.read_text(encoding="utf-8")).get("version") != "12.2.0":
        raise RuntimeError("Mermaid images require 12.2.0; run scripts/setup-runtime.ps1")
    for source, destination in IMAGE_PAIRS:
        shutil.copy2(root / source, target / destination)
    # Keep every diagram loader in one minified browser distribution.
    selected = [live / "dist/mermaid.esm.min.mjs", *sorted((live / "dist/chunks/mermaid.esm.min").glob("*.mjs"))]
    if len(selected) < 2:
        raise RuntimeError("Incomplete Mermaid browser distribution")
    for source in selected:
        destination = target / "live-dist" / source.relative_to(live / "dist")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    shutil.copy2(manifest, target / "mermaid-live-package.json")
    shutil.copy2(live / "LICENSE", target / "mermaid-live-LICENSE")


def stage_text(root: Path, package: Path) -> bool:
    runtime = root / ".build/mermaid-text-runtime"
    if not runtime.is_dir():
        return False
    target = package / "codex-resources/codux-mermaid-text"
    target.mkdir(parents=True, exist_ok=False)
    copy_dependencies(runtime, target, root / "renderers/mermaid-text")
    shutil.copy2(root / "renderers/mermaid-text/worker.mjs", target / "worker.mjs")
    stamp(target)
    return True


def verify_renderers(package: Path, scratch: Path) -> None:
    """Exercise the relocated, compact runtime before publishing an archive."""
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js is required to verify the packaged Mermaid runtime")
    with tempfile.TemporaryDirectory(prefix="mermaid-release-check-", dir=scratch) as temporary:
        cache = Path(temporary)
        requests = [{"source": "flowchart LR\n Start[Start] --> Done[Done]", "background": "#101010"},
                    {"source": "sequenceDiagram\n Alice->>Bob: Hello\n Bob-->>Alice: Ready", "background": "#ffffff"}]
        worker = package / "codex-resources/codux-mermaid/worker.mjs"
        result = subprocess.run([node, str(worker), str(cache)], input="".join(json.dumps(r) + "\n" for r in requests),
                                text=True, encoding="utf-8", capture_output=True, check=True, timeout=90)
        responses = [json.loads(line) for line in result.stdout.splitlines()]
        if len(responses) != len(requests):
            raise RuntimeError("Packaged image worker returned incomplete output")
        for response in responses:
            if not response.get("ok"):
                raise RuntimeError(f"Packaged Mermaid render failed: {response.get('error')}")
            if not Path(response["png"]).read_bytes().startswith(b"\x89PNG\r\n\x1a\n") or "<svg" not in Path(response["svg"]).read_text(encoding="utf-8"):
                raise RuntimeError("Packaged Mermaid renderer produced invalid image files")
        worker = package / "codex-resources/codux-mermaid-text/worker.mjs"
        result = subprocess.run([node, str(worker)], input=json.dumps({"source": requests[0]["source"], "columns": 160}) + "\n",
                                text=True, encoding="utf-8", capture_output=True, check=True, timeout=30)
        if not json.loads(result.stdout).get("ok"):
            raise RuntimeError("Packaged text renderer failed")
    print("Packaged Mermaid image and text render checks passed.")
