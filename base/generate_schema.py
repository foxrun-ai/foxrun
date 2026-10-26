#!/usr/bin/env python3
"""Generate JSON Schema files, an ERD, and a guide from dictionary rows."""

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
from datetime import datetime
import json
import re
import shutil
import sqlite3
import subprocess
import stat
import sys
import tempfile
from collections import defaultdict
from contextlib import closing
from pathlib import Path
from urllib.parse import quote


TOOLS = (Path(__file__).resolve().parent)
MODULES = Path(__file__).resolve().parent.parent
DEFAULT_OUT = (_fox_paths.system_home() / 'docs/schema')


def guide_frontmatter(body: str, target: Path, workspace: str, kind: str) -> str:
    """Give one generated guide page its three source-defined frontmatter keys."""
    existing = target.read_text(encoding='utf-8') if target.is_file() else ''
    if existing.startswith('---\n'):
        end = existing.find('\n---\n', 4)
        if end >= 0:
            previous = existing[4:end]
            old_body = existing[end + 5:]
            old_stamp = next((line[11:] for line in previous.splitlines()
                              if line.startswith('timestamp: ')), None)
            if old_stamp and old_body == body:
                stamp = old_stamp
            else:
                stamp = datetime.now().astimezone().isoformat(timespec='seconds')
        else:
            stamp = None
    else:
        stamp = None
    if stamp is None and target.is_file():
        try:
            repo = subprocess.run(['git', '-C', str(target.parent), 'rev-parse', '--show-toplevel'],
                                  capture_output=True, text=True, check=True).stdout.strip()
            relative = target.relative_to(Path(repo))
            stamp = subprocess.run(['git', '-C', repo, 'log', '-1', '--format=%cI', '--', str(relative)],
                                   capture_output=True, text=True, check=True).stdout.strip() or None
        except (OSError, subprocess.CalledProcessError, ValueError):
            pass
    if stamp is None:
        stamp = datetime.now().astimezone().isoformat(timespec='seconds')
    return f'---\ntype: {kind}\nworkspace: {workspace}\ntimestamp: {stamp}\n---\n' + body

JSON_TYPES = {
    "key": "string",
    "text": "string",
    "number": "number",
    "date": "string",
    "time": "string",
    "yes/no": "boolean",
    "pick": "string",
    "link": "string",
    "list": "array",
    "file": "string",
}


def filler_description(field: dict) -> bool:
    words = field["field"].replace("_", " ")
    return field["description"].strip() in {
        f"Records {words}.",
        f"Stores the {words} value.",
    }


def content_errors(objects: list[dict], fields: dict[str, list[dict]]) -> list[str]:
    errors = []
    for row in objects:
        for name in ("why", "example"):
            if not (row[name] or "").strip():
                errors.append(f"{row['name']} lacks {name}")
    for object_type, rows in fields.items():
        for field in rows:
            if filler_description(field):
                errors.append(f"{object_type}.{field['field']} has a filler description")
    return errors


def read_dictionary(database: Path) -> tuple[list[dict], dict[str, list[dict]]]:
    uri = "file:" + quote(str(database), safe="/:@") + "?mode=ro"
    with closing(_fox_person.connect(uri, uri=True)) as db:
        db.row_factory = sqlite3.Row
        objects = [
            dict(row) for row in db.execute(
                "SELECT name,supertype,subtype,lens,container,module,database_type,"
                "storage_name,description,why,example,definition,source FROM object_types"
            )
        ]
        fields: dict[str, list[dict]] = defaultdict(list)
        for row in db.execute(
            "SELECT object_type,field,ordinal,required,field_type,pick_values,"
            "pick_source,description,storage_type,sql_definition,source "
            "FROM fields ORDER BY object_type,ordinal,field"
        ):
            fields[row["object_type"]].append(dict(row))
    return objects, fields


