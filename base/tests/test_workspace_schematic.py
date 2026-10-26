#!/usr/bin/env python3
"""Tests for workspace_schematic.py. Run: python3 -m unittest test_workspace_schematic -v"""

from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

import workspace_schematic as ws

DECISIONS = sorted({
    "pr-root-order", "pr-base-rules", "pr-schema-md-view", "glossary-md", "pr-design-module-slim", "pr-brand-in-base",
    "pr-capabilities-runtime-setup", "pr-base-map", "pr-base-front-pages", "one-core-database", "pr-wiki-knowledge-base",
    "pr-queries-document", "pr-sources-into-raw", "pr-snapshots-in-raw", "pr-raw-holds-trail", "pr-docs-build-in-work",
    "pr-docs-no-shaping", "pr-design-module-shape", "pr-design-leftovers", "pr-db-collection-creative", "pr-base-timeline",
    "pr-capabilities-md", "data-db-name", "pr-db-old-files-retire-after-parity", "pr-scripts", "pr-agreement-base",
    "no-function-folders", "pr-docs-living", "pr-raw-types", "db-design-rule-r13", "pr-tiers", "tiers-and-organization",
    "every-part-intentional", "modules-inside-core", "module-table-prefix", "db-column-tests", "pr-db-installed-module-word",
    "outside-data-db-kinds", "pr-database-types", "pr-brand-md", "pr-design-rules", "module-vs-collection",
})


