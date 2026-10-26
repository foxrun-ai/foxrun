#!/usr/bin/env python3
"""Read the work-module program plan."""

from __future__ import annotations

import sys as _person_sys
from pathlib import Path as _PersonPath
_person_root = next(p for p in _PersonPath(__file__).resolve().parents if (p / "base/person.py").is_file())
_person_sys.path.insert(0, str(_person_root))
import os as _person_os
_person_os.environ.setdefault('FOXRUN_HOME', str(_person_root))
from base import person as _fox_person

import argparse
from collections import Counter
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

WORK = (Path(__file__).resolve().parent / 'work.py')
APPLY = _person_root / 'archive/one-time-scripts/apply_program_schema.py'
STATUS_LABELS = {"backlog": "Backlog", "todo": "To do", "in-progress": "In progress", "blocked": "Blocked", "in-review": "In review", "done": "Done", "accepted": "Accepted", "canceled": "Canceled", "superseded": "Superseded"}
FINISHED = ("done", "accepted")


def connect(database: Path) -> sqlite3.Connection:
    if not database.is_file():
        raise ValueError("database must already exist: " + str(database))
    uri = "file:" + quote(str(database), safe="/:@") + "?mode=ro"
    db = _fox_person.connect(uri, uri=True)
    db.row_factory = sqlite3.Row
    return db


def needs(value: str | None) -> list[str]:
    parsed = json.loads(value or "[]")
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise ValueError("stream needs must be a JSON list of ids")
    return parsed


def task_blockers(db: sqlite3.Connection, task_id: str, legacy: str | None) -> list[str]:
    blockers = {legacy} if legacy else set()
    blockers.update(row[0] for row in db.execute(
        "SELECT task FROM task_links WHERE system='task' AND relation='blocks' "
        "AND external_id=? AND active=1", (task_id,),
    ))
    return sorted(blockers)


def require_applied(db: sqlite3.Connection, database: Path) -> None:
    objects = {
        row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE name IN ('programs','themes','runs','stream_brief')"
        )
    }
    columns = {row[1] for row in db.execute('PRAGMA table_info("stream_brief")')}
    required = {"status", "open_tasks", "live_tasks", "done_tasks", "backlog_tasks"}
    if objects != {"programs", "themes", "runs", "stream_brief"} or not required.issubset(columns):
        raise ValueError(
            "program control is not applied; run: python3 " + str(APPLY)
            + " --db " + str(database) + " --receipt-root <workspace>"
        )


def open_runs(db: sqlite3.Connection, stream: str) -> list[dict]:
    runs = [dict(row) for row in db.execute(
        'SELECT id,subject_type,subject_id,"by",model,runtime,session,started_at FROM runs '
        "WHERE ended_at IS NULL AND ((subject_type='stream' AND subject_id=?) "
        "OR (subject_type='task' AND subject_id IN (SELECT id FROM tasks WHERE project=?))) "
        "ORDER BY started_at DESC,id",
        (stream, stream),
    )]
    for run in runs:
        note = db.execute(
            "SELECT body,at FROM comments WHERE subject_type='run' AND subject_id=? "
            "ORDER BY at DESC,id DESC LIMIT 1",
            (run["id"],),
        ).fetchone()
        run["latest_note"] = note["body"] if note else None
        run["latest_note_at"] = note["at"] if note else None
    return runs


def inbox(db: sqlite3.Connection) -> list[dict]:
    """Open tasks with no project (work stream)."""
    return [dict(row) for row in db.execute(
        "SELECT id,title,status,owner,claimed_by FROM tasks "
        "WHERE project IS NULL AND status NOT IN ('done','accepted','canceled','superseded') ORDER BY ord,id"
    )]


