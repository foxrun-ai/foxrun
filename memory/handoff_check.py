#!/usr/bin/env python3
"""Read transcript evidence and check whether a handoff covers it."""

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
import fnmatch
import json
import os
import re
import sqlite3
import sys
import tempfile
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


OUT_ROOT = _fox_paths.runs() / 'handoff-check'
TRACKERS = ((_fox_paths.database()),
            (_fox_paths.database()))
SECRET = re.compile(r"sk-|ghp_|xox|Bearer|op://", re.I)
TASK = re.compile(r"(?<![\w-])(?:T\d+|B-\d[0-9A-Za-z-]*|I-\d[0-9A-Za-z-]*|R-\d[0-9A-Za-z-]*|P\d+|WS\d\d)(?![\w-])")
SCORED_TASK = re.compile(r"(?:T\d+|P\d+|WS\d\d)\Z")
ROW_ID = re.compile(r"(?:R-|B-|I-)")
SCORED_DIRS = {"outputs", "docs", "tools", "skills", "handoffs", "foxrun-modules", "skillwright", "base", "work", "events", "decisions", "memory", "people", "design"}
APPROVAL = re.compile(r"^(?:yes|(?:yep|yeah|okay),?\s+approved|approved|run it|send it|merge it|go|do it)\b", re.I)
# A settlement is a turn where Person settles something: an approval turn, or a ruling cue.
POSITION = re.compile(r"\b(?:I(?:'ve| have) always thought|I would always think|I think of (?:it|them) as|"
                      r"from now on|the rule is)\b", re.I)
PURE_ACK = re.compile(r"^(?:(?:al{1,2}\s*right|okay|ok|cool|yep|yeah|yes|go|sounds good|"
                      r"i(?:'m| am) waiting)[.!?, ]*)+$", re.I)
DIRECT_QUESTION = re.compile(r"(?:\?|\b(?:want me to|should i|yes or no))\s*$", re.I)
EXPLICIT_RULING = re.compile(
    r"\b(?:from now on|the rule is|we go with|let'?s go with|approved|yes,? do it|"
    r"i approve|ruled|ruling|settled?|lock(?:ed)?\s+(?:it|that|this)\s+in|"
    r"this is (?:fucking )?perfect|love the way)\b", re.I)
QUESTION_RULING = re.compile(r"\b(?:decision|decide[sd]?|final|rule|i agree|sounds good)\b", re.I)
SETTLEMENT_CUE = re.compile(r"\b(?:approved|yes|run it|send it)\b", re.I)
LOCAL_ZONE = ZoneInfo("America/New_York")
HANDOFF_NAME = re.compile(r"\d{4}-\d{2}-\d{2}-\d{3}-[^/]+\.md\Z")
PERSON_PREFIX = re.compile(
    r"^" + re.escape(_fox_person.display_name()) + r"(?::|\s+(?:\d{1,2}[./]\d{1,2}|\d{4}-\d{2}-\d{2})\b"
    r"(?:\s+\d{1,2}:\d{2})?[^:]*:|\s+\([^)]*\):)", re.I)
SHELL_LINE = re.compile(r"^(?:[$#>]\s*)?(?:cd|cat|curl|echo|git|ls|mv|cp|mkdir|node|npm|npx|python\d*|rg|sed|sqlite3|work|sudo|export|set|source|touch|tee|bash|zsh)\b")
WORD = re.compile(r"[\w']+")
CONTENT_STOP = {"a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "do", "for",
                "from", "had", "has", "have", "he", "her", "here", "him", "his", "i", "if",
                "in", "is", "it", "its", "let", "me", "my", "of", "on", "or", "our", "she",
                "so", "that", "the", "their", "them", "there", "these", "they", "this", "to",
                "us", "was", "we", "were", "what", "when", "where", "which", "who", "will",
                "with", "would", "you", "your", "know", "like"}
FILLER = ("all right", "sounds good", "that's fine", "for now", "i think",
          "let's go", "got it")
CHANGE = re.compile(
    r"\b(?:work\.py\b|"
    r"git\s+(?:commit|push|merge)|merge_pr\.py|npm\s+run\s+roadmap:refresh|"
    r"curl\b[^\n]*\s-X\s+(?:POST|PUT)|sqlite3\b[^\n]*\b(?:INSERT|UPDATE|DELETE|CREATE|DROP|ALTER)\b|"
    r"imsg\s+send|send)\b", re.I
)
PATH = re.compile(r"(?<![\w])(?:~?/|\.{1,2}/)?[\w.~-]+(?:/[\w.~-]+)+")
REDIRECT = re.compile(r"(?:^|\s)(?:>>?|tee\s+(?:-a\s+)?)(?:\s*)([~./\w-]+(?:/[~./\w-]+)*)")
MOVE = re.compile(r"(?:^|[;&|]\s*|\n)\s*(?:cp|mv)\s+(?:-[\w-]+\s+)*([^\s]+)\s+([^\s;&|]+)")
MUTATION = re.compile(r"\b(?:git\s+(?:add|commit|push|merge)|mkdir|touch|rm|work\.py)\b", re.I)
INJECTED_TAG = re.compile(
    r"</?(system-reminder|cross-session-message|pasted_content|task-notification|"
    r"local-command-[\w-]+)\b[^>]*>", re.I
)
SKILL_HEADER = re.compile(r"(?m)^Base directory for this skill:")
QUOTED = re.compile(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"")
TURN_QUOTE = re.compile(r"(?<!\w)['‘][^'’]*['’](?!\w)|[\"“][^\"”]*[\"”]")
SQL_TARGET = re.compile(r"\bid\s*=\s*['\"]?(T\d+)", re.I)


def safe(value: str) -> str | None:
    """Reject a whole transcript line if it contains a credential marker."""
    return value.strip() if value.strip() and not SECRET.search(value) else None


def clean_path(value: str) -> str | None:
    value = value.strip("'\"`(),;:<>[]{}")
    if not value or value.isdigit() or value == "/dev/null" or "$" in value or "*" in value or SECRET.search(value):
        return None
    return value


def command_task_ids(line: str) -> set[str]:
    """Keep command targets, not unrelated IDs in quoted payloads."""
    if re.search(r"\bgit\s+commit\b", line):
        return set(TASK.findall(line))
    ids = set(TASK.findall(QUOTED.sub("", line)))
    ids.update(match.group(1) for match in SQL_TARGET.finditer(line))
    return ids


def transcript(session: str) -> Path:
    if len(session) < 13:
        raise ValueError("session prefix must contain at least 13 characters")
    roots = [Path.home() / ".claude/projects", Path.home() / ".codex/sessions"]
    hits = []
    for root in roots:
        if root.exists():
            hits.extend(p for p in root.glob(f"**/*{session}*.jsonl") if p.is_file())
    if len(hits) != 1:
        raise ValueError(f"session lookup found {len(hits)} transcripts; expected one")
    return hits[0]


def transcript_lines(path: Path, tail_bytes: int | None = None):
    """Yield complete JSONL records, starting near the end for a bounded hook check."""
    with path.open('rb') as stream:
        if tail_bytes is not None:
            offset = max(0, path.stat().st_size - tail_bytes)
            stream.seek(offset)
            if offset:
                stream.readline()  # Discard the partial first record.
        yield from stream


