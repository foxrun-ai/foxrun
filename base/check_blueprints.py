#!/usr/bin/env python3
"""Check module SQL blueprints for cross-module schema collisions."""

from __future__ import annotations

import sys as _person_sys
from pathlib import Path as _PersonPath
_person_root = next(p for p in _PersonPath(__file__).resolve().parents if (p / "base/person.py").is_file())
_person_sys.path.insert(0, str(_person_root))
from base import person as _fox_person

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import sqlite3
import sys
from typing import Iterable, Sequence


EXPECTED_WORK_STATUS = {
    "tasks": ("backlog", "todo", "in-progress", "blocked", "in-review", "done", "canceled", "superseded"),
    "projects": ("backlog", "todo", "in-progress", "blocked", "in-review", "done", "canceled", "superseded"),
}

CREATE_RE = re.compile(
    r"\bCREATE\s+(TABLE|VIEW)\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"(?:[`\"\[])?([A-Za-z_][\w-]*)(?:[`\"\]])?",
    re.IGNORECASE,
)
TABLE_RE = re.compile(
    r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"(?:[`\"\[])?([A-Za-z_][\w-]*)(?:[`\"\]])?\s*\((.*?)\)\s*;",
    re.IGNORECASE | re.DOTALL,
)
VIEW_RE = re.compile(
    r"\bCREATE\s+VIEW\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"(?:[`\"\[])?([A-Za-z_][\w-]*)(?:[`\"\]])?\s+AS\s+(.*?);",
    re.IGNORECASE | re.DOTALL,
)
REFERENCE_RE = re.compile(
    r"\bREFERENCES\s+(?:[`\"\[])?([A-Za-z_][\w-]*)(?:[`\"\]])?",
    re.IGNORECASE,
)
STATUS_CHECK_RE = re.compile(
    r"\bCHECK\s*\(\s*status\s+IN\s*\((.*?)\)\s*\)",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class Finding:
    category: str
    file: str
    line: int
    subject: str
    detail: str
    fix: str


@dataclass(frozen=True)
class SqlObject:
    kind: str
    name: str
    file: str
    line: int


@dataclass(frozen=True)
class TableDef:
    name: str
    file: str
    line: int
    sql: str
    columns: tuple[str, ...]
    key_columns: tuple[str, ...]


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _mask_comments(text: str) -> str:
    def mask(match: re.Match[str]) -> str:
        return "".join("\n" if char == "\n" else " " for char in match.group(0))

    return re.sub(r"--[^\n]*|/\*.*?\*/", mask, text, flags=re.DOTALL)


def _split_items(body: str) -> list[str]:
    items: list[str] = []
    start = 0
    depth = 0
    quote = ""
    index = 0
    while index < len(body):
        char = body[index]
        if quote:
            if char == quote:
                if index + 1 < len(body) and body[index + 1] == quote:
                    index += 1
                else:
                    quote = ""
        elif char in "'\"`":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            items.append(body[start:index].strip())
            start = index + 1
        index += 1
    if body[start:].strip():
        items.append(body[start:].strip())
    return items


def _table_def(path: Path, text: str, match: re.Match[str]) -> TableDef:
    name, body = match.group(1), match.group(2)
    items = _split_items(body)
    columns: list[str] = []
    keys: list[str] = []
    for item in items:
        head = re.match(r'\s*[`"\[]?([A-Za-z_][\w-]*)', item)
        if not head:
            continue
        token = head.group(1)
        if token.upper() not in {"PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "CONSTRAINT"}:
            columns.append(token.lower())
            if re.search(r"\b(?:PRIMARY\s+KEY|UNIQUE)\b", item, re.IGNORECASE):
                keys.append(token.lower())
        if re.match(r"\s*(?:CONSTRAINT\s+\w+\s+)?(?:PRIMARY\s+KEY|UNIQUE)\b", item, re.IGNORECASE):
            key_match = re.search(r"\((.*?)\)", item, re.DOTALL)
            if key_match:
                keys.extend(
                    part.strip().strip('`"[]').lower()
                    for part in key_match.group(1).split(",")
                )
    return TableDef(
        name=name,
        file=str(path),
        line=_line(text, match.start()),
        sql=match.group(0),
        columns=tuple(columns),
        key_columns=tuple(dict.fromkeys(keys)),
    )


def _is_outside_id(column: str) -> bool:
    patterns = (
        r"^source_(?:.*_)?id$",
        r"^source_record_key$",
        r"^(?:seller_sku|asin|campaign_id|profile_id|marketplace_id)$",
        r"^(?:native|external)_.*(?:id|key)$",
    )
    return any(re.match(pattern, column) for pattern in patterns)


def _has_outside_key(table: TableDef) -> bool:
    return any(_is_outside_id(column) for column in table.key_columns)


def _canonical_id(column: str) -> str | None:
    match = re.fullmatch(r"(.+)_id", column)
    if not match:
        return None
    base = match.group(1)
    if base.endswith("s") and not base.endswith("ss"):
        base = base[:-1]
    return base + "_id"


def _plain_collection_name(value: str) -> str:
    value = value.strip().strip("`").lower()
    return re.sub(r"[^a-z0-9]+", "_", value).strip("_")


def _declared_collection_types(blueprint: Path) -> dict[str, str]:
    """Read table, mirror, trend, and view types from the module metadata."""
    declared: dict[str, str] = {}
    install_path = blueprint.parent / "install.json"
    if install_path.is_file():
        install = json.loads(install_path.read_text(encoding="utf-8"))
        collections = install.get("collections", {})
        if isinstance(collections, dict):
            for name, value in collections.items():
                category = value.get("database_type") if isinstance(value, dict) else value
                if category in {"table", "mirror", "trend", "view"}:
                    declared[str(name).lower()] = str(category)
        elif isinstance(collections, list):
            for item in collections:
                if not isinstance(item, dict):
                    continue
                name = item.get("storage_name") or item.get("name")
                category = item.get("database_type") or item.get("type")
                if name and category in {"table", "mirror", "trend", "view"}:
                    declared[str(name).lower()] = str(category)

    module_path = blueprint.parent / "README.md"
    if not module_path.is_file():
        return declared
    in_collections = False
    for line in module_path.read_text(encoding="utf-8").splitlines():
        if re.match(r"^##\s+Collections\s*$", line, re.IGNORECASE):
            in_collections = True
            continue
        if in_collections and re.match(r"^##\s+", line):
            break
        if not in_collections or not line.lstrip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 5 or cells[0].lower() == "collection" or set(cells[0]) == {"-"}:
            continue
        database_cell = cells[4].strip().strip("`")
        match = re.match(
            r"^(table|mirror|trend|view)(?:\s*:\s*`?([A-Za-z_][\w-]*)`?)?$",
            database_cell,
            re.IGNORECASE,
        )
        if not match:
            continue
        category = match.group(1).lower()
        storage_name = match.group(2) or _plain_collection_name(cells[0])
        if storage_name:
            declared[storage_name.lower()] = category
    return declared


def check_blueprints(paths: Iterable[Path | str]) -> list[Finding]:
    """Load all paths into one memory database and return every finding."""
    files = [Path(path) for path in paths]
    texts = {path: path.read_text(encoding="utf-8") for path in files}
    parsed_texts = {path: _mask_comments(text) for path, text in texts.items()}
    declared_types = {path: _declared_collection_types(path) for path in files}
    objects: list[SqlObject] = []
    tables: list[TableDef] = []
    for path, text in parsed_texts.items():
        objects.extend(
            SqlObject(match.group(1).lower(), match.group(2), str(path), _line(text, match.start()))
            for match in CREATE_RE.finditer(text)
        )
        tables.extend(_table_def(path, text, match) for match in TABLE_RE.finditer(text))

    findings: list[Finding] = []
    definitions: dict[str, list[SqlObject]] = {}
    for obj in objects:
        definitions.setdefault(obj.name.lower(), []).append(obj)
    for name, definitions_for_name in definitions.items():
        modules = {Path(item.file).parent.name for item in definitions_for_name}
        if len(modules) > 1:
            first = definitions_for_name[0]
            for duplicate in definitions_for_name[1:]:
                findings.append(Finding(
                    "duplicate_object", duplicate.file, duplicate.line, duplicate.name,
                    f"{duplicate.kind} also created by {first.file}:{first.line}",
                    f"Keep {name} in one module or rename the other object.",
                ))

    created_tables = {obj.name.lower() for obj in objects if obj.kind == "table"}
    for path, text in parsed_texts.items():
        for match in REFERENCE_RE.finditer(text):
            target = match.group(1)
            if target.lower() not in created_tables:
                findings.append(Finding(
                    "broken_foreign_key", str(path), _line(text, match.start()), target,
                    f"Foreign key points to missing table {target}.",
                    f"Create {target} in one module or remove this foreign key.",
                ))

    for table in tables:
        columns = set(table.columns)
        path = Path(table.file)
        category = declared_types.get(path, {}).get(table.name.lower())
        if category == "mirror":
            if not _has_outside_key(table):
                findings.append(Finding(
                    "mirror_outside_key", table.file, table.line, table.name,
                    "Mirror has no outside identifier in a primary or unique key.",
                    "Put the source identifier and its account scope in a primary or unique key.",
                ))
            if "pulled_at" not in columns:
                findings.append(Finding(
                    "mirror_pulled_at", table.file, table.line, table.name,
                    "Mirror has no pulled_at field.",
                    "Add a required pulled_at field.",
                ))
        if category == "trend":
            if "as_of" not in columns:
                findings.append(Finding(
                    "trend_as_of", table.file, table.line, table.name,
                    "Trend has no as_of field.",
                    "Add a required as_of field and include it in the retained-observation key.",
                ))
        if table.name.lower() in {"tasks", "projects"}:
            check = STATUS_CHECK_RE.search(table.sql)
            values = tuple(re.findall(r"'([^']+)'", check.group(1))) if check else ()
            expected = EXPECTED_WORK_STATUS[table.name.lower()]
            if values != expected:
                findings.append(Finding(
                    "work_status_check", table.file, table.line, table.name,
                    "Status CHECK is " + (", ".join(values) if values else "missing"),
                    "Use exactly: " + ", ".join(expected) + ".",
                ))

    spellings: dict[str, dict[str, list[TableDef]]] = {}
    for table in tables:
        for column in table.columns:
            canonical = _canonical_id(column)
            if canonical:
                spellings.setdefault(canonical, {}).setdefault(column, []).append(table)
    for canonical, variants in spellings.items():
        if len(variants) > 1:
            names = ", ".join(sorted(variants))
            for name, locations in variants.items():
                if name == canonical:
                    continue
                location = locations[0]
                findings.append(Finding(
                    "column_name_collision", location.file, location.line, name,
                    f"Equivalent ID fields use different names: {names}.",
                    f"Rename {name} to {canonical}.",
                ))

    connection = _fox_person.connect(":memory:")
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        for path in files:
            try:
                connection.executescript(texts[path])
            except sqlite3.Error as error:
                findings.append(Finding(
                    "load_error", str(path), 1, path.name,
                    f"SQLite could not load this blueprint: {error}",
                    "Make this blueprint valid when loaded after the earlier modules.",
                ))
        for path, text in parsed_texts.items():
            for view_match in VIEW_RE.finditer(text):
                view_name = view_match.group(1)
                quoted = '"' + view_name.replace('"', '""') + '"'
                try:
                    connection.execute(
                        f"EXPLAIN QUERY PLAN SELECT * FROM {quoted} LIMIT 0"
                    ).fetchall()
                except sqlite3.Error as error:
                    findings.append(Finding(
                        "broken_view_source",
                        str(path),
                        _line(text, view_match.start()),
                        view_name,
                        f"SQLite could not resolve this view: {error}",
                        f"Create every source used by {view_name} or remove the missing source.",
                    ))
    finally:
        connection.close()

    return sorted(findings, key=lambda item: (item.file, item.line, item.category, item.subject))


def _format_finding(finding: Finding) -> str:
    return (
        f"{finding.category}: {finding.file}:{finding.line}: {finding.subject}: "
        f"{finding.detail} Smallest fix: {finding.fix}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, help="Blueprint files. Defaults to all module blueprints.")
    parser.add_argument("--json", action="store_true", help="Print findings as JSON.")
    args = parser.parse_args(argv)
    if args.paths:
        paths = args.paths
    else:
        modules = Path(__file__).resolve().parent.parent
        paths = [modules / 'base/dictionary.sql']
        for manifest in sorted(modules.glob('*/install.json')) + sorted(modules.glob('modules/*/install.json')):
            data = json.loads(manifest.read_text())
            blueprint = manifest.parent / 'blueprint.sql'
            if data.get('ships') is not False and blueprint.is_file():
                paths.append(blueprint)

    findings = check_blueprints(paths)
    if args.json:
        print(json.dumps([asdict(item) for item in findings], indent=2))
    elif findings:
        for finding in findings:
            print(_format_finding(finding))
    else:
        print("No blueprint collisions found.")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
