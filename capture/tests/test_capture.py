#!/usr/bin/env python3
"""Run the three reader fixtures through the real command entry points."""

from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
PACK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.common import CaptureError, markdown, read_capture
from lib import store as row_store

NAMES = ("x-thread", "github", "web")
NOTES = {name: f'His {name} note: keep "these words".\nSecond line.' for name in NAMES}


def rows(store):
    with sqlite3.connect(store) as database:
        database.row_factory = sqlite3.Row
        return {row["canonical_url"]: dict(row) for row in database.execute("SELECT * FROM captures")}


def snapshot(root):
    return {str(path.relative_to(root)): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


def command(tool, args, env, success=True):
    result = subprocess.run([str(Path(__file__).resolve().parent.parent / tool), *map(str, args)], env=env, text=True, capture_output=True)
    assert (result.returncode == 0) == success, result.stderr or result.stdout
    if success:
        assert not result.stderr, result.stderr
    return result.stdout


def mark(media):
    """Stand in for capture-read: its media directory carries the result's token."""
    (media / ".capture-read").write_text("fixture-media-token\n")


def extra_checks():
    """Use separate files for failures, recovery, and externally changed source bytes."""
    temporary = Path(tempfile.mkdtemp(prefix="capture-row-proof-"))
    fixtures = temporary / "reader"
    shutil.copytree((Path(__file__).resolve().parent / 'fixtures'), fixtures)
    mark(fixtures / "media")
    root, store = temporary / "raw", temporary / "captures.sqlite"
    reader = fixtures / "web.json"
    data = json.loads(reader.read_text())
    original_insert = row_store.insert_row

    def fail_after_file(database, row):
        assert Path(row["path"]).is_file(), "the raw file must exist before the row"
        raise CaptureError("fixture row failure")

    row_store.insert_row = fail_after_file
    try:
        try:
            row_store.write_capture(data, reader, root, store, "first note")
        except CaptureError as exc:
            assert str(exc) == "fixture row failure"
        else:
            raise AssertionError("expected the fixture row failure")
    finally:
        row_store.insert_row = original_insert
    assert len(rows(store)) == 0
    files_before = snapshot(root)
    row_store.write_capture(data, reader, root, store, "later note")
    assert snapshot(root) == files_before
    original = rows(store)[data["canonical_url"]]
    assert original["note"] == "first note"
    # Create a separate file with a stale frontmatter hash. Never overwrite raw bytes.
    metadata, body = read_capture(Path(original["path"]))
    changed_file = root / "web" / "external-change.md"
    with changed_file.open("x", encoding="utf-8") as stream:
        stream.write(markdown(metadata, body + "\nExternal source bytes.\n"))
    with sqlite3.connect(store) as database:
        database.execute("UPDATE captures SET path=?", (str(changed_file),))
    changed_before = snapshot(root)
    changes = row_store.check_captures(root, store)
    assert len(changes) == 1
    repaired = rows(store)[data["canonical_url"]]
    assert repaired["sha256"] == hashlib.sha256(read_capture(changed_file)[1].encode()).hexdigest()
    assert repaired["sha256"] != metadata["sha256"], "file body wins over stale frontmatter hash"
    assert snapshot(root) == changed_before
    assert row_store.check_captures(root, store) == []
    # GitHub without a supplied summary must keep summary_path empty.
    github = json.loads((fixtures / "github.json").read_text())
    github.pop("summary")
    row_store.write_capture(github, fixtures / "github.json", root, store)
    assert rows(store)[github["canonical_url"]]["summary_path"] == ""
    # Failed readers and missing local media must produce no raw file or row.
    env = {**os.environ, "CAPTURE_ROOT": str(root), "CAPTURE_STORE": str(store)}
    for status in ("needs-login", "unsupported", "error"):
        failed = dict(data, status=status, canonical_url=data["canonical_url"] + "/" + status)
        fixture = fixtures / f"{status}.json"
        fixture.write_text(json.dumps(failed))
        before = snapshot(root)
        assert command("capture-write", [fixture], env, success=False) == ""
        assert snapshot(root) == before and len(rows(store)) == 2
    missing = dict(data, canonical_url=data["canonical_url"] + "/missing")
    missing["media"] = [{"path": "missing.png", "kind": "image", "url": ""}]
    fixture = fixtures / "missing.json"
    fixture.write_text(json.dumps(missing))
    before = snapshot(root)
    command("capture-write", [fixture], env, success=False)
    assert snapshot(root) == before and len(rows(store)) == 2
    # A missing file fails the check without a false change receipt.
    with sqlite3.connect(store) as database:
        database.execute("UPDATE captures SET path=? WHERE canonical_url=?", (str(root / "missing.md"), data["canonical_url"]))
    assert command("capture-check", [], env, success=False) == ""
    print("PASS T9 recovery · file precedes row, retry keeps files, body wins, missing inputs fail")


def run(root, store, reader_dir):
    shutil.copytree((Path(__file__).resolve().parent / 'fixtures'), reader_dir)
    mark(reader_dir / "media")
    env = {**os.environ, "CAPTURE_ROOT": str(root), "CAPTURE_STORE": str(store), "PYTHONDONTWRITEBYTECODE": "1"}
    baseline = rows(store) if store.exists() else {}
    readers = {name: json.loads((reader_dir / f"{name}.json").read_text()) for name in NAMES}
    for name in NAMES:
        data = readers[name]
        output = command("capture-write", [reader_dir / f"{name}.json", "--note", NOTES[name], "--things-id", f"fixture-{name}"], env)
        assert len(output.splitlines()) == 1 and output.startswith(data["source"] + " · ")
        row = rows(store)[data["canonical_url"]]
        assert row["seen"] == baseline.get(data["canonical_url"], {}).get("seen", 0) + 1
        path = Path(row["path"])
        metadata, body = read_capture(path)
        assert metadata["note"] == NOTES[name] and row["note"] == NOTES[name]
        assert row["title"] == data["title"] and row["things_id"] == f"fixture-{name}"
        assert row["sha256"] == metadata["sha256"] == hashlib.sha256(body.encode()).hexdigest()
        assert metadata["type"] == "capture" and metadata["workspace"] == "atlas"
        assert metadata["tags"] == [] and metadata["timestamp"].endswith("-04:00")
        assert body.startswith("## Text\n\n" + data["text"])
        for media in metadata["media"]:
            target = path.parent / media["path"]
            fixture_media = (Path(__file__).resolve().parent / 'fixtures/media') / target.name
            assert target.read_bytes() == fixture_media.read_bytes()
        if name == "github":
            summary_metadata, summary_body = read_capture(Path(row["summary_path"]))
            assert summary_metadata["summary"] is True and summary_body == data["summary"]
            assert len(summary_body.splitlines()) == 10
        else:
            assert row["summary_path"] == ""
    current = rows(store)
    new_count = sum(data["canonical_url"] not in baseline for data in readers.values())
    assert len(current) == len(baseline) + new_count
    print("PASS T8 fixtures · 3 captures, 4 Markdown files, 2 images, 1 HTML file")
    before = snapshot(root)
    for name, data in readers.items():
        repeated = dict(data, fetched_at="2026-10-08T05:10:00-04:00", text="Different source words.", title="Different title")
        fixture = reader_dir / f"{name}-repeat.json"
        fixture.write_text(json.dumps(repeated))
        output = command("capture-write", [fixture, "--note", "A later note", "--things-id", "a-later-id"], env)
        row = rows(store)[data["canonical_url"]]
        assert row["seen"] == current[data["canonical_url"]]["seen"] + 1
        assert row["last_seen"] == "2026-10-08T05:10:00-04:00"
        assert row["note"] == NOTES[name] and row["title"] == data["title"]
        assert row["things_id"] == f"fixture-{name}" and len(output.splitlines()) == 1
    assert snapshot(root) == before, "repeat must preserve every raw file's bytes and time"
    assert len(rows(store)) == len(current)
    print("PASS T9 repeat · seen +1, last_seen saved, no new file, all raw bytes and times unchanged")
    assert command("capture-check", [], env) == ""
    xurl = readers["x-thread"]["canonical_url"]
    with sqlite3.connect(store) as database:
        database.execute("UPDATE captures SET sha256=?, title=?, note=?, status='error', error='wrong error', created_at='wrong time' WHERE canonical_url=?", ("0" * 64, "wrong title", "wrong note", xurl))
    change = command("capture-check", [], env)
    assert len(change.splitlines()) == 1 and "rebuilt row" in change
    repaired = rows(store)[xurl]
    assert repaired["title"] == readers["x-thread"]["title"] and repaired["note"] == NOTES["x-thread"]
    assert repaired["seen"] == current[xurl]["seen"] + 1
    assert repaired["status"] == "ok" and repaired["error"] == ""
    assert repaired["created_at"] == readers["x-thread"]["fetched_at"]
    assert command("capture-check", [], env) == "" and snapshot(root) == before
    print("PASS T9 check · 1 row rebuilt from its file, second check quiet, raw files unchanged")
    extra_checks()
    print("PASS T8/T9 · all fixture checks passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path)
    parser.add_argument("--store", type=Path)
    args = parser.parse_args()
    temporary = Path(tempfile.mkdtemp(prefix="capture-test-"))
    run((args.root or temporary / "raw").resolve(), (args.store or temporary / "captures.sqlite").resolve(), temporary / "reader")

import unittest
class CaptureContract(unittest.TestCase):
    def test_capture_contract(self):
        with tempfile.TemporaryDirectory(prefix="capture-test-") as folder:
            temporary = Path(folder)
            run((temporary / "raw").resolve(), (temporary / "captures.sqlite").resolve(), temporary / "reader")
