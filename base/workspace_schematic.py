#!/usr/bin/env python3
"""Workspace schematic: lint each workspace against the model, then draw one page.

Python 3.10+, standard library only. No network call. No model call. Read-only on its sources.

  workspace_schematic.py lint --root ROOT --out ROOT/review/schematic/schematic.json
  workspace_schematic.py validate --data schematic.json
  workspace_schematic.py page --data schematic.json --out index.html

ROOT holds vault/ and home/.local/share/foxrun/data.db. Each source path has its own flag.
The lint reads names and counts. It never reads a file body, a hidden folder, or archive/.
Equal sources give equal bytes: the output has no clock value and no absolute path.
"""

from __future__ import annotations

import sys as _person_sys
from pathlib import Path as _PersonPath
_person_root = next(p for p in _PersonPath(__file__).resolve().parents if (p / "base/person.py").is_file())
_person_sys.path.insert(0, str(_person_root))
from base import person as _fox_person

import argparse
import csv
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from base import paths as _fox_paths

HERE = (Path(__file__).resolve().parent)
RULES_FILE = (Path(__file__).resolve().parent / 'workspace-schematic-rules.json')
SCHEMA_FILE = (Path(__file__).resolve().parent / 'workspace-schematic.schema.json')
PAGE_FILE = (Path(__file__).resolve().parent / 'workspace-schematic-page.html')
PROTECTED = re.compile(r"(^\.env|credential|secret|token|(^|[-_.])auth([-_.]|$)|\.pem$|\.key$|\.p12$)", re.I)
DECISION_ID = re.compile(r"(?<![\w-])[a-z][a-z0-9]*(?:-[a-z0-9]+)+(?![\w-])")
BREAKS = ("change", "not on disk")
PLACEHOLDER = "__SCHEMATIC_JSON__"


# ---------------------------------------------------------------- sources

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def open_db(path: Path) -> sqlite3.Connection:
    """Open read-only and immutable: no lock file, no journal, no write."""
    return _fox_person.connect(f"file:{path}?mode=ro&immutable=1", uri=True)


def read_csv(path: Path) -> list[dict]:
    csv.field_size_limit(1 << 30)
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def read_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def load_decisions(path: Path | None) -> dict:
    """id -> {name, status}. Names and status only; no statement, no quoted words."""
    if path is None or not path.is_file():
        return {}
    con = open_db(path)
    try:
        return {row[0]: {"name": row[1], "status": row[2]} for row in con.execute("select id, name, status from decisions")}
    finally:
        con.close()


class Blueprint:
    def __init__(self, folder: Path):
        target = next(iter(sorted(folder.glob("target-v*.jsonl"))))
        columns = next(iter(sorted(folder.glob("columns-v*.jsonl"))))
        self.files = [target, columns]
        self.version = target.stem.split("-")[-1]
        self.objects = read_jsonl(target)
        self.by_name = {row["name"]: row for row in self.objects}
        self.columns: dict[str, dict] = {}
        for row in read_jsonl(columns):
            self.columns.setdefault(row["table"], {})[row["column"]] = row
        workspaces: list[str] = []
        for fields in self.columns.values():
            for value in (fields.get("workspace") or {}).get("allowed_values") or []:
                if value not in workspaces:
                    workspaces.append(value)
        self.workspaces = workspaces
        self.tables = {row["name"] for row in self.objects if row["kind"] == "table"}

    @staticmethod
    def kind(row: dict) -> str:
        if row["kind"] == "table":
            return row.get("database_type") or "table"
        return row["kind"]


class Database:
    """The staging database as it is: names, fields, the workspace list of each table, counts."""

    def __init__(self, path: Path):
        self.path = path
        self.con = open_db(path)
        self.objects: dict[str, dict] = {}
        rows = self.con.execute(
            "select type, name, coalesce(sql, '') from sqlite_master "
            "where type in ('table', 'view') and name not like 'sqlite_%' order by name"
        ).fetchall()
        digest = hashlib.sha256()
        for kind, name, sql in rows:
            digest.update(f"{kind}\0{name}\0{sql}\n".encode())
            fields = {
                info[1]: {"type": (info[2] or "").upper(), "required": bool(info[3]) or bool(info[5])}
                for info in self.con.execute(f'pragma table_xinfo("{name}")')
            }
            accepted = None
            match = re.search(r'"workspace"[^,]*?\bIN\s*\(([^)]*)\)', sql, re.I)
            if kind == "table" and match:
                accepted = re.findall(r"'([^']*)'", match.group(1))
            self.objects[name] = {"kind": kind, "fields": fields, "accepted": accepted}
        self.schema_sha256 = digest.hexdigest()

    def count(self, name: str, workspace: str | None = None) -> int:
        if workspace is None:
            return self.con.execute(f'select count(*) from "{name}"').fetchone()[0]
        return self.con.execute(f'select count(*) from "{name}" where "workspace" = ?', (workspace,)).fetchone()[0]

    def rows(self, sql: str, args: tuple = ()) -> list:
        try:
            return self.con.execute(sql, args).fetchall()
        except sqlite3.Error:
            return []


