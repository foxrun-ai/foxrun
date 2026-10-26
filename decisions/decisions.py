#!/usr/bin/env python3
"""Decision functions called by the existing work command."""
from __future__ import annotations

import sys as _person_sys
from pathlib import Path as _PersonPath
_person_root = next(p for p in _PersonPath(__file__).resolve().parents if (p / "base/person.py").is_file())
_person_sys.path.insert(0, str(_person_root))
_person_sys.path[:0] = [str(_person_root / "work"), str(_person_root / "events")]
from base import person as _fox_person
import re
import sqlite3
from work import (WorkError, REPLACES_WORD, DECISION_IDS, COMMENT_REF, SUBJECT_TABLES,
                  one_line, optional_line, optional_text, normalized_tags, now,
                  record_activity, action_word)


def decision_statuses(db: sqlite3.Connection) -> tuple[str, ...]:
    row = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='decisions'").fetchone()
    match = re.search(r"status\s+IN\s*\(([^)]*)\)", row[0] if row else "", re.IGNORECASE)
    if not match:
        raise WorkError("decisions.status has no CHECK list; refusing to guess allowed values")
    return tuple(re.findall(r"'([^']*)'", match.group(1)))


def ensure_replaces_text(db: sqlite3.Connection) -> None:
    """Remove the old single-id FK; replaces also holds clauses and id lists."""
    keys = list(db.execute('PRAGMA foreign_key_list("decisions")'))
    if not keys:
        return
    if {(row[2], row[3], row[4]) for row in keys} != {("decisions", "replaces", "id")}:
        raise WorkError("unsupported decisions foreign keys")
    schema = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='decisions'").fetchone()[0]
    if schema.count("REFERENCES decisions(id)") != 1:
        raise WorkError("unsupported decisions.replaces definition")
    columns = ",".join('"' + row[1] + '"' for row in db.execute('PRAGMA table_info("decisions")'))
    views = [(row[0], row[1]) for row in db.execute(
        "SELECT name,sql FROM sqlite_master WHERE type='view' ORDER BY rowid"
    )]
    indexes = [row[0] for row in db.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name='decisions' AND sql IS NOT NULL"
    )]
    triggers = [row[0] for row in db.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' AND tbl_name='decisions'"
    )]
    for name, _ in reversed(views):
        db.execute('DROP VIEW "' + name.replace('"', '""') + '"')
    create = re.sub(r"\bCREATE TABLE(?: IF NOT EXISTS)?\s+decisions\b",
                    "CREATE TABLE decisions_replaces_upgrade", schema, count=1)
    create = create.replace("REFERENCES decisions(id)", "")
    db.execute(create)
    db.execute(f"INSERT INTO decisions_replaces_upgrade ({columns}) SELECT {columns} FROM decisions")
    db.execute("DROP TABLE decisions")
    db.execute("ALTER TABLE decisions_replaces_upgrade RENAME TO decisions")
    for sql in indexes + triggers + [sql for _, sql in views]:
        db.execute(sql)


def checked_replaces(db: sqlite3.Connection, replaces: str | None, statement: str | None,
                     record_id: str) -> tuple[str | None, list[str]]:
    word = REPLACES_WORD.search(statement or "")
    if word and not replaces:
        raise WorkError(f"statement contains '{word.group()}'; set --replaces to decision id(s), clause text, or none")
    if not replaces or replaces == "none" or not DECISION_IDS.fullmatch(replaces):
        return replaces, []
    ids = replaces.split(",")
    if len(ids) != len(set(ids)):
        raise WorkError("--replaces repeats a decision id")
    if record_id in ids:
        raise WorkError("a decision cannot replace itself: " + record_id)
    for target in ids:
        if not db.execute("SELECT 1 FROM decisions WHERE id=?", (target,)).fetchone():
            raise WorkError("no such decision to replace: " + target)
    return replaces, ids


