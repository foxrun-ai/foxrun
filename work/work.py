#!/usr/bin/env python3
"""Portable writer for existing work-module task rows."""

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
from dataclasses import dataclass
from datetime import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
from typing import Callable, TextIO
from urllib.parse import quote


sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / '../events'))
sys.path.insert(0, str(Path(__file__).resolve().parent / '../decisions'))
# Run as a script, this file is __main__; decisions.py imports "work". One module keeps one WorkError,
# so a refusal from decisions.py prints "work failed" and exits 2 instead of a traceback (T260).
sys.modules.setdefault("work", sys.modules[__name__])
from history_actions import ACTIONS, history_action, database_action

SOURCE = "work cli"
STANDING_TITLE = "Session work to place"
SESSION_HOLDING_KEY = "session-holding-task"
HOLDING_BACKFILL_REQUIRED = (
    "session holding task is missing; backfill required: run session_run.py backfill-key "
    "--db <tracker> --task <id> before activating the new logger"
)
RUN_TASK_GUIDANCE = f"A run starts on a task. Find the task (program-control 'Every run rolls up') or plan one and ask {_fox_person.display_name()} to place it."
RUN_TASK_REQUIRED = "run-start needs a task id. " + RUN_TASK_GUIDANCE
RETIRED_JOB_MESSAGE = "finish-job is retired. Use run-start on a task, then run-end."
RETIRED_FLAGS = ("--run", "--job", "--elapsed-seconds")
FINAL_STATUSES = {"done", "accepted", "canceled", "superseded"}
# Named lead seats still control bounce; accept follows g-close-on-evidence-not-seat (T649).
LEAD_SEATS = _fox_person.leads()
ACTOR_TOKEN = re.compile(r"[A-Za-z0-9_-]+")
# Non-token names found across both tracker histories on 2026-10-04; only these names get exceptions.
LEGACY_ACTOR_NAMES = {_fox_person.name() + " + claude", "program-control apply"}
FLAG_PREFIX = "Flag: "
FIELD_NAME = re.compile(r"[a-z][a-z0-9_]*")
APPROVAL_CALLS = ("approve", "discuss", "wrong", "edit")
COMMENT_REF = re.compile(r"\bcomment:(\d+)\b")
REPLACES_WORD = re.compile(r"\b(replaces|amends|supersedes|corrects)\b", re.IGNORECASE)
DECISION_IDS = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*(?:,[a-z0-9]+(?:-[a-z0-9]+)*)*")
# source-note: the functions table has no CHECK on these columns. The writer holds the shape:
# id and organization are lowercase slugs; owner is a plain name, the same rule as --by.
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
FUNCTION_VERBS = ("function-create", "function-update")
FUNCTION_FIELDS = ("name", "organization", "parent", "owner", "page", "tags")
EMPTY_WORD = "none"
SUBJECT_TABLES = {
    "task": "tasks", "project": "projects", "function": "functions", "goal": "goals", "theme": "themes",
    "program": "programs", "run": "runs", "decision": "decisions", "incident": "incidents", "bug": "bugs",
}
REQUIRED_COLUMNS = {
    "functions": ("id", "name", "organization", "parent", "owner", "page", "tags", "created_on"),
    "goals": ("id", "title", "horizon", "period", "function", "owner", "status", "tags", "created_on", "replaced_by"),
    "measures": ("id", "name", "function", "goal", "owner", "target", "unit", "source", "created_on"),
    "measure_history": ("measure", "as_of", "value", "note"),
    "programs": ("id", "name", "objective", "created_on"),
    "themes": ("id", "program", "name", "tagline", "ord"),
    "projects": (
        "id", "title", "result", "goal", "status", "function", "owner", "due", "page", "tags",
        "created_on", "extra", "description", "problem", "job_when", "job_want", "job_so", "done_when",
        "context", "ord", "program", "theme", "needs", "order_column", "span", "alongside", "replaces",
    ),
    "tasks": (
        "id", "title", "body", "status", "project", "function", "tags", "owner",
        "created_by", "claimed_by", "claimed_at", "blocked_by", "done_check", "parent",
        "ord", "planned", "deadline", "important", "urgent", "flag", "idempotency_key",
        "created_on", "source", "extra", "goal", "note", "acceptance", "context", "prior_project",
    ),
    "runs": (
        "id", "subject_type", "subject_id", "by", "model", "runtime", "session", "started_at",
        "ended_at", "result", "fix_rounds", "evidence", "note",
    ),
    "task_links": ("id", "task", "system", "scope", "external_id", "path", "relation", "active", "created_on"),
    "activity": ("id", "subject_type", "subject_id", "field", "old_value", "new_value", "actor", "source", "at", "note"),
    "comments": ("id", "subject_type", "subject_id", "author", "at", "body", "reply_to"),
    "attachments": ("id", "subject_type", "subject_id", "path", "role", "author", "at", "hash"),
    "decisions": (
        "id", "name", "statement", "person_words", "status", "replaces", "path", "project", "function",
        "tags", "decided_on", "in_artifact", "artifact_version", "source", "extra",
    ),
    "approvals": ("id", "subject_type", "subject_id", "version", "call", "person_words", "given_at", "source"),
    "bugs": ("id", "title", "description", "capability", "status", "reports", "created_on"),
    "incidents": ("id", "title", "started_at", "ended_at", "impact", "restored_by", "status", "rca_cause", "bug", "created_on", "source"),
    "record_links": ("id", "subject_type", "subject_id", "target_type", "target_id", "relation"),
}
OPTIONAL_TABLES = {"programs", "themes", "runs", "bugs", "incidents", "record_links"}
ALLOWED_COLUMNS = {table: {columns} for table, columns in REQUIRED_COLUMNS.items()}
ALLOWED_COLUMNS["goals"].add(REQUIRED_COLUMNS["goals"][:-1])
ALLOWED_COLUMNS["projects"].update((REQUIRED_COLUMNS["projects"][:-1], REQUIRED_COLUMNS["projects"][:20]))
ALLOWED_COLUMNS["tasks"].add(REQUIRED_COLUMNS["tasks"][:-1])
ALLOWED_COLUMNS["tasks"].add(REQUIRED_COLUMNS["tasks"] + ("check_by", "canceled_reason", "folded_into"))
# T718: every task carries Problem and a job story (g-every-task-carries-the-six-fields-a-spec-is-a-parent-task).
SIX_FIELD_COLUMNS = ("problem", "job_when", "job_want", "job_so")
ALLOWED_COLUMNS["tasks"].add(REQUIRED_COLUMNS["tasks"] + SIX_FIELD_COLUMNS)
ALLOWED_COLUMNS["tasks"].add(REQUIRED_COLUMNS["tasks"] + ("check_by", "canceled_reason", "folded_into") + SIX_FIELD_COLUMNS)
# T718: a bug carries the same fields as a task.
BUG_FIELD_COLUMNS = ("tags", "problem", "job_when", "job_want", "job_so", "body", "acceptance", "context")
ALLOWED_COLUMNS["bugs"].add(REQUIRED_COLUMNS["bugs"] + BUG_FIELD_COLUMNS)
ALLOWED_COLUMNS["projects"].add(REQUIRED_COLUMNS["projects"] + ("canceled_reason",))
ALLOWED_COLUMNS["programs"].add(REQUIRED_COLUMNS["programs"] + ("status", "canceled_reason"))
ALLOWED_COLUMNS["activity"].add(REQUIRED_COLUMNS["activity"] + ("verb",))
ALLOWED_COLUMNS["comments"].add(REQUIRED_COLUMNS["comments"] + ("field",))
ALLOWED_COLUMNS["runs"].add(REQUIRED_COLUMNS["runs"][:6] + REQUIRED_COLUMNS["runs"][7:] + ("session",))
REQUIRED_FOREIGN_KEYS = {
    "functions": {("functions", "parent", "id")},
    "goals": {("functions", "function", "id")},
    "measures": {("functions", "function", "id"), ("goals", "goal", "id")},
    "measure_history": {("measures", "measure", "id")},
    "themes": {("programs", "program", "id")},
    "projects": {
        ("goals", "goal", "id"), ("functions", "function", "id"),
        ("programs", "program", "id"), ("themes", "theme", "id"),
    },
    "tasks": {
        ("projects", "project", "id"), ("functions", "function", "id"),
        ("tasks", "blocked_by", "id"), ("tasks", "parent", "id"), ("goals", "goal", "id"),
    },
    "task_links": {("tasks", "task", "id")},
    "comments": {("comments", "reply_to", "id")},
    "decisions": set(),
    "incidents": {("bugs", "bug", "id")},
}
LEGACY_FOREIGN_KEYS = {
    "projects": {("goals", "goal", "id"), ("functions", "function", "id")},
    "decisions": {("decisions", "replaces", "id")},
}
LEGACY_FOREIGN_KEYS["tasks"] = set(REQUIRED_FOREIGN_KEYS["tasks"])
REQUIRED_FOREIGN_KEYS["tasks"].add(("tasks", "folded_into", "id"))
SECRET_PART = re.compile(r"(^\.env(?:\.|$)|(^|[-_.])(auth|credential|secret|token)(s)?([-_.]|$)|\.(key|pem|p12)$)", re.IGNORECASE)


class WorkError(ValueError):
    pass


def run_start_refusal(db: sqlite3.Connection, subject: str) -> str:
    for table, kind in (("projects", "work stream"), ("programs", "program"),
                        ("goals", "goal"), ("themes", "theme")):
        if db.execute(f"SELECT 1 FROM {table} WHERE id=?", (subject,)).fetchone():
            return f"{subject} is a {kind}, not a task. {RUN_TASK_GUIDANCE}"
    return f"{subject} is unknown, not a task. {RUN_TASK_GUIDANCE}"


@dataclass
class Receipt:
    root: Path
    relative: str
    path: Path
    descriptor: int
    digest: str
    identity: tuple[int, int, int, int]

    def close(self) -> None:
        os.close(self.descriptor)


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def one_line(value: str | None, label: str) -> str:
    if value is None or not value.strip() or "\n" in value or "\r" in value:
        raise WorkError(label + " must be one non-empty line")
    return value.strip()


def tag_state(value: str | None, tag: str, present: bool) -> str | None:
    tags = [item.strip() for item in (value or "").split(",") if item.strip()]
    has_tag = any(item.lower() == tag for item in tags)
    if present:
        if has_tag:
            return value
        return ((value or "").rstrip() + ("," if value and value.rstrip() else "") + tag)
    if not has_tag:
        return value
    return ",".join(item for item in tags if item.lower() != tag) or None


def normalized_tags(value: str | None) -> list[str]:
    if not value:
        return []
    result = []
    for raw in value.split(","):
        tag = raw.strip().lower()
        if not tag or any(char.isspace() for char in tag):
            raise WorkError("tags must be non-empty comma-separated words without spaces")
        if tag not in result:
            result.append(tag)
    return result


def single_tag(value: str, label: str) -> str:
    tags = normalized_tags(value)
    if len(tags) != 1:
        raise WorkError(label + " needs one tag")
    return tags[0]


def acceptance_list(value: str) -> str:
    try:
        items = json.loads(value)
    except json.JSONDecodeError as error:
        raise WorkError("--acceptance must be a JSON list of non-empty strings") from error
    if not isinstance(items, list) or not all(isinstance(item, str) and item.strip() for item in items):
        raise WorkError("--acceptance must be a JSON list of non-empty strings")
    return json.dumps(items, ensure_ascii=False, separators=(",", ":"))


SIX_FIELD_FLAGS = (
    ("problem", "--problem", "Problem"),
    ("job_when", "--job-when", "Job story When"),
    ("job_want", "--job-want", "Job story I want"),
    ("job_so", "--job-so", "Job story So I can"),
    ("body", "--body", "What it does"),
    ("context", "--context", "Context"),
)
SIX_FIELD_RULING = "g-every-task-carries-the-six-fields-a-spec-is-a-parent-task"


def six_field_values(args) -> dict[str, str]:
    """Check the text of the six fields that a call supplies."""
    values = {}
    for field, flag, _ in SIX_FIELD_FLAGS:
        value = getattr(args, field)
        if value is None:
            continue
        values[field] = one_line(value, flag) if field.startswith("job_") else optional_text(value, flag)
    return values


def six_field_refusal(args, record: str = "task or subtask") -> None:
    """A new task, subtask, or bug carries all six fields of its own; nothing is inherited."""
    missing = [] if args.title and args.title.strip() else ["Title (--title)"]
    for field, flag, label in SIX_FIELD_FLAGS:
        value = getattr(args, field)
        if value is None or not value.strip():
            missing.append(label + " (" + flag + ")")
        if field == "body" and not any(item.strip() for item in args.acceptance):
            missing.append("Acceptance (--acceptance, one or more)")
    if not any(item.strip() for item in args.where):
        missing.append("Where (--where <path>, one or more)")
    if missing:
        raise WorkError(args.verb + " refuses a " + record + " missing: " + ", ".join(missing)
                        + ". Every task, subtask, and bug carries its own six fields (" + SIX_FIELD_RULING + ")")


def where_paths(root: Path, values: list[str]) -> list[str]:
    """Return each Where path as an absolute path that exists and is not a secret."""
    paths = []
    for value in values:
        text = one_line(value, "--where")
        path = Path(text).expanduser()
        if not path.is_absolute():
            path = root / path
        path = canonical(path)
        if any(SECRET_PART.search(part) for part in path.parts):
            raise WorkError("--where targets a refused secret path: " + text)
        if not path.exists():
            raise WorkError("--where must already exist: " + text)
        if str(path) not in paths:
            paths.append(str(path))
    return paths


def has_six_fields(db: sqlite3.Connection) -> bool:
    return set(SIX_FIELD_COLUMNS) <= {row[1] for row in db.execute('PRAGMA table_info("tasks")')}


def has_bug_fields(db: sqlite3.Connection) -> bool:
    return set(BUG_FIELD_COLUMNS) <= {row[1] for row in db.execute('PRAGMA table_info("bugs")')}


def bug_where_write(db: sqlite3.Connection, bug_id: str, paths: list[str], actor: str, at: str) -> list[str]:
    """A bug has no task_links row (its task column links to tasks), so its Where is an attachment."""
    added = []
    for path in paths:
        if not db.execute(
            "SELECT 1 FROM attachments WHERE subject_type='bug' AND subject_id=? AND path=? AND role='where'",
            (bug_id, path),
        ).fetchone():
            db.execute(
                "INSERT INTO attachments (subject_type,subject_id,path,role,author,at,hash) VALUES ('bug',?,?,'where',?,?,NULL)",
                (bug_id, path, actor, at),
            )
            added.append(path)
    return added


def where_write(db: sqlite3.Connection, task_id: str, paths: list[str], at: str) -> list[str]:
    """Link each Where path to the task as an active file link; return the paths that changed."""
    added = []
    for path in paths:
        link = db.execute(
            "SELECT id,path,relation,active FROM task_links WHERE task=? AND system='file' AND external_id=?",
            (task_id, path),
        ).fetchone()
        if link is None:
            db.execute(
                "INSERT INTO task_links (task,system,scope,external_id,path,relation,active,created_on) "
                "VALUES (?,'file',NULL,?,?,'where',1,?)",
                (task_id, path, path, at),
            )
            added.append(path)
        elif link["path"] != path:
            raise WorkError("--where conflicts with an existing file link: " + path)
        elif link["active"] != 1:
            if link["relation"] != "where":
                raise WorkError("--where conflicts with an inactive file link: " + path)
            db.execute("UPDATE task_links SET active=1 WHERE id=?", (link["id"],))
            added.append(path)
    return added


