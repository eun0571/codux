"""Build the static playground without Rust, npm dependencies, or a backend."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ('index.html', 'style.css', 'model.js', 'sessions.js', 'viewer.js', 'app.js', 'palettes.js')
NATIVE_INPUTS = tuple('codex-rs/tui/src/' + name for name in
                      ('mycodx_ui.rs', 'mycodx_style.rs', 'mycodx_theme.rs', 'mycodx_status.rs'))


def provenance(lock):
    return {'upstream_commit': lock['commit'],
            'native_sha256': {name: lock['patched_sha256'][name] for name in NATIVE_INPUTS},
            'catalog_sha256': hashlib.sha256((ROOT / 'playground/palettes.js').read_bytes()).hexdigest()}


def build(destination, test_exe=None):
    lock = json.loads((ROOT / 'upstream.lock.json').read_text(encoding='utf-8'))
    release = json.loads((ROOT / 'release.json').read_text(encoding='utf-8'))
    if test_exe:
        # Only an explicit native test binary refreshes the checked-in catalog.
        home = ROOT / '.build/playground-export-home'
        home.mkdir(parents=True, exist_ok=True)
        result = subprocess.run([str(test_exe.resolve()),
            'mycodx_ui::theme::tests::mycodx_export_playground_catalog', '--ignored', '--exact'],
            env={**os.environ, 'CODEX_HOME': str(home),
                 'MYCODEX_PLAYGROUND_OUTPUT': str(ROOT / 'playground/palettes.js')},
            capture_output=True, text=True, check=True)
        if '1 passed; 0 failed' not in result.stdout:
            raise ValueError('The supplied binary did not run the native catalog exporter')
        (ROOT / 'playground/catalog.json').write_text(json.dumps(provenance(lock), indent=2) + '\n', encoding='utf-8')
    if json.loads((ROOT / 'playground/catalog.json').read_text(encoding='utf-8')) != provenance(lock):
        raise ValueError('Native UI catalog changed; refresh it with --catalog-test-exe (see docs/PLAYGROUND.md)')
    subprocess.run(['node', str(ROOT / 'scripts/test_playground.cjs')], check=True)
    subprocess.run([sys.executable, str(ROOT / 'scripts/test_playground_server.py')], check=True)
    destination = destination.resolve()
    # Keep staging within disposable build output; never upload the source directory.
    build_root = (ROOT / '.build').resolve()
    if not destination.is_relative_to(build_root) or destination == build_root:
        raise ValueError('Playground output must be a subdirectory of .build')
    destination.mkdir(parents=True, exist_ok=True)
    allowed = {*ASSETS, 'release.js', '.nojekyll'}
    if any(p.name not in allowed or not p.is_file() or p.is_symlink() for p in destination.iterdir()):
        raise ValueError('Output contains unrelated files; choose a fresh output directory')
    for name in ASSETS:
        source = ROOT / 'playground' / name
        if source.is_symlink():
            raise ValueError(f'Symlink not allowed: {name}')
        shutil.copy2(source, destination / name)
    metadata = {key: release[key] for key in ('name', 'display_name', 'version')}
    metadata.update(upstream=lock['version'], patch=lock['patch_version'])
    (destination / 'release.js').write_text('window.PLAYGROUND_RELEASE = ' + json.dumps(metadata) + ';\n', encoding='utf-8')
    (destination / '.nojekyll').write_text('', encoding='utf-8')
    size = sum(p.stat().st_size for p in destination.iterdir())
    print(f'Playground ready: {destination} ({len(allowed)} files, {size:,} bytes). Nothing published.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / '.build/playground')
    parser.add_argument('--catalog-test-exe', type=Path, help='Refresh colors/defaults from the current compiled TUI tests')
    args = parser.parse_args()
    build(args.output, args.catalog_test_exe)
