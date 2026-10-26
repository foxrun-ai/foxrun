"""The third audit's exact pattern list, plus all source task references."""

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = _FoxPath(__file__).resolve().parents[2]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()
import json
from pathlib import Path
import re
import subprocess
import unittest
from base.tests.test_startup_round7 import shipped as named_shipped
from base.tests.test_privacy_round6 import SHIPPED
from base.tests.support import shipped_paths
ROOT = Path(__file__).resolve().parents[2]
from base.tests.privacy_support import patterns
PATTERNS = patterns()
# The audit explicitly accepts these generic candidates and the documented CLI alias.
GENERIC = {'email', 'phone', 'uuid'}


def shipped(name):
    """Every manifest path ships and is scanned; without a manifest, fall back to the name rule."""
    return name in SHIPPED if SHIPPED is not None else named_shipped(name)


def scan():
    # T742: local people/ and modules/ stay outside the core privacy scan.
    names = [p.relative_to(ROOT).as_posix() for p in shipped_paths(ROOT) if p.is_file()]
    hits, candidates, checked = [], [], []
    for name in names:
        if not shipped(name):
            continue
        try:
            source = (ROOT / name).read_text()
        except UnicodeError:
            continue
        checked.append(name)
        for number, line in enumerate(source.splitlines(), 1):
            line = line.replace('--person-words', '')
            for kind, pattern in PATTERNS:
                for match in re.finditer(pattern, line, re.I):
                    row = (name, number, kind, match.group())
                    (candidates if kind in GENERIC else hits).append(row)
    return checked, hits, candidates


class PublicPrivacy(unittest.TestCase):
    def test_auditor_patterns_have_zero_private_hits(self):
        checked, hits, candidates = scan()
        self.assertGreaterEqual(len(checked), 307)
        self.assertEqual(hits, [])

    def test_one_made_up_shop(self):
        files = list((ROOT / 'base/tests/fixtures').glob('*.md'))
        for path in files:
            text = path.read_text()
            self.assertNotIn('Sample Shop', text)
            self.assertNotIn('luxury watches', text)
        agents = (ROOT / 'base/tests/fixtures/sample-shop-AGENTS.md').read_text()
        self.assertIn('Cedar Shop', agents)
        self.assertIn('Garden trowel', agents)
        self.assertIn('Seed tray', agents)
        fixture = json.loads((ROOT / 'base/distribution/sample/rows.json').read_text())
        self.assertEqual({row['title'] for row in fixture['tables']['commerce_products']},
                         {'Garden trowel', 'Seed tray'})


if __name__ == '__main__':
    unittest.main()
