"""File-first writes and file-wins row repair."""

from __future__ import annotations

import sys as _person_sys
from pathlib import Path as _PersonPath
_person_root = next(p for p in _PersonPath(__file__).resolve().parents if (p / "base/person.py").is_file())
_person_sys.path.insert(0, str(_person_root))
from base import person as _fox_person

import fcntl
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from urllib.parse import urlsplit

from .common import (
    CaptureError, PACK_ROOT, SOURCES, capture_id, digest, inside, line,
    now, read_capture, timestamp,
)
from .files import validate_reader, write_raw


@contextmanager
def store_lock(root, store):
    root.parent.mkdir(parents=True, exist_ok=True)
    store.parent.mkdir(parents=True, exist_ok=True)
    # One lock per raw root also covers callers using different SQLite stores.
    with (root.parent / f".{root.name}-capture.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        database = _fox_person.connect(store, timeout=30)
        database.row_factory = sqlite3.Row
        try:
            database.executescript((PACK_ROOT / "blueprint.sql").read_text())
            database.execute("BEGIN IMMEDIATE")
            yield database
            database.commit()
        except BaseException:
            database.rollback()
            raise
        finally:
            database.close()
            fcntl.flock(lock, fcntl.LOCK_UN)


def later(first, second):
    first = timestamp(first, "last_seen")
    second = timestamp(second, "last_seen")
    return max((first, second), key=datetime.fromisoformat)


def row_from_file(path, root, previous=None):
    path = inside(path, root)
    metadata, body = read_capture(path)
    if metadata.get("type") != "capture" or metadata.get("workspace") != "atlas" or metadata.get("summary") is True:
        raise CaptureError(f"not an Atlas raw capture: {path}")
    source = metadata.get("kind")
    canonical = metadata.get("location")
    if source not in SOURCES or not isinstance(canonical, str):
        raise CaptureError(f"invalid capture source or location: {path}")
    parsed = urlsplit(canonical)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise CaptureError(f"invalid capture location: {path}")
    timestamp(metadata.get("timestamp"), "timestamp")
    captured = timestamp(metadata.get("captured"), "captured")
    fetched = timestamp(metadata.get("fetched_at") or captured, "fetched_at")
    last_seen = timestamp(metadata.get("last_seen") or captured, "last_seen")
    seen = metadata.get("seen", 1)
    if isinstance(seen, bool) or not isinstance(seen, int) or seen < 1:
        raise CaptureError(f"invalid seen count: {path}")
    tags = metadata.get("tags") or []
    if not isinstance(tags, list) or len(tags) > 3 or any(not isinstance(tag, str) or not tag or tag != tag.lower() for tag in tags):
        raise CaptureError(f"tags must contain at most three lowercase values: {path}")
    confidence = metadata.get("tag_confidence", json.loads(previous["tag_confidence"]) if previous else {})
    if not isinstance(confidence, dict):
        raise CaptureError(f"tag_confidence must be a JSON object: {path}")
    summary_path = metadata.get("summary_path") or ""
    if summary_path:
        summary = inside(summary_path, root)
        if not summary.is_file() or read_capture(summary)[0].get("summary") is not True:
            raise CaptureError(f"missing or invalid summary file: {summary}")
        summary_path = str(summary)
    row = {
        "id": capture_id(canonical), "canonical_url": canonical,
        "url": metadata.get("url") or canonical, "source": source,
        "things_id": metadata.get("things_id") or "", "title": metadata.get("title") or "",
        "author": metadata.get("author") or "", "author_handle": metadata.get("author_handle") or "",
        "published": metadata.get("published") or "", "captured": captured,
        "fetched_at": fetched, "reader": metadata.get("reader") or "",
        "path": str(path), "sha256": digest(body), "note": metadata.get("note") or "",
        "summary_path": summary_path, "seen": seen, "last_seen": last_seen,
        "status": "ok", "error": "", "tags": json.dumps(tags, ensure_ascii=False),
        "tag_confidence": json.dumps(confidence, ensure_ascii=False),
        "created_at": captured, "updated_at": now(),
    }
    for key in ("url", "things_id", "title", "author", "author_handle", "published", "reader", "note"):
        if not isinstance(row[key], str):
            raise CaptureError(f"frontmatter field {key} must be text: {path}")
    if previous:
        row.update(
            seen=max(seen, previous["seen"]), last_seen=later(last_seen, previous["last_seen"]),
        )
    return row


def insert_row(database, row):
    columns = list(row)
    database.execute(
        f"INSERT INTO captures ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
        [row[key] for key in columns],
    )


def receipt(row):
    return f"{row['source']} · {line(row['title'])} · {row['path']} · seen {row['seen']}"


def write_capture(data, reader_path, root, store, note="", things_id=""):
    validate_reader(data)
    with store_lock(root, store) as database:
        existing = database.execute("SELECT * FROM captures WHERE canonical_url=?", (data["canonical_url"],)).fetchone()
        if existing:
            if not inside(existing["path"], root).is_file():
                raise CaptureError("existing row has no raw file; restore the file before another capture")
            database.execute(
                "UPDATE captures SET seen=seen+1, last_seen=?, updated_at=? WHERE id=?",
                (later(existing["last_seen"], data["fetched_at"]), now(), existing["id"]),
            )
            result = dict(existing)
            result.update(seen=existing["seen"] + 1, last_seen=later(existing["last_seen"], data["fetched_at"]))
        else:
            # If the row write fails, leave the completed files for a retry to recover.
            path = write_raw(data, reader_path, root, note, things_id)
            result = row_from_file(path, root)
            insert_row(database, result)
    return receipt(result)


def check_captures(root, store):
    if not store.is_file():
        raise CaptureError(f"capture store does not exist: {store}")
    changes = []
    with store_lock(root, store) as database:
        for previous in database.execute("SELECT * FROM captures ORDER BY canonical_url").fetchall():
            rebuilt = row_from_file(previous["path"], root, previous)
            keys = [key for key in rebuilt if key != "updated_at"]
            changed = [key for key in keys if rebuilt[key] != previous[key]]
            if not changed:
                continue
            database.execute(
                f"UPDATE captures SET {','.join(key + '=?' for key in rebuilt)} WHERE id=?",
                [*rebuilt.values(), previous["id"]],
            )
            changes.append(f"{rebuilt['source']} · {line(rebuilt['title'])} · rebuilt row · {rebuilt['path']}")
    return changes