class Classification:
    """DM1's verdict for a file, by its vault path. Only action and home are used."""

    def __init__(self, rows: list[dict], excluded: list[dict]):
        self.rows = {row["path"]: row for row in rows}
        self.excluded = {row["path"] for row in excluded}

    def is_excluded(self, path: str) -> bool:
        parts = path.split("/")
        return any("/".join(parts[:i]) in self.excluded for i in range(1, len(parts) + 1))

    def tally(self, paths: list[str]) -> dict:
        out = {"move": 0, "keep": 0, "ask": 0, "not_listed": 0, "protected": 0}
        homes: dict[str, int] = {}
        for path in paths:
            row = self.rows.get(path)
            if row is None:
                out["protected" if self.is_excluded(path) else "not_listed"] += 1
                continue
            action = row["action"] if row["action"] in ("move", "keep", "ask") else "ask"
            out[action] += 1
            if action == "move":
                home = row["model_home"]
                if ";" in home:
                    home = f"{len(home.split(';'))} tables"
                homes[home] = homes.get(home, 0) + 1
        out["homes"] = [{"home": home, "files": count} for home, count in sorted(homes.items(), key=lambda item: (-item[1], item[0]))[:3]]
        return out


# ---------------------------------------------------------------- folders

class Walker:
    def __init__(self, vault: Path, rules: dict):
        self.vault = vault
        self.ignore = set(rules["ignore"]["names"])
        self.no_names = set(rules["no_traverse"]["names"])
        self.no_hidden = bool(rules["no_traverse"]["hidden"])

    def closed(self, name: str) -> bool:
        return (self.no_hidden and name.startswith(".")) or name in self.no_names or bool(PROTECTED.search(name))

    def entries(self, folder: Path) -> list[tuple[str, str]]:
        """Sorted (name, kind) of a folder. Ignored names are left out."""
        out = []
        with os.scandir(folder) as scan:
            for entry in scan:
                if entry.name in self.ignore:
                    continue
                if entry.is_symlink():
                    kind = "link"
                elif entry.is_dir(follow_symlinks=False):
                    kind = "folder"
                else:
                    kind = "file"
                out.append((entry.name, kind))
        return sorted(out)

    def files(self, folder: Path) -> list[str]:
        """Vault paths of every file below a folder. Closed folders and links are not opened."""
        out: list[str] = []
        for base, dirs, names in os.walk(folder, followlinks=False):
            here = Path(base)
            dirs[:] = sorted(d for d in dirs if d not in self.ignore and not self.closed(d) and not (here / d).is_symlink())
            for name in sorted(names):
                if name in self.ignore or (here / name).is_symlink():
                    continue
                out.append((here / name).relative_to(self.vault).as_posix())
        return out


def functions_of(workspace: str, db: Database, vault: Path) -> tuple[list[dict], str]:
    """Function rows for one workspace: data.db first, then the generated page list."""
    rows = db.rows('select "number", "page" from "work_functions" where "workspace" = ? order by "number"', (workspace,))
    if rows:
        return [{"id": number, "page": page or f"{number}.md"} for number, page in rows], "data.db work_functions"
    manifest = vault / workspace / "history" / "outputs" / "workspace-pages" / "functions.json"
    if manifest.is_file():
        try:
            listed = json.loads(manifest.read_text(encoding="utf-8")).get("functions", [])
        except (ValueError, OSError):
            listed = []
        found = [{"id": str(item["id"]), "page": str(item["page"])} for item in listed if item.get("id") and item.get("page")]
        if found:
            return sorted(found, key=lambda item: item["id"]), "history/outputs/workspace-pages/functions.json"
    return [], "none"


def workspace_modules(workspace: str, rules: dict, blueprint: Blueprint, db: Database) -> dict:
    """The modules the model gives one workspace: the base tier, its installed modules, and modules fed by its old files."""
    tiers = rules["module_tiers"]
    tier_of = {module: tier for tier in ("base", "workspace-type", "add-on") for module in tiers[tier]}
    modules_all: list[str] = []
    for row in blueprint.objects:
        if row["module"] not in modules_all:
            modules_all.append(row["module"])
    installed = [name for (name,) in db.rows(
        'select m."name" from "base_installs" i join "base_modules" m on m."id" = i."module" where i."workspace" = ? order by m."name"', (workspace,))]
    sourced = sorted({row["module"] for row in blueprint.objects if own_sources(row, workspace)})
    expected = [m for m in modules_all if tier_of.get(m) == "base" or m in sourced or m in installed]
    tier_rank = {"base": 0, "workspace-type": 1, "add-on": 2}
    expected.sort(key=lambda m: (tier_rank.get(tier_of.get(m), 3), m))
    return {"expected": expected, "installed": installed, "tier_of": tier_of}


def private_patterns(vault: Path, rules: dict) -> list:
    """Names of people, read from file names on the people shelf. A folder that carries one is shown without its name."""
    shelf = vault / rules["private_names"]["folder"]
    out = []
    if shelf.is_dir():
        for path in sorted(shelf.glob("*.md")):
            words = [w for w in re.split(r"[-_.\s]+", path.stem.lower()) if w]
            if len(words) >= 2:
                out.append(re.compile(r"(?<![a-z0-9])" + r"[-_.\s]+".join(re.escape(w) for w in words) + r"(?![a-z0-9])"))
    return out


