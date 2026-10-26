#!/usr/bin/env python3
"""Log tracked Claude and Codex sessions on a standing task."""

from __future__ import annotations

import sys as _person_sys
from pathlib import Path as _PersonPath
_person_root = next(p for p in _PersonPath(__file__).resolve().parents if (p / "base/person.py").is_file())
_person_sys.path.insert(0, str(_person_root))
from base import person as _fox_person

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_sys.path.insert(0, str(_FoxPath(__file__).resolve().parent / '..'))
from base import paths as _fox_paths

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / '../work'))
from work import (
    HOLDING_BACKFILL_REQUIRED, SESSION_HOLDING_KEY, STANDING_TITLE,
    normalized_tags, session_holding_task, task_project,
)
from history_actions import write_history

BUSY_TIMEOUT = 2.0


def one_line(value: str | None, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\n" in value or "\r" in value:
        raise ValueError(f"{name} must be one non-empty line")
    return value.strip()


def session_id(value: str | None) -> str:
    session = one_line(value, "--session")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}", session):
        raise ValueError("--session has invalid characters")
    return session


def tracker_from(cwd: str | None) -> Path | None:
    directory = Path(cwd or os.getcwd()).expanduser().resolve(strict=True)
    if not directory.is_dir():
        raise ValueError("--cwd must be a directory")
    root = Path(os.environ.get("FOX_SESSION_TRACKED_ROOT", str((_fox_paths.portfolio())))).expanduser().resolve()
    if directory != root and root not in directory.parents:
        return None
    relative = directory.relative_to(root)
    config = _fox_person.configuration()
    if relative.parts and relative.parts[0] in config.get('untracked_workspaces', []):
        return None
    candidate = relative.parts[0] if relative.parts else _fox_person.workspace()
    roster = _fox_person.configured_workspaces() or []
    workspace = candidate if candidate in config.get('session_workspaces', roster) else _fox_person.workspace()
    configured = _fox_person.workspace_setting(workspace, 'tracker')
    choices = [root / workspace / name for name in ([configured] if configured else ['data.db', f"{workspace}.sqlite"])]
    if root == _fox_paths.portfolio():
        # One system tracker since the 10.15 move: workspaces without their own use data.db in the home.
        choices.append(_fox_paths.database())
    return next((tracker for tracker in choices if tracker.is_file()), None)


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def setup(args: argparse.Namespace) -> None:
    tracker = Path(args.db).expanduser().resolve(strict=True)
    if not tracker.is_file():
        raise ValueError("--db must be a tracker file")
    with _fox_person.connect(tracker, timeout=1) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("BEGIN IMMEDIATE")
        existing = session_holding_task(db, required=False)
        if existing is not None:
            print(existing)
            return
        if not args.create or db.execute("SELECT 1 FROM tasks LIMIT 1").fetchone():
            raise ValueError(HOLDING_BACKFILL_REQUIRED + "; setup --create is only for an empty tracker at first installation")
        project = getattr(args, 'project', None) or _fox_person.configuration().get('session_project')
        stream = (db.execute('SELECT id,function FROM projects WHERE id=?', (project,)).fetchone()
                  if project else db.execute('SELECT id,function FROM projects ORDER BY id LIMIT 1').fetchone())
        if stream is None and project:
            raise ValueError('no such session project: ' + project)
        if stream is None:
            # A fresh install has no project yet; the holding task starts unfiled (T595).
            stream = (None, None)
        else:
            task_project(db, stream[0], for_move=True)
        numbers = [int(row[0][1:]) for row in db.execute("SELECT id FROM tasks WHERE id GLOB 'T[0-9]*'")
                   if re.fullmatch(r"T[0-9]+", row[0])]
        task = "T" + str(max(numbers, default=0) + 1)
        stamp = now()
        db.execute(
            "INSERT INTO tasks (id,title,status,project,function,tags,created_by,created_on,source,note,idempotency_key) "
            "VALUES (?,?,'todo',?,?,'recurring','session-run-setup',?,'session_run setup',?,?)",
            (task, STANDING_TITLE, stream[0], stream[1], stamp, "Each tracked session starts here; move its run to the work task at wrap.",
             SESSION_HOLDING_KEY),
        )
        write_history(db, 'task', task, 'create', None, STANDING_TITLE,
                      'session-run-setup', 'session_run setup', stamp)
        print(task)


