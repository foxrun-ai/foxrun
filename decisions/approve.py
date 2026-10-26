#!/usr/bin/env python3
"""Plan, attest, record, lint, and recover bounded document promotions."""
from __future__ import annotations

import sys as _person_sys
from pathlib import Path as _PersonPath
_person_root = next(p for p in _PersonPath(__file__).resolve().parents if (p / "base/person.py").is_file())
_person_sys.path.insert(0, str(_person_root))
import os as _person_os
_person_os.environ.setdefault('FOXRUN_HOME', str(_person_root))
from base import person as _fox_person
from base.paths import resolve_portfolio_path

import argparse
import base64
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, TextIO
from urllib.parse import quote
sys.path.insert(0, str(Path(__file__).resolve().parent / '../events'))
from history_actions import write_history

FORMAT = "foxrun-document-approval-plan/v1"
PRIVATE_FORMAT = "foxrun-document-approval-plan/v2-private-control"
IDENTITY_FORMAT = "foxrun-agent-team-identity-approval-plan/v1-private-control"
JOURNAL_FORMAT = "foxrun-document-approval-journal/v1"
REPORT_FORMAT = "foxrun-document-approval-lint/v1"
SOURCE = "approve cli"
TRUST_BOUNDARY = "The caller must possess actual exact-version approval. This plan and CLI do not authenticate the approval transport."
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
MAX_ITEMS = 64
SAFE_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@:-]{0,127}$")
STATUS = re.compile(r"^status\s*:\s*(.*)$", re.IGNORECASE)
STAGED_TAG = re.compile(r"^tags\s*:\s*\[\s*staged\s*\]\s*$", re.IGNORECASE)
TRANSFORMS = {"none", "remove-status", "remove-staged-tag"}
IDENTITY_MODE = "agent-team-identity-source"
IDENTITY_PATH = re.compile(r"^agents/[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
REFUSED_PARTS = {
    ".git", ".claude", ".codex", ".hermes", ".config", ".ssh",
    "runtime", "runtimes", "auth", "credentials", "secrets",
}
APPROVAL_COLUMNS = (
    "id", "subject_type", "subject_id", "version", "call",
    "person_words", "given_at", "source",
)
ACTIVITY_COLUMNS = (
    "id", "subject_type", "subject_id", "field", "old_value", "new_value",
    "actor", "source", "at", "note",
)
SUPPORTED_TABLE_SQL = {
    "approvals": "CREATE TABLE approvals ( id INTEGER PRIMARY KEY AUTOINCREMENT, subject_type TEXT NOT NULL, subject_id TEXT NOT NULL, version TEXT, call TEXT NOT NULL CHECK (call IN ('approve','discuss','wrong','edit')), person_words TEXT, given_at TEXT NOT NULL, source TEXT)",
    "activity": "CREATE TABLE activity ( id INTEGER PRIMARY KEY AUTOINCREMENT, subject_type TEXT NOT NULL, subject_id TEXT NOT NULL, field TEXT, old_value TEXT, new_value TEXT, actor TEXT NOT NULL, source TEXT, at TEXT NOT NULL, note TEXT)",
}
ACTIVITY_COLUMNS_T309 = ACTIVITY_COLUMNS + ("verb",)
SUPPORTED_ACTIVITY_SQL_T309 = SUPPORTED_TABLE_SQL["activity"][:-1] + ", verb TEXT)"


class ApproveError(ValueError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_hash(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def canonical(path: Path) -> Path:
    try:
        return resolve_portfolio_path(path)
    except ValueError:
        # Existing callers report the precise refusal for unsafe links.
        return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def symlink_component(path: Path) -> Path | None:
    path = canonical(path)
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            return current
    return None


def regular_file(path: Path, label: str) -> Path:
    path = canonical(path)
    if symlink_component(path):
        raise ApproveError(f"{label} crosses a symlink boundary: {path}")
    try:
        status = os.stat(path, follow_symlinks=False)
    except FileNotFoundError as exc:
        raise ApproveError(f"{label} must already exist: {path}") from exc
    if not stat.S_ISREG(status.st_mode):
        raise ApproveError(f"{label} is not a regular file: {path}")
    if status.st_nlink != 1:
        raise ApproveError(f"{label} has hard links: {path}")
    return path


def root_path(value: Path) -> Path:
    root = canonical(value)
    if symlink_component(root) or not root.is_dir():
        raise ApproveError(f"root must be an existing non-symlink directory: {root}")
    if root == Path(root.anchor):
        raise ApproveError("filesystem root is not an allowed document root")
    return root


def directory_identity(path: Path) -> dict[str, int]:
    status = os.stat(path, follow_symlinks=False)
    return {"device": status.st_dev, "inode": status.st_ino}


def separate_roots(root: Path, control_root: Path) -> None:
    if (
        directory_identity(root) == directory_identity(control_root)
        or root.is_relative_to(control_root)
        or control_root.is_relative_to(root)
    ):
        raise ApproveError("document root and private control root must be separate non-overlapping directories")


def relative_document(root: Path, value: str, label: str, *, must_exist: bool) -> tuple[str, Path]:
    raw = Path(value)
    if not value or raw.is_absolute() or ".." in raw.parts:
        raise ApproveError(f"{label} must be a relative path below root: {value}")
    normalized = Path(*[part for part in raw.parts if part not in ("", ".")])
    if not normalized.parts or normalized.suffix.lower() != ".md":
        raise ApproveError(f"{label} must be a Markdown document: {value}")
    if any(part.lower() in REFUSED_PARTS or part.startswith(".") for part in normalized.parts):
        raise ApproveError(f"{label} targets a refused runtime, config, or hidden path: {value}")
    path = canonical(root / normalized)
    if path != root and not path.is_relative_to(root):
        raise ApproveError(f"{label} escapes root: {value}")
    if symlink_component(path):
        raise ApproveError(f"{label} crosses a symlink boundary: {value}")
    if not path.parent.is_dir() or symlink_component(path.parent):
        raise ApproveError(f"{label} parent must already exist and contain no symlink: {value}")
    if must_exist:
        regular_file(path, label)
    elif path.exists() or path.is_symlink():
        regular_file(path, label)
    return normalized.as_posix(), path


def relative_control(root: Path, value: str, label: str, *, must_exist: bool = False) -> tuple[str, Path]:
    raw = Path(value)
    if not value or raw.is_absolute() or ".." in raw.parts:
        raise ApproveError(f"{label} must be a relative path below root: {value}")
    normalized = Path(*[part for part in raw.parts if part not in ("", ".")])
    if not normalized.parts:
        raise ApproveError(f"{label} must name a path below root: {value}")
    path = canonical(root / normalized)
    if path != root and not path.is_relative_to(root):
        raise ApproveError(f"{label} escapes root: {value}")
    if symlink_component(path) or not path.parent.is_dir() or symlink_component(path.parent):
        raise ApproveError(f"{label} crosses a symlink or missing parent: {value}")
    if must_exist:
        regular_file(path, label)
    return normalized.as_posix(), path


def identity(path: Path) -> dict[str, int]:
    status = os.stat(path, follow_symlinks=False)
    return {
        "device": status.st_dev, "inode": status.st_ino,
        "size": status.st_size, "mtime_ns": status.st_mtime_ns,
    }


def read_sealed(path: Path, label: str) -> tuple[bytes, dict[str, int]]:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ApproveError(f"{label} is not a single-link regular file: {path}")
        data = bytearray()
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            data.extend(block)
            if len(data) > MAX_DOCUMENT_BYTES:
                raise ApproveError(f"{label} exceeds {MAX_DOCUMENT_BYTES} bytes: {path}")
        after = os.fstat(descriptor)
        before_id = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        after_id = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        if before_id != after_id:
            raise ApproveError(f"{label} changed while read: {path}")
        return bytes(data), {
            "device": after.st_dev, "inode": after.st_ino,
            "size": after.st_size, "mtime_ns": after.st_mtime_ns,
        }
    finally:
        os.close(descriptor)


def proposed_document(source: bytes, label: str, transform: str) -> tuple[bytes, bool]:
    if transform not in TRANSFORMS:
        raise ApproveError(f"unsupported explicit transform: {transform}")
    try:
        text = source.decode("utf-8")
    except UnicodeError as exc:
        raise ApproveError(f"{label} must be UTF-8") from exc
    lines = text.splitlines(keepends=True)
    if transform == "none":
        return source, False
    if not lines or lines[0].lstrip("\ufeff").strip() != "---":
        raise ApproveError(f"{label} cannot apply {transform} without frontmatter")
    end = next((index for index in range(1, len(lines)) if lines[index].strip() in {"---", "..."}), None)
    if end is None:
        raise ApproveError(f"{label} frontmatter has no closing delimiter")
    matches = []
    for index in range(1, end):
        if lines[index].startswith((" ", "\t")):
            continue
        value = lines[index].rstrip("\r\n")
        if transform == "remove-status":
            match = STATUS.match(value)
            if match:
                matches.append((index, match.group(1).strip()))
        elif STAGED_TAG.match(value):
            matches.append((index, "staged"))
    if len(matches) > 1:
        raise ApproveError(f"{label} has duplicate metadata for {transform}")
    if not matches:
        raise ApproveError(f"{label} does not contain metadata required by {transform}")
    index, value = matches[0]
    if transform == "remove-status" and value in {"", "|", ">", "|-", ">-", "|+", ">+"}:
        raise ApproveError(f"{label} has unsupported multiline status metadata")
    del lines[index]
    return "".join(lines).encode("utf-8"), True


def unified_diff(before: bytes, after: bytes, before_label: str, after_label: str) -> str:
    try:
        before_text = before.decode("utf-8")
        after_text = after.decode("utf-8")
    except UnicodeError as exc:
        raise ApproveError("documents must be UTF-8 for readable diffs") from exc
    return "".join(difflib.unified_diff(
        before_text.splitlines(keepends=True), after_text.splitlines(keepends=True),
        fromfile=before_label, tofile=after_label,
    ))


def diff_text(prior: bytes | None, source: bytes, proposed: bytes, live: str, draft: str) -> str:
    before = b"" if prior is None else prior
    sections = []
    if source != proposed:
        sections.append(unified_diff(source, proposed, draft, draft + " (after explicit transform)"))
    sections.append(unified_diff(
        before, proposed, live + " (absent)" if prior is None else live,
        live + " (proposed)",
    ))
    return "".join(sections)


def connect_db(path: Path, *, readonly: bool) -> sqlite3.Connection:
    database = regular_file(path, "database")
    mode = "ro" if readonly else "rw"
    con = _fox_person.connect("file:" + quote(str(database), safe="/:@") + "?mode=" + mode, uri=True, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    if con.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        con.close()
        raise ApproveError("foreign-key enforcement is unavailable")
    validate_schema(con)
    return con


def validate_schema(con: sqlite3.Connection) -> None:
    for table, expected in (("approvals", APPROVAL_COLUMNS), ("activity", ACTIVITY_COLUMNS)):
        definition = con.execute("SELECT type,sql FROM sqlite_schema WHERE name=?", (table,)).fetchone()
        # This writer supports the reviewed work-module definitions only.
        # Column names alone can hide a non-integer ID or conflict-replace rule.
        allowed_sql = {SUPPORTED_TABLE_SQL[table]}
        if table == "activity":
            allowed_sql.add(SUPPORTED_ACTIVITY_SQL_T309)
        if definition is None or definition[0] != "table" or " ".join(definition[1].split()) not in allowed_sql:
            raise ApproveError(f"unsupported work schema definition for table: {table}")
        actual = tuple(str(row[1]) for row in con.execute(f'PRAGMA table_info("{table}")'))
        if actual != expected and not (table == "activity" and actual == ACTIVITY_COLUMNS_T309):
            raise ApproveError(f"unsupported work schema for table: {table}")
    triggers = list(con.execute(
        "SELECT name FROM sqlite_schema WHERE type='trigger' AND tbl_name IN ('approvals','activity') ORDER BY name"
    ))
    if triggers:
        raise ApproveError("unreviewed write-side triggers on approvals or activity are unsupported")


def schema_hash(con: sqlite3.Connection) -> str:
    value: dict[str, Any] = {}
    for table in ("approvals", "activity"):
        value[table] = {
            "columns": [str(item[1]) for item in con.execute(f'PRAGMA table_info("{table}")')],
            "objects": [
                {"type": str(item[0]), "name": str(item[1]), "sql": item[2]}
                for item in con.execute(
                    "SELECT type,name,sql FROM sqlite_schema "
                    "WHERE tbl_name=? AND type IN ('table','index','trigger') ORDER BY type,name",
                    (table,),
                )
            ],
        }
    return sha256_bytes(canonical_json(value))


def database_state_hash(con: sqlite3.Connection) -> str:
    value = {}
    for table in ("approvals", "activity"):
        value[table] = [dict(row) for row in con.execute(f'SELECT * FROM "{table}" ORDER BY id')]
    return sha256_bytes(canonical_json(value))


def foreign_key_findings_hash(con: sqlite3.Connection) -> str:
    return sha256_bytes(canonical_json([tuple(row) for row in con.execute("PRAGMA foreign_key_check")]))


def plan_digest(plan: dict[str, Any]) -> str:
    payload = {key: value for key, value in plan.items() if key != "plan_digest"}
    return sha256_bytes(canonical_json(payload))


def parse_item(value: str) -> tuple[str, str, str]:
    parts = value.split("::")
    if len(parts) not in {2, 3}:
        raise ApproveError("item must use DRAFT::LIVE or DRAFT::LIVE::TRANSFORM")
    draft, live = parts[:2]
    transform = parts[2] if len(parts) == 3 else "none"
    if not draft or not live:
        raise ApproveError("item must use nonempty DRAFT::LIVE paths")
    if transform not in TRANSFORMS:
        raise ApproveError(f"unsupported explicit transform: {transform}")
    return draft, live, transform


def is_private_format(plan: dict[str, Any]) -> bool:
    return plan.get("format") in {PRIVATE_FORMAT, IDENTITY_FORMAT}


def is_identity_plan(plan: dict[str, Any]) -> bool:
    return plan.get("format") == IDENTITY_FORMAT


def validate_identity_root_and_item(root: Path, live: str, transform: str) -> None:
    if root.name != "agent-team":
        raise ApproveError("identity-source root must be the agent-team repository root")
    if not IDENTITY_PATH.fullmatch(live):
        raise ApproveError("identity-source target must be agents/<safe-id>.md")
    if transform != "none":
        raise ApproveError("identity-source approval does not support document transforms")


def refuse_implicit_identity_target(root: Path, live: str) -> None:
    if root.name == "agent-team" and IDENTITY_PATH.fullmatch(live):
        raise ApproveError("agent-team identity sources require explicit identity-source mode")


def approval_subject(plan: dict[str, Any], item: dict[str, Any]) -> tuple[str, str]:
    if is_identity_plan(plan):
        return item["subject_type"], item["subject_id"]
    return "document", item["live"]


def validate_requested_mode(plan: dict[str, Any], identity_source: bool) -> None:
    if is_identity_plan(plan) != identity_source:
        raise ApproveError("identity-source mode does not match the sealed plan")


def build_plan(
    *, root: Path, database: Path, items: Iterable[tuple[str, str] | tuple[str, str, str]],
    archive_root: str, journal: str, control_root: Path | None = None,
    identity_source: bool = False,
    clock: Callable[[], str] = now,
) -> dict[str, Any]:
    root = root_path(root)
    if identity_source and control_root is None:
        raise ApproveError("identity-source mode requires a private control root")
    private = control_root is not None
    control = root_path(control_root) if control_root is not None else root
    if private:
        separate_roots(root, control)
    database = regular_file(database, "database")
    item_values = list(items)
    if not item_values or len(item_values) > MAX_ITEMS:
        raise ApproveError(f"plan needs 1-{MAX_ITEMS} items")
    archive_relative, archive_dir = relative_control(control, archive_root, "archive root")
    if not archive_dir.is_dir():
        raise ApproveError("archive root must already exist")
    journal_relative, journal_path = relative_control(control, journal, "recovery journal")
    if journal_path.exists() or journal_path.is_symlink():
        raise ApproveError("recovery journal already exists")

    planned = []
    seen_drafts: set[str] = set()
    seen_live: set[str] = set()
    seen_inodes: set[tuple[int, int]] = set()
    seen_archives: set[str] = set()
    for raw_item in item_values:
        draft_value, live_value = raw_item[:2]
        transform = raw_item[2] if len(raw_item) == 3 else "none"
        draft_rel, draft_path = relative_document(control, draft_value, "draft", must_exist=True)
        live_rel, live_path = relative_document(root, live_value, "live target", must_exist=False)
        if identity_source:
            validate_identity_root_and_item(root, live_rel, transform)
        else:
            refuse_implicit_identity_target(root, live_rel)
        if not private and draft_rel == live_rel:
            raise ApproveError("draft and live target must differ")
        if draft_rel in seen_drafts or live_rel in seen_live:
            raise ApproveError("conflicting draft or live document path")
        if Path(draft_rel).is_relative_to(Path(archive_relative)):
            raise ApproveError(f"draft path conflicts with archive root: {draft_rel}")
        if not private and Path(live_rel).is_relative_to(Path(archive_relative)):
            raise ApproveError(f"document path conflicts with archive root: {live_rel}")
        seen_drafts.add(draft_rel)
        seen_live.add(live_rel)
        draft_bytes, draft_identity = read_sealed(draft_path, "draft")
        proposed, transform_applied = proposed_document(draft_bytes, draft_rel, transform)
        inode = (draft_identity["device"], draft_identity["inode"])
        if inode in seen_inodes:
            raise ApproveError("documents share an inode")
        seen_inodes.add(inode)
        if live_path.exists():
            prior, prior_identity = read_sealed(live_path, "live target")
            live_inode = (prior_identity["device"], prior_identity["inode"])
            if live_inode in seen_inodes:
                raise ApproveError("draft and live paths share an inode")
            seen_inodes.add(live_inode)
            prior_hash = sha256_bytes(prior)
            archive_name = sha256_bytes(live_rel.encode("utf-8"))[:20] + "." + prior_hash + ".prior"
            archive_path = archive_dir / archive_name
            if archive_path.exists() or archive_path.is_symlink():
                raise ApproveError(f"archive collision: {archive_path}")
            archive_rel = (Path(archive_relative) / archive_name).as_posix()
            if archive_rel in seen_archives:
                raise ApproveError(f"conflicting archive path: {archive_rel}")
            seen_archives.add(archive_rel)
            prior_b64 = base64.b64encode(prior).decode("ascii")
        else:
            prior = None
            prior_identity = None
            prior_hash = None
            prior_b64 = None
            archive_rel = None
        planned_item = {
            "draft": draft_rel, "draft_sha256": sha256_bytes(draft_bytes),
            "draft_identity": draft_identity, "draft_bytes": len(draft_bytes),
            "live": live_rel, "prior_exists": prior is not None,
            "prior_sha256": prior_hash, "prior_identity": prior_identity,
            "prior_base64": prior_b64, "proposed_sha256": sha256_bytes(proposed),
            "proposed_base64": base64.b64encode(proposed).decode("ascii"),
            "proposed_bytes": len(proposed), "transform": transform,
            "transform_applied": transform_applied,
            "archive": archive_rel,
            "diff": diff_text(prior, draft_bytes, proposed, live_rel, draft_rel),
        }
        if identity_source:
            planned_item["subject_type"] = "contract"
            planned_item["subject_id"] = "agent-team/" + live_rel
        planned.append(planned_item)
    if (
        journal_relative in seen_drafts
        or archive_relative in seen_drafts
        or (not private and (journal_relative in seen_live or archive_relative in seen_live))
        or Path(journal_relative).is_relative_to(Path(archive_relative))
    ):
        raise ApproveError("control paths conflict with document paths")
    with connect_db(database, readonly=True) as con:
        db_binding = {
            "path": str(database), "identity": identity(database),
            "file_sha256": file_hash(database), "schema_sha256": schema_hash(con),
            "state_sha256": database_state_hash(con),
            "foreign_key_findings_sha256": foreign_key_findings_hash(con),
        }
    plan = {
        "format": IDENTITY_FORMAT if identity_source else (PRIVATE_FORMAT if private else FORMAT),
        "created_at": clock(),
        "root": str(root), "root_identity": directory_identity(root),
        "database": db_binding, "archive_root": archive_relative,
        "journal": journal_relative, "items": planned,
        "trust_boundary": TRUST_BOUNDARY,
    }
    if private:
        plan["control_root"] = str(control)
        plan["control_root_identity"] = directory_identity(control)
    if identity_source:
        plan["approval_mode"] = IDENTITY_MODE
    plan["plan_digest"] = plan_digest(plan)
    return plan


def exclusive_write(path: Path, data: bytes, label: str) -> dict[str, int]:
    if symlink_component(path) or not path.parent.is_dir() or symlink_component(path.parent):
        raise ApproveError(f"unsafe {label} path: {path}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise ApproveError(f"{label} already exists: {path}") from exc
    try:
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
        status = os.fstat(descriptor)
        return {"device": status.st_dev, "inode": status.st_ino, "size": status.st_size, "mtime_ns": status.st_mtime_ns}
    finally:
        os.close(descriptor)


def atomic_replace(path: Path, data: bytes, label: str) -> dict[str, int]:
    if symlink_component(path) or not path.parent.is_dir() or symlink_component(path.parent):
        raise ApproveError(f"unsafe {label} path: {path}")
    descriptor, raw_temp = tempfile.mkstemp(prefix="." + path.name + ".approve-", dir=path.parent)
    temp = Path(raw_temp)
    temp_identity = None
    try:
        os.fchmod(descriptor, 0o600)
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
        status = os.fstat(descriptor)
        temp_identity = (status.st_dev, status.st_ino)
        os.close(descriptor)
        descriptor = -1
        os.replace(temp, path)
        return identity(path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temp.exists() and temp_identity is not None:
            status = os.stat(temp, follow_symlinks=False)
            if (status.st_dev, status.st_ino) == temp_identity:
                temp.unlink()


def write_json_exclusive(path: Path, value: dict[str, Any], label: str) -> None:
    exclusive_write(path, json.dumps(value, indent=2, ensure_ascii=False).encode("utf-8") + b"\n", label)


def update_journal(path: Path, journal: dict[str, Any], expected_sha256: str) -> str:
    current = regular_file(path, "recovery journal")
    if file_hash(current) != expected_sha256:
        raise ApproveError("recovery journal changed concurrently")
    data = json.dumps(journal, indent=2, ensure_ascii=False).encode("utf-8") + b"\n"
    atomic_replace(path, data, "recovery journal")
    return sha256_bytes(data)


def load_plan(path: Path) -> dict[str, Any]:
    path = regular_file(path, "plan")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ApproveError("plan is not valid JSON") from exc
    validate_plan_object(value)
    return value


def exact_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise ApproveError(f"{label} has unsupported fields")
    return value


def exact_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def validate_identity_shape(value: Any, label: str) -> None:
    identity_value = exact_keys(value, {"device", "inode", "size", "mtime_ns"}, label)
    if not all(exact_int(identity_value[key]) and identity_value[key] >= 0 for key in identity_value):
        raise ApproveError(f"{label} contains invalid values")


def validate_plan_structure(plan: dict[str, Any]) -> None:
    common_keys = {
        "format", "created_at", "root", "root_identity", "database", "archive_root",
        "journal", "items", "trust_boundary", "plan_digest",
    }
    if plan.get("format") == FORMAT:
        exact_keys(plan, common_keys, "plan")
    elif plan.get("format") == PRIVATE_FORMAT:
        exact_keys(plan, common_keys | {"control_root", "control_root_identity"}, "plan")
    elif plan.get("format") == IDENTITY_FORMAT:
        exact_keys(
            plan,
            common_keys | {"control_root", "control_root_identity", "approval_mode"},
            "plan",
        )
    else:
        raise ApproveError("plan format is invalid or stale")
    if plan["trust_boundary"] != TRUST_BOUNDARY:
        raise ApproveError("plan format or trust boundary is invalid")
    if not isinstance(plan["created_at"], str) or not plan["created_at"] or len(plan["created_at"]) > 100:
        raise ApproveError("plan creation time is invalid")
    for label in ("root", "archive_root", "journal"):
        if not isinstance(plan[label], str) or not plan[label]:
            raise ApproveError(f"plan {label} is invalid")
    root_identity = exact_keys(plan["root_identity"], {"device", "inode"}, "root identity")
    if not all(exact_int(root_identity[key]) and root_identity[key] >= 0 for key in root_identity):
        raise ApproveError("root identity contains invalid values")
    if is_private_format(plan):
        if not isinstance(plan["control_root"], str) or not plan["control_root"]:
            raise ApproveError("plan control root is invalid")
        control_identity = exact_keys(
            plan["control_root_identity"], {"device", "inode"}, "control root identity"
        )
        if not all(exact_int(control_identity[key]) and control_identity[key] >= 0 for key in control_identity):
            raise ApproveError("control root identity contains invalid values")
    if is_identity_plan(plan) and plan["approval_mode"] != IDENTITY_MODE:
        raise ApproveError("identity-source approval mode is invalid")
    database = exact_keys(plan["database"], {
        "path", "identity", "file_sha256", "schema_sha256", "state_sha256",
        "foreign_key_findings_sha256",
    }, "database binding")
    if not isinstance(database["path"], str) or not database["path"]:
        raise ApproveError("database path is invalid")
    validate_identity_shape(database["identity"], "database identity")
    for label in ("file_sha256", "schema_sha256", "state_sha256", "foreign_key_findings_sha256"):
        if not valid_sha256(database[label]):
            raise ApproveError(f"database {label} is invalid")
    if not isinstance(plan["items"], list) or not 1 <= len(plan["items"]) <= MAX_ITEMS:
        raise ApproveError(f"plan needs 1-{MAX_ITEMS} items")
    item_keys = {
        "draft", "draft_sha256", "draft_identity", "draft_bytes", "live",
        "prior_exists", "prior_sha256", "prior_identity", "prior_base64",
        "proposed_sha256", "proposed_base64", "proposed_bytes", "transform",
        "transform_applied", "archive", "diff",
    }
    if is_identity_plan(plan):
        item_keys |= {"subject_type", "subject_id"}
    for index, raw_item in enumerate(plan["items"]):
        item = exact_keys(raw_item, item_keys, f"item {index}")
        for label in ("draft", "live", "proposed_base64", "transform", "diff"):
            if not isinstance(item[label], str):
                raise ApproveError(f"item {index} {label} is invalid")
        if item["transform"] not in TRANSFORMS:
            raise ApproveError(f"item {index} transform is invalid")
        if is_identity_plan(plan) and (
            item["subject_type"] != "contract"
            or item["subject_id"] != "agent-team/" + item["live"]
        ):
            raise ApproveError(f"item {index} identity subject is invalid")
        for label in ("draft_sha256", "proposed_sha256"):
            if not valid_sha256(item[label]):
                raise ApproveError(f"item {index} {label} is invalid")
        for label in ("draft_bytes", "proposed_bytes"):
            if not exact_int(item[label]) or not 0 <= item[label] <= MAX_DOCUMENT_BYTES:
                raise ApproveError(f"item {index} {label} is invalid")
        if type(item["prior_exists"]) is not bool or type(item["transform_applied"]) is not bool:
            raise ApproveError(f"item {index} boolean fields are invalid")
        validate_identity_shape(item["draft_identity"], f"item {index} draft identity")
        if item["prior_exists"]:
            if not valid_sha256(item["prior_sha256"]):
                raise ApproveError(f"item {index} prior hash is invalid")
            validate_identity_shape(item["prior_identity"], f"item {index} prior identity")
            if not isinstance(item["prior_base64"], str) or not isinstance(item["archive"], str):
                raise ApproveError(f"item {index} prior fields are invalid")
        elif any(item[label] is not None for label in ("prior_sha256", "prior_identity", "prior_base64", "archive")):
            raise ApproveError(f"item {index} absent-prior fields are invalid")


def validate_plan_object(plan: dict[str, Any]) -> None:
    if not isinstance(plan, dict):
        raise ApproveError("plan is not an object")
    try:
        digest = plan_digest(plan)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ApproveError("plan cannot be hashed") from exc
    if plan.get("plan_digest") != digest:
        raise ApproveError("plan digest is invalid")
    validate_plan_structure(plan)


def bind_control_root(root: Path, plan: dict[str, Any], control_root: Path | None) -> Path:
    if plan["format"] == FORMAT:
        if control_root is not None:
            raise ApproveError("v1 plan does not support a private control root")
        return root
    if control_root is None:
        raise ApproveError("private-control plan requires the exact control root")
    control = root_path(control_root)
    separate_roots(root, control)
    if str(control) != plan["control_root"]:
        raise ApproveError("control root does not match plan")
    if directory_identity(control) != plan["control_root_identity"]:
        raise ApproveError("control root identity changed")
    return control


def validate_private_plan_location(path: Path, plan: dict[str, Any], control_root: Path | None) -> None:
    if not is_private_format(plan):
        return
    if control_root is None:
        raise ApproveError("private-control plan requires the exact control root")
    control = root_path(control_root)
    plan_path = regular_file(path, "plan")
    if plan_path == control or not plan_path.is_relative_to(control):
        raise ApproveError("private-control plan file must stay below the control root")


def validate_plan_semantics(
    root: Path, database: Path, plan: dict[str, Any], control_root: Path | None = None,
) -> Path:
    if str(root) != plan["root"] or str(database) != plan["database"]["path"]:
        raise ApproveError("root or database does not match plan")
    current_root_identity = directory_identity(root)
    if current_root_identity != plan["root_identity"]:
        raise ApproveError("root identity changed")
    database_identity = identity(database)
    if (database_identity["device"], database_identity["inode"]) != (
        plan["database"]["identity"]["device"], plan["database"]["identity"]["inode"],
    ):
        raise ApproveError("database identity changed")
    control = bind_control_root(root, plan, control_root)
    private = is_private_format(plan)
    archive_rel, archive_dir = relative_control(control, plan["archive_root"], "archive root")
    if archive_rel != plan["archive_root"] or not archive_dir.is_dir():
        raise ApproveError("archive root is not canonical")
    journal_rel, _journal_path = relative_control(control, plan["journal"], "recovery journal")
    if journal_rel != plan["journal"]:
        raise ApproveError("journal path is not canonical")

    seen_drafts: set[str] = set()
    seen_live: set[str] = set()
    seen_draft_inodes: set[tuple[int, int]] = set()
    seen_archives: set[str] = set()
    for index, item in enumerate(plan["items"]):
        draft_rel, draft_path = relative_document(control, item["draft"], "draft", must_exist=True)
        live_rel, _live_path = relative_document(root, item["live"], "live target", must_exist=False)
        if is_identity_plan(plan):
            validate_identity_root_and_item(root, live_rel, item["transform"])
        else:
            refuse_implicit_identity_target(root, live_rel)
        if (
            draft_rel != item["draft"] or live_rel != item["live"]
            or (not private and draft_rel == live_rel)
        ):
            raise ApproveError(f"item {index} paths are not canonical")
        if draft_rel in seen_drafts or live_rel in seen_live:
            raise ApproveError("conflicting draft or live document path")
        if Path(draft_rel).is_relative_to(Path(archive_rel)):
            raise ApproveError(f"draft path conflicts with archive root: {draft_rel}")
        if not private and Path(live_rel).is_relative_to(Path(archive_rel)):
            raise ApproveError(f"document path conflicts with archive root: {live_rel}")
        seen_drafts.add(draft_rel)
        seen_live.add(live_rel)
        draft, draft_identity = read_sealed(draft_path, "draft")
        if (
            draft_identity != item["draft_identity"]
            or len(draft) != item["draft_bytes"]
            or sha256_bytes(draft) != item["draft_sha256"]
        ):
            raise ApproveError(f"draft is stale: {draft_rel}")
        draft_inode = (draft_identity["device"], draft_identity["inode"])
        if draft_inode in seen_draft_inodes:
            raise ApproveError("draft documents share an inode")
        seen_draft_inodes.add(draft_inode)
        try:
            proposed = base64.b64decode(item["proposed_base64"], validate=True)
        except (ValueError, TypeError) as exc:
            raise ApproveError(f"item {index} proposed bytes are invalid") from exc
        recomputed, applied = proposed_document(draft, draft_rel, item["transform"])
        if (
            proposed != recomputed
            or sha256_bytes(proposed) != item["proposed_sha256"]
            or len(proposed) != item["proposed_bytes"]
            or applied is not item["transform_applied"]
        ):
            raise ApproveError(f"item {index} proposed semantics are invalid")
        if item["prior_exists"]:
            try:
                prior = base64.b64decode(item["prior_base64"], validate=True)
            except (ValueError, TypeError) as exc:
                raise ApproveError(f"item {index} prior bytes are invalid") from exc
            if (
                sha256_bytes(prior) != item["prior_sha256"]
                or len(prior) != item["prior_identity"]["size"]
            ):
                raise ApproveError(f"item {index} prior semantics are invalid")
            archive_name = sha256_bytes(live_rel.encode("utf-8"))[:20] + "." + item["prior_sha256"] + ".prior"
            expected_archive = (Path(archive_rel) / archive_name).as_posix()
            if item["archive"] != expected_archive:
                raise ApproveError(f"item {index} archive path is invalid")
            if expected_archive in seen_archives:
                raise ApproveError(f"conflicting archive path: {expected_archive}")
            seen_archives.add(expected_archive)
            archive_value, _archive_path = relative_control(control, item["archive"], "archive")
            if archive_value != expected_archive:
                raise ApproveError(f"item {index} archive path is not canonical")
        else:
            prior = None
        expected_diff = diff_text(prior, draft, proposed, live_rel, draft_rel)
        if item["diff"] != expected_diff:
            raise ApproveError(f"item {index} displayed diff is invalid")
    if (
        journal_rel in seen_drafts or archive_rel in seen_drafts
        or (not private and (journal_rel in seen_live or archive_rel in seen_live))
        or Path(journal_rel).is_relative_to(Path(archive_rel))
    ):
        raise ApproveError("control paths conflict with document paths")
    return control


def validate_confirmation(plan: dict[str, Any], confirmation: str | None) -> None:
    if not confirmation:
        raise ApproveError("exact plan digest confirmation is required")
    if confirmation != plan["plan_digest"]:
        raise ApproveError("confirmation does not match the exact plan digest")


def validate_attestation(actor: str, approval_ref: str, approval_text: str) -> None:
    if not SAFE_ACTOR.fullmatch(actor or ""):
        raise ApproveError("actor is invalid")
    for label, value in (("approval evidence reference", approval_ref), ("approval text", approval_text)):
        if not value or len(value) > 1000 or any(character in value for character in "\r\n\x00"):
            raise ApproveError(f"{label} must be nonempty single-line text")


def verify_item_fresh(
    root: Path, control: Path, item: dict[str, Any],
) -> tuple[Path, Path, bytes, bytes | None]:
    draft_rel, draft_path = relative_document(control, item["draft"], "draft", must_exist=True)
    live_rel, live_path = relative_document(root, item["live"], "live target", must_exist=False)
    if draft_rel != item["draft"] or live_rel != item["live"]:
        raise ApproveError("plan paths are not canonical")
    draft, draft_identity = read_sealed(draft_path, "draft")
    if sha256_bytes(draft) != item["draft_sha256"] or draft_identity != item["draft_identity"]:
        raise ApproveError(f"draft is stale: {draft_rel}")
    if item["prior_exists"]:
        if not live_path.exists():
            raise ApproveError(f"live target disappeared: {live_rel}")
        prior, prior_identity = read_sealed(live_path, "live target")
        if sha256_bytes(prior) != item["prior_sha256"] or prior_identity != item["prior_identity"]:
            raise ApproveError(f"live target is stale: {live_rel}")
    else:
        if live_path.exists() or live_path.is_symlink():
            raise ApproveError(f"live target appeared after plan: {live_rel}")
        prior = None
    proposed = base64.b64decode(item["proposed_base64"], validate=True)
    if sha256_bytes(proposed) != item["proposed_sha256"]:
        raise ApproveError(f"proposed bytes do not match plan: {live_rel}")
    sealed_prior = None if item["prior_base64"] is None else base64.b64decode(item["prior_base64"], validate=True)
    if prior != sealed_prior:
        raise ApproveError(f"prior bytes do not match plan: {live_rel}")
    return draft_path, live_path, proposed, prior


def exact_existing_approval(
    con: sqlite3.Connection, plan: dict[str, Any], approval_ref: str, approval_text: str, actor: str,
) -> bool:
    for item in plan["items"]:
        subject_type, subject_id = approval_subject(plan, item)
        row = con.execute(
            "SELECT id FROM approvals WHERE subject_type=? AND subject_id=? AND version=? AND call='approve' AND person_words=? AND source=?",
            (subject_type, subject_id, item["proposed_sha256"], approval_text, approval_ref),
        ).fetchone()
        if row is None:
            return False
        marker = f"plan={plan['plan_digest']};approval={row['id']}"
        activity = con.execute(
            "SELECT id FROM activity WHERE subject_type=? AND subject_id=? AND field='approval' AND new_value=? AND actor=? AND source=? AND note=?",
            (subject_type, subject_id, item["proposed_sha256"], actor, SOURCE, marker),
        ).fetchone()
        if activity is None:
            return False
    return True


def completed_replay(
    root: Path, control: Path, plan: dict[str, Any], con: sqlite3.Connection,
    journal_path: Path, approval_ref: str, approval_text: str, actor: str,
) -> bool:
    if not journal_path.exists():
        return False
    journal = json.loads(regular_file(journal_path, "recovery journal").read_text(encoding="utf-8"))
    if journal.get("format") != JOURNAL_FORMAT or journal.get("plan_digest") != plan["plan_digest"]:
        raise ApproveError("existing recovery journal belongs to another plan")
    if journal.get("state") != "completed":
        raise ApproveError("an incomplete recovery journal exists; recover before retry")
    if len(journal.get("items", [])) != len(plan["items"]):
        raise ApproveError("completed recovery journal item count is invalid")
    for index, item in enumerate(plan["items"]):
        _, live_path = relative_document(root, item["live"], "live target", must_exist=True)
        live, live_identity = read_sealed(live_path, "live target")
        journal_item = journal["items"][index]
        if (
            journal_item.get("state") != "target_written"
            or sha256_bytes(live) != item["proposed_sha256"]
            or live_identity != journal_item.get("written_identity")
        ):
            raise ApproveError("completed replay target no longer matches approved version")
        if item["archive"]:
            _, archive_path = relative_control(control, item["archive"], "archive", must_exist=True)
            if file_hash(archive_path) != item["prior_sha256"]:
                raise ApproveError("completed replay archive changed")
    if not exact_existing_approval(con, plan, approval_ref, approval_text, actor):
        raise ApproveError("completed journal does not match exact database approval evidence")
    return True


def verify_committed_files(
    root: Path, control: Path, plan: dict[str, Any], journal: dict[str, Any],
) -> None:
    if len(journal.get("items", [])) != len(plan["items"]):
        raise ApproveError("recovery journal item count is invalid")
    for index, item in enumerate(plan["items"]):
        journal_item = journal["items"][index]
        _, live_path = relative_document(root, item["live"], "live target", must_exist=True)
        live, live_identity = read_sealed(live_path, "live target")
        if (
            journal_item.get("state") != "target_written"
            or sha256_bytes(live) != item["proposed_sha256"]
            or live_identity != journal_item.get("written_identity")
        ):
            raise ApproveError(f"committed target needs manual review: {item['live']}")
        if item["archive"]:
            _, archive_path = relative_control(control, item["archive"], "archive", must_exist=True)
            archive, _ = read_sealed(archive_path, "archive")
            if sha256_bytes(archive) != item["prior_sha256"]:
                raise ApproveError(f"committed archive needs manual review: {item['archive']}")


def database_plan_commit_state(con: sqlite3.Connection, plan: dict[str, Any]) -> str:
    matched = 0
    prefix = f"plan={plan['plan_digest']};approval="
    for item in plan["items"]:
        subject_type, subject_id = approval_subject(plan, item)
        rows = list(con.execute(
            "SELECT a.note FROM activity a WHERE a.subject_type=? AND a.subject_id=? "
            "AND a.field='approval' AND a.new_value=? AND a.source=? AND a.note LIKE ?",
            (subject_type, subject_id, item["proposed_sha256"], SOURCE, prefix + "%"),
        ))
        valid = 0
        for row in rows:
            raw_id = str(row["note"])[len(prefix):]
            if not raw_id.isdigit():
                continue
            approval = con.execute(
                "SELECT id FROM approvals WHERE id=? AND subject_type=? AND subject_id=? AND version=? AND call='approve'",
                (int(raw_id), subject_type, subject_id, item["proposed_sha256"]),
            ).fetchone()
            if approval is not None:
                valid += 1
        if valid == 1:
            matched += 1
        elif valid > 1:
            return "partial"
    if matched == 0:
        return "none"
    return "complete" if matched == len(plan["items"]) else "partial"


def apply_plan(
    *, root: Path, database: Path, plan: dict[str, Any], confirmation: str | None,
    actor: str, approval_ref: str, approval_text: str,
    control_root: Path | None = None,
    identity_source: bool = False,
    clock: Callable[[], str] = now, inject_failure: str | None = None,
    before_item_write: Callable[[int], None] | None = None,
    after_archive_write: Callable[[int], None] | None = None,
) -> dict[str, Any]:
    validate_plan_object(plan)
    validate_requested_mode(plan, identity_source)
    validate_confirmation(plan, confirmation)
    validate_attestation(actor, approval_ref, approval_text)
    root = root_path(root)
    database = regular_file(database, "database")
    control = validate_plan_semantics(root, database, plan, control_root)
    journal_rel, journal_path = relative_control(control, plan["journal"], "recovery journal")
    if journal_rel != plan["journal"]:
        raise ApproveError("journal path is not canonical")
    with connect_db(database, readonly=False) as con:
        if completed_replay(root, control, plan, con, journal_path, approval_ref, approval_text, actor):
            return {"status": "duplicate", "plan_digest": plan["plan_digest"], "items": len(plan["items"])}
        if journal_path.exists():
            raise ApproveError("an incomplete recovery journal exists")
        if (
            schema_hash(con) != plan["database"]["schema_sha256"]
            or database_state_hash(con) != plan["database"]["state_sha256"]
            or foreign_key_findings_hash(con) != plan["database"]["foreign_key_findings_sha256"]
        ):
            raise ApproveError("database approval or activity state is stale")
        prepared = [verify_item_fresh(root, control, item) for item in plan["items"]]
        for item in plan["items"]:
            if item["archive"]:
                _, archive_path = relative_control(control, item["archive"], "archive")
                if archive_path.exists() or archive_path.is_symlink():
                    raise ApproveError(f"archive collision: {archive_path}")
        journal = {
            "format": JOURNAL_FORMAT, "plan_digest": plan["plan_digest"],
            "state": "prepared", "created_at": clock(), "updated_at": clock(),
            "items": [{"live": item["live"], "archive": item["archive"], "state": "pending"} for item in plan["items"]],
            "database_committed": False, "error": None,
        }
        write_json_exclusive(journal_path, journal, "recovery journal")
        journal_hash = file_hash(journal_path)
        try:
            for index, (item, (_draft_path, live_path, proposed, prior)) in enumerate(zip(plan["items"], prepared)):
                if before_item_write:
                    before_item_write(index)
                verify_item_fresh(root, control, item)
                if item["archive"]:
                    _, archive_path = relative_control(control, item["archive"], "archive")
                    exclusive_write(archive_path, prior or b"", "archive")
                    journal["items"][index]["state"] = "archive_written"
                    journal["updated_at"] = clock()
                    journal_hash = update_journal(journal_path, journal, journal_hash)
                    if after_archive_write:
                        after_archive_write(index)
                    _draft_path, live_path, proposed, prior = verify_item_fresh(root, control, item)
                written_identity = atomic_replace(live_path, proposed, "live target")
                journal["items"][index]["state"] = "target_written"
                journal["items"][index]["written_identity"] = written_identity
                journal["updated_at"] = clock()
                journal_hash = update_journal(journal_path, journal, journal_hash)
                if inject_failure == f"after_target:{index}":
                    raise RuntimeError("injected failure after target write")

            verify_committed_files(root, control, plan, journal)
            con.execute("BEGIN IMMEDIATE")
            try:
                if (
                    schema_hash(con) != plan["database"]["schema_sha256"]
                    or database_state_hash(con) != plan["database"]["state_sha256"]
                    or foreign_key_findings_hash(con) != plan["database"]["foreign_key_findings_sha256"]
                ):
                    raise ApproveError("database changed before approval write")
                timestamp = clock()
                for item in plan["items"]:
                    subject_type, subject_id = approval_subject(plan, item)
                    cursor = con.execute(
                        "INSERT INTO approvals(subject_type,subject_id,version,call,person_words,given_at,source) VALUES (?,?,?,'approve',?,?,?)",
                        (subject_type, subject_id, item["proposed_sha256"], approval_text, timestamp, approval_ref),
                    )
                    approval_id = int(cursor.lastrowid)
                    marker = f"plan={plan['plan_digest']};approval={approval_id}"
                    write_history(con, subject_type, subject_id, 'approval', item['prior_sha256'],
                                  item['proposed_sha256'], actor, SOURCE, timestamp, marker, call='approve')
                verify_committed_files(root, control, plan, journal)
                if inject_failure == "before_database_commit":
                    raise RuntimeError("injected failure before database commit")
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
            if inject_failure == "after_database_commit":
                raise RuntimeError("injected failure after database commit")
            journal["database_committed"] = True
            journal["state"] = "completed"
            journal["updated_at"] = clock()
            journal_hash = update_journal(journal_path, journal, journal_hash)
            return {"status": "applied", "plan_digest": plan["plan_digest"], "items": len(plan["items"]), "journal_sha256": journal_hash}
        except Exception as error:
            journal["state"] = "partial"
            journal["updated_at"] = clock()
            journal["error"] = type(error).__name__ + ": " + str(error)
            try:
                update_journal(journal_path, journal, journal_hash)
            except Exception as journal_error:
                raise ApproveError(f"apply failed and journal update conflicted: {error}; {journal_error}") from error
            raise ApproveError(f"apply stopped with recoverable partial state: {error}") from error


def recover_plan(
    *, root: Path, plan: dict[str, Any], confirmation: str | None,
    control_root: Path | None = None,
    identity_source: bool = False,
    clock: Callable[[], str] = now,
    before_recovery_write: Callable[[int], None] | None = None,
) -> dict[str, Any]:
    validate_plan_object(plan)
    validate_requested_mode(plan, identity_source)
    validate_confirmation(plan, confirmation)
    root = root_path(root)
    if str(root) != plan["root"]:
        raise ApproveError("root does not match plan")
    database = regular_file(Path(plan["database"]["path"]), "database")
    control = validate_plan_semantics(root, database, plan, control_root)
    _, journal_path = relative_control(control, plan["journal"], "recovery journal", must_exist=True)
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    if journal.get("format") != JOURNAL_FORMAT or journal.get("plan_digest") != plan["plan_digest"]:
        raise ApproveError("recovery journal does not match plan")
    if journal.get("state") == "completed" or journal.get("database_committed"):
        raise ApproveError("database approval committed; recovery cannot roll it back")
    if len(journal.get("items", [])) != len(plan["items"]):
        raise ApproveError("recovery journal item count is invalid")
    journal_hash = file_hash(journal_path)
    with connect_db(database, readonly=True) as con:
        commit_state = database_plan_commit_state(con, plan)
    if commit_state == "complete":
        verify_committed_files(root, control, plan, journal)
        journal["state"] = "completed"
        journal["database_committed"] = True
        journal["error"] = None
        journal["updated_at"] = clock()
        journal_hash = update_journal(journal_path, journal, journal_hash)
        return {
            "status": "completed-after-crash", "plan_digest": plan["plan_digest"],
            "journal_sha256": journal_hash,
        }
    if commit_state == "partial":
        raise ApproveError("database contains partial approval evidence; manual review required")

    manual_review: list[str] = []
    for index, item in enumerate(plan["items"]):
        journal_item = journal["items"][index]
        state = journal_item.get("state")
        if state not in {"pending", "archive_written", "target_written", "recovered", "untouched"}:
            manual_review.append(item["live"] + " (invalid journal state)")
            continue
        _, live_path = relative_document(root, item["live"], "live target", must_exist=False)
        exists = live_path.exists()
        current = current_identity = None
        if exists:
            current, current_identity = read_sealed(live_path, "live target")
        if state == "target_written":
            if (
                not exists
                or sha256_bytes(current or b"") != item["proposed_sha256"]
                or current_identity != journal_item.get("written_identity")
            ):
                manual_review.append(item["live"] + " (recorded candidate write changed)")
        elif state in {"pending", "archive_written"}:
            if item["prior_exists"]:
                if (
                    not exists
                    or sha256_bytes(current or b"") != item["prior_sha256"]
                    or current_identity != item["prior_identity"]
                ):
                    detail = "unrecorded candidate write" if exists and sha256_bytes(current or b"") == item["proposed_sha256"] else "source changed"
                    manual_review.append(item["live"] + f" ({detail})")
            elif exists:
                detail = "unrecorded candidate write" if sha256_bytes(current or b"") == item["proposed_sha256"] else "unexpected file"
                manual_review.append(item["live"] + f" ({detail})")
        else:  # recovered or untouched
            if item["prior_exists"]:
                if (
                    not exists
                    or sha256_bytes(current or b"") != item["prior_sha256"]
                    or current_identity != journal_item.get("recovered_identity")
                ):
                    manual_review.append(item["live"] + " (recovered target changed)")
            elif exists:
                manual_review.append(item["live"] + " (recovered absent target reappeared)")

        if item["archive"]:
            _, archive_path = relative_control(control, item["archive"], "archive")
            archive_exists = archive_path.exists()
            if state in {"pending", "untouched"} and archive_exists:
                manual_review.append(item["archive"] + " (unrecorded archive write)")
            elif state in {"archive_written", "target_written", "recovered"}:
                if not archive_exists:
                    manual_review.append(item["archive"] + " (missing archive)")
                else:
                    archive, _ = read_sealed(archive_path, "archive")
                    if sha256_bytes(archive) != item["prior_sha256"]:
                        manual_review.append(item["archive"] + " (archive changed)")
    if manual_review:
        journal["error"] = "manual review required: " + ", ".join(manual_review)
        journal["updated_at"] = clock()
        update_journal(journal_path, journal, journal_hash)
        raise ApproveError("recovery requires manual review: " + ", ".join(manual_review))

    if journal.get("state") == "recovered":
        return {"status": "duplicate-recovery", "plan_digest": plan["plan_digest"]}

    for index in reversed(range(len(plan["items"]))):
        item = plan["items"][index]
        state = journal["items"][index]["state"]
        _, live_path = relative_document(root, item["live"], "live target", must_exist=state == "target_written")
        if state == "target_written":
            if before_recovery_write:
                before_recovery_write(index)
            current, current_identity = read_sealed(live_path, "live target")
            expected_identity = journal["items"][index].get("written_identity")
            if sha256_bytes(current) != item["proposed_sha256"] or current_identity != expected_identity:
                raise ApproveError(f"recovery requires manual review: {item['live']} changed before restore")
            if item["prior_exists"]:
                _, archive_path = relative_control(control, item["archive"], "archive", must_exist=True)
                prior, _ = read_sealed(archive_path, "archive")
                if sha256_bytes(prior) != item["prior_sha256"]:
                    raise ApproveError(f"recovery requires manual review: {item['archive']} changed before restore")
                latest, latest_identity = read_sealed(live_path, "live target")
                if (
                    sha256_bytes(latest) != item["proposed_sha256"]
                    or latest_identity != expected_identity
                    or latest != current
                    or latest_identity != current_identity
                ):
                    raise ApproveError(f"recovery requires manual review: {item['live']} changed before restore")
                latest_prior, _ = read_sealed(archive_path, "archive")
                if latest_prior != prior or sha256_bytes(latest_prior) != item["prior_sha256"]:
                    raise ApproveError(f"recovery requires manual review: {item['archive']} changed before restore")
                recovered_identity = atomic_replace(live_path, prior, "recovered live target")
                journal["items"][index]["recovered_identity"] = recovered_identity
            else:
                latest, latest_identity = read_sealed(live_path, "live target")
                if sha256_bytes(latest) != item["proposed_sha256"] or latest_identity != expected_identity:
                    raise ApproveError(f"recovery requires manual review: {item['live']} changed before removal")
                live_path.unlink()
                journal["items"][index]["recovered_identity"] = None
            journal["items"][index]["state"] = "recovered"
            journal["updated_at"] = clock()
            journal_hash = update_journal(journal_path, journal, journal_hash)
        elif state in {"pending", "archive_written"}:
            journal["items"][index]["state"] = "untouched" if state == "pending" else "recovered"
            journal["items"][index]["recovered_identity"] = item["prior_identity"] if item["prior_exists"] else None
    journal["state"] = "recovered"
    journal["error"] = None
    journal["updated_at"] = clock()
    journal_hash = update_journal(journal_path, journal, journal_hash)
    return {"status": "recovered", "plan_digest": plan["plan_digest"], "journal_sha256": journal_hash}


def discover_documents(root: Path) -> list[str]:
    """Use the one contract rule file to discover active contracts and live specs."""
    import importlib.util
    tools = (Path(__file__).resolve().parent / '../base')
    spec = importlib.util.spec_from_file_location("approval_contract_lint", (Path(__file__).resolve().parent / '../base/contract_lint.py'))
    if spec is None or spec.loader is None:
        raise ApproveError("contract lint discovery is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rules, _ = module.load_rules((Path(__file__).resolve().parent / '../base/contract-lint-rules.json'))
    return [path.relative_to(root).as_posix() for path in module.discover_contracts(root, root, rules)]


def lint_documents(
    *, root: Path, database: Path, paths: Iterable[str] | None = None, identity_source: bool = False,
    control_root: Path | None = None,
    discover: bool = False,
) -> dict[str, Any]:
    root = root_path(root)
    if identity_source:
        if control_root is None:
            raise ApproveError("identity-source lint requires a private control root")
        control = root_path(control_root)
        separate_roots(root, control)
        if root.name != "agent-team":
            raise ApproveError("identity-source root must be the agent-team repository root")
    elif control_root is not None:
        raise ApproveError("document lint does not accept a private control root")
    database = regular_file(database, "database")
    if discover and (paths or identity_source):
        raise ApproveError("discovery cannot combine explicit paths or identity-source mode")
    selected = discover_documents(root) if discover else list(paths or [])
    if not selected or len(selected) != len(set(selected)):
        raise ApproveError("lint needs unique explicit document paths")
    documents = []
    findings = []
    bindings = []
    with connect_db(database, readonly=True) as con:
        for value in sorted(selected):
            relative, path = relative_document(root, value, "live document", must_exist=True)
            if identity_source:
                validate_identity_root_and_item(root, relative, "none")
            else:
                refuse_implicit_identity_target(root, relative)
            raw, _ = read_sealed(path, "live document")
            version = sha256_bytes(raw)
            subject_type = "contract" if identity_source else "document"
            subject_id = "agent-team/" + relative if identity_source else relative
            rows = list(con.execute(
                "SELECT id,source FROM approvals WHERE subject_type=? AND subject_id=? AND version=? AND call='approve' ORDER BY id",
                (subject_type, subject_id, version),
            ))
            document = {"file": relative, "sha256": version, "approval_rows": [int(row["id"]) for row in rows]}
            if identity_source:
                document.update({"subject_type": subject_type, "subject_id": subject_id})
            documents.append(document)
            if not rows:
                findings.append({
                    "file": relative, "sha256": version, "rule": "approval_coverage",
                    "state": "missing", "evidence": "no exact subject path and SHA-256 approval row",
                })
            for row in rows:
                binding = {"file": relative, "sha256": version, "approval": f"approval-row:{int(row['id'])}"}
                if identity_source:
                    binding.update({"subject_type": subject_type, "subject_id": subject_id})
                bindings.append(binding)
    report = {
        "format": REPORT_FORMAT, "read_only": True, "root": str(root),
        "documents": documents, "findings": findings,
        "summary": {"documents": len(documents), "missing": len(findings)},
        "approval_source": {"approvals": bindings},
    }
    if identity_source:
        report["approval_mode"] = IDENTITY_MODE
    return report


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(description=__doc__)
    commands = top.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("--root", type=Path, required=True)
    plan.add_argument("--db", type=Path, required=True)
    plan.add_argument("--item", action="append", required=True)
    plan.add_argument("--archive-root", required=True)
    plan.add_argument("--journal", required=True)
    plan.add_argument("--output", type=Path, required=True)
    plan.add_argument("--control-root", type=Path)
    plan.add_argument("--identity-source", action="store_true")
    apply = commands.add_parser("apply")
    apply.add_argument("--root", type=Path, required=True)
    apply.add_argument("--db", type=Path, required=True)
    apply.add_argument("--plan", type=Path, required=True)
    apply.add_argument("--confirm-digest", required=True)
    apply.add_argument("--actor", required=True)
    apply.add_argument("--approval-ref", required=True)
    apply.add_argument("--approval-text", required=True)
    apply.add_argument("--control-root", type=Path)
    apply.add_argument("--identity-source", action="store_true")
    recover = commands.add_parser("recover")
    recover.add_argument("--root", type=Path, required=True)
    recover.add_argument("--plan", type=Path, required=True)
    recover.add_argument("--confirm-digest", required=True)
    recover.add_argument("--control-root", type=Path)
    recover.add_argument("--identity-source", action="store_true")
    lint = commands.add_parser("lint")
    lint.add_argument("--root", type=Path, required=True)
    lint.add_argument("--db", type=Path, required=True)
    scope = lint.add_mutually_exclusive_group(required=True)
    scope.add_argument("--path", action="append")
    scope.add_argument("--discover", action="store_true")
    lint.add_argument("--approval-source-output", type=Path)
    lint.add_argument("--control-root", type=Path)
    lint.add_argument("--identity-source", action="store_true")
    return top


def run(argv: list[str] | None = None, *, stdout: TextIO | None = None, stderr: TextIO | None = None) -> int:
    out = stdout or sys.stdout
    err = stderr or sys.stderr
    try:
        args = parser().parse_args(argv)
        if args.command == "plan":
            value = build_plan(
                root=args.root, database=args.db, items=[parse_item(item) for item in args.item],
                archive_root=args.archive_root, journal=args.journal, control_root=args.control_root,
                identity_source=args.identity_source,
            )
            output = canonical(args.output)
            if output.exists() or output.is_symlink() or symlink_component(output) or not output.parent.is_dir():
                raise ApproveError("plan output must be a new file under an existing non-symlink parent")
            if args.control_root is not None:
                control = root_path(args.control_root)
                if output == control or not output.is_relative_to(control):
                    raise ApproveError("private-control plan output must stay below the control root")
            write_json_exclusive(output, value, "plan output")
            for item in value["items"]:
                print(item["diff"], file=out, end="" if item["diff"].endswith("\n") else "\n")
            print("plan digest: " + value["plan_digest"], file=out)
            print("Apply only after the external caller possesses approval for this exact digest and version.", file=out)
        elif args.command == "apply":
            plan_value = load_plan(args.plan)
            validate_private_plan_location(args.plan, plan_value, args.control_root)
            value = apply_plan(
                root=args.root, database=args.db, plan=plan_value, confirmation=args.confirm_digest,
                actor=args.actor, approval_ref=args.approval_ref, approval_text=args.approval_text,
                control_root=args.control_root, identity_source=args.identity_source,
            )
            print(json.dumps(value, indent=2), file=out)
        elif args.command == "recover":
            plan_value = load_plan(args.plan)
            validate_private_plan_location(args.plan, plan_value, args.control_root)
            value = recover_plan(
                root=args.root, plan=plan_value, confirmation=args.confirm_digest,
                control_root=args.control_root, identity_source=args.identity_source,
            )
            print(json.dumps(value, indent=2), file=out)
        else:
            value = lint_documents(
                root=args.root, database=args.db, paths=args.path,
                identity_source=args.identity_source, control_root=args.control_root,
                discover=args.discover,
            )
            if args.approval_source_output:
                output = canonical(args.approval_source_output)
                if output.exists() or output.is_symlink() or symlink_component(output) or not output.parent.is_dir():
                    raise ApproveError("approval source output must be a new safe file")
                write_json_exclusive(output, value["approval_source"], "approval source output")
            print(json.dumps(value, indent=2), file=out)
        return 1 if args.command == "lint" and value["findings"] else 0
    except (ApproveError, OSError, sqlite3.Error, ValueError, json.JSONDecodeError) as error:
        print("approve failed: " + str(error), file=err)
        return 2


if __name__ == "__main__":
    raise SystemExit(run())