def lint_folders(workspace: str, vault: Path, rules: dict, walker: Walker, dm1: Classification, db: Database, table_names: set[str],
                 modules: list[str], private: list) -> dict:
    root = vault / workspace
    hidden_name = rules["private_names"]["shown_as"]

    def is_private(name: str) -> bool:
        return bool(PROTECTED.search(name)) or any(pattern.search(name.lower()) for pattern in private)
    functions, function_source = functions_of(workspace, db, vault)
    pages = {item["page"] for item in functions}
    function_ids = {item["id"] for item in functions} | {Path(page).stem for page in pages}

    def fill(text: str) -> str:
        return text.replace("{workspace}", workspace)

    slots: list[dict] = []
    for slot in rules["slots"]:
        if slot["path"] == "{function-page}":
            for item in functions:
                slots.append({**slot, "path": item["page"]})
            continue
        with_module = any(module in modules for module in slot.get("required_with", []))
        slots.append({**slot, "path": fill(slot["path"]), "required": bool(slot["required"]) or with_module, "with_module": with_module})
    slot_at = {slot["path"]: slot for slot in slots}
    order = {slot["path"]: index for index, slot in enumerate(slots)}
    group_order = {group["id"]: index for index, group in enumerate(rules["groups"])}

    def match_rule(listing: list[dict], rel: str, kind: str) -> dict | None:
        for rule in listing:
            if rule["kind"] != kind:
                continue
            pattern = fill(rule["match"])
            if pattern == "{function}":
                if "/" not in rel and rel in function_ids:
                    return rule
            elif fnmatch.fnmatchcase(rel, pattern) and rel.count("/") == pattern.count("/"):
                return rule
        return None

    def target_of(rule: dict, rel: str) -> str:
        target = fill(rule["to"])
        if target == "{function-page}":
            page = next((item["page"] for item in functions if item["id"] == rel or Path(item["page"]).stem == rel), None)
            return page or "the function page"
        return target

    as_is: list[dict] = []
    arrivals: dict[str, list[str]] = {}

    def nest(item: dict, rel: str, paths: list[str]) -> None:
        """Every folder below an emitted folder line. Closed folders are named and not opened. Private names are not shown."""
        inside: dict[str, int] = {}
        prefix = f"{workspace}/"
        for path in paths:
            parts = path[len(prefix):].split("/")[:-1]
            for i in range(1, len(parts) + 1):
                key = "/".join(parts[:i])
                inside[key] = inside.get(key, 0) + 1
        found: list[dict] = []

        def walk(real: str, shown: str, depth: int) -> None:
            for child, child_kind in walker.entries(root / real):
                if child_kind == "file" or (child_kind == "link" and not (root / real / child).is_dir()):
                    continue
                label = hidden_name if is_private(child) else child
                opened = child_kind == "folder" and not walker.closed(child)
                found.append({
                    "path": f"{shown}/{label}", "name": label, "depth": depth, "kind": child_kind, "group": item["group"],
                    "status": "not checked" if child_kind == "link" else item["status"] if item["status"] != "matches" else "decide",
                    "collection": None, "to": None, "rules": list(item["rules"]), "line": rules["nested"]["with"],
                    "files": inside.get(f"{real}/{child}", 0) if opened else None, "opened": opened, "dm1": None,
                    "counted": False, "nested": True,
                })
                if opened:
                    walk(f"{real}/{child}", f"{shown}/{label}", depth + 1)

        walk(rel, item["path"], item["depth"] + 1)
        if not found:
            return
        if item["status"] == "matches":
            as_is.append({
                "path": f"{item['path']}/(folders inside)", "name": f"{len(found)} folders inside", "depth": item["depth"] + 1, "kind": "folders",
                "group": item["group"], "status": "decide", "collection": None, "to": None, "rules": list(item["rules"]),
                "line": rules["nested"]["open"], "files": None, "opened": True, "dm1": None, "counted": True, "nested": False,
            })
        as_is.extend(found)

    def node(rel: str, kind: str, depth: int, parent: dict | None) -> None:
        name = rel.rsplit("/", 1)[-1]
        full = root / rel
        item = {
            "path": rel, "name": name, "depth": depth, "kind": kind, "group": "outside", "status": "change",
            "collection": None, "to": None, "rules": [], "line": "", "files": None, "opened": False, "dm1": None,
            "counted": True, "nested": False,
        }
        paths: list[str] = []
        if kind == "folder" and not walker.closed(name):
            paths = walker.files(full)
            item["files"], item["opened"] = len(paths), True
            item["dm1"] = dm1.tally(paths)
        elif kind == "file":
            row = dm1.rows.get(f"{workspace}/{rel}")
            if row is not None:
                item["dm1"] = dm1.tally([f"{workspace}/{rel}"])
        if PROTECTED.search(name):
            item.update(name="(protected name)", path=rel.rsplit("/", 1)[0] + "/(protected name)" if "/" in rel else "(protected name)")
            item.update(status="not checked", line="A protected name. Not read and not shown.")
            as_is.append(item)
            return
        if kind == "link":
            item.update(status="not checked", line="A link. Not followed.")
            as_is.append(item)
            return
        slot = slot_at.get(rel)
        move = match_rule(rules["moves"], rel, kind)
        decide = match_rule(rules["decide"], rel, kind)
        if slot and slot["kind"] == kind:
            item.update(group=slot["group"], status="matches", collection=slot["collection"], rules=list(slot["rules"]))
            holds = slot.get("holds")
            if holds and item["opened"]:
                other = [p for p in walker.files(full) if not (p.endswith(holds["suffix"]) and Path(p).stem in table_names and p.count("/") == rel.count("/") + 2)]
                if other:
                    item.update(status="change", rules=list(holds["rules"]), line=f"{holds['line']} {len(other)} files here are not table exports.")
        elif move:
            target = target_of(move, rel)
            item.update(status="change", to=target, rules=list(move["rules"]), line=move["line"])
            if target in slot_at:
                item["group"] = slot_at[target]["group"]
                arrivals.setdefault(target, []).append(rel)
            elif parent:
                item["group"] = parent["group"]
        elif decide:
            item.update(status="decide", rules=list(decide["rules"]), line=decide["line"])
            if parent:
                item["group"] = parent["group"]
        elif parent is not None:
            parent_slot = slot_at[parent["path"]]
            if "closed" in parent_slot:
                item.update(status="change", rules=list(parent_slot["closed"]["rules"]), line=parent_slot["closed"]["line"])
            else:
                item.update(status="decide", rules=list(parent_slot["open"]["rules"]), line=parent_slot["open"]["line"])
            item["group"] = parent["group"]
        else:
            item.update(status="change", rules=list(rules["root"]["rules"]), line=rules["root"]["line"])
        if any(pattern.search(name.lower()) for pattern in private):
            item.update(name=hidden_name, path=(rel.rsplit("/", 1)[0] + "/" if "/" in rel else "") + hidden_name)
        as_is.append(item)
        expanded = bool(slot and slot["kind"] == kind == "folder" and slot.get("expand"))
        if kind == "folder" and item["opened"] and not expanded:
            nest(item, rel, paths)
        if slot and slot["kind"] == kind == "folder" and slot.get("expand") and item["opened"]:
            children = walker.entries(full)
            allowed = set(slot.get("closed", {}).get("files", []))
            folders = [(n, k) for n, k in children if k != "file"]
            loose = [n for n, k in children if k == "file" and n not in allowed]
            for child, child_kind in sorted(folders, key=lambda pair: (order.get(f"{rel}/{pair[0]}", len(order)), pair[0])):
                node(f"{rel}/{child}", child_kind, depth + 1, item)
            if loose:
                paths = [f"{workspace}/{rel}/{n}" for n in loose]
                source = slot.get("closed") or slot["open"]
                as_is.append({
                    "path": f"{rel}/(loose files)", "name": f"{len(loose)} loose files", "depth": depth + 1, "kind": "files",
                    "group": item["group"], "status": "change" if "closed" in slot else "decide", "collection": None, "to": None,
                    "rules": list(source["rules"]), "line": source["line"], "files": len(loose), "opened": True, "dm1": dm1.tally(paths),
                    "counted": True, "nested": False,
                })

    top = walker.entries(root) if root.is_dir() else []
    for name, kind in top:
        node(name, kind, 0, None)

    # Display order: the model's root order first, then what has no place, by name.
    blocks: list[list[dict]] = []
    for item in as_is:
        if item["depth"] == 0:
            blocks.append([item])
        else:
            blocks[-1].append(item)

    def block_key(block: list[dict]):
        head = block[0]
        anchor = head["path"] if head["status"] == "matches" or head["path"] in order else (head["to"] or "")
        return (group_order[head["group"]], order.get(anchor, len(order)), head["kind"] != "folder", head["name"].lower())

    as_is = [item for block in sorted(blocks, key=block_key) for item in block]

    disk_kind = {item["path"]: item["kind"] for item in as_is}
    model: list[dict] = []
    for slot in slots:
        rel = slot["path"]
        present = disk_kind.get(rel) == slot["kind"]
        came = sorted(arrivals.get(rel, []))
        if present:
            status = "matches"
        elif came or slot["required"]:
            status = "not on disk"
        else:
            status = "optional"
        line = ""
        if status == "not on disk":
            line = rules["model_lines"]["arrives"].replace("{paths}", ", ".join(came)) if came else rules["model_lines"]["missing"]
            if slot.get("with_module") and slot.get("why"):
                line = f"{line} {slot['why']}"
        model.append({
            "path": rel, "name": rel.rsplit("/", 1)[-1], "depth": rel.count("/"), "kind": slot["kind"], "group": slot["group"],
            "collection": slot["collection"], "rules": list(slot["rules"]), "required": bool(slot["required"]),
            "status": status, "line": line, "from": came, "counted": status == "not on disk" and not came,
        })
    if not functions:
        slot = next(s for s in rules["slots"] if s["path"] == "{function-page}")
        model.append({
            "path": "(function pages)", "name": "one page per function", "depth": 0, "kind": "file", "group": slot["group"],
            "collection": slot["collection"], "rules": list(slot["rules"]), "required": False, "status": "not checked",
            "line": rules["model_lines"]["no_functions"], "from": [], "counted": False,
        })
        model.sort(key=lambda m: group_order[m["group"]])

    counts = {"matches": 0, "change": 0, "not on disk": 0, "decide": 0, "not checked": 0}
    for item in as_is:
        if item["counted"]:
            counts[item["status"]] += 1
    counts["not on disk"] += sum(1 for item in model if item["counted"])
    files = [path for item in as_is if item["depth"] == 0 and item["opened"] for path in walker.files(root / item["path"])]
    files += [f"{workspace}/{item['path']}" for item in as_is if item["depth"] == 0 and item["kind"] == "file" and item["status"] != "not checked"]
    listed = sum(1 for path, row in dm1.rows.items() if path.startswith(workspace + "/") and row.get("source_kind") != "folder")
    tally = dm1.tally(files)
    return {
        "on_disk": root.is_dir(),
        "function_source": function_source,
        "as_is": as_is,
        "model": model,
        "counts": {"matches": counts["matches"], "breaks": counts["change"] + counts["not on disk"], "change": counts["change"],
                   "not_on_disk": counts["not on disk"], "decide": counts["decide"], "not_checked": counts["not checked"]},
        "files": {"counted": len(files), "move": tally["move"], "keep": tally["keep"], "ask": tally["ask"],
                  "not_listed": tally["not_listed"], "protected": tally["protected"],
                  "listed_not_counted": listed - tally["move"] - tally["keep"] - tally["ask"]},
    }


