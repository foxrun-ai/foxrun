"""Approved canonical versions bind triggers and ships to exact reviewed bytes."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import test_dayone_release as fixture


class CatalogVersion(unittest.TestCase):
    def setUp(self):
        fixture.PROOF=Path(tempfile.mkdtemp(prefix='catalog-version-')).resolve()
        fixture.HOME=fixture.PROOF/'fake-home';fixture.REPO=fixture.HOME/'.foxrun/skillwright'
        fixture.SHELF=fixture.HOME/'.foxrun/skills'
        self.env,self.overrides=fixture.setup()
        self.repo=fixture.REPO;self.catalog=self.repo/'config/catalog.yaml'
        self.ship=self.repo/'tools/skill_ship.py';self.owner=self.repo.parent/'base/catalog.py'
        self.assertEqual(os.readlink(self.catalog),'../../config/catalog.yaml')
        self.before=[p.read_bytes() for p in self.metadata()]

    def metadata(self):
        return [fixture.SHELF/'.release-manifest.json',self.repo/'manifests/shipped.yaml',
                Path(self.env['SKILLS_PIN_PATH']),self.repo/'skill-state/release-state.json']

    def run_cli(self,tool,*args,env=None):
        return fixture.run(sys.executable,'-B',tool,*args,env=env or self.env,ok=False)

    def test_unapproved_canonical_change_cannot_ship(self):
        raw=json.loads(self.catalog.read_text());raw['where']['close']='off'
        self.catalog.write_text(json.dumps(raw))
        result=self.run_cli(self.ship,'ship','--skill','close',*self.overrides)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('differs from its approved snapshot',result.stderr)
        self.assertEqual([p.read_bytes() for p in self.metadata()],self.before)
        self.assertFalse(fixture.SHELF.is_symlink())

    def test_stale_notification_cannot_ship(self):
        result=self.run_cli(self.ship,'ship','--skill','close',*self.overrides,
                            env=dict(self.env,SKILLS_CATALOG_DIGEST='0'*64))
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Catalog version changed',result.stderr)
        self.assertEqual([p.read_bytes() for p in self.metadata()],self.before)

    def test_stale_owner_review_cannot_write(self):
        before=self.catalog.read_bytes();approval=(self.repo/'skill-state/catalog-approved.json').read_bytes()
        payload=fixture.PROOF/'reviewed.json';payload.write_text('{"version":1,"where":{"close":"off"}}')
        result=self.run_cli(self.owner,'apply','--input',payload,'--expected-sha256','0'*64,'--by','Reviewer')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('rebase the proposal',result.stderr)
        self.assertEqual(self.catalog.read_bytes(),before)
        self.assertEqual((self.repo/'skill-state/catalog-approved.json').read_bytes(),approval)

    def test_catalog_drift_during_canary_restores_shelf_and_records(self):
        page=self.repo/'skills/close/SKILL.md'
        page.write_text(page.read_text().replace('Run the fx-close skill.','Use the fx-close skill.'))
        for args in [('add','skills/close'),('commit','-q','-m','Reviewed source'),('push','-q','origin','main')]:
            fixture.run('git','-C',self.repo,*args,env=self.env)
        canary=fixture.PROOF/'drift-canary.py'
        canary.write_text('import os\nfrom pathlib import Path\np=Path(os.environ["SKILLS_DOJO_ROOT"])/"config/catalog.yaml"\nwith p.open("ab") as f:f.write(b" ")\nprint("close: present")\n')
        overrides=[]
        for runtime in ['claude','codex','hermes']:
            overrides+=['--canary-command',runtime+'='+sys.executable+' -B '+str(canary)]
        result=self.run_cli(self.ship,'ship','--skill','close',*overrides)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('differs from its approved snapshot',result.stderr)
        self.assertEqual([p.read_bytes() for p in self.metadata()],self.before)
        self.assertFalse(fixture.SHELF.is_symlink())

    def test_missing_prior_snapshot_cannot_notify(self):
        approval=self.repo/'skill-state/catalog-approved.json';record=json.loads(approval.read_text())
        record['previous']='0'*64;approval.write_text(json.dumps(record))
        result=self.run_cli(self.owner,'notify','--expected-sha256',record['digest'])
        self.assertNotEqual(result.returncode,0)
        self.assertEqual([p.read_bytes() for p in self.metadata()],self.before)


if __name__=='__main__':unittest.main()
