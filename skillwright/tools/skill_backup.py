#!/usr/bin/env python3
"""Back up Skillwright without changing its branch, index, or runtime release."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from skill_catalog import authored_skills


EXCLUDED_PARTS = {".git", ".cache", ".pytest_cache", ".venv", "__pycache__", "node_modules", "venv"}
BLOCKED_NAMES = {"auth.json", "credentials.json"}
BLOCKED_SUFFIXES = {".db", ".key", ".p12", ".pem", ".sqlite", ".sqlite3"}
SENSITIVE_NAMES = {
    ".npmrc",
    ".pypirc",
    "cookie.json",
    "cookies.json",
    "secret.json",
    "secrets.json",
    "session.json",
    "sessions.json",
    "settings.local.json",
    "runtime-state.json",
    "runtime.json",
    "token.json",
    "tokens.json",
}
SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{30,}\b"),
    re.compile(rb"\bglpat-[A-Za-z0-9_-]{20,}\b"),
    re.compile(rb"\bAIza[0-9A-Za-z_-]{35}\b"),
    re.compile(rb"\bsk-[A-Za-z0-9_-]{24,}\b"),
    re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(rb"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(rb"(?i)aws_secret_access_key\s*[:=]\s*[A-Za-z0-9/+=]{32,}"),
)
BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,128}$")
ROOT_FILES = {".gitignore", "AGENTS.md", "README.md", "STATE.md"}
ROOT_TREES = {"manifests", "tests", "tools"}


def path_env(name: str, default: str, *, resolve: bool = True) -> Path:
    path = Path(os.path.abspath(os.path.expanduser(os.environ.get(name, default))))
    return path.resolve(strict=False) if resolve else path


DOJO = path_env("SKILLS_DOJO_ROOT", "~/.foxrun/skillwright")
STATE = path_env("SKILL_STATE_ROOT", "~/.foxrun/skillwright/skill-state")
ACTIVE = path_env("SKILLS_ACTIVE_PATH", "~/.foxrun/skills", resolve=False)
RELEASES = path_env("SKILL_RELEASES_ROOT", "~/.foxrun/skillwright/skill-releases")
LOCK_PATH = path_env("SKILLS_LOCK_PATH", str(STATE / "lifecycle.lock"))
RECEIPTS = path_env("SKILLS_BACKUP_RECEIPTS", str(STATE / "backups"))
# The person's own Skillwright origin; there is no shipped default.
EXPECTED_REMOTE = os.environ.get("SKILLS_DOJO_EXPECTED_REMOTE", "")
BACKUP_BRANCH = os.environ.get("SKILLS_BACKUP_BRANCH", "backup/person-mac")
MAX_BYTES = int(os.environ.get("SKILLS_BACKUP_MAX_BYTES", "90000000"))
NOTIFY_COMMAND = os.environ.get("SKILLS_NOTIFY_COMMAND", "/usr/bin/osascript")
GIT_TIMEOUT = int(os.environ.get("SKILLS_BACKUP_GIT_TIMEOUT", "120"))
GIT_ENV = os.environ.copy()
GIT_ENV.update({"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"})


def command(
    args: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    env: dict[str, str] | None = None,
    timeout: int | None = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=cwd,
        check=check,
        env=env,
        timeout=timeout,
        text=True,
        capture_output=True,
    )


def git(*args: str, cwd: Path = DOJO, check: bool = True) -> subprocess.CompletedProcess:
    return command(
        ["git", "-C", str(cwd), *args],
        check=check,
        env=GIT_ENV,
        timeout=GIT_TIMEOUT,
    )


def sanitize_remote(value: str) -> str:
    value = value.strip()
    if "://" not in value:
        if value.startswith(("/", "~")):
            return value
        return value if value.startswith("git@github.com:") else "[REDACTED_REMOTE]"
    parts = urlsplit(value)
    host = parts.hostname or ""
    if parts.port:
        host += f":{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


def normalize_remote(value: str) -> str:
    value = sanitize_remote(value).removesuffix(".git").removesuffix("/")
    if value.startswith("git@github.com:"):
        return "https://github.com/" + value.removeprefix("git@github.com:")
    if value.startswith("ssh://git@github.com/"):
        return "https://github.com/" + value.removeprefix("ssh://git@github.com/")
    try:
        path = Path(value).expanduser().resolve(strict=False)
    except OSError:
        return value
    return str(path) if path.exists() or value.startswith(("/", "~")) else value


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def replace_receipt(target: Path, payload: dict) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, target)
    return target


def write_receipt(payload: dict) -> Path:
    target = RECEIPTS / f"{timestamp()}-{os.getpid()}.json"
    return replace_receipt(target, payload)


def notify_failure(message: str) -> None:
    try:
        if NOTIFY_COMMAND == "/usr/bin/osascript":
            script = f'display notification {json.dumps(message)} with title "Skillwright backup failed"'
            command([NOTIFY_COMMAND, "-e", script], check=False)
        else:
            command([NOTIFY_COMMAND, message], check=False)
    except OSError:
        pass


@contextmanager
def lifecycle_lock():
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"skill lifecycle lock is busy: {LOCK_PATH}") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def is_sensitive_path(relative: Path) -> bool:
    name = relative.name.lower()
    if (
        name == ".env"
        or name.startswith(".env.")
        or name in BLOCKED_NAMES
        or name in SENSITIVE_NAMES
        or name.startswith("client_secret") and name.endswith(".json")
    ):
        return True
    if relative.suffix.lower() in BLOCKED_SUFFIXES or name.endswith((".db-shm", ".db-wal", ".log")):
        return True
    return False


def is_blocked(relative: Path) -> bool:
    return any(part in EXCLUDED_PARTS for part in relative.parts) or is_sensitive_path(relative)


def is_allowed(relative: Path, tracked_roots: set[str]) -> bool:
    top = relative.parts[0]
    if top == "skills":
        return len(relative.parts) > 2 and (authored_skills(DOJO) / relative.parts[1] / "SKILL.md").is_file()
    if top in tracked_roots:
        return True
    if len(relative.parts) == 1 and top in ROOT_FILES:
        return True
    if top in ROOT_TREES:
        return True
    return (DOJO / top / "SKILL.md").is_file()


def source_files() -> list[Path]:
    tracked_roots = set(git("ls-tree", "--name-only", "HEAD").stdout.splitlines())
    ignored = git("ls-files", "-o", "-i", "--exclude-standard", "-z")
    for raw in ignored.stdout.split("\0"):
        # An ignored log never enters a snapshot; ignored credential files still stop the backup.
        if raw and not raw.endswith(".log") and is_sensitive_path(Path(raw)):
            raise RuntimeError(f"ignored sensitive path in Skillwright: {raw}")
    tracked = set(git("ls-files", "-z").stdout.split("\0"))
    result = git("ls-files", "-co", "--exclude-standard", "-z")
    files = []
    for raw in result.stdout.split("\0"):
        if not raw:
            continue
        relative = Path(raw)
        if is_sensitive_path(relative):
            raise RuntimeError(f"sensitive path in Skillwright snapshot: {relative}")
        if is_blocked(relative):
            raise RuntimeError(f"blocked path in Skillwright snapshot: {relative}")
        # The allowlist gates untracked files; a tracked file is already in the repo's history.
        if raw not in tracked and not is_allowed(relative, tracked_roots):
            raise RuntimeError(f"path is not allowlisted for Skillwright backup: {relative}")
        source = DOJO / relative
        if source.is_file() and not source.is_symlink() and source.stat().st_size > MAX_BYTES:
            raise RuntimeError(f"oversized file in Skillwright snapshot: {relative}")
        if source.exists() or source.is_symlink():
            files.append(relative)
    return sorted(set(files), key=lambda path: path.as_posix())


def files_requiring_secret_scan() -> set[Path]:
    changed: set[Path] = set()
    commands = (
        ("ls-files", "-o", "--exclude-standard", "-z"),
        ("diff", "--name-only", "-z"),
        ("diff", "--cached", "--name-only", "-z"),
    )
    for args in commands:
        for raw in git(*args).stdout.split("\0"):
            if raw:
                changed.add(Path(raw))
    return changed


def source_fingerprints(files: list[Path]) -> dict[Path, str]:
    fingerprints: dict[Path, str] = {}
    for relative in files:
        source = DOJO / relative
        source_info = source.lstat()
        if stat.S_ISLNK(source_info.st_mode):
            fingerprints[relative] = "symlink:" + os.readlink(source)
            continue
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(source, flags)
        try:
            current_info = os.fstat(descriptor)
            if not stat.S_ISREG(current_info.st_mode):
                raise RuntimeError(f"unsupported source type while fingerprinting: {relative}")
            digest = hashlib.sha256()
            total = 0
            while chunk := os.read(descriptor, 1024 * 1024):
                total += len(chunk)
                if total > MAX_BYTES:
                    raise RuntimeError(f"oversized file in Skillwright snapshot: {relative}")
                digest.update(chunk)
            final_info = os.fstat(descriptor)
            if (
                final_info.st_size,
                final_info.st_mtime_ns,
                final_info.st_ctime_ns,
            ) != (
                current_info.st_size,
                current_info.st_mtime_ns,
                current_info.st_ctime_ns,
            ):
                raise RuntimeError(f"source changed while fingerprinting: {relative}")
            fingerprints[relative] = "file:" + digest.hexdigest()
        finally:
            os.close(descriptor)
    return fingerprints


def preflight() -> dict:
    if not BRANCH_RE.fullmatch(BACKUP_BRANCH):
        raise RuntimeError(f"unsafe backup branch: {BACKUP_BRANCH}")
    if not BACKUP_BRANCH.startswith("backup/"):
        raise RuntimeError(f"backup branch must use the backup/ namespace: {BACKUP_BRANCH}")
    if git("check-ref-format", "--branch", BACKUP_BRANCH, check=False).returncode != 0:
        raise RuntimeError(f"invalid backup branch: {BACKUP_BRANCH}")
    if not (DOJO / ".git").is_dir():
        raise RuntimeError(f"Skillwright is not a normal Git clone: {DOJO}")
    resolved_active = ACTIVE.resolve(strict=False)
    if DOJO == resolved_active or (DOJO / ".release-manifest.json").is_file() or RELEASES in DOJO.parents:
        raise RuntimeError(f"refusing Skillwright runtime path: {DOJO}")
    if git("rev-parse", "--is-inside-work-tree").stdout.strip() != "true":
        raise RuntimeError(f"Skillwright is not a Git work tree: {DOJO}")
    branch = git("branch", "--show-current").stdout.strip()
    if not branch:
        raise RuntimeError("Skillwright HEAD is detached")
    if branch != "main":
        raise RuntimeError(f"Skillwright must remain on protected branch main, found {branch}")
    conflicts = git("diff", "--name-only", "--diff-filter=U").stdout.strip()
    if conflicts:
        raise RuntimeError(f"Skillwright has unresolved conflict paths: {conflicts}")
    for state_name in (
        "MERGE_HEAD",
        "CHERRY_PICK_HEAD",
        "REVERT_HEAD",
        "rebase-merge",
        "rebase-apply",
    ):
        state_path = Path(git("rev-parse", "--git-path", state_name).stdout.strip())
        if not state_path.is_absolute():
            state_path = DOJO / state_path
        if state_path.exists():
            raise RuntimeError(f"Skillwright has an unfinished Git operation: {state_name}")
    remote = git("remote", "get-url", "origin").stdout.strip()
    if not EXPECTED_REMOTE:
        raise RuntimeError("set SKILLS_DOJO_EXPECTED_REMOTE to the Skillwright origin")
    if normalize_remote(remote) != normalize_remote(EXPECTED_REMOTE):
        raise RuntimeError(f"unexpected Skillwright origin: {sanitize_remote(remote)}")
    upstream_name = git("rev-parse", "--abbrev-ref", "@{u}").stdout.strip()
    if upstream_name != "origin/main":
        raise RuntimeError(f"Skillwright main must track origin/main, found {upstream_name}")
    head = git("rev-parse", "HEAD").stdout.strip()
    upstream = git("rev-parse", "@{u}").stdout.strip()
    if head != upstream:
        raise RuntimeError("Skillwright main is not synchronized with origin/main")
    return {
        "branch": branch,
        "head": head,
        "origin": sanitize_remote(remote),
        "origin_for_clone": remote,
        "upstream": upstream,
        "source_status": git("status", "--porcelain=v1", "--untracked-files=all").stdout.splitlines(),
    }


def clear_worktree(clone: Path) -> None:
    for child in clone.iterdir():
        if child.name == ".git":
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()


def copy_snapshot(
    clone: Path,
    files: list[Path],
    secret_scan_files: set[Path],
    expected_fingerprints: dict[Path, str],
) -> None:
    clear_worktree(clone)
    for relative in files:
        source = DOJO / relative
        destination = clone / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        source_info = source.lstat()
        if stat.S_ISLNK(source_info.st_mode):
            target = os.readlink(source)
            if "symlink:" + target != expected_fingerprints[relative]:
                raise RuntimeError(f"source changed before snapshotting symlink: {relative}")
            current_info = source.lstat()
            if (current_info.st_dev, current_info.st_ino) != (source_info.st_dev, source_info.st_ino):
                raise RuntimeError(f"source changed while snapshotting symlink: {relative}")
            destination.symlink_to(target)
            continue
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(source, flags)
        try:
            current_info = os.fstat(descriptor)
            if not stat.S_ISREG(current_info.st_mode):
                raise RuntimeError(f"unsupported source type while snapshotting: {relative}")
            if current_info.st_size > MAX_BYTES:
                raise RuntimeError(f"oversized file in Skillwright snapshot: {relative}")
            with os.fdopen(descriptor, "rb", closefd=False) as source_handle:
                payload = source_handle.read(MAX_BYTES + 1)
            if len(payload) > MAX_BYTES:
                raise RuntimeError(f"file grew past size limit while snapshotting: {relative}")
            if relative in secret_scan_files and any(pattern.search(payload) for pattern in SECRET_PATTERNS):
                raise RuntimeError(f"credential-like content in Skillwright snapshot: {relative}")
            if "file:" + hashlib.sha256(payload).hexdigest() != expected_fingerprints[relative]:
                raise RuntimeError(f"source changed before snapshotting file: {relative}")
            final_info = os.fstat(descriptor)
            if (
                final_info.st_size,
                final_info.st_mtime_ns,
                final_info.st_ctime_ns,
            ) != (
                current_info.st_size,
                current_info.st_mtime_ns,
                current_info.st_ctime_ns,
            ):
                raise RuntimeError(f"source changed while snapshotting file: {relative}")
            destination.write_bytes(payload)
            os.chmod(destination, stat.S_IMODE(current_info.st_mode))
            os.utime(destination, ns=(current_info.st_atime_ns, current_info.st_mtime_ns))
        finally:
            os.close(descriptor)


def snapshot(
    preflight_data: dict,
    files: list[Path],
    secret_scan_files: set[Path],
    expected_fingerprints: dict[Path, str],
) -> dict:
    with tempfile.TemporaryDirectory(prefix="skill_backup.py-") as temporary:
        clone = Path(temporary) / "clone"
        command(
            ["git", "clone", "--quiet", "--no-checkout", preflight_data["origin_for_clone"], str(clone)],
            env=GIT_ENV,
            timeout=GIT_TIMEOUT,
        )
        remote_main = git("rev-parse", "refs/remotes/origin/main", cwd=clone).stdout.strip()
        if remote_main != preflight_data["head"]:
            raise RuntimeError("Skillwright main is stale or divergent from remote origin/main")
        remote_branch = git("show-ref", "--verify", f"refs/remotes/origin/{BACKUP_BRANCH}", cwd=clone, check=False)
        remote_exists = remote_branch.returncode == 0
        if remote_exists:
            git("switch", "--quiet", "-C", BACKUP_BRANCH, f"origin/{BACKUP_BRANCH}", cwd=clone)
        else:
            git("switch", "--quiet", "-c", BACKUP_BRANCH, "origin/main", cwd=clone)
        copy_snapshot(clone, files, secret_scan_files, expected_fingerprints)
        postflight_data = preflight()
        if (
            postflight_data["head"] != preflight_data["head"]
            or postflight_data["source_status"] != preflight_data["source_status"]
            or source_files() != files
            or files_requiring_secret_scan() != secret_scan_files
            or source_fingerprints(files) != expected_fingerprints
        ):
            raise RuntimeError("Skillwright source changed during backup; no snapshot was pushed")
        git("add", "-A", cwd=clone)
        if git("diff", "--cached", "--quiet", cwd=clone, check=False).returncode == 0:
            commit = git("rev-parse", "HEAD", cwd=clone).stdout.strip()
            if not remote_exists:
                git("push", "--quiet", "origin", f"HEAD:refs/heads/{BACKUP_BRANCH}", cwd=clone)
                return {"result": "pushed", "commit": commit, "remote_main": remote_main}
            return {"result": "no_changes", "commit": commit, "remote_main": remote_main}
        git("config", "user.name", "Skillwright Backup", cwd=clone)
        git("config", "user.email", "skill_backup.py@localhost", cwd=clone)
        # The time only: a host name would tell the remote which machine this is.
        message = f"backup: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %Z')}"
        git("commit", "--quiet", "--no-gpg-sign", "-m", message, cwd=clone)
        git("push", "--quiet", "origin", f"HEAD:refs/heads/{BACKUP_BRANCH}", cwd=clone)
        return {
            "result": "pushed",
            "commit": git("rev-parse", "HEAD", cwd=clone).stdout.strip(),
            "remote_main": remote_main,
        }


def run_backup() -> int:
    started = datetime.now(timezone.utc).isoformat()
    context = {"started_at": started, "dojo": str(DOJO), "backup_branch": BACKUP_BRANCH}
    receipt: Path | None = None
    try:
        with lifecycle_lock():
            preflight_data = preflight()
            files = source_files()
            secret_scan_files = files_requiring_secret_scan()
            fingerprints = source_fingerprints(files)
            receipt = write_receipt(context | {"status": "in_progress"})
            result = snapshot(preflight_data, files, secret_scan_files, fingerprints)
            replace_receipt(
                receipt,
                context
                | {key: value for key, value in preflight_data.items() if key != "origin_for_clone"}
                | result
                | {"status": "success", "file_count": len(files), "finished_at": datetime.now(timezone.utc).isoformat()}
            )
    except Exception as exc:
        message = str(exc)
        failure = context | {
            "status": "failure",
            "error": message,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            receipt = replace_receipt(receipt, failure) if receipt else write_receipt(failure)
        except OSError as receipt_error:
            message = f"{message}; receipt storage unavailable: {receipt_error}"
        notify_failure(message)
        receipt_label = str(receipt) if receipt and receipt.exists() else "unavailable"
        print(f"skill_backup.py: {message}; receipt={receipt_label}", file=sys.stderr)
        return 1
    if result["result"] == "no_changes":
        print(f"skill_backup.py: no changes; receipt={receipt}")
    else:
        print(f"skill_backup.py: backup complete commit={result['commit']}; receipt={receipt}")
    return 0


def person_root() -> Path | None:
    """The person's own skill repo, backed up beside the Skillwright (T675).

    SKILLS_PERSON_ROOT names it; an empty value turns it off. Without it, only the
    installed Dojo uses <portfolio>/skillwright, so an isolated Dojo never reads it.
    """
    value = os.environ.get("SKILLS_PERSON_ROOT")
    if value is not None:
        return path_env("SKILLS_PERSON_ROOT", value) if value else None
    if DOJO != Path("~/.foxrun/skillwright").expanduser().resolve(strict=False):
        return None
    candidate = Path(os.environ.get("FOXRUN_PORTFOLIO", "~/foxrun")).expanduser().resolve(strict=False) / "skillwright"
    return candidate if (candidate / "skills").is_dir() else None


def run_all() -> int:
    """Back up the Skillwright, then the person's skill repo in its own run and receipt."""
    code = run_backup()
    person = person_root()
    if person is None or person == DOJO:
        return code
    remote = os.environ.get("SKILLS_PERSON_EXPECTED_REMOTE", "")
    if not remote:
        message = f"set SKILLS_PERSON_EXPECTED_REMOTE to the origin of {person}"
        notify_failure(message)
        print(f"skill_backup.py: {message}", file=sys.stderr)
        return 1
    env = dict(os.environ, SKILLS_DOJO_ROOT=str(person), SKILLS_PERSON_ROOT="",
               SKILLS_DOJO_EXPECTED_REMOTE=remote)
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "run"], env=env)
    return code or result.returncode


def self_test() -> int:
    result = command(
        [sys.executable, "-m", "unittest", "tests.test_backup"], cwd=DOJO, check=False
    )
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    sub = result.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="create an isolated backup snapshot")
    sub.add_parser("self-test", help="run the disposable backup test suite")
    return result


def main() -> int:
    args = parser().parse_args()
    if args.command == "self-test":
        return self_test()
    if args.command == "run":
        return run_all()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