def show(db: sqlite3.Connection) -> dict:
    legacy_runs = [dict(row) for row in db.execute(
        'SELECT id,subject_type,subject_id,"by",started_at,ended_at,result FROM runs '
        "WHERE subject_type IN ('stream','job') ORDER BY started_at DESC,id"
    )]
    program = db.execute("SELECT * FROM programs ORDER BY created_on,id LIMIT 1").fetchone()
    if program is None:
        return {
            "id": None, "name": None, "objective": None,
            "tasks": {"total": 0, "done": 0, "percent": 0, "statuses": {}},
            "streams": [], "inbox": inbox(db), "legacy_runs": legacy_runs,
        }
    statuses = dict(db.execute(
        "SELECT t.status,count(*) FROM tasks t JOIN projects p ON p.id=t.project "
        "WHERE p.program=? AND p.status<>'superseded' AND t.status<>'canceled' GROUP BY t.status",
        (program["id"],),
    ))
    streams = [dict(row) for row in db.execute(
        "SELECT stream_id,stream,theme_id,theme,status,open_tasks,live_tasks,done_tasks,backlog_tasks,ord "
        "FROM stream_brief WHERE program_id=?",
        (program["id"],),
    )]
    for stream in streams:
        stream["percent"] = round(stream["done_tasks"] * 100 / stream["live_tasks"]) if stream["live_tasks"] else 0
        stream["open_runs"] = open_runs(db, stream["stream_id"])
    total = sum(statuses.values())
    done = sum(statuses.get(status, 0) for status in FINISHED)
    return {
        "id": program["id"], "name": program["name"], "objective": program["objective"],
        "tasks": {"total": total, "done": done, "percent": round(done * 100 / total) if total else 0, "statuses": statuses},
        "streams": streams, "inbox": inbox(db), "legacy_runs": legacy_runs,
    }


def pick_up(db: sqlite3.Connection, stream: str, database: Path, receipt_root: Path) -> dict:
    row = db.execute("SELECT * FROM stream_brief WHERE stream_id=?", (stream,)).fetchone()
    if row is None:
        raise ValueError("no such program stream: " + stream)
    dependency_ids = needs(row["needs"])
    dependency_rows = []
    for dependency in dependency_ids:
        found = db.execute(
            "SELECT stream_id AS id,stream AS title,status,backlog_tasks FROM stream_brief WHERE stream_id=?",
            (dependency,),
        ).fetchone()
        dependency_rows.append(dict(found) if found else {"id": dependency, "title": "missing", "status": "missing"})
    tasks = [dict(item) for item in db.execute(
        "SELECT id,title,status,owner,claimed_by,ord,blocked_by FROM tasks WHERE project=? AND status NOT IN ('done','accepted','canceled','superseded') ORDER BY ord,id",
        (stream,),
    )]
    for task in tasks:
        task["blockers"] = task_blockers(db, task["id"], task.pop("blocked_by"))
    runs = [dict(item) for item in db.execute(
        'SELECT id,"by",model,runtime,session,started_at,ended_at,result,fix_rounds,evidence FROM runs '
        "WHERE (subject_type='stream' AND subject_id=?) "
        "OR (subject_type='task' AND subject_id IN (SELECT id FROM tasks WHERE project=?)) "
        "ORDER BY started_at DESC LIMIT 3",
        (stream, stream),
    )]
    base = f"python3 {WORK} --db {database} --receipt-root {receipt_root}"
    commands = [
        base + " run-start <task-id> --by <name> --model <model> --runtime <runtime> --session <native-session-id>",
        base + " run-end <run-id> --result <result> --evidence <relative-path> --fix-rounds 0",
    ]
    if tasks:
        commands.extend((
            base + f" claim {tasks[0]['id']} --by <name>",
            base + f" done {tasks[0]['id']} --by <name> --receipt <relative-path> --proof <one-line-proof>",
        ))
    return {
        "id": row["stream_id"], "title": row["stream"], "theme": row["theme"],
        "status": row["status"], "result": row["result"], "needs": dependency_rows,
        "done_tasks": row["done_tasks"], "live_tasks": row["live_tasks"],
        "percent": round(row["done_tasks"] * 100 / row["live_tasks"]) if row["live_tasks"] else 0,
        "backlog_tasks": row["backlog_tasks"], "open_tasks": tasks, "last_runs": runs,
        "open_runs": open_runs(db, stream), "commands": commands,
    }


def next_streams(db: sqlite3.Connection) -> list[dict]:
    statuses = {row[0]: row[1] for row in db.execute("SELECT stream_id,status FROM stream_brief")}
    ready = []
    for row in db.execute("SELECT * FROM stream_brief WHERE status<>'done'"):
        dependencies = needs(row["needs"])
        if all(statuses.get(item) == "done" for item in dependencies):
            ready.append({"id": row["stream_id"], "title": row["stream"], "theme": row["theme"], "status": row["status"]})
    return ready


def status_text(status: str, backlog: int = 0) -> str:
    value = STATUS_LABELS.get(status, status)
    if status == "done" and backlog:
        value += f" · {backlog} in backlog"
    return value


