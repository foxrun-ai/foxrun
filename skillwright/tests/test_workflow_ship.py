"""Workflow release acceptance on fake homes; no live release or model call."""
import hashlib
import csv
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / 'skillwright/tools/skill_ship.py'


def definition(name, purpose='A checked workflow.'):
    return json.dumps(dict(version=1, flow=name, kind='workflow', purpose=purpose,
        members={'writer': {'what': 'Writes the result.'}},
        graph={'draft': {'member': 'writer', 'done_when': {'file': 'draft.md'}}})) + '\n'


class WorkflowRelease(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='workflow-release-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / 'system'
        self.portfolio = self.root / 'portfolio'
        self.source = self.portfolio / 'skillwright/workflows'
        self.shelf = self.home / 'skillwright/workflows'
        self.source.mkdir(parents=True)
        self.home.mkdir()
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(('FOXRUN_', 'SKILLS_'))}
        self.env.update(FOXRUN_HOME=str(self.home), FOXRUN_PORTFOLIO=str(self.portfolio), PYTHONDONTWRITEBYTECODE='1')

    def run_ship(self, name='review', *args, expected=0):
        result = subprocess.run([sys.executable, '-B', str(TOOL), 'ship', '--workflow', name, *args],
            env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def author(self, name='review', folder=None):
        folder = folder or self.source
        folder.mkdir(parents=True, exist_ok=True)
        (folder / (name + '.yaml')).write_text(definition(name))
        (folder / (name + '.md')).write_text('# ' + name + '\n')
        return folder / (name + '.yaml')

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def test_dry_run_makes_nothing_including_no_lock_or_release_folder(self):
        self.author()
        before = self.snapshot()
        report = json.loads(self.run_ship('review', '--dry-run').stdout)
        self.assertEqual(report['action'], 'release')
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.shelf.exists())

    def test_one_release_equals_source_has_hash_rows_and_repeat_is_unchanged(self):
        self.author()
        report = json.loads(self.run_ship().stdout)
        self.assertTrue(report['source_equals_shelf'])
        for suffix in ('yaml', 'md'):
            name = 'review.' + suffix
            self.assertEqual((self.source/name).read_bytes(), (self.shelf/name).read_bytes())
            self.assertEqual(report['files'][name]['sha256'], hashlib.sha256((self.shelf/name).read_bytes()).hexdigest())
        manifest = json.loads((self.shelf/'.release-manifest.json').read_text())
        self.assertEqual(manifest['workflows']['review']['owner'], 'person')
        before = self.snapshot()
        self.assertEqual(json.loads(self.run_ship().stdout)['action'], 'unchanged')
        self.assertEqual(self.snapshot(), before)

    def test_one_command_promotes_workspace_source_and_keeps_its_name(self):
        local = self.portfolio / 'shop/workflows'
        source = self.author('amazon-audit', local)
        self.run_ship('amazon-audit', '--workspace', 'shop')
        self.assertEqual(source.read_bytes(), (self.shelf/'amazon-audit.yaml').read_bytes())
        row = json.loads((self.shelf/'.release-manifest.json').read_text())['workflows']['amazon-audit']
        self.assertEqual(row['source'], str(self.source/'amazon-audit.yaml'))
        self.assertEqual(row['promoted_from'], str(source))
        self.assertEqual((self.source/'amazon-audit.yaml').read_bytes(), source.read_bytes())
        self.assertTrue(source.is_file())

    def test_workspace_promotion_dry_run_makes_no_shared_source_or_shelf(self):
        self.author('amazon-audit', self.portfolio/'shop/workflows')
        before = self.snapshot()
        self.run_ship('amazon-audit', '--workspace', 'shop', '--dry-run')
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.source/'amazon-audit.yaml').exists())
        self.assertFalse(self.shelf.exists())

    def test_promotion_refuses_to_overwrite_a_different_shared_source(self):
        self.author('review', self.portfolio/'shop/workflows')
        self.author()
        (self.source/'review.yaml').write_text(definition('review','Keep this shared source.'))
        before = self.snapshot()
        self.assertIn('already differs', self.run_ship('review','--workspace','shop','--dry-run',expected=1).stderr)
        self.assertEqual(self.snapshot(), before)

    def name_approvals(self):
        self.author('produce-ugc-ads')
        with sqlite3.connect(str(self.home/'data.db')) as db:
            db.execute('CREATE TABLE approvals (id INTEGER, call TEXT, person_words TEXT, subject_id TEXT, subject_type TEXT)')
            db.execute('CREATE TABLE tasks (id TEXT, body TEXT, note TEXT, acceptance TEXT, context TEXT)')
            db.execute('CREATE TABLE comments (subject_type TEXT, subject_id TEXT, body TEXT)')
            db.execute('INSERT INTO tasks VALUES (?,?,?,?,?)', ('T754', '', '', '', ''))
            db.executemany('INSERT INTO approvals VALUES (?,?,?,?,?)', [
                (1,'approve','Keep the name produce-ugc-ads.','other','workflow'),
                (2,'discuss','produce-ugc-ads needs discussion.','produce-ugc-ads','workflow'),
                (3,'approve','Yes, build it.','T754','task'),
                (4,'approve','Keep this name.','produce-ugc-ads','workflow'),
                (5,'wrong','No.','T754','task')])

    def test_long_name_needs_an_approve_row_for_the_exact_workflow(self):
        self.name_approvals()
        self.assertIn('at most two words', self.run_ship('produce-ugc-ads', '--dry-run', expected=1).stderr)
        for approval in ('1','2','3','5','99'):
            self.run_ship('produce-ugc-ads','--approval',approval,'--dry-run',expected=1)
        self.run_ship('produce-ugc-ads','--approval','4','--dry-run')
        self.assertFalse(self.shelf.exists())

    def test_long_name_accepts_only_an_approve_id_cited_on_its_task(self):
        self.name_approvals()
        with sqlite3.connect(str(self.home/'data.db')) as db:
            db.execute("UPDATE tasks SET note='Approval 30; approval 5' WHERE id='T754'")
            db.execute("INSERT INTO comments VALUES ('task','other','Approval 3')")
        self.run_ship('produce-ugc-ads','--approval','3','--dry-run',expected=1)
        self.run_ship('produce-ugc-ads','--approval','5','--dry-run',expected=1)
        with sqlite3.connect(str(self.home/'data.db')) as db:
            db.execute("UPDATE tasks SET note='Approval 3: keep this workflow name.' WHERE id='T754'")
        self.run_ship('produce-ugc-ads','--approval','3','--dry-run')
        with sqlite3.connect(str(self.home/'data.db')) as db:
            db.execute("UPDATE tasks SET note='' WHERE id='T754'")
            db.execute("INSERT INTO comments VALUES ('task','T754','Approval 3: keep this workflow name.')")
        self.run_ship('produce-ugc-ads','--approval','3','--dry-run')
        self.assertFalse(self.shelf.exists())

    def test_bad_name_invalid_schema_and_shelf_as_source_are_refused(self):
        for name in ('../escape','Review','my-review','review-v2','research-and'):
            self.run_ship(name,'--dry-run',expected=1)
        source = self.author()
        source.write_text(definition('different'))
        self.run_ship(expected=1)
        self.author(folder=self.shelf)
        self.assertIn('never a workflow source', self.run_ship('review','--source',str(self.shelf/'review.yaml'),'--dry-run',expected=1).stderr)

    def test_symlink_source_or_destination_is_refused_without_changes(self):
        source = self.author()
        other = self.root/'other.yaml'
        source.rename(other)
        source.symlink_to(other)
        self.run_ship('review','--dry-run',expected=1)
        source.unlink()
        source.write_bytes(other.read_bytes())
        self.shelf.mkdir(parents=True)
        (self.shelf/'review.yaml').symlink_to(other)
        self.run_ship('review','--dry-run',expected=1)
        self.assertTrue((self.shelf/'review.yaml').is_symlink())

    def test_replacement_backs_up_exact_old_bytes_and_refuses_recorded_drift(self):
        source = self.author()
        self.run_ship()
        old = (self.shelf/'review.yaml').read_bytes()
        source.write_text(definition('review','The revised workflow.'))
        report = json.loads(self.run_ship().stdout)
        backup = self.home/'skillwright/skill-state/workflow-releases'/report['release_id']/'backup/review.yaml'
        self.assertEqual(backup.read_bytes(), old)
        self.assertEqual((self.shelf/'review.yaml').read_bytes(), source.read_bytes())
        (self.shelf/'review.yaml').write_text(definition('review','Unreleased drift.'))
        before = self.snapshot()
        self.assertIn('drift', self.run_ship('review','--dry-run',expected=1).stderr)
        self.assertEqual(self.snapshot(), before)

    def test_product_release_keeps_a_fallback_and_personal_release_preserves_it(self):
        product = self.author('research', self.root/'product/skillwright/workflows')
        (self.root/'product/product-manifest.tsv').write_text('path\tbytes\tsha256\n')
        self.run_ship('research','--source',str(product))
        fallback = self.shelf/'.product/research.yaml'
        self.assertEqual(fallback.read_bytes(), product.read_bytes())
        self.author('research')
        self.run_ship('research')
        self.assertEqual(fallback.read_bytes(), product.read_bytes())
        self.assertEqual((self.shelf/'research.yaml').read_bytes(), (self.source/'research.yaml').read_bytes())

    def test_release_updates_only_its_product_rows_and_personal_override_leaves_product_fallback(self):
        product = self.author('review', self.root/'product/skillwright/workflows')
        (self.root/'product/product-manifest.tsv').write_text('path\tbytes\tsha256\n')
        original = 'path\tbytes\tsha256\nother.txt\t4\tkept\n'
        for relative in ('product-manifest.tsv','base/product-manifest.tsv'):
            target = self.home/relative
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(original)
        report = json.loads(self.run_ship('review','--source',str(product)).stdout)
        for relative in ('product-manifest.tsv','base/product-manifest.tsv'):
            rows = list(csv.DictReader(io.StringIO((self.home/relative).read_text()),delimiter='\t'))
            indexed = {row['path']:row for row in rows}
            self.assertEqual(indexed['other.txt']['sha256'],'kept')
            for prefix in ('skillwright/workflows/','skillwright/workflows/.product/'):
                row = indexed[prefix+'review.yaml']
                self.assertEqual(row['sha256'],hashlib.sha256(product.read_bytes()).hexdigest())
            backup = self.home/'skillwright/skill-state/workflow-releases'/report['release_id']/'backup/system'/relative
            self.assertEqual(backup.read_text(),original)
        self.author()
        self.run_ship()
        for relative in ('product-manifest.tsv','base/product-manifest.tsv'):
            rows = list(csv.DictReader(io.StringIO((self.home/relative).read_text()),delimiter='\t'))
            indexed = {row['path']:row for row in rows}
            self.assertNotIn('skillwright/workflows/review.yaml',indexed)
            self.assertIn('skillwright/workflows/.product/review.yaml',indexed)
        self.assertEqual((self.shelf/'.product/review.yaml').read_bytes(),product.read_bytes())

    def test_omitting_a_previously_released_page_removes_only_a_checked_backup_copy(self):
        self.author()
        self.run_ship()
        old = (self.shelf/'review.md').read_bytes()
        (self.source/'review.md').unlink()
        report = json.loads(self.run_ship().stdout)
        self.assertFalse((self.shelf/'review.md').exists())
        backup = self.home/'skillwright/skill-state/workflow-releases'/report['release_id']/'backup/review.md'
        self.assertEqual(backup.read_bytes(), old)


if __name__ == '__main__':
    unittest.main()