def supersede_targets(db: sqlite3.Connection, ids: list[str], actor: str, timestamp: str,
                      replacement: str) -> None:
    for target in ids:
        old = db.execute("SELECT status FROM decisions WHERE id=?", (target,)).fetchone()[0]
        if old == "superseded":
            continue
        db.execute("UPDATE decisions SET status='superseded' WHERE id=?", (target,))
        record_activity(db, 'decision', target, 'status', old, 'superseded', actor, timestamp, 'replaced by ' + replacement, verb=action_word('status', 'superseded', subject_type='decision'))


def decision_add_write(db: sqlite3.Connection, args) -> str:
    actor = args.by
    record_id = args.record_id
    name = one_line(args.name, "--name")
    status = args.status or "ruled"
    allowed = decision_statuses(db)
    if status not in allowed:
        raise WorkError("--status must be one of: " + ", ".join(allowed))
    source = optional_line(args.source, "--source")
    if db.execute("SELECT 1 FROM decisions WHERE id=?", (record_id,)).fetchone():
        raise WorkError("decision already exists: " + record_id)
    for comment in COMMENT_REF.findall(source or ""):
        if not db.execute("SELECT 1 FROM comments WHERE id=?", (int(comment),)).fetchone():
            raise WorkError("no such comment: " + comment)
        for row in db.execute("SELECT id,source FROM decisions WHERE source LIKE ?", ("%comment:" + comment + "%",)):
            if comment in COMMENT_REF.findall(row["source"] or ""):
                raise WorkError(f"comment:{comment} is already promoted to decision {row['id']}")
    replaces, targets = checked_replaces(db, optional_line(args.replaces, "--replaces"),
                                         args.statement, record_id)
    function = optional_line(args.function, "--function")
    if function and not db.execute("SELECT 1 FROM functions WHERE id=?", (function,)).fetchone():
        raise WorkError("no such function: " + function)
    tags = ",".join(normalized_tags(args.tags)) or None if args.tags is not None else None
    timestamp = now()
    db.execute(
        "INSERT INTO decisions (id,name,statement,person_words,status,replaces,project,function,tags,decided_on,source) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            record_id, name, optional_text(args.statement, "--statement"),
            optional_text(args.person_words, "--person-words"), status, replaces,
            optional_line(args.project, "--project"), function, tags,
            args.decided_on or timestamp[:10], source,
        ),
    )
    note = "status=" + status + ("; source=" + source if source else "") + ("; replaces=" + replaces if replaces else "")
    record_activity(db, 'decision', record_id, 'create', None, name, actor, timestamp, note, verb=action_word('create', name, subject_type='decision', command='decision-add', status=status))
    if not args.partial:
        supersede_targets(db, targets, actor, timestamp, record_id)
    return record_id


def decision_update_write(db: sqlite3.Connection, args) -> str:
    actor = args.by
    record_id = one_line(args.task, "decision id")
    row = db.execute("SELECT statement,status,replaces FROM decisions WHERE id=?", (record_id,)).fetchone()
    if not row:
        raise WorkError("no such decision: " + record_id)
    statement = optional_text(args.statement, "--statement") if args.statement is not None else row["statement"]
    replaces, targets = checked_replaces(
        db, optional_line(args.replaces, "--replaces") if args.replaces is not None else row["replaces"],
        statement, record_id,
    )
    status = args.status if args.status is not None else row["status"]
    if status not in decision_statuses(db):
        raise WorkError("--status must be one of: " + ", ".join(decision_statuses(db)))
    timestamp = now()
    note = optional_text(args.note, "--note")
    for field, old, new in (("statement", row["statement"], statement), ("replaces", row["replaces"], replaces), ("status", row["status"], status)):
        if old != new:
            db.execute(f"UPDATE decisions SET {field}=? WHERE id=?", (new, record_id))
            record_activity(db, 'decision', record_id, field, old, new, actor, timestamp, note, verb=action_word(field, new, subject_type='decision'))
    if not args.partial and args.replaces is not None:
        supersede_targets(db, targets, actor, timestamp, record_id)
    return record_id