def write(path: Path, text: str = "x\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def column(table: str, name: str, kind: str = "TEXT", allowed=None) -> dict:
    return {"table": table, "column": name, "sqlite_type": kind, "required": False, "allowed_values": allowed}


def build(root: Path) -> None:
    vault = root / "vault"
    alpha = vault / "alpha"
    for name in ("AGENTS.md", "CLAUDE.md", "RESOLVER.md", "SCHEMA.md", "CONCEPTS.md", "CAPABILITIES.md", "index.md", "alpha.md", "stray.md", ".DS_Store"):
        write(alpha / name)
    write(alpha / "handoffs" / "one.md")
    write(alpha / "docs" / "specs" / "a.md")
    write(alpha / "docs" / "plans" / "b.md")
    write(alpha / "docs" / "loose.md")
    write(alpha / "wiki" / "raw" / "documents" / "c.md")
    write(alpha / "wiki" / "raw" / "captures" / "d.md")
    write(alpha / "data" / "work_tasks.jsonl")
    write(alpha / "data" / "tool.py")
    write(alpha / "ops" / "private-name.md")
    write(alpha / "ops" / "nested-two" / "y.md")
    write(alpha / "ops" / "ann-example" / "z.md")
    write(alpha / "docs" / "specs" / "nested-one" / "deeper" / "x.md")
    write(alpha / ".claude" / "inner" / "k.md")
    write(alpha / "archive" / "inner" / "k.md")
    write(vault / "people" / "ann-example.md")
    write(alpha / ".claude" / "settings.json")
    write(alpha / "archive" / "old.md")
    write(alpha / "client-secret.txt")
    write(vault / "beta" / "AGENTS.md")

    old = sqlite3.connect(alpha / "alpha.sqlite")
    old.execute("create table tasks (id integer primary key, title text)")
    old.executemany("insert into tasks (title) values (?)", [("a",), ("b",), ("c",)])
    old.execute("create table goals (id integer primary key)")
    old.commit()
    old.close()

    blueprint = vault / "system-workspace" / "docs" / "data-db" / "blueprint" / "final-v11"
    workspaces = ["alpha", "beta"]
    objects = [
        {"name": "work_tasks", "kind": "table", "database_type": None, "module": "work", "collection": "operations", "sources": ["alpha/alpha.sqlite:tasks"]},
        {"name": "work_goals", "kind": "table", "database_type": None, "module": "work", "collection": "strategy", "sources": ["alpha/alpha.sqlite:goals"]},
        {"name": "work_runs", "kind": "table", "database_type": None, "module": "work", "collection": "activity", "sources": []},
        {"name": "work_open_tasks", "kind": "view", "database_type": "view", "module": "work", "collection": "operations", "sources": []},
        {"name": "base_installs", "kind": "table", "database_type": None, "module": "base", "collection": "installations", "sources": []},
        {"name": "base_modules", "kind": "table", "database_type": None, "module": "base", "collection": "installations", "sources": []},
        {"name": "import_keys", "kind": "import", "module": "base"},
        {"name": "commerce_orders", "kind": "table", "database_type": "mirror", "module": "commerce", "collection": "orders", "sources": ["alpha/alpha.sqlite:goals"]},
    ]
    columns = [
        column("work_tasks", "id", "INTEGER"), column("work_tasks", "title"), column("work_tasks", "workspace", allowed=workspaces),
        column("work_goals", "id", "INTEGER"), column("work_goals", "workspace", allowed=workspaces),
        column("work_runs", "id", "INTEGER"),
        column("work_open_tasks", "id", "INTEGER"),
        column("base_installs", "id", "INTEGER"), column("base_installs", "module", "INTEGER"), column("base_installs", "workspace"),
        column("base_modules", "id", "INTEGER"), column("base_modules", "name"), column("base_modules", "tier"),
        column("import_keys", "id", "INTEGER"),
        column("commerce_orders", "id", "INTEGER"),
    ]
    write(blueprint / "target-v11.jsonl", "".join(json.dumps(row) + "\n" for row in objects))
    write(blueprint / "columns-v11.jsonl", "".join(json.dumps(row) + "\n" for row in columns))

    data = root / "home" / ".local" / "share" / "foxrun" / "data.db"
    data.parent.mkdir(parents=True)
    con = sqlite3.connect(data)
    con.executescript("""
        create table "work_tasks" ("id" INTEGER PRIMARY KEY, "title" TEXT, "extra" TEXT,
          "workspace" TEXT NOT NULL CHECK ("workspace" IN ('alpha','beta')));
        create table "work_goals" ("id" INTEGER PRIMARY KEY, "workspace" TEXT NOT NULL CHECK ("workspace" IN ('alpha','beta')));
        create view "work_open_tasks" as select "id" from "work_tasks";
        create table "base_installs" ("id" INTEGER PRIMARY KEY, "module" INTEGER, "workspace" TEXT);
        create table "base_modules" ("id" INTEGER PRIMARY KEY, "name" TEXT, "tier" TEXT);
        create table "_counter" ("id" INTEGER PRIMARY KEY);
        create table "commerce_orders" ("id" INTEGER PRIMARY KEY);
        insert into "base_modules" ("name", "tier") values ('base', 'base'), ('work', 'add-on');
    """)
    con.commit()
    con.close()

    tracker = sqlite3.connect(vault / "system-workspace" / "system-workspace.sqlite")
    tracker.execute("create table decisions (id text primary key, name text, status text)")
    tracker.executemany("insert into decisions values (?, ?, 'ruled')", [(rule, "Name of " + rule) for rule in DECISIONS])
    tracker.commit()
    tracker.close()

    outputs = vault / "system-workspace" / "outputs"
    write(outputs / "2026-10-05-t342-leftover-classification.csv",
          "path,model_home,action,source_kind\n"
          "alpha/ops/private-name.md,wiki/raw,move,file\n"
          "alpha/stray.md,work_tasks,ask,file\n")
    write(outputs / "2026-10-05-t342-excluded-paths.csv", "path,reason,question\nalpha/archive,protected,may this be read\n")
    write(outputs / "2026-10-05-T9-location-map.csv",
          "location,kind,outside_branch,outside_verdict,basis\n"
          "/elsewhere/tool/state.db,tool-internal,kind,PASS,outside-data-db-kinds: keep\n"
          "/elsewhere/run/log.jsonl,-,raw-output,FAIL,db-design-rule-r13: needs one run row\n")


def lint(root: Path) -> dict:
    flags = ("vault", "db", "blueprint", "location_map", "classification", "excluded", "decisions_db", "rules", "out")
    values = {flag: None for flag in flags}
    values["blueprint"] = str(root / "vault/system-workspace/docs/data-db/blueprint/final-v11")
    values['location_map'] = str(root / 'vault/system-workspace/outputs/2026-10-05-T9-location-map.csv')
    values['classification'] = str(root / 'vault/system-workspace/outputs/2026-10-05-t342-leftover-classification.csv')
    values['excluded'] = str(root / 'vault/system-workspace/outputs/2026-10-05-t342-excluded-paths.csv')
    values["decisions_db"] = str(root / "vault/system-workspace/system-workspace.sqlite")
    return ws.lint(argparse.Namespace(root=str(root), **values))


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes() + str(path.stat().st_mtime_ns).encode())
    return digest.hexdigest()


class SchematicTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        build(cls.root)
        cls.before = tree_hash(cls.root)
        cls.data = lint(cls.root)
        cls.after = tree_hash(cls.root)
        cls.schema = json.loads(ws.SCHEMA_FILE.read_text(encoding="utf-8"))
        cls.alpha = cls.data["workspaces"][0]
        cls.nodes = {node["path"]: node for node in cls.alpha["folders"]["as_is"]}
        cls.model = {node["path"]: node for node in cls.alpha["folders"]["model"]}
        cls.objects = {o["name"]: o for m in cls.alpha["tables"]["modules"] for c in m["collections"] for o in c["objects"]}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_two_runs_give_equal_bytes(self):
        self.assertEqual(ws.dump(self.data), ws.dump(lint(self.root)))

    def test_the_lint_only_reads(self):
        self.assertEqual(self.before, self.after)

    def test_data_fits_the_schema_and_counts_add_up(self):
        self.assertEqual(ws.check_data(self.data, self.schema), [])

    def test_a_break_without_a_ruled_id_is_refused(self):
        broken = copy.deepcopy(self.data)
        next(n for n in broken["workspaces"][0]["folders"]["as_is"] if n["status"] == "change")["rules"] = []
        self.assertTrue(any("without a rule id" in e for e in ws.check_data(broken, self.schema)))
        unruled = copy.deepcopy(self.data)
        unruled["rules"]["pr-root-order"]["status"] = "soft"
        self.assertTrue(any("not a ruled decision" in e for e in ws.check_data(unruled, self.schema)))

    def test_workspaces_come_from_the_blueprint(self):
        self.assertEqual([w["name"] for w in self.data["workspaces"]], ["alpha", "beta"])
        self.assertEqual([row["workspace"] for row in self.data["summary"]], ["alpha", "beta"])

    def test_folder_lines(self):
        self.assertEqual(self.nodes["AGENTS.md"]["status"], "matches")
        self.assertEqual((self.nodes["CONCEPTS.md"]["status"], self.nodes["CONCEPTS.md"]["to"]), ("change", "GLOSSARY.md"))
        self.assertEqual((self.nodes["handoffs"]["status"], self.nodes["handoffs"]["to"]), ("change", "wiki/raw/handoffs"))
        self.assertEqual(self.nodes["stray.md"]["rules"], ["pr-root-order"])
        self.assertEqual(self.nodes["alpha.sqlite"]["to"], "data.db")
        self.assertEqual((self.nodes["docs/plans"]["status"], self.nodes["docs/plans"]["to"]), ("change", "docs/specs"))
        self.assertEqual(self.nodes["docs/(loose files)"]["rules"], ["pr-docs-no-shaping"])
        self.assertEqual(self.nodes["wiki/raw/documents"]["status"], "matches")
        self.assertEqual(self.nodes["wiki/raw/captures"]["status"], "change")
        self.assertEqual(self.nodes["data"]["status"], "change")
        self.assertNotIn(".DS_Store", self.nodes)

    def test_model_lines(self):
        self.assertEqual((self.model["GLOSSARY.md"]["status"], self.model["GLOSSARY.md"]["from"], self.model["GLOSSARY.md"]["counted"]),
                         ("not on disk", ["CONCEPTS.md"], False))
        self.assertEqual(self.model["wiki/raw/handoffs"]["from"], ["handoffs"])
        beta = {node["path"]: node for node in self.data["workspaces"][1]["folders"]["model"]}
        self.assertEqual((beta["DESIGN.md"]["status"], beta["BRAND.md"]["status"]), ("optional", "optional"))
        self.assertEqual((beta["RESOLVER.md"]["status"], beta["RESOLVER.md"]["counted"]), ("not on disk", True))

    def test_names_stay_structural(self):
        text = ws.dump(self.data)
        self.assertNotIn("private-name", text)
        self.assertNotIn("client-secret", text)
        self.assertNotIn("/elsewhere/", text)
        self.assertNotIn(str(self.root), text)
        self.assertFalse(self.nodes[".claude"]["opened"])
        self.assertFalse(self.nodes["archive"]["opened"])
        self.assertEqual(self.nodes["ops"]["dm1"]["move"], 1)
        self.assertTrue(all(node["kind"] != "file" for node in self.nodes.values() if node["depth"] > 0))

    def test_table_lines(self):
        self.assertEqual((self.objects["work_tasks"]["status"], self.objects["work_tasks"]["extra_fields"]), ("change", ["extra"]))
        self.assertEqual((self.objects["work_runs"]["status"], self.objects["work_runs"]["rules"]), ("not on disk", ["one-core-database"]))
        self.assertEqual(self.objects["import_keys"]["status"], "optional")
        self.assertEqual(self.objects["work_goals"]["load"], "nothing to load")
        self.assertEqual(self.objects["work_tasks"]["sources"], [{"store": "alpha/alpha.sqlite", "table": "tasks", "rows": 3}])
        self.assertEqual(self.alpha["tables"]["installed"]["status"], "not on disk")

    def test_waiting_records_are_a_break_until_rows_arrive(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            build(root)
            data_db = root / "home" / ".local" / "share" / "foxrun" / "data.db"
            con = sqlite3.connect(data_db)
            con.execute('alter table "work_tasks" drop column "extra"')
            con.commit()
            waiting = {o["name"]: o for m in lint(root)["workspaces"][0]["tables"]["modules"] for c in m["collections"] for o in c["objects"]}
            self.assertEqual((waiting["work_tasks"]["status"], waiting["work_tasks"]["load"]), ("change", "waiting"))
            self.assertIn("3 rows wait", waiting["work_tasks"]["line"])
            con.executemany('insert into "work_tasks" ("title", "workspace") values (?, ?)', [("a", "alpha"), ("b", "alpha"), ("c", "alpha")])
            con.commit()
            con.close()
            loaded = {o["name"]: o for m in lint(root)["workspaces"][0]["tables"]["modules"] for c in m["collections"] for o in c["objects"]}
            self.assertEqual((loaded["work_tasks"]["status"], loaded["work_tasks"]["load"], loaded["work_tasks"]["rows"]), ("matches", "loaded", 3))

    def test_database_lines(self):
        lines = {line["name"]: line for line in self.data["database"]["lines"]}
        self.assertEqual(lines["_counter"]["status"], "change")
        self.assertIn("module-table-prefix", lines["_counter"]["rules"])
        self.assertEqual(lines["work"]["status"], "change")
        self.assertEqual(lines["base"]["status"], "matches")
        self.assertEqual(self.data["machine"]["fail"], 1)

    # ---- review round 1: each defect has a planted case that must show red

    def test_f1_each_required_contract_missing_is_a_break(self):
        contracts = ["AGENTS.md", "CLAUDE.md", "RESOLVER.md", "SCHEMA.md", "GLOSSARY.md", "DESIGN.md", "BRAND.md", "CAPABILITIES.md", "index.md", "alpha.md"]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            build(root)
            alpha = root / "vault" / "alpha"
            (alpha / "CONCEPTS.md").unlink()
            for name in contracts:
                write(alpha / name)
            full = {n["path"]: n for n in lint(root)["workspaces"][0]["folders"]["model"]}
            self.assertEqual([full[name]["status"] for name in contracts], ["matches"] * len(contracts))
            self.assertEqual(full["BRAND.md"]["collection"], "base/rules")
            self.assertIn("pr-brand-in-base", full["BRAND.md"]["rules"])
            for name in contracts:
                with self.subTest(removed=name):
                    (alpha / name).unlink()
                    data = lint(root)
                    line = {n["path"]: n for n in data["workspaces"][0]["folders"]["model"]}[name]
                    self.assertEqual((line["status"], line["counted"], bool(line["rules"]), bool(line["line"])), ("not on disk", True, True, True))
                    self.assertEqual(ws.check_data(data, self.schema), [])
                    write(alpha / name)

    def test_f1_a_selling_workspace_needs_both_contracts_and_others_do_not(self):
        self.assertEqual((self.model["DESIGN.md"]["status"], self.model["DESIGN.md"]["counted"]), ("not on disk", True))
        self.assertEqual((self.model["BRAND.md"]["status"], self.model["BRAND.md"]["counted"]), ("not on disk", True))
        self.assertIn("sells", self.model["BRAND.md"]["line"])
        self.assertIn("commerce", [m["name"] for m in self.alpha["tables"]["modules"]])
        self.assertNotIn("commerce", [m["name"] for m in self.data["workspaces"][1]["tables"]["modules"]])

    def swapped(self, statements):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            build(root)
            con = sqlite3.connect(root / "home" / ".local" / "share" / "foxrun" / "data.db")
            con.executescript(statements)
            con.commit()
            con.close()
            data = lint(root)
            self.assertEqual(ws.check_data(data, self.schema), [])
            objects = {o["name"]: o for m in data["workspaces"][0]["tables"]["modules"] for c in m["collections"] for o in c["objects"]}
            return objects, {line["name"]: line for line in data["database"]["lines"]}

    def test_f2_a_view_in_place_of_a_table_is_a_break(self):
        objects, lines = self.swapped('drop table "work_goals"; create view "work_goals" as select 1 as "id", \'alpha\' as "workspace";')
        goal = objects["work_goals"]
        self.assertEqual((goal["status"], goal["kind"], goal["kind_db"]), ("change", "table", "view"))
        self.assertIn("pr-database-types", goal["rules"])
        self.assertIn("The blueprint says table. The database has a view.", goal["line"])
        self.assertEqual(lines["work_goals"]["status"], "change")

    def test_f2_a_table_in_place_of_a_view_is_a_break(self):
        objects, lines = self.swapped('drop view "work_open_tasks"; create table "work_open_tasks" ("id" INTEGER);')
        view = objects["work_open_tasks"]
        self.assertEqual((view["status"], view["kind"], view["kind_db"]), ("change", "view", "table"))
        self.assertIn("pr-database-types", view["rules"])
        self.assertEqual(lines["work_open_tasks"]["status"], "change")

    def test_f2_the_right_kind_still_matches(self):
        self.assertEqual((self.objects["work_goals"]["kind_db"], self.objects["work_open_tasks"]["kind_db"]), ("table", "view"))
        self.assertEqual(self.objects["work_open_tasks"]["status"], "matches")

    def test_f3_every_permitted_folder_is_in_the_tree(self):
        import os
        alpha = self.root / "vault" / "alpha"
        on_disk = set()
        for base, dirs, _ in os.walk(alpha):
            rel = Path(base).relative_to(alpha).as_posix()
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for d in list(dirs):
                on_disk.add(d if rel == "." else f"{rel}/{d}")
                if d.startswith(".") or d == "archive":
                    dirs.remove(d)
        shown = {n["path"] for n in self.alpha["folders"]["as_is"] if n["kind"] == "folder"}
        self.assertEqual(on_disk - shown, {"ops/ann-example"})
        self.assertIn("ops/(private name)", shown)
        self.assertNotIn("ann-example", ws.dump(self.data))
        self.assertNotIn(".claude/inner", shown)
        self.assertNotIn("archive/inner", shown)
        for path in ("docs/specs/nested-one", "docs/specs/nested-one/deeper", "ops/nested-two"):
            self.assertIn(path, shown)

    def test_f3_a_nested_folder_takes_the_verdict_above_it_and_is_not_counted_twice(self):
        self.assertEqual((self.nodes["ops/nested-two"]["status"], self.nodes["ops/nested-two"]["counted"], self.nodes["ops/nested-two"]["rules"]),
                         ("change", False, ["pr-root-order"]))
        inside = self.nodes["docs/specs/(folders inside)"]
        self.assertEqual((inside["status"], inside["counted"], inside["name"]), ("decide", True, "2 folders inside"))
        self.assertEqual((self.nodes["docs/specs/nested-one"]["status"], self.nodes["docs/specs/nested-one"]["counted"]), ("decide", False))
        self.assertEqual(self.nodes["docs/specs/nested-one"]["files"], 1)

    # ---- review round 2: a break at any depth carries its id and its line, and stays in the "Breaks only" view

    def test_r2_a_nested_break_carries_its_decision_id_and_plain_line(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            build(root)
            write(root / "vault" / "alpha" / "ops" / "nested-two" / "level-three" / "level-four" / "w.md")
            data = lint(root)
            nodes = {n["path"]: n for n in data["workspaces"][0]["folders"]["as_is"]}
            for path in ("ops/nested-two", "ops/nested-two/level-three", "ops/nested-two/level-three/level-four"):
                with self.subTest(path=path):
                    node = nodes[path]
                    self.assertEqual((node["status"], node["nested"]), ("change", True))
                    self.assertEqual(node["rules"], ["pr-root-order"])
                    self.assertTrue(node["line"])
            self.assertEqual(ws.check_data(data, self.schema), [])
            stripped = copy.deepcopy(data)
            next(n for n in stripped["workspaces"][0]["folders"]["as_is"] if n["path"] == "ops/nested-two/level-three")["rules"] = []
            self.assertTrue(any("without a rule id" in e for e in ws.check_data(stripped, self.schema)))

    def test_r2_the_page_draws_the_line_and_ids_of_a_nested_break(self):
        template = ws.PAGE_FILE.read_text(encoding="utf-8")
        body = template[template.index("function nestedLine(item)"):template.index("/* filter:start */")]
        self.assertIn("rules(item.rules)", body)
        self.assertIn("item.line", body)

    def test_r2_breaks_only_keeps_a_nested_break_and_the_folders_above_it(self):
        import shutil
        import subprocess
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not installed")
        template = ws.PAGE_FILE.read_text(encoding="utf-8")
        source = template[template.index("/* filter:start */"):template.index("/* filter:end */")]
        items = [
            {"path": "docs", "status": "matches", "nested": False},
            {"path": "docs/plans", "status": "change", "nested": False},
            {"path": "docs/specs", "status": "matches", "nested": False},
            {"path": "docs/specs/(folders inside)", "status": "decide", "nested": False},
            {"path": "docs/specs/inner", "status": "decide", "nested": True},
            {"path": "ops", "status": "change", "nested": False},
            {"path": "ops/nested-two", "status": "change", "nested": True},
            {"path": "ops/nested-two/level-three", "status": "change", "nested": True},
            {"path": "wiki", "status": "matches", "nested": False},
            {"path": "wiki/raw", "status": "matches", "nested": False},
            {"path": "wiki/raw/snapshots", "status": "not on disk"},
            {"path": "index.md", "status": "matches", "nested": False},
            {"path": "kept", "status": "not checked", "nested": False},
        ]
        script = source + "\nprocess.stdout.write(JSON.stringify(breakFilter(" + json.dumps(items) + ")));"
        out = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout
        keep = dict(zip([item["path"] for item in items], json.loads(out)))
        self.assertEqual(keep, {
            "docs": True, "docs/plans": True, "docs/specs": False, "docs/specs/(folders inside)": True, "docs/specs/inner": False,
            "ops": True, "ops/nested-two": True, "ops/nested-two/level-three": True,
            "wiki": True, "wiki/raw": True, "wiki/raw/snapshots": True, "index.md": False, "kept": False,
        })

    def test_f4_the_page_shows_each_status_with_its_exact_word(self):
        import re
        template = ws.PAGE_FILE.read_text(encoding="utf-8")
        self.assertIn('function tag(status) { return el("span", { class: "tag s-" + slug(status) }, icon(slug(status)), status); }', template)
        calls = re.findall(r"\btag\(([^()]*)\)", template)
        words = set(self.schema["$defs"]["status"]["enum"])
        for call in calls:
            self.assertNotIn(",", call)
            if call.startswith('"'):
                self.assertIn(call.strip('"'), words)
            else:
                self.assertTrue(call == "status" or call.endswith(".status"), call)
        self.assertNotIn('? "on disk"', template)
        self.assertNotIn("not in the database", template)

    def test_page_holds_the_same_data_and_no_address(self):
        template = ws.PAGE_FILE.read_text(encoding="utf-8")
        text = ws.dump(self.data).replace("alpha.md", "<b>.md")
        page = ws.build_page(text, template)
        self.assertEqual(ws.page_data(page), json.loads(text))
        self.assertNotIn("<b>.md", page)
        self.assertNotIn("http", template)


if __name__ == "__main__":
    unittest.main()