# ---------------------------------------------------------------- tables

def compare_object(name: str, blueprint: Blueprint, db: Database, checks: dict) -> dict:
    """One blueprint object beside the database: status, field counts, and what differs."""
    row = blueprint.by_name[name]
    kind = Blueprint.kind(row)
    want = blueprint.columns.get(name, {})
    have = db.objects.get(name)
    out = {
        "name": name, "kind": kind, "kind_db": have["kind"] if have else None, "status": "matches", "fields_model": len(want), "fields_db": None,
        "extra_fields": [], "missing_fields": [], "type_fields": [], "rules": [], "line": "",
    }
    if have is None:
        if kind == "import":
            out.update(status="optional", rules=list(checks["import_only"]["rules"]), line=checks["import_only"]["line"])
        else:
            out.update(status="not on disk", rules=list(checks["missing_object"]["rules"]), line=checks["missing_object"]["line"])
        return out
    fields = have["fields"]
    out["fields_db"] = len(fields)
    out["extra_fields"] = sorted(set(fields) - set(want))
    out["missing_fields"] = sorted(set(want) - set(fields))
    if have["kind"] == "table":
        out["type_fields"] = sorted(f for f in fields if f in want and fields[f]["type"] != want[f]["sqlite_type"])
    problems = []
    physical = "view" if kind == "view" else "table"
    if have["kind"] != physical:
        problems.append({"rules": checks["kind"]["rules"], "line": checks["kind"]["line"].replace("{model}", kind).replace("{db}", have["kind"])})
    for key, rule in (("missing_fields", "missing_field"), ("extra_fields", "extra_field"), ("type_fields", "field_type")):
        if out[key]:
            problems.append(checks[rule])
    if problems:
        out["status"] = "change"
        out["rules"] = sorted({rule for problem in problems for rule in problem["rules"]})
        out["line"] = " ".join(problem["line"] for problem in problems)
    return out