def module_order(objects: list[dict]) -> dict[str, int]:
    on_disk = sorted(path.name for path in MODULES.iterdir() if path.is_dir())
    names = {row["module"] for row in objects}
    ordered = ["base"]
    ordered.extend(name for name in on_disk if name != "base" and name in names)
    ordered.extend(sorted(names - set(ordered)))
    return {name: index for index, name in enumerate(ordered)}


def ordered_objects(objects: list[dict]) -> list[dict]:
    modules = module_order(objects)
    return sorted(
        objects,
        key=lambda row: (
            modules[row["module"]],
            0 if row["container"] == "collection" else 1,
            row["container"],
            row["name"],
        ),
    )


def json_property(field: dict) -> dict:
    field_type = field["field_type"]
    result: dict = {"type": JSON_TYPES[field_type]}
    if field_type == "date":
        result["format"] = "date"
    elif field_type == "time":
        result["format"] = "date-time"
    elif field_type == "list":
        result["items"] = {"type": "string"}
    elif field_type == "pick":
        result["enum"] = json.loads(field["pick_values"])
    result["description"] = field["description"]
    return result


def schema_for(row: dict, fields: list[dict]) -> dict:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": row["name"],
        "description": row["description"],
        "type": "object",
        "properties": {
            field["field"]: json_property(field)
            for field in fields
        },
    }
    required = [field["field"] for field in fields if field["required"]]
    if required:
        schema["required"] = required
    return schema


def link_target(source: str, field: dict, object_names: set[str]) -> str | None:
    definition = field["sql_definition"] or ""
    match = re.search(r"\bREFERENCES\s+[\"\[]?([^\"\](\s]+)", definition, re.IGNORECASE)
    if match and match.group(1) in object_names:
        return match.group(1)
    raw = field["field"]
    candidates = [raw]
    if raw.endswith("_id"):
        raw = raw[:-3]
        candidates.extend([raw, raw.split("_")[-1]])
    if raw == "parent":
        candidates.insert(0, source)
    for candidate in candidates:
        forms = [candidate, candidate.replace("_", "-"), candidate + "s"]
        if candidate.endswith("y"):
            forms.append(candidate[:-1] + "ies")
        for form in forms:
            if form in object_names:
                return form
    suffix_matches = sorted(name for name in object_names if name.endswith("-" + raw))
    return suffix_matches[0] if len(suffix_matches) == 1 else None


def link_maps(
    objects: list[dict], fields: dict[str, list[dict]]
) -> tuple[dict[str, list[tuple[str, str]]], dict[str, list[tuple[str, str]]]]:
    names = {row["name"] for row in objects}
    outgoing: dict[str, list[tuple[str, str]]] = defaultdict(list)
    incoming: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for row in objects:
        source = row["name"]
        for field in fields.get(source, []):
            if field["field_type"] != "link":
                continue
            target = link_target(source, field, names)
            if target:
                outgoing[source].append((field["field"], target))
                incoming[target].append((source, field["field"]))
    return outgoing, incoming


def entity_name(name: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_]", "_", name)
    return ("OBJECT_" + value if value[:1].isdigit() else value).upper()


def render_erd(
    objects: list[dict],
    fields: dict[str, list[dict]],
    outgoing: dict[str, list[tuple[str, str]]],
) -> str:
    lines = ["# Entity relationship diagram", "", "```mermaid", "erDiagram"]
    last_module = None
    for row in ordered_objects(objects):
        if row["module"] != last_module:
            lines.append(f"    %% Module: {row['module']}")
            last_module = row["module"]
        lines.append(f"    {entity_name(row['name'])} {{")
        for field in fields.get(row["name"], []):
            data_type = JSON_TYPES[field["field_type"]].replace("array", "string")
            lines.append(f"        {data_type} {entity_name(field['field']).lower()}")
        lines.append("    }")
    lines.append("    %% Relations")
    required = {
        (name, field["field"]): bool(field["required"])
        for name, rows in fields.items()
        for field in rows
    }
    for source in sorted(outgoing):
        for field, target in sorted(outgoing[source]):
            relation = "}o--||" if required[(source, field)] else "}o--o|"
            lines.append(
                f'    {entity_name(source)} {relation} {entity_name(target)} : "{field}"'
            )
    lines.extend(["```", ""])
    return "\n".join(lines)


