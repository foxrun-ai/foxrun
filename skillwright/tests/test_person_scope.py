"""A skill that only the person's repo holds keeps its global scope; the ship never retires it (T742)."""
import unittest
import test_person_source as person
import test_dayone_release as fixture


class PersonOnlyScope(unittest.TestCase):
    setUp = person.PersonSource.setUp
    git = person.PersonSource.git
    commit = person.PersonSource.commit
    cli = person.PersonSource.cli
    record = person.PersonSource.record

    def test_person_only_skill_ships_and_is_not_retired(self):
        self.commit('Person copy of close')
        self.assertIn('shipped close', self.cli('ship', '--skill', 'close', *self.overrides).stdout)
        # The product repo drops its copy, the way T675 moved the person's skills out.
        fixture.run('git', '-C', self.repo, 'rm', '-q', '-r', 'skills/close')
        fixture.run('git', '-C', self.repo, 'commit', '-q', '-m', 'Product copy of close leaves')
        fixture.run('git', '-C', self.repo, 'push', '-q', 'origin', 'main')
        self.page.write_text(self.page.read_text() + '\nOne more line.\n')
        self.commit('Person edits close')
        shipped = self.cli('ship', '--skill', 'close', *self.overrides)
        self.assertNotIn('scope off', shipped.stdout)
        self.assertIn('shipped close', shipped.stdout)
        self.assertEqual(self.page.read_bytes(), (self.shelf / 'close/SKILL.md').read_bytes())
        self.assertEqual(self.record()['skills']['close']['owner'], 'person')


if __name__ == '__main__':
    unittest.main()
