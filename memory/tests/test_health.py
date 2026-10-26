#!/usr/bin/env python3
"""T742: health watches the standing seats and the person's leads.

Run from the system home: python3 -m unittest memory.tests.test_health
"""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # system home, so discover from memory/ finds the memory package
from memory import health, state


class LeadRoster(unittest.TestCase):
    def test_roster_is_the_standing_seats_then_the_person_leads(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder).resolve()
            (home / 'config').mkdir()
            (home / 'config/person.json').write_text(json.dumps({'name': 'pat', 'leads': ['lead-shop', 'architect']}))
            (home / 'config/standing-seats.json').write_text(json.dumps(
                {'format': 1, 'seats': {'chief-of-staff': 'system:agents/chief-of-staff.md',
                                        'architect': 'system:agents/architect.md'}}))
            beats = home / 'runs/lead-beats'
            beats.mkdir(parents=True)
            (beats / 'architect.json').write_text(json.dumps({'seat': 'architect', 'at': state.stamp(state.now())}))
            with patch.dict(os.environ, {'FOXRUN_HOME': str(home)}), redirect_stdout(io.StringIO()):
                self.assertEqual(health.roster(home), ('chief-of-staff', 'architect', 'lead-shop'))
                health.check_health()
            leads = json.loads((home / 'health.json').read_text())['leads']
            self.assertEqual(sorted(leads), ['architect', 'chief-of-staff', 'lead-shop'])
            self.assertFalse(leads['architect']['stale'])
            self.assertTrue(leads['lead-shop']['stale'])


if __name__ == '__main__':
    unittest.main()