def own_sources(row: dict, workspace: str) -> list[tuple[str, str]]:
    """(old file, old table) pairs the blueprint names for this object inside one workspace."""
    out = []
    for source in row.get("sources") or []:
        store, _, table = source.partition(":")
        if store.startswith(workspace + "/") and table and re.fullmatch(r"\w+", table):
            out.append((store, table))
    return out


def source_counts(row: dict, workspace: str, vault: Path) -> list[dict]:
    """Row counts of the old stores the blueprint names for this workspace. Counts only."""
    out = []
    for store, table in own_sources(row, workspace):
        rows = None
        path = vault / store
        if path.is_file():
            try:
                con = open_db(path)
                try:
                    rows = con.execute(f'select count(*) from "{table}"').fetchone()[0]
                finally:
                    con.close()
            except sqlite3.Error:
                rows = None
        out.append({"store": store, "table": table, "rows": rows})
    return out


def lint_tables(workspace: str, vault: Path, rules: dict, blueprint: Blueprint, db: Database, compared: dict) -> dict:
    checks = rules["database"]
    taken = workspace_modules(workspace, rules, blueprint, db)
    expected, installed, tier_of = taken["expected"], taken["installed"], taken["tier_of"]

    counts = {"matches": 0, "change": 0, "not on disk": 0, "decide": 0, "not checked": 0}
    install = {
        "expected": expected, "found": installed, "status": "matches", "rules": [], "line": "",
    }
    missing = [m for m in expected if m not in installed]
    if missing:
        install.update(status="not on disk", rules=list(checks["installs"]["rules"]),
                       line=f"{checks['installs']['line']} Missing for: {', '.join(missing)}.")
    counts[install["status"]] += 1

    modules = []
    waiting = 0
    for module in expected:
        why = "base tier" if tier_of.get(module) == "base" else "installed" if module in installed else "the blueprint names this workspace's old files as a source"
        collections: dict[str, list[dict]] = {}
        for row in blueprint.objects:
            if row["module"] != module:
                continue
            item = dict(compared[row["name"]])
            have = db.objects.get(row["name"])
            item["scope"] = "view" if item["kind"] == "view" else "import" if item["kind"] == "import" else "shared"
            item["rows"] = None
            item["load"] = "none"
            item["sources"] = source_counts(row, workspace, vault)
            if have and have["kind"] == "table":
                if "workspace" in have["fields"]:
                    item["scope"] = "workspace"
                    item["rows"] = db.count(row["name"], workspace)
                    if have["accepted"] is not None and workspace not in have["accepted"] and item["status"] == "matches":
                        item.update(status="change", rules=list(checks["workspace_list"]["rules"]), line=checks["workspace_list"]["line"])
                else:
                    item["rows"] = db.count(row["name"])
                known = [s["rows"] for s in item["sources"] if s["rows"] is not None]
                old_rows = sum(known)
                if not item["sources"]:
                    item["load"] = "none"
                elif len(known) < len(item["sources"]):
                    item["load"] = "not counted"
                    if item["status"] == "matches" and item["rows"] == 0:
                        item.update(status="not checked", line="The old file is not in this copy. Its rows were not counted.")
                elif old_rows == 0:
                    item["load"] = "nothing to load"
                elif item["rows"] == 0:
                    item["load"] = "waiting"
                    waiting += 1
                    if item["status"] == "matches":
                        item.update(status="change", rules=list(checks["not_loaded"]["rules"]),
                                    line=f"{checks['not_loaded']['line']} {old_rows} {'row waits' if old_rows == 1 else 'rows wait'}.")
                elif item["rows"] < old_rows:
                    item["load"] = "part"
                    if item["status"] == "matches":
                        item.update(status="not checked", line=f"data.db has {item['rows']} rows. The old files have {old_rows}. The row count check is a later step.")
                else:
                    item["load"] = "loaded"
            if item["status"] != "optional":
                counts[item["status"]] += 1
            collections.setdefault(row.get("collection") or "import", []).append(item)
        groups = []
        for collection in sorted(collections):
            objects = sorted(collections[collection], key=lambda o: (o["kind"] == "view", o["name"]))
            groups.append({"name": collection, "objects": objects})
        flat = [o for g in groups for o in g["objects"]]
        modules.append({
            "name": module, "tier": tier_of.get(module, "no ruling"), "why": why, "collections": groups,
            "counts": {"objects": len(flat), "matches": sum(o["status"] == "matches" for o in flat),
                       "breaks": sum(o["status"] in BREAKS for o in flat), "not_checked": sum(o["status"] == "not checked" for o in flat)},
        })
    return {
        "installed": install,
        "modules": modules,
        "counts": {"matches": counts["matches"], "breaks": counts["change"] + counts["not on disk"], "change": counts["change"],
                   "not_on_disk": counts["not on disk"], "decide": counts["decide"], "not_checked": counts["not checked"],
                   "waiting_for_rows": waiting},
    }


