#!/usr/bin/env python3
"""Second pass for contract lint: three judgment questions for Jev, one request per section.

The lint runs this only with --judgment. Nothing here runs in the exact checks.
The Jev runner is the command the caller names; this file never reads a secret.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess

QUESTION_SET = "contract-judgment-v1"
STATE_SCHEMA = "contract-section-v1"
THRESHOLD = 0.5
MAX_SECTION_LINES = 40
QUESTIONS = {
    "contradiction": {"type": "boolean", "instructions": "Does a sentence in this section contradict another sentence in this section?"},
    "filler": {"type": "boolean", "instructions": "Does this section hold a filler sentence: one that gives the agent nothing to do, to check, or to know?"},
    "invented_term": {"type": "boolean", "instructions": "Does this section use a label that is not in the word list and is not explained in the same sentence?"},
}


class JudgmentError(ValueError):
    """The judgment pass cannot run as asked."""


def words(files: list[Path]) -> list[str]:
    """The approved words: every bold term and every heading in the word files."""
    found = set()
    for path in files:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            heading = re.match(r"^#{1,6}\s+(.*?)\s*#*\s*$", line)
            if heading:
                found.add(heading.group(1).strip())
            found.update(term.strip().rstrip(":").strip() for term in re.findall(r"\*\*([^*\n]+)\*\*", line))
    return sorted(word for word in found if word)


def sections(lines: list[str]) -> list[tuple[int, str, list[str]]]:
    """Cut a contract into sections at its headings: (first line, heading, lines). Frontmatter is left out."""
    start = 0
    if lines and lines[0].strip() == "---":
        start = next((index + 1 for index in range(1, len(lines)) if lines[index].strip() in {"---", "..."}), 0)
    result: list[tuple[int, str, list[str]]] = []
    current: tuple[int, str, list[str]] | None = None
    for number, line in enumerate(lines[start:], start + 1):
        heading = re.match(r"^#{1,6}\s+(.*?)\s*#*\s*$", line)
        if heading or current is None or len(current[2]) >= MAX_SECTION_LINES:
            current = (number, heading.group(1) if heading else (current[1] if current else "(top)"), [])
            result.append(current)
        current[2].append(line)
    return [item for item in result if any(line.strip() and not line.lstrip().startswith("#") for line in item[2])]


def build_request(contracts: list[tuple[str, str]], word_list: list[str], database: Path | None = None) -> dict:
    """One Jev batch: one evaluate request per section, with a request id made from its exact input."""
    requests = []
    for file, text in contracts:
        for first_line, heading, body in sections(text.splitlines()):
            state = {"file": file, "first_line": first_line, "heading": heading, "section": "\n".join(body), "words": word_list}
            digest = hashlib.sha256(json.dumps([QUESTION_SET, state], sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
            request = {
                "action": "evaluate",
                "request_id": "contract-judgment-" + digest[:24],
                "use_case": "contract lint judgment",
                "request_schema_version": "1",
                "question_set_version": QUESTION_SET,
                "state_schema_version": STATE_SCHEMA,
                "state": state,
                "questions": QUESTIONS,
            }
            if database is not None:
                request["storage"] = {"database": str(database), "required": True}
            requests.append(request)
    return {"action": "batch", "requests": requests}


def rows(request: dict, progress_lines: list[str]) -> list[dict]:
    """Turn the runner's answer lines into lint rows: a finding for each yes, a not-checked row for each gap."""
    answers = {}
    for line in progress_lines:
        if line.strip():
            entry = json.loads(line)
            answers[entry.get("request_id")] = entry
    result = []
    for item in request["requests"]:
        state = item["state"]
        entry = answers.get(item["request_id"])
        given = entry.get("result", {}).get("answers", {}) if entry and entry.get("ok") is True else None
        for name in QUESTIONS:
            probability = given.get(name, {}).get("probability") if given else None
            base = {"file": state["file"], "line": state["first_line"], "target": state["heading"]}
            if not isinstance(probability, (int, float)) or isinstance(probability, bool):
                result.append({**base, "rule": "judgment_" + name, "severity": "info", "state": "uncheckable", "resolution_evidence": "Jev gave no answer for request " + item["request_id"]})
            elif probability >= THRESHOLD:
                result.append({**base, "rule": "judgment_" + name, "severity": "warning", "state": "invalid", "resolution_evidence": f"Jev probability {probability:.2f}; question set {QUESTION_SET}"})
    return result


def run(report: dict, *, command: str | None, directory: Path | None, word_files: list[Path], database: Path | None = None) -> dict:
    """Ask Jev about every scanned contract and add its answers to the lint report."""
    if not command or directory is None or not word_files:
        raise JudgmentError("--judgment needs --judgment-command, --judgment-dir, and at least one --judgment-words")
    directory = Path(directory).expanduser().resolve()
    vault = Path(report["vault_root"])
    if not directory.is_dir() or directory == vault or directory.is_relative_to(vault):
        raise JudgmentError("--judgment-dir must be an existing folder outside the vault")
    request_path, progress_path = directory / "request.json", directory / "progress.jsonl"
    if request_path.exists() or progress_path.exists():
        raise JudgmentError("--judgment-dir already holds a request or answers; nothing was overwritten")
    contracts = []
    for item in report["scanned"]:
        path = Path(item["file"]) if Path(item["file"]).is_absolute() else vault / item["file"]
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise JudgmentError("contract changed during the lint: " + item["file"])
        contracts.append((item["file"], raw.decode("utf-8-sig")))
    request = build_request(contracts, words(word_files), database)
    request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    completed = subprocess.run([*shlex.split(command), "--progress", str(progress_path), str(request_path)], capture_output=True, text=True, check=False)
    lines = progress_path.read_text(encoding="utf-8").splitlines() if progress_path.is_file() else []
    if not lines and completed.returncode != 0:
        raise JudgmentError("the Jev runner failed with exit " + str(completed.returncode) + " and wrote no answers")
    for row in rows(request, lines):
        report["unchecked" if row["state"] == "uncheckable" else "findings"].append(row)
    for name in ("findings", "unchecked"):
        report[name].sort(key=lambda item: (item["file"], item["line"], item["rule"], item["target"]))
        report["summary"][name] = len(report[name])
    report["judgment"] = {"question_set": QUESTION_SET, "requests": len(request["requests"]), "request": str(request_path), "answers": str(progress_path)}
    return report
