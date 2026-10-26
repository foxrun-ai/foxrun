#!/usr/bin/env python3
"""Tag typed user turns from the source-note inventory with recorded Jev judgments."""

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
import os
import json
import re
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

from handoff_check import Extract, TASK, TRACKERS, call_input, recorded_match, text_blocks, words

HOME = Path.home()
INVENTORY = (_fox_paths.system_home() / 'history/outputs/session-inventory.md')
REPORT = (_fox_paths.system_home() / 'history/outputs/turn-tagging.md')
RUNNER = Path(os.environ["FOXRUN_JEV_RUNNER"]).expanduser() if os.environ.get("FOXRUN_JEV_RUNNER") else None
KINDS = ("instruction", "ruling", "approval", "feedback", "question", "chatter")
PRIVATE = re.compile(r"\$\s*\d|\b(?:payment|paid|invoice|bank|card|shipping|shipment|shipbob|tracking|address|fulfill|refund|SKU)\b", re.I)
TASK_ID = re.compile(r"(?<![\w-])T\d+(?![\w-])")


def inventory_rows(path: Path) -> list[dict]:
    runtime = None
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line in ("## Claude", "## Codex"):
            runtime = line[3:]
        elif line.startswith("## "):
            runtime = None
        elif runtime and line.startswith("| ") and not line.startswith(("| ID", "|---")):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) != 12 or not cells[5].isdigit() or int(cells[5]) < 1:
                continue
            rows.append({"runtime": runtime, "session": cells[0].split(";")[0].strip(),
                         "title": cells[8], "cwd": cells[7],
                         "handoffs": [item.strip() for item in cells[10].split(",")
                                                    if item.strip() != "—" and not item.strip().endswith(".coverage.md")]})
    return rows


def transcript_index() -> dict[str, Path]:
    paths = [* (HOME / ".claude/projects").rglob("*.jsonl"),
             * (HOME / ".codex/sessions").rglob("*.jsonl")]
    index = {}
    for path in paths:
        name = path.stem.removeprefix("rollout-")
        match = re.search(r"(?:[0-9a-f]{8}-[0-9a-f-]{27,}|agent-[0-9a-f]+)$", name)
        if match:
            index[match.group()] = path
    return index


def next_call_task(name: str, raw: object) -> str | None:
    args = call_input(raw)
    strings = [name, *[value for value in args.values() if isinstance(value, str)]]
    for value in strings:
        if hit := TASK_ID.search(value):
            return hit.group()
    return None


def extract_turns(row: dict, path: Path) -> list[dict]:
    data = Extract(row["session"], row["runtime"].lower())
    pending = None
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row["runtime"] == "Claude":
                msg = event.get("message")
                if not isinstance(msg, dict):
                    continue
                if event.get("type") == "user":
                    content = msg.get("content")
                    if isinstance(content, list) and any(isinstance(x, dict) and x.get("type") == "tool_result" for x in content):
                        continue
                    before = len(data.person)
                    data.add_user_turn(content)
                    if len(data.person) > before:
                        turn = data.person[-1]
                        turn["timestamp"] = event.get("timestamp") or "—"
                        turn["task_id"] = next(iter(TASK_ID.findall(turn["text"])), None)
                        turn["excerpt"] = turn["text"][:300]
                        pending = turn if not turn["task_id"] else None
                elif event.get("type") == "assistant" and pending and isinstance(msg.get("content"), list):
                    for block in msg["content"]:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            pending["task_id"] = next_call_task(str(block.get("name", "")), block.get("input"))
                            pending = None
                            break
            else:
                payload = event.get("payload")
                if not isinstance(payload, dict) or event.get("type") != "response_item":
                    continue
                if payload.get("type") == "message" and payload.get("role") == "user":
                    before = len(data.person)
                    data.add_user_turn(payload.get("content"))
                    if len(data.person) > before:
                        turn = data.person[-1]
                        turn["timestamp"] = event.get("timestamp") or "—"
                        turn["task_id"] = next(iter(TASK_ID.findall(turn["text"])), None)
                        turn["excerpt"] = turn["text"][:300]
                        pending = turn if not turn["task_id"] else None
                elif pending and payload.get("type") in ("custom_tool_call", "function_call"):
                    pending["task_id"] = next_call_task(str(payload.get("name", "")),
                                                         payload.get("input", payload.get("arguments")))
                    pending = None
    return data.person


def tracker_data() -> tuple[list[tuple[str, str, str]], dict[str, dict[str, str]]]:
    comments = []
    titles = {}
    for db in TRACKERS:
        with _fox_person.connect(f"file:{db}?mode=ro", uri=True) as conn:
            comments.extend(conn.execute("SELECT id, subject_id, body FROM comments WHERE body LIKE ?", (_fox_person.display_name() + ":%",)).fetchall())
            titles[db.parent.name] = dict(conn.execute("SELECT id, title FROM tasks").fetchall())
    return comments, titles


