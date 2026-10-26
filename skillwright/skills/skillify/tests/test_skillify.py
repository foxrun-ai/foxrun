from __future__ import annotations

from contextlib import redirect_stderr
import importlib.machinery
import importlib.util
from io import StringIO
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1] if ROOT.parent.name == "skills" else ROOT.parent
SOURCES = REPO / "skills" if (REPO / "skills").is_dir() else REPO
if not (SOURCES / "runtime-session-search").is_dir():
    # A staged Dojo copy holds only the skill under check; the fixtures are the person's own skills.
    SOURCES = Path(os.environ.get("SKILLS_PERSON_ROOT") or Path(os.environ.get("FOXRUN_PORTFOLIO", "~/foxrun")).expanduser() / "skillwright").expanduser() / "skills"
# T675: the person's source holds only skills; the tools live in the installed Skillwright.
DOJO = REPO if (REPO / "tools" / "skill_ship.py").is_file() else Path(
    os.environ.get("SKILLS_DOJO_ROOT", "~/.foxrun/skillwright")).expanduser()
BIN = ROOT / "bin" / "skillify"
RELEASE_TOOL = DOJO / "tools" / "skill_ship.py"
SEARCH_BIN = SOURCES / "runtime-session-search" / "bin" / "runtime-session-search"
FIXTURES = SOURCES / "runtime-session-search" / "tests" / "fixtures"
LOADER = importlib.machinery.SourceFileLoader("skillify_cli", str(BIN))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC is not None
skillify = importlib.util.module_from_spec(SPEC)
sys.modules[LOADER.name] = skillify
LOADER.exec_module(skillify)


def seed_release_gate(system, source_system):
    """Use the real gate and engine with a labelled minimal skill-source fixture policy."""
    (system/'base').mkdir(parents=True,exist_ok=True)
    for name in ['lint.py','lint_gate.py']:shutil.copy2(source_system/'base'/name,system/'base'/name)
    shutil.copytree(source_system/'config/lint',system/'config/lint')
    (system/'config/lint/rules.tsv').write_text('id\twords\tkind\tscope\tlevel\nFIXTURE-BLANK-SKILL\tFixture skill pages contain text.\tblank_page\tsystem:*/skills/**/SKILL.md\terror\n')