def print_open_runs(runs: list[dict], indent: str = "  ") -> None:
    for run in runs:
        note = run["latest_note"] or "no run-note yet"
        at = run["latest_note_at"] or "no note time"
        print(f"{indent}{run['id']} · {run['by']} · {at} · {note}")


def print_inbox(tasks: list[dict]) -> None:
    if not tasks:
        return
    print("\nInbox")
    for task in tasks:
        owner = task["claimed_by"] or task["owner"] or "unclaimed"
        print(f"  {task['id']} · {task['title']} · {task['status']} · {owner}")


def print_show(data: dict) -> None:
    if data["id"] is None:
        print("No programs.")
        print_inbox(data.get("inbox", []))
        print_legacy_runs(data.get("legacy_runs", []))
        return
    tasks = data["tasks"]
    print(f"{data['id']} · {data['name']} · {tasks['done']}/{tasks['total']} done ({tasks['percent']}%)")
    print(data["objective"] or "No objective")
    theme = None
    for stream in data["streams"]:
        if stream["theme"] != theme:
            theme = stream["theme"]
            print("\n" + theme)
        label = status_text(stream["status"], stream["backlog_tasks"])
        print(
            f"  {stream['stream_id']} · {stream['stream']} · {label} · "
            f"{stream['done_tasks']}/{stream['live_tasks']} ({stream['percent']}%)"
        )
        print_open_runs(stream["open_runs"], "    ")
    print_inbox(data.get("inbox", []))
    print_legacy_runs(data.get("legacy_runs", []))


def print_legacy_runs(runs: list[dict]) -> None:
    if runs:
        counts = Counter(run["subject_type"] for run in runs)
        summary = ", ".join(f"{counts[kind]} {kind}" for kind in ("job", "stream") if counts[kind])
        print("\nLegacy runs waiting for placement (schema): " + summary)
        for run in runs:
            if run["ended_at"] is None:
                print(f"  {run['id']} · {run['subject_type']} {run['subject_id']} · {run['by']} · running")


def print_pick_up(data: dict) -> None:
    print(
        f"{data['id']} · {data['title']} · {status_text(data['status'], data['backlog_tasks'])} · "
        f"{data['done_tasks']}/{data['live_tasks']} ({data['percent']}%)"
    )
    print("Result: " + (data["result"] or "None"))
    print("Needs first: " + (", ".join(f"{item['id']} {item['title']} [{item['status']}]" for item in data["needs"]) or "none"))
    print("\nOpen tasks")
    if data["open_tasks"]:
        for task in data["open_tasks"]:
            owner = task["claimed_by"] or task["owner"] or "unclaimed"
            blockers = " · blocked by " + ", ".join(task["blockers"]) if task["blockers"] else ""
            print(f"  {task['ord']}. {task['id']} · {task['title']} · {task['status']} · {owner}{blockers}")
    else:
        print("  none")
    print("\nLast runs")
    if data["last_runs"]:
        for run in data["last_runs"]:
            print(f"  {run['id']} · {run['result'] or 'running'} · {run['by']}")
    else:
        print("  none")
    print("\nOpen runs")
    if data["open_runs"]:
        print_open_runs(data["open_runs"])
    else:
        print("  none")
    print("\nCommands")
    for command in data["commands"]:
        print("  " + command)


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--receipt-root", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("action", choices=("show", "pick-up", "next"))
    parser.add_argument("stream", nargs="?")
    args = parser.parse_args(argv)
    database = args.db.expanduser().resolve()
    receipt_root = args.receipt_root.expanduser().resolve()
    try:
        with closing(connect(database)) as db:
            require_applied(db, database)
            if args.action == "show":
                data = show(db)
            elif args.action == "pick-up":
                if not args.stream:
                    raise ValueError("pick-up needs a stream id")
                data = pick_up(db, args.stream, database, receipt_root)
            else:
                data = next_streams(db)
        if args.json:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        elif args.action == "show":
            print_show(data)
        elif args.action == "pick-up":
            print_pick_up(data)
        else:
            if data:
                for stream in data:
                    print(f"{stream['id']} · {stream['title']} · {stream['theme']} · {status_text(stream['status'])}")
            else:
                print("No work streams are ready.")
        return 0
    except (OSError, sqlite3.Error, ValueError, json.JSONDecodeError) as error:
        print("program failed: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(run())