def recorded(turn: dict, comments: list[tuple[str, str, str]]) -> bool:
    return any(recorded_match(turn["text"], body) for _, _, body in comments)


def task_title(row: dict, task_id: str | None, titles: dict[str, dict[str, str]]) -> str | None:
    if not task_id:
        return None
    portfolio = _fox_paths.portfolio()
    try:
        preferred = Path(row['cwd']).relative_to(portfolio).parts[0]
    except (ValueError, IndexError):
        preferred = _fox_person.workspace()
    ordered = [preferred, *sorted(name for name in titles if name != preferred)]
    return next((titles.get(name, {}).get(task_id) for name in ordered if titles.get(name, {}).get(task_id)), None)


def request(row: dict, turn: dict, title: str | None, base_id: str, retry: int = 0) -> dict:
    task_id = turn["task_id"]
    # This bound stays below 2K tokens for ordinary prose and keeps one turn only.
    bounded = turn["text"][:4000]
    return {
        "action": "evaluate",
        "request_id": base_id + (f"-retry{retry}" if retry else ""),
        "use_case": "turn-tagging",
        "request_schema_version": "1",
        "question_set_version": "v1",
        "state_schema_version": "v1",
        "state": {"turn": bounded, "task_id": task_id, "task_title": title},
        "questions": {
            "kind": {"type": "choice", "instructions": "Classify this user turn by its main purpose. Choose one kind.",
                     "criteria": {"instruction": "Tells the agent what to do or how to do it",
                                  "ruling": "Makes a decision or sets a rule",
                                  "approval": "Authorizes a proposed action",
                                  "feedback": "Corrects or evaluates work or a response",
                                  "question": "Asks for information or clarification",
                                  "chatter": "Social talk or incidental content"}},
            "durable": {"type": "boolean", "instructions":
                        f"Does this turn state something that holds beyond the current task: a rule, a preference, a decision, or a fact about {_fox_person.display_name()} or his business?"}
        },
        "output_ref": str(REPORT),
        "storage": {"database": str(TRACKERS[0]), "required": True},
    }


def evaluate(row: dict, turn: dict, titles: dict[str, dict[str, str]]) -> dict:
    if len(words(turn["text"])) < 5:
        return {"kind": "chatter", "p": 1.0, "durable": False, "durable_p": 0.0}
    title = task_title(row, turn["task_id"], titles)
    previous_title = next((entries.get(turn['task_id']) for entries in titles.values() if entries.get(turn['task_id'])), None)
    suffix = "-titlefix" if title != previous_title else ""
    base_id = f"source-note-turn-tag-v1-{row['session']}-{turn['index']:04d}{suffix}"
    with _fox_person.connect(f"file:{TRACKERS[0]}?mode=ro", uri=True) as conn:
        previous = conn.execute(
            "SELECT request_id, status, result_json FROM jev_runs WHERE request_id=? OR request_id LIKE ?",
            (base_id, base_id + "-retry%"),
        ).fetchall()
    for _, status, result in previous:
        if status == "succeeded" and result:
            answers = json.loads(result)["answers"]
            kind = answers["kind"]["choice"]
            return {"kind": kind, "p": answers["kind"]["probabilities"][kind],
                    "durable": answers["durable"]["probability"] >= 0.5,
                    "durable_p": answers["durable"]["probability"]}
    retry = 0 if not previous else max(
        [0, *[int(match.group(1)) for request_id, _, _ in previous
               if (match := re.search(r"-retry(\d+)$", request_id))]]
    ) + 1
    for attempt in range(6):
        # The gateway rate limits short bursts. One paced request keeps the run resumable.
        time.sleep(0.5 if attempt == 0 else min(60, 15 * attempt))
        result = subprocess.run(["node", str(RUNNER)], input=json.dumps(request(row, turn, title, base_id, retry)),
                                text=True, capture_output=True, timeout=90, check=False)
        try:
            output = json.loads(result.stdout)
        except json.JSONDecodeError:
            output = {}
        if result.returncode == 0 and output.get("answers"):
            answers = output["answers"]
            kind = answers["kind"]["choice"]
            probability = answers["kind"].get("probabilities", {}).get(kind)
            durable_p = answers["durable"]["probability"]
            if kind not in KINDS or probability is None:
                raise RuntimeError(f"invalid Jev answer: {row['session']} turn {turn['index']}")
            return {"kind": kind, "p": probability, "durable": durable_p >= 0.5, "durable_p": durable_p}
        error = output.get("error", {})
        code = error.get("code") if isinstance(error, dict) else None
        if code not in ("provider_failed", "provider_timeout", "provider_rate_limited", "storage_failed"):
            break
        retry += 1
    raise RuntimeError(f"Jev {code or 'failed'}: {row['session']} turn {turn['index']}")


