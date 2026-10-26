"""Defaults resolve every shipped template; missing values remain an error."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from base import install_workspace as tool
from base.tests.support import shipped_paths


# T742: a local installed home has unrelated folders; copy only shipped inputs.
_INPUTS = {'base', 'work', 'memory', 'config', 'agents', 'capture', 'events', 'decisions'}


class TemplateDefaults(unittest.TestCase):
    def test_every_shipped_template_resolves_with_its_module_defaults(self):
        count = 0
        for module in ('base', 'work', 'memory', 'config', 'agents', 'capture', 'events', 'decisions'):
            defaults = json.loads((ROOT / module / 'defaults.json').read_text())
            for path in (ROOT / module).rglob('*'):
                if not path.is_file() or 'tests' in path.parts or path.suffix not in ('.md', '.jsonl', '.yaml'):
                    continue
                if path == ROOT / 'base/templates/index.md':
                    continue  # T697 (2841cc8): the index builder fills this one, not the installer.
                if 'template' in str(path.relative_to(ROOT / module)) or path.name in ('design.md', 'brand.md'):
                    with self.subTest(path=str(path.relative_to(ROOT))):
                        rendered, _ = tool.render_template(path.read_bytes(), defaults, path)
                        self.assertFalse(tool.PLACEHOLDER.search(rendered.decode()))
                    count += 1
        self.assertGreater(count, 30)

    def test_config_owner_override_and_missing_default(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            tree = root / 'tree'
            for path in shipped_paths(ROOT):
                relative = path.relative_to(ROOT)
                if relative.parts[0] not in _INPUTS or not path.is_file():
                    continue
                output = tree / relative
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, output)
            (tree / 'config/person.json').write_text('{"name":"avery"}')
            target = root / 'workspace'; target.mkdir()
            args = dict(modules_root=tree, target=target, live_vault=tree,
                        workspace_type='personal', raw_modules='base,work,memory',
                        target_workspace='maple-shop', install_timestamp='2026-10-13T00:00:00Z',
                        approved_tags=[], database=None, actor=None)
            plan = tool.plan_install(values={}, **args)
            self.assertEqual(plan['values']['owner'], 'avery')
            plan = tool.plan_install(values={'owner': 'rowan'}, **args)
            self.assertEqual(plan['values']['owner'], 'rowan')
            tool.apply_plan(plan)
            # T669 (9b0f89d): the design pack left the installer; the owner now lands in AGENTS.md.
            self.assertIn('rowan', (target / 'AGENTS.md').read_text())
            empty = root / 'empty'; empty.mkdir(); args['target'] = empty
            with (tree / 'base/templates/AGENTS.md').open('a') as handle:
                handle.write('\n{{unknown_day_one_value}}\n')
            with self.assertRaisesRegex(tool.InstallError, 'unknown_day_one_value'):
                tool.plan_install(values={}, **args)
