"""The complete source set for the public repository and native npm builds."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILES = [
    "README.md", "LICENSE", "NOTICE", "release.json", "upstream.lock.json", ".gitignore", ".gitattributes",
    "patches/codux-ui.patch", "docs/DEVELOPMENT.md", "docs/RELEASE.md", "docs/MERMAID.md", "docs/COMPATIBILITY.md",
    "scripts/build.ps1", "scripts/manage.py", "scripts/migration_inputs.py", "scripts/release_info.py",
    "scripts/mermaid_runtime.py", "scripts/public_source.py", "scripts/audit_public.py",
    "scripts/setup-windows.ps1", "scripts/setup-runtime.ps1",
    "renderers/mermaid-product/package.json", "renderers/mermaid-product/package-lock.json",
    "renderers/mermaid-live/package.json", "renderers/mermaid-live/package-lock.json",
    "renderers/mermaid/product-worker.mjs", "renderers/mermaid/official-config.mjs",
    "renderers/mermaid/frame.html", "renderers/mermaid/frame.js",
    "renderers/mermaid-text/package.json", "renderers/mermaid-text/package-lock.json", "renderers/mermaid-text/worker.mjs",
    "npm/cli.mjs", "npm/update.mjs", "scripts/package_npm.py", "scripts/setup_runtime.py",
    "scripts/npm_smoke.py", "scripts/ci_build.py", ".github/workflows/native-build.yml",
    "scripts/prepare_upstream.py", "scripts/track_upstream.py", "scripts/publish_npm.py",
    ".github/workflows/track-upstream.yml", ".github/workflows/verify-pr.yml", ".github/workflows/publish-npm.yml",
    ".github/workflows/playground.yml", "scripts/build_playground.py", "scripts/test_playground.cjs",
    "docs/PLAYGROUND.md", "playground/index.html", "playground/style.css", "playground/model.js",
    "playground/app.js", "playground/palettes.js", "playground/catalog.json",
    "playground/sessions.js", "playground/viewer.js",
    "scripts/serve_playground.py", "scripts/test_playground_server.py",
]


def source_files(root=ROOT):
    files = [root / name for name in SOURCE_FILES]
    for path in files:
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"Missing or unsafe public source: {path.relative_to(root)}")
    return sorted(files)
