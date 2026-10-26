#!/usr/bin/env python3
"""T755: runs have one home, one shape, and a budget.

Run from the system home: python3 -m unittest memory.tests.test_runs
"""
from datetime import datetime
from types import SimpleNamespace
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from memory import runs  # noqa: E402


class RunHome(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='runs-home-')
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()
        self.system, self.portfolio, self.service = root / 'system', root / 'portfolio', root / 'service'
        for folder in (self.system / 'runs', self.portfolio / 'shop/history/runs', self.service):
            folder.mkdir(parents=True)
        self.env = patch.dict(os.environ, {'FOXRUN_HOME': str(self.system), 'FOXRUN_PORTFOLIO': str(self.portfolio),
                                           'FOXRUN_STATE': str(self.service)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.today = '2026-10-24'

    def check(self):
        return runs.check(self.system, self.portfolio, today=self.today)

    def errors(self):
        return [row for row in self.check() if row['level'] == 'error']

    def test_a_new_run_has_the_shape_and_passes_the_check(self):
        moment = datetime(2026, 10, 24, 9).astimezone()
        folder = runs.new_run('T755', 'keeper', 'runs-move', self.system, moment)
        self.assertEqual(folder, self.system / 'runs/2026-10-24/T755-keeper-runs-move')
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ['brief.md', 'heavy'])
        self.assertIn('Budget: the run check warns above 200 MB', (folder / 'brief.md').read_text())
        (folder / 'result.md').write_text('# Result\n')
        self.assertEqual(self.check(), [])
        again = runs.new_run('T755', 'keeper', 'runs-move', self.system, moment)
        self.assertEqual(again.name, 'T755-keeper-runs-move-2')

    def test_a_bad_name_is_refused(self):
        for task, seat, what in (('755', 'keeper', 'x'), ('T755', 'Keeper', 'x'), ('T755', 'keeper', 'Has Space')):
            with self.assertRaises(ValueError):
                runs.run_name(task, seat, what)

    def test_session_starts_are_lines_not_folders(self):
        moment = datetime(2026, 10, 24, 9).astimezone()
        runs.record_session({'workspace': 'shop', 'seat': 'keeper', 'session': 's1'}, self.system, moment)
        runs.record_session({'workspace': 'shop', 'seat': None, 'session': 's2'}, self.system, moment)
        file = self.system / 'runs/2026-10-24/sessions.jsonl'
        self.assertEqual(len(file.read_text().splitlines()), 2)
        self.assertEqual([row['session'] for row in runs.sessions(self.system)], ['s1', 's2'])
        self.assertEqual([p.name for p in (self.system / 'runs/2026-10-24').iterdir()], ['sessions.jsonl'])
        self.assertEqual(self.check(), [])

    def test_off_shape_and_elsewhere_runs_are_errors(self):
        (self.system / 'runs/2026-10-24-worker-abc').mkdir()             # old shape, new day
        (self.system / 'runs/2026-10-24/loose-notes').mkdir(parents=True)  # not <task>-<seat>-<what>
        run = runs.new_run('T1', 'worker', 'job', self.system, datetime(2026, 10, 24).astimezone())
        (run / 'notes.txt').write_text('x')                               # extra file at the run top
        (self.portfolio / 'shop/history/runs/2026-10-24-T9-new').mkdir()   # outside the home
        (self.service / 'runs').mkdir()
        (self.service / 'runs/2026-10-25-late').mkdir()
        what = sorted((Path(row['path']).name, row['what'].split(':')[0]) for row in self.errors())
        self.assertEqual(what, [('2026-10-24-T9-new', 'Run written outside ~/.foxrun/runs/.'),
                                ('2026-10-24-worker-abc', 'Run written off-shape at the top of runs/.'),
                                ('2026-10-25-late', 'Run written outside ~/.foxrun/runs/.'),
                                ('T1-worker-job', 'Run is off-shape'),
                                ('loose-notes', 'Entry in a day folder is not a run')])

    def test_older_runs_wait_as_one_warning_per_place(self):
        (self.system / 'runs/2026-10-14-worker-abc').mkdir()
        (self.system / 'runs/20261020T031607240643Z-nightly').mkdir()
        for name in ('2026-10-01-a', '2026-10-02-b.md'):
            (self.portfolio / 'shop/history/runs' / name).mkdir() if '.' not in name else \
                (self.portfolio / 'shop/history/runs' / name).write_text('x')
        rows = self.check()
        self.assertEqual([row['level'] for row in rows], ['warning', 'warning'])
        self.assertIn('2 older entries at the top of runs/', rows[0]['what'])
        self.assertIn('2 older runs here', rows[1]['what'])

    def test_a_pointer_left_by_the_move_is_not_a_run(self):
        target = self.system / 'runs/2026-10-01/legacy/shop/2026-10-01-a'
        target.mkdir(parents=True)
        link = self.portfolio / 'shop/history/runs/2026-10-01-a'
        link.symlink_to(os.path.relpath(target, link.parent))
        old = self.system / 'runs/2026-10-02-cited'
        (self.system / 'runs/2026-10-02/legacy/system/2026-10-02-cited').mkdir(parents=True)
        old.symlink_to('2026-10-02/legacy/system/2026-10-02-cited')
        (self.system / 'runs/moves.tsv').write_text('old\tnew\n%s\t%s\n%s\t%s\n' % (
            link, target, old, self.system / 'runs/2026-10-02/legacy/system/2026-10-02-cited'))
        self.assertEqual(self.check(), [])
        self.assertEqual(runs.where(str(link) + '/result.md', self.system), str(target) + '/result.md')
        self.assertIsNone(runs.where(self.portfolio / 'shop/other', self.system))
        (self.system / 'runs/stray').symlink_to('2026-10-01')
        self.assertEqual([Path(row['path']).name for row in self.errors()], ['stray'])

    def test_a_pointer_to_a_moved_link_is_still_a_pointer(self):
        # Found in the T755 rehearsal: the service runs were links to the backup drive; their pointers chain on.
        moved = self.system / 'runs/2026-09-06/legacy/local-state/2026-09-06-030-adapter-fixture'
        moved.parent.mkdir(parents=True)
        moved.symlink_to('/nonexistent-example-drive/foxrun-runs/2026-09-06-030-adapter-fixture')  # Synthetic outside path.
        (self.service / 'runs').mkdir()
        pointer = self.service / 'runs/2026-09-06-030-adapter-fixture'
        pointer.symlink_to(os.path.relpath(moved, pointer.parent))
        self.assertEqual(self.check(), [])

    def test_the_budget_warns_at_200_mb_and_heavy_needs_a_reason_above_1_gb(self):
        run = runs.new_run('T1', 'worker', 'big', self.system, datetime(2026, 10, 24).astimezone())
        (run / 'result.md').write_text('done\n')
        (run / 'heavy/copy.bin').write_bytes(b'x' * 3000)
        with patch.object(runs, 'RUN_WARN_BYTES', 1000), patch.object(runs, 'HEAVY_LIMIT_BYTES', 2000):
            rows = self.check()
            self.assertEqual([(row['level'], Path(row['path']).name) for row in rows],
                             [('warning', 'T1-worker-big'), ('error', 'heavy')])
            with open(run / 'brief.md', 'a') as stream:
                stream.write('Heavy reason: a whole-repo practice copy for the T1 drill.\n')
            self.assertEqual([row['level'] for row in self.check()], ['warning'])

    def test_nightly_folder_holds_only_nightly_receipts(self):
        nightly = self.system / 'runs/nightly'
        for name in ('20261024T074833006549Z-nightly', '20261024T063006566403Z-lint',
                     '20261024T215311745939Z-nightly-watchdog', '2026-10-24-dream', '2026-10-24-dream-2'):
            (nightly / name).mkdir(parents=True)
        self.assertEqual(self.check(), [])
        (nightly / 'random').mkdir()
        self.assertEqual([Path(row['path']).name for row in self.errors()], ['random'])
        (self.system / 'runs/20261019T000000000000Z-nightly').mkdir()
        names = sorted(p.name for p in runs.nightly_folders(self.system))
        self.assertEqual(names, ['20261019T000000000000Z-nightly', '20261024T074833006549Z-nightly'])

    def test_disk_uses_portable_free_space_with_and_without_runs_folder(self):
        run_root = self.system / 'runs'
        for exists in (True, False):
            if not exists:
                run_root.rmdir()
            with patch.object(runs.shutil, 'disk_usage', return_value=SimpleNamespace(free=123456789)) as usage, \
                    patch.object(runs.os, 'statvfs', side_effect=AttributeError('unavailable'), create=True):
                self.assertEqual(runs.disk(self.system), {'total_bytes': 0, 'free_bytes': 123456789, 'big': []})
            usage.assert_called_once_with(run_root if exists else self.system)

    def test_doctor_warns_on_size_and_free_disk(self):
        run = runs.new_run('T1', 'worker', 'big', self.system, datetime(2026, 10, 24).astimezone())
        (run / 'heavy/data.bin').write_bytes(b'x' * 5000)
        self.assertEqual(runs.warnings(self.system), [])
        with patch.object(runs, 'TOTAL_WARN_BYTES', 100), patch.object(runs, 'RUN_WARN_BYTES', 1000), \
                patch.object(runs, 'FREE_WARN_BYTES', 1 << 62):
            lines = runs.warnings(self.system)
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[0].startswith('runs total'))
        self.assertIn('1 runs above 200 MB', lines[1])
        self.assertTrue(lines[2].startswith('free disk'))

    def test_the_cli_prints_the_move_map_answer(self):
        (self.system / 'runs/moves.tsv').write_text('old\tnew\n/a/b\t/c/d\n')
        with patch('sys.stdout') as out:
            self.assertEqual(runs.main(['where', '/a/b/x.md']), 0)
        self.assertIn('/c/d/x.md', ''.join(call.args[0] for call in out.write.call_args_list))
        self.assertEqual(json.loads(json.dumps(runs.moves(self.system))), [['/a/b', '/c/d']])


if __name__ == '__main__':
    unittest.main()
