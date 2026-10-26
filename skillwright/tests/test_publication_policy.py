"""The catalog narrows global sources; full publication keeps its explicit X5 hold."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from skill_catalog import read_catalog,load_policy,canary_checklist

class CatalogContract(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.repo=Path(self.temp.name)
        for name,status in [('alpha','active'),('beta','active'),('draft','draft')]:
            p=self.repo/'skills'/name/'SKILL.md';p.parent.mkdir(parents=True);p.write_text('---\nname: '+name+'\nstatus: '+status+'\n---\n')
        self.path=self.repo/'config/catalog.yaml';self.path.parent.mkdir()
        self.raw=dict(version=1,where={},claude_preserve_physical=[],claude_approval_required={},host_specific={})
    def tearDown(self):self.temp.cleanup()
    def save(self):self.path.write_text(json.dumps(self.raw))
    def load(self):self.save();return load_policy(self.path,self.repo)[0]
    def test_absence_is_global_and_draft_stays_in_workshop(self):
        p=self.load();self.assertEqual(p['publish'],['alpha','beta']);self.assertIn('draft',p['exclude'])
    def test_off_and_workspace_scopes_narrow_global_sources(self):
        self.raw['where']={'alpha':'off','beta':['one','two']};p=self.load()
        self.assertEqual(p['publish'],[]);self.assertEqual(p['workspace_publish'],{'beta':['one','two']})
        self.assertEqual(set(p['exclude']),{'alpha','beta','draft'})
    def test_stale_publish_list_cannot_override_where(self):
        self.raw.update(publish=['alpha'],where={'alpha':'off'});p=self.load()
        self.assertNotIn('alpha',p['publish']);self.assertIn('beta',p['publish'])
    def test_invalid_scope_stops(self):
        self.raw['where']={'alpha':'global'}
        with self.assertRaisesRegex(RuntimeError,'where must be off'):self.load()
    def test_full_publication_keeps_the_real_x5_hold(self):
        self.raw['host_specific']={'gstack':{'dayone_hold':'X5 must prove the vendor route.'}}
        self.save()
        raw=json.loads(self.path.read_text())
        self.assertTrue(any(e.get('dayone_hold') for e in raw['host_specific'].values()))
        with self.assertRaisesRegex(RuntimeError,'X5'):load_policy(self.path,self.repo)
        self.assertNotIn('publish',raw)
    def test_app_owned_folder_never_collides_with_shelf_sources(self):
        self.raw['claude_app_owned']={'alpha':{'reason':'app'}}
        with self.assertRaisesRegex(RuntimeError,'collide with shelf names'):self.load()
        self.raw['claude_app_owned']={'synced/account':{'reason':'app'}}
        with self.assertRaisesRegex(RuntimeError,'one folder name'):self.load()
        self.raw['claude_app_owned']={'synced':{'reason':' '}}
        with self.assertRaisesRegex(RuntimeError,'needs a reason'):self.load()
        self.raw['claude_app_owned']={'synced':{'reason':'The app owns it.'}}
        self.assertEqual(set(self.load()['claude_app_owned']),{'synced'})
    def test_physical_preservation_only_selects_global_sources(self):
        self.raw.update(where={'alpha':'off'},claude_preserve_physical=['alpha','beta'])
        self.assertEqual(self.load()['claude_preserve_physical'],['beta'])
    def test_canaries_still_require_fresh_sessions(self):
        p=canary_checklist();self.assertTrue(p['fresh_sessions_required'])
        self.assertEqual(p['runtimes'],['hermes','codex','claude'])
        self.assertTrue({'orchestrate','herdr','runtime-session-search','tabladb'}<=set(p['required_skills']))
if __name__=='__main__':unittest.main()