def handoff_window(source: Path, handoff: Path, tail_bytes: int | None = None) -> tuple[datetime | None, datetime | None]:
    """Find this handoff's last write and the previous handoff write in this session."""
    target = handoff.expanduser().resolve(strict=False)
    writes = []
    def previous_handoff(path: Path) -> bool:
        if not HANDOFF_NAME.fullmatch(path.name) or not path.is_file():
            return False
        try:
            head = path.read_text(encoding="utf-8")[:4096]
        except OSError:
            return False
        match = re.match(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", head, re.S)
        return bool(match and re.search(r"(?m)^type:\s*['\"]?handoff['\"]?\s*$", match.group(1)))
    for line in transcript_lines(source, tail_bytes):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("type") != "assistant":
            continue
        msg = row.get("message")
        if not isinstance(msg, dict) or not isinstance(msg.get("content"), list):
            continue
        for block in msg["content"]:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            if block.get("name") not in ("Write", "Edit", "MultiEdit"):
                continue
            args = block.get("input")
            if not isinstance(args, dict):
                continue
            raw = args.get("file_path") or args.get("path")
            if not isinstance(raw, str):
                continue
            written = Path(raw).expanduser().resolve(strict=False)
            if written.parent != target.parent or written.suffix != ".md":
                continue
            stamp = row.get("timestamp")
            if isinstance(stamp, str):
                try:
                    moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                except ValueError:
                    continue
                writes.append((written, moment))
    latest = max((at for path, at in writes if path == target), default=None)
    previous = max((at for path, at in writes if path != target and previous_handoff(path) and
                    (latest is None or at < latest)), default=None)
    return latest, previous


def handoff_cutoff(source: Path, handoff: Path) -> datetime | None:
    return handoff_window(source, handoff)[0]


def text_blocks(content: object) -> list[str]:
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        return [v for block in content if isinstance(block, dict) and block.get("type") in ("text", "input_text", "output_text")
                for v in (block.get("text"),) if isinstance(v, str)]
    return []


def human_text(content: object) -> str:
    """Remove injected blocks while keeping words around them in a mixed turn."""
    value = "\n".join(text_blocks(content))
    if match := SKILL_HEADER.search(value):
        value = value[:match.start()]
    chunks = []
    depth = 0
    start = 0
    for match in INJECTED_TAG.finditer(value):
        if depth == 0:
            chunks.append(value[start:match.start()])
        if match.group().startswith("</"):
            depth = max(0, depth - 1)
        elif not match.group().endswith("/>"):
            depth += 1
        start = match.end()
    if depth == 0:
        chunks.append(value[start:])
    return "".join(chunks)


def call_input(raw: object) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {"raw": raw}
        except json.JSONDecodeError:
            return {"raw": raw}
    return {}


@dataclass
class Extract:
    session: str
    source: str
    model: str = "unknown"
    ids: set[str] = field(default_factory=set)
    files: set[str] = field(default_factory=set)
    person: list[dict] = field(default_factory=list)
    approvals: list[dict] = field(default_factory=list)
    commands: list[dict] = field(default_factory=list)
    assistant_text: str = ""
    seen_turns: dict[str, list[datetime]] = field(default_factory=dict)

    def add_text(self, text: str) -> None:
        for line in text.splitlines():
            line = safe(line)
            if line is None:
                continue
            self.ids.update(TASK.findall(line))

    def add_user_turn(self, content: object, timestamp: str | None = None) -> None:
        own_text = human_text(content)
        if own_text.startswith("This session is being continued from a previous conversation"):
            self.assistant_text = ""
            return
        self.add_text(own_text)
        lines = []
        for block in [own_text]:
            for raw in block.splitlines():
                line = safe(raw)
                if line and not line.startswith("<") and not line.startswith("```") and not SHELL_LINE.match(line):
                    lines.append(line)
        if not lines:
            return
        full = " ".join(lines)
        if timestamp:
            try:
                moment = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                if any(abs((moment - prior).total_seconds()) <= 2
                       for prior in self.seen_turns.get(full, [])):
                    self.assistant_text = ""
                    return
                self.seen_turns.setdefault(full, []).append(moment)
            except (ValueError, TypeError):
                pass
        turn = {"index": len(self.person) + 1, "text": full, "excerpt": full[:240],
                "timestamp": timestamp,
                "assistant_before": self.assistant_text,
                "approval": len(full.split()) <= 12 and bool(APPROVAL.match(full)),
                "recorded": False, "comment_id": None, "task_id": None}
        self.person.append(turn)
        self.assistant_text = ""
        if turn["approval"]:
            self.approvals.append(turn)

    def add_call(self, name: str, raw: object, call_id: str) -> None:
        args = call_input(raw)
        short = name.rsplit(".", 1)[-1]
        if re.search(r"send", short, re.I):
            task = "unassigned"
            for value in args.values():
                if isinstance(value, str):
                    for line in value.splitlines():
                        if safe(line) and (hits := TASK.findall(line)):
                            task = hits[0]
                            break
                if task != "unassigned":
                    break
            self.commands.append({"id": call_id, "task": task,
                                  "command": f"{name} [payload omitted]", "outcome": "unknown"})
        if short in ("Write", "Edit", "MultiEdit", "apply_patch"):
            for key in ("file_path", "path"):
                val = args.get(key)
                if isinstance(val, str) and (p := clean_path(val)):
                    self.files.add(p)
                    self.add_text(p)
            if short == "apply_patch":
                patch = args.get("input") or args.get("patch") or args.get("raw") or ""
                if isinstance(patch, str):
                    for m in re.finditer(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", patch, re.M):
                        if p := clean_path(m.group(1)):
                            self.files.add(p)
                            self.add_text(p)
        commands = []
        for key in ("command", "cmd"):
            if isinstance(args.get(key), str):
                commands.append(args[key])
        # Codex wraps exec_command in JavaScript. Parse only explicit command fields.
        if short == "exec" and isinstance(args.get("raw"), str):
            raw_js = args["raw"]
            for m in re.finditer(r'\bcmd\s*:\s*("(?:\\.|[^"\\])*")', raw_js):
                try:
                    commands.append(json.loads(m.group(1)))
                except json.JSONDecodeError:
                    pass
            for m in re.finditer(r'\bapply_patch\s*\(\s*("(?:\\.|[^"\\])*")', raw_js):
                try:
                    patch = json.loads(m.group(1))
                except json.JSONDecodeError:
                    continue
                for hit in re.finditer(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", patch, re.M):
                    if p := clean_path(hit.group(1)):
                        self.files.add(p)
                        self.add_text(p)
        for command in commands:
            for line in command.splitlines():
                line = safe(line)
                if line is None:
                    continue
                changed = bool(CHANGE.search(line) or MUTATION.search(line))
                for match in REDIRECT.finditer(line):
                    if p := clean_path(match.group(1)):
                        self.files.add(p)
                        self.add_text(p)
                        changed = True
                for match in MOVE.finditer(line):
                    if p := clean_path(match.group(2)):
                        self.files.add(p)
                        self.add_text(p)
                        changed = True
                if changed:
                    self.ids.update(command_task_ids(line))
                if CHANGE.search(line):
                    ids = TASK.findall(line)
                    self.commands.append({"id": call_id, "task": ids[0] if ids else "unassigned",
                                          "command": line, "outcome": "unknown"})


def parse(path: Path, until: datetime | None = None, tail_bytes: int | None = None) -> Extract:
    session = re.search(r"[0-9a-f]{8}-[0-9a-f-]{27,}", path.name)
    result = Extract(session.group() if session else path.stem,
                     "codex" if path.name.startswith("rollout-") else "claude")
    outcomes: dict[str, str] = {}
    for line in transcript_lines(path, tail_bytes):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if until is not None and isinstance(row.get("timestamp"), str):
            try:
                if datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")) > until:
                    continue
            except ValueError:
                pass
        if result.source == "claude":
            msg = row.get("message")
            if not isinstance(msg, dict):
                continue
            if row.get("type") == "assistant":
                model = msg.get("model") or row.get("advisorModel")
                if isinstance(model, str) and model not in ("<synthetic>", "unknown"):
                    result.model = model
            content = msg.get("content")
            if row.get("type") == "assistant":
                result.assistant_text += " ".join(text_blocks(content)) + " "
            if row.get("type") == "user" and not row.get("isMeta") and not row.get("sourceToolUseID"):
                result.add_user_turn(content, row.get("timestamp"))
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_use":
                        result.add_call(str(block.get("name", "")), block.get("input"), str(block.get("id", "")))
                    elif block.get("type") == "tool_result":
                        value = block.get("content", "")
                        fail = bool(block.get("is_error")) or (isinstance(value, str) and
                            bool(re.search(r"(?:exit code|exit_code)\s*[:=]?\s*[1-9]", value, re.I)))
                        outcomes[str(block.get("tool_use_id", ""))] = "fail" if fail else "ok"
        else:
            payload = row.get("payload", {})
            if not isinstance(payload, dict):
                continue
            if row.get("type") == "turn_context":
                model = payload.get("model")
                if isinstance(model, str) and model != "unknown":
                    result.model = model
            elif row.get("type") == "response_item":
                kind = payload.get("type")
                if kind == "message":
                    if payload.get("role") == "user":
                        result.add_user_turn(payload.get("content"), row.get("timestamp"))
                    elif payload.get("role") == "assistant":
                        result.assistant_text += " ".join(text_blocks(payload.get("content"))) + " "
                elif kind in ("custom_tool_call", "function_call"):
                    result.add_call(str(payload.get("name", "")), payload.get("input", payload.get("arguments")), str(payload.get("call_id", "")))
                elif kind in ("custom_tool_call_output", "function_call_output"):
                    output = payload.get("output", "")
                    if isinstance(output, str):
                        try:
                            output = json.loads(output)
                        except json.JSONDecodeError:
                            pass
                    if isinstance(output, dict):
                        code = output.get("exit_code")
                        fail = output.get("isError") or code not in (None, 0)
                    elif isinstance(output, list):
                        rendered = " ".join(x.get("text", "") for x in output if isinstance(x, dict))
                        fail = bool(re.search(r"(?:Script failed|exit_code\s*[:=]\s*[1-9]|Process exited with code [1-9])", rendered, re.I))
                    else:
                        fail = isinstance(output, str) and bool(re.search(r"(?:exit code|exit_code)\s*[:=]?\s*[1-9]", output, re.I))
                    outcomes[str(payload.get("call_id", ""))] = "fail" if fail else "ok"
    for item in result.commands:
        item["outcome"] = outcomes.get(item["id"], "unknown")
    return result


def words(value: str) -> list[str]:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = re.sub(r"(?<=\w)['’](?=\w)", "", value)
    return re.findall(r"[^\W_]+", value)


FILLER_PHRASES = tuple(tuple(words(phrase)) for phrase in FILLER)


def without_filler(value: tuple[str, ...]) -> list[str]:
    remaining = []
    index = 0
    while index < len(value):
        phrase = next((part for part in FILLER_PHRASES if value[index:index + len(part)] == part), None)
        if phrase:
            index += len(phrase)
        else:
            remaining.append(value[index])
            index += 1
    return remaining


def content_words(value: str) -> list[str]:
    return [word for word in words(value) if word not in CONTENT_STOP]


def own_word_runs(value: str, size: int, assistant_before: str = "") -> set[tuple[str, ...]]:
    """Keep runs outside quoted text and absent from the preceding assistant turn."""
    assistant = tuple(words(assistant_before))
    echoes = {assistant[i:i + size] for i in range(len(assistant) - size + 1)}
    runs = set()
    start = 0
    for quote in TURN_QUOTE.finditer(value):
        segment = words(value[start:quote.start()])
        runs.update(tuple(segment[i:i + size]) for i in range(len(segment) - size + 1))
        start = quote.end()
    segment = words(value[start:])
    runs.update(tuple(segment[i:i + size]) for i in range(len(segment) - size + 1))
    return {run for run in runs - echoes
            if sum(word not in CONTENT_STOP for word in without_filler(run)) >= 4}


def recorded_match(turn: str, body: str, kind: str = "comment",
                   row_words: tuple[str, ...] | None = None,
                   turn_words: tuple[str, ...] | None = None,
                   chunks: set[tuple[str, ...]] | None = None,
                   short_row_words: tuple[str, ...] | None = None,
                   quote_words: tuple[tuple[str, ...], ...] | None = None,
                   assistant_before: str = "", run_size: int | None = None) -> bool:
    prefix = PERSON_PREFIX.match(body) if kind == "comment" else None
    needle = turn_words if turn_words is not None else tuple(words(turn))
    if not needle:
        return False
    if kind != "comment":
        haystack = row_words if row_words is not None else tuple(words(body))
        if any(tuple(haystack[i:i + len(needle)]) == needle
               for i in range(len(haystack) - len(needle) + 1)):
            return True
    if len(needle) >= 6:
        if kind == "comment" and not prefix:
            return False
        haystack = row_words if row_words is not None else tuple(words(body))
        size = run_size or min(8, len(needle))
        if chunks is None:
            chunks = own_word_runs(turn, size, assistant_before)
        return any(tuple(haystack[i:i + size]) in chunks for i in range(len(haystack) - size + 1))
    if kind == "comment" and not prefix:
        return False
    haystack = short_row_words if short_row_words is not None else tuple(words(body[prefix.end():] if prefix else body))
    if haystack == needle:
        return True
    if quote_words is None:
        quotes = re.findall(r"(?<!\w)['‘](.*?)['’](?!\w)|[\"“](.*?)[\"”]", body)
        quote_words = tuple(tuple(words(quote)) for pair in quotes for quote in pair if quote)
    return needle in quote_words


def dated_row_indices(rows: list[tuple]) -> dict:
    """Keep original row order within each local date."""
    dates = defaultdict(list)
    for index, row in enumerate(rows):
        moment = row[7] if len(row) > 7 else None
        if moment is not None:
            day = moment.astimezone(LOCAL_ZONE).date() if moment.tzinfo else moment.date()
            dates[day].append(index)
    return dates


def candidate_row_indices(turn: dict, dates: dict) -> list[int]:
    """A row can match a turn only on its local date or the next date."""
    stamp = turn.get("timestamp")
    if not stamp:
        return []
    try:
        day = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(LOCAL_ZONE).date()
    except (TypeError, ValueError):
        return []
    return sorted((*dates.get(day, ()), *dates.get(day + timedelta(days=1), ())))


def mark_recorded(data: Extract, trackers: tuple[Path, ...] = TRACKERS,
                  match_window_hours: float = 24) -> None:
    rows = row_bodies(trackers)
    dates = dated_row_indices(rows)
    used = set()
    for turn in data.person:
        for index in candidate_row_indices(turn, dates):
            row = rows[index]
            if index not in used and row_matches_turn(turn, row,
                                                      match_window_hours=match_window_hours, rows=rows):
                kind, row_id, task_id = row[:3]
                turn.update(recorded=True, comment_id=int(row_id) if kind == "comment" else row_id,
                            task_id=task_id)
                used.add(index)
                break


def is_settlement(turn: dict) -> bool:
    f"""Score a {_fox_person.display_name()} turn as a settlement: an approval, or a ruling cue that is not only a question."""
    text = turn["text"].strip()
    question = bool(DIRECT_QUESTION.search(turn.get("assistant_before", "").strip()))
    if SETTLEMENT_CUE.search(text):
        return True
    if PURE_ACK.fullmatch(text) and not question:
        return False
    if turn["approval"]:
        return True
    if POSITION.search(text):
        return True
    if text.endswith("?"):
        return False
    if EXPLICIT_RULING.search(text):
        return True
    return bool(QUESTION_RULING.search(text)) and (len(words(text)) < 6 or question)


def prepared_row(kind: str, row_id: str, task_id: str | None, body: str,
                 at: str | None, subject: str) -> tuple:
    """Normalize row text and time once, before matching any turns."""
    try:
        moment = datetime.fromisoformat(at.replace("Z", "+00:00")) if at else None
        if moment and moment.tzinfo is None and "T" in at:
            moment = moment.replace(tzinfo=LOCAL_ZONE)
    except (ValueError, TypeError):
        moment = None
    prefix = PERSON_PREFIX.match(body) if kind == "comment" else None
    quotes = re.findall(r"(?<!\w)['‘](.*?)['’](?!\w)|[\"“](.*?)[\"”]", body)
    quote_words = tuple(tuple(words(quote)) for pair in quotes for quote in pair if quote)
    subject_quotes = re.findall(r"(?<!\w)['‘](.*?)['’](?!\w)|[\"“](.*?)[\"”]", subject)
    subject_quote_words = tuple(tuple(words(quote)) for pair in subject_quotes for quote in pair if quote)
    return (kind, row_id, task_id, body, at, subject, tuple(words(body)), moment,
            tuple(words(body[prefix.end():] if prefix else body)), quote_words, subject_quote_words)


def row_bodies(trackers: tuple[Path, ...]) -> list[tuple]:
    f"""Every row that can hold {_fox_person.display_name()}'s words: comments, decisions, and approvals. Read-only."""
    rows = []
    for db in trackers:
        if not db.exists():
            continue
        with _fox_person.connect(f"file:{db}?mode=ro", uri=True) as conn:
            tables = {name for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            first_row = len(rows)
            if "comments" in tables:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(comments)")}
                stamp = "at" if "at" in columns else "NULL"
                rows.extend(prepared_row("comment", str(i), subject, body, at, body)
                            for i, subject, body, at in conn.execute(
                    f"SELECT id, subject_id, body, {stamp} FROM comments WHERE coalesce(body, '') != ''"))
            if "decisions" in tables:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(decisions)")}
                stamp = "decided_on" if "decided_on" in columns else "NULL"
                source = "source" if "source" in columns else "NULL"
                comments = {row[1]: (row[2], row[4], row[3]) for row in rows[first_row:]
                            if row[0] == "comment"}
                for i, words_, at, ref in conn.execute(
                    f"SELECT id, person_words, {stamp}, {source} FROM decisions WHERE coalesce(person_words, '') != ''"
                ):
                    linked = comments.get(ref.removeprefix("comment:")) if isinstance(ref, str) and ref.startswith("comment:") else None
                    rows.append(prepared_row("decision", str(i), linked[0] if linked else None, words_,
                                             linked[1] if linked else at, linked[2] if linked else words_) +
                                (bool(linked),))
            if "approvals" in tables:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(approvals)")}
                stamp = "given_at" if "given_at" in columns else "NULL"
                rows.extend(prepared_row("approval", str(i), subject, words_, at, words_)
                            for i, subject, words_, at in conn.execute(
                    f"SELECT id, subject_id, person_words, {stamp} FROM approvals WHERE coalesce(person_words, '') != ''"))
    return rows


def subject_matches(turn: dict, row: tuple) -> bool:
    kind, row_id, task_id, body, at, subject = row[:6]
    assistant = turn.get("assistant_before", "")
    if not assistant:
        return False
    subitems = re.findall(r"\bR\d+\b", subject, re.I)
    if subitems:
        identifiers = subitems[:1]
    elif kind == "approval":
        identifiers = [task_id] if task_id else []
    elif kind == "decision" and subject == body:
        identifiers = [row_id]
    else:
        identifiers = [task_id] if task_id else []
    for identifier in identifiers:
        if re.search(r"(?<![\w-])" + re.escape(identifier) + r"(?![\w-])", assistant, re.I):
            return True
    quotes = row[10] if len(row) > 10 else tuple(
        tuple(words(quote)) for pair in re.findall(r"(?<!\w)['‘](.*?)['’](?!\w)|[\"“](.*?)[\"”]", subject)
        for quote in pair if quote)
    if "_assistant_words" not in turn:
        turn["_assistant_words"] = tuple(words(assistant))
    assistant_words = turn["_assistant_words"]
    if "_words" not in turn:
        turn["_words"] = tuple(words(turn["text"]))
    turn_words = turn["_words"]
    for quoted in quotes:
        if not quoted or quoted == turn_words or not any(word not in CONTENT_STOP for word in quoted):
            continue
        if any(assistant_words[i:i + len(quoted)] == quoted
               for i in range(len(assistant_words) - len(quoted) + 1)):
            return True
    return False


def subitems(value: str) -> set[str]:
    """Names that distinguish one question or ruling from another on a task."""
    found = {"Q" + number for number in re.findall(r"\b(?:Q|question)\s*(\d+)\b", value, re.I)}
    found.update("R" + number for number in re.findall(r"\bR\s*(\d+)\b", value, re.I))
    found.update("option " + letter.upper() for letter in re.findall(r"\boption\s+([A-Z])\b", value, re.I))
    found.update(name.casefold() for name in re.findall(r"(?<![\w-])(?:g-|pr-)[a-z0-9-]+", value, re.I))
    return found


def short_capture_match(turn: dict, row: tuple, rows: list[tuple] | None) -> bool:
    """A short assent needs its task and exact words, shared item, or unique prompt."""
    kind, _, task_id, body, _, subject = row[:6]
    if kind == "decision" and not (len(row) > 11 and row[11]):
        return False  # A date-only, unlinked decision cannot prove a 30-minute match.
    explicit_tasks = set(re.findall(r"(?<![\w-])T\d+(?![\w-])",
                                    turn["text"] + " " + turn.get("assistant_before", "")))
    if explicit_tasks and task_id not in explicit_tasks:
        return False
    if not task_id:
        return False
    assistant = turn.get("assistant_before", "")
    row_items = subitems(subject)
    assistant_items = subitems(assistant)
    assistant_decisions = {item for item in assistant_items if item.startswith(("g-", "pr-"))}
    if assistant_decisions and assistant_decisions.isdisjoint(row_items) and not (row_items & assistant_items):
        return False
    for prefix in ("Q", "R", "option "):
        left = {item for item in row_items if item.startswith(prefix)}
        right = {item for item in assistant_items if item.startswith(prefix)}
        if left and right and left.isdisjoint(right):
            return False
    needle = turn["_words"]
    exact = recorded_match(turn["text"], body, kind, row[6], needle,
                           short_row_words=row[8], quote_words=row[9])
    shared_item = bool(row_items & assistant_items)
    unique_prompt = False
    if kind == "comment" and rows is not None and DIRECT_QUESTION.search(assistant.strip()):
        turn_time = turn["_time"]
        captures = [candidate for candidate in rows
                    if candidate[0] == "comment" and candidate[2] == task_id
                    and PERSON_PREFIX.match(candidate[3]) and candidate[7] is not None
                    and turn_time <= candidate[7] <= turn_time + timedelta(minutes=5)]
        unique_prompt = len(captures) == 1 and captures[0][1] == row[1]
    linked = bool(explicit_tasks) or subject_matches(turn, row)
    contextual_capture = len(row[8]) >= 6
    return (exact and (linked or contextual_capture)) or shared_item or (unique_prompt and linked)


def row_matches_turn(turn: dict, row: tuple, since: datetime | None = None,
                     until: datetime | None = None, match_window_hours: float = 24,
                     rows: list[tuple] | None = None) -> bool:
    kind, _, _, body, at, _ = row[:6]
    if kind == "comment" and not PERSON_PREFIX.match(body):
        return False
    if not turn.get("timestamp") or not at:
        return False
    try:
        if "_time" not in turn:
            turn["_time"] = datetime.fromisoformat(turn["timestamp"].replace("Z", "+00:00"))
        turn_time = turn["_time"]
        row_time = row[7] if len(row) > 7 else prepared_row(*row[:6])[7]
        if row_time is None or turn_time.tzinfo is None:
            return False
        if "_words" not in turn:
            turn["_words"] = tuple(words(turn["text"]))
        needle = turn["_words"]
        # An exact whole-turn capture is sufficient even when it is short or
        # its words also appeared in the assistant's preceding question.
        if len(needle) >= 6 and row_time.tzinfo is not None and turn_time <= row_time <= turn_time + timedelta(minutes=30) and not (
            (since is not None and row_time <= since.astimezone(LOCAL_ZONE)) or
            (until is not None and row_time > until.astimezone(LOCAL_ZONE))
        ):
            haystack = row[6] if len(row) > 6 else tuple(words(body))
            if any(tuple(haystack[i:i + len(needle)]) == needle
                   for i in range(len(haystack) - len(needle) + 1)):
                return True
        long_turn = len(needle) >= 6
        if "T" not in at and kind == "decision":
            local_date = turn_time.astimezone(LOCAL_ZONE).date()
            if row_time.date() not in (local_date, local_date + timedelta(days=1)):
                return False
            # A date-only decision has no clock time. Its date is the evidence window.
            row_time = turn_time
        else:
            window = timedelta(hours=match_window_hours) if long_turn else timedelta(minutes=30)
            if not turn_time <= row_time <= turn_time + window:
                return False
        if (since is not None and row_time <= since.astimezone(LOCAL_ZONE)) or (until is not None and row_time > until.astimezone(LOCAL_ZONE)):
            return False
        if not long_turn:
            if "T" not in at:
                return False
            return short_capture_match(turn, row, rows)
        date_only_unlinked = kind == "decision" and "T" not in at and not (len(row) > 11 and row[11])
        if date_only_unlinked and len(row[6]) < min(8, len(needle)):
            return False
        size = min(10, len(row[6])) if date_only_unlinked else min(8, len(needle))
        if long_turn and ("_chunks", size) not in turn:
            turn[("_chunks", size)] = own_word_runs(turn["text"], size, turn.get("assistant_before", ""))
        return recorded_match(turn["text"], body, kind, row[6] if len(row) > 6 else None,
                              needle, turn.get(("_chunks", size)), row[8] if len(row) > 8 else None,
                              row[9] if len(row) > 9 else None, turn.get("assistant_before", ""), size)
    except (ValueError, TypeError, OverflowError):
        return False


def date_mismatch_time(turn: dict, row: tuple, since: datetime | None = None,
                       until: datetime | None = None, match_window_hours: float = 24) -> str | None:
    """Return a row time only for an eight-word match one calendar day outside its date rule."""
    kind, _, _, body, at, _ = row[:6]
    if kind == "comment" and not PERSON_PREFIX.match(body):
        return None
    if not turn.get("timestamp") or not at:
        return None
    try:
        turn_time = datetime.fromisoformat(turn["timestamp"].replace("Z", "+00:00"))
        row_time = row[7]
        if turn_time.tzinfo is None or row_time is None:
            return None
        needle = tuple(words(turn["text"]))
        if len(needle) < 8:
            return None
        if (since is not None and row_time <= since.astimezone(LOCAL_ZONE)) or (until is not None and row_time > until.astimezone(LOCAL_ZONE)):
            return None
        local_date = turn_time.astimezone(LOCAL_ZONE).date()
        if kind == "decision" and "T" not in at:
            near_date = row_time.date() in (local_date - timedelta(days=1), local_date + timedelta(days=2))
        else:
            end = turn_time + timedelta(hours=match_window_hours)
            near_date = ((row_time < turn_time and row_time >= turn_time - timedelta(days=1) and
                          row_time.astimezone(LOCAL_ZONE).date() == local_date - timedelta(days=1)) or
                         (row_time > end and row_time <= end + timedelta(days=1) and
                          row_time.astimezone(LOCAL_ZONE).date() == end.astimezone(LOCAL_ZONE).date() + timedelta(days=1)))
        if not near_date:
            return None
        date_only_unlinked = kind == "decision" and "T" not in at and not (len(row) > 11 and row[11])
        if date_only_unlinked and len(row[6]) < 8:
            return None
        size = min(10, len(row[6])) if date_only_unlinked else 8
        chunks = own_word_runs(turn["text"], size, turn.get("assistant_before", ""))
        if recorded_match(turn["text"], body, kind, row[6], needle, chunks, row[8], row[9],
                          turn.get("assistant_before", ""), size):
            return at
    except (ValueError, TypeError, OverflowError):
        pass
    return None


def local_time(timestamp: str | None) -> str:
    if not timestamp:
        return "unknown time"
    stamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone()
    return stamp.strftime("%Y-%m-%d %H:%M:%S %Z")


def settlement_excerpt(value: str) -> str:
    positions = list(POSITION.finditer(value))
    start = positions[-1].start() if positions else 0
    return value[start:start + 240]


def settlements_report(data: Extract, trackers: tuple[Path, ...], since: datetime | None = None,
                       until: datetime | None = None, match_window_hours: float = 24,
                       rows: list[tuple] | None = None) -> dict:
    f"""Settlement turns and whether a comment, decision, or approval row holds {_fox_person.display_name()}'s words.

    Read-only: it opens trackers with mode=ro and writes no file.
    """
    turns = data.person
    if since is not None:
        boundary = since.astimezone()
        turns = [turn for turn in turns if turn["timestamp"] and
                 datetime.fromisoformat(turn["timestamp"].replace("Z", "+00:00")).astimezone() > boundary]
    rows = row_bodies(trackers) if rows is None else rows
    dates = dated_row_indices(rows)
    settled, promoted, unpromoted, warnings, date_mismatch = [], [], [], [], []
    used = set()
    for turn in turns:
        if not is_settlement(turn):
            continue
        settled.append(turn)
        candidates = candidate_row_indices(turn, dates)
        matching = [(i, rows[i]) for i in candidates if i not in used and
                    row_matches_turn(turn, rows[i], since, until, match_window_hours, rows)]
        hit = next(((i, row) for i, row in matching if row[0] == "decision"), None) or next(
            ((i, row) for i, row in matching if row[0] == "approval"), None) or next(iter(matching), None)
        item = {"index": turn["index"], "timestamp": turn["timestamp"], "local_time": local_time(turn["timestamp"]),
                "text": settlement_excerpt(turn["text"]), "approval": turn["approval"]}
        if hit:
            used.add(hit[0])
            row = hit[1]
            promoted.append({**item, "row_kind": row[0], "row_id": row[1], "task_id": row[2],
                             "row_time": row[4]})
            if row[0] == "comment" and len(words(turn["text"])) >= 6 and not any(row_matches_turn(turn, candidate, since, until,
                                                                   match_window_hours, rows)
                                                    for candidate in (rows[i] for i in candidates) if candidate[0] == "decision"):
                warnings.append({**item, "row_id": row[1], "warning": "comment only, no decision row"})
        else:
            drift = next(((row, at) for i, row in enumerate(rows) if i not in used
                          for at in (date_mismatch_time(turn, row, since, until, match_window_hours),) if at), None)
            if drift:
                row, at = drift
                date_mismatch.append({**item, "warning": "date mismatch", "row_kind": row[0],
                                      "row_id": row[1], "row_time": at})
            else:
                unpromoted.append(item)
    return {"session": data.session, "source": data.source, "model": data.model,
            "since": since.isoformat() if since else None, "turns": len(turns),
            "settlements": len(settled), "promoted": promoted, "unpromoted": unpromoted,
            "warnings": warnings, "date_mismatch": date_mismatch,
            "ids": sorted(data.ids), "files": sorted(data.files)}


def rate_report(data: Extract, since: datetime | None = None) -> None:
    turns = data.person
    if since is not None:
        boundary = since.astimezone()
        turns = [turn for turn in turns if turn["timestamp"] and
                 datetime.fromisoformat(turn["timestamp"].replace("Z", "+00:00")).astimezone() > boundary]
    recorded = sum(turn["recorded"] for turn in turns)
    percent = round(100 * recorded / len(turns)) if turns else 100
    print(f"{_fox_person.display_name()} record rate: {recorded}/{len(turns)} ({percent}%)")
    for turn in turns:
        if not turn["recorded"]:
            stamp = (datetime.fromisoformat(turn["timestamp"].replace("Z", "+00:00")).astimezone()
                     if turn["timestamp"] else None)
            local_time = stamp.strftime("%Y-%m-%d %H:%M:%S %Z") if stamp else "unknown time"
            print(f"U{turn['index']:03d} {local_time} | {turn['text'][:160]}")


def write_private(path: Path, text: str, mode: int = 0o600) -> None:
    """Write path through a new private temporary file beside it, then rename it into place.
    mkstemp makes the file 0600 with O_EXCL, so a link planted at the report name is never followed."""
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.chmod(temporary, mode)
        os.replace(temporary, str(path))
    except BaseException:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise


def report_path(out: Path, name: str) -> Path:
    """Keep folder outputs and place file outputs beside the extract."""
    if out.suffix:
        if out.is_dir():
            raise ValueError(f"--out must name a file, but this path is a directory: {out}")
        return out if name == "extract.md" else out.with_name(f"{out.stem}.{name}")
    return out / name


def write_extract(data: Extract, out: Path) -> None:
    target = report_path(out, "extract.md")
    if not out.suffix:
        out.mkdir(parents=True, exist_ok=True)
    lines = [f"# Extract: {data.session}", "", f"Source: {data.source}", f"Model: {data.model}",
             f"Task IDs: {len(data.ids)}", f"Files written or edited: {len(data.files)}",
             f"State-changing commands: {len(data.commands)}", f"User turns: {len(data.person)}",
             f"Approval turns: {len(data.approvals)}", "", "## Task IDs", ""]
    lines.extend(f"- {x}" for x in sorted(data.ids))
    lines.extend(["", "## Files written or edited", ""])
    lines.extend(f"- {x}" for x in sorted(data.files))
    lines.extend(["", "## State-changing commands", ""])
    lines.extend(f"- {c['task']} | {c['outcome']} | {c['command']}" for c in data.commands)
    lines.extend(["", f"## {_fox_person.display_name()} lines", ""])
    lines.extend(f"- U{x['index']:03d} | {x['excerpt']}" for x in data.person)
    lines.extend(["", "## Approval lines", ""])
    lines.extend(f"- U{x['index']:03d} | {x['excerpt']}" for x in data.approvals)
    lines.extend(["", "## Recorded turns", ""])
    lines.extend(f"- U{x['index']:03d} | comment {x['comment_id']} | task {x['task_id']} | {x['excerpt']}"
                 for x in data.person if x["recorded"])
    lines.extend(["", "## Unrecorded turns", ""])
    lines.extend(f"- U{x['index']:03d} | {x['excerpt']}" for x in data.person if not x["recorded"])
    write_private(target, "\n".join(lines) + "\n")


def tracker_statuses(ids: set[str], preferred: Path) -> dict[str, str]:
    """Read the preferred tracker first, then the other tracker for absent IDs."""
    statuses: dict[str, str] = {}
    for db in (preferred, *(p for p in TRACKERS if p != preferred)):
        remaining = sorted(ids - statuses.keys())
        if not remaining or not db.exists():
            continue
        with _fox_person.connect(f"file:{db}?mode=ro", uri=True) as conn:
            for task_id, status in conn.execute(
                f"SELECT id, status FROM tasks WHERE id IN ({','.join('?' for _ in remaining)})", remaining
            ):
                statuses[task_id] = status
    return statuses


def file_group(raw: str, handoff: Path) -> tuple[str, Path | None]:
    """Classify a written path, resolving workspace paths beside the handoff."""
    if raw.endswith("/"):
        return "excluded", None
    if raw.startswith("~/"):
        path = Path.home() / raw[2:]
    else:
        path = Path(raw)
    if not path.is_absolute():
        if "scratchpad" in path.parts or path.name.endswith(".coverage.md"):
            return "excluded", None
        if path.parts[0] in SCORED_DIRS:
            path = handoff.parent.parent / path
        else:
            return "other", None
    path = path.resolve(strict=False)
    roots = ((_fox_paths.portfolio()), _fox_paths.system_home(), _fox_paths.state())
    root = next((r for r in roots if path.is_relative_to(r)), None)
    if root is None or "scratchpad" in path.parts or path.name in {"log.md", "HOME.md"}:
        return "excluded", path
    if path == handoff.resolve(strict=False) or path.name.endswith(".coverage.md"):
        return "excluded", path
    return ("scored" if any(part in SCORED_DIRS for part in path.relative_to(root).parts[:-1]) else "other"), path


def mentioned(path: str, canonical: Path, text: str, handoff: Path) -> bool:
    root = Path.home()
    candidates = {path, str(canonical)}
    if canonical.is_relative_to(root):
        candidates.add("~/" + str(canonical.relative_to(root)))
    for base in (_fox_paths.portfolio(), _fox_paths.system_home(), _fox_paths.system_home(),
                 _fox_paths.system_home() / "skillwright", root / ".agents", handoff.parent.parent):
        if canonical.is_relative_to(base):
            candidates.add(str(canonical.relative_to(base)))
    if any(candidate in text for candidate in candidates):
        return True
    for candidate in candidates:
        if candidate.endswith(".md") and re.search(r"\[\[" + re.escape(candidate[:-3]) + r"(?:\||\]\])", text):
            return True
    patterns = re.findall(r"[\w./~*-]+(?:/[\w./~*-]+)+", text)
    return any("*" in pattern and fnmatch.fnmatch(candidate, pattern)
               for pattern in patterns for candidate in candidates)


def coverage(data: Extract, handoff: Path, db: Path | None = None) -> dict:
    text = handoff.read_text(encoding="utf-8")
    preferred = db or (TRACKERS[0])
    task_ids = {x for x in data.ids if SCORED_TASK.fullmatch(x)}
    statuses = tracker_statuses(task_ids, preferred)
    open_ids = {x for x in task_ids if statuses.get(x) in {"todo", "in-progress", "blocked", "in-review"}}
    missing = {x for x in task_ids if not re.search(rf"(?<![\w-]){re.escape(x)}(?![\w-])", text)}
    ids = sorted(missing & open_ids)
    done = sorted(x for x in missing if statuses.get(x) in {"done", "accepted", "canceled", "superseded"})
    backlog = sorted(x for x in missing if statuses.get(x) == "backlog")
    unknown = sorted(x for x in missing if x not in statuses)
    rows = sorted(x for x in data.ids if ROW_ID.match(x))
    scored_files: dict[Path, str] = {}
    other_files: list[str] = []
    for raw in sorted(data.files):
        group, canonical = file_group(raw, handoff)
        if group == "scored" and canonical is not None:
            scored_files.setdefault(canonical, raw)
        elif group == "other":
            other_files.append(raw)
    files = sorted(raw for path, raw in scored_files.items() if not mentioned(raw, path, text, handoff))
    id_percent = 100 if not open_ids else round(100 * (len(open_ids) - len(ids)) / len(open_ids))
    file_percent = 100 if not scored_files else round(100 * (len(scored_files) - len(files)) / len(scored_files))
    row_counts = {prefix: sum(x.startswith(prefix) for x in rows) for prefix in ("R-", "B-", "I-")}
    lines = [f"# Handoff coverage: {data.session}", "",
             f"Open work missing: {len(ids)} tasks, {len(files)} files.",
             f"Task ID coverage: {id_percent}% ({len(open_ids)-len(ids)}/{len(open_ids)})",
             f"File coverage: {file_percent}% ({len(scored_files)-len(files)}/{len(scored_files)})",
             f"Handoff: {handoff}", "", "## Missing task IDs", ""]
    lines.extend(f"- {x} ({statuses[x]})" for x in ids)
    lines.extend(["", "## Missing files", ""])
    lines.extend(f"- {x}" for x in files)
    lines.extend(["", "## Done, in rows (not scored)", ""])
    lines.extend(f"- {x} ({statuses[x]})" for x in done)
    lines.extend(["", "## Backlog, in rows (not scored)", ""])
    lines.extend(f"- {x}" for x in backlog)
    lines.extend(["", "## Not in a tracker", ""])
    lines.extend(f"- {x}" for x in unknown)
    lines.extend(["", f"## Rows already recorded (not scored): R {row_counts['R-']}, B {row_counts['B-']}, I {row_counts['I-']}", ""])
    lines.extend(f"- {x}" for x in rows)
    lines.extend(["", "## Other files written (not scored)", ""])
    lines.extend(f"- {x}" for x in other_files)
    lines.extend(["", f"## {_fox_person.display_name()} lines with missing task IDs", ""])
    lines.extend(f"- U{x['index']:03d} | {x['excerpt']}" for x in data.person if set(TASK.findall(x['text'])) & set(ids))
    lines.extend(["", "## Approval lines with missing task IDs", ""])
    lines.extend(f"- U{x['index']:03d} | {x['excerpt']}" for x in data.approvals if set(TASK.findall(x['text'])) & set(ids))
    target = handoff.with_name(handoff.name + ".coverage.md")
    section = "\n".join(lines) + "\n"
    # The coverage page sits beside the handoff and is read like it, so it stays 0644.
    write_private(target, section, 0o644)
    return {"id_percent": id_percent, "file_percent": file_percent, "missing_ids": ids, "missing_files": files}


def worker_report(data: Extract, out: Path) -> None:
    groups: dict[str, list[dict]] = defaultdict(list)
    for command in data.commands:
        groups[command["task"]].append(command)
    lines = [f"# Worker did: {data.session}", "", f"Model: {data.model}", ""]
    for task, commands in groups.items():
        lines.extend([f"## {task}", ""])
        lines.extend(f"{i}. {c['outcome']}: {c['command']}" for i, c in enumerate(commands, 1))
        lines.append("")
    write_private(report_path(out, "worker-did.md"), "\n".join(lines))


def run_result(db: Path, session: str) -> str:
    with _fox_person.connect(f"file:{db}?mode=ro", uri=True) as conn:
        count = conn.execute("SELECT count(*) FROM runs WHERE session LIKE ? AND result IS NOT NULL", (session + "%",)).fetchone()[0]
    return "ok" if count else "missing"


def backfill(db: Path, dry_run: bool) -> tuple[list[str], Path | None]:
    with _fox_person.connect(f"file:{db}?mode=ro", uri=True) as conn:
        rows = conn.execute("SELECT id, session FROM runs WHERE model='unknown' AND session IS NOT NULL").fetchall()
    updates = []
    models: dict[str, str] = {}
    for row_id, session in rows:
        if not session or len(session) < 13:
            continue
        if session not in models:
            try:
                models[session] = parse(transcript(session)).model
            except ValueError:
                models[session] = "unknown"
        model = models[session]
        if model != "unknown" and not SECRET.search(model):
            updates.append((row_id, model))
    def quote(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    statements = [f"UPDATE runs SET model={quote(model)} WHERE id={quote(row_id)} AND model='unknown';"
                  for row_id, model in updates]
    backup = None
    if updates and not dry_run:
        backup = db.with_name(db.name + ".backup-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
        # sqlite opens its target by name and follows links. Back up inside a new private folder
        # (mkdtemp: 0700, unique), then move the finished 0600 file to the backup name.
        staging = Path(tempfile.mkdtemp(prefix="." + backup.name + ".", dir=str(db.parent)))
        partial = staging / "partial.sqlite"
        try:
            with _fox_person.connect(f"file:{db}?mode=ro", uri=True) as source, \
                    _fox_person.connect(partial) as target:
                source.backup(target)
            target.close()
            os.chmod(partial, 0o600)
            os.replace(partial, backup)
        finally:
            for leftover in staging.iterdir():
                leftover.unlink()
            staging.rmdir()
        with _fox_person.connect(db) as conn:
            conn.executemany("UPDATE runs SET model=? WHERE id=? AND model='unknown'", [(m, i) for i, m in updates])
    return statements, backup


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session")
    parser.add_argument("--handoff-only", action="store_true", help="check handoff readability when no transcript is supplied")
    parser.add_argument("--transcript", type=Path,
                        help="read this transcript file instead of looking the session up")
    parser.add_argument("--tail-bytes", type=int,
                        help="bound a hook check to complete records in the final N transcript bytes")
    parser.add_argument("--handoff", type=Path)
    parser.add_argument("--kind", choices=("lead", "worker", "oneshot"), default="lead")
    parser.add_argument("--db", type=Path, action="append")
    parser.add_argument("--rate", action="store_true")
    parser.add_argument("--since", type=datetime.fromisoformat)
    parser.add_argument("--match-window-hours", type=float, default=24,
                        help=f"maximum hours after each long {_fox_person.display_name()} turn for a row to match (default: 24)")
    parser.add_argument("--backfill-model", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--settlements", action="store_true",
                        help="read-only: print settlement turns as JSON, each with its row or none")
    args = parser.parse_args(argv)
    if args.handoff_only:
        try:
            if not args.handoff or not args.handoff.read_text(encoding='utf-8').strip():
                raise ValueError('handoff is empty or absent')
            print('Handoff readable: ' + str(args.handoff) + '. Supply a transcript to check coverage.')
            return 0
        except (OSError, ValueError) as error:
            print('Handoff check: ' + str(error))
            return 1
    if args.tail_bytes is not None and args.tail_bytes <= 0:
        parser.error("--tail-bytes must be positive")
    if not 0 < args.match_window_hours <= 24:
        parser.error("--match-window-hours must be greater than 0 and at most 24")
    if not args.session and not args.transcript and args.handoff and args.handoff.is_file():
        frontmatter = args.handoff.read_text(encoding="utf-8")[:4096]
        match = re.search(r"(?m)^session:\s*['\"]?([0-9a-f-]{13,})", frontmatter)
        if match:
            args.session = match.group(1)
    if not args.session and not args.transcript:
        parser.error("--session or --transcript is required")
    db = args.db[0] if args.db else None
    try:
        path = args.transcript.expanduser() if args.transcript else transcript(args.session)
        if not path.is_file():
            raise OSError(f"transcript not found: {path}")
        cutoff, previous = handoff_window(path, args.handoff, args.tail_bytes) if args.kind == "lead" and args.handoff else (None, None)
        since = args.since or previous
        if args.settlements:
            data = parse(path, cutoff, args.tail_bytes)
            report = settlements_report(data, tuple(args.db) if args.db else TRACKERS, since, cutoff,
                                        args.match_window_hours)
            print(json.dumps(report, indent=2))
            return 1 if report["unpromoted"] else 0
        if args.rate:
            data = parse(path, tail_bytes=args.tail_bytes)
            mark_recorded(data, tuple(args.db) if args.db else TRACKERS, args.match_window_hours)
            rate_report(data, args.since)
            return 0
        data = parse(path, cutoff, args.tail_bytes)
        mark_recorded(data, tuple(args.db) if args.db else TRACKERS, args.match_window_hours)
        out = args.out or OUT_ROOT / data.session[:13]
        write_extract(data, out)
        print(f"session={data.session} model={data.model} ids={len(data.ids)} files={len(data.files)} extract={report_path(out, 'extract.md')}")
        if args.tail_bytes is not None:
            print(f"Transcript scope: final {args.tail_bytes} bytes; run without --tail-bytes for full-session coverage.")
        if args.kind == "lead" and args.handoff:
            result = coverage(data, args.handoff, db)
            print(f"coverage ids={result['id_percent']}% files={result['file_percent']}% gaps={len(result['missing_ids'])+len(result['missing_files'])}")
            report = settlements_report(data, tuple(args.db) if args.db else TRACKERS, since, cutoff,
                                        args.match_window_hours)
            print(f"settlements={report['settlements']} recorded={len(report['promoted'])} unpromoted={len(report['unpromoted'])} warnings={len(report['warnings'])} date_mismatch={len(report['date_mismatch'])}")
            print("Rows written after this handoff cannot clear a failure until the handoff is written again.")
            for item in report["unpromoted"]:
                print(f"UNPROMOTED {item['local_time']} | {item['text']}")
            for item in report["warnings"]:
                print(f"WARNING {item['local_time']} | {item['warning']} | {item['text'][:160]}")
            for item in report["date_mismatch"]:
                print(f"DATE MISMATCH {item['local_time']} | row {item['row_kind']} {item['row_id']} at {item['row_time']} | {item['text'][:160]}")
            if report["unpromoted"] or report["date_mismatch"]:
                return 1
        elif args.kind == "worker":
            worker_report(data, out)
            print(f"worker={report_path(out, 'worker-did.md')}")
        elif args.kind == "oneshot":
            if not db:
                parser.error("--db is required for oneshot")
            print(run_result(db, data.session))
        if args.backfill_model:
            if not db:
                parser.error("--db is required for --backfill-model")
            statements, backup = backfill(db, args.dry_run)
            backfill_report = report_path(out, "backfill-model.md")
            write_private(backfill_report, "\n".join([
                "# Model backfill", "", f"Tracker: {db}",
                f"Mode: {'dry run' if args.dry_run else 'applied'}",
                f"Rows: {len(statements)}", f"Backup: {backup or 'none'}", "",
                "## Updates", "", *[f"- `{statement}`" for statement in statements], "",
            ]))
            print("\n".join(statements))
            print(f"backfill_rows={len(statements)} backup={backup or 'none'} report={backfill_report}")
        return 0
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"handoff_check: {exc}", file=sys.stderr)
        return 0 if args.rate else 1


if __name__ == "__main__":
    raise SystemExit(main())