def backfill_key(args: argparse.Namespace) -> None:
    tracker = Path(args.db).expanduser().resolve(strict=True)
    if not tracker.is_file():
        raise ValueError("--db must be a tracker file")
    task = one_line(args.task, "--task")
    with _fox_person.connect(tracker, timeout=BUSY_TIMEOUT) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("BEGIN IMMEDIATE")
        existing = session_holding_task(db, required=False)
        if existing is not None and existing != task:
            raise ValueError(f"session holding key already belongs to {existing}; cannot assign it to {task}")
        row = db.execute("SELECT status,tags,idempotency_key FROM tasks WHERE id=?", (task,)).fetchone()
        if row is None:
            raise ValueError("no such task: " + task)
        if row[0] in {"done", "canceled", "superseded"}:
            raise ValueError(f"backfill requires a live task; {task} is {row[0]}")
        if not isinstance(row[1], str) or "recurring" not in normalized_tags(row[1]):
            raise ValueError("backfill requires the recurring tag on " + task)
        if existing == task:
            print(task + " already keyed; no changes")
            return
        if row[2] is not None:
            raise ValueError(f"{task} already has an idempotency_key; backfill never replaces a key")
        db.execute("UPDATE tasks SET idempotency_key=? WHERE id=?", (SESSION_HOLDING_KEY, task))
        write_history(db, 'task', task, 'idempotency_key', None, SESSION_HOLDING_KEY,
                      'session-run-backfill', 'session_run backfill-key', now())
        print(task + " keyed")


def transcript_for(session: str, runtime: str, supplied: str | None) -> Path | None:
    if supplied:
        candidate = Path(supplied).expanduser()
        if candidate.suffix != ".jsonl" or session not in candidate.name:
            raise ValueError("--transcript must name this session's JSONL transcript")
        return candidate
    return None


def first_assistant_model(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    with path.open(encoding="utf-8") as source:
        for index, line in enumerate(source):
            if index >= 128:
                break
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("type") != "assistant":
                continue
            message = entry.get("message")
            if isinstance(message, dict):
                model = message.get("model")
                if isinstance(model, str) and model.strip() and model != "<synthetic>":
                    return one_line(model, "transcript model")
    return None


def start(args: argparse.Namespace) -> None:
    session = session_id(args.session)
    model = one_line(args.model, "--model") if args.model is not None else "pending"
    runtime = one_line(args.runtime, "--runtime")
    actor = one_line(args.by, "--by") if args.by else runtime
    tracker = tracker_from(args.cwd)
    if tracker is None:
        return
    cwd = str(Path(args.cwd or os.getcwd()).expanduser().resolve(strict=True))
    with _fox_person.connect(tracker, timeout=BUSY_TIMEOUT) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("BEGIN IMMEDIATE")
        task = session_holding_task(db)
        previous = db.execute(
            'SELECT id,ended_at,result,note FROM runs WHERE "session"=? '
            "ORDER BY started_at DESC LIMIT 1", (session,),
        ).fetchone()
        if previous:
            if not (previous[3] or "").startswith("opened_by=hook") or previous[1] is None or args.source != "resume":
                return
            if previous[2] is None:
                stamp = now()
                db.execute("UPDATE runs SET ended_at=NULL WHERE id=?", (previous[0],))
                write_history(db, 'run', previous[0], 'ended_at', previous[1], None,
                              actor, 'session_run resume', stamp)
                return
        stamp = now()
        run_id = "R-" + datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%f") + "-" + task
        note = "opened_by=hook\ncwd=" + cwd
        if args.desktop_session:
            note += "\ndesktop_session=" + one_line(args.desktop_session, "--desktop-session")
        db.execute(
            'INSERT INTO runs (id,subject_type,subject_id,"by",model,runtime,"session",started_at,note) '
            "VALUES (?,'task',?,?,?,?,?,?,?)",
            (run_id, task, actor, model, runtime, session, stamp, note),
        )


def end(args: argparse.Namespace) -> None:
    session = session_id(args.session)
    model = one_line(args.model, "--model") if args.model is not None else None
    tracker = tracker_from(args.cwd)
    if tracker is None:
        return
    with _fox_person.connect(tracker, timeout=BUSY_TIMEOUT) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            'SELECT id,model,runtime FROM runs WHERE "session"=? AND note LIKE \'opened_by=hook%\' '
            "AND ended_at IS NULL LIMIT 1", (session,),
        ).fetchone()
        if row is None:
            return
        if row[1] == "pending" and model is None:
            model = first_assistant_model(transcript_for(session, row[2], args.transcript))
        db.execute(
            "UPDATE runs SET ended_at=?, model=? WHERE id=?",
            (now(), (model or row[1]) if row[1] == "pending" else row[1], row[0]),
        )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    setup_command = commands.add_parser("setup", help="verify the holding task; explicit first installation on an empty tracker")
    setup_command.add_argument("--db", required=True)
    setup_command.add_argument("--project", help="existing session project; defaults to the first project")
    setup_command.add_argument("--create", action="store_true", help="create a keyed holding task only on an empty tracker")
    backfill_command = commands.add_parser("backfill-key", help="assign the reserved key to the named live recurring task once")
    backfill_command.add_argument("--db", required=True)
    backfill_command.add_argument("--task", required=True)
    start_command = commands.add_parser("start")
    start_command.add_argument("--runtime", choices=("claude", "codex"), required=True)
    start_command.add_argument("--session", required=True)
    start_command.add_argument("--cwd")
    start_command.add_argument("--model")
    start_command.add_argument("--desktop-session")
    start_command.add_argument("--by")
    start_command.add_argument("--source", choices=("startup", "resume", "clear", "fork"), default="startup")
    end_command = commands.add_parser("end")
    end_command.add_argument("--session", required=True)
    end_command.add_argument("--cwd")
    end_command.add_argument("--model")
    end_command.add_argument("--transcript", help=argparse.SUPPRESS)
    for name in ("hook-start", "hook-end"):
        hook = commands.add_parser(name, help=argparse.SUPPRESS)
        hook.add_argument("--runtime", choices=("claude", "codex"), required=True)
    return result


