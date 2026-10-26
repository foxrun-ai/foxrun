#!/usr/bin/env python3
"""Tests for schema generation from dictionary rows."""

from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()

import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import apply_dictionary
import generate_schema


TOOLS = Path(__file__).resolve().parent.parent
BLUEPRINT = (Path(__file__).resolve().parent / '../../work/blueprint.sql')


class GenerateSchemaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="generate-schema-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "tracker.sqlite"
        with closing(sqlite3.connect(self.db)) as db:
            db.executescript(BLUEPRINT.read_text(encoding="utf-8"))
        apply_dictionary.apply(self.db, self.root / "backups")
        with closing(sqlite3.connect(self.db)) as db:
            db.execute(
                "UPDATE fields SET description='Test meaning. Allowed value: example.' "
                "WHERE description='Records ' || replace(field,'_',' ') || '.' "
                "OR description='Stores the ' || replace(field,'_',' ') || ' value.'"
            )
            db.commit()
        self.out = self.root / "schema"

    def digest(self) -> str:
        digest = hashlib.sha256()
        for path in sorted(self.out.rglob("*")):
            if path.is_file():
                digest.update(str(path.relative_to(self.out)).encode())
                digest.update(path.read_bytes())
        return digest.hexdigest()

    def test_generates_one_schema_and_page_per_object_type(self):
        generate_schema.write_outputs(self.db, self.out)
        with closing(sqlite3.connect(self.db)) as db:
            count = db.execute("SELECT count(*) FROM object_types").fetchone()[0]
        self.assertEqual(count, len(list((self.out / "json").glob("*.schema.json"))))
        self.assertEqual(count + 1, len(list((self.out / "guide").glob("*.md"))))
        schema = json.loads((self.out / "json/tasks.schema.json").read_text())
        self.assertEqual("https://json-schema.org/draft/2020-12/schema", schema["$schema"])
        self.assertEqual("string", schema["properties"]["status"]["type"])
        self.assertIn("todo", schema["properties"]["status"]["enum"])
        self.assertIn("id", schema["required"])
        self.assertIn("%% Module: base", (self.out / "erd.md").read_text())
        self.assertIn("%% Module: work", (self.out / "erd.md").read_text())

    def test_second_generation_is_byte_identical_and_check_finds_drift(self):
        generate_schema.write_outputs(self.db, self.out)
        first = self.digest()
        generate_schema.write_outputs(self.db, self.out)
        self.assertEqual(first, self.digest())
        self.assertEqual(0, generate_schema.run([
            "--db", str(self.db), "--out", str(self.out), "--check",
        ]))
        page = self.out / "guide/tasks.md"
        page.write_text(page.read_text() + "hand edit\n")
        self.assertEqual(1, generate_schema.run([
            "--db", str(self.db), "--out", str(self.out), "--check",
        ]))

    def test_links_and_grouping_come_from_rows(self):
        generate_schema.write_outputs(self.db, self.out)
        project = (self.out / "guide/projects.md").read_text()
        goal = (self.out / "guide/goals.md").read_text()
        index = (self.out / "guide/index.md").read_text()
        self.assertIn("goal links to [goals]", project)
        self.assertIn("[projects](projects.md) links through goal", goal)
        self.assertLess(index.index("## base"), index.index("## work"))

    def test_check_rejects_missing_guide_prose_and_filler_field_descriptions(self):
        generate_schema.write_outputs(self.db, self.out)
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("UPDATE object_types SET why=NULL WHERE name='tasks'")
            db.execute("UPDATE object_types SET example='' WHERE name='projects'")
            db.execute(
                "UPDATE fields SET description='Stores the by value.' "
                "WHERE object_type='runs' AND field='by'"
            )
            db.commit()
        self.assertEqual(1, generate_schema.run([
            "--db", str(self.db), "--out", str(self.out), "--check",
        ]))


if __name__ == "__main__":
    unittest.main()
