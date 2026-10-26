#!/usr/bin/env python3
"""Parse a legacy workspace log.md into staged JSONL without changing the source."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


INLINE = re.compile(
    r"^-\s+(?P<date>\d{4}-\d{2}-\d{2}T\S+)\s+[—-]\s+"
    r"(?P<tag>[^·]+?)\s+·\s+agent:\s*(?P<agent>[^·]+?)\s+·\s+(?P<body>.+)$"
)
HEADING = re.compile(r"^#{2,3}\s+(.+?)\s*$")
DATED_HEADING = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2}(?:T\S+|(?:\s+\d{1,2}:\d{2}(?:\s+[A-Z]{2,5})?)?)?)"
    r"\s+(?:—|-)\s+(?P<title>.+)$"
)
DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}(?:T\S+)?$")
TAG = re.compile(r"^\s*-\s*\[([^]]+)\]", re.M)
TIMESTAMP_FIELD = re.compile(r"^\s*-\s*\[timestamp\]\s+(.+?)\s*$", re.M | re.I)
AGENT = re.compile(r"\bagent(?:\s*[:=]|\s+)([A-Za-z0-9_-]+)", re.I)
ARTIFACT_MARKER = re.compile(r"^\s*<!--\s*workspace-artifact:[^>]+-->\s*$")


def title_from_body(body: str) -> str:
    text = re.sub(r"^\s*-\s*\[[^]]+\]\s*", "", body.strip())
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    sentence = re.split(r"(?<=[.!?])\s+", first, maxsplit=1)[0]
    return sentence[:160]


def entry(date: str | None, agent: str | None, tag: str, title: str, body: str, start: int, end: int) -> dict[str, object]:
    return {
        "date": date,
        "agent": agent,
        "tag": tag.strip(),
        "title": title.strip(),
        "body": body.strip(),
        "source_line_range": {"start": start, "end": end},
    }


def heading_entry(lines: list[str], start: int, heading_line: int, end: int) -> dict[str, object]:
    heading = HEADING.match(lines[heading_line - 1]).group(1)
    match = DATED_HEADING.match(heading)
    if match:
        date = match.group("date")
        title = match.group("title")
    elif DATE_ONLY.match(heading):
        date = heading
        title = ""
    else:
        date = None
        title = heading
    body_lines = lines[start - 1:heading_line - 1] + lines[heading_line:end]
    body = "\n".join(body_lines).strip()
    timestamp = TIMESTAMP_FIELD.search(body)
    if date is None and timestamp:
        date = timestamp.group(1).strip()
    agent_match = AGENT.search(body)
    agent = agent_match.group(1) if agent_match else None
    tag_match = TAG.search(body)
    if tag_match:
        tag = tag_match.group(1)
    elif title.casefold() == "workspace checkpoint":
        tag = "checkpoint"
    elif title.casefold() == "note-create":
        tag = "note-create"
    else:
        tag = "history"
    return entry(date, agent, tag, title, body, start, end)


def inline_entry(lines: list[str], start: int, end: int, match: re.Match[str]) -> dict[str, object]:
    body = match.group("body")
    continuation = "\n".join(lines[start:end]).strip()
    if continuation:
        body += "\n" + continuation
    return entry(
        match.group("date"), match.group("agent"), match.group("tag"),
        title_from_body(match.group("body")), body, start, end,
    )


def validate_partition(
    line_count: int,
    entries: list[dict[str, object]],
    unaccounted: list[tuple[int, str]],
) -> None:
    """Require every source line to have exactly one owner."""
    owners = [0] * (line_count + 1)
    for item in entries:
        source_range = item["source_line_range"]
        start = source_range["start"]
        end = source_range["end"]
        if not (1 <= start <= end <= line_count):
            raise RuntimeError(f"invalid source range: {start}-{end}")
        for number in range(start, end + 1):
            owners[number] += 1
    for number, _line in unaccounted:
        if not 1 <= number <= line_count:
            raise RuntimeError(f"invalid unaccounted line: {number}")
        owners[number] += 1
    bad = [number for number in range(1, line_count + 1) if owners[number] != 1]
    if bad:
        details = ", ".join(f"{number} ({owners[number]} owners)" for number in bad[:10])
        raise RuntimeError(f"source partition failed: {details}")


def parse_log(text: str) -> tuple[list[dict[str, object]], list[tuple[int, str]]]:
    lines = text.splitlines()
    entries: list[dict[str, object]] = []
    starts: list[tuple[int, int, str, re.Match[str]]] = []

    for number, line in enumerate(lines, 1):
        inline = INLINE.match(line)
        if inline:
            starts.append((number, number, "inline", inline))
            continue
        heading = HEADING.match(line)
        if heading:
            start = number
            if number > 1 and ARTIFACT_MARKER.match(lines[number - 2]):
                start -= 1
            starts.append((start, number, "heading", heading))

    starts.sort(key=lambda item: item[0])
    for index, (start, marker_line, kind, match) in enumerate(starts):
        end = starts[index + 1][0] - 1 if index + 1 < len(starts) else len(lines)
        if kind == "heading":
            entries.append(heading_entry(lines, start, marker_line, end))
        else:
            entries.append(inline_entry(lines, start, end, match))

    owned = {
        number
        for item in entries
        for number in range(
            item["source_line_range"]["start"],
            item["source_line_range"]["end"] + 1,
        )
    }
    unaccounted = [
        (number, line) for number, line in enumerate(lines, 1)
        if number not in owned
    ]
    validate_partition(len(lines), entries, unaccounted)
    return entries, unaccounted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    if not args.dry_run:
        parser.error("--dry-run is required; this tool never edits log.md")

    workspace = args.workspace.resolve()
    source = workspace / "log.md"
    output = args.out.resolve()
    if not workspace.is_dir():
        parser.error("workspace must be an existing directory")
    if not source.is_file() or source.is_symlink():
        parser.error("workspace log.md must be an existing regular file")
    if output.exists() or output.is_symlink():
        parser.error("--out already exists; refusing to overwrite it")

    entries, unaccounted = parse_log(source.read_text(encoding="utf-8"))
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as target:
        for item in entries:
            target.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"entries parsed: {len(entries)}")
    print(f"lines not accounted for: {len(unaccounted)}")
    for number, line in unaccounted:
        print(f"unaccounted line {number}: {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