class NestedGitTests(unittest.TestCase):
    def full_cli_without_replays(self, changed):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / 'skillwright'
            path = root / 'skills/demo-read'
            path.mkdir(parents=True)
            (path / 'SKILL.md').write_text('---\nname: demo-read\ndescription: Read the demonstration.\n---\n\nRead the demonstration input and return its stored text without changing the input.\n')
            shutil.copytree(ROOT, root / 'skills/skillify')
            shutil.copytree(RELEASE_TOOL.parent, root / 'tools')
            (root / 'manifests').mkdir()
            (root / 'config').mkdir()
            seed_release_gate(root.parent,DOJO.parent)
            (base/'portfolio').mkdir()
            (root / 'config/catalog.yaml').write_text(json.dumps(dict(
                version=1, where={'skillify':'off'}, host_specific={},
                claude_preserve_physical=[], claude_approval_required={})))
            def git(*args):
                return subprocess.run(['git', '-C', str(root), *args], check=True,
                                      capture_output=True, text=True).stdout.strip()
            git('init', '-q', '-b', 'main')
            git('config', 'user.name', 'CLI proof')
            git('config', 'user.email', 'proof@local')
            git('add', '.')
            git('commit', '-q', '-m', 'baseline')
            git('update-ref', 'refs/remotes/origin/main', git('rev-parse', 'HEAD'))
            if changed:
                (path / 'SKILL.md').write_text((path / 'SKILL.md').read_text() + 'Changed.\n')
            home = base / 'home'; home.mkdir()
            env = dict(os.environ, HOME=str(home), SKILLIFY_DOJO_ROOT=str(root),
                       SKILLS_DOJO_ROOT=str(root), SKILLIFY_RELEASE_TOOL=str(root / 'tools/skill_ship.py'),
                       PYTHONDONTWRITEBYTECODE='1', TMPDIR=str(base))
            # This nested fixture owns a different catalog from the triggering parent ship.
            env['SKILLS_CATALOG_DIGEST']=__import__('hashlib').sha256((root/'config/catalog.yaml').read_bytes()).hexdigest()
            env.update(FOXRUN_HOME=str(root.parent),FOXRUN_PORTFOLIO=str(base/'portfolio'))
            result = subprocess.run([sys.executable, '-B', str(root / 'skills/skillify/bin/skillify'),
                                     'check', 'demo-read'], env=env, capture_output=True, text=True)
            if changed:
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('check 8 replay cases', result.stderr)
                self.assertNotIn('warn only', result.stderr)
            else:
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('ready demo-read', result.stdout)
                self.assertIn('warn only', result.stderr)
            self.assertFalse((home / '.foxrun').exists())

    def test_complete_cli_unchanged_without_replays_warns(self):
        self.full_cli_without_replays(False)

    def test_complete_cli_changed_without_replays_refuses(self):
        self.full_cli_without_replays(True)

    def test_unchanged_untracked_modified_and_committed_nested_skill(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'skillwright'
            path = root / 'skills/demo-read'
            path.mkdir(parents=True)
            (path / 'SKILL.md').write_text('---\nname: demo-read\ndescription: Read the demonstration.\n---\n\nRead it.\n')
            def git(*args):
                return subprocess.run(['git', '-C', str(root), *args], check=True,
                                      capture_output=True, text=True).stdout.strip()
            git('init', '-q', '-b', 'main')
            git('config', 'user.name', 'Nested proof')
            git('config', 'user.email', 'proof@local')
            git('add', '.')
            git('commit', '-q', '-m', 'baseline')
            git('update-ref', 'refs/remotes/origin/main', git('rev-parse', 'HEAD'))
            self.assertFalse(skillify.skill_changed(root, 'demo-read'))
            # A clean nested skill without replays must warn, not refuse.
            with redirect_stderr(StringIO()):
                skillify.check_law(root, 'demo-read')
            new = root / 'skills/new-read'
            new.mkdir()
            (new / 'SKILL.md').write_text('new')
            self.assertTrue(skillify.skill_changed(root, 'new-read'))
            (path / 'SKILL.md').write_text((path / 'SKILL.md').read_text() + 'Changed.\n')
            self.assertTrue(skillify.skill_changed(root, 'demo-read'))
            git('add', '.')
            git('commit', '-q', '-m', 'nested change')
            self.assertTrue(skillify.skill_changed(root, 'demo-read'))
            git('update-ref', 'refs/remotes/origin/main', git('rev-parse', 'HEAD'))
            self.assertFalse(skillify.skill_changed(root, 'demo-read'))


CLAUDE_ID = "11111111-1111-4111-8111-111111111111"


def make_dojo(root: Path) -> Path:
    dojo = root / "dojo"
    (dojo / "manifests").mkdir(parents=True)
    (dojo / "config").mkdir()
    (dojo / "skills").mkdir()
    (dojo / "tools").mkdir()
    shutil.copy2(DOJO / "tools/skill_catalog.py", dojo / "tools/skill_catalog.py")
    (dojo / "config" / "catalog.yaml").write_text(
        json.dumps(
            {
                "version": 1,
                "where": {},
                "claude_preserve_physical": [],
                "claude_approval_required": {},
                "host_specific": {},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return dojo


def build_fixture_stores(root: Path) -> Path:
    stores = root / "stores"
    claude = stores / ".claude" / "projects" / "-Users-tester-project"
    codex = stores / ".codex" / "sessions" / "2026" / "08" / "22"
    hermes = stores / ".hermes"
    for path in (claude, codex, hermes):
        path.mkdir(parents=True)

    records = [json.loads(line) for line in (FIXTURES / "claude_session.jsonl").read_text().splitlines()]
    records[0]["sessionId"] = CLAUDE_ID
    records.extend(
        [
            {
                "type": "assistant",
                "sessionId": CLAUDE_ID,
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "CLAUDE PRIVATE REASONING"},
                        {
                            "type": "tool_use",
                            "id": "claude-call-1",
                            "name": "Bash",
                            "input": {"command": "printf claude-ok"},
                        },
                    ],
                },
            },
            {
                "type": "user",
                "sessionId": CLAUDE_ID,
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "claude-call-1",
                            "content": "claude-ok",
                            "is_error": False,
                        }
                    ],
                },
            },
            {
                "type": "assistant",
                "sessionId": CLAUDE_ID,
                "message": {"role": "assistant", "content": "done"},
            },
        ]
    )
    with (claude / f"{CLAUDE_ID}.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")

    codex_records = [json.loads(line) for line in (FIXTURES / "codex_rollout.jsonl").read_text().splitlines()]
    codex_records.extend(
        [
            {
                "type": "response_item",
                "payload": {"type": "reasoning", "summary": "CODEX PRIVATE REASONING"},
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "call_id": "codex-call-1",
                    "name": "exec",
                    "input": "const r = await tools.exec_command({cmd: 'printf codex-ok'});",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "call_id": "codex-call-1",
                    "output": [{"type": "input_text", "text": "codex-ok"}],
                },
            },
        ]
    )
    with (codex / "rollout-2026-08-22T14-00-00-codex-session-1.jsonl").open(
        "w", encoding="utf-8"
    ) as handle:
        for record in codex_records:
            handle.write(json.dumps(record) + "\n")

    database = hermes / "state.db"
    connection = sqlite3.connect(database)
    connection.executescript((FIXTURES / "hermes_state.sql").read_text())
    connection.execute("ALTER TABLE messages ADD COLUMN role TEXT")
    connection.execute("ALTER TABLE messages ADD COLUMN tool_call_id TEXT")
    connection.execute("ALTER TABLE messages ADD COLUMN tool_calls TEXT")
    connection.execute("ALTER TABLE messages ADD COLUMN tool_name TEXT")
    connection.execute("ALTER TABLE messages ADD COLUMN reasoning TEXT")
    connection.execute("UPDATE messages SET role = 'assistant'")
    connection.execute(
        "INSERT INTO messages (id, session_id, content, role) VALUES (2, 'hermes-session-1', 'run it', 'user')"
    )
    connection.execute(
        "INSERT INTO messages (id, session_id, content, role, tool_calls, reasoning) "
        "VALUES (3, 'hermes-session-1', '', 'assistant', ?, 'HERMES PRIVATE REASONING')",
        (
            json.dumps(
                [
                    {
                        "id": "hermes-call-1",
                        "function": {
                            "name": "tool_call",
                            "arguments": json.dumps(
                                {
                                    "name": "computer_use",
                                    "arguments": {"action": "click", "coordinate": [10, 20]},
                                }
                            ),
                        },
                    }
                ]
            ),
        ),
    )
    connection.execute(
        "INSERT INTO messages (id, session_id, content, role, tool_call_id, tool_name) "
        "VALUES (4, 'hermes-session-1', ?, 'tool', 'hermes-call-1', 'computer_use')",
        (json.dumps({"success": True, "clicked": [10, 20]}),),
    )
    connection.execute(
        "INSERT INTO messages (id, session_id, content, role) VALUES (5, 'hermes-session-1', 'done', 'assistant')"
    )
    connection.commit()
    connection.close()
    return stores


