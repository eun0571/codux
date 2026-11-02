"""Keep embedded SQLx checksums compatible with the official native release."""

import hashlib
import mmap
from pathlib import Path
import re
import subprocess

DIRECTORIES = (
    "migrations", "logs_migrations", "goals_migrations", "memory_migrations",
    "queue_migrations", "thread_history_migrations",
)
START = "# mycodx migration newlines begin"
END = "# mycodx migration newlines end"


def git_bytes(source: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-c", f"safe.directory={source.resolve().as_posix()}", *args],
        cwd=source, check=True, capture_output=True,
    ).stdout


def prepare(source: Path, commit: str, *, windows: bool) -> dict[str, str]:
    paths = git_bytes(source, "ls-tree", "-r", "--name-only", commit, "codex-rs/state").decode().splitlines()
    prefixes = tuple(f"codex-rs/state/{directory}/" for directory in DIRECTORIES)
    paths = [name for name in paths if name.startswith(prefixes) and name.endswith(".sql")]
    if not paths:
        raise RuntimeError("Pinned SQL migrations are missing")
    updates = {}
    # Validate every input before touching any file. Only newline differences are accepted.
    for name in paths:
        original = git_bytes(source, "show", f"{commit}:{name}").replace(b"\r\n", b"\n")
        current = (source / name).read_bytes()
        if current.replace(b"\r\n", b"\n") != original:
            raise RuntimeError(f"Migration has edits beyond line endings: {name}")
        updates[name] = original.replace(b"\n", b"\r\n") if windows else original

    # Local checkout attributes keep Git's canonical blobs unchanged. Other source files
    # retain LF. Never change the user's global Git configuration or an existing database.
    attributes = source / ".git/info/attributes"
    previous = attributes.read_text(encoding="utf-8") if attributes.exists() else ""
    clean = re.sub(re.escape(START) + r"\n.*?" + re.escape(END) + r"\n?", "", previous, flags=re.S)
    newline = "crlf" if windows else "lf"
    rules = "\n".join(f"{prefix}*.sql text eol={newline}" for prefix in prefixes)
    updated_attributes = clean.rstrip("\n") + ("\n" if clean else "") + f"{START}\n{rules}\n{END}\n"
    if previous != updated_attributes:
        attributes.parent.mkdir(exist_ok=True)
        attributes.write_text(updated_attributes, encoding="utf-8", newline="\n")
    for name, content in updates.items():
        path = source / name
        if path.read_bytes() != content:
            path.write_bytes(content)
    checksums = {name: hashlib.sha384(content).hexdigest() for name, content in updates.items()}
    print(f"SQL migration inputs: {len(checksums)} pinned files, {newline.upper()} checksums.")
    return checksums


def verify_binary(executable: Path, checksums: dict[str, str]) -> None:
    # SQLx embeds the exact SHA-384 bytes. Detect a stale/incompatible executable before
    # publishing it, without opening the user's databases or bypassing SQLx validation.
    with executable.open("rb") as file, mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ) as binary:
        missing = [name for name, digest in checksums.items() if binary.find(bytes.fromhex(digest)) < 0]
    if missing:
        raise RuntimeError(f"Executable has incompatible migration checksums: {', '.join(missing[:3])}")
    print(f"Verified {len(checksums)} embedded SQL migration checksums in {executable.name}.")
