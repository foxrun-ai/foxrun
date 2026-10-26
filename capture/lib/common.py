"""Portable settings, hashes, and the capture frontmatter format."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path

PACK_ROOT = Path(__file__).resolve().parent.parent
SOURCES = {"x", "instagram", "youtube", "github", "reddit", "web", "pdf"}


class CaptureError(ValueError):
    pass


def settings():
    config_path = Path(os.environ.get("CAPTURE_CONFIG", (Path(__file__).resolve().parent / '../capture.config.json')))
    config = {}
    if config_path.is_file():
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            raise CaptureError("capture settings must be a JSON object")
    values = {}
    for name in ("CAPTURE_ROOT", "CAPTURE_STORE"):
        value = os.environ.get(name) or config.get(name)
        if not isinstance(value, str) or not value.strip():
            raise CaptureError(f"set {name} before writing a capture")
        values[name] = Path(value).expanduser().resolve()
    return values["CAPTURE_ROOT"], values["CAPTURE_STORE"]


def timestamp(value, field):
    if not isinstance(value, str):
        raise CaptureError(f"{field} must have a time and offset")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CaptureError(f"invalid {field}") from exc
    if "T" not in value or parsed.utcoffset() is None:
        raise CaptureError(f"{field} must have a time and offset")
    return value[:-1] + "+00:00" if value.endswith("Z") else value


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def digest(body):
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def capture_id(canonical_url):
    return hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()


def slug(value, fallback="source", limit=72):
    value = re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")
    return value[:limit].rstrip("-") or fallback


def line(value):
    return " ".join(str(value).split())


def markdown(metadata, body):
    # JSON values are valid YAML. Quoting preserves notes and source titles exactly.
    header = "\n".join(f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in metadata.items())
    return f"---\n{header}\n---\n{body}"


def scalar(value):
    value = value.strip()
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        pass
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    if value.startswith("[") and value.endswith("]"):
        return [scalar(item) for item in value[1:-1].split(",") if item.strip()]
    if value in ("null", "Null", "NULL", "~"):
        return None
    if value in ("true", "false", "True", "False"):
        return value.lower() == "true"
    if value.startswith(('"', "'", "{", "[", "|", ">", "&", "*", "!")):
        raise CaptureError("unsupported frontmatter value; use JSON-valued YAML")
    return value


def read_capture(path):
    # Decode bytes directly; newline conversion would change the body hash.
    raw = path.read_bytes().decode("utf-8")
    if not raw.startswith("---\n"):
        raise CaptureError(f"missing frontmatter: {path}")
    header, separator, body = raw[4:].partition("\n---\n")
    if not separator:
        raise CaptureError(f"unclosed frontmatter: {path}")
    metadata = {}
    active = None
    for entry in header.splitlines():
        if not entry.strip() or entry.lstrip().startswith("#"):
            continue
        if entry.startswith(" ") or entry.startswith("- "):
            if active is None:
                raise CaptureError(f"invalid frontmatter block: {path}")
            content = entry.strip()
            if content.startswith("- "):
                if metadata[active] is None:
                    metadata[active] = []
                if not isinstance(metadata[active], list):
                    raise CaptureError(f"invalid frontmatter list: {path}")
                metadata[active].append(scalar(content[2:]))
            else:
                key, sep, value = content.partition(":")
                if not sep or not re.fullmatch(r"[A-Za-z0-9_-]+", key):
                    raise CaptureError(f"unsupported frontmatter block: {path}")
                if metadata[active] is None:
                    metadata[active] = {}
                if not isinstance(metadata[active], dict):
                    raise CaptureError(f"invalid frontmatter map: {path}")
                metadata[active][key] = scalar(value)
            continue
        key, sep, value = entry.partition(":")
        if not sep or not re.fullmatch(r"[A-Za-z0-9_]+", key) or key in metadata:
            raise CaptureError(f"invalid frontmatter field: {path}")
        metadata[key] = scalar(value)
        active = key if metadata[key] is None else None
    return metadata, body


def inside(path, root):
    path = Path(path).resolve()
    if not path.is_relative_to(root.resolve()):
        raise CaptureError(f"capture path is outside CAPTURE_ROOT: {path}")
    return path


def create_file(path, content):
    """Create once. Keep any failed file for inspection; never remove or replace it."""
    with path.open("x", encoding="utf-8", newline="") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
