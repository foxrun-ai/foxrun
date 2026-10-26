"""A move-only workspace gets index.md; its wiki stays unchanged; Atlas gets index.md too.
The person names the move-only workspace in config/person.json; the code holds no name.
Rerun: python3 -m unittest base.tests.test_page_indexes_move_only"""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
import page_indexes  # noqa: E402


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


class MoveOnlyIndex(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()
        self.portfolio, self.system = root / 'portfolio', root / 'system'
        self.system.mkdir()
        self.moved_name = 'sample-project'
        write(self.system / 'config/person.json', json.dumps({'name': 'person', 'workspace_settings': {self.moved_name: {'move_only': True}}}))
        atlas = self.portfolio / 'atlas'
        write(atlas / 'AGENTS.md', '# Atlas\n')
        write(atlas / 'config/topics.yaml', '{"topics": [{"id": "tools", "name": "Tools"}]}\n')
        moved = self.portfolio / self.moved_name
        write(moved / 'AGENTS.md', '# Sample project\n\nThe contract.\n')
        write(moved / 'wiki/concepts/page.md', '# A wiki page\n')

    def test_move_only_workspace_gets_index_and_no_topics_page(self):
        outputs, issues = page_indexes.build(self.portfolio, self.system, '2026-10-18', 'all')
        moved = self.portfolio / self.moved_name
        self.assertIn(moved / 'index.md', outputs)
        self.assertTrue(outputs[moved / 'index.md'].startswith('---\ntype: index\nworkspace: ' + self.moved_name + '\n'))
        self.assertNotIn(moved / 'wiki/TOPICS.md', outputs)
        self.assertFalse([i for i in issues if i['workspace'] == self.moved_name])

    def test_no_config_means_no_move_only_workspace(self):
        (self.system / 'config/person.json').unlink()
        outputs, _ = page_indexes.build(self.portfolio, self.system, '2026-10-18', 'all')
        self.assertIn(self.portfolio / self.moved_name / 'wiki/TOPICS.md', outputs)

    def test_atlas_gets_an_index_like_every_workspace(self):
        # g-atlas-is-a-standard-workspace-with-its-wiki-at-the-top repeals the old 'no index.md' rule.
        outputs, _ = page_indexes.build(self.portfolio, self.system, '2026-10-18', 'index')
        page = outputs[self.portfolio / 'atlas' / 'index.md']
        self.assertTrue(page.startswith('---\ntype: index\nworkspace: atlas\n'))
        self.assertIn('# Index: atlas', page)


    def test_write_gate_reads_closed_draft_and_always_removes_it(self):
        gate = self.system / 'base/lint_gate.py'
        write(gate, 'import pathlib,sys\npathlib.Path(sys.argv[-1]).read_text(encoding="utf-8")\n')
        target = self.portfolio / 'atlas/index.md'
        body = '# Index: atlas\n\nUnicode: café — ready.\n'
        real_temporary = tempfile.NamedTemporaryFile
        real_run = page_indexes.subprocess.run
        drafts = []

        def temporary(*args, **kwargs):
            draft = real_temporary(*args, **kwargs)
            drafts.append(draft)
            return draft

        def child(*args, **kwargs):
            self.assertTrue(drafts[-1].closed, 'Windows children cannot reopen an open draft')
            self.assertTrue(Path(drafts[-1].name).read_text(encoding='utf-8').startswith(body))
            return real_run(*args, **kwargs)

        with patch.object(page_indexes.tempfile, 'NamedTemporaryFile', side_effect=temporary), \
                patch.object(page_indexes.subprocess, 'run', side_effect=child):
            self.assertEqual(page_indexes.write_outputs({target: body}, self.portfolio, self.system), 1)
        self.assertEqual(target.read_bytes(), body.encode('utf-8'))
        self.assertFalse(Path(drafts[-1].name).exists())
        # A child refusal or launch failure must also remove the draft and preserve the page.
        for fail in (False, True):
            write(gate, 'raise SystemExit(1)\n')
            with patch.object(page_indexes.tempfile, 'NamedTemporaryFile', side_effect=temporary), \
                    patch.object(page_indexes.subprocess, 'run', side_effect=OSError('launch failed') if fail else child):
                with self.assertRaises(OSError if fail else ValueError):
                    page_indexes.write_outputs({target: body + 'new\n'}, self.portfolio, self.system)
            self.assertFalse(Path(drafts[-1].name).exists())
            self.assertEqual(target.read_bytes(), body.encode('utf-8'))


if __name__ == '__main__':
    unittest.main()
