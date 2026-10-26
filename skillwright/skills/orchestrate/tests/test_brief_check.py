from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest


BIN = Path(__file__).resolve().parents[1] / "bin" / "brief-check"
REPLAYS = Path(__file__).resolve().parents[1] / "replays"
ANCHORS = "## Source\nSELECT id FROM decisions;\n## Person's logged words\nPerson: copy the source.\n"
LEAD = "## Owning lead sources\nRead the owning lead's session and pipeline page.\n"
LEAD_MISSING = "owning-lead sources section for the business lifecycle or list"


class BriefCheckTests(unittest.TestCase):
    def run_brief(self, content: str, *flags: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            brief = Path(directory) / "brief.md"
            brief.write_text(content, encoding="utf-8")
            return subprocess.run([str(BIN), str(brief), *flags], capture_output=True, text=True)

    def replay(self, name: str, *flags: str) -> subprocess.CompletedProcess[str]:
        case = json.loads((REPLAYS / f"{name}.json").read_text(encoding="utf-8"))
        return self.run_brief(case["setup"]["files"]["brief.md"], *flags)

    def missing(self, result: subprocess.CompletedProcess[str]) -> list[str]:
        return json.loads(result.stdout)["missing"]

    def test_missing_decisions_fails(self) -> None:
        result = self.replay("missing-decisions", "--json")
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing decisions section", result.stderr)
        self.assertIn("decisions section", self.missing(result)[0])

    def test_t289_wording_requires_owning_lead_sources(self) -> None:
        content = "# T289 allowed statuses and opportunity kinds\n## Decisions\nSELECT id FROM decisions;\n## Person's logged words\nPerson 9.29: the customer-ops lifecycle was agreed with the communications lead on 9.22.\n## Current source of truth\nRead the customer-ops model page.\n## Scope and out of scope\nReview table shape only.\n"
        result = self.run_brief(content, "--json")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.missing(result), [LEAD_MISSING])

    def test_real_t289_panel_requires_owning_lead_sources(self) -> None:
        result = self.replay("t289-real-panel", "--json")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.missing(result), [LEAD_MISSING])

    def test_anchored_brief_passes(self) -> None:
        result = self.replay("anchored-brief")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"ok": True, "missing": []})
        self.assertIn("brief-check: pass", result.stderr)

    def test_well_known_bullet_is_not_an_id(self) -> None:
        result = self.run_brief("# Brief\n## Decisions\n- well-known\n## Person's logged words\nPerson: yes.\n", "--json")
        self.assertEqual(result.returncode, 1)
        self.assertIn("decisions section", self.missing(result)[0])

    def test_prose_select_anything_is_not_a_query(self) -> None:
        result = self.run_brief("# Brief\n## Decisions\nWe did not select anything from decisions.\n## Person's logged words\nPerson: yes.\n", "--json")
        self.assertEqual(result.returncode, 1)
        self.assertIn("decisions section", self.missing(result)[0])

    def test_owning_leads_sources_heading_passes(self) -> None:
        result = self.run_brief("# Allowed statuses\n" + ANCHORS + "## Owning lead's sources\nRead session 123.\n", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_sqlite_person_paste_passes(self) -> None:
        content = "# Brief\n## Decisions\nSELECT id FROM decisions;\n## Person's logged words\n1144|Person 9.29: yes.\n"
        self.assertEqual(self.run_brief(content, "--json").returncode, 0)

    def test_person_said_passes(self) -> None:
        content = "# Brief\n## Decisions\nSELECT id FROM decisions;\n## Person's logged words\nPerson said to copy the source.\n"
        self.assertEqual(self.run_brief(content, "--json").returncode, 0)

    def test_decisions_heading_with_query_passes(self) -> None:
        content = "# Brief\n## Decisions\nSELECT id FROM decisions;\n## Person's logged words\nPerson (9.29): yes.\n"
        self.assertEqual(self.run_brief(content, "--json").returncode, 0)

    def test_multiline_decisions_query_passes(self) -> None:
        content = "# Brief\n## Decisions\nSELECT id,\n       status,\n       statement\nFROM decisions;\n## Person's logged words\nPerson: yes.\n"
        self.assertEqual(self.run_brief(content, "--json").returncode, 0)

    def test_person_words_heading_variants_pass(self) -> None:
        for heading in ("Person's words", "Words from Person"):
            with self.subTest(heading=heading):
                content = "# Brief\n## Decisions\nSELECT id FROM decisions;\n## " + heading + "\nPerson: yes.\n"
                self.assertEqual(self.run_brief(content, "--json").returncode, 0)

    def test_code_comment_does_not_split_sections(self) -> None:
        content = "# Brief\n## Decisions\n```sql\n# comment\nSELECT id FROM decisions;\n```\n## Person's logged words\n```text\n# comment\n```\nPerson: yes.\n"
        self.assertEqual(self.run_brief(content, "--json").returncode, 0)

    def test_ci_stage_does_not_trigger(self) -> None:
        result = self.run_brief("# CI stage\n" + ANCHORS, "--json")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_business_terms_require_owning_lead_sources(self) -> None:
        for term in ("deal stages", "venture pipeline", "stage list", "opportunity kind", "status column values"):
            with self.subTest(term=term):
                result = self.run_brief("# " + term + "\n" + ANCHORS, "--json")
                self.assertEqual(self.missing(result), [LEAD_MISSING])

    def test_build_pipeline_and_all_kinds_of_do_not_trigger(self) -> None:
        for term in ("build pipeline", "all kinds of flaky tests", "test stage", "deploy pipeline", "CI pipeline"):
            with self.subTest(term=term):
                result = self.run_brief("# " + term + "\n" + ANCHORS, "--json")
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_build_stage_does_not_trigger(self) -> None:
        result = self.run_brief("# Build stage\n" + ANCHORS, "--json")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_opportunity_kinds_and_status_values_trigger(self) -> None:
        result = self.run_brief("# Opportunity kinds and status values\n" + ANCHORS, "--json")
        self.assertEqual(self.missing(result), [LEAD_MISSING])

    def test_statuses_and_kinds_trigger(self) -> None:
        result = self.run_brief("# Statuses and kinds\n" + ANCHORS, "--json")
        self.assertEqual(self.missing(result), [LEAD_MISSING])

    def test_empty_and_placeholder_sources_fail(self) -> None:
        for source in ("", "TBD", "none", "n/a", "todo", "Not found yet.", "?"):
            with self.subTest(source=source):
                result = self.run_brief("# Allowed statuses\n" + ANCHORS + "## Owning-lead sources\n" + source + "\n", "--json")
                self.assertEqual(self.missing(result), [LEAD_MISSING])

    def test_lead_heading_without_apostrophe_passes(self) -> None:
        result = self.run_brief("# Allowed statuses\n" + ANCHORS + LEAD, "--json")
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless((Path.home() / ".foxrun/data.db").is_file(), "decisions database is absent")
    def test_decision_id_must_exist_when_database_is_reachable(self) -> None:
        result = self.run_brief("# Brief\n## Decisions\ng-certainly-not-a-real-decision-id\n## Person's logged words\nPerson: yes.\n", "--json")
        self.assertIn("decisions section", self.missing(result)[0])

    def test_help(self) -> None:
        result = subprocess.run([str(BIN), "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("brief-check <brief.md> [--json]", result.stdout)