class ScaffoldTests(unittest.TestCase):
    def test_name_law_refuses_four_words_and_reserved_words(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dojo = make_dojo(Path(temporary))
            for name in ("phone-text-message-send", "phone-and-send", "phone-my-send", "phone-text-v2"):
                with self.subTest(name=name):
                    with self.assertRaisesRegex(skillify.SkillifyError, "~/.foxrun/skillwright/standards/skill-law.md"):
                        skillify.scaffold(dojo, name, "A test skill.")

    def test_phone_text_send_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dojo = make_dojo(Path(temporary))
            self.assertTrue(skillify.scaffold(dojo, "phone-text-send", "Send text.").is_dir())

    def test_name_override_warns_and_prints_reason(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dojo = make_dojo(Path(temporary))
            warnings = StringIO()
            with redirect_stderr(warnings):
                destination = skillify.scaffold(
                    dojo, "phone-text-message-send", "Send text.", name_override="Legacy contract"
                )
            self.assertTrue(destination.is_dir())
            self.assertIn("~/.foxrun/skillwright/standards/skill-law.md", warnings.getvalue())
            self.assertIn("Legacy contract", warnings.getvalue())

    def test_sibling_warning_lists_existing_skills(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dojo = make_dojo(Path(temporary))
            skillify.scaffold(dojo, "phone-screen-read", "Read screen.")
            skillify.scaffold(dojo, "phone-text-read", "Read text.")
            warnings = StringIO()
            with redirect_stderr(warnings):
                skillify.scaffold(dojo, "phone-text-send", "Send text.")
            self.assertIn("phone-screen-read", warnings.getvalue())
            self.assertIn("phone-text-read", warnings.getvalue())
            self.assertIn("~/.foxrun/skillwright/standards/skill-law.md", warnings.getvalue())

    def test_scaffold_creates_a_valid_skill_and_optional_stubs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dojo = make_dojo(Path(temporary))
            destination = skillify.scaffold(
                dojo,
                "demo-skill",
                "A valid demo skill.",
                with_bin=True,
                with_tests=True,
            )
            validator = skillify.load_frontmatter_validator(RELEASE_TOOL)
            validator(destination / "SKILL.md")
            self.assertTrue((destination / "bin" / "demo-skill").stat().st_mode & 0o100)
            self.assertTrue((destination / "tests" / "test_demo_skill.py").is_file())

    def test_duplicate_name_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dojo = make_dojo(Path(temporary))
            skillify.scaffold(dojo, "demo", "First.")
            with self.assertRaisesRegex(skillify.SkillifyError, "already exists"):
                skillify.scaffold(dojo, "demo", "Second.")

    def test_from_text_body_is_bounded_to_sixty_lines(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dojo = make_dojo(root)
            source = root / "source.md"
            source.write_text("\n".join(f"line {number}" for number in range(70)))
            destination = skillify.scaffold(dojo, "bounded", "Bounded.", from_text=source)
            _, body = skillify.split_frontmatter((destination / "SKILL.md").read_text())
            self.assertEqual(len(body), 61)


class KindTests(unittest.TestCase):
    def headings(self, path: Path) -> list[str]:
        return [line for line in path.read_text().splitlines() if line.startswith("## ")]

    def test_default_kind_is_knowledge(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dojo = make_dojo(Path(temporary))
            destination = skillify.scaffold(dojo, "demo-kb", "Read the demo page.")
            text = (destination / "SKILL.md").read_text()
            self.assertIn("kind: knowledge", text)
            self.assertEqual(self.headings(destination / "SKILL.md"), ["## Steps", "## Gotchas"])
            self.assertFalse((destination / "bin").exists())
            help_text = subprocess.run(
                [sys.executable, str(BIN), "new", "--help"], text=True, capture_output=True, check=True
            ).stdout
            self.assertIn("default: knowledge", " ".join(help_text.split()))
            args = skillify.build_parser().parse_args(["new", "x", "--description", "d"])
            self.assertEqual(args.kind, "knowledge")

    def test_knowledge_kind_has_done_checks_and_gotchas(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dojo = make_dojo(Path(temporary))
            destination = skillify.scaffold(dojo, "demo-kb-read", "Read the demo page.", kind="knowledge")
            text = (destination / "SKILL.md").read_text()
            skillify.load_frontmatter_validator(RELEASE_TOOL)(destination / "SKILL.md")
            self.assertEqual(text.count("Done when:"), 2)
            self.assertIn("fixes that step", text)
            self.assertNotIn("## Stop", text)

    def test_tool_kind_adds_a_bin_stub_that_follows_script_rules(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dojo = make_dojo(Path(temporary))
            destination = skillify.scaffold(
                dojo, "demo-file-send", "Send the demo file.", kind="tool", with_tests=True
            )
            self.assertIn("kind: tool", (destination / "SKILL.md").read_text())
            self.assertEqual(self.headings(destination / "SKILL.md"), ["## Steps", "## Gotchas"])
            binary = destination / "bin" / "demo-file-send"
            self.assertTrue(binary.stat().st_mode & 0o100)
            helped = subprocess.run(
                [sys.executable, str(binary), "--help"], text=True, capture_output=True,
                stdin=subprocess.DEVNULL, check=False,
            )
            self.assertEqual(helped.returncode, 0)
            self.assertIn("--dry-run", helped.stdout)
            dry = subprocess.run(
                [sys.executable, str(binary), "--dry-run"], text=True, capture_output=True,
                stdin=subprocess.DEVNULL, check=False,
            )
            self.assertEqual(dry.returncode, 0)
            self.assertEqual(json.loads(dry.stdout)["dry_run"], True)
            self.assertEqual(dry.stderr, "")
            skillify.run_skill_tests(destination)

    def test_driving_kind_adds_read_back_and_stop(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dojo = make_dojo(Path(temporary))
            destination = skillify.scaffold(dojo, "demo-page-read", "Read the demo page.", kind="driving")
            text = (destination / "SKILL.md").read_text()
            self.assertIn("kind: driving", text)
            self.assertEqual(
                self.headings(destination / "SKILL.md"), ["## Steps", "## Gotchas", "## Stop"]
            )
            self.assertLess(text.index("Read back the exact text"), text.index("Send only after the approved gate"))
            self.assertIn("Close only the tabs or apps you opened", text)
            self.assertIn("Never send without the approved gate", text)
            self.assertFalse((destination / "bin").exists())

    def test_with_bin_makes_a_tool_and_mixed_kinds_combine(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dojo = make_dojo(Path(temporary))
            legacy = skillify.scaffold(dojo, "demo-legacy", "Legacy flag.", with_bin=True)
            self.assertIn("kind: tool", (legacy / "SKILL.md").read_text())
            mixed = skillify.scaffold(dojo, "demo-mixed", "Mixed.", kind="driving,tool")
            text = (mixed / "SKILL.md").read_text()
            self.assertIn("kind: tool, driving", text)
            self.assertIn("## Stop", text)
            self.assertTrue((mixed / "bin" / "demo-mixed").is_file())

    def test_unknown_kind_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dojo = make_dojo(Path(temporary))
            with self.assertRaisesRegex(skillify.SkillifyError, "unknown skill kind"):
                skillify.scaffold(dojo, "demo-bad", "Bad.", kind="script")
            self.assertFalse((dojo / "skills" / "demo-bad").exists())

    def test_each_kind_passes_check(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dojo = make_dojo(Path(temporary))
            for name, kind in (("demo-kb-read", "knowledge"), ("demo-file-send", "tool"), ("demo-page-read", "driving")):
                with self.subTest(kind=kind):
                    skillify.scaffold(dojo, name, "Demo.", kind=kind, with_tests=True)
                    skillify.check_skill(dojo, name, tool=RELEASE_TOOL, ship_runner=lambda *_: None)


class SessionTests(unittest.TestCase):
    def test_three_native_fixture_stores_keep_tool_steps_and_drop_reasoning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dojo = make_dojo(root)
            stores = build_fixture_stores(root)
            cases = (
                ("claude", CLAUDE_ID, "claude-flow", "Bash", "printf claude-ok"),
                ("codex", "codex-session-1", "codex-flow", "exec", "printf codex-ok"),
                ("hermes", "hermes-session-1", "hermes-flow", "computer_use", "coordinate"),
            )
            for runtime, session_id, name, tool, argument in cases:
                destination = skillify.from_session(
                    dojo,
                    runtime,
                    session_id,
                    name,
                    search_bin=SEARCH_BIN,
                    store_root=stores,
                )
                text = (destination / "SKILL.md").read_text()
                self.assertIn(f"`{tool}`", text)
                self.assertIn(argument, text)
                self.assertIn("status: draft", text)
                self.assertNotIn("PRIVATE REASONING", text)

    def test_session_without_allowed_successful_tools_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dojo = make_dojo(root)
            stores = build_fixture_stores(root)
            claude_file = next((stores / ".claude" / "projects").glob("*/*.jsonl"))
            records = [json.loads(line) for line in claude_file.read_text().splitlines()]
            records = [record for record in records if "claude-call-1" not in json.dumps(record)]
            claude_file.write_text("\n".join(json.dumps(record) for record in records) + "\n")
            with self.assertRaisesRegex(skillify.SkillifyError, "no successful"):
                skillify.from_session(
                    dojo,
                    "claude",
                    CLAUDE_ID,
                    "empty-flow",
                    search_bin=SEARCH_BIN,
                    store_root=stores,
                )


class PromoteTests(unittest.TestCase):
    def test_promote_normalizes_frontmatter_and_keeps_hermes_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dojo = make_dojo(root)
            hermes = root / "hermes"
            source = hermes / "managed-demo"
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text(
                "---\nname: old-name\nversion: 1\ndescription: Managed demo.\n---\n# Demo\n"
            )
            destination, receipt = skillify.promote(dojo, hermes, "managed-demo")
            text = (destination / "SKILL.md").read_text()
            self.assertIn("name: managed-demo", text)
            self.assertIn("origin: hermes skill_manage", text.casefold())
            self.assertTrue((source / "SKILL.md").is_file())
            self.assertIn("local precedence", receipt)


class CheckTests(unittest.TestCase):
    def test_existing_four_word_name_passes_with_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dojo = make_dojo(Path(temporary))
            target = dojo / "skills" / "old-long-name-here"
            target.mkdir()
            (target / "SKILL.md").write_text(
                skillify.skill_document("old-long-name-here", "Old skill.", ["# Old skill"])
            )
            add_read_case(target)
            warnings = StringIO()
            with redirect_stderr(warnings):
                skillify.check_skill(
                    dojo, "old-long-name-here", tool=RELEASE_TOOL, ship_runner=lambda *_: None
                )
            self.assertIn("warning", warnings.getvalue())
            self.assertIn("~/.foxrun/skillwright/standards/skill-law.md", warnings.getvalue())

    def test_changed_skill_with_bad_name_warns_and_is_not_renamed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dojo = make_dojo(Path(temporary))
            target = dojo / "skills" / "old-skill-and-more"
            target.mkdir()
            (target / "SKILL.md").write_text(
                skillify.skill_document("old-skill-and-more", "Old skill.", ["# Old skill", "", "Changed line."])
            )
            add_read_case(target)
            warnings = StringIO()
            with redirect_stderr(warnings):
                skillify.check_skill(
                    dojo, "old-skill-and-more", tool=RELEASE_TOOL, ship_runner=lambda *_: None
                )
            message = warnings.getvalue()
            self.assertIn("warning: name 'old-skill-and-more'", message)
            self.assertIn("exempt until T245", message)
            self.assertIn("do not rename", message)
            self.assertTrue((target / "SKILL.md").is_file())
            self.assertIn("name: old-skill-and-more", (target / "SKILL.md").read_text())
            self.assertEqual(sorted(child.name for child in dojo.iterdir()), ["config", "manifests", "skills", "tools"])

    def test_new_name_that_breaks_the_law_is_still_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dojo = make_dojo(Path(temporary))
            with self.assertRaisesRegex(skillify.SkillifyError, "breaks ~/.foxrun/skillwright/standards/skill-law.md"):
                skillify.scaffold(dojo, "old-skill-and-more", "New skill.", kind="tool")

    def test_check_fails_on_missing_description(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dojo = make_dojo(Path(temporary))
            target = dojo / "skills" / "broken"
            target.mkdir()
            (target / "SKILL.md").write_text("---\nname: broken\n---\n# Broken\n")
            with self.assertRaisesRegex(RuntimeError, "description"):
                skillify.check_skill(
                    dojo,
                    "broken",
                    tool=RELEASE_TOOL,
                    ship_runner=lambda *_: None,
                )

    def test_check_passes_scaffold_and_adds_policy_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dojo = make_dojo(Path(temporary))
            skillify.scaffold(dojo, "ready-demo", "Ready demo.", with_tests=True)
            for _ in range(2):
                skillify.check_skill(
                    dojo,
                    "ready-demo",
                    tool=RELEASE_TOOL,
                    ship_runner=lambda *_: None,
                )
            policy = json.loads((dojo / "config" / "catalog.yaml").read_text())
            self.assertNotIn("publish", policy)
            self.assertNotIn("ready-demo", policy["where"])
            self.assertEqual(skillify.read_skill_catalog(dojo)[0].catalog_scope(policy, "ready-demo", dojo), "global")

    def test_check_refuses_the_checked_name_in_another_root_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dojo = make_dojo(Path(temporary))
            skillify.scaffold(dojo, "ready-demo", "Ready demo.")
            duplicate = dojo / "skills" / "other-folder"
            duplicate.mkdir()
            (duplicate / "SKILL.md").write_text(
                "---\nname: ready-demo\ndescription: Duplicate.\n---\n# Duplicate\n"
            )
            with self.assertRaisesRegex(skillify.SkillifyError, "duplicate or mismatched"):
                skillify.check_skill(
                    dojo,
                    "ready-demo",
                    tool=RELEASE_TOOL,
                    ship_runner=lambda *_: None,
                )

    def test_check_marks_session_draft_active_only_after_all_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dojo = make_dojo(root)
            stores = build_fixture_stores(root)
            destination = skillify.from_session(
                dojo,
                "claude",
                CLAUDE_ID,
                "session-demo",
                search_bin=SEARCH_BIN,
                store_root=stores,
            )
            skillify.check_skill(
                dojo,
                "session-demo",
                tool=RELEASE_TOOL,
                ship_runner=lambda *_: None,
            )
            self.assertIn("status: active", (destination / "SKILL.md").read_text())


def add_read_case(target: Path) -> None:
    """Give a hand-written test skill the one replay case a new or changed skill needs (check 8)."""
    skillify.write_replay_cases(
        target,
        [{"name": "read-purpose", "run": "read", "input": "What does it do?", "expect": {"output_contains": ["demo"]}}],
    )


def write_skill(dojo: Path, name: str, body: list[str], *, description: str = "Check the demo page and report what it shows.", kind: str | None = None, replay: bool = True) -> Path:
    target = dojo / "skills" / name
    target.mkdir(parents=True, exist_ok=True)
    (target / "SKILL.md").write_text(
        skillify.skill_document(name, description, body, kinds=[kind] if kind else None), encoding="utf-8"
    )
    if replay:
        add_read_case(target)
    return target


GOOD_STEPS = ["# Demo", "", "## Steps", "", "1. Open the page.", "   Done when: the title shows.", "", "## Gotchas", "", "- None yet."]


class LawCheckTests(unittest.TestCase):
    def law(self, dojo: Path, name: str, *, changed: bool = True) -> str:
        warnings = StringIO()
        with redirect_stderr(warnings):
            skillify.check_law(dojo, name, changed=changed)
        return warnings.getvalue()

    def test_check_1_trigger_opener(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dojo = make_dojo(Path(temporary))
            write_skill(dojo, "demo-good", GOOD_STEPS, description="Send the demo text to one chat after a read-back.", kind="knowledge")
            self.assertNotIn("check 1", self.law(dojo, "demo-good"))
            cut = "Send the demo text to one chat after a read-back and a verification of the thread."
            self.assertTrue(cut[56].isalnum() and cut[57].isalnum())
            write_skill(dojo, "demo-cut", GOOD_STEPS, description=cut, kind="knowledge")
            self.assertIn("check 1 trigger opener: the first 57 characters cut a word", self.law(dojo, "demo-cut"))
            write_skill(dojo, "demo-noun", GOOD_STEPS, description="The demo page, its chart, and its footer.", kind="knowledge")
            message = self.law(dojo, "demo-noun")
            self.assertIn("name no known verb", message)
            self.assertIn("~/.foxrun/skillwright/standards/skill-law.md", message)

    def test_check_2_catalog_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dojo = make_dojo(Path(temporary))
            write_skill(dojo, "demo-short", GOOD_STEPS, description="Check the demo.", kind="knowledge")
            write_skill(dojo, "demo-long", GOOD_STEPS, description="Check the demo. " + "x" * 1020, kind="knowledge")
            message = self.law(dojo, "demo-short")
            self.assertIn("description 15 chars; shelf total 1051 chars across 2 skills", message)
            with self.assertRaisesRegex(skillify.SkillifyError, "refuse: demo-long: check 2 catalog budget: description is 1036 chars"):
                self.law(dojo, "demo-long")
            self.assertIn("warn only until T245", self.law(dojo, "demo-long", changed=False))

    def test_check_3_body_size_and_references(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dojo = make_dojo(Path(temporary))
            good = write_skill(dojo, "demo-good", GOOD_STEPS + ["", "Read `references/one.md` when the page shows an error."], kind="knowledge")
            (good / "references").mkdir()
            (good / "references" / "one.md").write_text("# One\n\nNo further links.\n")
            self.assertNotIn("check 3", self.law(dojo, "demo-good"))
            long = write_skill(dojo, "demo-long", GOOD_STEPS + ["filler"] * 500 + ["", "`references/one.md`"], kind="knowledge")
            (long / "references").mkdir()
            (long / "references" / "one.md").write_text("# One\n\nThen read [two](two.md).\n")
            (long / "references" / "two.md").write_text("# Two\n")
            message = self.law(dojo, "demo-long")
            self.assertIn("check 3 body size: SKILL.md has", message)
            self.assertIn("references/one.md links to a further reference references/two.md", message)
            self.assertIn("references/one.md has no when-to-read line near it", message)

    def test_check_4_dead_links_refuse_new_and_warn_existing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dojo = make_dojo(Path(temporary))
            good = write_skill(dojo, "demo-good", GOOD_STEPS + ["", "Run `scripts/go.py` for the page. See [the notes](notes.md)."], kind="knowledge")
            (good / "scripts").mkdir()
            (good / "scripts" / "go.py").write_text("")
            (good / "notes.md").write_text("")
            self.assertNotIn("check 4", self.law(dojo, "demo-good"))
            write_skill(dojo, "demo-dead", GOOD_STEPS + ["", "See [mechanics](SKILL-MECHANICS.md)."], kind="knowledge")
            with self.assertRaisesRegex(skillify.SkillifyError, "check 4 dead link: SKILL.md line 18 names SKILL-MECHANICS.md"):
                self.law(dojo, "demo-dead")
            message = self.law(dojo, "demo-dead", changed=False)
            self.assertIn("check 4 dead link", message)
            self.assertIn("warn only until T245", message)

    def test_check_4_exemptions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dojo = make_dojo(Path(temporary))
            body = GOOD_STEPS + [
                "",
                "```bash example",
                "python3 scripts/missing.py",
                "```",
                "",
                "For example:",
                "",
                "```text",
                "references/also-missing.md",
                "```",
                "",
                "Read `references/<topic>.md` when the topic comes up.",
                "Write `scripts/{name}.py` for each case.",
                "The run writes `outputs/report.md` and [the log](runs/today.log).",
                "Tool output lands in `references/tmp/scratch.md`.",
            ]
            write_skill(dojo, "demo-exempt", body, kind="knowledge")
            self.assertNotIn("check 4", self.law(dojo, "demo-exempt"))
            write_skill(dojo, "demo-code", GOOD_STEPS + ["", "```bash", "python3 scripts/missing.py", "```"], kind="knowledge")
            with self.assertRaisesRegex(skillify.SkillifyError, "names scripts/missing.py"):
                self.law(dojo, "demo-code")

    def test_check_5_gotchas_steps_and_done_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dojo = make_dojo(Path(temporary))
            skillify.scaffold(dojo, "demo-kb-read", "Read the demo page.", kind="knowledge")
            self.assertNotIn("check 5", self.law(dojo, "demo-kb-read"))
            write_skill(dojo, "demo-bare", ["# Demo", "", "## Steps", "", "1. Open the page.", "2. Read it.", "   Done when: the text shows."], kind="knowledge")
            message = self.law(dojo, "demo-bare")
            self.assertIn("check 5 gotchas: a knowledge skill needs a ## Gotchas section", message)
            self.assertIn("step 'Open the page.' has no 'Done when:' check", message)
            self.assertNotIn("Read it.", message)
            write_skill(dojo, "demo-none", ["# Demo"], kind="driving")
            self.assertIn("a driving skill needs a ## Steps section", self.law(dojo, "demo-none"))

    def test_check_6_script_rules(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dojo = make_dojo(Path(temporary))
            skillify.scaffold(dojo, "demo-file-send", "Send the demo file.", kind="tool")
            self.assertNotIn("check 6", self.law(dojo, "demo-file-send"))
            bad = write_skill(dojo, "demo-bad-tool", GOOD_STEPS, kind="tool")
            (bad / "bin").mkdir()
            script = bad / "bin" / "demo-bad-tool"
            script.write_text(
                "#!/usr/bin/env python3\nimport sys\nfrom pathlib import Path\n"
                "if '--help' in sys.argv:\n    sys.exit(2)\n"
                "name = input('name? ')\nPath('out.txt').write_text(name)\n"
            )
            script.chmod(0o755)
            quiet = bad / "bin" / "quiet"
            quiet.write_text("#!/bin/sh\necho hi\n")
            quiet.chmod(0o755)
            message = self.law(dojo, "demo-bad-tool")
            self.assertIn("bin/demo-bad-tool --help exited 2 without usage text", message)
            self.assertIn("bin/demo-bad-tool asks for input", message)
            self.assertIn("bin/demo-bad-tool writes files but takes no --dry-run", message)
            self.assertIn("bin/quiet shows no --help handling; not run", message)
            self.assertFalse((bad / "out.txt").exists())

    def test_unknown_kind_skips_checks_5_and_6(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dojo = make_dojo(Path(temporary))
            write_skill(dojo, "demo-bet", ["# Demo"], kind="bet")
            message = self.law(dojo, "demo-bet")
            self.assertIn("unknown kind bet counts as undeclared; checks 5 and 6 skipped", message)
            self.assertNotIn("check 5", message)
            self.assertNotIn("check 6", message)
            write_skill(dojo, "demo-plain", ["# Demo"])
            self.assertIn("no kind declared; checks 5 and 6 skipped", self.law(dojo, "demo-plain"))

    def test_kit_skill_and_unchanged_skill_only_warn(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dojo = make_dojo(Path(temporary))
            write_skill(dojo, "demo-kit", [skillify.KIT_MARKER + " -->", "See [gone](gone.md)."])
            self.assertIn("warn only until T245", self.law(dojo, "demo-kit", changed=True))
            env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
            for args in (["init", "-q", "-b", "main"], ["add", "."], ["commit", "-q", "-m", "base"]):
                subprocess.run(["git", "-C", str(dojo), *args], check=True, env=env, capture_output=True)
            self.assertFalse(skillify.skill_changed(dojo, "demo-kit"))
            (dojo / "skills" / "demo-kit" / "SKILL.md").write_text((dojo / "skills" / "demo-kit" / "SKILL.md").read_text() + "\nChanged.\n")
            self.assertTrue(skillify.skill_changed(dojo, "demo-kit"))
            write_skill(dojo, "demo-new", ["# Demo"])
            self.assertTrue(skillify.skill_changed(dojo, "demo-new"))


def write_script(target: Path, name: str, source: str) -> Path:
    script = target / "bin" / name
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("#!/usr/bin/env python3\n" + source, encoding="utf-8")
    script.chmod(0o755)
    return script


def write_case(target: Path, case: dict) -> None:
    skillify.write_replay_cases(target, [case])


REHEARSE_SOURCE = (
    "import json, sys\n"
    "args = sys.argv[1:]\n"
    "text = args[args.index('--text') + 1]\n"
    "if '--rehearsal' not in args:\n"
    "    open(args[args.index('--marker') + 1], 'w').write('ran')\n"
    "    raise SystemExit(3)\n"
    "print(json.dumps({'ok': True, 'rehearsal': True, 'would_send': {'to': 'demo', 'text': text}}))\n"
)


class ReplayTests(unittest.TestCase):
    def test_scaffold_writes_one_example_case_per_kind(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dojo = make_dojo(Path(temporary))
            expected = {
                "demo-kb-read": ("knowledge", ["read-purpose.json"]),
                "demo-file-send": ("tool", ["dry-run-plan.json"]),
                "demo-page-read": ("driving", ["rehearse-send.json"]),
                "demo-page-send": ("tool,driving", ["dry-run-plan.json", "rehearse-send.json"]),
            }
            for name, (kind, files) in expected.items():
                with self.subTest(kind=kind):
                    skillify.scaffold(dojo, name, "Demo.", kind=kind)
                    self.assertEqual(sorted(path.name for path in (dojo / "skills" / name / "replays").iterdir()), files)
                    for case in skillify.load_replay_cases(dojo / "skills" / name):
                        self.assertIn(case["run"], skillify.REPLAY_RUNS)
            rehearsal = json.loads((dojo / "skills" / "demo-page-read" / "replays" / "rehearse-send.json").read_text())
            self.assertEqual(rehearsal["expect"]["sent_text"], "Hello from the replay.")

    def test_tool_scaffold_dry_run_case_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dojo = make_dojo(Path(temporary))
            skillify.scaffold(dojo, "demo-file-send", "Demo.", kind="tool")
            with redirect_stderr(StringIO()) as log:
                results = skillify.run_replays(dojo, "demo-file-send")
            self.assertEqual(results, [("dry-run-plan", "pass", "end state matches")])
            self.assertIn("replay: demo-file-send/dry-run-plan (dry-run): pass", log.getvalue())

    def test_dry_run_case_checks_files_in_the_temporary_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dojo = make_dojo(Path(temporary))
            target = write_skill(dojo, "demo-note-write", ["# Demo"], replay=False)
            write_script(
                target, "demo-note-write",
                "import os, sys\nfrom pathlib import Path\n"
                "folder = Path(sys.argv[1]) / 'notes'\nfolder.mkdir()\n"
                "(folder / 'one.md').write_text(Path(os.environ['HOME'], 'seed.txt').read_text())\nprint(folder / 'one.md')\n",
            )
            case = {
                "name": "write-note", "run": "dry-run", "input": "bin/demo-note-write {tmp}/ws",
                "setup": {"dirs": ["ws"], "files": {"seed.txt": "seeded"}},
                "expect": {"exit": 0, "output_contains": ["{tmp}/ws/notes/one.md"], "files": ["ws/notes/*.md"]},
            }
            write_case(target, case)
            with redirect_stderr(StringIO()) as log:
                self.assertEqual(skillify.run_replays(dojo, "demo-note-write")[0][1], "pass")
            self.assertIn("no --dry-run; the case runs sealed", log.getvalue())
            case["expect"]["files"] = ["ws/notes/two.md"]
            write_case(target, case)
            with redirect_stderr(StringIO()), self.assertRaisesRegex(skillify.SkillifyError, "no file matches 'ws/notes/two.md'"):
                skillify.run_replays(dojo, "demo-note-write")

    def test_failing_case_refuses_new_and_existing_skills(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dojo = make_dojo(Path(temporary))
            skillify.scaffold(dojo, "demo-file-send", "Demo.", kind="tool")
            write_case(dojo / "skills" / "demo-file-send", {
                "name": "dry-run-plan", "run": "dry-run", "input": "bin/demo-file-send --dry-run",
                "expect": {"exit": 0, "output_contains": ["never printed"]},
            })
            for changed in (True, False):
                with self.subTest(changed=changed), redirect_stderr(StringIO()):
                    with self.assertRaisesRegex(skillify.SkillifyError, "replay dry-run-plan failed: output lacks 'never printed'"):
                        skillify.check_skill(dojo, "demo-file-send", tool=RELEASE_TOOL, ship_runner=lambda *_: None, changed=changed)

    def test_missing_cases_refuse_new_skills_and_warn_existing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dojo = make_dojo(Path(temporary))
            write_skill(dojo, "demo-bare", GOOD_STEPS, kind="knowledge", replay=False)
            with redirect_stderr(StringIO()), self.assertRaisesRegex(skillify.SkillifyError, "check 8 replay cases: no replay cases in replays/"):
                skillify.check_law(dojo, "demo-bare", changed=True)
            warnings = StringIO()
            with redirect_stderr(warnings):
                skillify.check_law(dojo, "demo-bare", changed=False)
            self.assertIn("check 8 replay cases: no replay cases", warnings.getvalue())
            self.assertIn("warn only until T245", warnings.getvalue())

    def test_rehearsal_flag_is_required_and_sent_text_must_match(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dojo = make_dojo(root)
            marker = root / "marker"
            target = write_skill(dojo, "demo-text-send", ["# Demo"], replay=False)
            write_script(target, "demo-text-send", REHEARSE_SOURCE)
            case = {
                "name": "rehearse-hello", "run": "rehearsal",
                "input": f"bin/demo-text-send --rehearsal --text 'Hi there.' --marker {marker}",
                "expect": {"exit": 0, "sent_text": "Hi there."},
            }
            write_case(target, case)
            with redirect_stderr(StringIO()):
                self.assertEqual(skillify.run_replays(dojo, "demo-text-send")[0][1], "pass")
            case["expect"]["sent_text"] = "Hi there!"
            write_case(target, case)
            with redirect_stderr(StringIO()), self.assertRaisesRegex(skillify.SkillifyError, "would have sent 'Hi there.', expected 'Hi there!'"):
                skillify.run_replays(dojo, "demo-text-send")
            case["input"] = f"bin/demo-text-send --text 'Hi there.' --marker {marker}"
            write_case(target, case)
            with redirect_stderr(StringIO()), self.assertRaisesRegex(skillify.SkillifyError, "must carry --rehearsal"):
                skillify.run_replays(dojo, "demo-text-send")
            self.assertFalse(marker.exists())

    def test_agent_cases_are_listed_and_run_only_with_the_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dojo = make_dojo(Path(temporary))
            skillify.scaffold(dojo, "demo-kb-read", "Demo.", kind="knowledge")
            skillify.scaffold(dojo, "demo-page-read", "Demo.", kind="driving")
            calls = []

            def runner(agent: str, prompt: str, cwd: Path) -> str:
                calls.append((agent, prompt, cwd))
                return "The demo skill. Would send: Hello from the replay."

            with redirect_stderr(StringIO()):
                for name in ("demo-kb-read", "demo-page-read"):
                    self.assertEqual(skillify.run_replays(dojo, name, agent_runner=runner)[0][1], "listed")
                self.assertEqual(calls, [])
                for name in ("demo-kb-read", "demo-page-read"):
                    self.assertEqual(skillify.run_replays(dojo, name, agent="claude", agent_runner=runner)[0][1], "pass")
            self.assertEqual([call[0] for call in calls], ["claude", "claude"])
            self.assertIn("You have no tools. Never send anything.", calls[1][1])
            self.assertIn("name: demo-page-read", calls[1][1])
            self.assertIn("stop before the send", calls[1][1])
            with redirect_stderr(StringIO()), self.assertRaisesRegex(skillify.SkillifyError, "answer lacks"):
                skillify.run_replays(dojo, "demo-kb-read", agent="claude", agent_runner=lambda *_: "nothing useful")
            with self.assertRaisesRegex(skillify.SkillifyError, "unknown replay agent"):
                skillify.run_replays(dojo, "demo-kb-read", agent="hermes")
            args = skillify.build_parser().parse_args(["check", "demo-kb-read", "--replay-agent", "claude"])
            self.assertEqual(args.replay_agent, "claude")

    def test_bad_case_shape_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            dojo = make_dojo(Path(temporary))
            target = write_skill(dojo, "demo-bad-case", ["# Demo"], replay=False)
            bad_cases = {
                "a rehearsal case needs 'expect.sent_text'": {"name": "no-text", "run": "rehearsal", "input": "go", "expect": {"exit": 0}},
                "'run' must be one of": {"name": "bad-run", "run": "live", "input": "go", "expect": {"exit": 0}},
                "must stay inside the temporary folder": {"name": "escape", "run": "dry-run", "input": "bin/x", "setup": {"dirs": ["../out"]}, "expect": {"exit": 0}},
            }
            for message, case in bad_cases.items():
                with self.subTest(message=message):
                    shutil.rmtree(target / "replays", ignore_errors=True)
                    write_case(target, case)
                    with self.assertRaisesRegex(skillify.SkillifyError, message):
                        skillify.load_replay_cases(target)

    def test_from_session_writes_a_read_case_for_the_first_step(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dojo = make_dojo(root)
            destination = skillify.from_session(
                dojo, "claude", CLAUDE_ID, "session-demo", search_bin=SEARCH_BIN, store_root=build_fixture_stores(root),
            )
            case = skillify.load_replay_cases(destination)[0]
            self.assertEqual((case["run"], case["expect"]["output_contains"]), ("read", ["Bash"]))


if __name__ == "__main__":
    unittest.main()


class ShelfLocationTests(unittest.TestCase):
    def test_copy_outside_the_dojo_still_targets_the_dojo(self) -> None:
        import shutil, tempfile, subprocess, os
        with tempfile.TemporaryDirectory() as tmp:
            shelf = Path(tmp) / "release" / "skillify" / "bin"
            shelf.mkdir(parents=True)
            shutil.copy(ROOT / "bin" / "skillify", shelf / "skillify")
            env = dict(os.environ)
            env.pop("SKILLS_DOJO_ROOT", None)
            env.pop("SKILLIFY_DOJO_ROOT", None)
            probe = "import importlib.machinery as m, importlib.util as u, sys; " \
                    "l=m.SourceFileLoader('sk', sys.argv[1]); s=u.spec_from_loader('sk', l); mod=u.module_from_spec(s); " \
                    "l.exec_module(mod); print(mod.DEFAULT_DOJO)"
            out = subprocess.run(["python3", "-c", probe, str(shelf / "skillify")], capture_output=True, text=True, env=env, check=True).stdout.strip()
            self.assertEqual(Path(out), Path("~/.foxrun/skillwright").expanduser())
