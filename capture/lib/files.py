"""Immutable raw files from the reader JSON contract."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from urllib.parse import urlsplit

from readers.common import MEDIA_MARKER, carries_secret

from .common import (
    CaptureError, SOURCES, capture_id, create_file, digest, inside,
    markdown, read_capture, slug, timestamp,
)


def text_field(data, key):
    value = data.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise CaptureError(f"reader field {key} must be text")
    return value


def validate_reader(data):
    if not isinstance(data, dict):
        raise CaptureError("reader JSON must be an object")
    if data.get("status") != "ok":
        raise CaptureError(f"reader status {data.get('status', 'missing')}: {data.get('error') or 'no raw file written'}")
    if data.get("source") not in SOURCES:
        raise CaptureError("unsupported reader source")
    for key in ("url", "canonical_url"):
        value = text_field(data, key)
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise CaptureError(f"reader field {key} must be a public URL")
        # Never echo the value: it may hold a credential.
        if carries_secret(value):
            raise CaptureError(f"reader field {key} carries a credential; read the link again with capture-read")
    timestamp(data.get("fetched_at"), "fetched_at")
    for key in ("id", "title", "author", "author_handle", "published", "reader", "text", "transcript", "summary", "ocr"):
        text_field(data, key)
    for key in ("media", "comments"):
        if data.get(key) is not None and not isinstance(data[key], list):
            raise CaptureError(f"reader field {key} must be a list")
    for item in data.get("media") or []:
        if isinstance(item, dict) and isinstance(item.get("url"), str) and carries_secret(item["url"]):
            raise CaptureError("reader media url carries a credential; read the link again with capture-read")
    for comment in data.get("comments") or []:
        if not isinstance(comment, dict):
            raise CaptureError("reader comment must be an object")
        text_field(comment, "author")
        text_field(comment, "text")
    for key in ("metrics", "repo"):
        if data.get(key) is not None and not isinstance(data[key], dict):
            raise CaptureError(f"reader field {key} must be an object")


def filename(data):
    date = text_field(data, "published") or data["fetched_at"]
    try:
        # A published date alone is valid reader input; frontmatter keeps it verbatim.
        from datetime import date as Date
        Date.fromisoformat(date[:10])
    except ValueError as exc:
        raise CaptureError("invalid published date") from exc
    author = data.get("author_handle") or data.get("author") or data.get("title") or urlsplit(data["canonical_url"]).hostname
    identity = data.get("id") or capture_id(data["canonical_url"])[:16]
    return f"{date[:10]}-{slug(author)}-{slug(identity, 'source', 64)}"


def select_path(data, root):
    folder = inside(root / data["source"], root)
    folder.mkdir(parents=True, exist_ok=True)
    # Recover a completed file after an interrupted row write, without another file.
    for candidate in sorted(folder.glob("*.md")):
        try:
            metadata, _ = read_capture(candidate)
        except (CaptureError, UnicodeError):
            continue
        if metadata.get("summary") is not True and metadata.get("location") == data["canonical_url"]:
            return inside(candidate, root), True
    base = filename(data)
    version = 1
    while True:
        stem = base if version == 1 else f"{base}-v{version}"
        path = folder / f"{stem}.md"
        if not path.exists() and not (folder / f"{stem}-summary.md").exists() and not (folder / "media" / stem).exists():
            return inside(path, root), False
        version += 1


def owned_file(info):
    return stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.getuid()


def reader_path_of(value, reader_path):
    path = Path(value).expanduser()
    return path if path.is_absolute() else reader_path.parent / path


def media_directory(data, reader_path, root):
    """Return the directory capture-read made for this result, or refuse."""
    value, token = data.get("media_dir"), data.get("media_token")
    if not isinstance(value, str) or not value or not isinstance(token, str) or not token:
        raise CaptureError("reader media needs the media_dir and media_token that capture-read writes")
    lexical = reader_path_of(value, reader_path)
    if lexical.is_symlink():
        raise CaptureError("reader media directory must not be a link")
    directory = lexical.resolve()
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise CaptureError("reader media directory must be a directory that capture-read made")
    if directory.is_relative_to(root):
        raise CaptureError("reader media must be outside CAPTURE_ROOT")
    try:
        descriptor = os.open(directory / MEDIA_MARKER, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise CaptureError("reader media directory has no capture-read marker") from exc
    with os.fdopen(descriptor, "rb") as marker:
        if not owned_file(os.fstat(marker.fileno())) or marker.read(256).decode("ascii", "replace").strip() != token:
            raise CaptureError("reader media directory does not belong to this reader result")
    return directory


def plan_media(data, reader_path, path, root):
    result = []
    names = set()
    items = data.get("media") or []
    root = Path(root).resolve()
    directory = media_directory(data, reader_path, root) if items else None
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not item["path"]:
            raise CaptureError("reader media needs a saved local path")
        lexical = reader_path_of(item["path"], reader_path)
        # Only files the reader saved in its own directory: no links, no outside paths.
        if lexical.is_symlink():
            raise CaptureError("reader media must not be a link")
        source = lexical.resolve()
        if source.parent != directory or source.name.startswith("."):
            raise CaptureError("reader media must sit in its capture-read directory")
        try:
            info = source.lstat()
        except OSError as exc:
            raise CaptureError(f"missing reader media: {source.name}") from exc
        if not owned_file(info):
            raise CaptureError("reader media must be a regular file with one link")
        # Preserve extensions but remove link syntax and unsafe path characters.
        extension = source.suffix.lower()
        if not extension[1:].isalnum():
            extension = ""
        base = slug(source.stem, f"media-{index}")
        name = f"{base}{extension}"
        number = 2
        while name in names:
            name = f"{base}-{number}{extension}"
            number += 1
        names.add(name)
        target = inside(path.parent / "media" / path.stem / name, root)
        result.append({"original": source, "identity": (info.st_dev, info.st_ino), "target": target,
                       "url": text_field(item, "url"), "kind": text_field(item, "kind")})
    return result


def copy_media(item):
    """Copy one planned file and check the copy. The reader's file stays in place."""
    descriptor = os.open(item["original"], os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as source:
        info = os.fstat(source.fileno())
        if not owned_file(info) or (info.st_dev, info.st_ino) != item["identity"]:
            raise CaptureError("reader media changed after its check")
        expected = hashlib.sha256()
        with item["target"].open("xb") as target:
            try:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    expected.update(block)
                    target.write(block)
            except BaseException:
                item["target"].unlink(missing_ok=True)
                raise
    if hashlib.sha256(item["target"].read_bytes()).hexdigest() != expected.hexdigest():
        item["target"].unlink(missing_ok=True)
        raise CaptureError(f"media copy does not match its source: {item['target'].name}")


def body_text(data, media, path):
    parts = ["## Text\n\n" + text_field(data, "text")]
    if data.get("transcript"):
        parts.append("## Transcript\n\n" + data["transcript"])
    if data.get("comments"):
        comments = []
        for comment in data["comments"]:
            author = text_field(comment, "author") or "Unknown author"
            comments.append(f"### {author}\n\n{text_field(comment, 'text')}")
        parts.append("## Comments\n\n" + "\n\n".join(comments))
    if media:
        links = []
        for item in media:
            relative = item["target"].relative_to(path.parent).as_posix()
            if item["kind"] == "image":
                links.append(f"![[{relative}]]")
            else:
                links.append(f"[{item['target'].name}]({relative})")
        parts.append("## Media\n\n" + "\n".join(links))
    if data.get("ocr"):
        ocr = "\n".join("> " + entry for entry in data["ocr"].split("\n"))
        parts.append("> [!note]- OCR\n" + ocr)
    return "\n\n".join(parts) + "\n"


def write_raw(data, reader_path, root, note="", things_id=""):
    validate_reader(data)
    path, recovered = select_path(data, root)
    if recovered:
        return path
    media = plan_media(data, reader_path, path, root)
    body = body_text(data, media, path)
    fetched = timestamp(data["fetched_at"], "fetched_at")
    summary = text_field(data, "summary") if data["source"] == "github" else ""
    summary_path = path.with_name(path.stem + "-summary.md") if summary.strip() else None
    metadata = {
        "type": "capture", "workspace": "atlas", "timestamp": fetched,
        "kind": data["source"], "location": data["canonical_url"],
        "title": text_field(data, "title"), "author": text_field(data, "author"),
        "author_handle": text_field(data, "author_handle"),
        "published": text_field(data, "published"), "captured": fetched,
        "note": note, "things_id": things_id, "reader": text_field(data, "reader"),
        "sha256": digest(body), "seen": 1, "last_seen": fetched,
        "metrics": data.get("metrics") or {},
        "summary": next((entry for entry in summary.splitlines() if entry.strip()), ""),
        "untrusted": True, "safety_flags": [], "tags": [],
        "id": capture_id(data["canonical_url"]), "url": data["url"],
        "source": data["source"], "category": "", "fetched_at": fetched,
        "summary_path": str(summary_path) if summary_path else "",
        "media": [{"url": item["url"], "path": item["target"].relative_to(path.parent).as_posix(), "kind": item["kind"]} for item in media],
    }
    if data["source"] == "github":
        metadata["repo"] = data.get("repo") or {}
        if "tree" in data:
            metadata["tree"] = data["tree"]
    # All inputs are checked before a copy. The caller serializes writers.
    copied = []
    try:
        for item in media:
            item["target"].parent.mkdir(parents=True, exist_ok=True)
            if item["target"].exists():
                raise CaptureError(f"media already exists: {item['target']}")
            copy_media(item)
            copied.append(item["target"])
    except BaseException:
        # Remove only the unreferenced copies this call made; no raw file exists yet.
        for target in copied:
            target.unlink(missing_ok=True)
        raise
    if summary_path:
        summary_metadata = dict(metadata)
        summary_metadata.update(summary=True, sha256=digest(summary), summary_path="")
        create_file(summary_path, markdown(summary_metadata, summary))
    create_file(path, markdown(metadata, body))
    return path
