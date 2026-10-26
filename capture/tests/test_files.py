#!/usr/bin/env python3
"""File contract proof using only hand-made reader fixtures."""

from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
PACK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.common import CaptureError, digest, read_capture
from lib.files import write_raw

TOKEN = "fixture-media-token"


def mark(media):
    """Stand in for capture-read: its media directory carries the result's token."""
    (media / ".capture-read").write_text(TOKEN + "\n")


def run():
    run_root = Path(tempfile.mkdtemp(prefix="capture-files-"))
    fixtures = run_root / "reader"
    shutil.copytree((Path(__file__).resolve().parent / 'fixtures'), fixtures)
    mark(fixtures / "media")
    root = run_root / "raw"
    note = 'His note: keep "these words".\nAnd this second line.'
    paths = {}
    for name in ("x-thread", "github", "web"):
        reader = fixtures / f"{name}.json"
        data = json.loads(reader.read_text())
        path = write_raw(data, reader, root, note, "fixture-things-id")
        metadata, body = read_capture(path)
        assert metadata["type"] == "capture" and metadata["workspace"] == "atlas"
        assert metadata["note"] == note and metadata["title"] == data["title"]
        assert metadata["sha256"] == digest(body)
        assert metadata["timestamp"] == data["fetched_at"]
        assert metadata["tags"] == [] and metadata["untrusted"] is True
        assert body.startswith("## Text\n\n" + data["text"])
        for item in data["media"]:
            original = fixtures / item["path"]
            copy = path.parent / "media" / path.stem / original.name
            assert original.is_file(), "reader media must be copied, never moved"
            assert copy.read_bytes() == original.read_bytes(), "the copy must match its source"
        saved = path.read_bytes()
        assert write_raw(data, reader, root, "a later note") == path
        assert path.read_bytes() == saved, "recovery must keep raw bytes"
        paths[name] = path
    assert paths["x-thread"].name == "2026-10-01-atlas-demo-10001.md"
    _, xbody = read_capture(paths["x-thread"])
    assert xbody.count("![[media/") == 2
    assert len(list((paths["x-thread"].parent / "media" / paths["x-thread"].stem).glob("*.png"))) == 2
    summary = paths["github"].with_name(paths["github"].stem + "-summary.md")
    metadata, body = read_capture(summary)
    assert metadata["summary"] is True and len(body.splitlines()) == 10
    assert metadata["sha256"] == digest(body)
    assert "[article.html](media/" in read_capture(paths["web"])[1]
    data = json.loads((fixtures / "github.json").read_text())
    data["canonical_url"] += "/another"
    data.pop("summary")
    collision = write_raw(data, fixtures / "github.json", root)
    assert collision.stem.endswith("-v2")
    assert read_capture(collision)[0]["summary_path"] == ""
    data["canonical_url"] += "/transcript"
    data["source"] = "youtube"
    data["transcript"] = "Exact transcript.\nSecond line."
    data["comments"] = [{"author": "Reader", "text": "Exact comment.", "score": 3}]
    data["ocr"] = "Image text.\nSecond image line."
    extra = write_raw(data, fixtures / "github.json", root)
    extra_body = read_capture(extra)[1]
    assert "## Transcript\n\n" + data["transcript"] in extra_body
    assert "## Comments\n\n### Reader\n\nExact comment." in extra_body
    assert "> [!note]- OCR\n> Image text.\n> Second image line." in extra_body
    print("PASS T9 files · 3 fixtures, 2 images, HTML, GitHub summary, immutable recovery, version suffix")
    outside_checks(run_root)
    return run_root


def refused(data, reader, root, words, outside=None):
    before = sorted(str(item) for item in root.rglob("*") if not item.is_dir()) if root.exists() else []
    try:
        write_raw(data, reader, root)
    except CaptureError as exc:
        assert words in str(exc), (words, str(exc))
        for secret in ("synthetic-pass", "synthetic-token"):
            assert secret not in str(exc), "an error must never echo a credential"
    else:
        raise AssertionError(f"expected a refusal: {words}")
    after = sorted(str(item) for item in root.rglob("*") if not item.is_dir()) if root.exists() else []
    assert after == before, "a refused capture writes nothing"
    if outside is not None:
        assert outside.read_bytes() == b"synthetic local file\n", "the outside file must stay in place"


def outside_checks(run_root):
    """T750 F01 and F06: reader JSON cannot pull outside files or keep credentials."""
    fixtures = run_root / "outside-reader"
    shutil.copytree((Path(__file__).resolve().parent / 'fixtures'), fixtures)
    media = fixtures / "media"
    mark(media)
    root = run_root / "outside-raw"
    home = run_root / "home"
    home.mkdir()
    outside = home / "config.secret"
    outside.write_bytes(b"synthetic local file\n")
    base = json.loads((fixtures / "x-thread.json").read_text())
    reader = fixtures / "x-thread.json"

    def case(number, **changes):
        data = json.loads(json.dumps(base))
        data["canonical_url"] = f"https://x.com/atlas_demo/status/{20000 + number}"
        data["id"] = str(20000 + number)
        data.update(changes)
        return data

    # The repro: an absolute path to an unrelated file. Before T750 it was moved into raw.
    refused(case(1, media=[{"url": "", "path": str(outside), "kind": "image"}]), reader, root,
            "capture-read directory", outside)
    refused(case(2, media=[{"url": "", "path": "media/../../home/config.secret", "kind": "image"}]), reader, root,
            "capture-read directory", outside)
    (media / "link.png").symlink_to(outside)
    refused(case(3, media=[{"url": "", "path": "media/link.png", "kind": "image"}]), reader, root, "link", outside)
    os.link(outside, media / "hard.png")
    refused(case(4, media=[{"url": "", "path": "media/hard.png", "kind": "image"}]), reader, root, "one link", outside)
    refused(case(5, media=[{"url": "", "path": "media/.capture-read", "kind": "image"}]), reader, root,
            "capture-read directory")
    refused(case(6, media_token="another-token"), reader, root, "does not belong")
    without = case(7)
    without.pop("media_dir")
    refused(without, reader, root, "media_dir")
    (fixtures / "linked-media").symlink_to(media)
    refused(case(8, media_dir="linked-media"), reader, root, "must not be a link")
    unmarked = fixtures / "unmarked"
    unmarked.mkdir()
    shutil.copy(media / "library.png", unmarked / "library.png")
    refused(case(9, media_dir="unmarked", media=[{"url": "", "path": "unmarked/library.png", "kind": "image"}]),
            reader, root, "no capture-read marker")
    # F06: a hand-made reader JSON cannot store a credential in a URL.
    refused(case(10, url="https://user:synthetic-pass@x.com/atlas_demo/status/1"), reader, root, "carries a credential")
    refused(case(11, canonical_url="https://example.org/a?token=synthetic-token"), reader, root, "carries a credential")
    refused(case(12, media=[{"url": "https://cdn.example/a.png?X-Amz-Signature=synthetic-token",
                             "path": "media/library.png", "kind": "image"}]), reader, root, "carries a credential")
    redacted = write_raw(case(13, url="https://example.org/a?token=[REDACTED]"), reader, root)
    assert read_capture(redacted)[0]["url"] == "https://example.org/a?token=[REDACTED]"
    assert (media / "library.png").is_file() and outside.is_file()
    print("PASS T750 F01/F06 writer · outside, traversal, links, hard links, marker, token, and credential URLs refused")


if __name__ == "__main__":
    run()

import unittest
class FileContract(unittest.TestCase):
    def test_file_contract(self):
        path = run()
        shutil.rmtree(path)
