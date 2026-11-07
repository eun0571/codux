"""Prepare and build an isolated, pinned Codux package. Python 3.12+; stdlib only."""

import argparse
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import traceback

import migration_inputs
import release_info

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / ".build"


def source_directory(lock: dict) -> Path:
    # Preserve previous source checkouts when changing the pinned upstream version.
    name = lock.get("source_directory", "upstream")
    if not isinstance(name, str) or not re.fullmatch(r"upstream(?:-[0-9]+\.[0-9]+\.[0-9]+)?", name):
        raise RuntimeError("Source directory must be a versioned upstream folder under .build")
    return BUILD / name


SOURCE = source_directory(json.loads((ROOT / "upstream.lock.json").read_text(encoding="utf-8")))


def git_args(path: Path, *args: str) -> list[str]:
    # The agent and the interactive Windows user can have different SIDs. Trust only
    # this explicitly selected checkout, for this command; never change global Git config.
    return ["git", "-c", f"safe.directory={path.resolve().as_posix()}",
            "-c", "core.longpaths=true",
            "-c", "core.whitespace=trailing-space,space-before-tab,cr-at-eol", *args]


def strip_terminal_color_queries(text: str) -> str:
    # Captured test output has no terminal input reader. Relaying an OSC query
    # would send the terminal's answer to the parent shell instead of the test.
    return re.sub(r"\x1b\](?:10|11);\?(?:\x07|\x1b\\)", "", text)


def run(*args: str, cwd: Path = ROOT, env=None, capture=False) -> str:
    if args and args[0] == "git":
        args = tuple(git_args(cwd, *args[1:]))
    print("+ " + " ".join(map(str, args)), flush=True)
    command = list(map(str, args))
    if capture:
        result = subprocess.run(
            command, cwd=cwd, env=env, check=True,
            text=True, encoding="utf-8", capture_output=True,
        )
        return result.stdout.rstrip("\r\n")
    # PowerShell 5 Start-Transcript omits inherited native stdout/stderr. Pipe and
    # relay explicitly so Cargo/compiler/test output reaches both console and log.
    with subprocess.Popen(
        command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    ) as process:
        for line in process.stdout:
            print(strip_terminal_color_queries(line), end="", flush=True)
        code = process.wait()
    if code:
        raise subprocess.CalledProcessError(code, command)
    return ""


class LoggedStream:
    def __init__(self, terminal, log):
        self.terminal = terminal
        self.log = log

    def write(self, text):
        self.terminal.write(text)
        self.log.write(text)
        self.log.flush()
        return len(text)

    def flush(self):
        self.terminal.flush()
        self.log.flush()

    def __getattr__(self, name):
        return getattr(self.terminal, name)


def read_lock() -> dict:
    lock = json.loads((ROOT / "upstream.lock.json").read_text(encoding="utf-8"))
    if lock["repository"] != "https://github.com/openai/codex.git":
        raise RuntimeError("Unexpected upstream repository; review upstream.lock.json")
    if not re.fullmatch(r"[0-9a-f]{40}", lock["commit"]):
        raise RuntimeError("Upstream must be pinned to a full commit SHA")
    patch = (ROOT / lock["patch"]).resolve()
    if not patch.is_relative_to(ROOT / "patches"):
        raise RuntimeError("Patch must be inside patches/")
    if hashlib.sha256(patch.read_bytes()).hexdigest() != lock["patch_sha256"]:
        raise RuntimeError("Patch checksum mismatch; review changes and re-export the lock")
    if lock.get("windows_sql_newlines") != "crlf":
        raise RuntimeError("Windows SQL migration newline policy must be pinned to CRLF")
    return lock


