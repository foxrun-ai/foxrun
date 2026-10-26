"""Direct command startup uses an empty home and no product search path."""

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = _FoxPath(__file__).resolve().parents[2]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
from base.tests.support import shipped_paths
_fox_test_setup()
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def shipped(name):
    parts = Path(name).parts
    if 'not-shipped' in parts or 'tests' in parts or name.endswith('_tests.py'):
        return False
    if len(parts) > 2 and parts[0] == 'modules':
        manifest = ROOT / 'modules' / parts[1] / 'install.json'
        if manifest.exists() and json.loads(manifest.read_text()).get('ships') is False:
            return False
    return not any(s in Path(name).name.lower() for s in ('.env', 'credential', 'secret', 'token', 'auth'))


def probe():
    # T742: commands come from the shipped list, not local installed folders.
    names = [p.relative_to(ROOT).as_posix() for p in shipped_paths(ROOT) if p.is_file()]
    results = []
    with tempfile.TemporaryDirectory() as folder:
        home = Path(folder)
        env = {'HOME': str(home), 'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
               'FOXRUN_HOME': str(home / 'system'), 'FOXRUN_PORTFOLIO': str(home / 'portfolio'),
               'FOXRUN_STATE': str(home / 'state'), 'FOXRUN_PERSON': 'avery',
               'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1',
               'CAPTURE_ROOT': str(home / 'captures'), 'CAPTURE_STORE': str(home / 'capture.db')}
        for name in names:
            # 4fe39f0: the skill ship trigger is a Git hook, not a --help command.
            if (not shipped(name) or Path(name).suffix not in ('', '.py', '.sh')
                    or name.startswith('hooks/') or name == 'skillwright/tools/skill-ship-trigger.sh'):
                continue
            source = (ROOT / name).read_text()
            if not (('__main__' in source and 'argparse' in source) or
                    source.startswith('#!') and Path(name).suffix in ('', '.sh')):
                continue
            interpreter = ('/bin/sh' if source.startswith('#!/bin/sh') else
                           '/bin/bash' if source.startswith(('#!/bin/bash', '#!/usr/bin/env bash')) else
                           '/usr/bin/python3')
            try:
                p = subprocess.run([interpreter, '-B', str(ROOT / name), '--help'] if interpreter.endswith('python3')
                                   else [interpreter, str(ROOT / name), '--help'],
                                   cwd=home, env=env, capture_output=True, text=True, timeout=20,
                                   stdin=subprocess.DEVNULL)
                results.append({'command': name, 'exit': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr})
            except subprocess.TimeoutExpired:
                results.append({'command': name, 'exit': 124, 'stderr': 'timeout'})
    return results


class DirectStartup(unittest.TestCase):
    def test_value_sets_direct(self):
        with tempfile.TemporaryDirectory() as folder:
            p = subprocess.run(['/usr/bin/python3', '-B', str(ROOT / 'base/value_sets.py'), '--help'],
                               cwd=folder, env={'HOME': folder, 'FOXRUN_HOME': folder,
                                               'FOXRUN_PERSON': 'avery', 'PYTHONDONTWRITEBYTECODE': '1'},
                               capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)

    def test_all_commands_have_no_import_failures(self):
        results = probe()
        # 42 table commands moved to their packs and add-ons (g-business-packs-do-not-ship, g-people-ships-with-small-talk).
        # g-business-packs-do-not-ship (44cee23): the shipped list has fewer commands than a live home.
        self.assertGreaterEqual(len(results), 125)
        self.assertEqual([r for r in results if 'ModuleNotFoundError' in r.get('stderr', '') or
                          'ImportError' in r.get('stderr', '')], [])
        # These two commands do not implement help; input refusal still proves startup.
        excluded_runtime = {'agents/tools/profile_check.py', 'agents/tools/tool_probe.py'}
        for row in results:
            if row['command'] in excluded_runtime:
                self.assertEqual(row['exit'], 2)
                self.assertEqual(row['stdout'].strip(), 'Claude and Codex on day one.')
        no_help = {'capture/capture-check'} | excluded_runtime
        self.assertEqual([r for r in results if r['exit'] and r['command'] not in no_help], [])


if __name__ == '__main__':
    unittest.main()