def lint_database(db_path: Path, rules: dict, blueprint: Blueprint, db: Database, compared: dict) -> dict:
    """Checks that hold for the whole install, not for one workspace."""
    checks = rules["database"]
    tiers = rules["module_tiers"]
    tier_of = {module: tier for tier in ("base", "workspace-type", "add-on") for module in tiers[tier]}
    lines = []
    name_rule = checks["file_name"]
    lines.append({"what": "file", "name": db_path.name, "status": "matches" if db_path.name == name_rule["value"] else "change",
                  "rules": list(name_rule["rules"]), "line": name_rule["line"]})
    for name in sorted(compared):
        item = compared[name]
        if item["status"] != "matches":
            detail = []
            if item["extra_fields"]:
                detail.append("In the database only: " + ", ".join(item["extra_fields"]) + ".")
            if item["missing_fields"]:
                detail.append("In the blueprint only: " + ", ".join(item["missing_fields"]) + ".")
            if item["type_fields"]:
                detail.append("Type differs: " + ", ".join(item["type_fields"]) + ".")
            lines.append({"what": item["kind"], "name": name, "status": item["status"], "rules": item["rules"],
                          "line": " ".join([item["line"], *detail]).strip()})
    modules = {row["module"] for row in blueprint.objects}
    for name in sorted(set(db.objects) - set(blueprint.by_name)):
        rule = checks["extra_object"]
        rule_ids, text = list(rule["rules"]), rule["line"]
        if not any(name.startswith(module.replace("-", "_") + "_") for module in modules):
            rule_ids = sorted(set(rule_ids) | set(checks["prefix"]["rules"]))
            text = f"{text} {checks['prefix']['line']}"
        lines.append({"what": db.objects[name]["kind"], "name": name, "status": "change", "rules": rule_ids, "line": text})
    for name, tier in db.rows('select "name", "tier" from "base_modules" order by "name"'):
        want = tier_of.get(name)
        if want is None:
            lines.append({"what": "module", "name": name, "status": "decide", "rules": list(checks["tier_open"]["rules"]),
                          "line": f"{checks['tier_open']['line']} The database says {tier}."})
        elif want != tier:
            lines.append({"what": "module", "name": name, "status": "change", "rules": list(checks["tier"]["rules"]),
                          "line": f"{checks['tier']['line']} The database says {tier}. The ruling says {want}."})
        else:
            lines.append({"what": "module", "name": name, "status": "matches", "rules": list(checks["tier"]["rules"]), "line": f"Tier {tier}."})
    kinds = [Blueprint.kind(row) for row in blueprint.objects]
    in_db = [name for name in blueprint.by_name if name in db.objects]
    matched = sum(1 for name in in_db if compared[name]["status"] == "matches")
    counts = {
        "blueprint_tables": sum(k in ("table", "mirror", "trend") for k in kinds),
        "blueprint_views": kinds.count("view"),
        "blueprint_imports": kinds.count("import"),
        "database_tables": sum(o["kind"] == "table" for o in db.objects.values()),
        "database_views": sum(o["kind"] == "view" for o in db.objects.values()),
        "objects_match": matched,
        "fields_model": sum(len(blueprint.columns.get(name, {})) for name in in_db),
        "fields_database": sum(len(o["fields"]) for o in db.objects.values()),
        "installed_module_rows": db.count("base_installs") if "base_installs" in db.objects else 0,
    }
    tally = {"matches": matched, "change": 0, "not on disk": 0, "decide": 0, "not checked": 0, "optional": 0}
    for line in lines:
        if line["what"] in ("file", "module") or line["status"] != "matches":
            tally[line["status"]] += 1
    return {
        "version": blueprint.version, "lines": lines, "counts": counts,
        "summary": {"matches": tally["matches"], "breaks": tally["change"] + tally["not on disk"], "decide": tally["decide"]},
    }


