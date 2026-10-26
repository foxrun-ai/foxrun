import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from base import ownership


class OwnershipLinkTests(unittest.TestCase):
    """T634: links inside the system home keep their owner; links out alarm."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name).resolve()
        self.home = root / 'home'
        self.outside = root / 'outside'
        (self.home / 'agents').mkdir(parents=True)
        (self.home / 'skills-real').mkdir()
        self.outside.mkdir()
        (self.home / 'agents' / 'keeper.md').write_text('---\nid: keeper\nowns: [skills-real, skills]\n---\n')
        os.symlink(self.home / 'skills-real', self.home / 'skills')
        os.symlink(self.outside, self.home / 'escape')

    def tearDown(self):
        self.tmp.cleanup()

    def test_link_inside_home_keeps_owner(self):
        ok, message = ownership.allowed(self.home, self.home / 'skills' / 'a.md', seat='keeper')
        self.assertTrue(ok, message)

    def test_link_out_of_home_is_not_allowed(self):
        with self.assertRaises(Exception):
            ok, message = ownership.allowed(self.home, self.home / 'escape' / 'a.md', seat='keeper')
            if not ok:
                raise ValueError(message)


if __name__ == '__main__':
    unittest.main()
