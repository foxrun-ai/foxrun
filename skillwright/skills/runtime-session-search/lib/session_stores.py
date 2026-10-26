"""The native session store readers for runtime-session-search.

Claude JSONL transcripts, Codex rollouts, and Hermes state.db files, read-only.
Every path comes from the caller: a stores root (the person's home folder by
default) and the runtime's own folders under it. Standard library only.

These readers are a copy of the hosted-session skill's adapters, so this skill
works on a shelf that has no herdr skill. Room labels come from a room map the
caller passes; with no map every hit is labeled home.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import shlex
import shutil
import sqlite3
import subprocess
import time
from typing import BinaryIO, Callable, Mapping, Sequence


TESTED_MEMEX_VERSION = "0.11.6"


DEFAULT_ROOM_LABEL = "⌂ home"


MAX_READ_BYTES = 8192


MAX_READ_LINES = 120


FIND_DEFAULT_SINCE = timedelta(days=14)


FIND_ADAPTER_BUDGET = 2.0


FIND_LIMIT = 15


FIND_TITLE_CHARS = 96


FIND_SNIPPET_CHARS = 120


MAX_TRANSCRIPT_SCAN_BYTES = 512 * 1024


UUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


UUID_IN_TEXT_PATTERN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


ID_PREFIX_PATTERN = re.compile(r"^[0-9a-fA-F][0-9a-fA-F-]{7,}$")


HERMES_ID_PATTERN = re.compile(r"^\d{8}_\d{6}_[0-9a-fA-F]+$")


class StoreError(RuntimeError):
    """A user-correctable store error."""

    def __init__(self, message: str, details: Mapping[str, object] | None = None) -> None:
        self.details = dict(details or {})
        super().__init__(message)


def _expand_anchor(anchor: str, home: Path) -> Path:
    if anchor == "~":
        return home.resolve()
    if anchor.startswith("~/"):
        return (home / anchor[2:]).resolve()
    return Path(anchor).resolve()


def memex_capability(
    *,
    executable: str | None = None,
    which: Callable[[str], str | None] = shutil.which,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    budget_seconds: float = 2.0,
) -> dict[str, object]:
    command = executable or which("memex")
    fallback = {"backend": "builtin", "memex": False}
    if not command:
        return {**fallback, "reason": "memex_not_found"}
    deadline = time.monotonic() + budget_seconds

    def remaining() -> float:
        value = deadline - time.monotonic()
        if value <= 0:
            raise subprocess.TimeoutExpired([command], budget_seconds)
        return value

    try:
        version_result = runner(
            [command, "--version"],
            capture_output=True,
            text=True,
            timeout=remaining(),
            check=False,
        )
        version_text = (version_result.stdout or version_result.stderr).strip()
        version = version_text.rsplit(" ", 1)[-1]
        if version_result.returncode != 0 or version != TESTED_MEMEX_VERSION:
            return {
                **fallback,
                "reason": "memex_version_mismatch",
                "found_version": version or None,
                "required_version": TESTED_MEMEX_VERSION,
            }
        help_result = runner(
            [command, "sessions", "--help"],
            capture_output=True,
            text=True,
            timeout=remaining(),
            check=False,
        )
        help_text = f"{help_result.stdout}\n{help_result.stderr}"
        required_flags = ("--cwd", "--limit", "--source")
        if help_result.returncode != 0 or any(flag not in help_text for flag in required_flags):
            return {**fallback, "reason": "memex_sessions_capability_missing"}
        search_help = runner(
            [command, "search", "--help"],
            capture_output=True,
            text=True,
            timeout=remaining(),
            check=False,
        )
        search_text = f"{search_help.stdout}\n{search_help.stderr}"
        search_flags = ("--source", "--since", "--limit", "--fields")
        if search_help.returncode != 0 or any(
            flag not in search_text for flag in search_flags
        ):
            return {**fallback, "reason": "memex_search_capability_missing"}
    except (OSError, subprocess.TimeoutExpired):
        return {**fallback, "reason": "memex_check_failed"}
    return {
        "backend": "memex",
        "memex": True,
        "version": TESTED_MEMEX_VERSION,
        "executable": command,
    }


def _content_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for item in value:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            text = item.get("text") or item.get("content")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts)


def _query_matches(query: str, *values: object) -> bool:
    terms = [term.casefold() for term in re.findall(r"\w+", query)]
    haystack = "\n".join(str(value) for value in values if value is not None).casefold()
    return not terms or all(term in haystack for term in terms)


def _is_session_id_query(query: str) -> bool:
    value = query.strip()
    return bool(
        UUID_PATTERN.fullmatch(value)
        or ID_PREFIX_PATTERN.fullmatch(value)
        or HERMES_ID_PATTERN.fullmatch(value)
    )


def _session_id_match_kind(query: str, session_id: object) -> str | None:
    if not _is_session_id_query(query) or not isinstance(session_id, str):
        return None
    candidate = session_id.casefold()
    requested = query.strip().casefold()
    if candidate == requested:
        return "id_exact"
    if candidate.startswith(requested):
        return "id_prefix"
    return None


def _ellipsize(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    if limit <= 1:
        return "…"[:limit]
    return value[: limit - 1] + "…"


def _snippet(
    query: str, texts: Sequence[str], limit: int = FIND_SNIPPET_CHARS
) -> str:
    terms = [term.casefold() for term in re.findall(r"\w+", query)]
    selected = ""
    for text in texts:
        folded = text.casefold()
        if text and terms and all(term in folded for term in terms):
            selected = text
            break
    for text in texts:
        if selected:
            break
        if text and (not terms or any(term in text.casefold() for term in terms)):
            selected = text
            break
    if not selected:
        selected = next((text for text in reversed(texts) if text), "")
    compact = re.sub(r"\s+", " ", selected).strip()
    return _ellipsize(compact, limit)


def _when_sort_key(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str) or not value:
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _when_text(value: object) -> str | None:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), timezone.utc).isoformat()
    return value if isinstance(value, str) and value else None


def _since_cutoff(value: str | None, now: datetime) -> tuple[str | None, float]:
    default_days = int(FIND_DEFAULT_SINCE.total_seconds() // 86400)
    selected = value or f"{default_days}d"
    if selected == "all":
        return None, 0.0
    try:
        duration = parse_duration(selected)
    except StoreError:
        timestamp = _when_sort_key(selected)
        if timestamp <= 0:
            raise StoreError("since must be an ISO timestamp, duration, or all")
        return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(), timestamp
    cutoff = now - duration
    return cutoff.isoformat(), cutoff.timestamp()


def _jsonl_records(
    path: Path, max_bytes: int = MAX_TRANSCRIPT_SCAN_BYTES
) -> Sequence[dict[str, object]]:
    records: list[dict[str, object]] = []

    def parse(handle: BinaryIO, byte_budget: int) -> None:
        consumed = 0
        while consumed < byte_budget:
            line = handle.readline(byte_budget - consumed + 1)
            if not line:
                break
            consumed += len(line)
            if consumed > byte_budget:
                break
            try:
                record = json.loads(line.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)

    try:
        with path.open("rb") as handle:
            size = path.stat().st_size
            if size <= max_bytes:
                parse(handle, max_bytes)
            else:
                head_bytes = max_bytes // 2
                tail_bytes = max_bytes - head_bytes
                parse(handle, head_bytes)
                handle.seek(max(0, size - tail_bytes))
                handle.readline()
                parse(handle, tail_bytes)
    except OSError:
        return []
    return records


def _newest_paths(paths: Sequence[Path], since_epoch: float) -> list[Path]:
    dated: list[tuple[float, Path]] = []
    for path in paths:
        try:
            modified = path.stat().st_mtime
        except OSError:
            continue
        if modified >= since_epoch:
            dated.append((modified, path))
    dated.sort(key=lambda item: item[0], reverse=True)
    return [path for _, path in dated]


def _filename_session_id(path: Path, source: str) -> str:
    if source == "claude":
        return path.stem
    match = UUID_IN_TEXT_PATTERN.search(path.stem)
    return match.group(0) if match else ""


def _bounded_session_metadata(
    path: Path, source: str, *, max_bytes: int = MAX_TRANSCRIPT_SCAN_BYTES
) -> dict[str, object]:
    session_id: str | None = _filename_session_id(path, source) or None
    cwd: str | None = None
    title: str | None = None
    first_user: str | None = None
    when: object = None
    for record in _jsonl_records(path, max_bytes=max_bytes):
        payload = record.get("payload")
        if source == "codex" and isinstance(payload, dict):
            if record.get("type") == "session_meta":
                session_id = str(payload.get("id") or session_id)
                cwd = str(payload["cwd"]) if isinstance(payload.get("cwd"), str) else cwd
                when = payload.get("timestamp") or when
            elif record.get("type") == "event_msg":
                message = payload.get("message")
                if payload.get("type") in {"user_message", "user_prompt"} and isinstance(message, str):
                    first_user = first_user or message.splitlines()[0].strip()
        elif source == "claude":
            record_session_id = record.get("sessionId") or record.get("session_id")
            if isinstance(record_session_id, str):
                session_id = record_session_id
            custom = record.get("customTitle") or record.get("custom-title")
            if record.get("type") == "custom-title":
                custom = custom or record.get("title")
            if isinstance(custom, str) and custom.strip():
                title = custom.strip()
            if isinstance(record.get("cwd"), str):
                cwd = str(record["cwd"])
            when = record.get("timestamp") or when
            message = record.get("message")
            if isinstance(message, dict) and message.get("role") == "user":
                text = _content_text(message.get("content"))
                if text and first_user is None:
                    first_user = text.splitlines()[0].strip()
    return {
        "session_id": session_id,
        "cwd": cwd,
        "title": title or first_user,
        "when": when,
    }


def room_label_for_cwd(cwd: str | None, room_map: Mapping[str, object], home: Path) -> str | None:
    if not cwd:
        return None
    rooms = room_map.get("rooms")
    if not isinstance(rooms, dict):
        return None
    path = Path(cwd).expanduser().resolve()
    candidates: list[tuple[int, str]] = []
    for label, value in rooms.items():
        if label == DEFAULT_ROOM_LABEL or not isinstance(value, dict):
            continue
        anchor = value.get("anchor")
        if not isinstance(anchor, str):
            continue
        expanded = _expand_anchor(anchor, home)
        if path == expanded or expanded in path.parents:
            candidates.append((len(expanded.parts), str(label)))
    return max(candidates)[1] if candidates else DEFAULT_ROOM_LABEL


def _hit(
    *,
    store: str,
    session_id: str,
    title: str | None,
    when: object,
    cwd: str | None,
    room: str | None,
    pane_id: str | None,
    live: bool | None,
    surfaces: Sequence[str],
    command: str,
    snippet: str,
) -> dict[str, object]:
    return {
        "store": store,
        "session_id": session_id,
        "title": _ellipsize(title, FIND_TITLE_CHARS) if title is not None else None,
        "when": _when_text(when),
        "cwd": cwd,
        "room": room,
        "pane_id": pane_id,
        "live": live,
        "surfaces": list(surfaces),
        "attach_or_resume_cmd": command,
        "snippet": _ellipsize(snippet, FIND_SNIPPET_CHARS),
    }


def claude_jsonl_hits(
    projects_root: Path,
    query: str,
    room_map: Mapping[str, object],
    home: Path,
    paths: Sequence[Path] | None = None,
    *,
    since_epoch: float = 0.0,
    limit: int = FIND_LIMIT,
    budget_seconds: float = FIND_ADAPTER_BUDGET,
    notes: list[str] | None = None,
) -> list[dict[str, object]]:
    files = _newest_paths(
        list(paths) if paths is not None else list(projects_root.glob("*/*.jsonl")),
        since_epoch,
    )
    hits: list[dict[str, object]] = []
    deadline = time.monotonic() + budget_seconds
    for path in files:
        if time.monotonic() >= deadline:
            if notes is not None:
                notes.append("claude_budget_exceeded; adapter stopped")
            break
        if len(hits) >= limit:
            break
        title: str | None = None
        first_user: str | None = None
        cwd: str | None = None
        when: object = None
        texts: list[str] = []
        session_id = _filename_session_id(path, "claude")
        for record in _jsonl_records(path):
            record_type = record.get("type")
            record_session_id = record.get("sessionId") or record.get("session_id")
            if isinstance(record_session_id, str):
                session_id = record_session_id
            custom = record.get("customTitle") or record.get("custom-title")
            if record_type == "custom-title":
                custom = custom or record.get("title")
            if isinstance(custom, str) and custom.strip():
                title = custom.strip()
            if isinstance(record.get("cwd"), str):
                cwd = str(record["cwd"])
            if record.get("timestamp") is not None:
                when = record.get("timestamp")
            message = record.get("message")
            if isinstance(message, dict):
                text = _content_text(message.get("content"))
                role = message.get("role")
                if text:
                    texts.append(text)
                    if role == "user" and first_user is None:
                        first_user = text.splitlines()[0].strip()
        title = title or first_user or session_id
        if not _query_matches(query, session_id, title, cwd, *texts):
            continue
        hits.append(
            _hit(
                store="claude",
                session_id=session_id,
                title=title,
                when=when,
                cwd=cwd,
                room=room_label_for_cwd(cwd, room_map, home),
                pane_id=None,
                live=False,
                surfaces=("claude",),
                command=f"claude --resume {shlex.quote(session_id)}",
                snippet=_snippet(query, texts),
            )
        )
    return hits


def codex_rollout_hits(
    sessions_root: Path,
    query: str,
    room_map: Mapping[str, object],
    home: Path,
    paths: Sequence[Path] | None = None,
    *,
    since_epoch: float = 0.0,
    limit: int = FIND_LIMIT,
    budget_seconds: float = FIND_ADAPTER_BUDGET,
    notes: list[str] | None = None,
) -> list[dict[str, object]]:
    files = _newest_paths(
        list(paths) if paths is not None else list(sessions_root.glob("**/rollout-*.jsonl")),
        since_epoch,
    )
    hits: list[dict[str, object]] = []
    deadline = time.monotonic() + budget_seconds
    for path in files:
        if time.monotonic() >= deadline:
            if notes is not None:
                notes.append("codex_budget_exceeded; adapter stopped")
            break
        if len(hits) >= limit:
            break
        session_id: str | None = _filename_session_id(path, "codex") or None
        cwd: str | None = None
        when: object = None
        first_prompt: str | None = None
        texts: list[str] = []
        for record in _jsonl_records(path):
            payload = record.get("payload")
            if not isinstance(payload, dict):
                continue
            if record.get("type") == "session_meta":
                if isinstance(payload.get("id"), str):
                    session_id = str(payload["id"])
                if isinstance(payload.get("cwd"), str):
                    cwd = str(payload["cwd"])
                when = payload.get("timestamp") or when
            elif record.get("type") == "event_msg":
                text = payload.get("last_agent_message")
                if isinstance(text, str):
                    texts.append(text)
                message = payload.get("message")
                if payload.get("type") in {"user_message", "user_prompt"} and isinstance(message, str):
                    first_prompt = first_prompt or message.splitlines()[0].strip()
                    texts.append(message)
            elif record.get("type") == "response_item":
                text = _content_text(payload.get("content"))
                if text:
                    texts.append(text)
                    if payload.get("role") == "user" and first_prompt is None:
                        first_prompt = text.splitlines()[0].strip()
        if not session_id:
            continue
        title = first_prompt or (Path(cwd).name if cwd else session_id)
        if not _query_matches(query, session_id, title, cwd, *texts):
            continue
        hits.append(
            _hit(
                store="codex",
                session_id=session_id,
                title=title,
                when=when,
                cwd=cwd,
                room=room_label_for_cwd(cwd, room_map, home),
                pane_id=None,
                live=False,
                surfaces=("codex",),
                command=f"codex resume {shlex.quote(session_id)}",
                snippet=_snippet(query, texts),
            )
        )
    return hits


def transcript_id_hits(
    root: Path,
    source: str,
    query: str,
    room_map: Mapping[str, object],
    home: Path,
    *,
    since_epoch: float = 0.0,
    limit: int = FIND_LIMIT,
    budget_seconds: float = FIND_ADAPTER_BUDGET,
    notes: list[str] | None = None,
) -> list[dict[str, object]]:
    if source == "claude":
        paths = list(root.glob("*/*.jsonl"))
    elif source == "codex":
        paths = list(root.glob("**/rollout-*.jsonl"))
    else:
        raise StoreError(f"unsupported transcript source: {source}")
    files = _newest_paths(paths, since_epoch)
    deadline = time.monotonic() + budget_seconds
    direct = [
        path
        for path in files
        if _session_id_match_kind(query, _filename_session_id(path, source))
    ]
    candidates = direct or files
    hits: list[dict[str, object]] = []
    seen: set[str] = set()
    for path in candidates:
        if time.monotonic() >= deadline:
            if notes is not None:
                notes.append(f"{source}_id_budget_exceeded; adapter stopped")
            break
        metadata = _bounded_session_metadata(path, source, max_bytes=64 * 1024)
        filename_id = _filename_session_id(path, source)
        metadata_id = metadata.get("session_id")
        session_id = (
            str(metadata_id)
            if _session_id_match_kind(query, metadata_id)
            else filename_id
            if _session_id_match_kind(query, filename_id)
            else None
        )
        if not session_id or session_id in seen:
            continue
        seen.add(session_id)
        cwd = metadata.get("cwd") if isinstance(metadata.get("cwd"), str) else None
        title = metadata.get("title")
        hits.append(
            _hit(
                store=source,
                session_id=session_id,
                title=str(title or session_id),
                when=metadata.get("when"),
                cwd=cwd,
                room=room_label_for_cwd(cwd, room_map, home),
                pane_id=None,
                live=False,
                surfaces=(source,),
                command=(
                    f"claude --resume {shlex.quote(session_id)}"
                    if source == "claude"
                    else f"codex resume {shlex.quote(session_id)}"
                ),
                snippet="",
            )
        )
        if len(hits) >= limit:
            break
    return hits


def parse_hermes_session_ids(text: str) -> set[str]:
    identifiers: set[str] = set()
    for line in text.splitlines():
        fields = line.split()
        if fields:
            candidate = fields[-1]
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{5,}", candidate):
                identifiers.add(candidate)
    return identifiers


def hermes_cli_id_hits(
    session_list_text: str,
    query: str,
) -> list[dict[str, object]]:
    hits = []
    for session_id in sorted(parse_hermes_session_ids(session_list_text)):
        if not _session_id_match_kind(query, session_id):
            continue
        hits.append(
            _hit(
                store="hermes",
                session_id=session_id,
                title=session_id,
                when=None,
                cwd=None,
                room=None,
                pane_id=None,
                live=None,
                surfaces=("hermes",),
                command=f"hermes --resume {shlex.quote(session_id)}",
                snippet="",
            )
        )
    return hits


def hermes_store_hits(
    database: Path,
    query: str,
    room_map: Mapping[str, object],
    home: Path,
    *,
    session_list_text: str,
    since_epoch: float = 0.0,
    limit: int = FIND_LIMIT,
    budget_seconds: float = FIND_ADAPTER_BUDGET,
) -> tuple[list[dict[str, object]], str | None]:
    sanctioned_ids = parse_hermes_session_ids(session_list_text)
    cli_id_hits = hermes_cli_id_hits(session_list_text, query)
    if not database.exists():
        return cli_id_hits, "hermes_state_db_missing"
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    except sqlite3.Error:
        return cli_id_hits, "hermes_state_db_unreadable"
    deadline = time.monotonic() + budget_seconds
    connection.set_progress_handler(lambda: 1 if time.monotonic() >= deadline else 0, 1000)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        required = {"sessions", "messages", "messages_fts_trigram"}
        if not required <= tables:
            return cli_id_hits, "hermes_tables_or_fts_missing"
        matched_messages: dict[str, list[str]] = {}
        terms = re.findall(r"\w+", query)
        if terms:
            expression = " AND ".join('"' + term.replace('"', '""') + '"' for term in terms)
            try:
                rows = connection.execute(
                    "SELECT m.session_id, m.content FROM messages_fts_trigram f "
                    "JOIN messages m ON m.id = f.rowid WHERE f.content MATCH ? LIMIT ?",
                    (expression, max(limit * 4, limit)),
                )
                for session_id, content in rows:
                    if isinstance(session_id, str) and isinstance(content, str):
                        matched_messages.setdefault(session_id, []).append(content)
            except sqlite3.Error:
                if time.monotonic() >= deadline:
                    return [], "hermes_budget_exceeded"
                return [], "hermes_fts_query_failed"
        session_rows = connection.execute(
            "SELECT id, title, started_at, last_activity_at, cwd, source, ended_at "
            "FROM sessions WHERE COALESCE(last_activity_at, started_at) >= ? "
            "ORDER BY COALESCE(last_activity_at, started_at) DESC LIMIT ?",
            (since_epoch, max(limit * 10, 200)),
        )
        hits: list[dict[str, object]] = list(cli_id_hits)
        for session_id, title, started, last_active, cwd, source, ended_at in session_rows:
            if time.monotonic() >= deadline:
                return hits, "hermes_budget_exceeded"
            if not isinstance(session_id, str):
                continue
            texts = matched_messages.get(session_id, [])
            if not _query_matches(query, session_id, title, cwd, source, *texts):
                continue
            known_to_cli = session_id in sanctioned_ids
            live = bool(known_to_cli and ended_at is None)
            hits.append(
                _hit(
                    store="hermes",
                    session_id=session_id,
                    title=title if isinstance(title, str) else session_id,
                    when=last_active or started,
                    cwd=cwd if isinstance(cwd, str) else None,
                    room=room_label_for_cwd(cwd, room_map, home) if isinstance(cwd, str) else None,
                    pane_id=None,
                    live=live,
                    surfaces=("hermes", "telegram") if source == "telegram" else ("hermes",),
                    command=f"hermes --resume {shlex.quote(session_id)}",
                    snippet=_snippet(query, texts),
                )
            )
            if len(hits) >= limit:
                break
        return hits, None
    except sqlite3.Error:
        return [], "hermes_schema_drift"
    finally:
        connection.close()


def memex_search_hits(
    query: str,
    *,
    since: str | None,
    limit: int,
    room_map: Mapping[str, object],
    home: Path,
    executable: str = "memex",
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    budget_seconds: float = 2.0,
) -> tuple[list[dict[str, object]], str | None]:
    command = [
        executable,
        "search",
        query,
        "--limit",
        str(limit),
        "--unique-session",
        "--fields",
        "score,ts,session_id,source,source_path,snippet,project",
    ]
    if since:
        command.extend(["--since", since])
    try:
        result = runner(
            command,
            capture_output=True,
            text=True,
            timeout=budget_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return [], "memex_budget_exceeded; adapter skipped"
    except OSError:
        return [], "memex_search_failed; adapter skipped"
    if result.returncode != 0:
        return [], "memex_search_failed; adapter skipped"
    hits: list[dict[str, object]] = []
    for line in result.stdout.splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return [], "memex_search_invalid_json; adapter skipped"
        if not isinstance(payload, dict):
            continue
        source = payload.get("source")
        session_id = payload.get("session_id")
        if source not in {"claude", "codex"} or not isinstance(session_id, str):
            continue
        source_path = payload.get("source_path")
        metadata: dict[str, object] = {}
        if isinstance(source_path, str):
            metadata = _bounded_session_metadata(Path(source_path), str(source))
        cwd = metadata.get("cwd") if isinstance(metadata.get("cwd"), str) else None
        title = metadata.get("title") or payload.get("project") or session_id
        when = payload.get("ts") or metadata.get("when")
        hits.append(
            _hit(
                store=str(source),
                session_id=session_id,
                title=str(title),
                when=when,
                cwd=cwd,
                room=room_label_for_cwd(cwd, room_map, home),
                pane_id=None,
                live=False,
                surfaces=(str(source),),
                command=(
                    f"claude --resume {shlex.quote(session_id)}"
                    if source == "claude"
                    else f"codex resume {shlex.quote(session_id)}"
                ),
                snippet=str(payload.get("snippet") or "")[:240],
            )
        )
    return hits[:limit], None


def parse_duration(value: str) -> timedelta:
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([mhd])", value.strip())
    if not match:
        raise StoreError("duration must use m, h, or d, for example 2h")
    amount = float(match.group(1))
    if amount <= 0:
        raise StoreError("duration must be positive")
    unit = match.group(2)
    return timedelta(seconds=amount * {"m": 60, "h": 3600, "d": 86400}[unit])


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _limit_read_text(
    text: str,
    *,
    max_lines: int,
    max_bytes: int,
    server_truncated: bool = False,
) -> dict[str, object]:
    original_byte_count = len(text.encode())
    text_lines = text.splitlines()
    line_truncated = len(text_lines) > max_lines
    if line_truncated:
        text = "\n".join(text_lines[-max_lines:])
    encoded = text.encode()
    byte_truncated = len(encoded) > max_bytes
    if byte_truncated:
        text = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return {
        "text": text,
        "byte_count": original_byte_count,
        "max_bytes": max_bytes,
        "max_lines": max_lines,
        "truncated": server_truncated or line_truncated or byte_truncated,
        "server_truncated": server_truncated,
        "line_truncated": line_truncated,
        "byte_truncated": byte_truncated,
    }


def _session_jsonl_path(root: Path, source: str, session_id: str) -> Path | None:
    if source == "claude":
        paths = list(root.glob(f"*/{session_id}.jsonl"))
        paths += list(root.glob("*/*.jsonl")) if not paths else []
    elif source == "codex":
        paths = list(root.glob(f"**/*{session_id}*.jsonl"))
        paths += list(root.glob("**/rollout-*.jsonl")) if not paths else []
    else:
        return None
    for path in _newest_paths(paths, 0.0):
        metadata = _bounded_session_metadata(path, source, max_bytes=64 * 1024)
        if str(metadata.get("session_id") or "") == session_id:
            return path
    return None


def _jsonl_last_messages(path: Path, source: str) -> tuple[str | None, str | None]:
    return _jsonl_messages(_jsonl_records(path), source)


def _jsonl_messages(
    records: Sequence[Mapping[str, object]], source: str
) -> tuple[str | None, str | None]:
    last_user: str | None = None
    last_assistant: str | None = None
    for record in records:
        if source == "claude":
            message = record.get("message")
            if not isinstance(message, dict):
                continue
            if message.get("channel") not in {None, "final", "commentary"}:
                continue
            text = _reply_content_text(message.get("content"))
            role = message.get("role")
        else:
            payload = record.get("payload")
            if not isinstance(payload, dict):
                continue
            if payload.get("channel") not in {None, "final", "commentary"}:
                continue
            text = ""
            role: object = None
            if record.get("type") == "event_msg":
                event_type = payload.get("type")
                if event_type in {"user_message", "user_prompt"}:
                    role = "user"
                    text = payload.get("message") if isinstance(payload.get("message"), str) else ""
                elif event_type in {"agent_message", "assistant_message"}:
                    role = "assistant"
                    value = payload.get("last_agent_message") or payload.get("message")
                    text = value if isinstance(value, str) else ""
            elif record.get("type") == "response_item":
                role = payload.get("role")
                text = _reply_content_text(payload.get("content"))
        if text and role == "user":
            last_user = text
        elif text and role == "assistant":
            last_assistant = text
    return last_user, last_assistant


def _reply_content_text(value: object) -> str:
    """Extract visible message text; omit reasoning and tool payload blocks."""
    if isinstance(value, list):
        value = [item for item in value if isinstance(item, str) or (
            isinstance(item, dict) and item.get("type") in {None, "text", "input_text", "output_text"}
        )]
    return _content_text(value)


def _hermes_last_messages(database: Path, session_id: str) -> tuple[str | None, str | None]:
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    except sqlite3.Error as error:
        raise StoreError("Hermes transcript store is unavailable") from error
    try:
        columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(messages)")
        }
        role_column = next(
            (name for name in ("role", "sender", "message_type") if name in columns),
            None,
        )
        order_column = next(
            (name for name in ("created_at", "timestamp", "id") if name in columns),
            None,
        )
        if "session_id" not in columns or "content" not in columns or not role_column:
            raise StoreError("Hermes transcript store has an unsupported messages schema")
        order_sql = f" ORDER BY {order_column}" if order_column else ""
        rows = connection.execute(
            f"SELECT {role_column}, content FROM messages WHERE session_id = ?{order_sql}",
            (session_id,),
        )
        last_user: str | None = None
        last_assistant: str | None = None
        for role, content in rows:
            if not isinstance(content, str):
                continue
            normalized = str(role).casefold()
            if normalized in {"user", "human"}:
                last_user = content
            elif normalized in {"assistant", "agent", "hermes"}:
                last_assistant = content
        return last_user, last_assistant
    except sqlite3.Error as error:
        raise StoreError("Hermes transcript store is unreadable") from error
    finally:
        connection.close()


def _format_transcript(last_user: str | None, last_assistant: str | None) -> str:
    parts = []
    if last_user:
        parts.append(f"User:\n{last_user}")
    if last_assistant:
        parts.append(f"Assistant:\n{last_assistant}")
    return "\n\n".join(parts)