def table_row(values: list[object]) -> str:
    return "| " + " | ".join(str(value).replace("|", "\\|") for value in values) + " |"


def render_page(
    row: dict,
    fields: list[dict],
    outgoing: list[tuple[str, str]],
    incoming: list[tuple[str, str]],
) -> str:
    name = row["name"]
    lines = [
        f"# {name}",
        "",
        "This file is generated. Do not edit it.",
        "",
        row["description"],
        "",
        "## Why",
        "",
        row["why"] or "No reason is recorded.",
        "",
        "## Example",
        "",
        row["example"] or "No example is recorded.",
        "",
        "## Fields",
        "",
    ]
    if fields:
        lines.extend([
            "| Field | Type | Required | Description |",
            "|---|---|---:|---|",
        ])
        for field in fields:
            lines.append(table_row([
                field["field"],
                field["field_type"],
                "yes" if field["required"] else "no",
                field["description"],
            ]))
    else:
        lines.append("No fields are recorded.")
    lines.extend(["", "## Links out", ""])
    lines.extend(
        [f"- {field} links to [{target}]({target}.md)." for field, target in outgoing]
        or ["No outgoing links are recorded."]
    )
    lines.extend(["", "## Links in", ""])
    lines.extend(
        [f"- [{source}]({source}.md) links through {field}." for source, field in incoming]
        or ["No incoming links are recorded."]
    )
    lines.extend([
        "",
        "## JSON Schema",
        "",
        f"Path: [json/{name}.schema.json](../json/{name}.schema.json)",
        "",
    ])
    return "\n".join(lines)


def render_index(objects: list[dict]) -> str:
    ordered = ordered_objects(objects)
    lines = ["# Schema guide", "", "This guide is generated from dictionary rows.", ""]
    module = container = None
    for row in ordered:
        if row["module"] != module:
            module, container = row["module"], None
            if lines[-1]:
                lines.append("")
            lines.extend([f"## {module}", ""])
        if row["container"] != container:
            container = row["container"]
            if lines[-1]:
                lines.append("")
            lines.extend([f"### {container}", ""])
        lines.append(f"- [{row['name']}]({row['name']}.md) — {row['description']}")
    lines.extend(["", "## A to Z", ""])
    lines.extend(f"- [{row['name']}]({row['name']}.md)" for row in sorted(objects, key=lambda item: item["name"]))
    lines.append("")
    return "\n".join(lines)


def write_outputs(database: Path, output: Path, stamp_source: Path | None = None,
                  workspace: str = 'system') -> None:
    objects, fields = read_dictionary(database)
    outgoing, incoming = link_maps(objects, fields)
    json_dir, guide_dir = output / "json", output / "guide"
    previous_guide = (stamp_source or output) / "guide"
    guide_pages = {}
    for row in sorted(objects, key=lambda item: item["name"]):
        name = row["name"]
        body = render_page(row, fields.get(name, []), sorted(outgoing.get(name, [])),
                           sorted(incoming.get(name, [])))
        guide_pages[name + '.md'] = guide_frontmatter(
            body, previous_guide / (name + '.md'), workspace, 'topic')
    guide_pages['index.md'] = guide_frontmatter(
        render_index(objects), previous_guide / 'index.md', workspace, 'index')
    if json_dir.exists():
        shutil.rmtree(json_dir)
    if guide_dir.exists():
        shutil.rmtree(guide_dir)
    json_dir.mkdir(parents=True)
    guide_dir.mkdir(parents=True)
    for row in sorted(objects, key=lambda item: item["name"]):
        name = row["name"]
        payload = json.dumps(
            schema_for(row, fields.get(name, [])),
            ensure_ascii=False,
            indent=2,
        ) + "\n"
        (json_dir / f"{name}.schema.json").write_text(payload, encoding="utf-8")
        (guide_dir / f"{name}.md").write_text(guide_pages[name + '.md'], encoding="utf-8")
    (guide_dir / "index.md").write_text(guide_pages['index.md'], encoding="utf-8")
    (output / "erd.md").write_text(render_erd(objects, fields, outgoing), encoding="utf-8")