def canonical(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def symlink_component(path: Path) -> Path | None:
    try:
        resolve_portfolio_path(path)
        return None
    except ValueError:
        pass
    path = Path(path).expanduser().absolute()
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            return current
    return None


def existing_path(value: Path, label: str, directory: bool = False) -> Path:
    try:
        path = resolve_portfolio_path(value)
    except ValueError as error:
        raise WorkError(label + " crosses a symlink boundary: " + str(error)) from error
    valid = path.is_dir() if directory else path.is_file()
    if not valid:
        raise WorkError(label + " must already exist: " + str(path))
    return path


def connect_database(path: Path, *, read_only: bool) -> sqlite3.Connection:
    database = existing_path(path, "database")
    mode = "ro" if read_only else "rw"
    uri = "file:" + quote(str(database), safe="/:@") + "?mode=" + mode
    db = _fox_person.connect(uri, uri=True, timeout=20, isolation_level=None)
    try:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        if db.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            raise WorkError("SQLite foreign-key enforcement is unavailable")
        validate_schema(db)
        return db
    except Exception:
        db.close()
        raise


def core_task_database(path: Path) -> bool:
    """A fresh core install has record runs, rather than tracker runs."""
    with _fox_person.connect(path.as_uri() + '?mode=ro', uri=True) as db:
        columns = {row[1] for row in db.execute('PRAGMA table_info("runs")')}
        return {'id', 'number', 'actor', 'workspace'} <= columns


def create_core_task(database: Path, args) -> str:
    """Use the core writer when the installed database uses its record model."""
    from base import core
    workspace = args.workspace or _fox_person.workspace('system')
    if not args.session:
        raise WorkError('Core task creation requires --session')
    data = {'title': one_line(args.title, '--title'), 'status': args.status or 'todo',
            'created_by': args.by, 'source': SOURCE, 'reviewer': args.check_by or 'lead'}
    if data['reviewer'] == 'lead':
        data['reviewed_by'] = _fox_person.workspace_setting(workspace, 'lead', _fox_person.leads()[0])
    if args.note:
        data['body'] = args.note
    if args.acceptance:
        data['acceptance_criteria'] = json.dumps([one_line(item, '--acceptance') for item in args.acceptance])
    if args.tags:
        raise WorkError('Core task creation does not support --tags')
    with _fox_person.connect(database.as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        def linked(table, number):
            row = db.execute('SELECT * FROM "' + table + '" WHERE number=? AND workspace=?',
                             (number, workspace)).fetchone()
            if row is None:
                raise WorkError('No such record in this workspace: ' + number)
            return row
        parent = linked('work_tasks', args.parent) if args.parent else None
        if parent and parent['parent'] is not None:
            raise WorkError('a checklist line cannot have a child')
        if parent:
            data.update(parent=parent['id'], project=parent['project'])
        if args.project:
            project = linked('work_projects', args.project)
            if project['status'] == 'replaced':
                raise WorkError('Cannot create a task in a replaced project')
            data['project'] = project['id']
        data['sort_order'] = args.ord if args.ord is not None else db.execute(
            'SELECT coalesce(max(sort_order),0)+1 FROM work_tasks WHERE workspace=? AND project IS ?',
            (workspace, data.get('project'))).fetchone()[0]
    try:
        result = core.execute(database, _person_root / 'base/blueprint', 'work_tasks', 'insert', data, None,
                              {'writer': 'agent', 'actor': args.by, 'workspace': workspace,
                               'session': args.session, 'source': SOURCE})
    except ValueError as error:
        raise WorkError(str(error)) from error
    with _fox_person.connect(database.as_uri() + '?mode=ro', uri=True) as db:
        return db.execute('SELECT number FROM work_tasks WHERE id=?', (result['id'],)).fetchone()[0]


def validate_schema(db: sqlite3.Connection) -> None:
    for table, expected in REQUIRED_COLUMNS.items():
        actual = tuple(row[1] for row in db.execute(f'PRAGMA table_info("{table}")'))
        if not actual and table in OPTIONAL_TABLES:
            continue
        allowed = ALLOWED_COLUMNS[table]
        if actual not in allowed:
            raise WorkError("unsupported work schema for table: " + table)
    for table, expected in REQUIRED_FOREIGN_KEYS.items():
        if table in OPTIONAL_TABLES and not db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone():
            continue
        actual = {
            (row[2], row[3], row[4])
            for row in db.execute(f'PRAGMA foreign_key_list("{table}")')
        }
        allowed = (expected, LEGACY_FOREIGN_KEYS.get(table, expected))
        if actual not in allowed:
            raise WorkError("unsupported work schema foreign keys for table: " + table)
    unique_columns = set()
    for index in db.execute('PRAGMA index_list("task_links")'):
        if index[2]:
            name = str(index[1]).replace('"', '""')
            unique_columns.add(tuple(row[2] for row in db.execute(f'PRAGMA index_info("{name}")')))
    if ("task", "system", "external_id") not in unique_columns:
        raise WorkError("unsupported work schema: task link identity is absent")
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='record_links'").fetchone():
        identities = set()
        for index in db.execute('PRAGMA index_list("record_links")'):
            if index[2]:
                name = str(index[1]).replace('"', '""')
                identities.add(tuple(row[2] for row in db.execute(f'PRAGMA index_info("{name}")')))
        if ("subject_type", "subject_id", "target_type", "target_id", "relation") not in identities:
            raise WorkError("unsupported work schema: record link identity is absent")


def report_existing_fk_defects(db: sqlite3.Connection, stream: TextIO) -> None:
    defects = db.execute("PRAGMA foreign_key_check").fetchall()
    if defects:
        print(f"warning: existing foreign-key defects: {len(defects)}; no repair attempted", file=stream)


def hash_descriptor(descriptor: int) -> str:
    os.lseek(descriptor, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            return digest.hexdigest()
        digest.update(chunk)


def identity(value: os.stat_result) -> tuple[int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)


def open_receipt(root: Path, value: str) -> Receipt:
    relative = Path(value)
    if not value or relative.is_absolute() or ".." in relative.parts:
        raise WorkError("receipt must be a relative path below --receipt-root: " + value)
    normalized = Path(*[part for part in relative.parts if part not in ("", ".")])
    if not normalized.parts or any(SECRET_PART.search(part) for part in normalized.parts):
        raise WorkError("receipt targets a refused secret path: " + value)
    path = canonical(root / normalized)
    if path != root and not path.is_relative_to(root):
        raise WorkError("receipt escapes --receipt-root: " + value)
    try:
        path = resolve_portfolio_path(path)
    except ValueError as error:
        raise WorkError("receipt crosses a symlink boundary: " + value + ": " + str(error)) from error
    if any(SECRET_PART.search(part) for part in path.parts):
        raise WorkError("receipt targets a refused secret path: " + value)
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as error:
        raise WorkError("receipt is missing or unsafe: " + value) from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise WorkError("receipt is not a regular file: " + value)
        digest = hash_descriptor(descriptor)
        after = os.fstat(descriptor)
        if identity(before) != identity(after):
            raise WorkError("receipt changed while it was read: " + value)
        return Receipt(root, normalized.as_posix(), path, descriptor, digest, identity(after))
    except Exception:
        os.close(descriptor)
        raise


def verify_receipt(receipt: Receipt, root: Path) -> None:
    if symlink_component(receipt.path):
        raise WorkError("receipt crossed a symlink boundary during the operation: " + receipt.relative)
    current = os.stat(receipt.path, follow_symlinks=False)
    descriptor_state = os.fstat(receipt.descriptor)
    if identity(current) != receipt.identity or identity(descriptor_state) != receipt.identity:
        raise WorkError("receipt changed during the operation: " + receipt.relative)
    if hash_descriptor(receipt.descriptor) != receipt.digest:
        raise WorkError("receipt bytes changed during the operation: " + receipt.relative)
    try:
        resolved = resolve_portfolio_path(root / receipt.relative)
    except ValueError as error:
        raise WorkError("receipt crossed a symlink boundary during the operation: " + receipt.relative) from error
    if canonical(receipt.path) != resolved:
        raise WorkError("receipt path changed during the operation: " + receipt.relative)


def task_row(db: sqlite3.Connection, task: str) -> sqlite3.Row:
    row = db.execute("SELECT * FROM tasks WHERE id=?", (task,)).fetchone()
    if row is None:
        raise WorkError("no such task: " + task)
    return row


def session_holding_task(db: sqlite3.Connection, *, required: bool = True) -> str | None:
    """Find only the reserved TEXT key; never infer identity from display fields."""
    rows = db.execute(
        "SELECT id,status,typeof(idempotency_key) FROM tasks "
        "WHERE idempotency_key COLLATE BINARY=? OR idempotency_key=CAST(? AS BLOB)",
        (SESSION_HOLDING_KEY, SESSION_HOLDING_KEY),
    ).fetchall()
    # SQLite UNIQUE permits the same bytes as TEXT and BLOB. Reject either BLOB
    # case before selecting a holder, including a BLOB alongside a valid TEXT key.
    if any(row[2] != "text" for row in rows):
        raise WorkError("corrupt session holding identity: session-holding-task must be TEXT, not BLOB; no changes made")
    if len(rows) > 1:
        raise WorkError("corrupt session holding identity: multiple TEXT keys; no changes made")
    if not rows:
        if required:
            raise WorkError(HOLDING_BACKFILL_REQUIRED)
        return None
    task, status, _ = rows[0]
    if status in {"done", "canceled", "superseded"}:
        raise WorkError(f"corrupt session holding identity: keyed task {task} is {status}; no replacement created")
    return task


def task_project(db: sqlite3.Connection, project_id: str, *, for_move: bool = False) -> str:
    project_id = one_line(project_id, "--project")
    project = db.execute("SELECT status FROM projects WHERE id=?", (project_id,)).fetchone()
    if project is None:
        raise WorkError("no such project: " + project_id)
    if project[0] == "superseded":
        raise WorkError("project is superseded: " + project_id)
    if for_move and project[0] == "canceled":
        raise WorkError("project is canceled: " + project_id)
    return project_id


def next_identifier(db: sqlite3.Connection, table: str, prefix: str, width: int = 0) -> str:
    numbers = [
        int(match.group(1))
        for row in db.execute(f'SELECT id FROM "{table}"')
        if (match := re.fullmatch(re.escape(prefix) + r"(\d+)", row[0]))
    ]
    number = (max(numbers) if numbers else 0) + 1
    return prefix + (f"{number:0{width}d}" if width else str(number))


def require_program_control(db: sqlite3.Connection) -> None:
    tables = {
        row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('programs','themes','projects')"
        )
    }
    project_columns = {row[1] for row in db.execute('PRAGMA table_info("projects")')}
    required = {"program", "theme", "needs", "order_column", "span", "alongside"}
    if tables != {"programs", "themes", "projects"} or not required.issubset(project_columns):
        raise WorkError("program control is not installed; run apply_program_schema.py")


def assert_not_final(task: sqlite3.Row, verb: str) -> None:
    if task["status"] in FINAL_STATUSES:
        raise WorkError(f"cannot {verb} final task {task['id']}: {task['status']}")


def assert_controller(task: sqlite3.Row, actor: str) -> None:
    if task["claimed_by"] and task["claimed_by"] != actor:
        raise WorkError("task is claimed by " + task["claimed_by"])
    if task["status"] == "in-progress" and not task["claimed_by"] and task["owner"] and task["owner"] != actor:
        raise WorkError("in-progress task is owned by " + task["owner"])


def activity(db: sqlite3.Connection, task: str, field: str, old, new, actor: str, at: str,
             note: str | None = None, *, verb: str) -> None:
    record_activity(db, 'task', task, field, old, new, actor, at, note, verb=verb)


def task_approval(db: sqlite3.Connection, reference: str, instruction: str) -> sqlite3.Row:
    row = db.execute("SELECT subject_type,subject_id,call,person_words FROM approvals WHERE id=?", (int(reference),)).fetchone() if reference.isdecimal() else None
    if row is None:
        raise WorkError(f"--approval {reference} must name an approvals row; {instruction}")
    if row["call"] != "approve":
        raise WorkError(f"--approval {reference} has call={row['call']}; expected approve; {instruction}")
    if row["subject_type"] != "task":
        raise WorkError(f"--approval {reference} has subject_type={row['subject_type']}; expected task; {instruction}")
    return row


def approved_accept(db: sqlite3.Connection, reference: str, task: sqlite3.Row) -> str:
    reference = one_line(reference, "--approval")
    instruction = f"record {_fox_person.display_name()}'s yes with approval-add on task {task['id']}, then pass that id"
    row = task_approval(db, reference, instruction)
    if row["subject_id"] != task["id"]:
        raise WorkError(f"--approval {reference} is for {row['subject_id']}; expected {task['id']}; {instruction}")
    if not (row["person_words"] or "").strip():
        raise WorkError(f"--approval {reference} needs non-empty person_words; {instruction}")
    return reference


def approved_rewrite(db: sqlite3.Connection, reference: str | None, task: sqlite3.Row, *, standing_move: bool = False) -> str:
    if reference is None:
        if standing_move:
            raise WorkError(f"a standing task move needs --approval <approvals id> with call=approve on task {task['id']}")
        raise WorkError("a subtask rewrite or placement change needs --approval")
    reference = one_line(reference, "--approval")
    instruction = (f"record {_fox_person.display_name()}'s yes with approval-add on standing task {task['id']}, then pass that id"
                   if standing_move else f"record {_fox_person.display_name()}'s yes with approval-add on the parent task, then pass that id")
    row = task_approval(db, reference, instruction)
    parents = {task["id"]}
    if not standing_move:
        parents.add(task["parent"])
        for history in db.execute(
            "SELECT old_value,new_value FROM activity WHERE subject_type='task' AND subject_id=? AND field='parent'",
            (task["id"],),
        ):
            parents.update(history)
    if row["subject_id"] not in parents:
        expected = task["id"] if standing_move else f"{task['id']} or a current or former parent"
        raise WorkError(f"--approval {reference} is for {row['subject_id']}; expected {expected}; {instruction}")
    return reference


def was_subtask(db: sqlite3.Connection, task: sqlite3.Row) -> bool:
    return task["parent"] is not None or db.execute(
        "SELECT 1 FROM activity WHERE subject_type='task' AND subject_id=? "
        "AND field='parent' AND (old_value IS NOT NULL OR new_value IS NOT NULL) LIMIT 1", (task["id"],)
    ).fetchone() is not None


def blocker_cycle(db: sqlite3.Connection, blocker_id: str, blocked_id: str) -> list[str] | None:
    """Return the cycle made by blocker -> blocked, across both blocker stores."""
    edges: dict[str, set[str]] = {}
    for row in db.execute("SELECT id,blocked_by FROM tasks WHERE blocked_by IS NOT NULL"):
        edges.setdefault(row["blocked_by"], set()).add(row["id"])
    for row in db.execute(
        "SELECT task,external_id FROM task_links WHERE system='task' AND relation='blocks' AND active=1"
    ):
        edges.setdefault(row["task"], set()).add(row["external_id"])
    queue = [[blocked_id]]
    seen = {blocked_id}
    for path in queue:
        for following in edges.get(path[-1], ()):
            if following == blocker_id:
                return [blocker_id, *path, blocker_id]
            if following not in seen:
                seen.add(following)
                queue.append([*path, following])
    return None


def record_activity(db: sqlite3.Connection, subject_type: str, subject_id: str, field: str, old, new,
                    actor: str, at: str, note: str | None = None, *, verb: str) -> None:
    from log import record_activity as implementation
    return implementation(db, subject_type, subject_id, field, old, new, actor, at, note, verb=verb)


def require_incident_tables(db: sqlite3.Connection) -> None:
    present = {
        row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('bugs','incidents','record_links')"
        )
    }
    if present != {"bugs", "incidents", "record_links"}:
        raise WorkError("incident tables are not installed; run apply_incidents.py")


def insert_comment(db: sqlite3.Connection, task: str, actor: str, at: str, body: str, field: str | None = None) -> int:
    if field is None:
        cursor = db.execute(
            "INSERT INTO comments (subject_type,subject_id,author,at,body) VALUES ('task',?,?,?,?)",
            (task, actor, at, body),
        )
    else:
        if "field" not in {row[1] for row in db.execute('PRAGMA table_info("comments")')}:
            raise WorkError("comments.field is missing; upgrade the tracker schema before writing comments")
        cursor = db.execute(
            "INSERT INTO comments (subject_type,subject_id,author,at,body,field) VALUES ('task',?,?,?,?,?)",
            (task, actor, at, body, field),
        )
    return int(cursor.lastrowid)


def supports_accepted(db: sqlite3.Connection) -> bool:
    row = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='tasks'").fetchone()
    return bool(row and "'accepted'" in row[0])


def has_t309(db: sqlite3.Connection) -> bool:
    return "check_by" in {row[1] for row in db.execute('PRAGMA table_info("tasks")')}


def task_finishers(
    db: sqlite3.Connection, task: sqlite3.Row,
) -> list[tuple[str, str]]:
    """Use the latest finish event, or every contributor to an older migrated review."""
    if has_t309(db):
        row = db.execute(
            "SELECT actor FROM activity WHERE subject_type='task' AND subject_id=? "
            "AND field='status' AND new_value='in-review' AND verb='finished' ORDER BY id DESC LIMIT 1",
            (task["id"],),
        ).fetchone()
        if row:
            return [(row[0], "latest finished status")]
    finishers = [(row[0], "receipt") for row in db.execute(
        "SELECT actor FROM activity WHERE subject_type='task' AND subject_id=? "
        "AND field='receipt' ORDER BY id DESC", (task["id"],),
    )]
    finishers.extend((row[0], "Proof: comment") for row in db.execute(
        "SELECT author FROM comments WHERE subject_type='task' AND subject_id=? "
        "AND substr(body,1,6)='Proof:' ORDER BY id DESC", (task["id"],),
    ))
    if task["claimed_by"]:
        finishers.append((task["claimed_by"], "claimed_by"))
    return finishers


def task_finisher(db: sqlite3.Connection, task: sqlite3.Row) -> tuple[str | None, str | None]:
    """Return the first finisher for display; permission checks use every applicable name."""
    finishers = task_finishers(db, task)
    return finishers[0] if finishers else (None, None)


def assert_not_finisher(
    db: sqlite3.Connection, task: sqlite3.Row, actor: str, action: str,
) -> None:
    for finisher, source in task_finishers(db, task):
        if finisher and finisher.strip().casefold() == actor.strip().casefold():
            raise WorkError(f"finisher rule: {finisher} finished {task['id']} ({source}); {actor} cannot {action}")


def assert_lead_seat(actor: str, action: str) -> None:
    if actor.strip().casefold() not in LEAD_SEATS:
        seats = " or ".join(LEAD_SEATS)
        raise WorkError(f"named lead seat rule: {actor} cannot {action}; name your seat: {seats}")


def assert_signer(db: sqlite3.Connection, task: sqlite3.Row, actor: str) -> None:
    checker = task["check_by"] if has_t309(db) else "lead"
    if (checker or "").strip().casefold() == _fox_person.name().casefold() or (task["owner"] or "").strip().casefold() == _fox_person.name().casefold():
        if actor.strip().casefold() != _fox_person.name().casefold():
            raise WorkError(f"{_fox_person.display_name()} must sign off this task; signer refused: " + actor)
    assert_not_finisher(db, task, actor, "sign it off")
    for field in ("owner", "claimed_by"):
        name = task[field]
        if name and name.strip().casefold() == actor.strip().casefold():
            raise WorkError(f"{field} rule: {name} is {task['id']}'s {field}; {actor} cannot sign it off")


def assert_accept_evidence(db: sqlite3.Connection, task: sqlite3.Row) -> None:
    """T649: a done receipt or hashed proof attachment must precede acceptance."""
    receipt = any((row[0] or "").strip() for row in db.execute(
        "SELECT new_value FROM activity WHERE subject_type='task' AND subject_id=? AND field='receipt'",
        (task["id"],),
    ))
    proof = any((row[0] or "").strip() and (row[1] or "").strip() for row in db.execute(
        "SELECT path,hash FROM attachments WHERE subject_type='task' AND subject_id=? "
        "AND role='produced'", (task["id"],),
    ))
    if not receipt and not proof:
        raise WorkError("task has no receipt or proof: " + task["id"])



def operation_key(task: str, actor: str, proof: str, receipts: list[Receipt]) -> str:
    value = {
        "task": task,
        "actor": actor,
        "proof": proof,
        "receipts": sorted((str(item.root), str(item.path), item.digest) for item in receipts),
    }
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def done_write(
    db: sqlite3.Connection,
    task: sqlite3.Row,
    actor: str,
    proof: str,
    receipts: list[Receipt],
    at: str,
) -> bool:
    key = operation_key(task["id"], actor, proof, receipts)
    marker = "retry-key=" + key
    previous = db.execute(
        "SELECT id FROM activity WHERE subject_type='task' AND subject_id=? AND field='receipt' AND actor=? AND source=? AND note LIKE ?",
        (task["id"], actor, SOURCE, "%" + marker),
    ).fetchone()
    if previous:
        for receipt in receipts:
            link = db.execute(
                "SELECT 1 FROM task_links WHERE task=? AND system='receipt-root' AND external_id=? AND path=? AND relation='produced' AND active=1",
                (task["id"], str(receipt.path), str(receipt.path)),
            ).fetchone()
            attached = db.execute(
                "SELECT 1 FROM attachments WHERE subject_type='task' AND subject_id=? AND path=? AND role='produced' AND hash=?",
                (task["id"], str(receipt.path), receipt.digest),
            ).fetchone()
            if not link or not attached:
                raise WorkError("duplicate receipt marker has incomplete rows; no repair attempted")
        # A bounce starts a new review round, even when proof and receipt paths repeat.
        if not has_t309(db) or task["status"] == "in-review":
            return True

    for receipt in receipts:
        source_path = str(receipt.path)
        db.execute(
            "INSERT OR IGNORE INTO task_links (task,system,scope,external_id,path,relation,active,created_on) VALUES (?,?,?,?,?,'produced',1,?)",
            (task["id"], "receipt-root", str(receipt.root), source_path, source_path, at),
        )
        link = db.execute(
            "SELECT path,relation,active FROM task_links WHERE task=? AND system='receipt-root' AND external_id=?",
            (task["id"], source_path),
        ).fetchone()
        if not link or link["path"] != source_path or link["relation"] != "produced" or link["active"] != 1:
            raise WorkError("receipt link conflicts with an existing row: " + receipt.relative)
        if not db.execute(
            "SELECT 1 FROM attachments WHERE subject_type='task' AND subject_id=? AND path=? AND role='produced' AND hash=?",
            (task["id"], source_path, receipt.digest),
        ).fetchone():
            db.execute(
                "INSERT INTO attachments (subject_type,subject_id,path,role,author,at,hash) VALUES ('task',?,?,'produced',?,?,?)",
                (task["id"], source_path, actor, at, receipt.digest),
            )
    insert_comment(db, task["id"], actor, at, "Proof: " + proof)
    migrated = has_t309(db)
    if not migrated:
        db.execute("UPDATE tasks SET flag=1 WHERE id=?", (task["id"],))
    values = ", ".join(str(item.path) for item in receipts)
    note = "Proof: " + proof + (" | " if migrated else " | flagged for review; status and acceptance unchanged | ") + marker
    activity(db, task['id'], 'receipt', None, values, actor, at, note, verb=action_word('receipt', values, subject_type='task'))
    if migrated:
        db.execute("UPDATE tasks SET status='in-review' WHERE id=?", (task["id"],))
        if task["status"] != "in-review":
            activity(db, task['id'], 'status', task['status'], 'in-review', actor, at, 'proof submitted', verb=action_word('status', 'in-review', command='done', subject_type='task'))
    return False


def optional_line(value: str | None, label: str) -> str | None:
    return None if value is None else one_line(value, label)


def optional_text(value: str | None, label: str) -> str | None:
    if value is None:
        return None
    if not value.strip():
        raise WorkError(label + " must not be empty")
    return value.strip()


def decision_statuses(db: sqlite3.Connection) -> tuple[str, ...]:
    from decisions import decision_statuses as implementation
    return implementation(db)


def ensure_replaces_text(db: sqlite3.Connection) -> None:
    from decisions import ensure_replaces_text as implementation
    return implementation(db)


def checked_replaces(db: sqlite3.Connection, replaces: str | None, statement: str | None,
                     record_id: str) -> tuple[str | None, list[str]]:
    from decisions import checked_replaces as implementation
    return implementation(db, replaces, statement, record_id)


def supersede_targets(db: sqlite3.Connection, ids: list[str], actor: str, timestamp: str,
                      replacement: str) -> None:
    from decisions import supersede_targets as implementation
    return implementation(db, ids, actor, timestamp, replacement)


def decision_add_write(db: sqlite3.Connection, args) -> str:
    from decisions import decision_add_write as implementation
    return implementation(db, args)


def decision_update_write(db: sqlite3.Connection, args) -> str:
    from decisions import decision_update_write as implementation
    return implementation(db, args)


def approval_add_write(db: sqlite3.Connection, args) -> str:
    from decisions import approval_add_write as implementation
    return implementation(db, args)


# T260: lessons every agent reads. The table is memory/lessons.sql (the Keeper owns it); this writer adds rows.
LESSON_VERBS = {"lesson-add", "lesson-update"}
LESSON_ID = re.compile(r"L[1-9][0-9]*")
LESSON_STATUSES = ("active", "replaced")


def require_lessons(db: sqlite3.Connection) -> None:
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='lessons'").fetchone():
        raise WorkError("lessons table is not installed; run python3 memory/lessons.py apply --db <data.db>")


def lesson_scope(value: str | None, label: str, kind: str) -> str | None:
    """all, or a lowercase id. A workspace must be a folder of the portfolio when the portfolio exists."""
    if value is None:
        return None
    scope = one_line(value, label)
    if scope == "all":
        return scope
    if not SLUG.fullmatch(scope):
        raise WorkError(label + " must be all or a lowercase " + kind + " id: " + scope)
    if kind == "workspace":
        from base import paths
        portfolio = paths.portfolio()
        if portfolio.is_dir() and not (portfolio / scope).is_dir():
            raise WorkError("no such workspace: " + scope + " (not a folder of " + str(portfolio) + ")")
    return scope


def lesson_replaces(db: sqlite3.Connection, value: str | None, own: str | None) -> str | None:
    if value is None:
        return None
    target = one_line(value, "--replaces")
    if not LESSON_ID.fullmatch(target):
        raise WorkError("--replaces must be one lesson id, for example L12")
    if target == own:
        raise WorkError("a lesson cannot replace itself: " + target)
    if not db.execute("SELECT 1 FROM lessons WHERE id=?", (target,)).fetchone():
        raise WorkError("no such lesson to replace: " + target)
    return target


def replace_lesson(db: sqlite3.Connection, target: str, replacement: str, actor: str, timestamp: str) -> None:
    old = db.execute("SELECT status FROM lessons WHERE id=?", (target,)).fetchone()[0]
    if old == "replaced":
        return
    db.execute("UPDATE lessons SET status='replaced' WHERE id=?", (target,))
    record_activity(db, 'lesson', target, 'status', old, 'replaced', actor, timestamp, 'replaced by ' + replacement,
                    verb=action_word('status', 'replaced', subject_type='lesson'))


def lesson_add_write(db: sqlite3.Connection, args) -> tuple[str, bool]:
    rule = one_line(args.rule, "--rule")
    source = one_line(args.source, "--source")
    same = db.execute("SELECT id FROM lessons WHERE status='active' AND lower(trim(text))=lower(?) ORDER BY id",
                      (rule,)).fetchone()
    if same:
        return same[0], True
    if db.execute("SELECT id FROM lessons WHERE source=? AND text=?", (source, rule)).fetchone():
        raise WorkError("a replaced lesson already has this rule and source; use lesson-update --status active")
    replaces = lesson_replaces(db, args.replaces, None)
    number = db.execute("SELECT coalesce(max(CAST(substr(id,2) AS INTEGER)),0)+1 FROM lessons").fetchone()[0]
    record_id = "L" + str(number)
    timestamp = now()
    db.execute(
        "INSERT INTO lessons (id,text,person_words,source,workspace,applies_to,status,replaces,created_on) "
        "VALUES (?,?,?,?,?,?,'active',?,?)",
        (record_id, rule, optional_text(args.person_words, "--person-words"), source,
         lesson_scope(args.lesson_workspace, "--lesson-workspace", "workspace") or "all",
         lesson_scope(args.applies_to, "--applies-to", "seat") or "all", replaces, timestamp[:10]),
    )
    record_activity(db, 'lesson', record_id, 'create', None, rule, args.by, timestamp, "source=" + source,
                    verb=action_word('create', rule, subject_type='lesson', command='create', status='active'))
    if replaces:
        replace_lesson(db, replaces, record_id, args.by, timestamp)
    return record_id, False


def lesson_update_write(db: sqlite3.Connection, args) -> tuple[str, bool]:
    record_id = one_line(args.task, "lesson id")
    if not LESSON_ID.fullmatch(record_id):
        raise WorkError("a lesson id is L and a number, for example L12: " + record_id)
    row = db.execute("SELECT * FROM lessons WHERE id=?", (record_id,)).fetchone()
    if not row:
        raise WorkError("no such lesson: " + record_id)
    if args.status is not None and args.status not in LESSON_STATUSES:
        raise WorkError("--status must be one of: " + ", ".join(LESSON_STATUSES))
    wanted = {
        "text": one_line(args.rule, "--rule") if args.rule is not None else None,
        "person_words": optional_text(args.person_words, "--person-words") if args.person_words is not None else None,
        "source": one_line(args.source, "--source") if args.source is not None else None,
        "workspace": lesson_scope(args.lesson_workspace, "--lesson-workspace", "workspace"),
        "applies_to": lesson_scope(args.applies_to, "--applies-to", "seat"),
        "status": args.status,
        "replaces": lesson_replaces(db, args.replaces, record_id),
    }
    if wanted["text"] is not None and db.execute(
            "SELECT 1 FROM lessons WHERE id<>? AND status='active' AND lower(trim(text))=lower(?)",
            (record_id, wanted["text"])).fetchone():
        raise WorkError("an active lesson already says this; replace that lesson instead")
    timestamp = now()
    changed = False
    for field, value in wanted.items():
        if value is None or row[field] == value:
            continue
        db.execute(f'UPDATE lessons SET "{field}"=? WHERE id=?', (value, record_id))
        record_activity(db, 'lesson', record_id, field, row[field], value, args.by, timestamp, None,
                        verb=database_action('lesson', field, row[field], value))
        changed = True
    if wanted["replaces"] and changed:
        replace_lesson(db, wanted["replaces"], record_id, args.by, timestamp)
    return record_id, not changed


def action_word(field: str, new=None, **evidence) -> str:
    word = history_action(field, new, **evidence)
    if word is None:
        raise WorkError("no reviewed history action for field: " + field)
    return word

def function_owner(value: str) -> str:
    owner = one_line(value, "--owner")
    if not ACTOR_TOKEN.fullmatch(owner):
        raise WorkError("--owner must be a plain name (letters, digits, dash, underscore): " + owner)
    return owner

def function_organization(value: str) -> str:
    organization = one_line(value, "--organization")
    if not SLUG.fullmatch(organization):
        raise WorkError("--organization must be a lowercase slug, for example cedar-shop: " + organization)
    return organization

def function_parent(db: sqlite3.Connection, record_id: str, value: str) -> str:
    parent = one_line(value, "--parent")
    if parent == record_id:
        raise WorkError("a function cannot be its own parent: " + record_id)
    if not db.execute("SELECT 1 FROM functions WHERE id=?", (parent,)).fetchone():
        raise WorkError("no such function: " + parent)
    path = [record_id]
    current = parent
    while current is not None:
        if current in path:
            raise WorkError("function parent cycle: " + " -> ".join([*path, current]))
        path.append(current)
        row = db.execute("SELECT parent FROM functions WHERE id=?", (current,)).fetchone()
        current = row[0] if row else None
    return parent

def function_values(db: sqlite3.Connection, args, record_id: str, current: sqlite3.Row | None = None) -> dict:
    """Check each supplied function field. The word none empties an optional field."""
    values: dict[str, str | None] = {}
    if args.name is not None:
        values["name"] = one_line(args.name, "--name")
    checks = (
        ("organization", function_organization),
        ("parent", lambda value: function_parent(db, record_id, value)),
        ("owner", function_owner),
        ("page", lambda value: one_line(value, "--page")),
    )
    for field, check in checks:
        raw = getattr(args, field)
        if raw is not None:
            values[field] = None if raw.strip() == EMPTY_WORD else check(raw)
    if args.tags is not None or args.add_tag or args.remove_tag:
        tags = normalized_tags(args.tags if args.tags is not None else (current["tags"] if current else None))
        for value in args.add_tag:
            tag = single_tag(value, "--add-tag")
            if tag not in tags:
                tags.append(tag)
        for value in args.remove_tag:
            tag = single_tag(value, "--remove-tag")
            tags = [item for item in tags if item != tag]
        values["tags"] = ",".join(tags) or None
    return values

def function_create_write(db: sqlite3.Connection, args) -> str:
    record_id = args.record_id
    if db.execute("SELECT 1 FROM functions WHERE id=?", (record_id,)).fetchone():
        raise WorkError("function already exists: " + record_id)
    values = function_values(db, args, record_id)
    reason = optional_line(args.note, "--note")
    timestamp = now()
    db.execute(
        "INSERT INTO functions (id,name,organization,parent,owner,page,tags,created_on) VALUES (?,?,?,?,?,?,?,?)",
        (
            record_id, values["name"], values.get("organization"), values.get("parent"),
            values.get("owner"), values.get("page"), values.get("tags"), timestamp[:10],
        ),
    )
    parts = [f"{field}={values[field]}" for field in FUNCTION_FIELDS[1:] if values.get(field) is not None]
    if reason:
        parts.append("note=" + reason)
    record_activity(db, 'function', record_id, 'create', None, values['name'], args.by, timestamp, '; '.join(parts) or None, verb=action_word('create', values['name'], subject_type='function'))
    return record_id

def function_update_write(db: sqlite3.Connection, args) -> tuple[str, bool]:
    record_id = one_line(args.task, "function id")
    row = db.execute(
        "SELECT name,organization,parent,owner,page,tags FROM functions WHERE id=?", (record_id,)
    ).fetchone()
    if row is None:
        raise WorkError("no such function: " + record_id)
    values = function_values(db, args, record_id, row)
    reason = optional_line(args.note, "--note")
    changed = {field: value for field, value in values.items() if value != row[field]}
    timestamp = now()
    for field, value in changed.items():
        db.execute(f'UPDATE functions SET "{field}"=? WHERE id=?', (value, record_id))
        record_activity(db, 'function', record_id, field, row[field], value, args.by, timestamp, reason, verb=action_word(field, value, subject_type='function'))
    return record_id, not changed

def stream_update_write(db: sqlite3.Connection, args) -> tuple[str, bool]:
    record_id = one_line(args.task, "stream id")
    row = db.execute("SELECT title,ord FROM projects WHERE id=?", (record_id,)).fetchone()
    if row is None:
        raise WorkError("no such stream: " + record_id)
    values: dict = {}
    if args.title is not None:
        values["title"] = one_line(args.title, "--title")
    if args.ord is not None:
        values["ord"] = args.ord
    reason = optional_line(args.note, "--note")
    changed = {field: value for field, value in values.items() if value != row[field]}
    timestamp = now()
    for field, value in changed.items():
        db.execute(f'UPDATE projects SET "{field}"=? WHERE id=?', (value, record_id))
        record_activity(db, 'project', record_id, field, row[field], value, args.by, timestamp, reason, verb=action_word(field, value, subject_type='project'))
    return record_id, not changed


def task_decision_link_write(db: sqlite3.Connection, args) -> bool:
    task_row(db, args.task)
    if not db.execute("SELECT 1 FROM decisions WHERE id=?", (args.decision,)).fetchone():
        raise WorkError("no such decision: " + args.decision)
    link = db.execute(
        "SELECT id,relation,active FROM task_links WHERE task=? AND system='decision' AND external_id=?",
        (args.task, args.decision),
    ).fetchone()
    relation = "step:" + args.step
    old = link["relation"] if link else None
    if old == relation and link["active"] == 1:
        return True
    if link:
        db.execute("UPDATE task_links SET relation=?,active=1 WHERE id=?", (relation, link["id"]))
    else:
        db.execute("INSERT INTO task_links(task,system,external_id,relation,active,created_on) "
                   "VALUES (?,'decision',?,?,1,?)", (args.task, args.decision, relation, now()))
    timestamp = now()
    note = "Decision " + args.decision + "; " + (old + " -> " if old else "") + relation
    insert_comment(db, args.task, args.by, timestamp, "Linked " + note)
    if old != relation:
        record_activity(db, 'task', args.task, 'link', old, relation, args.by, timestamp, 'decision=' + args.decision, verb=action_word('link', relation))
    if link and link["active"] != 1:
        record_activity(db, 'task', args.task, 'active', link['active'], 1, args.by, timestamp, 'decision=' + args.decision, verb='updated')
    return False


def goal_create_write(db: sqlite3.Connection, args) -> str:
    title = one_line(args.title, "--title")
    if args.horizon not in {"north-star", "3-year", "1-year", "quarter"}:
        raise WorkError("--horizon must be north-star, 3-year, 1-year, or quarter")
    status = args.status or "on-track"
    if status not in {"on-track", "at-risk", "off-track", "done", "dropped", "superseded"}:
        raise WorkError("goal --status must be on-track, at-risk, off-track, done, dropped, or superseded")
    record_id = one_line(args.record_id, "--id") if args.record_id is not None else next_identifier(db, "goals", "G")
    if db.execute("SELECT 1 FROM goals WHERE id=?", (record_id,)).fetchone():
        raise WorkError("goal already exists: " + record_id)
    function = optional_line(args.function, "--function")
    if function and not db.execute("SELECT 1 FROM functions WHERE id=?", (function,)).fetchone():
        raise WorkError("no such function: " + function)
    period = optional_line(args.period, "--period")
    owner = optional_line(args.owner, "--owner")
    tags = ",".join(normalized_tags(args.tags)) or None
    timestamp = now()
    db.execute("INSERT INTO goals(id,title,horizon,period,function,owner,status,tags,created_on) VALUES (?,?,?,?,?,?,?,?,?)",
               (record_id, title, args.horizon, period, function, owner, status, tags, timestamp[:10]))
    note = "horizon=" + args.horizon + ("; period=" + period if period else "")
    db.execute("INSERT INTO comments(subject_type,subject_id,author,at,body) VALUES ('goal',?,?,?,?)",
               (record_id, args.by, timestamp, "Created goal: " + title + "; " + note))
    record_activity(db, 'goal', record_id, 'create', None, title, args.by, timestamp, note, verb=action_word('create', title))
    return record_id


def export_after_write(database: Path, root: Path, errors: TextIO) -> None:
    script = (Path(__file__).resolve().parent / '../base/backup.py')
    try:
        spec = importlib.util.spec_from_file_location("work_export_state", script)
        if spec is None or spec.loader is None:
            raise RuntimeError("backup.py could not be loaded")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.export_state(database, database.resolve().parent / "state")
    except Exception as error:
        message = " ".join(str(error).splitlines())
        print("warning: state export failed: " + message, file=errors)


def path_move_workspace(db: sqlite3.Connection, table: str, row, portfolio: Path, source: Path, destination: Path, legacy_workspace=None) -> Path:
    """Resolve row ownership from its subject, never from the command receipt root."""
    def subject(kind, identifier, seen):
        key = (kind, str(identifier))
        if key in seen:
            raise WorkError('path-move subject ownership cycle: ' + str(identifier))
        seen = seen | {key}
        if kind == 'workspace':
            return str(identifier)
        if kind == 'run':
            item = db.execute('SELECT * FROM runs WHERE id=?', (identifier,)).fetchone()
            return subject(item['subject_type'], item['subject_id'], seen) if item else None
        name = {'task': 'tasks', 'stream': 'projects', 'project': 'projects', 'bug': 'bugs'}.get(kind)
        if name is None:
            return None
        item = db.execute(f'SELECT * FROM {name} WHERE id=?', (identifier,)).fetchone()
        if item is None:
            return None
        values = dict(item)
        owners = set(re.findall(r'(?:^|,)\s*workspace:([a-z0-9-]+)\s*(?=,|$)', values.get('tags') or ''))
        if values.get('workspace'):
            owners.add(values['workspace'])
        try:
            extra = json.loads(values.get('extra') or '{}')
        except (ValueError, TypeError):
            extra = {}
        if isinstance(extra, dict) and extra.get('workspace'):
            owners.add(extra['workspace'])
        if len(owners) > 1:
            raise WorkError('path-move conflicting workspaces: ' + str(identifier))
        if owners:
            return owners.pop()
        if values.get('parent'):
            inherited = subject(kind, values['parent'], seen)
            if inherited:
                return inherited
        if values.get('project'):
            return subject('project', values['project'], seen)
        return None

    owner = subject('task', row['task'], set()) if table == 'task_links' else subject(row['subject_type'], row['subject_id'], set())
    # Legacy subjects omit their system scope. A unique existing foreign file
    # supplies stronger provenance than that default for a relative reference.
    if owner is None and legacy_workspace is not None:
        return Path(legacy_workspace)
    if owner is None:
        default = _fox_person.workspace('system')
        columns = {'runs': ('evidence',), 'task_links': ('path', 'external_id'),
                   'attachments': ('path',), 'comments': ('body',),
                   'activity': ('old_value', 'new_value', 'note')}[table]
        references = set()
        for column in columns:
            text = row[column]
            if isinstance(text, str):
                references.update(re.findall(r"(?<![\w./~:-])(?:history|team|state|wiki|notes|ops)/[^\s`<>\"'()\[\]{},;]+", text))
        provenance = set()
        for reference in references:
            reference = reference.rstrip('.:!?')
            if '..' in Path(reference).parts or not Path(reference).suffix:
                continue
            expected = portfolio / default / reference
            if not expected.is_relative_to(source):
                continue
            if expected.exists():
                continue
            candidates = {folder.name for folder in portfolio.iterdir()
                          if re.fullmatch(r'[a-z][a-z0-9-]*', folder.name)
                          and not destination.is_relative_to(folder)
                          and folder.is_dir() and (folder / reference).is_file()}
            if len(candidates) > 1:
                raise WorkError('path-move relative reference has ambiguous workspace: ' + reference)
            provenance.update(candidates)
        if len(provenance) > 1:
            raise WorkError('path-move row has conflicting relative workspace references')
        owner = next(iter(provenance), default)
    if not isinstance(owner, str) or not re.fullmatch(r'[a-z][a-z0-9-]*', owner):
        raise WorkError('path-move invalid workspace ownership')
    return portfolio / owner


def path_move_plan(db: sqlite3.Connection, root: Path, old: str, new: str, legacy_workspaces=None) -> list[dict]:
    """Map receipt references using the workspace of each subject row."""
    from base.paths import portfolio as portfolio_path
    portfolio = portfolio_path()

    def prefix(value, relative_root):
        if not value or '\n' in value or '\r' in value:
            raise WorkError('path-move prefixes must be nonempty paths')
        expanded = os.path.expanduser(value)
        path = Path(os.path.abspath(expanded if Path(expanded).is_absolute() else relative_root / expanded))
        if any(SECRET_PART.search(part) for part in path.parts) or '..' in Path(value).parts:
            raise WorkError('path-move prefix is unsafe: ' + value)
        return path

    source, destination = prefix(old, root), prefix(new, root)
    if source == destination or source == Path('/'):
        raise WorkError('path-move needs distinct, non-root prefixes')
    changes = []
    selections = (
        ('runs', ('evidence',), '1'),
        ('task_links', ('scope', 'external_id', 'path'), "system='receipt-root'"),
        ('attachments', ('path',), '1'),
        ('activity', ('old_value', 'new_value', 'note'), "field IN ('receipt','comment') AND subject_type!='path-move'"),
        ('comments', ('body',), '1'),
    )
    for table, columns, condition in selections:
        for row in db.execute(f'SELECT * FROM {table} WHERE {condition} ORDER BY id').fetchall():
            workspace = path_move_workspace(db, table, row, portfolio, source, destination,
                                            (legacy_workspaces or {}).get((table, row['id'])))
            variants = {str(source)}
            if source.is_relative_to(workspace):
                variants.add(source.relative_to(workspace).as_posix())
            if source.is_relative_to(Path.home()):
                variants.add('~/' + source.relative_to(Path.home()).as_posix())
            alternatives = '|'.join(re.escape(v) for v in sorted(variants, key=len, reverse=True))
            expression = re.compile(
                r"(?:(?<=[`<\"'])(?:" + alternatives + r")(?=/|[`>\"'])(?:/[^\n`<>\"']*)?"
                r"|(?<![\w./~:-])(?:" + alternatives
                + r")(?=/|$|[\s`<>\"'()\[\]{},;.!?])(?:/[^\s`<>\"'()\[\]{},;]*)?)")
            for column in columns:
                value = row[column]
                if not value:
                    continue
                targets = []

                def replace(match):
                    text = match.group().rstrip('.:!?')
                    base = next(v for v in sorted(variants, key=len, reverse=True)
                                if text == v or text.startswith(v + '/'))
                    suffix = text[len(base):].lstrip('/')
                    if '..' in Path(suffix).parts:
                        raise WorkError('path-move refuses traversal: ' + text)
                    if not base.startswith(('~', '/')) and not Path(text).suffix:
                        return match.group()
                    target = destination / suffix
                    targets.append(str(target))
                    return str(target) + match.group()[len(text):]

                if table in {'runs', 'task_links', 'attachments'} or (
                    table == 'activity' and row['field'] == 'receipt'
                    and column in {'old_value', 'new_value'} and ', ' not in value
                    and any(value == v or value.startswith(v + '/') for v in variants)
                ):
                    if '..' in Path(value).parts:
                        raise WorkError('path-move refuses traversal: ' + value)
                    expanded = prefix(value, workspace)
                    if expanded == source or source in expanded.parents:
                        target = destination / expanded.relative_to(source)
                        targets.append(str(target))
                        updated = str(target)
                    else:
                        updated = value
                else:
                    updated = expression.sub(replace, value)
                if updated != value:
                    changes.append(dict(table=table, id=row['id'], column=column,
                                        old=value, new=updated, targets=targets, workspace=str(workspace),
                                        row_sha256=hashlib.sha256(json.dumps(dict(row), sort_keys=True).encode()).hexdigest()))
            if table == 'task_links' and row['scope'] == str(workspace) and source.is_relative_to(workspace):
                suffix = source.relative_to(workspace).parts
                moved_path = any(item['table'] == table and item['id'] == row['id']
                                 and item['column'] in {'path', 'external_id'} for item in changes)
                moved_scope = any(item['table'] == table and item['id'] == row['id']
                                  and item['column'] == 'scope' for item in changes)
                if moved_path and not moved_scope and suffix and destination.parts[-len(suffix):] == suffix:
                    scope = destination.parents[len(suffix) - 1]
                    changes.append(dict(table=table, id=row['id'], column='scope', old=row['scope'],
                                        new=str(scope), targets=[str(scope)], workspace=str(workspace),
                                        row_sha256=hashlib.sha256(json.dumps(dict(row), sort_keys=True).encode()).hexdigest()))
    return changes


def path_move_write(db: sqlite3.Connection, args, root: Path, output: TextIO) -> int:
    """Save a checked pre-move plan, or apply its exact changes in one transaction."""
    read_only = args.dry_run or args.plan_out is not None
    db.execute('BEGIN' if read_only else 'BEGIN IMMEDIATE')
    try:
        saved = None
        if args.plan:
            if symlink_component(args.plan) or any(SECRET_PART.search(part) for part in args.plan.parts):
                raise WorkError('path-move plan path is unsafe')
            try:
                saved = json.loads(args.plan.read_text())
            except ValueError as error:
                raise WorkError('path-move plan JSON is invalid') from error
            if not isinstance(saved, dict) or saved.get('format') != 'foxrun-path-move/v1':
                raise WorkError('path-move plan format is invalid')
            if not all(isinstance(saved.get(key), str) for key in ('database', 'from', 'to')) or not isinstance(saved.get('changes'), list):
                raise WorkError('path-move plan fields are invalid')
            if saved.get('database') != str(args.db.expanduser().resolve()):
                raise WorkError('path-move plan belongs to another database')
            if not all(isinstance(item, dict) and all(key in item for key in ('table', 'id', 'workspace'))
                       and isinstance(item['workspace'], str) for item in saved['changes']):
                raise WorkError('path-move plan changes are invalid')
            args.path_from, args.path_to = saved['from'], saved['to']
        legacy_workspaces = {(item['table'], item['id']): item['workspace'] for item in saved['changes']} if saved else None
        changes = path_move_plan(db, root, args.path_from, args.path_to, legacy_workspaces)
        if saved and saved.get('changes') != changes:
            raise WorkError('path-move plan is stale: rows or workspace ownership changed; rebuild before moving')
        source = Path(os.path.abspath(os.path.expanduser(args.path_from)))
        destination = Path(os.path.abspath(os.path.expanduser(args.path_to)))
        if not Path(args.path_from).is_absolute():
            source = Path(os.path.abspath(root / args.path_from))
        if not Path(args.path_to).is_absolute():
            destination = Path(os.path.abspath(root / args.path_to))
        targets = sorted({target for change in changes for target in change['targets']})
        missing = []
        for target in targets:
            path = Path(target)
            if any(SECRET_PART.search(part) for part in path.parts) or symlink_component(path):
                raise WorkError('path-move destination is unsafe: ' + target)
            original = source / path.relative_to(destination) if path.is_relative_to(destination) else None
            # Aligned receipt scope is the destination parent; its source is root.
            if original is None and destination.is_relative_to(path):
                original = source.parents[len(destination.relative_to(path).parts) - 1]
            if args.plan_out and original and symlink_component(original):
                raise WorkError('path-move source is unsafe: ' + str(original))
            if not path.exists() and not (args.plan_out and original and original.exists()):
                missing.append(target)
        if missing:
            label = 'source or destination must exist' if args.plan_out else 'destination must already exist'
            raise WorkError('path-move ' + label + ' (' + str(len(missing)) + '): ' + ', '.join(missing))
        if args.plan_out:
            if symlink_component(args.plan_out) or args.plan_out.exists() or any(SECRET_PART.search(part) for part in args.plan_out.parts):
                raise WorkError('path-move plan output must be a new, regular path')
            body = json.dumps(dict(format='foxrun-path-move/v1', database=str(args.db.expanduser().resolve()),
                                   **{'from': str(source), 'to': str(destination)}, changes=changes), indent=2) + '\n'
            from base.paths import system_home, portfolio
            if any(args.plan_out.absolute().is_relative_to(home) for home in (system_home(), portfolio())):
                import subprocess
                import tempfile
                if args.plan_out.absolute().is_relative_to(system_home()):
                    guard = subprocess.run([sys.executable, str(system_home() / 'base/ownership.py'),
                                            'write-check', str(args.plan_out)], capture_output=True)
                    if guard.returncode:
                        raise WorkError('path-move plan output failed ownership check')
                with tempfile.NamedTemporaryFile(mode='w') as draft:
                    draft.write(body)
                    draft.flush()
                    check = subprocess.run([sys.executable, str(system_home() / 'base/lint_gate.py'),
                                            '--mode', 'write', '--target', str(args.plan_out), '--body', draft.name],
                                           capture_output=True)
                    if check.returncode:
                        raise WorkError('path-move plan output failed write lint')
            # Plan parents must be prepared by their owner outside the move trees.
            with args.plan_out.open('x') as stream:
                stream.write(body)
        if read_only:
            db.execute('ROLLBACK')
        else:
            timestamp = now()
            for change in changes:
                db.execute(f"UPDATE {change['table']} SET {change['column']}=? WHERE id=?",
                           (change['new'], change['id']))
                record_activity(db, 'path-move', str(change['id']), change['table'] + '.' + change['column'],
                                change['old'], change['new'], args.by, timestamp,
                                'path-move ' + args.path_from + ' -> ' + args.path_to, verb='moved')
            db.execute('COMMIT')
        for change in changes:
            print(json.dumps(change, ensure_ascii=False, sort_keys=True), file=output)
        mode = 'plan-out' if args.plan_out else 'dry-run' if args.dry_run else 'applied'
        print('ok path-move ' + mode + ' changes=' + str(len(changes)), file=output)
        return len(changes)
    except Exception:
        if db.in_transaction:
            db.execute('ROLLBACK')
        raise


OWNERSHIP_TAG = 'ownership-alarm'


def ownership_task(task):
    tags = task['tags']
    return isinstance(tags, str) and OWNERSHIP_TAG in [tag.strip() for tag in tags.split(',')]


def ownership_write(db, args):
    from base import ownership, paths
    home = paths.system_home()
    timestamp = now()
    if args.verb == 'ownership-alarm':
        detail = ownership.write_details(home, args.write_path, args.by)
        if detail['owner'] == args.by:
            raise WorkError('writer owns this path; no alarm is needed')
        lead = detail['owner'] or _fox_person.leads()[0]
        workspace = args.workspace or _fox_person.workspace()
        detail.update(workspace=workspace, lead=lead)
        key = 'ownership-alarm:' + hashlib.sha256(json.dumps(detail, sort_keys=True).encode()).hexdigest()
        prior = db.execute("SELECT * FROM tasks WHERE idempotency_key=? AND status='blocked'", (key,)).fetchone()
        old = 'open' if prior else None
        if prior:
            task_id = prior['id']
        else:
            if not has_six_fields(db):
                raise WorkError('ownership alarms need the problem and job story columns')
            numbers = [int(m.group(1)) for row in db.execute('SELECT id FROM tasks')
                       if (m := re.fullmatch(r'T(\d+)', row[0]))]
            task_id = 'T' + str(max(numbers, default=0) + 1)
            title = 'Ownership alarm: ' + str(Path(detail['target']).relative_to(home.resolve()))
            note = (args.by + ' -> ' + detail['target'] + '; owner=' + str(detail['owner']) +
                    '; ' + detail['reason'] + '; lead=' + lead)
            db.execute(
                "INSERT INTO tasks (id,title,status,owner,created_by,created_on,source,note,acceptance,tags,idempotency_key,"
                "problem,job_when,job_want,job_so,body,context) VALUES (?,?,'blocked',?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (task_id, title, lead, args.by, timestamp, SOURCE, note,
                 json.dumps(['A second person clears this alarm with a logged reason.']),
                 OWNERSHIP_TAG + ',workspace:' + workspace, key,
                 'A writer requested a path outside its area.', 'A write crosses an ownership boundary.',
                 'The owning lead reviews the blocked write.', 'The decision stays in the event trail.',
                 note, 'ownership.write-check; use ownership-clear with --reason and --by'))
        activity(db, task_id, 'ownership_alarm', old, 'open', args.by, timestamp,
                 json.dumps(detail, sort_keys=True), verb='created' if old is None else 'updated')
        return task_id
    task = task_row(db, args.task)
    if not ownership_task(task):
        raise WorkError('not an ownership alarm: ' + args.task)
    first = db.execute("SELECT * FROM activity WHERE subject_type='task' AND subject_id=? "
                       "AND field='ownership_alarm' AND old_value IS NULL ORDER BY id LIMIT 1", (args.task,)).fetchone()
    latest = db.execute("SELECT * FROM activity WHERE subject_type='task' AND subject_id=? "
                        "AND field='ownership_alarm' ORDER BY id DESC LIMIT 1", (args.task,)).fetchone()
    if first is None or latest is None:
        raise WorkError('alarm has no event trail')
    detail = json.loads(first['note'])
    if args.workspace and args.workspace != detail['workspace']:
        raise WorkError('alarm belongs to another workspace')
    if args.verb == 'ownership-clear':
        # The ruled decision requires a reason and a second person, not a seat whitelist.
        if args.by.casefold() == first['actor'].casefold():
            raise WorkError('the writer cannot clear its own alarm; a second person must clear it')
        if latest['new_value'] != 'open' or task['status'] != 'blocked':
            raise WorkError('alarm is not open: ' + args.task)
        activity(db, args.task, 'ownership_alarm', 'open', 'cleared', args.by, timestamp, args.reason, verb='accepted')
        db.execute("UPDATE tasks SET status='done',idempotency_key=NULL WHERE id=?", (args.task,))
        return args.task
    if latest['new_value'] != 'cleared' or task['status'] != 'done':
        raise WorkError('alarm is not cleared: ' + args.task)
    current = ownership.write_details(home, args.write_path, args.by)
    if any(current[key] != detail[key] for key in ('target', 'area', 'owner', 'writer')):
        raise WorkError('cleared alarm does not match this writer, path, and owner')
    if not (latest['note'] or '').strip() or latest['actor'].casefold() == first['actor'].casefold():
        raise WorkError('clearing needs a reason and a second person')
    return args.task


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Flags: done --by --proof <path> (repeatable) --note <words> (sets in-review); accept --by (sets done); "
            "For one release, done --receipt <path> --proof <words> remains an alias. "
            "sign-off requires a done receipt or hashed proof attachment and a signer "
            "who is neither finisher, owner, nor claimed_by; no lead seat is required. "
            "check by person requires person; owner person uses recorded approval. "
            "On migrated reviews, every receipt actor and Proof: author is a finisher. "
            "--by lead is retired: name your seat. "
            f"accept --approval <id> uses {_fox_person.display_name()}'s task approval with non-empty person_words, bypassing signer rules; evidence is still required. "
            "bounce <task> <reason> --by <actor> (named lead seat or person, never the finisher; "
            "in-review to in-progress, verb bounced; subtasks need no --approval); "
            "ownership-alarm --write-path <path> --by <writer>; "
            "ownership-clear <alarm> --reason <reason> --by <reviewer>; "
            "ownership-check <alarm> --write-path <path> --by <writer>; "
            "flag <task> <reason> --by <actor>; unflag <task> <reason> --by <actor> "
            "(attention flags on tasks and subtasks; no --approval); "
            "comment --by --field <task field> --flag (comment only; does not set tasks.flag; "
            "use flag to set tasks.flag); "
            "create without --project makes an inbox task; "
            "create needs the six fields for every task and subtask: --title --problem --job-when --job-want --job-so "
            "--body (what it does) --acceptance (one or more) --context --where <path> (one or more); "
            "task-move <task> --project <stream id> --by <actor> [--note <reason>] "
            "(or --inbox); "
            "run-end --result --proof <path> --fix-rounds (--evidence is an alias for one release); run-move <run> --task <task> --by <actor>; "
            "task-update --by --title --note "
            "--append-note --acceptance (JSON list) --problem --job-when --job-want --job-so --body --context "
            "--where <path> --tags --add-tag --remove-tag "
            "--parent <task|none> --approval <approve row id> for subtask rewrites; "
            "bug-close --by --status fixed|wont-fix --note; "
            "bug-open --id --title --capability --by and the six fields (--problem --job-when --job-want --job-so "
            "--body (what the fix changes) --acceptance --context --where), --tags optional; "
            "bug-update <bug> --by --tags --add-tag --remove-tag --problem --job-when --job-want --job-so --body "
            "--acceptance (JSON list) --context --where; "
            "run-start --by --model --runtime --session --desktop-session --note; "
            "link --by --subject-type incident|bug --target-type --target-id --relation [--remove]; "
            "link-task <blocker> --blocks <blocked task> --by <actor> [--remove]; "
            "task-update --owner <name> (comment and activity trail like the other fields).\n"
            "task-rank <task> --ord <integer> --by <actor>; task-update also accepts --ord.\n"
            "stream-update <stream id> --by <actor> [--title <title>] [--ord <integer at least 1>] [--note <reason>] "
            "(one change row per changed field, old and new value; a repeat prints duplicate and writes nothing).\n"
            "backlog <task> --by <actor> [--note <reason>]; todo <task> --by <actor> [--note <reason>].\n"
            "task-decision-link <task> --decision <id> --step <number-or-number-letter> --by <actor>.\n"
            "goal-create --title --horizon north-star|3-year|1-year|quarter --by [--id --period --function --owner --tags --status]; "
            "task-goal <task> --goal <id> --by <actor>.\n"
            f"Promote {_fox_person.display_name()}'s words (rule source-note): "
            "decision-add --id <slug> --name --statement --person-words --status (default ruled; "
            "the decisions CHECK list) --source (for example comment:<id>) --project --function --tags "
            "--decided-on YYYY-MM-DD (default today) --replaces <decision ids|clause|none> --partial --by; "
            "decision-update <id> --replaces <decision ids|clause|none> --status --partial --note --by; "
            "approval-add <subject id> --subject-type (default task) --call approve|discuss|wrong|edit "
            "--person-words --given-at (default now) --source --version --by.\n"
            "decision-add refuses a duplicate id and, with --source comment:<id>, a second decision citing that comment. "
            "approval-add refuses a second row with the same subject, call, and source.\n"
            "Lessons every agent reads (memory/lessons.sql): "
            "lesson-add --rule <one line> --source <task, comment, session, handoff, or file> "
            "[--person-words] [--lesson-workspace <workspace>|all] [--applies-to <seat>|all] [--replaces <lesson id>] --by; "
            "lesson-update <lesson id> [--rule --person-words --source --lesson-workspace --applies-to "
            "--status active|replaced --replaces] --by. lesson-add prints the new id, or the id of an active lesson "
            "with the same rule plus duplicate; --replaces marks the old lesson replaced.\n"
            "Functions are structure rows (source-note): "
            "function-create --id <slug> --name --organization <slug> --owner <name> --parent <function id> "
            "--page --tags --note <reason> --by (writes one functions row and one create change row; "
            "refuses a duplicate id, an unknown parent, an owner that is not a plain name, "
            "and an organization that is not a lowercase slug); "
            "function-update <id> takes each field alone: --name --organization --owner --parent --page "
            "--tags --add-tag --remove-tag --note <reason> --by (one change row per changed field, old and new value; "
            "the word none empties organization, owner, parent, or page; "
            "refuses --id: a function id never changes).\n"
            "Function examples (also pass --db and --receipt-root):\n"
            "  function-create --id communications --name Communications --owner comms-lead --by chief-of-staff\n"
            "  function-update communications --owner comms-lead --note \"owner named\" --by chief-of-staff\n"
            "kind and skip are tags, not columns: set them with create --tags or task-update --add-tag/--remove-tag.\n"
            "A standing task move needs --approval <approvals id> with call=approve on that task; it cannot leave to the inbox.\n"
            "Cedar Shop link examples (also pass --db and --receipt-root):\n"
            "  link B-1 --subject-type bug --target-type task --target-id T1 --relation fix --by sol\n"
            "  link I-1 --subject-type incident --target-type bug --target-id B-1 --relation caused-by --by sol\n"
            "  link I-1 --subject-type incident --target-type run --target-id R-1 --relation found-in --by sol\n"
            "  link I-1 --subject-type incident --target-type task --target-id T1 --relation updated --by sol\n"
            "  link B-1 --subject-type bug --target-type project --target-id WS01 --relation about --by sol"
        ),
    )
    parser.add_argument("--write-path", help="ownership-alarm/check: requested system path")
    parser.add_argument("--db", type=Path)
    parser.add_argument("--workspace", help="workspace tracker; workspace data.db takes precedence")
    parser.add_argument("--receipt-root", type=Path, required=True)
    parser.add_argument("verb", choices=("claim", "comment", "flag", "unflag", "create", "program-create", "theme-create", "stream-create", "stream-update", "function-create", "function-update", "goal-create", "task-goal", "done", "accept", "bounce", "cancel", "block", "backlog", "todo", "show", "run-start", "run-note", "run-end", "run-move", "incident-open", "incident-close", "bug-open", "bug-update", "link", "link-task", "task-decision-link", "task-update", "task-rank", "task-move", "bug-close", "decision-add", "decision-update", "approval-add", "lesson-add", "lesson-update", "path-move", "ownership-alarm", "ownership-clear", "ownership-check"))
    parser.add_argument("task", nargs="?")
    parser.add_argument("text", nargs="?")
    parser.add_argument("--from", dest="path_from", help="path-move: old path prefix")
    parser.add_argument("--to", dest="path_to", help="path-move: new path prefix")
    parser.add_argument("--dry-run", action="store_true", help="path-move: validate without writing")
    plan_mode = parser.add_mutually_exclusive_group()
    plan_mode.add_argument("--plan-out", type=Path, help="path-move: save a checked plan before moving")
    plan_mode.add_argument("--plan", type=Path, help="path-move: apply exactly this saved plan")
    parser.add_argument("--by")
    parser.add_argument("--decision", help="task-decision-link: decision id")
    parser.add_argument("--step", help="task-decision-link: positive step number with optional lowercase letter, for example 2b")
    parser.add_argument("--horizon", help="goal-create: north-star, 3-year, 1-year, or quarter")
    parser.add_argument("--period", help="goal-create: period, for example 2026-Q4")
    parser.add_argument("--goal", help="task-goal: existing goal id")
    parser.add_argument("--takeover")
    parser.add_argument("--receipt", action="append", default=[])
    parser.add_argument("--proof", action="append", default=[], help="done/run-end: proof file path; old done --receipt calls use one proof line")
    parser.add_argument("--business-input", action="store_true")
    parser.add_argument("--model")
    parser.add_argument("--runtime")
    parser.add_argument("--session")
    parser.add_argument("--task", dest="target_task", help="run-move: destination task id")
    parser.add_argument("--desktop-session")
    parser.add_argument("--fix-rounds", type=int)
    parser.add_argument("--result")
    parser.add_argument("--evidence")
    parser.add_argument("--title")
    parser.add_argument("--tags")
    parser.add_argument("--add-tag", action="append", default=[])
    parser.add_argument("--remove-tag", action="append", default=[])
    parser.add_argument("--name")
    parser.add_argument("--objective")
    parser.add_argument("--project")
    parser.add_argument("--inbox", action="store_true", help="task-move: move the task out of a stream")
    parser.add_argument("--program")
    parser.add_argument("--theme")
    parser.add_argument("--function")
    parser.add_argument("--tagline")
    parser.add_argument("--order", type=int)
    parser.add_argument("--status")
    parser.add_argument("--note")
    parser.add_argument("--append-note")
    parser.add_argument("--acceptance", action="append", default=[])
    parser.add_argument("--problem", help="create, task-update: the problem this task solves")
    parser.add_argument("--job-when", dest="job_when", help="create, task-update: job story, When ...")
    parser.add_argument("--job-want", dest="job_want", help="create, task-update: job story, I want ...")
    parser.add_argument("--job-so", dest="job_so", help="create, task-update: job story, So I can ...")
    parser.add_argument("--body", help="create, task-update: what it does")
    parser.add_argument("--context", help="create, task-update: context")
    parser.add_argument("--where", action="append", default=[],
                        help="create, task-update: a linked file or folder (repeatable); relative paths start at --receipt-root")
    parser.add_argument("--ord", type=int)
    parser.add_argument("--parent")
    parser.add_argument("--approval", help="approvals row id with call=approve; accept: this task with non-empty person_words; task-update: this task or its current or former parent; standing task-move: this task only")
    parser.add_argument("--blocks", help="link-task: blocked task id")
    parser.add_argument("--remove", action="store_true", help="link, link-task: remove only this matching link")
    parser.add_argument("--id", dest="record_id")
    parser.add_argument("--started-at")
    parser.add_argument("--ended-at")
    parser.add_argument("--impact")
    parser.add_argument("--restored-by")
    parser.add_argument("--rca-cause")
    parser.add_argument("--bug")
    parser.add_argument("--description")
    parser.add_argument("--capability")
    parser.add_argument("--subject-type", help="link: incident or bug; approval-add: subject table, default task")
    parser.add_argument("--target-type", choices=("task", "project", "function", "theme", "run", "decision", "incident", "bug"))
    parser.add_argument("--target-id")
    parser.add_argument("--relation", choices=("fix", "caused-by", "found-in", "updated", "about"))
    parser.add_argument("--source")
    parser.add_argument("--field", help="task field a comment is about, for example title or acceptance")
    parser.add_argument("--flag", action="store_true", help="comment only: add 'Flag: ' once; does not set tasks.flag; use flag to set it")
    parser.add_argument("--owner", help="task-update, goal-create, function-create/update: owner")
    parser.add_argument("--organization", help="function-create/update: lowercase organization slug")
    parser.add_argument("--page", help="function-create/update: readable function page")
    parser.add_argument("--check-by", choices=("lead", _fox_person.name()), help="task checker")
    parser.add_argument("--reason", help="cancel, ownership-clear: required reason")
    parser.add_argument("--folded-into", help="cancel: task that absorbs this work")
    parser.add_argument("--statement", help="decision-add: the decision in one or more sentences")
    parser.add_argument("--person-words", dest="person_words", help="decision-add, approval-add: configured person's exact words")
    parser.add_argument("--decided-on", help="decision-add: YYYY-MM-DD, default today")
    parser.add_argument("--replaces", help="decision-add/update: ids, clause text, or none")
    parser.add_argument("--partial", action="store_true", help="decision-add/update: record ids without superseding targets")
    parser.add_argument("--call", choices=APPROVAL_CALLS, help="approval-add: approve, discuss, wrong, or edit")
    parser.add_argument("--given-at", help="approval-add: ISO time, default now")
    parser.add_argument("--version", help="approval-add: version of the subject that was approved")
    parser.add_argument("--rule", help="lesson-add/update: the lesson in one line")
    parser.add_argument("--applies-to", dest="applies_to", help="lesson-add/update: all, or one seat id")
    parser.add_argument("--lesson-workspace", dest="lesson_workspace", help="lesson-add/update: all, or one workspace")
    return parser


