"""Raw integrity regression tests. Fixtures contain no real data."""
import hashlib
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('raw_source_digest',
    Path(__file__).resolve().parents[1] / 'source_digest.py')
digest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(digest)


class RawIntegrity(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_formerly_excluded_folders_catch_same_size_same_time_changes(self):
        for folder in ('build', 'dist', '.cache', 'node_modules', '.git', '__pycache__'):
            with self.subTest(folder=folder):
                p = self.root / folder / 'captured.txt'
                p.parent.mkdir()
                p.write_bytes(b'one')
                old = p.stat()
                first = digest.digest_tree(self.root)
                self.assertEqual(digest.check_source(self.root, first), 'ok')
                p.write_bytes(b'two')
                os.utime(p, ns=(old.st_atime_ns, old.st_mtime_ns))
                self.assertEqual(digest.check_source(self.root, first), 'changed')

    def test_add_remove_rename_and_empty_directory(self):
        first = digest.digest_tree(self.root)
        p = self.root / 'a'
        p.write_text('one')
        second = digest.digest_tree(self.root)
        self.assertNotEqual(first, second)
        p.rename(self.root / 'b')
        self.assertNotEqual(second, digest.digest_tree(self.root))
        (self.root / 'b').unlink()
        self.assertEqual(first, digest.digest_tree(self.root))
        (self.root / 'empty').mkdir()
        self.assertNotEqual(first, digest.digest_tree(self.root))

    def test_all_file_bytes_and_path_framing(self):
        p = self.root / 'big'
        data = b'a' * (1024 * 1024 + 100)
        p.write_bytes(data)
        self.assertEqual(digest.source_digest(p), hashlib.sha256(data).hexdigest())
        old = digest.digest_tree(self.root)
        p.write_bytes(data[:-1] + b'b')
        self.assertNotEqual(old, digest.digest_tree(self.root))
        p.rename(self.root / 'a\nF:b')
        self.assertNotEqual(old, digest.digest_tree(self.root))

    def test_links_contribute_text_without_target_reads(self):
        outside = self.root.parent / (self.root.name + '-outside')
        outside.mkdir()
        try:
            target = outside / 'target'
            target.write_text('outside one')
            link = self.root / 'link'
            link.symlink_to(outside, target_is_directory=True)
            first = digest.digest_tree(self.root)
            target.write_text('outside two')
            self.assertEqual(first, digest.digest_tree(self.root))
            link.unlink()
            link.symlink_to(outside / 'missing')
            self.assertNotEqual(first, digest.digest_tree(self.root))
            self.assertEqual(digest.check_source(link, digest.source_digest(link)), 'ok')
        finally:
            target.unlink()
            outside.rmdir()

    def test_nested_internal_links_are_not_traversed(self):
        (self.root / 'cycle').symlink_to(self.root, target_is_directory=True)
        (self.root / 'broken').symlink_to('not-here')
        first = digest.digest_tree(self.root)
        self.assertEqual(first, digest.digest_tree(self.root))
        (self.root / 'broken').unlink()
        self.assertNotEqual(first, digest.digest_tree(self.root))

    def test_deterministic_tree_independent_of_creation_order(self):
        other = self.root / 'other'
        one = self.root / 'one'
        other.mkdir()
        one.mkdir()
        for base, names in ((one, ['z', 'a']), (other, ['a', 'z'])):
            for name in names:
                (base / name).write_text(name)
        self.assertEqual(digest.digest_tree(one), digest.digest_tree(other))

    def test_secret_names_and_special_files_fail_closed(self):
        # Empty protected fixtures; they contain no secret.
        p = self.root / '.env'
        p.touch()
        with patch.object(digest, '_file', side_effect=AssertionError('must not open')):
            with self.assertRaises(digest.UnsafeSource):
                digest.digest_tree(self.root)
        p.unlink()
        os.mkfifo(self.root / 'pipe')
        with self.assertRaises(digest.UnsafeSource):
            digest.digest_tree(self.root)

    def test_unreadable_entry_is_an_error_not_a_passing_digest(self):
        (self.root / 'file').write_text('one')
        with patch.object(digest, '_file', side_effect=PermissionError('fixture')):
            with self.assertRaises(PermissionError):
                digest.digest_tree(self.root)

    def test_concurrent_change_is_an_error(self):
        p = self.root / 'file'
        p.write_text('one')
        original = digest._file
        def change(path, before, parent_fd=None):
            result = original(path, before, parent_fd)
            path.write_text('two')
            return result
        with patch.object(digest, '_file', side_effect=change):
            with self.assertRaises(digest.UnsafeSource):
                digest.digest_tree(self.root)

    def test_missing_root_and_invalid_expected_hash(self):
        self.assertEqual(digest.check_source(self.root / 'missing', 'a' * 64), 'missing')
        with self.assertRaises(ValueError):
            digest.check_source(self.root, 'bad')

    def test_symlinked_ancestor_is_refused(self):
        (self.root / 'folder').mkdir()
        (self.root / 'folder/file').write_text('one')
        (self.root / 'alias').symlink_to(self.root / 'folder', target_is_directory=True)
        with self.assertRaises(digest.UnsafeSource):
            digest.source_digest(self.root / 'alias/file')


if __name__ == '__main__':
    unittest.main()