def compare_trees(expected: Path, actual: Path) -> list[str]:
    expected_files = {
        path.relative_to(expected): path.read_bytes()
        for path in expected.rglob("*") if path.is_file()
    }
    actual_files = {
        path.relative_to(actual): path.read_bytes()
        for path in actual.rglob("*") if path.is_file()
    } if actual.is_dir() else {}
    paths = sorted(set(expected_files) | set(actual_files))
    return [str(path) for path in paths if expected_files.get(path) != actual_files.get(path)]


def refresh_guide_frontmatter(directory: Path, workspace: str) -> int:
    """Refresh only metadata on existing generated guide copies."""
    count = 0
    for target in sorted(directory.glob('*.md')):
        if target.is_symlink() or not target.is_file():
            continue
        body = target.read_text(encoding='utf-8')
        if body.startswith('---\n'):
            continue
        if 'This file is generated. Do not edit it.' not in body[:200] and \
                'This guide is generated from dictionary rows.' not in body[:200]:
            continue
        candidate = guide_frontmatter(body, target, workspace,
                                      'index' if target.name == 'index.md' else 'topic')
        with tempfile.NamedTemporaryFile('w', suffix='.md', encoding='utf-8') as staged:
            staged.write(candidate)
            staged.flush()
            gate = subprocess.run(['python3', str(_fox_paths.system_home() / 'base/lint_gate.py'),
                                   '--mode', 'write', '--target', str(target), '--body', staged.name],
                                  capture_output=True, text=True)
            if gate.returncode:
                raise ValueError('lint gate failed for ' + str(target) + ': ' + gate.stderr[:120])
        mode = stat.S_IMODE(target.stat().st_mode)
        try:
            if not (mode & stat.S_IWUSR):
                target.chmod(mode | stat.S_IWUSR)
            target.write_text(candidate, encoding='utf-8')
        finally:
            if not (mode & stat.S_IWUSR):
                target.chmod(mode)
        count += 1
    return count


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--refresh-guide-frontmatter", type=Path)
    parser.add_argument("--frontmatter-workspace", default='system')
    args = parser.parse_args(argv)
    database = args.db.expanduser().resolve()
    output = args.out.expanduser().resolve()
    try:
        if args.refresh_guide_frontmatter:
            count = refresh_guide_frontmatter(args.refresh_guide_frontmatter.expanduser().resolve(),
                                              args.frontmatter_workspace)
            print(f'refreshed frontmatter on {count} generated guide pages')
            return 0
        if args.check:
            objects, fields = read_dictionary(database)
            errors = content_errors(objects, fields)
            if errors:
                print("schema content failed: " + "; ".join(errors), file=sys.stderr)
                return 1
            with tempfile.TemporaryDirectory(prefix="schema-check-") as temp:
                expected = Path(temp) / "schema"
                write_outputs(database, expected, stamp_source=output,
                              workspace=args.frontmatter_workspace)
                differences = compare_trees(expected, output)
            if differences:
                print("schema output differs: " + ", ".join(differences), file=sys.stderr)
                return 1
            print("schema output matches dictionary rows")
            return 0
        write_outputs(database, output, workspace=args.frontmatter_workspace)
        print(f"generated {len(list((output / 'json').glob('*.schema.json')))} schemas in {output}")
        return 0
    except (OSError, ValueError, sqlite3.Error, json.JSONDecodeError) as error:
        print("schema generation failed: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(run())