def lint_machine(rows: list[dict], decisions: dict, fail_line: str) -> dict:
    """DM1's location map, as counts by kind. No location is written out."""
    groups: dict[str, dict] = {}
    for row in rows:
        kind = row["kind"] if row["kind"] != "-" else row["outside_branch"]
        group = groups.setdefault(kind, {"kind": kind, "locations": 0, "pass": 0, "fail": 0, "not_verified": 0, "rules": set()})
        group["locations"] += 1
        verdict = row["outside_verdict"]
        if verdict == "PASS":
            group["pass"] += 1
        elif verdict == "FAIL":
            group["fail"] += 1
            group["rules"].update(i for i in DECISION_ID.findall(row["basis"]) if decisions.get(i, {}).get("status") == "ruled")
        else:
            group["not_verified"] += 1
    out = []
    for kind in sorted(groups):
        group = groups[kind]
        group["rules"] = sorted(group["rules"])
        group["status"] = "change" if group["fail"] else "not checked" if group["not_verified"] else "matches"
        group["line"] = fail_line.replace("{count}", str(group["fail"])) if group["fail"] else ""
        out.append(group)
    return {"locations": len(rows), "kinds": out, "fail": sum(g["fail"] for g in out)}


# ---------------------------------------------------------------- lint

def cited(value, found: set) -> None:
    if isinstance(value, dict):
        for key, inner in value.items():
            if key == "rules" and isinstance(inner, list):
                found.update(inner)
            else:
                cited(inner, found)
    elif isinstance(value, list):
        for inner in value:
            cited(inner, found)


def lint(args) -> dict:
    root = Path(args.root).resolve() if args.root else None

    def pick(value, *default) -> Path:
        if value:
            return Path(value).resolve()
        if root is None:
            raise SystemExit("Give --root or every source path.")
        return root.joinpath(*default)

    vault = pick(args.vault, "vault")
    db_path = pick(args.db, "home", ".local", "share", "foxrun", "data.db")
    outputs = _fox_paths.system_home() / 'history/outputs'
    blueprint_dir = Path(args.blueprint).resolve() if args.blueprint else Path(__file__).resolve().parent / 'blueprint'
    location_map = Path(args.location_map).resolve() if args.location_map else outputs / "location-map.csv"
    classification = Path(args.classification).resolve() if args.classification else outputs / "classification.csv"
    excluded = Path(args.excluded).resolve() if args.excluded else outputs / "excluded-paths.csv"
    decisions_db = Path(args.decisions_db).resolve() if args.decisions_db else _fox_paths.database()
    rules_path = Path(args.rules).resolve() if args.rules else RULES_FILE

    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    blueprint = Blueprint(blueprint_dir)
    db = Database(db_path)
    decisions = load_decisions(decisions_db)
    dm1 = Classification(read_csv(classification), read_csv(excluded))
    walker = Walker(vault, rules)
    compared = {row["name"]: compare_object(row["name"], blueprint, db, rules["database"]) for row in blueprint.objects}

    workspaces = []
    private = private_patterns(vault, rules)
    for name in blueprint.workspaces:
        modules = workspace_modules(name, rules, blueprint, db)["expected"]
        folders = lint_folders(name, vault, rules, walker, dm1, db, blueprint.tables, modules, private)
        tables = lint_tables(name, vault, rules, blueprint, db, compared)
        workspaces.append({"name": name, "folders": folders, "tables": tables})

    def label(path: Path) -> str:
        for base in (vault.parent, rules_path.parent.parent.parent):
            try:
                return path.relative_to(base).as_posix()
            except ValueError:
                continue
        return path.name

    inputs = [{"role": role, "path": label(path), "sha256": sha256(path)} for role, path in (
        ("rules", rules_path), ("blueprint objects", blueprint.files[0]), ("blueprint fields", blueprint.files[1]),
        ("location map", location_map), ("leftover classification", classification), ("excluded paths", excluded))]
    data = {
        "schema_version": 1,
        "task": _fox_person.configuration().get('schematic_task'),
        "title": "Workspace schematic",
        "inputs": {"files": inputs, "database": {"path": label(db_path), "schema_sha256": db.schema_sha256},
                   "blueprint": blueprint.version, "decisions": label(decisions_db)},
        "groups": rules["groups"],
        "summary": [{"workspace": w["name"],
                     "folders": {k: w["folders"]["counts"][k] for k in ("matches", "breaks", "decide", "not_checked")},
                     "tables": {k: w["tables"]["counts"][k] for k in ("matches", "breaks", "decide", "not_checked")}} for w in workspaces],
        "database": lint_database(db_path, rules, blueprint, db, compared),
        "workspaces": workspaces,
        "machine": lint_machine(read_csv(location_map), decisions, rules["model_lines"]["location_fail"]),
        "notes": {"ignored": rules["ignore"]["line"], "not_opened": rules["no_traverse"]["line"]},
    }
    found: set[str] = set()
    cited(data, found)
    data["rules"] = {rule: decisions.get(rule, {"name": "", "status": "unknown"}) for rule in sorted(found)}
    db.con.close()
    return data


