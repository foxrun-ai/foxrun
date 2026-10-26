"""T742: the retired-place list never names a current home."""
import csv
import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'lint.py'
spec = importlib.util.spec_from_file_location('stale_names_lint', SOURCE)
lint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lint)
POLICY = SOURCE.parents[1] / 'config/lint'


class StaleNames(unittest.TestCase):
    def test_no_row_maps_a_name_to_itself(self):
        with (POLICY / 'stale-names.tsv').open(newline='') as stream:
            rows = list(csv.DictReader(stream, delimiter='\t'))
        self.assertTrue(rows)
        for row in rows:
            self.assertNotEqual(row['literal'], row['replacement'], row['literal'])

    def test_a_contract_that_names_both_homes_passes(self):
        with tempfile.TemporaryDirectory() as folder:
            home, portfolio = Path(folder) / 'system', Path(folder) / 'portfolio'
            home.mkdir()
            portfolio.mkdir()
            policy = Path(folder) / 'policy'
            shutil.copytree(POLICY, policy)
            (home / 'AGENTS.md').write_text('# Rules\nCode is in ~/.foxrun/. Work is in ~/foxrun/.\n')
            self.assertEqual(lint.Lint(home, portfolio, policy).run('UPKEEP03'), [])


if __name__ == '__main__':
    unittest.main()