def approval_add_write(db: sqlite3.Connection, args) -> str:
    actor = args.by
    subject_type = one_line(args.subject_type or "task", "--subject-type")
    subject_id = one_line(args.task, "subject id")
    table = SUBJECT_TABLES.get(subject_type)
    if table and db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
        if not db.execute(f'SELECT 1 FROM "{table}" WHERE id=?', (subject_id,)).fetchone():
            raise WorkError("no such " + subject_type + ": " + subject_id)
    source = optional_line(args.source, "--source")
    prior = db.execute(
        "SELECT id FROM approvals WHERE subject_type=? AND subject_id=? AND call=? AND source IS ?",
        (subject_type, subject_id, args.call, source),
    ).fetchone()
    if prior:
        raise WorkError(f"approval already exists: {prior['id']} ({subject_type} {subject_id} {args.call} source={source})")
    optional_text(args.person_words, "--person-words")  # Validate; preserve the original text below.
    timestamp = now()
    cursor = db.execute(
        "INSERT INTO approvals (subject_type,subject_id,version,call,person_words,given_at,source) VALUES (?,?,?,?,?,?,?)",
        (
            subject_type, subject_id, optional_line(args.version, "--version"), args.call,
            args.person_words, args.given_at or timestamp, source,
        ),
    )
    approval_id = int(cursor.lastrowid)
    note = "approval=" + str(approval_id) + ("; source=" + source if source else "")
    record_activity(db, subject_type, subject_id, 'approval', None, args.call, actor, timestamp, note, verb=action_word('approval', args.call, subject_type=subject_type))
    return f"{subject_type} {subject_id} approval={approval_id}"



def run(argv=None):
    """Expose the drawn words while retaining the existing work writer."""
    import argparse
    import json
    from urllib.parse import quote
    import work as writer

    argv = list(_person_sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("add", "update"):
        return writer.run(["decision-" + argv[0]] + argv[1:])

    parser = argparse.ArgumentParser(
        description="Read decisions. Add and update use the checked work writer.",
        epilog="Writes: decisions.py add|update [work decision flags] --db PATH --receipt-root PATH --by ACTOR. "
               "Use add --help or update --help for the existing writer flags.",
    )
    parser.add_argument("verb", choices=("show", "list"))
    parser.add_argument("id", nargs="?")
    parser.add_argument("--db", type=_PersonPath)
    parser.add_argument("--workspace")
    parser.add_argument("--status")
    args = parser.parse_args(argv)
    if args.verb == "show" and (not args.id or args.status):
        parser.error("show needs one decision id; --status belongs to list")
    if args.verb == "list" and args.id:
        parser.error("list does not take a decision id")
    try:
        database = args.db
        if args.workspace:
            from base.tracker import tracker
            database = tracker(args.workspace, database)
        if database is None:
            database = _person_root / "data.db"
        database = writer.existing_path(database, "database")
        if any(writer.SECRET_PART.search(part) for part in database.parts):
            raise WorkError("database is a refused secret path")
        uri = "file:" + quote(str(database), safe="/:@") + "?mode=ro"
        with sqlite3.connect(uri, uri=True) as db:
            db.row_factory = sqlite3.Row
            if args.verb == "show":
                record = db.execute("SELECT * FROM decisions WHERE id=?", (args.id,)).fetchone()
                if record is None:
                    raise WorkError("no such decision: " + args.id)
                result = dict(record)
            else:
                sql = "SELECT * FROM decisions"
                values = ()
                if args.status:
                    sql += " WHERE status=?"
                    values = (args.status,)
                result = [dict(record) for record in db.execute(sql + " ORDER BY id", values)]
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (WorkError, ValueError, OSError, sqlite3.Error) as error:
        print("error: " + str(error), file=_person_sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
