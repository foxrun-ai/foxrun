"""A skill release refreshes the installed workspace pages."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
import skill_scoped

class WorkspaceViewRefreshTests(unittest.TestCase):
    def test_skill_change_leaves_workspace_check_clean(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            home, portfolio = root / 'home', root / 'portfolio'
            script = home / 'base/make_workspaces_view.py'
            script.parent.mkdir(parents=True)
            script.write_bytes((Path(__file__).resolve().parents[2] / 'base/make_workspaces_view.py').read_bytes())
            (home / 'base/page_indexes.py').write_bytes(
                (Path(__file__).resolve().parents[2] / 'base/page_indexes.py').read_bytes())
            (home / 'skillwright').mkdir()
            (home / 'skills/demo').mkdir(parents=True)
            (home / 'skills/demo/SKILL.md').write_text('---\nname: demo\ndescription: First wording.\n---\n')
            ws = portfolio / 'shop'
            ws.mkdir(parents=True)
            (ws / 'AGENTS.md').write_text('# Shop\n')
            (ws / 'skills').mkdir()
            (ws / 'skills/demo').mkdir()
            (ws / 'skills/demo/SKILL.md').write_text('---\nname: demo\ndescription: First wording.\n---\n')
            class Tool:
                DOJO = home / 'skillwright'
            with patch.dict(os.environ, {'FOXRUN_PORTFOLIO': str(portfolio)}):
                skill_scoped.refresh_workspace_views(Tool)
                (ws / 'skills/demo/SKILL.md').write_text('---\nname: demo\ndescription: New wording.\n---\n')
                skill_scoped.refresh_workspace_views(Tool)
            check = subprocess.run([sys.executable, str(script), '--system-home', str(home),
                                    '--workspace-root', str(portfolio), '--check'], capture_output=True, text=True)
            self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
            self.assertIn('New wording', (home / 'workspaces/shop/SKILLS.md').read_text())

if __name__ == '__main__':
    unittest.main()