def dump(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


def write_if_changed(path: Path, text: str) -> bool:
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


# ---------------------------------------------------------------- schema

def validate(value, schema: dict, defs: dict, where: str = "$") -> list[str]:
    """A small JSON Schema reader: type, enum, required, properties, additionalProperties, items, minimum, pattern, $ref."""
    if "$ref" in schema:
        return validate(value, defs[schema["$ref"].rsplit("/", 1)[-1]], defs, where)
    errors: list[str] = []
    types = schema.get("type")
    if types is not None:
        names = types if isinstance(types, list) else [types]
        checks = {
            "object": isinstance(value, dict), "array": isinstance(value, list), "string": isinstance(value, str),
            "boolean": isinstance(value, bool), "null": value is None,
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        }
        if not any(checks[name] for name in names):
            return [f"{where}: expected {' or '.join(names)}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{where}: {value!r} is not an allowed value")
    if isinstance(value, str) and "pattern" in schema and not re.search(schema["pattern"], value):
        errors.append(f"{where}: does not fit {schema['pattern']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and "minimum" in schema and value < schema["minimum"]:
        errors.append(f"{where}: below {schema['minimum']}")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{where}: missing {key}")
        extra = schema.get("additionalProperties", True)
        for key, inner in value.items():
            if key in properties:
                errors.extend(validate(inner, properties[key], defs, f"{where}.{key}"))
            elif extra is False:
                errors.append(f"{where}: unexpected {key}")
            elif isinstance(extra, dict):
                errors.extend(validate(inner, extra, defs, f"{where}.{key}"))
    if isinstance(value, list) and "items" in schema:
        for index, inner in enumerate(value):
            errors.extend(validate(inner, schema["items"], defs, f"{where}[{index}]"))
    return errors


def check_data(data: dict, schema: dict) -> list[str]:
    """Schema first, then the two rules a schema cannot say: breaks carry ruled ids; counts add up."""
    errors = validate(data, schema, schema.get("$defs", {}))
    if errors:
        return errors
    rules = data["rules"]

    def walk(value, where):
        if isinstance(value, dict):
            if value.get("status") in BREAKS and "rules" in value:
                if not value["rules"]:
                    errors.append(f"{where}: a break without a rule id")
                for rule in value["rules"]:
                    if rules.get(rule, {}).get("status") != "ruled":
                        errors.append(f"{where}: {rule} is not a ruled decision")
            for key, inner in value.items():
                walk(inner, f"{where}.{key}")
        elif isinstance(value, list):
            for index, inner in enumerate(value):
                walk(inner, f"{where}[{index}]")

    walk(data, "$")
    for workspace, row in zip(data["workspaces"], data["summary"]):
        folders = workspace["folders"]
        breaks = sum(n["status"] in BREAKS and n["counted"] for n in folders["as_is"]) + sum(n["counted"] for n in folders["model"])
        matches = sum(n["status"] == "matches" and n["counted"] for n in folders["as_is"])
        if (row["folders"]["breaks"], row["folders"]["matches"]) != (breaks, matches):
            errors.append(f"{workspace['name']}: folder counts do not add up")
        objects = [o for m in workspace["tables"]["modules"] for c in m["collections"] for o in c["objects"]]
        objects.append(workspace["tables"]["installed"])
        breaks = sum(o["status"] in BREAKS for o in objects)
        matches = sum(o["status"] == "matches" for o in objects)
        if (row["tables"]["breaks"], row["tables"]["matches"]) != (breaks, matches):
            errors.append(f"{workspace['name']}: table counts do not add up")
    return errors


# ---------------------------------------------------------------- page

def build_page(data_text: str, template: str) -> str:
    if template.count(PLACEHOLDER) != 1:
        raise SystemExit("The page file must hold the data placeholder once.")
    safe = json.dumps(json.loads(data_text), ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    return template.replace(PLACEHOLDER, safe)


def page_data(page_text: str) -> dict:
    match = re.search(r'<script id="schematic-data" type="application/json">(.*?)</script>', page_text, re.S)
    if not match:
        raise SystemExit("The page holds no data block.")
    return json.loads(match.group(1))


# ---------------------------------------------------------------- command line

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    one = commands.add_parser("lint", help="write the schematic data")
    one.add_argument("--root")
    for flag in ("vault", "db", "blueprint", "location-map", "classification", "excluded", "decisions-db", "rules"):
        one.add_argument(f"--{flag}")
    one.add_argument("--out")
    two = commands.add_parser("validate", help="check the data against the schema")
    two.add_argument("--data", required=True)
    two.add_argument("--schema", default=str(SCHEMA_FILE))
    three = commands.add_parser("page", help="draw the page from the data")
    three.add_argument("--data", required=True)
    three.add_argument("--template", default=str(PAGE_FILE))
    three.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    if args.command == "lint":
        text = dump(lint(args))
        if args.out:
            changed = write_if_changed(Path(args.out), text)
            print(f"{'wrote' if changed else 'unchanged'} {args.out}")
        else:
            sys.stdout.write(text)
        return 0
    if args.command == "validate":
        data = json.loads(Path(args.data).read_text(encoding="utf-8"))
        schema = json.loads(Path(args.schema).read_text(encoding="utf-8"))
        errors = check_data(data, schema)
        for error in errors[:40]:
            print(error)
        print("valid" if not errors else f"{len(errors)} errors")
        return 1 if errors else 0
    text = build_page(Path(args.data).read_text(encoding="utf-8"), Path(args.template).read_text(encoding="utf-8"))
    changed = write_if_changed(Path(args.out), text)
    print(f"{'wrote' if changed else 'unchanged'} {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