def run(
    argv: list[str] | None = None,
    *,
    before_final_receipt_check: Callable[[], None] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    output = stdout or sys.stdout
    errors = stderr or sys.stderr
    receipts: list[Receipt] = []
    try:
        argv = list(sys.argv[1:] if argv is None else argv)
        if "finish-job" in argv:
            raise WorkError(RETIRED_JOB_MESSAGE)
        for flag in RETIRED_FLAGS:
            if any(arg == flag or arg.startswith(flag + "=") for arg in argv):
                raise WorkError(f"{flag} is retired. Use run-start on a task, then run-end.")
        args = build_parser().parse_intermixed_args(argv)
        root = existing_path(args.receipt_root, "receipt root", directory=True)
        if any(SECRET_PART.search(part) for part in root.parts):
            raise WorkError("receipt root is a refused secret path")
        if args.workspace is not None:
            from base.tracker import tracker
            try:
                args.db = tracker(args.workspace, args.db)
            except ValueError as error:
                raise WorkError(str(error)) from error
        if args.db is None:
            raise WorkError("--db or --workspace is required for work actions")
        if args.verb.startswith('ownership-'):
            if not args.by:
                raise WorkError('--by is required: who is writing')
            if args.verb == 'ownership-clear':
                args.reason = one_line(args.reason, '--reason')
                if args.write_path is not None or args.text:
                    raise WorkError('ownership-clear needs an alarm id, --reason, and --by')
            else:
                args.write_path = one_line(args.write_path, '--write-path')
                if any(SECRET_PART.search(part) for part in Path(args.write_path).parts):
                    raise WorkError('ownership check refuses a secret path')
                if args.text or (args.verb == 'ownership-alarm' and args.task):
                    raise WorkError('ownership-alarm takes --write-path, without a task id')
        elif args.write_path is not None:
            raise WorkError('--write-path belongs to ownership-alarm/check')
        if args.verb == "run-start" and not args.task:
            raise WorkError(RUN_TASK_REQUIRED)
        if args.verb not in {"create", "program-create", "theme-create", "stream-create", "function-create", "goal-create", "incident-open", "bug-open", "decision-add", "lesson-add", "path-move", "ownership-alarm"} and not args.task:
            raise WorkError("task, stream, or run id is required")
        if args.verb in {"claim", "comment", "flag", "unflag", "create", "program-create", "theme-create", "stream-create", "stream-update", "function-create", "function-update", "goal-create", "task-goal", "done", "accept", "bounce", "cancel", "block", "backlog", "todo", "run-start", "run-note", "run-move", "incident-open", "incident-close", "bug-open", "bug-update", "link", "link-task", "task-decision-link", "task-update", "task-rank", "task-move", "bug-close", "decision-add", "decision-update", "approval-add", "lesson-add", "lesson-update"} and not args.by:
            raise WorkError("--by is required: who is writing")
        if args.verb == "path-move":
            if args.task or args.text or (not args.plan and (not args.path_from or not args.path_to)) or (args.plan and (args.path_from or args.path_to)):
                raise WorkError("path-move needs --from <prefix> and --to <prefix>, without a task id")
            if not (args.dry_run or args.plan_out) and not args.by:
                raise WorkError("path-move needs --by when writing")
        elif args.path_from is not None or args.path_to is not None or args.dry_run or args.plan_out or args.plan:
            raise WorkError("--from, --to, and --dry-run belong to path-move")
        if args.by is not None:
            args.by = one_line(args.by, "--by")
            if not ACTOR_TOKEN.fullmatch(args.by) and args.by.casefold() not in LEGACY_ACTOR_NAMES:
                raise WorkError("--by actor name must be a plain token (letters, digits, dash, underscore) "
                                "or an existing historical name: " + args.by)
        if args.verb == "accept" and args.by.casefold() == "lead" and args.approval is None:
            assert_lead_seat(args.by, "sign it off")
        if args.verb == "task-decision-link":
            if args.text or not args.decision or not args.step:
                raise WorkError("task-decision-link needs --decision <id> and --step <number-or-number-letter>")
            args.decision = one_line(args.decision, "--decision")
            if not re.fullmatch(r"[1-9][0-9]*[a-z]?", args.step):
                raise WorkError("--step must be a positive number with an optional lowercase letter, for example 2b")
        elif args.decision is not None or args.step is not None:
            raise WorkError("--decision and --step belong to task-decision-link")
        if args.verb == "goal-create":
            if args.task or args.text or not args.title or not args.horizon:
                raise WorkError("goal-create needs --title and --horizon; use --id for an explicit id")
        elif args.horizon is not None or args.period is not None:
            raise WorkError("--horizon and --period belong to goal-create")
        if args.verb == "task-goal":
            if args.text or not args.goal:
                raise WorkError("task-goal needs --goal <id> and no text argument")
            args.goal = one_line(args.goal, "--goal")
        elif args.goal is not None:
            raise WorkError("--goal belongs to task-goal")
        if args.verb == "run-move":
            if args.text or not args.target_task:
                raise WorkError("run-move needs --task <task id> and no text argument")
        elif args.target_task is not None:
            raise WorkError("--task belongs to run-move")
        if args.verb == "create":
            if args.task or args.text:
                raise WorkError("create accepts no task id or text argument")
            if not args.title:
                raise WorkError("create needs --title (--project is optional; without it the task goes to the inbox)")
            if args.status is not None and args.status not in {"backlog", "todo", "done"}:
                raise WorkError("create --status must be backlog, todo, or done with --note")
            if args.status == "done" and not args.note:
                raise WorkError("create --status done needs --note")
            if args.ord is not None and args.ord < 0:
                raise WorkError("--ord must be an integer at least zero")
        if args.verb == "program-create" and not args.name:
            raise WorkError("program-create needs --name")
        if args.verb == "theme-create" and (not args.program or not args.name):
            raise WorkError("theme-create needs --program and --name")
        if args.verb == "stream-create":
            if not args.program or not args.theme or not args.function or not args.title:
                raise WorkError("stream-create needs --program, --theme, --function, and --title")
            if args.status is not None and args.status not in {"backlog", "todo"}:
                raise WorkError("stream-create --status must be backlog or todo")
        if args.verb == "stream-update":
            if args.text:
                raise WorkError("stream-update takes one positional stream id")
            if args.title is None and args.ord is None:
                raise WorkError("stream-update needs a field to change: --title or --ord")
            if args.ord is not None and args.ord < 1:
                raise WorkError("stream-update --ord must be an integer at least one")
            supplied = ["--" + field for field in ("order", "status", "program", "theme", "function", "result", "owner", "tags")
                        if getattr(args, field) is not None]
            if supplied or args.add_tag or args.remove_tag:
                raise WorkError("stream-update changes only --title and --ord (with --note as the reason); refused: "
                                + ", ".join(supplied + ["--add-tag"] * bool(args.add_tag) + ["--remove-tag"] * bool(args.remove_tag)))
        if args.verb == "task-rank":
            if args.ord is None or args.text:
                raise WorkError("task-rank needs --ord <integer> and no text argument")
            if any((args.title is not None, args.note is not None, args.append_note is not None,
                    bool(args.acceptance), args.tags is not None, bool(args.add_tag), bool(args.remove_tag),
                    args.owner is not None, args.check_by is not None, args.parent is not None,
                    bool(six_field_values(args)), bool(args.where))):
                raise WorkError("task-rank changes only --ord; use task-update for other fields")
        if args.verb in {"backlog", "todo"}:
            if args.text or args.status is not None:
                raise WorkError(args.verb + " takes no text or --status; use --note for a reason")
            args.note = optional_line(args.note, "--note")
        if (any(getattr(args, field) is not None for field, _, _ in SIX_FIELD_FLAGS) or args.where) \
                and args.verb not in {"create", "task-update", "task-rank", "bug-open", "bug-update"}:
            raise WorkError("--problem, --job-when, --job-want, --job-so, --body, --context, and --where belong to create, task-update, bug-open, or bug-update")
        if args.ord is not None:
            if args.verb not in {"create", "task-update", "task-rank", "stream-update"}:
                raise WorkError("--ord belongs to create, task-update, task-rank, or stream-update")
            if args.ord < 0:
                raise WorkError("--ord must be an integer at least zero")
        if args.verb in {"task-update", "task-rank"}:
            forbidden = ("status", "project", "program", "theme", "function")
            supplied = ["--" + field for field in forbidden if getattr(args, field) is not None]
            if supplied:
                hint = "; use task-move <task> --project <stream id>" if "--project" in supplied else ""
                raise WorkError("task-update refuses " + ", ".join(supplied) + hint)
            six_field_values(args)
            if args.parent is not None and any((args.title is not None, args.note is not None,
                                                args.append_note is not None, bool(args.acceptance),
                                                bool(six_field_values(args)), bool(args.where))):
                raise WorkError("placement and edits are separate calls")
            if not any((args.title is not None, args.note is not None, args.append_note is not None,
                        bool(args.acceptance), args.tags is not None, bool(args.add_tag), bool(args.remove_tag),
                        args.owner is not None, args.check_by is not None, args.parent is not None, args.ord is not None,
                        bool(six_field_values(args)), bool(args.where))):
                raise WorkError("task-update needs a field to change")
            if len(args.acceptance) > 1:
                raise WorkError("task-update accepts one --acceptance JSON list")
            if args.acceptance:
                acceptance_list(args.acceptance[0])
        elif args.approval is not None and args.verb not in {"task-move", "accept"}:
            raise WorkError("--approval belongs to accept, task-update or standing task-move")
        if args.verb == "link-task":
            if not args.blocks or args.text:
                raise WorkError("link-task needs one blocker and --blocks <task>")
        elif args.blocks is not None:
            raise WorkError("--blocks belongs to link-task")
        if args.remove and args.verb not in {"link", "link-task"}:
            raise WorkError("--remove belongs to link or link-task")
        if args.verb == "task-move":
            if bool(args.project is not None) == args.inbox:
                raise WorkError("task-move needs exactly one of --project <stream id> or --inbox")
            if args.text:
                raise WorkError("task-move accepts no text argument; use --note")
        elif args.inbox:
            raise WorkError("--inbox belongs to task-move")
        if args.verb in {"theme-create", "stream-create"} and args.order is not None and args.order < 1:
            raise WorkError("--order must be an integer at least one")
        if args.verb == "run-start" and (not args.model or not args.runtime):
            raise WorkError("run-start needs --model and --runtime")
        if args.verb == "run-start" and args.desktop_session and not re.fullmatch(r"local_[A-Za-z0-9_-]+", args.desktop_session):
            raise WorkError("--desktop-session must be a local_ id")
        if args.verb == "run-note" and not args.text:
            raise WorkError("run-note step required")
        if args.verb == "run-end":
            if args.proof and args.evidence:
                raise WorkError("run-end accepts --proof or its --evidence alias, not both")
            if len(args.proof) > 1:
                raise WorkError("run-end needs one --proof path")
            args.evidence = args.proof[0] if args.proof else args.evidence
            if not args.result or not args.evidence:
                raise WorkError("run-end needs --result and --proof <path> (--evidence alias)")
            if args.fix_rounds is not None and args.fix_rounds < 0:
                raise WorkError("--fix-rounds must be an integer at least zero")
            receipts.append(open_receipt(root, args.evidence))
        if args.verb == "comment" and not args.text:
            raise WorkError("comment text required")
        if args.verb in {"flag", "unflag", "bounce"}:
            if args.text is None or not args.text.strip():
                raise WorkError(args.verb + " reason is required and must not be blank")
            if args.verb == "bounce" and args.text.splitlines() != [args.text]:
                raise WorkError("bounce reason must be one non-empty line")
            args.text = one_line(args.text, "bounce reason") if args.verb == "bounce" else args.text.strip()
        if (args.field is not None or args.flag) and args.verb != "comment":
            raise WorkError("--field and --flag belong to comment")
        if args.field is not None and not FIELD_NAME.fullmatch(args.field):
            raise WorkError("--field must be one lowercase field name, for example acceptance")
        if args.verb == "block" and not args.text:
            raise WorkError("say what you are waiting on")
        if args.verb == "cancel":
            if not args.reason:
                raise WorkError("cancel needs --reason")
            one_line(args.reason, "--reason")
        elif (args.reason is not None and args.verb != 'ownership-clear') or args.folded_into is not None:
            raise WorkError("--reason and --folded-into belong to cancel")
        if args.verb == "done":
            # The old words flag is unambiguous only with --receipt and no --note.
            if args.receipt and args.note is None:
                if len(args.proof) != 1:
                    raise WorkError('done legacy --receipt needs one --proof "<one line>"')
                args.note = args.proof[0]
                args.proof = []
            paths = args.proof + args.receipt
            if not paths or not args.note or not args.note.strip() or "\n" in args.note or "\r" in args.note:
                raise WorkError('done needs --proof <path> and --note "<one line>"; legacy --receipt <path> and --proof "<one line>" is supported')
            for value in paths:
                receipts.append(open_receipt(root, value))
            if len({item.relative for item in receipts}) != len(receipts):
                raise WorkError("duplicate --proof or --receipt path")
        if args.verb == "incident-open" and (not args.record_id or not args.title):
            raise WorkError("incident-open needs --id and --title")
        if args.verb == "incident-close" and not args.rca_cause:
            raise WorkError("incident-close needs --rca-cause")
        if args.verb == "incident-close" and args.status not in {None, "restored", "closed"}:
            raise WorkError("incident-close --status must be restored or closed")
        if args.verb == "bug-open" and (not args.record_id or not args.title or not args.capability):
            raise WorkError("bug-open needs --id, --title, and --capability")
        if args.verb == "bug-open":
            six_field_refusal(args, "bug")
        if args.verb == "bug-update":
            if args.text:
                raise WorkError("bug-update takes no text argument")
            if not any((bool(six_field_values(args)), bool(args.where), bool(args.acceptance), args.tags is not None,
                        bool(args.add_tag), bool(args.remove_tag))):
                raise WorkError("bug-update needs a field to change: --tags --add-tag --remove-tag --problem --job-when "
                                "--job-want --job-so --body --acceptance (JSON list) --context --where")
            if len(args.acceptance) > 1:
                raise WorkError("bug-update accepts one --acceptance JSON list")
            if args.acceptance:
                acceptance_list(args.acceptance[0])
        if args.verb == "bug-close":
            if args.status not in (None, "fixed", "wont-fix"):
                raise WorkError("bug-close --status must be fixed or wont-fix")
            if args.status == "wont-fix" and not args.note:
                raise WorkError("bug-close --status wont-fix needs --note")
        if args.verb == "link" and (not args.subject_type or not args.target_type or not args.target_id or not args.relation):
            raise WorkError("link needs --subject-type, --target-type, --target-id, and --relation")
        if args.verb == "link" and args.subject_type not in {"incident", "bug"}:
            raise WorkError("link --subject-type must be incident or bug")
        if args.owner is not None and args.verb not in {"task-update", "goal-create"} and args.verb not in FUNCTION_VERBS:
            raise WorkError("--owner belongs to task-update, function-create, or function-update; goal-create also accepts --owner")
        if (args.organization is not None or args.page is not None) and args.verb not in FUNCTION_VERBS:
            raise WorkError("--organization and --page belong to function-create or function-update")
        if args.verb == "function-create":
            if args.task or args.text:
                raise WorkError("function-create takes --id, not a positional id")
            if not args.record_id or not args.name:
                raise WorkError("function-create needs --id and --name")
            if not SLUG.fullmatch(args.record_id):
                raise WorkError("--id must be a lowercase slug, for example communications")
            if args.add_tag or args.remove_tag:
                raise WorkError("function-create takes --tags; --add-tag and --remove-tag belong to function-update")
        if args.verb == "function-update":
            if args.text:
                raise WorkError("function-update takes one positional function id")
            if args.record_id is not None:
                raise WorkError("function-update refuses --id: a function id never changes; "
                                "tasks, work streams, goals, measures, and decisions point to it")
            if not any((args.name is not None, args.organization is not None, args.owner is not None,
                        args.parent is not None, args.page is not None, args.tags is not None,
                        bool(args.add_tag), bool(args.remove_tag))):
                raise WorkError("function-update needs a field to change: --name, --organization, --owner, "
                                "--parent, --page, --tags, --add-tag, or --remove-tag")
        promotion_flags = {
            "decision-add": ("decided_on",),
            "approval-add": ("call", "given_at", "version"),
        }
        for verb, fields in promotion_flags.items():
            if args.verb != verb:
                supplied = ["--" + field.replace("_", "-") for field in fields if getattr(args, field) is not None]
                if supplied:
                    raise WorkError(", ".join(supplied) + " belong to " + verb)
        if args.replaces is not None and args.verb not in {"decision-add", "decision-update"} | LESSON_VERBS:
            raise WorkError("--replaces belong to decision-add, decision-update, lesson-add, or lesson-update")
        if args.statement is not None and args.verb not in {"decision-add", "decision-update"}:
            raise WorkError("--statement belongs to decision-add or decision-update")
        if args.check_by is not None and args.verb not in {"create", "task-update"}:
            raise WorkError("--check-by belongs to create or task-update")
        if args.partial and args.verb not in {"decision-add", "decision-update"}:
            raise WorkError("--partial belongs to decision-add or decision-update")
        if args.person_words is not None and args.verb not in set(promotion_flags) | LESSON_VERBS:
            raise WorkError("--person-words belongs to decision-add, approval-add, lesson-add, or lesson-update")
        lesson_flags = [flag for flag, value in (("--rule", args.rule), ("--applies-to", args.applies_to),
                                                 ("--lesson-workspace", args.lesson_workspace)) if value is not None]
        if lesson_flags and args.verb not in LESSON_VERBS:
            raise WorkError(", ".join(lesson_flags) + " belong to lesson-add or lesson-update")
        if args.verb == "lesson-add":
            if args.task or args.text:
                raise WorkError("lesson-add takes no positional id; lesson-add prints the new id")
            if not args.rule or not args.source:
                raise WorkError("lesson-add needs --rule (the lesson in one line) and --source (where it came from)")
            if args.status is not None:
                raise WorkError("lesson-add writes an active lesson; --status belongs to lesson-update")
        if args.verb == "lesson-update":
            if args.text:
                raise WorkError("lesson-update takes one positional lesson id")
            if not any(value is not None for value in (args.rule, args.person_words, args.source, args.applies_to,
                                                       args.lesson_workspace, args.status, args.replaces)):
                raise WorkError("lesson-update needs a field to change: --rule, --person-words, --source, "
                                "--lesson-workspace, --applies-to, --status, or --replaces")
        if args.verb == "decision-add":
            if args.task or args.text:
                raise WorkError("decision-add takes --id, not a positional id")
            if not args.record_id or not args.name:
                raise WorkError("decision-add needs --id and --name")
            if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", args.record_id):
                raise WorkError("--id must be a lowercase slug, for example no-subtasks")
            if args.decided_on is not None:
                try:
                    datetime.strptime(args.decided_on, "%Y-%m-%d")
                except ValueError as error:
                    raise WorkError("--decided-on must be YYYY-MM-DD") from error
        if args.verb == "decision-update":
            if args.text or args.record_id:
                raise WorkError("decision-update takes one positional decision id")
            if not any((args.replaces is not None, args.status is not None, args.statement is not None)):
                raise WorkError("decision-update needs --replaces, --status, or --statement")
        if args.partial and args.replaces is None:
            raise WorkError("--partial needs --replaces")
        if args.verb == "approval-add":
            if args.text:
                raise WorkError("approval-add takes one subject id")
            if not args.call:
                raise WorkError("approval-add needs --call approve|discuss|wrong|edit")
            if args.given_at is not None:
                try:
                    datetime.fromisoformat(args.given_at)
                except ValueError as error:
                    raise WorkError("--given-at must be an ISO time, for example 2026-09-26T10:00:00-04:00") from error

        database = canonical(args.db)
        if args.verb == "create" and core_task_database(existing_path(database, "database")):
            print(create_core_task(database, args), file=output)
            return 0
        if args.verb == "create":
            six_field_refusal(args)
            six_fields = six_field_values(args)
            acceptance_items = [one_line(item, "--acceptance") for item in args.acceptance]
            where = where_paths(root, args.where)
        elif args.verb in {"task-update", "bug-open", "bug-update"}:
            six_fields = six_field_values(args)
            where = where_paths(root, args.where)
        db = connect_database(database, read_only=args.verb in {"show", "ownership-check"} or (args.verb == "path-move" and (args.dry_run or args.plan_out)))
        try:
            report_existing_fk_defects(db, errors)
            if args.verb.startswith('ownership-'):
                db.execute('BEGIN' if args.verb == 'ownership-check' else 'BEGIN IMMEDIATE')
                try:
                    record_id = ownership_write(db, args)
                    db.execute('COMMIT')
                except Exception:
                    db.execute('ROLLBACK')
                    raise
                if args.verb != 'ownership-check':
                    export_after_write(database, root, errors)
                print(('ALLOW: cleared alarm ' if args.verb == 'ownership-check' else 'ok ' + args.verb + ' ') + record_id, file=output)
                return 0
            if args.verb == "path-move":
                path_move_write(db, args, root, output)
                if not (args.dry_run or args.plan_out):
                    export_after_write(database, root, errors)
                return 0
            if args.verb == "goal-create":
                db.execute("BEGIN IMMEDIATE")
                try:
                    record_id = goal_create_write(db, args)
                    db.execute("COMMIT")
                except Exception:
                    db.execute("ROLLBACK")
                    raise
                export_after_write(database, root, errors)
                print(f"ok goal-create {record_id}", file=output)
                return 0
            if args.verb == "task-decision-link":
                db.execute("BEGIN IMMEDIATE")
                try:
                    duplicate = task_decision_link_write(db, args)
                    db.execute("COMMIT")
                except Exception:
                    db.execute("ROLLBACK")
                    raise
                export_after_write(database, root, errors)
                print(f"ok task-decision-link {args.task}" + (" duplicate" if duplicate else ""), file=output)
                return 0
            if args.verb == "show":
                task = task_row(db, args.task)
                fields = ("id", "title", "note", "status", "owner", "claimed_by", "project", "acceptance")
                print(json.dumps({key: task[key] for key in fields}, ensure_ascii=False, indent=2), file=output)
                for row in db.execute(
                    "SELECT relation,path,external_id FROM task_links WHERE task=? AND active=1 ORDER BY id",
                    (args.task,),
                ):
                    print(" link:", dict(row), file=output)
                blockers = {task["blocked_by"]} if task["blocked_by"] else set()
                blockers.update(row[0] for row in db.execute(
                    "SELECT task FROM task_links WHERE system='task' AND relation='blocks' "
                    "AND external_id=? AND active=1", (args.task,),
                ))
                if blockers:
                    print(" blocked by:", ", ".join(sorted(blockers)), file=output)
                return 0

            if args.verb == "link-task":
                actor = args.by
                blocker_id = one_line(args.task, "blocker")
                blocked_id = one_line(args.blocks, "--blocks")
                if blocker_id == blocked_id:
                    raise WorkError("a task cannot block itself")
                db.execute("BEGIN IMMEDIATE")
                try:
                    task_row(db, blocker_id)
                    task_row(db, blocked_id)
                    existing = db.execute(
                        "SELECT id,relation,active FROM task_links WHERE task=? AND system='task' AND external_id=?",
                        (blocker_id, blocked_id),
                    ).fetchone()
                    if existing and existing["relation"] != "blocks":
                        raise WorkError("task link identity is already used by another relation")
                    duplicate = (existing is None if args.remove else existing is not None and existing["active"] == 1)
                    if not duplicate:
                        if not args.remove:
                            cycle = blocker_cycle(db, blocker_id, blocked_id)
                            if cycle:
                                raise WorkError("blocker cycle: " + " -> ".join(cycle))
                        timestamp = now()
                        if args.remove:
                            db.execute("DELETE FROM task_links WHERE id=?", (existing["id"],))
                            activity(db, blocked_id, 'blocks', blocker_id, None, actor, timestamp, 'removed blocker link ' + blocker_id, verb=action_word('blocks', None, subject_type='task'))
                        elif existing:
                            db.execute("UPDATE task_links SET active=1 WHERE id=?", (existing["id"],))
                            activity(db, blocked_id, 'blocks', None, blocker_id, actor, timestamp, 'added blocker link ' + blocker_id, verb=action_word('blocks', blocker_id, subject_type='task'))
                        else:
                            db.execute(
                                "INSERT INTO task_links (task,system,scope,external_id,path,relation,active,created_on) "
                                "VALUES (?,'task',NULL,?,NULL,'blocks',1,?)",
                                (blocker_id, blocked_id, timestamp),
                            )
                            activity(db, blocked_id, 'blocks', None, blocker_id, actor, timestamp, 'added blocker link ' + blocker_id, verb=action_word('blocks', blocker_id, subject_type='task'))
                    db.execute("COMMIT")
                except Exception:
                    db.execute("ROLLBACK")
                    raise
                export_after_write(database, root, errors)
                print(f"ok link-task {blocker_id} --blocks {blocked_id}"
                      + (" --remove" if args.remove else "")
                      + (" duplicate" if duplicate else ""), file=output)
                return 0

            if args.verb in {"incident-open", "incident-close", "bug-open", "bug-update", "bug-close", "link"}:
                require_incident_tables(db)
                if args.verb in {"bug-open", "bug-update"} and not has_bug_fields(db):
                    raise WorkError("this tracker's bugs table has no six-field columns; apply work/apply_program_schema.py first")
                db.execute("BEGIN IMMEDIATE")
                try:
                    timestamp = now()
                    actor = args.by
                    duplicate = False
                    if args.verb == "incident-open":
                        record_id = one_line(args.record_id, "--id")
                        title = one_line(args.title, "--title")
                        if args.bug and not db.execute("SELECT 1 FROM bugs WHERE id=?", (args.bug,)).fetchone():
                            raise WorkError("no such bug: " + args.bug)
                        if db.execute("SELECT 1 FROM incidents WHERE id=?", (record_id,)).fetchone():
                            raise WorkError("incident already exists: " + record_id)
                        db.execute(
                            "INSERT INTO incidents (id,title,started_at,impact,status,bug,created_on,source) VALUES (?,?,?,?,'open',?,?,?)",
                            (record_id, title, args.started_at or timestamp, args.impact, args.bug, timestamp[:10], args.source or SOURCE),
                        )
                        if args.bug:
                            db.execute(
                                "INSERT INTO record_links (subject_type,subject_id,target_type,target_id,relation) VALUES ('incident',?,'bug',?,'caused-by')",
                                (record_id, args.bug),
                            )
                        record_activity(db, 'incident', record_id, 'create', None, title, actor, timestamp, verb=action_word('create', title, subject_type='incident'))
                    elif args.verb == "incident-close":
                        record_id = one_line(args.task, "incident id")
                        row = db.execute("SELECT status,rca_cause,ended_at,restored_by FROM incidents WHERE id=?", (record_id,)).fetchone()
                        if row is None:
                            raise WorkError("no such incident: " + record_id)
                        status = "restored" if args.status == "restored" else "closed"
                        cause = one_line(args.rca_cause, "--rca-cause")
                        ended_at = args.ended_at or row["ended_at"] or timestamp
                        duplicate = (
                            row["status"] == status and row["rca_cause"] == cause
                            and row["ended_at"] == ended_at and row["restored_by"] == args.restored_by
                        )
                        if not duplicate:
                            db.execute(
                                "UPDATE incidents SET ended_at=?,restored_by=?,status=?,rca_cause=? WHERE id=?",
                                (ended_at, args.restored_by, status, cause, record_id),
                            )
                            record_activity(db, 'incident', record_id, 'status', row['status'], status, actor, timestamp, cause, verb=action_word('status', status, subject_type='incident'))
                    elif args.verb == "bug-open":
                        record_id = one_line(args.record_id, "--id")
                        title = one_line(args.title, "--title")
                        if db.execute("SELECT 1 FROM bugs WHERE id=?", (record_id,)).fetchone():
                            raise WorkError("bug already exists: " + record_id)
                        db.execute(
                            "INSERT INTO bugs (id,title,description,capability,status,reports,created_on) VALUES (?,?,?,?,'open',1,?)",
                            (record_id, title, args.description, one_line(args.capability, "--capability"), timestamp[:10]),
                        )
                        acceptance = json.dumps([one_line(item, "--acceptance") for item in args.acceptance], ensure_ascii=False, separators=(",", ":"))
                        db.execute(
                            "UPDATE bugs SET tags=?,problem=?,job_when=?,job_want=?,job_so=?,body=?,context=?,acceptance=? WHERE id=?",
                            (",".join(normalized_tags(args.tags)) or None,
                             *(six_fields[field] for field, _, _ in SIX_FIELD_FLAGS), acceptance, record_id),
                        )
                        bug_where_write(db, record_id, where, actor, timestamp)
                        record_activity(db, 'bug', record_id, 'create', None, title, actor, timestamp, verb=action_word('create', title, subject_type='bug'))
                    elif args.verb == "bug-update":
                        record_id = one_line(args.task, "bug id")
                        bug = db.execute("SELECT * FROM bugs WHERE id=?", (record_id,)).fetchone()
                        if bug is None:
                            raise WorkError("no such bug: " + record_id)
                        changes = dict(six_fields)
                        if args.acceptance:
                            changes["acceptance"] = acceptance_list(args.acceptance[0])
                        if args.tags is not None or args.add_tag or args.remove_tag:
                            tags = normalized_tags(args.tags if args.tags is not None else bug["tags"])
                            for value in args.add_tag:
                                tag = single_tag(value, "--add-tag")
                                if tag not in tags:
                                    tags.append(tag)
                            for value in args.remove_tag:
                                tag = single_tag(value, "--remove-tag")
                                tags = [item for item in tags if item != tag]
                            changes["tags"] = ",".join(tags) or None
                        changed = {field: value for field, value in changes.items() if value != bug[field]}
                        for field, value in changed.items():
                            db.execute(f'UPDATE bugs SET "{field}"=? WHERE id=?', (value, record_id))
                            record_activity(db, 'bug', record_id, field, bug[field], value, actor, timestamp,
                                            f'FROM {json.dumps(bug[field], ensure_ascii=False)} TO {json.dumps(value, ensure_ascii=False)}',
                                            verb=action_word(field, value, command='task-update'))
                        linked = bug_where_write(db, record_id, where, actor, timestamp)
                        for path in linked:
                            record_activity(db, 'bug', record_id, 'where', None, path, actor, timestamp, verb=action_word('where', path, command='task-update'))
                        duplicate = not changed and not linked
                    elif args.verb == "bug-close":
                        record_id = one_line(args.task, "bug id")
                        bug = db.execute("SELECT status FROM bugs WHERE id=?", (record_id,)).fetchone()
                        if bug is None:
                            raise WorkError("no such bug: " + record_id)
                        if bug["status"] != "open":
                            raise WorkError("bug is already closed: " + record_id)
                        status = args.status or "fixed"
                        fix_tasks = [row[0] for row in db.execute(
                            "SELECT target_id FROM record_links WHERE subject_type='bug' AND subject_id=? "
                            "AND target_type='task' AND relation='fix' ORDER BY target_id", (record_id,)
                        )]
                        if status == "fixed" and not fix_tasks:
                            raise WorkError("fixed bug needs a fix link to a task")
                        reason = one_line(args.note, "--note") if args.note is not None else "fix task: " + ", ".join(fix_tasks)
                        db.execute("UPDATE bugs SET status=? WHERE id=?", (status, record_id))
                        db.execute(
                            "INSERT INTO comments (subject_type,subject_id,author,at,body) VALUES ('bug',?,?,?,?)",
                            (record_id, actor, timestamp, "Closed " + status + ": " + reason),
                        )
                        record_activity(db, 'bug', record_id, 'status', bug['status'], status, actor, timestamp, reason, verb=action_word('status', status, subject_type='bug'))
                    else:
                        subject_id = one_line(args.task, "subject id")
                        subject_table = "incidents" if args.subject_type == "incident" else "bugs"
                        target_tables = {
                            "task": "tasks", "project": "projects", "function": "functions", "theme": "themes",
                            "run": "runs", "decision": "decisions", "incident": "incidents", "bug": "bugs",
                        }
                        if not db.execute(f'SELECT 1 FROM "{subject_table}" WHERE id=?', (subject_id,)).fetchone():
                            raise WorkError("no such " + args.subject_type + ": " + subject_id)
                        target_table = target_tables[args.target_type]
                        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (target_table,)).fetchone():
                            raise WorkError("target table is not installed: " + target_table)
                        if not db.execute(f'SELECT 1 FROM "{target_table}" WHERE id=?', (args.target_id,)).fetchone():
                            raise WorkError("no such " + args.target_type + ": " + args.target_id)
                        if args.relation == "fix" and args.target_type != "task":
                            raise WorkError("a fix link must target a task")
                        values = (args.subject_type, subject_id, args.target_type, args.target_id, args.relation)
                        duplicate = bool(db.execute(
                            "SELECT 1 FROM record_links WHERE subject_type=? AND subject_id=? AND target_type=? AND target_id=? AND relation=?",
                            values,
                        ).fetchone())
                        if args.remove:
                            if not duplicate:
                                raise WorkError("no matching record link")
                            db.execute(
                                "DELETE FROM record_links WHERE subject_type=? AND subject_id=? AND target_type=? AND target_id=? AND relation=?",
                                values,
                            )
                            record_activity(db, args.subject_type, subject_id, 'link', args.target_type + ':' + args.target_id, None, actor, timestamp, args.relation, verb=action_word('link', None, subject_type=args.subject_type))
                            duplicate = False
                        elif not duplicate:
                            db.execute(
                                "INSERT INTO record_links (subject_type,subject_id,target_type,target_id,relation) VALUES (?,?,?,?,?)", values
                            )
                            record_activity(db, args.subject_type, subject_id, 'link', None, args.target_type + ':' + args.target_id, actor, timestamp, args.relation, verb=action_word('link', args.target_type + ':' + args.target_id, subject_type=args.subject_type))
                    db.execute("COMMIT")
                except Exception:
                    db.execute("ROLLBACK")
                    raise
                export_after_write(database, root, errors)
                label = args.record_id if args.verb in {"incident-open", "bug-open"} else args.task
                print(f"ok {args.verb} {label}" + (" --remove" if args.remove else "")
                      + (" duplicate" if duplicate else ""), file=output)
                return 0

            if args.verb in {"decision-add", "decision-update", "approval-add"}:
                db.execute("BEGIN IMMEDIATE")
                try:
                    if args.verb == "decision-add":
                        ensure_replaces_text(db)
                        label = decision_add_write(db, args)
                    elif args.verb == "decision-update":
                        ensure_replaces_text(db)
                        label = decision_update_write(db, args)
                    else:
                        label = approval_add_write(db, args)
                    db.execute("COMMIT")
                except Exception:
                    db.execute("ROLLBACK")
                    raise
                export_after_write(database, root, errors)
                print(f"ok {args.verb} {label}", file=output)
                return 0

            if args.verb in LESSON_VERBS:
                require_lessons(db)
                db.execute("BEGIN IMMEDIATE")
                try:
                    if args.verb == "lesson-add":
                        label, duplicate = lesson_add_write(db, args)
                    else:
                        label, duplicate = lesson_update_write(db, args)
                    db.execute("COMMIT")
                except Exception:
                    db.execute("ROLLBACK")
                    raise
                export_after_write(database, root, errors)
                print(f"ok {args.verb} {label}" + (" duplicate" if duplicate else ""), file=output)
                return 0

            if args.verb in FUNCTION_VERBS:
                db.execute("BEGIN IMMEDIATE")
                try:
                    duplicate = False
                    if args.verb == "function-create":
                        label = function_create_write(db, args)
                    else:
                        label, duplicate = function_update_write(db, args)
                    db.execute("COMMIT")
                except Exception:
                    db.execute("ROLLBACK")
                    raise
                export_after_write(database, root, errors)
                print(f"ok {args.verb} {label}" + (" duplicate" if duplicate else ""), file=output)
                return 0

            if args.verb == "stream-update":
                require_program_control(db)
                db.execute("BEGIN IMMEDIATE")
                try:
                    label, duplicate = stream_update_write(db, args)
                    db.execute("COMMIT")
                except Exception:
                    db.execute("ROLLBACK")
                    raise
                if not duplicate:
                    export_after_write(database, root, errors)
                print(f"ok stream-update {label}" + (" duplicate" if duplicate else ""), file=output)
                return 0

            if args.verb in {"program-create", "theme-create", "stream-create"}:
                require_program_control(db)
                db.execute("BEGIN IMMEDIATE")
                try:
                    timestamp = now()
                    actor = args.by
                    if args.verb == "program-create":
                        record_id = next_identifier(db, "programs", "PG")
                        name = one_line(args.name, "--name")
                        objective = one_line(args.objective, "--objective") if args.objective else None
                        db.execute(
                            "INSERT INTO programs (id,name,objective,created_on) VALUES (?,?,?,?)",
                            (record_id, name, objective, timestamp[:10]),
                        )
                        record_activity(db, 'program', record_id, 'create', None, name, actor, timestamp, verb=action_word('create', name, subject_type='program'))
                    elif args.verb == "theme-create":
                        program = one_line(args.program, "--program")
                        if not db.execute("SELECT 1 FROM programs WHERE id=?", (program,)).fetchone():
                            raise WorkError("no such program: " + program)
                        record_id = next_identifier(db, "themes", "TH")
                        order = args.order or db.execute(
                            "SELECT coalesce(max(ord),0)+1 FROM themes WHERE program=?", (program,)
                        ).fetchone()[0]
                        name = one_line(args.name, "--name")
                        tagline = one_line(args.tagline, "--tagline") if args.tagline else None
                        db.execute(
                            "INSERT INTO themes (id,program,name,tagline,ord) VALUES (?,?,?,?,?)",
                            (record_id, program, name, tagline, order),
                        )
                        record_activity(db, 'theme', record_id, 'create', None, name, actor, timestamp, f'program={program}; order={order}', verb=action_word('create', name, subject_type='theme'))
                    else:
                        program = one_line(args.program, "--program")
                        theme = one_line(args.theme, "--theme")
                        function = one_line(args.function, "--function")
                        linked_theme = db.execute("SELECT program FROM themes WHERE id=?", (theme,)).fetchone()
                        if linked_theme is None:
                            raise WorkError("no such theme: " + theme)
                        if linked_theme["program"] != program:
                            raise WorkError(f"theme {theme} does not belong to program {program}")
                        if not db.execute("SELECT 1 FROM functions WHERE id=?", (function,)).fetchone():
                            raise WorkError("no such function: " + function)
                        record_id = next_identifier(db, "projects", "WS", 2)
                        order = args.order or db.execute(
                            "SELECT coalesce(max(ord),0)+1 FROM projects WHERE program=? AND theme=?",
                            (program, theme),
                        ).fetchone()[0]
                        title = one_line(args.title, "--title")
                        result = one_line(args.result, "--result") if args.result else None
                        db.execute(
                            "INSERT INTO projects "
                            "(id,title,result,status,function,created_on,ord,program,theme,needs,order_column,span,alongside) "
                            "VALUES (?,?,?,?,?,?,?, ?,?,'[]',?,1,0)",
                            (record_id, title, result, args.status or "todo", function, timestamp, order, program, theme, order),
                        )
                        record_activity(db, 'project', record_id, 'create', None, title, actor, timestamp, f'program={program}; theme={theme}; function={function}; order={order}', verb=action_word('create', title, subject_type='project'))
                    db.execute("COMMIT")
                except Exception:
                    db.execute("ROLLBACK")
                    raise
                export_after_write(database, root, errors)
                print(record_id, file=output)
                return 0

            if args.verb == "create":
                db.execute("BEGIN IMMEDIATE")
                try:
                    parent = task_row(db, args.parent) if args.parent else None
                    if parent and parent["parent"] is not None:
                        raise WorkError("a checklist line cannot have a child")
                    if args.project is not None:
                        args.project = task_project(db, args.project)
                    elif parent:
                        args.project = parent["project"]
                    numbers = [int(match.group(1)) for row in db.execute("SELECT id FROM tasks") if (match := re.fullmatch(r"T(\d+)", row[0]))]
                    task_id = "T" + str((max(numbers) if numbers else 0) + 1)
                    order = args.ord
                    if order is None:
                        order = db.execute("SELECT coalesce(max(ord),0)+1 FROM tasks WHERE project IS ?", (args.project,)).fetchone()[0]
                    title = one_line(args.title, "--title")
                    actor = args.by
                    acceptance = json.dumps(acceptance_items, ensure_ascii=False, separators=(",", ":"))
                    timestamp = now()
                    if not has_six_fields(db):
                        raise WorkError("this tracker has no problem and job story columns; apply work/apply_program_schema.py first")
                    values = normalized_tags(args.tags)
                    if args.workspace:
                        values = [tag for tag in values if not tag.startswith('workspace:')]
                        values.append('workspace:' + args.workspace)
                    tags = ','.join(values) or None
                    if has_t309(db):
                        db.execute(
                            "INSERT INTO tasks (id,title,status,project,created_by,created_on,source,note,acceptance,ord,tags,parent,check_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (task_id, title, args.status or "todo", args.project, actor, timestamp, SOURCE, args.note, acceptance, order, tags, args.parent, args.check_by or "lead"),
                        )
                    else:
                        if args.parent or args.check_by:
                            raise WorkError("source-note schema is required for --parent and --check-by")
                        db.execute(
                            "INSERT INTO tasks (id,title,status,project,created_by,created_on,source,note,acceptance,ord,tags) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (task_id, title, args.status or "todo", args.project, actor, timestamp, SOURCE, args.note, acceptance, order, tags),
                        )
                    db.execute(
                        "UPDATE tasks SET problem=?,job_when=?,job_want=?,job_so=?,body=?,context=? WHERE id=?",
                        (*(six_fields[field] for field, _, _ in SIX_FIELD_FLAGS), task_id),
                    )
                    where_write(db, task_id, where, timestamp)
                    activity(db, task_id, 'create', None, title, actor, timestamp, 'project=' + (args.project or 'inbox'), verb=action_word('create', title, subject_type='task'))
                    db.execute("COMMIT")
                except Exception:
                    db.execute("ROLLBACK")
                    raise
                export_after_write(database, root, errors)
                print(task_id, file=output)
                return 0

            if args.verb == "run-note":
                db.execute("BEGIN IMMEDIATE")
                try:
                    run_id = one_line(args.task, "run id")
                    record = db.execute("SELECT ended_at FROM runs WHERE id=?", (run_id,)).fetchone()
                    if record is None:
                        raise WorkError("no such run: " + run_id)
                    if record["ended_at"] is not None:
                        raise WorkError("run is already ended: " + run_id)
                    db.execute(
                        "INSERT INTO comments (subject_type,subject_id,author,at,body) VALUES ('run',?,?,?,?)",
                        (run_id, args.by, now(), one_line(args.text, "step")),
                    )
                    db.execute("COMMIT")
                except Exception:
                    db.execute("ROLLBACK")
                    raise
                export_after_write(database, root, errors)
                print(f"ok run-note {run_id}", file=output)
                return 0

            if args.verb == "run-move":
                db.execute("BEGIN IMMEDIATE")
                try:
                    run_id = one_line(args.task, "run id")
                    target_id = one_line(args.target_task, "--task")
                    actor = args.by
                    record = db.execute("SELECT subject_type,subject_id FROM runs WHERE id=?", (run_id,)).fetchone()
                    if record is None:
                        raise WorkError("no such run: " + run_id)
                    target = db.execute("SELECT status FROM tasks WHERE id=?", (target_id,)).fetchone()
                    if target is None:
                        raise WorkError(run_start_refusal(db, target_id))
                    if target["status"] in {"done", "canceled", "superseded"}:
                        raise WorkError(f"cannot move run to {target['status']} task: {target_id}")
                    old_subject = record["subject_type"] + ":" + record["subject_id"]
                    new_subject = "task:" + target_id
                    duplicate = old_subject == new_subject
                    if not duplicate:
                        db.execute("UPDATE runs SET subject_type='task',subject_id=? WHERE id=?", (target_id, run_id))
                        columns = {row[1] for row in db.execute('PRAGMA table_info("activity")')}
                        if "verb" in columns:
                            db.execute(
                                "INSERT INTO activity (subject_type,subject_id,field,old_value,new_value,actor,source,at,verb) "
                                "VALUES ('run',?,'subject',?,?,?,?,?,'moved')",
                                (run_id, old_subject, new_subject, actor, SOURCE, now()),
                            )
                        else:
                            record_activity(db, 'run', run_id, 'subject', old_subject, new_subject, actor, now(), verb=action_word('subject', new_subject, command='run-move'))
                    db.execute("COMMIT")
                except Exception:
                    db.execute("ROLLBACK")
                    raise
                export_after_write(database, root, errors)
                print(f"ok run-move {run_id}" + (" duplicate" if duplicate else ""), file=output)
                return 0

            if args.verb == "run-end":
                db.execute("BEGIN IMMEDIATE")
                try:
                    duplicate = False
                    record = db.execute('SELECT * FROM runs WHERE id=?', (args.task,)).fetchone()
                    if record is None:
                        raise WorkError("no such run: " + args.task)
                    result = one_line(args.result, "--result")
                    rounds = args.fix_rounds or 0
                    if record["ended_at"]:
                        duplicate = (
                            record["result"] == result and record["fix_rounds"] == rounds
                            and record["evidence"] is not None
                            and canonical(root / record["evidence"]) == receipts[0].path
                        )
                        if not duplicate:
                            raise WorkError("run is already ended: " + args.task)
                    else:
                        ended = now()
                        verify_receipt(receipts[0], root)
                        db.execute(
                            "UPDATE runs SET ended_at=?,result=?,fix_rounds=?,evidence=? WHERE id=?",
                            (ended, result, rounds, receipts[0].relative, record["id"]),
                        )
                    db.execute("COMMIT")
                except Exception:
                    db.execute("ROLLBACK")
                    raise
                export_after_write(database, root, errors)
                suffix = " duplicate" if duplicate else ""
                print(f"ok run-end {args.task}{suffix}", file=output)
                return 0

            db.execute("BEGIN IMMEDIATE")
            try:
                if args.verb in {"flag", "unflag"} and not db.execute(
                    "SELECT 1 FROM tasks WHERE id=?", (args.task,)
                ).fetchone() and (
                    args.task.startswith("B-") or (
                        db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='bugs'").fetchone()
                        and db.execute("SELECT 1 FROM bugs WHERE id=?", (args.task,)).fetchone()
                    )
                ):
                    raise WorkError("flags are for tasks; bugs have no flag yet")
                task = task_row(db, args.task) if args.verb != "run-start" else None
                if task is not None and ownership_task(task) and args.verb != 'comment':
                    raise WorkError('ownership alarms change through ownership-clear with --reason and --by')
                timestamp = now()
                duplicate = False
                standing_id = session_holding_task(db, required=False)
                standing = task is not None and task["id"] == standing_id
                if standing and args.verb in {"done", "accept", "cancel"}:
                    raise WorkError("the session holding task is a standing task and cannot close")
                if standing and args.verb == "task-move" and args.inbox:
                    raise WorkError("the session holding task is a standing task; it must stay in a stream and cannot enter the inbox")
                if args.verb in {"task-update", "task-rank"}:
                    changes = {}
                    protected = was_subtask(db, task) and any((
                        args.title is not None, args.note is not None, args.append_note is not None,
                        bool(args.acceptance),
                        # Filling an empty six-field column is not a rewrite; changing a written one is.
                        any(task[field] not in (None, "") and task[field] != value
                            for field, value in six_field_values(args).items()),
                        args.parent is not None and
                        (None if args.parent == "none" else args.parent) != task["parent"],
                    ))
                    approval = approved_rewrite(db, args.approval, task) if args.approval is not None else None
                    if protected and approval is None:
                        approved_rewrite(db, None, task)
                    if args.parent is not None:
                        if not has_t309(db):
                            raise WorkError("source-note schema is required for --parent")
                        parent_id = one_line(args.parent, "--parent")
                        if parent_id == "none":
                            changes["parent"] = None
                        else:
                            if parent_id == args.task:
                                raise WorkError("a task cannot be its own parent")
                            parent = task_row(db, parent_id)
                            task_stream = task["project"] or "inbox"
                            parent_stream = parent["project"] or "inbox"
                            if parent["status"] == "canceled":
                                raise WorkError(f"parent {parent_id} is canceled; task stream {task_stream}; parent stream {parent_stream}")
                            if task["project"] != parent["project"]:
                                raise WorkError(f"parent stream differs: task stream {task_stream}; parent stream {parent_stream}")
                            if parent["parent"] is not None:
                                raise WorkError("a checklist line cannot have a child")
                            if db.execute("SELECT 1 FROM tasks WHERE parent=? LIMIT 1", (args.task,)).fetchone():
                                raise WorkError("a task with children cannot have a parent")
                            changes["parent"] = parent_id
                    if args.title is not None:
                        changes["title"] = one_line(args.title, "--title")
                    if args.ord is not None:
                        changes["ord"] = args.ord
                    if args.note is not None or args.append_note is not None:
                        note = args.note if args.note is not None else task["note"]
                        if args.append_note is not None:
                            addition = one_line(args.append_note, "--append-note")
                            note = (note or "") + ("\n" if note else "") + addition
                        changes["note"] = note
                    if args.acceptance:
                        changes["acceptance"] = acceptance_list(args.acceptance[0])
                    if args.verb == "task-update" and (six_fields or where):
                        if six_fields and not has_six_fields(db):
                            raise WorkError("this tracker has no problem and job story columns; apply work/apply_program_schema.py first")
                        changes.update(six_fields)
                    if args.owner is not None:
                        changes["owner"] = one_line(args.owner, "--owner")
                    if args.check_by is not None:
                        if not has_t309(db):
                            raise WorkError("source-note schema is required for --check-by")
                        changes["check_by"] = args.check_by
                    if args.tags is not None or args.add_tag or args.remove_tag:
                        tags = normalized_tags(args.tags if args.tags is not None else task["tags"])
                        for value in args.add_tag:
                            tag = single_tag(value, "--add-tag")
                            if tag not in tags:
                                tags.append(tag)
                        for value in args.remove_tag:
                            tag = single_tag(value, "--remove-tag")
                            tags = [item for item in tags if item != tag]
                        changes["tags"] = ",".join(tags) or None
                        if standing and "recurring" not in tags:
                            raise WorkError("the session holding task is a standing task and must keep the recurring tag")
                    changed = {field: value for field, value in changes.items() if value != task[field]}
                    linked = where_write(db, args.task, where, timestamp) if args.verb == "task-update" else []
                    for path in linked:
                        insert_comment(db, args.task, args.by, timestamp, "Linked where: " + path)
                        activity(db, args.task, 'where', None, path, args.by, timestamp, verb=action_word('where', path, command='task-update'))
                    duplicate = not changed and not linked
                    for field, value in changed.items():
                        db.execute(f'UPDATE tasks SET "{field}"=? WHERE id=?', (value, args.task))
                        insert_comment(
                            db, args.task, args.by, timestamp,
                            f"Changed {field}: {json.dumps(task[field], ensure_ascii=False)} -> "
                            f"{json.dumps(value, ensure_ascii=False)}",
                        )
                        activity(db, args.task, field, task[field], value, args.by, timestamp, note=f'approval {approval}; FROM {json.dumps(task[field], ensure_ascii=False)} TO {json.dumps(value, ensure_ascii=False)}' if approval else None, verb=action_word(field, value, command='task-update'))
                elif args.verb == "task-goal":
                    if not db.execute("SELECT 1 FROM goals WHERE id=?", (args.goal,)).fetchone():
                        raise WorkError("no such goal: " + args.goal)
                    duplicate = task["goal"] == args.goal
                    if not duplicate:
                        db.execute("UPDATE tasks SET goal=? WHERE id=?", (args.goal, args.task))
                        insert_comment(db, args.task, args.by, timestamp,
                                       f"Changed goal: {json.dumps(task['goal'])} -> {json.dumps(args.goal)}")
                        activity(db, args.task, 'goal', task['goal'], args.goal, args.by, timestamp, verb=action_word('goal', args.goal))
                elif args.verb in {"backlog", "todo"}:
                    assert_not_final(task, "plan")
                    target = args.verb
                    duplicate = task["status"] == target
                    if not duplicate:
                        db.execute("UPDATE tasks SET status=?,claimed_by=NULL,claimed_at=NULL WHERE id=?", (target, args.task))
                        insert_comment(db, args.task, args.by, timestamp,
                                       f"Changed status: {json.dumps(task['status'])} -> {json.dumps(target)}"
                                       + (" | " + args.note if args.note else ""))
                        activity(db, args.task, 'status', task['status'], target, args.by, timestamp, args.note, verb=action_word('status', target))
                        for field in ("claimed_by", "claimed_at"):
                            if task[field] is not None:
                                activity(db, args.task, field, task[field], None, args.by, timestamp, args.note, verb='updated' if field == 'claimed_at' else action_word(field, None))
                elif args.verb == "task-move":
                    if args.approval is not None and not standing:
                        raise WorkError("--approval on task-move is only for a standing task")
                    approval = approved_rewrite(db, args.approval, task, standing_move=True) if standing else None
                    target = task_project(db, args.project, for_move=True) if args.project is not None else None
                    if task["project"] == target:
                        raise WorkError("task is already in " + (target or "inbox") + ": " + args.task)
                    actor = args.by
                    note = "moved" + (": " + one_line(args.note, "--note") if args.note is not None else "")
                    if approval:
                        note = (f"approval {approval}; FROM {json.dumps(task['project'], ensure_ascii=False)} "
                                f"TO {json.dumps(target, ensure_ascii=False)}; " + note)
                    db.execute("UPDATE tasks SET project=? WHERE id=?", (target, args.task))
                    record_activity(db, 'task', args.task, 'project', task['project'], target, actor, timestamp, note, verb=action_word('project', target, subject_type='task'))
                elif args.verb == "claim":
                    assert_not_final(task, "claim")
                    if not args.takeover:
                        assert_controller(task, args.by)
                    takeover = None
                    prior_controller = task["claimed_by"] or (
                        task["owner"] if task["status"] == "in-progress" else None
                    )
                    if args.takeover and prior_controller and prior_controller != args.by:
                        takeover = one_line(args.takeover, "--takeover")
                    elif args.takeover:
                        raise WorkError("--takeover requires a different current controller")
                    clean_tags = tag_state(task["tags"], "business-input", False)
                    duplicate = (
                        task["status"] == "in-progress" and task["owner"] == args.by
                        and task["claimed_by"] == args.by and clean_tags == task["tags"]
                    )
                    if not duplicate:
                        db.execute(
                            "UPDATE tasks SET status='in-progress',owner=?,claimed_by=?,claimed_at=?,tags=? WHERE id=?",
                            (args.by, args.by, timestamp, clean_tags, args.task),
                        )
                        if task["status"] != "in-progress":
                            activity(db, args.task, 'status', task['status'], 'in-progress', args.by, timestamp, 'claimed', verb=action_word('status', 'in-progress', command='claim', subject_type='task'))
                        if takeover:
                            if task["owner"] and task["owner"] != args.by:
                                activity(db, args.task, 'owner', task['owner'], args.by, args.by, timestamp, 'takeover: ' + takeover, verb=action_word('owner', args.by))
                            activity(db, args.task, 'claimed_by', prior_controller, args.by, args.by, timestamp, 'takeover: ' + takeover, verb=action_word('claimed_by', args.by))
                elif args.verb == "comment":
                    body = (FLAG_PREFIX + args.text) if args.flag and not re.match(r"^\s*flag\s*:", args.text, re.IGNORECASE) else args.text
                    comment_id = insert_comment(db, args.task, args.by, timestamp, body, args.field)
                    activity(db, args.task, 'comment', None, str(comment_id), args.by, timestamp, body, verb=action_word('comment', str(comment_id), subject_type='task'))
                elif args.verb in {"flag", "unflag"}:
                    old_flag = task["flag"] or 0
                    new_flag = 1 if args.verb == "flag" else 0
                    if args.verb == "unflag" and old_flag != 1:
                        raise WorkError("task is not flagged: " + args.task)
                    duplicate = old_flag == new_flag
                    body = (FLAG_PREFIX if new_flag else "Unflag: ") + args.text
                    insert_comment(db, args.task, args.by, timestamp, body)
                    if not duplicate:
                        db.execute("UPDATE tasks SET flag=? WHERE id=?", (new_flag, args.task))
                        activity(db, args.task, 'flag', old_flag, new_flag, args.by, timestamp, body, verb=action_word('flag', new_flag, subject_type='task'))
                elif args.verb == "block":
                    assert_not_final(task, "block")
                    prior_controller = task["claimed_by"] or (
                        task["owner"] if task["status"] == "in-progress" else None
                    )
                    takeover = None
                    if args.takeover and prior_controller and prior_controller != args.by:
                        takeover = one_line(args.takeover, "--takeover")
                    elif args.takeover:
                        raise WorkError("--takeover requires a different current controller")
                    else:
                        assert_controller(task, args.by)
                    block_note = args.text + (" | takeover: " + takeover if takeover else "")
                    next_tags = tag_state(task["tags"], "business-input", args.business_input)
                    prior = db.execute(
                        "SELECT new_value,actor,note FROM activity WHERE subject_type='task' AND subject_id=? AND field='status' ORDER BY id DESC LIMIT 1",
                        (args.task,),
                    ).fetchone()
                    duplicate = (
                        task["status"] == "blocked"
                        and (has_t309(db) or task["flag"] == 1)
                        and prior is not None
                        and prior["new_value"] == "blocked"
                        and prior["actor"] == args.by
                        and prior["note"] == block_note
                        and task["tags"] == next_tags
                    )
                    if not duplicate:
                        if has_t309(db):
                            db.execute("UPDATE tasks SET status='blocked',tags=? WHERE id=?", (next_tags, args.task))
                            if task["status"] != "blocked":
                                activity(db, args.task, 'status', task['status'], 'blocked', args.by, timestamp, block_note, verb=action_word('status', 'blocked', command='block', subject_type='task'))
                        else:
                            db.execute("UPDATE tasks SET status='blocked',flag=1,tags=? WHERE id=?", (next_tags, args.task))
                            activity(db, args.task, 'status', task['status'], 'blocked', args.by, timestamp, block_note, verb=action_word('status', 'blocked', command='block', subject_type='task'))
                        insert_comment(db, args.task, args.by, timestamp, "Blocked: " + block_note)
                elif args.verb == "done":
                    assert_not_final(task, "submit evidence for")
                    assert_controller(task, args.by)
                    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='runs'").fetchone():
                        open_runs = [row[0] for row in db.execute(
                            "SELECT id FROM runs WHERE subject_type='task' AND subject_id=? AND (ended_at IS NULL OR ended_at='') ORDER BY id",
                            (args.task,),
                        )]
                        if open_runs:
                            raise WorkError(f"task {args.task} has open runs: {', '.join(open_runs)}; end them with run-end before done")
                    duplicate = done_write(db, task, args.by, args.note, receipts, timestamp)
                    if before_final_receipt_check:
                        before_final_receipt_check()
                    for receipt in receipts:
                        verify_receipt(receipt, root)
                elif args.verb == "accept":
                    approval = approved_accept(db, args.approval, task) if args.approval is not None else None
                    if approval is None:
                        assert_signer(db, task, args.by)
                    # The recorded person is the signer; args.by is the acting seat.
                    approval_note = f"; approval={approval}" if approval else ""
                    if not has_t309(db):
                        target = "accepted" if supports_accepted(db) else "done"
                        duplicate = task["status"] == "accepted"
                        if not duplicate and not (task["status"] == "done" and target == "accepted"):
                            assert_not_final(task, "accept")
                        if not duplicate:
                            if task["flag"] != 1:
                                raise WorkError("task is not flagged for acceptance: " + args.task)
                            assert_accept_evidence(db, task)
                            if target == "done":
                                print("warning: tracker has no status accepted; set done. Upgrade the tracker schema", file=errors)
                            db.execute("UPDATE tasks SET status=? WHERE id=?", (target, args.task))
                            activity(db, args.task, 'status', task['status'], target, args.by, timestamp, 'accepted receipt' + approval_note, verb=action_word('status', target, command='accept'))
                    else:
                        duplicate = task["status"] == "done"
                        if not duplicate:
                            own_task = (task["owner"] or "").strip().casefold() == _fox_person.name().casefold()
                            if not own_task:
                                if task["status"] != "in-review":
                                    raise WorkError("task must be in-review before sign-off")
                            assert_accept_evidence(db, task)
                            db.execute("UPDATE tasks SET status='done' WHERE id=?", (args.task,))
                            activity(db, args.task, 'status', task['status'], 'done', args.by, timestamp, 'accepted' + approval_note, verb=action_word('status', 'done', command='accept', subject_type='task'))
                elif args.verb == "bounce":
                    if task["status"] != "in-review":
                        raise WorkError("task must be in-review before bounce: " + args.task)
                    if args.by.casefold() != _fox_person.name().casefold():
                        assert_lead_seat(args.by, "bounce it")
                    assert_not_finisher(db, task, args.by, "bounce it")
                    db.execute("UPDATE tasks SET status='in-progress' WHERE id=?", (args.task,))
                    insert_comment(db, args.task, args.by, timestamp, "Bounce: " + args.text)
                    activity(db, args.task, 'status', 'in-review', 'in-progress', args.by, timestamp, args.text, verb=action_word('status', 'in-progress', command='bounce', subject_type='task'))
                elif args.verb == "cancel":
                    duplicate = task["status"] == "canceled" and task["canceled_reason"] == args.reason and task["folded_into"] == args.folded_into
                    if not duplicate:
                        assert_not_final(task, "cancel")
                        if args.folded_into:
                            if args.folded_into == args.task or not db.execute("SELECT 1 FROM tasks WHERE id=?", (args.folded_into,)).fetchone():
                                raise WorkError("--folded-into needs a different existing task")
                        db.execute("UPDATE tasks SET status='canceled',canceled_reason=?,folded_into=? WHERE id=?",
                                   (args.reason, args.folded_into, args.task))
                        activity(db, args.task, 'status', task['status'], 'canceled', args.by, timestamp, args.reason + ('; folded into ' + args.folded_into if args.folded_into else ''), verb=action_word('status', 'canceled', command='cancel', subject_type='task'))
                elif args.verb == "run-start":
                    task_match = db.execute("SELECT id FROM tasks WHERE id=?", (args.task,)).fetchone()
                    if not task_match:
                        raise WorkError(run_start_refusal(db, args.task))
                    timestamp = now()
                    run_id = "R-" + datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%f") + "-" + args.task
                    run_note = args.note
                    if args.desktop_session:
                        run_note = (run_note or "") + ("\n" if run_note else "") + "desktop_session=" + args.desktop_session
                    db.execute(
                        'INSERT INTO runs (id,subject_type,subject_id,"by",model,runtime,session,started_at,note) VALUES (?,?,?,?,?,?,?,?,?)',
                        (
                            run_id, "task", args.task, args.by,
                            one_line(args.model, "--model"), one_line(args.runtime, "--runtime"),
                            one_line(args.session, "--session") if args.session else None, timestamp, run_note,
                        ),
                    )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        finally:
            db.close()
        export_after_write(database, root, errors)
        suffix = (" already flagged; reason added; flag unchanged" if args.verb == "flag" else " duplicate") if duplicate else ""
        if args.verb == "run-start":
            print(run_id, file=output)
        else:
            print(f"ok {args.verb} {args.task}{suffix}", file=output)
        return 0
    except (OSError, sqlite3.Error, WorkError) as error:
        print("work failed: " + str(error), file=errors)
        return 2
    finally:
        for receipt in receipts:
            receipt.close()


if __name__ == "__main__":
    raise SystemExit(run())