def to_codify_ids(handoff: str) -> set[str]:
    path = (_fox_paths.portfolio()) / handoff
    if not path.is_file():
        return set()
    text = path.read_text(encoding="utf-8")
    match = re.search(r"(?ms)^## To codify\s*\n(.*?)(?=^## |\Z)", text)
    return set(TASK_ID.findall(match.group(1))) if match else set()


def safe_excerpt(value: str) -> str:
    if PRIVATE.search(value):
        return "[payment or shipping details omitted]"
    return value.replace("|", "\\|").replace("\n", " ").strip()


def make_report(rows: list[dict]) -> tuple[int, int]:
    lines = ["---", "type: output", 'workspace: ' + _fox_person.workspace('system'), "timestamp: 2026-09-24", "session: source-note", 'agent: ' + os.environ.get('FOXRUN_MODEL', 'configured'), "---", "", "# source-note Jev Turn Tagging", "",
             "One Jev request tagged each eligible typed user turn. Turns under five words were tagged chatter in code.",
             f"Recorded means a {_fox_person.display_name()}: comment shares six consecutive words or quotes the turn. P is Jev's probability for the selected kind.", ""]
    flagged = 0
    unrecorded = 0
    for runtime in ("Claude", "Codex"):
        lines.extend([f"## {runtime}", "", "| Session | Title | Turns | Instruction | Ruling | Approval | Feedback | Question | Chatter | Durable | Durable-unrecorded | Handoff | Flag |", "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|"])
        for row in (r for r in rows if r["runtime"] == runtime):
            counts = Counter(turn["kind"] for turn in row["turns"])
            durable = [turn for turn in row["turns"] if turn["durable"]]
            missing = [turn for turn in durable if not turn["recorded"]]
            ids = {turn["task_id"] for turn in durable if turn["task_id"]}
            handoffs = row["handoffs"]
            flags = []
            if durable and not handoffs:
                flags.append("no handoff")
            if durable and handoffs and not any(ids & to_codify_ids(path) for path in handoffs):
                flags.append("To codify misses durable task IDs")
            flagged += bool(flags)
            unrecorded += len(missing)
            row["missing"] = missing
            row["flags"] = flags
            title = safe_excerpt(row["title"])
            lines.append(f"| {row['session']} | {title} | {len(row['turns'])} | " + " | ".join(str(counts[k]) for k in KINDS) +
                         f" | {len(durable)} | {len(missing)} | {'yes' if handoffs else 'no'} | {', '.join(flags) or '—'} |")
        lines.append("")
    lines.extend(["## Durable and unrecorded turns", ""])
    for row in rows:
        if not row["missing"]:
            continue
        lines.extend([f"### {row['runtime']} {row['session']}", "", "| Turn | Time | Excerpt | Kind | P | Task ID |", "|---|---|---|---|---:|---|"])
        for turn in row["missing"]:
            lines.append(f"| U{turn['index']:03d} | {turn['timestamp']} | {safe_excerpt(turn['excerpt'])} | {turn['kind']} | {turn['p']:.2f} | {turn['task_id'] or '—'} |")
        lines.append("")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return unrecorded, flagged


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="Process first N sessions for a local check")
    parser.add_argument("--inventory", type=Path, default=INVENTORY)
    args = parser.parse_args()
    if RUNNER is None or not RUNNER.is_file():
        print("Jev is optional. Set FOXRUN_JEV_RUNNER to its runner file to use turn_tag.py.", file=sys.stderr)
        return 2
    if not args.inventory.is_file():
        print("Inventory missing. Supply --inventory PATH.", file=sys.stderr)
        return 2
    rows = inventory_rows(args.inventory)
    if args.limit:
        rows = rows[:args.limit]
    paths = transcript_index()
    comments, titles = tracker_data()
    missing_paths = [row["session"] for row in rows if row["session"] not in paths]
    if missing_paths:
        raise RuntimeError(f"missing transcripts: {', '.join(missing_paths)}")
    for row in rows:
        row["turns"] = extract_turns(row, paths[row["session"]])
        for turn in row["turns"]:
            turn["recorded"] = recorded(turn, comments)
    jobs = [(row, turn) for row in rows for turn in row["turns"]]
    for count, (row, turn) in enumerate(jobs, 1):
        turn.update(evaluate(row, turn, titles))
        if count % 25 == 0 or count == len(jobs):
            print(f"tagged {count}/{len(jobs)} turns", file=sys.stderr, flush=True)
    unrecorded, flagged = make_report(rows)
    print(json.dumps({"sessions": len(rows), "turns": len(jobs), "durable_unrecorded": unrecorded,
                      "flagged_sessions": flagged, "report": str(REPORT)}))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
        print(f"turn_tag: {error}", file=sys.stderr)
        raise SystemExit(1)
