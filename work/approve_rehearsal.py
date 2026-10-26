#!/usr/bin/env python3
"""Rehearse document approval on retained, labeled fixtures. No real consent."""

from __future__ import annotations

import sys as _person_sys
from pathlib import Path as _PersonPath
_person_root = next(p for p in _PersonPath(__file__).resolve().parents if (p / "base/person.py").is_file())
_person_sys.path.insert(0, str(_person_root))
from base import person as _fox_person
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
from decisions import approve

TOOLS = (Path(__file__).resolve().parent)
MODULES = Path(__file__).resolve().parent.parent
OLD = b"---\ntype: agents\n---\n# Earlier fixture contract\nKeep these exact bytes.\n"
NEW = b"---\ntype: agents\n---\n# Proposed fixture contract\nThis is a labeled rehearsal.\n"
DRAFT = b"---\ntype: agents\nstatus: draft\n---\n# Proposed fixture contract\nThis is a labeled rehearsal.\n"


def run(vault, run_root, case=None):
    vault = approve.root_path(vault)
    run_root = approve.root_path(run_root)
    if run_root == vault or run_root.is_relative_to(vault) or vault.is_relative_to(run_root):
        raise ValueError("rehearsal run root and vault must be separate")
    fixtures = vault / "foxrun/scratch/ac2-approval-fixtures"
    fixtures.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="source-note-", dir=fixtures))
    private = Path(tempfile.mkdtemp(prefix="source-note-", dir=run_root))
    for name in ("drafts", "archives", "journals", "plans"):
        (private / name).mkdir()
    (root / ".fixture-only").write_text("SIMULATED CONSENT. No real approval.\n")
    target = root / "AGENTS.md"
    target.write_bytes(OLD)
    (private / "drafts/AGENTS.md").write_bytes(DRAFT)
    database = private / "fixture.sqlite"
    with _fox_person.connect(database) as con:
        con.executescript(((Path(__file__).resolve().parent / 'blueprint.sql')).read_text())
    plan_file = private / "plans/approve.json"
    plan = approve.build_plan(root=root, database=database, control_root=private,
        items=[("drafts/AGENTS.md", "AGENTS.md", "remove-status")], archive_root="archives", journal="journals/approve.json")
    approve.write_json_exclusive(plan_file, plan, "fixture plan")

    def apply(confirmation):
        return approve.apply_plan(root=root, database=database, control_root=private, plan=plan,
            confirmation=confirmation, actor="night-run-fixture",
            approval_ref="fixture://source-note/simulated-consent", approval_text="SIMULATED CONSENT: yes for this exact fixture plan")

    def rows(table):
        with _fox_person.connect(database) as con:
            con.row_factory = sqlite3.Row
            return [dict(row) for row in con.execute("SELECT * FROM " + table + " ORDER BY id")]

    def lint_cli(selected_root=None):
        return subprocess.run([sys.executable, "-B", str((Path(__file__).resolve().parent / '../decisions/approve.py')), "lint", "--root", str(selected_root or root),
            "--db", str(database), "--path", "AGENTS.md"], capture_output=True, text=True)

    checks = {}
    diff = plan["items"][0]["diff"]
    checks["diff"] = "-# Earlier fixture contract" in diff and "+# Proposed fixture contract" in diff and "-status: draft" in diff
    before_db = database.read_bytes()
    try:
        apply("0" * 64)
        checks["consent"] = False
    except approve.ApproveError:
        checks["consent"] = target.read_bytes() == OLD and database.read_bytes() == before_db and not rows("approvals")
    missing = lint_cli()
    if missing.returncode != 1:
        raise ValueError("missing approval evidence did not fail lint: " + missing.stderr)
    applied = apply(plan["plan_digest"])
    archive = private / plan["items"][0]["archive"]
    checks["archive"] = applied["status"] == "applied" and archive.read_bytes() == OLD and target.read_bytes() == NEW
    approvals, activities = rows("approvals"), rows("activity")
    sha = hashlib.sha256(NEW).hexdigest()
    checks["rows"] = (len(approvals) == len(activities) == 1 and approvals[0]["version"] == sha
        and approvals[0]["subject_id"] == "AGENTS.md" and approvals[0]["source"] == "fixture://source-note/simulated-consent"
        and activities[0]["new_value"] == sha and activities[0]["old_value"] == hashlib.sha256(OLD).hexdigest()
        and "SIMULATED CONSENT" in approvals[0]["person_words"])
    good = lint_cli()
    drift_root = Path(tempfile.mkdtemp(prefix="source-note-drift-", dir=fixtures))
    (drift_root / ".fixture-only").write_text("Changed-byte lint fixture. No live approval.\n")
    (drift_root / "AGENTS.md").write_bytes(NEW + b"Fixture drift.\n")
    drift = lint_cli(drift_root)
    report = approve.lint_documents(root=root, database=database, paths=["AGENTS.md"])
    checks["lint"] = good.returncode == 0 and drift.returncode == 1 and not report["findings"]
    before_db = database.read_bytes()
    result = apply(plan["plan_digest"])
    checks["repeat"] = (result["status"] == "duplicate" and rows("approvals") == approvals and rows("activity") == activities
        and database.read_bytes() == before_db and target.read_bytes() == NEW and archive.read_bytes() == OLD
        and (private / "drafts/AGENTS.md").read_bytes() == DRAFT)
    specs = root / "docs/specs"
    specs.mkdir(parents=True)
    (specs / "unapproved.md").write_text("# Unapproved spec fixture\n")
    (specs / "draft.new.md").write_text("# Draft spec fixture\n")
    drafts = specs / "drafts"
    drafts.mkdir()
    (drafts / "draft.md").write_text("# Draft fixture\n")
    discovery = subprocess.run([sys.executable, "-B", str((Path(__file__).resolve().parent / '../decisions/approve.py')), "lint", "--root", str(root),
        "--db", str(database), "--discover"], capture_output=True, text=True)
    discovered = json.loads(discovery.stdout)
    checks["discovery"] = (discovery.returncode == 1
        and {d["file"] for d in discovered["documents"]} == {"AGENTS.md", "docs/specs/unapproved.md"}
        and [f["file"] for f in discovered["findings"]] == ["docs/specs/unapproved.md"])
    (private / "discovery.json").write_text(json.dumps(discovered, indent=2) + "\n")
    receipt = {"fixture_only": True, "real_consent": False, "root": str(root), "private": str(private),
               "database": str(database), "plan": str(plan_file), "checks": checks, "approval_rows": approvals,
               "activity_rows": activities, "archive": str(archive), "archive_sha256": hashlib.sha256(OLD).hexdigest()}
    (private / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    for name in [case] if case else checks:
        print(("PASS " if checks[name] else "FAIL ") + name)
    print("Fixture receipt: " + str(private / "receipt.json"))
    return checks, private / "receipt.json"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--case", choices=["diff", "consent", "archive", "rows", "lint", "repeat", "discovery"])
    args = parser.parse_args()
    try:
        checks, _ = run(args.vault, args.run_root, args.case)
        raise SystemExit(0 if all(checks.values()) else 1)
    except (ValueError, OSError, sqlite3.Error, approve.ApproveError) as error:
        print("FAIL " + str(error), file=sys.stderr)
        raise SystemExit(2)