def doctor(lock: dict) -> None:
    prerequisites = ["git", "rustup", "cargo", "rustc"]
    if os.name == "nt":
        prerequisites += ["cl", "cmake"]
    missing = [name for name in prerequisites if shutil.which(name) is None]
    print(f"Upstream: {lock['version']} ({lock['commit']})")
    print(f"Required Rust toolchain: {lock['rust_toolchain']}")
    print(f"Source directory: {SOURCE}")
    if missing:
        raise RuntimeError("Missing build prerequisites: " + ", ".join(missing)
                           + ". On Windows, use scripts/setup-windows.ps1 and scripts/build.ps1.")
    toolchains = run("rustup", "toolchain", "list", capture=True)
    if not any(line.startswith(lock["rust_toolchain"] + "-") for line in toolchains.splitlines()):
        raise RuntimeError(f"Install Rust {lock['rust_toolchain']} with rustup first")
    if os.name == "nt":
        print("Windows also requires the MSVC C++ build tools and Windows SDK.")
    print("Prerequisites found. Network access is required for upstream and dependencies.")


def verify_sources(path: Path, lock: dict) -> None:
    for relative, expected in lock["source_sha256"].items():
        actual = hashlib.sha256((path / relative).read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(f"Upstream file differs from pinned source: {relative}")


def verify_patched(path: Path, lock: dict) -> None:
    for relative, expected in lock["patched_sha256"].items():
        actual = hashlib.sha256((path / relative).read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(f"Patched file has additional edits: {relative}")


def ensure_patch(path: Path, lock: dict) -> None:
    patch = ROOT / lock["patch"]
    reverse = subprocess.run(
        git_args(path, "-c", "core.autocrlf=false", "apply", "--reverse", "--check", str(patch)),
        cwd=path, capture_output=True, check=False,
    )
    if reverse.returncode == 0:
        verify_patched(path, lock)
        print("Exact patch already applied.")
        return
    verify_sources(path, lock)
    run("git", "-c", "core.autocrlf=false", "apply", "--check", str(patch), cwd=path)
    run("git", "-c", "core.autocrlf=false", "apply", str(patch), cwd=path)
    verify_patched(path, lock)


def prepare(lock: dict) -> dict[str, str]:
    BUILD.mkdir(exist_ok=True)
    if not SOURCE.exists():
        SOURCE.mkdir()
        run("git", "init", str(SOURCE))
        run("git", "config", "core.autocrlf", "false", cwd=SOURCE)
        run("git", "remote", "add", "origin", lock["repository"], cwd=SOURCE)
    if not (SOURCE / ".git").is_dir():
        raise RuntimeError(f"Existing path is not the managed Git checkout: {SOURCE}")
    origin = run("git", "remote", "get-url", "origin", cwd=SOURCE, capture=True)
    if origin != lock["repository"]:
        raise RuntimeError("Checkout origin differs; no changes made")
    head = subprocess.run(
        git_args(SOURCE, "rev-parse", "--verify", "HEAD"), cwd=SOURCE,
        text=True, capture_output=True, check=False,
    )
    if head.returncode != 0:
        if run("git", "status", "--porcelain", cwd=SOURCE, capture=True):
            raise RuntimeError("Uncommitted files found in incomplete checkout; no changes made")
        run("git", "fetch", "--depth", "1", "origin", lock["commit"], cwd=SOURCE)
        run("git", "checkout", "--detach", "FETCH_HEAD", cwd=SOURCE)
    elif head.stdout.strip() != lock["commit"]:
        raise RuntimeError("Checkout is at another commit; keep it and use a fresh workspace")
    actual = run("git", "rev-parse", "HEAD", cwd=SOURCE, capture=True)
    if actual != lock["commit"]:
        raise RuntimeError("Resolved upstream commit mismatch")
    migration_checksums = migration_inputs.prepare(SOURCE, lock["commit"], windows=os.name == "nt")
    status = run("git", "status", "--porcelain", "--untracked-files=all", cwd=SOURCE, capture=True)
    if status:
        # SQL bytes were independently checked against the pinned blobs above. Git can
        # report stat-only changes after newline conversion when optional index locks are off.
        expected = set(lock["patched_sha256"]) | migration_checksums.keys()
        if any(line[3:] not in expected for line in status.splitlines()):
            raise RuntimeError("Checkout has unrelated edits; patch/build stopped")
        if any(line[3:] not in migration_checksums for line in status.splitlines()):
            reverse = subprocess.run(
                git_args(SOURCE, "-c", "core.autocrlf=false", "apply", "--reverse", "--check", str(ROOT / lock["patch"])),
                cwd=SOURCE, capture_output=True, check=False,
            )
            if reverse.returncode != 0:
                raise RuntimeError("Checkout has edits beyond the patch; patch/build stopped")
            verify_patched(SOURCE, lock)
    ensure_patch(SOURCE, lock)
    return migration_checksums


def build_environment(lock: dict) -> tuple[Path, dict, str]:
    rust = SOURCE / "codex-rs"
    env = {**os.environ, "CODEX_REPO_ROOT": str(SOURCE), "RUSTUP_TOOLCHAIN": lock["rust_toolchain"]}
    git_config_count = int(env.get("GIT_CONFIG_COUNT", "0"))
    env[f"GIT_CONFIG_KEY_{git_config_count}"] = "safe.directory"
    env[f"GIT_CONFIG_VALUE_{git_config_count}"] = SOURCE.resolve().as_posix()
    env["GIT_CONFIG_COUNT"] = str(git_config_count + 1)
    compiler = run("rustc", "-vV", env=env, capture=True)
    target = next((line.removeprefix("host: ") for line in compiler.splitlines() if line.startswith("host: ")), None)
    if target is None:
        raise RuntimeError("Cannot determine the native Rust target")
    # TUI checks need the same pinned V8 archive and bindings as the package build.
    previous_repo = os.environ.get("CODEX_REPO_ROOT")
    os.environ["CODEX_REPO_ROOT"] = str(SOURCE)
    sys.path.insert(0, str(SOURCE / "scripts"))
    try:
        from codex_package.targets import TARGET_SPECS
        from codex_package.v8 import resolve_codex_v8_cargo_env
        if target not in TARGET_SPECS:
            raise RuntimeError(f"Unsupported package target: {target}")
        env.update(resolve_codex_v8_cargo_env(
            TARGET_SPECS[target], environ=env, cache_root=BUILD / "v8-cache",
        ))
    finally:
        sys.path.pop(0)
        if previous_repo is None:
            os.environ.pop("CODEX_REPO_ROOT", None)
        else:
            os.environ["CODEX_REPO_ROOT"] = previous_repo
    return rust, env, target


def fetch(lock: dict) -> None:
    doctor(lock)
    prepare(lock)
    rust, env, target = build_environment(lock)
    run("cargo", "fetch", "--locked", "--target", target, cwd=rust, env=env)
    print("Pinned upstream, V8 archive/bindings and Cargo dependencies are ready for local compilation.")


def build(lock: dict, profile: str) -> None:
    doctor(lock)
    migration_checksums = prepare(lock)
    rust, env, target = build_environment(lock)
    release = release_info.read_release()
    if target not in release_info.BUILD_TARGETS:
        raise RuntimeError(f"Unsupported native build target: {target}")
    env.update(MYCODEX_COMMAND=release["name"],
               MYCODEX_DISPLAY_VERSION=release_info.display_version(release, lock),
               MYCODEX_RELEASE_URL=release_info.package_url(release))
    # Resolve upstream's required helpers before expensive compilation/tests so
    # packaging API changes fail early when the pinned upstream is updated.
    from codex_package.cargo import source_binaries_for_target
    from codex_package.targets import PACKAGE_VARIANTS, TARGET_SPECS
    spec = TARGET_SPECS[target]
    binaries = source_binaries_for_target(
        spec, PACKAGE_VARIANTS["codex"], build_entrypoint=True, build_code_mode_host=True,
        build_exec_server=True, build_bwrap=spec.is_linux,
        build_codex_command_runner=spec.is_windows,
        build_codex_windows_sandbox_setup=spec.is_windows,
    )
    # Syntax/type checking and behavioral tests must succeed before packaging.
    check_options = ["--locked", "--target", target, "--profile", "dev-small", "-p", "codex-tui"]
    run("cargo", "check", *check_options, cwd=rust, env=env)
    # Match upstream rust-ci-full-nextest-platform.yml: async app tests need an
    # 8 MiB thread stack. The Windows linker /STACK setting only covers main.
    # Keep any larger caller setting, and scope this to tests, not the package.
    # Snapshot buffers include RGB styles. Headless CI reports less color support
    # than an interactive terminal; use a fixed capability for tests only.
    test_env = {**env, "FORCE_COLOR": "3", "INSTA_UPDATE": "no",
                "RUST_MIN_STACK": str(max(8 * 1024 * 1024, int(env.get("RUST_MIN_STACK", "0"))))}
    print(f"Test thread stack: {test_env['RUST_MIN_STACK']} bytes (upstream CI minimum: 8 MiB)")
    run("cargo", "test", *check_options, "--lib", "transcript_view::mycodx::tests", cwd=rust, env=test_env)
    run("cargo", "test", *check_options, "--lib", "app::codux_navigation::tests", cwd=rust, env=test_env)
    run("cargo", "test", *check_options, "--lib", "transcript_view::follow_control::tests", cwd=rust, env=test_env)
    run("cargo", "test", *check_options, "--lib", "codux_escape_does_not_interrupt", cwd=rust, env=test_env)
    run("cargo", "test", *check_options, "--lib", "codux_working_", cwd=rust, env=test_env)
    run("cargo", "test", *check_options, "--lib", "keymap::", cwd=rust, env=test_env)
    run("cargo", "test", *check_options, "--lib", "bottom_pane::shortcut_overlay::tests", cwd=rust, env=test_env)
    run("cargo", "test", *check_options, "--lib", "bottom_pane::footer::tests", cwd=rust, env=test_env)
    run("cargo", "test", *check_options, "--lib", "transcript_view::search::", cwd=rust, env=test_env)
    run("cargo", "test", *check_options, "--lib", "transcript_view::footer::tests", cwd=rust, env=test_env)
    run("cargo", "test", *check_options, "--lib", "transcript_view::prompt_header::tests", cwd=rust, env=test_env)
    run("cargo", "test", *check_options, "--lib", "find_refreshes_live_details_before_searching_the_first_query", cwd=rust, env=test_env)
    run("cargo", "test", *check_options, "--lib", "mycodx_ui::", cwd=rust, env=test_env)
    run("cargo", "test", *check_options, "--lib", "status_indicator_widget::", cwd=rust, env=test_env)
    run("cargo", "test", *check_options, "--lib", "history_cell::separators::tests", cwd=rust, env=test_env)
    run("cargo", "test", *check_options, "--lib", "transcript_view::text::", cwd=rust, env=test_env)
    run("cargo", "test", *check_options, "--lib", "codux_mermaid::", cwd=rust, env=test_env)
    run("cargo", "test", *check_options, "--lib", "terminal_probe::", cwd=rust, env=test_env)
    run("cargo", "test", *check_options, "--lib", "update_action::tests", cwd=rust, env=test_env)
    run("cargo", "test", *check_options, "--lib", "updates_cache::tests", cwd=rust, env=test_env)
    run("cargo", "test", *check_options, "--lib", "update_prompt::tests", cwd=rust, env=test_env)
    run("cargo", "test", *check_options, "--lib", "bottom_pane::chat_composer::paste_tests", cwd=rust, env=test_env)
    run("cargo", "test", *check_options, "--lib", "raw_multiline_paste_defers_rendering_and_submits_once", cwd=rust, env=test_env)
    run("cargo", "test", *check_options, "--lib", "accepted_find_defers_paste_rendering_but_keeps_enter", cwd=rust, env=test_env)
    target_label = "" if target == release["target"] else f"-{target}"
    package = ROOT / "dist" / f"{lock['package_version']}{target_label}-{profile}"
    if package.exists() and (not package.is_dir() or any(package.iterdir())):
        raise RuntimeError(f"Output already exists; keep it or choose another profile: {package}")
    # Upstream's assembler accepts prebuilt binaries, but its own Cargo command
    # omits --locked. Build the complete upstream-defined set ourselves to keep pins enforced.
    package_env = {**env, "STABLE_GIT_COMMIT": lock["commit"]}
    cargo_command = ["cargo", "build", "--locked", "--target", target, "--profile", profile]
    for binary in binaries:
        cargo_command.extend(["--bin", binary])
    run(*cargo_command, cwd=rust, env=package_env)
    target_dir = Path(env.get("CARGO_TARGET_DIR", rust / "target"))
    if not target_dir.is_absolute():
        target_dir = rust / target_dir
    output_dir = target_dir / target / profile
    migration_inputs.verify_binary(output_dir / f"codex{spec.exe_suffix}", migration_checksums)
    # Retain upstream's canonical package layout and resource validation.
    command = [sys.executable, str(SOURCE / "scripts/build_codex_package.py"),
               "--package-version", lock["package_version"], "--package-dir", str(package),
               "--cargo-profile", profile, "--target", target,
               "--entrypoint-bin", str(output_dir / f"codex{spec.exe_suffix}"),
               "--code-mode-host-bin", str(output_dir / f"codex-code-mode-host{spec.exe_suffix}"),
               "--exec-server-bin", str(output_dir / f"codex-exec-server{spec.exe_suffix}")]
    if spec.is_windows:
        command.extend(["--codex-command-runner-bin", str(output_dir / "codex-command-runner.exe"),
                        "--codex-windows-sandbox-setup-bin", str(output_dir / "codex-windows-sandbox-setup.exe")])
    if spec.is_linux:
        command.extend(["--bwrap-bin", str(output_dir / "bwrap")])
    rg = shutil.which("rg")
    if rg:
        command.extend(["--rg-bin", rg])
    run(*command, cwd=SOURCE, env=package_env)
    import mermaid_runtime
    mermaid_bundled = mermaid_runtime.stage(ROOT, package)
    mermaid_text_bundled = mermaid_runtime.stage_text(ROOT, package)
    if not mermaid_bundled or not mermaid_text_bundled:
        raise RuntimeError("Run python scripts/setup_runtime.py before building a package")
    (package / "release.json").write_text(json.dumps({**release, "target": target}, indent=2) + "\n", encoding="utf-8")
    suffix = ".exe" if os.name == "nt" else ""
    executable = package / "bin" / f"{release['name']}{suffix}"
    shutil.copy2(package / "bin" / f"codex{suffix}", executable)
    output = run(str(executable), "--version", capture=True)
    if output != f"{release['name']} {release_info.display_version(release, lock)}":
        raise RuntimeError(f"Unexpected CLI version: {output}")
    manifest = {**lock, "release_name": release["name"], "release_version": release["version"],
                "profile": profile, "target": target, "mermaid_bundled": mermaid_bundled,
                "mermaid_text_bundled": mermaid_text_bundled}
    (package / "codux-build.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (package / "migration-checksums.json").write_text(
        json.dumps(migration_checksums, indent=2) + "\n", encoding="utf-8"
    )
    # Publish the local pointer only after the complete package and version check succeed.
    pointer = BUILD / "current.json"
    temporary = pointer.with_suffix(".tmp")
    temporary.write_text(json.dumps({"executable": str(executable)}, indent=2) + "\n", encoding="utf-8")
    temporary.replace(pointer)
    print(f"Built {executable}\nRun: {executable}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["doctor", "prepare", "fetch", "build"])
    parser.add_argument("--profile", choices=["dev-small", "release"], default="release")
    args = parser.parse_args()
    try:
        lock = read_lock()
        if args.action == "doctor":
            doctor(lock)
        elif args.action == "prepare":
            prepare(lock)
        elif args.action == "fetch":
            fetch(lock)
        else:
            build(lock, args.profile)
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
            print(exc.stderr.strip(), file=sys.stderr)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception:
        # Print unexpected failures before leaving the log redirection context.
        # Otherwise Python writes the traceback only to the caller's terminal.
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    log_name = os.environ.get("MYCODX_BUILD_LOG")
    if log_name:
        log_path = Path(log_name).resolve()
        if not log_path.is_relative_to((BUILD / "logs").resolve()):
            raise SystemExit("Build log must be inside .build/logs")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w", encoding="utf-8", buffering=1) as log:
            with redirect_stdout(LoggedStream(sys.stdout, log)), redirect_stderr(LoggedStream(sys.stderr, log)):
                raise SystemExit(main())
    else:
        raise SystemExit(main())