def from_hook(args: argparse.Namespace) -> argparse.Namespace | None:
    if os.environ.get("FOXRUN_NO_SESSION_LOG") == "1":
        return None
    if args.runtime == "claude" and os.environ.get("CLAUDE_CODE_ENTRYPOINT", "").startswith("sdk-"):
        return None
    data = json.load(sys.stdin)
    if not isinstance(data, dict):
        raise ValueError("hook input must be a JSON object")
    event = "SessionStart" if args.command == "hook-start" else "SessionEnd"
    if data.get("hook_event_name") != event:
        raise ValueError(f"expected {event} hook input")
    if event == "SessionStart" and data.get("source") == "compact":
        return None
    cwd = one_line(data.get("cwd"), "hook cwd")
    return argparse.Namespace(
        session=data.get("session_id"), cwd=cwd, model=data.get("model"),
        runtime=args.runtime, by=data.get("seat") or data.get("agent"),
        desktop_session=data.get("desktop_session"),
        transcript=data.get("transcript_path"),
        source=data.get("source"),
    )


def main(argv: list[str] | None = None) -> int:
    command = None
    try:
        args = parser().parse_args(argv)
        command = args.command
        if command not in {"setup", "backfill-key"} and os.environ.get("FOXRUN_NO_SESSION_LOG") == "1":
            return 0
        if command != "setup" and getattr(args, "runtime", None) == "claude" and os.environ.get("CLAUDE_CODE_ENTRYPOINT", "").startswith("sdk-"):
            return 0
        if args.command.startswith("hook-"):
            hook_args = from_hook(args)
            if hook_args is None:
                return 0
            action = start if args.command == "hook-start" else end
            action(hook_args)
        elif args.command == "setup":
            setup(args)
        elif args.command == "backfill-key":
            backfill_key(args)
        elif args.command == "start":
            start(args)
        else:
            end(args)
    except (Exception, SystemExit) as error:
        print(f"session_run: {error}", file=sys.stderr)
        return 2 if command in {"setup", "backfill-key"} else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
