
from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'not-shipped/his/base/catchup', 'not-shipped/his/base/migrations', 'not-shipped/his/base/staging', 'work', 'not-shipped/his/work', 'events', 'decisions', 'memory', 'people', 'design', 'capture', 'modules/commerce', 'modules/ugc', 'modules/amazon')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _setup
_setup()

import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent.parent
MODULES = Path(__file__).resolve().parent.parent.parent
FIXTURE = _fox_root / 'base/tests/fixtures/cedar-table'
RULES = FIXTURE / 'proposal-rules.md'
COMMANDS = {
    name: (FIXTURE / 'people/people.py' if name=='people' else FIXTURE / 'modules' / name / name)
    for name in ("people", "ugc", "commerce", "amazon")
}
sys.path.insert(0, str(HERE))
import table


class SharedTableCommandRegressionTest(unittest.TestCase):
    def setUp(self):
        self.original_modules = table.MODULES_ROOT
        table.MODULES_ROOT = FIXTURE
        self.addCleanup(setattr, table, "MODULES_ROOT", self.original_modules)
        self.temp = tempfile.TemporaryDirectory(dir=HERE)
        self.db_path = Path(self.temp.name) / "test.sqlite"
        db = sqlite3.connect(self.db_path)
        for module in ("work", "people", "commerce", "amazon", "ugc"):
            db.executescript(((FIXTURE / 'modules' / module if module in {'amazon','commerce','ugc'} else FIXTURE / module) / 'blueprint.sql').read_text())
        db.execute("INSERT INTO pipelines(id,name) VALUES('p','Pipeline')")
        db.execute("INSERT INTO pipeline_stages(pipeline,stage,ord) VALUES('p','lead',0)")
        for number in (1, 2):
            db.execute(
                "INSERT INTO persons(id,display_name,evidence_refs) VALUES(?,?,?)",
                (f"person-{number}", f"Person {number}", '["seed"]'),
            )
            db.execute(
                "INSERT INTO opportunities(id,title,person_id,pipeline,stage,evidence_refs) "
                "VALUES(?,?,?,?,?,?)",
                (f"opp-{number}", f"Opportunity {number}", f"person-{number}", "p", "lead", '["seed"]'),
            )
        db.execute(
            "INSERT INTO creator_cycles "
            "(id,opportunity_id,cycle_key,name,cycle_type,amount_unknown_reason,"
            "created_at,updated_at,evidence_refs) "
            "VALUES('cycle-1','opp-1','first','First','recurring','unknown','t','t','[\"seed\"]')"
        )
        db.execute(
            "INSERT INTO interactions "
            "(id,person_id,summary_author,happened_at,summary,evidence_refs) "
            "VALUES('interaction-1','person-1','sol','2026-09-18T20:00:00-04:00','Sent request','[\"message\"]')"
        )
        db.commit()
        db.close()

    def tearDown(self):
        self.temp.cleanup()

    def run_command(self, module, *args, ok=True):
        result = subprocess.run(
            [str(COMMANDS[module]), "--db", str(self.db_path), "--rules", str(RULES), *args],
            text=True,
            capture_output=True,
        )
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result

    def proposal(self, module, *args):
        return self.run_command(module, "propose", *args).stdout.strip().split()[-1]

    def scalar(self, sql, values=()):
        with sqlite3.connect(self.db_path) as db:
            return db.execute(sql, values).fetchone()[0]

    def add_restock(self, row_id="R1"):
        self.run_command(
            "commerce", "add", "restocks", "--by", "sol",
            "--set", f"id={row_id}", "--set", "source_system=shopify",
            "--set", "source_account_id=store-1",
            "--set", "inventory_source_id=item-1",
            "--set", "destination_location_id=destination-1",
            "--set", "requested_quantity=10",
        )

    def test_recheck_1_legacy_approved_row_uses_its_own_fields(self):
        self.add_restock()
        with sqlite3.connect(self.db_path) as db:
            db.execute(
                "INSERT INTO receivings "
                "(id,restock_id,quantity,counted_at,counted_by,status,evidence_ref) "
                "VALUES('legacy-receiving','R1',10,'2026-09-18T21:00:00Z',"
                "'worker','confirmed','count-sheet')"
            )
            db.execute(
                "INSERT INTO approvals "
                "(subject_type,subject_id,call,person_words,given_at,source) "
                "VALUES('receivings','legacy-receiving','approve','confirmed import',"
                "'2026-09-18T21:01:00Z','legacy import')"
            )
        changed = self.run_command(
            "commerce", "set", "receivings", "legacy-receiving", "--by", "worker",
            "--set", "quantity=999", "--set", "status=confirmed", ok=False,
        )
        self.assertIn("must use propose", changed.stderr)
        self.assertEqual(
            self.scalar("SELECT quantity FROM receivings WHERE id='legacy-receiving'"),
            10,
        )
        proposal_id = self.proposal(
            "commerce", "receivings", "legacy-receiving", "--by", "worker",
            "--set", "quantity=11", "--why", "correct confirmed count",
        )
        self.run_command("commerce", "accept", proposal_id, "--by", "chief-of-staff", "--person-words", "Approve this change.")
        self.assertEqual(
            self.scalar("SELECT quantity FROM receivings WHERE id='legacy-receiving'"),
            11,
        )

    def test_recheck_4_non_finite_numbers_fail_every_write_path(self):
        added = self.run_command(
            "people", "add", "opportunities", "--by", "sol",
            "--set", "id=opp-nan", "--set", "title=Bad number",
            "--set", "pipeline=p", "--set", "stage=lead",
            "--set", "value=NaN", "--set", 'evidence_refs=["seed"]', ok=False,
        )
        self.assertIn("finite number required", added.stderr)

        changed = self.run_command(
            "people", "set", "opportunities", "opp-1", "--by", "sol",
            "--set", "value=Infinity", ok=False,
        )
        self.assertIn("finite number required", changed.stderr)

        proposed = self.run_command(
            "ugc", "propose", "creator_cycles", "cycle-1", "--by", "ugc-producer",
            "--set", "agreed_amount=NaN", "--set", "currency=USD",
            "--why", "invalid amount", ok=False,
        )
        self.assertIn("finite number required", proposed.stderr)

        with sqlite3.connect(self.db_path) as db:
            db.row_factory = sqlite3.Row
            db.execute(table.PROPOSAL_DDL)
            base_row = dict(db.execute(
                "SELECT * FROM creator_cycles WHERE id='cycle-1'"
            ).fetchone())
            db.execute(
                'INSERT INTO proposals '
                '(id,module,table_name,row_id,changes,base_row,why,"by",at,state) '
                "VALUES(?,?,?,?,?,?,?,?,?,'pending')",
                (
                    "P-non-finite", "ugc", "creator_cycles", "cycle-1",
                    json.dumps({"agreed_amount": "NaN", "currency": "USD"}),
                    json.dumps(base_row, sort_keys=True, separators=(",", ":")),
                    "invalid imported proposal", "ugc-producer",
                    "2026-09-18T21:02:00Z",
                ),
            )
        accepted = self.run_command(
            "ugc", "accept", "P-non-finite", "--by", "chief-of-staff", "--person-words", "Approve this change.", ok=False,
        )
        self.assertIn("finite number required", accepted.stderr)
        self.assertIsNone(self.scalar(
            "SELECT agreed_amount FROM creator_cycles WHERE id='cycle-1'"
        ))

    def test_recheck_5_unknown_rule_names_refuse_the_whole_rules_file(self):
        original = RULES.read_text()
        bad_cases = (
            ("commerce.restocks: approved_quantity", "commerc.restocks: approved_quantity", "commerc"),
            ("commerce.restocks: approved_quantity", "commerce.restockz: approved_quantity", "restockz"),
            ("commerce.restocks: approved_quantity", "commerce.restocks: approved_quantitty", "approved_quantitty"),
        )
        for old, new, bad_name in bad_cases:
            path = Path(self.temp.name) / (bad_name + ".md")
            path.write_text(original.replace(old, new, 1))
            with self.subTest(bad_name=bad_name):
                with self.assertRaisesRegex(SystemExit, bad_name):
                    table.load_rules(path, "people")

        duplicate = Path(self.temp.name) / "duplicate.md"
        duplicate.write_text(original.replace(
            "commerce.restocks: approved_quantity\n```",
            "commerce.restocks: approved_quantity\n"
            "commerce.restocks: approved_quantity\n```",
            1,
        ))
        with self.assertRaisesRegex(SystemExit, "duplicate rule commerce.restocks"):
            table.load_rules(duplicate, "people")

        uncovered = Path(self.temp.name) / "uncovered.md"
        uncovered.write_text(original.replace(
            "commerce.receivings: status=confirmed\n", "", 1
        ))
        with self.assertRaisesRegex(SystemExit, "commerce.receivings"):
            table.load_rules(uncovered, "people")

    def test_new_hole_history_rows_are_append_only_from_module_metadata(self):
        added = self.run_command(
            "people", "add", "interactions", "--by", "worker",
            "--set", "id=interaction-2", "--set", "person_id=person-1",
            "--set", "summary_author=worker",
            "--set", "happened_at=2026-09-18T21:03:00-04:00",
            "--set", "summary=New receipt", "--set", 'evidence_refs=["message-2"]',
        )
        self.assertIn("ok add interactions interaction-2", added.stdout)

        rewritten = self.run_command(
            "people", "set", "interactions", "interaction-1", "--by", "worker",
            "--set", "summary=Rewritten receipt", "--set", "person_id=person-2",
            ok=False,
        )
        self.assertIn("history", rewritten.stderr)
        self.assertEqual(
            self.scalar("SELECT summary FROM interactions WHERE id='interaction-1'"),
            "Sent request",
        )
        self.run_command(
            "people", "add", "meetings", "--by", "worker",
            "--set", "id=M1", "--set", "title=Original meeting",
            "--set", "happened_at=2026-09-18T21:04:00-04:00",
        )
        meeting = self.run_command(
            "people", "set", "meetings", "M1", "--by", "worker",
            "--set", "title=Rewritten meeting", "--set", "happened_at=2030-01-01",
            ok=False,
        )
        self.assertIn("history", meeting.stderr)
        self.assertEqual(
            self.scalar("SELECT title FROM meetings WHERE id='M1'"),
            "Original meeting",
        )
        self.assertTrue(
            {"activity", "comments", "approvals"}
            <= table.load_history_tables("work")
        )
        with self.assertRaisesRegex(SystemExit, "module metadata"):
            table.load_history_tables("missing-module")

    def test_must_fix_1_accepted_facts_are_locked(self):
        self.add_restock()
        proposal_id = self.proposal(
            "commerce", "restocks", "R1", "--by", "sol",
            "--set", "approved_quantity=10", "--why", "approve ten",
        )
        self.run_command("commerce", "accept", proposal_id, "--by", "chief-of-staff", "--person-words", "Approve this change.")
        changed = self.run_command(
            "commerce", "set", "restocks", "R1", "--by", "sol",
            "--set", "inventory_source_id=item-2",
            "--set", "destination_location_id=destination-2",
            "--set", "requested_quantity=999", ok=False,
        )
        self.assertIn("must use propose", changed.stderr)

        self.run_command(
            "commerce", "add", "receivings", "--by", "sol",
            "--set", "id=RC1", "--set", "restock_id=R1",
            "--set", "quantity=10", "--set", "counted_at=2026-09-18T21:00:00Z",
            "--set", "counted_by=sol", "--set", "evidence_ref=count-sheet",
        )
        receiving = self.proposal(
            "commerce", "receivings", "RC1", "--by", "sol",
            "--set", "status=confirmed", "--why", "verified count",
        )
        self.run_command("commerce", "accept", receiving, "--by", "chief-of-staff", "--person-words", "Approve this change.")
        refused_count = self.run_command(
            "commerce", "set", "receivings", "RC1", "--by", "sol",
            "--set", "quantity=999", ok=False,
        )
        self.assertIn("must use propose", refused_count.stderr)

        cycle = self.proposal(
            "ugc", "creator_cycles", "cycle-1", "--by", "ugc-producer",
            "--set", "agreed_amount=100.00", "--set", "currency=USD",
            "--why", "approved creator amount",
        )
        self.run_command("ugc", "accept", cycle, "--by", "chief-of-staff", "--person-words", "Approve this change.")
        moved = self.run_command(
            "ugc", "set", "creator_cycles", "cycle-1", "--by", "ugc-producer",
            "--set", "opportunity_id=opp-2", ok=False,
        )
        self.assertIn("must use propose", moved.stderr)

    def test_must_fix_2_concurrent_accept_happens_once(self):
        self.add_restock()
        proposal_id = self.proposal(
            "commerce", "restocks", "R1", "--by", "sol",
            "--set", "approved_quantity=10", "--why", "approve ten",
        )
        command = [
            str(COMMANDS["commerce"]), "--db", str(self.db_path), "--rules", str(RULES),
            "accept", proposal_id, "--by", "chief-of-staff", "--person-words", "Approve this change.",
        ]
        processes = [
            subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            for _ in range(2)
        ]
        results = [process.communicate() + (process.returncode,) for process in processes]
        self.assertEqual(sum(code == 0 for _, _, code in results), 1)
        self.assertEqual(
            self.scalar("SELECT count(*) FROM approvals WHERE version=?", (proposal_id,)),
            1,
        )

    def test_t611_accept_requires_nonblank_person_words_without_writes(self):
        self.add_restock()
        proposal_id = self.proposal(
            "commerce", "restocks", "R1", "--by", "sol",
            "--set", "approved_quantity=10", "--why", "The agent recommends ten.",
        )
        before = self.db_path.read_bytes()
        for flags in ((), ("--person-words", ""), ("--person-words", " \t\n")):
            with self.subTest(flags=flags):
                result = self.run_command(
                    "commerce", "accept", proposal_id, "--by", "architect", *flags, ok=False,
                )
                self.assertIn("--person-words", result.stderr)
                self.assertEqual(before, self.db_path.read_bytes())
                self.assertEqual("pending", self.scalar(
                    "SELECT state FROM proposals WHERE id=?", (proposal_id,),
                ))
                self.assertEqual(0, self.scalar("SELECT count(*) FROM approvals"))

    def test_t611_accept_saves_person_words_exactly_not_proposal_why(self):
        self.add_restock()
        reason = "The agent recommends ten."
        words = "  Yes, approve ten.\nKeep the delivery date.\t — Person  "
        proposal_id = self.proposal(
            "commerce", "restocks", "R1", "--by", "sol",
            "--set", "approved_quantity=10", "--why", reason,
        )
        self.run_command(
            "commerce", "accept", proposal_id, "--by", "architect", "--person-words", words,
        )
        self.assertEqual(words, self.scalar(
            "SELECT person_words FROM approvals WHERE version=?", (proposal_id,),
        ))
        self.assertEqual(reason, self.scalar(
            "SELECT why FROM proposals WHERE id=?", (proposal_id,),
        ))
        self.assertEqual("accepted", self.scalar(
            "SELECT state FROM proposals WHERE id=?", (proposal_id,),
        ))
        self.assertEqual(10, self.scalar("SELECT approved_quantity FROM restocks WHERE id='R1'"))

    def test_t611_legacy_list_selects_only_matching_accepted_approvals_without_writes(self):
        self.add_restock()
        reason = "The agent recommends ten."
        legacy = self.proposal(
            "commerce", "restocks", "R1", "--by", "sol",
            "--set", "approved_quantity=10", "--why", reason,
        )
        self.run_command(
            "commerce", "accept", legacy, "--by", "architect", "--person-words", "Yes, ten.",
        )
        with sqlite3.connect(self.db_path) as db:
            db.execute("UPDATE approvals SET person_words=? WHERE version=?", (reason, legacy))
            approval_id = db.execute("SELECT id FROM approvals WHERE version=?", (legacy,)).fetchone()[0]
        current = self.proposal(
            "commerce", "restocks", "R1", "--by", "sol",
            "--set", "approved_quantity=12", "--why", "The agent recommends twelve.",
        )
        self.run_command(
            "commerce", "accept", current, "--by", "architect", "--person-words", "Yes, twelve.",
        )
        self.proposal(
            "commerce", "restocks", "R1", "--by", "sol",
            "--set", "approved_quantity=14", "--why", "Still pending.",
        )
        before = self.db_path.read_bytes()
        result = subprocess.run(
            [sys.executable, str(HERE / "list_legacy_approval_words.py"), "--db", str(self.db_path)],
            capture_output=True, text=True,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([{"id": approval_id, "proposal": legacy, "person_words": reason}], json.loads(result.stdout))
        self.assertEqual(before, self.db_path.read_bytes())

    def test_t611_legacy_list_refuses_missing_database_without_creating_it(self):
        missing = Path(self.temp.name) / "missing.sqlite"
        result = subprocess.run(
            [sys.executable, str(HERE / "list_legacy_approval_words.py"), "--db", str(missing)],
            capture_output=True, text=True,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("Cannot list legacy approval words", result.stderr)
        self.assertFalse(missing.exists())

    def test_t146_named_agent_accepts_authorized_proposal_and_records_actor(self):
        self.add_restock()
        proposal_id = self.proposal(
            'commerce', 'restocks', 'R1', '--by', 'sol',
            '--set', 'approved_quantity=10', '--why', 'Synthetic direct request from Person: approve ten',
        )
        self.run_command('commerce', 'accept', proposal_id, '--by', 'architect', "--person-words", "Approve this change.")
        self.assertEqual(10, self.scalar("SELECT approved_quantity FROM restocks WHERE id='R1'"))
        self.assertEqual('architect', self.scalar('SELECT decided_by FROM proposals WHERE id=?', (proposal_id,)))
        self.assertEqual('commerce cli by architect', self.scalar('SELECT source FROM approvals WHERE version=?', (proposal_id,)))
        self.run_command('commerce', 'accept', proposal_id, '--by', 'sol', "--person-words", "Approve this change.", ok=False)
        self.assertEqual(1, self.scalar('SELECT count(*) FROM approvals WHERE version=?', (proposal_id,)))

    def test_must_fix_3_agreement_can_be_created_by_proposal(self):
        proposal_id = self.proposal(
            "people", "agreements", "agreement-1", "--by", "sol",
            "--set", "agreement_family_id=family-1", "--set", "version=1",
            "--set", "opportunity_id=opp-1", "--set", "type=creator",
            "--set", "counterparty_person_id=person-1",
            "--set", "value=125.50", "--set", "currency=USD",
            "--set", 'evidence_refs=["agreement-draft"]',
            "--why", "new creator agreement",
        )
        self.run_command("people", "accept", proposal_id, "--by", "person", "--person-words", "Approve this change.")
        self.assertEqual(
            self.scalar("SELECT value FROM agreements WHERE id='agreement-1'"),
            125.5,
        )

    def test_must_fix_4_values_actors_reasons_and_evidence_are_validated(self):
        bad_money = self.run_command(
            "people", "propose", "opportunities", "opp-1", "--by", "sol",
            "--set", "value=not-money", "--why", "bad value", ok=False,
        )
        self.assertIn("invalid real value", bad_money.stderr)

        blank_actor = self.run_command(
            "people", "add", "persons", "--by", "",
            "--set", "id=blank-actor", "--set", "display_name=Blank",
            "--set", 'evidence_refs=["source"]', ok=False,
        )
        self.assertIn("--by must not be blank", blank_actor.stderr)

        blank_reason = self.run_command(
            "people", "propose", "opportunities", "opp-1", "--by", "sol",
            "--set", "currency=USD", "--why", "", ok=False,
        )
        self.assertIn("--why must not be blank", blank_reason.stderr)

        for evidence in ("[ ]", "[null]", '[""]'):
            result = self.run_command(
                "people", "add", "persons", "--by", "sol",
                "--set", "id=bad-" + str(abs(hash(evidence))),
                "--set", "display_name=Bad Evidence",
                "--set", "evidence_refs=" + evidence, ok=False,
            )
            self.assertIn("non-empty list", result.stderr)

        self.run_command(
            "amazon", "add", "accounts", "--by", "sol",
            "--set", "id=A1", "--set", "source_account_id=S1",
            "--set", "label=US",
        )
        self.run_command(
            "amazon", "add", "compliance_cases", "--by", "sol",
            "--set", "id=C1", "--set", "account_id=A1",
            "--set", "requirement=Identity evidence",
        )
        resolved = self.run_command(
            "amazon", "set", "compliance_cases", "C1", "--by", "sol",
            "--set", "status=resolved", ok=False,
        )
        self.assertIn("evidence is required", resolved.stderr)

    def test_must_fix_5_shared_policy_read_only_reads_and_immutable_ids(self):
        with self.assertRaisesRegex(SystemExit, "rules file is missing"):
            table.load_rules((Path(__file__).resolve().parent / '../missing-proposal-rules.md'), "people")

        self.assertEqual(
            self.scalar("SELECT count(*) FROM sqlite_schema WHERE type='table' AND name='proposals'"),
            0,
        )
        self.run_command("people", "list", "persons")
        self.assertEqual(
            self.scalar("SELECT count(*) FROM sqlite_schema WHERE type='table' AND name='proposals'"),
            0,
        )

        self.run_command(
            "amazon", "add", "accounts", "--by", "sol",
            "--set", "id=A1", "--set", "source_account_id=S1",
            "--set", "label=US",
        )
        renamed = self.run_command(
            "amazon", "set", "accounts", "A1", "--by", "sol",
            "--set", "id=A2", ok=False,
        )
        self.assertIn("cannot change primary key", renamed.stderr)

        for module, command in COMMANDS.items():
            text = command.read_text()
            self.assertIn("from table import CommandConfig, main", text, module)
            self.assertNotIn("PROPOSAL_FIELDS", text, module)

    def test_status_fields_gate_only_named_transitions(self):
        self.add_restock()
        self.run_command(
            "commerce", "set", "restocks", "R1", "--by", "sol",
            "--set", "status=planned",
        )
        approved = self.run_command(
            "commerce", "set", "restocks", "R1", "--by", "sol",
            "--set", "status=approved", ok=False,
        )
        self.assertIn("must use propose", approved.stderr)

        self.run_command(
            "commerce", "add", "receivings", "--by", "sol",
            "--set", "id=RC1", "--set", "restock_id=R1",
            "--set", "quantity=10", "--set", "counted_at=2026-09-18T21:00:00Z",
            "--set", "counted_by=sol", "--set", "evidence_ref=count-sheet",
        )
        self.run_command(
            "commerce", "set", "receivings", "RC1", "--by", "sol",
            "--set", "status=disputed",
        )
        confirmed = self.run_command(
            "commerce", "set", "receivings", "RC1", "--by", "sol",
            "--set", "status=confirmed", ok=False,
        )
        self.assertIn("must use propose", confirmed.stderr)

        deliverable = self.proposal(
            "ugc", "deliverables", "D1", "--by", "ugc-producer",
            "--set", "creator_cycle_id=cycle-1", "--set", "promise_key=video-1",
            "--set", "format=video", "--set", "quantity=1",
            "--set", 'evidence_refs=["brief"]', "--why", "creator promise",
        )
        self.run_command("ugc", "accept", deliverable, "--by", "chief-of-staff", "--person-words", "Approve this change.")
        agreed = self.run_command(
            "ugc", "set", "deliverables", "D1", "--by", "ugc-producer",
            "--set", "status=agreed", ok=False,
        )
        self.assertIn("must use propose", agreed.stderr)

        self.run_command(
            "ugc", "add", "file_reqs", "--by", "ugc-producer",
            "--set", "id=F1", "--set", "creator_cycle_id=cycle-1",
            "--set", "provider=dropbox", "--set", "title=Files",
            "--set", 'evidence_refs=["request"]',
        )
        sent = self.run_command(
            "ugc", "set", "file_reqs", "F1", "--by", "ugc-producer",
            "--set", "status=sent", ok=False,
        )
        self.assertIn("must use propose", sent.stderr)
        send_proposal = self.proposal(
            "ugc", "file_reqs", "F1", "--by", "ugc-producer",
            "--set", "status=sent", "--set", "source_id=dropbox-1",
            "--set", "approval_ref=approval-1", "--set", "receipt_ref=send-receipt",
            "--set", "sent_interaction_id=interaction-1", "--why", "send approved request",
        )
        self.run_command("ugc", "accept", send_proposal, "--by", "person", "--person-words", "Approve this change.")
        self.run_command(
            "ugc", "set", "file_reqs", "F1", "--by", "ugc-producer",
            "--set", "status=received", "--set", "received_at=2026-09-18T22:00:00-04:00",
            "--set", "receipt_ref=received-files",
        )


if __name__ == "__main__":
    unittest.main()
