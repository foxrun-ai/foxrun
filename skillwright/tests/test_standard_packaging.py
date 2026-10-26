"""The installed source alias survives; each release owns immutable standard bytes."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import test_dayone_release as fixture


class StandardPackaging(unittest.TestCase):
    def setUp(self):
        fixture.PROOF=Path(tempfile.mkdtemp(prefix='standard-packaging-'))
        fixture.HOME=fixture.PROOF/'fake-home';fixture.REPO=fixture.HOME/'.foxrun/skillwright'
        fixture.SHELF=fixture.HOME/'.foxrun/skills';self.env,self.overrides=fixture.setup()
        self.repo=fixture.REPO;self.shelf=fixture.SHELF;self.ship=self.repo/'tools/skill_ship.py'
        self.alias=self.repo/'skills/skillify/references/skill-law.md'
        self.assertTrue(self.alias.is_symlink());self.assertEqual(os.readlink(self.alias),'../../../standards/skill-law.md')
        self.standard=self.repo/'standards/skill-law.md';self.original=self.standard.read_bytes()

    def cli(self,*args,ok=True):
        return fixture.run(sys.executable,'-B',self.ship,*args,env=self.env,ok=ok)

    def commit(self,*paths):
        for args in [('add',*paths),('commit','-q','-m','Reviewed standard packaging case'),('push','-q','origin','main')]:
            fixture.run('git','-C',self.repo,*args,env=self.env)

    def canaries(self,name):
        path=fixture.PROOF/'standard-canary.py'
        path.write_text('import os\nfrom pathlib import Path\ns=Path(os.environ["SKILLS_ACTIVE_PATH"])\np=s/"skillify/references/skill-law.md"\nassert p.is_file() and not p.is_symlink()\nassert not p.stat().st_mode & 0o222\nprint('+repr(name+': present')+')\n')
        return [item for runtime in ['claude','codex','hermes'] for item in ['--canary-command',runtime+'='+sys.executable+' -B '+str(path)]]

    def test_skillify_then_ordinary_ship_with_preserved_source_alias(self):
        page=self.repo/'skills/skillify/SKILL.md';page.write_text(page.read_text()+'\nReviewed packaging proof.\n')
        self.commit('skills/skillify/SKILL.md')
        result=self.cli('ship','--skill','skillify',*self.canaries('skillify'))
        self.assertIn('shipped skillify',result.stdout)
        self.assertTrue(self.alias.is_symlink())
        record=json.loads((self.shelf/'.release-manifest.json').read_text())
        self.assertIn('standard_snapshots',record['skills']['skillify'])
        self.assertNotIn('source_drift',record['skills']['skillify'])
        law=self.shelf/'skillify/references/skill-law.md'
        self.assertEqual(law.read_bytes(),self.original)
        page=self.repo/'skills/close/SKILL.md';page.write_text(page.read_text().replace('Run the fx-close skill.','Use the fx-close skill.'))
        self.commit('skills/close/SKILL.md')
        self.assertIn('shipped close',self.cli('ship','--skill','close',*self.canaries('close')).stdout)
        self.assertEqual((self.shelf/'skillify/references/skill-law.md').read_bytes(),self.original)
        self.assertTrue(self.alias.is_symlink())
        self.cli('validate','--candidate',self.shelf)

    def test_relocated_frozen_release_resolves_without_workshop_law(self):
        self.shelf.chmod(0o755)
        for root,dirs,files in os.walk(self.shelf):
            for name in dirs:(Path(root)/name).chmod(0o555)
        moved=self.repo/'skill-releases/relocated';moved.parent.mkdir()
        self.shelf.rename(moved);moved.chmod(0o555)
        self.shelf.symlink_to(os.path.relpath(moved,self.shelf.parent))
        self.standard.write_text('Changed live standard.\n')
        snapshot=moved/'skillify/references/skill-law.md'
        self.assertFalse(snapshot.is_symlink());self.assertEqual(snapshot.read_bytes(),self.original)
        self.assertEqual((self.shelf/'skillify/references/skill-law.md').read_bytes(),self.original)
        self.assertFalse(snapshot.stat().st_mode&0o222)
        # Independent frozen validation must not consult the changed live standard.
        result=fixture.run(sys.executable,'-B','-c',
            'from pathlib import Path; import skill_ship; from skill_scoped import validate_record; validate_record(skill_ship,Path('+repr(str(moved))+'))',
            cwd=self.repo/'tools',env=self.env)
        self.assertEqual(result.returncode,0)

    def test_standard_only_merge_starts_ship_without_manual_ship(self):
        self.env.update(SKILLS_SHIP_SETTLE_SECONDS='0')
        self.canaries('skillify')
        self.env['SKILLS_CANARY_COMMAND']=sys.executable+' -B '+str(fixture.PROOF/'standard-canary.py')
        self.cli('install-trigger')
        author=fixture.PROOF/'standard-author'
        def git(*args,cwd=None):
            return fixture.run('git',*args,cwd=cwd,env=self.env)
        git('clone','--branch','main',str(fixture.PROOF/'origin.git'),str(author))
        for key,value in [('user.name','Reviewed standard author'),('user.email','standard@local')]:git('-C',author,'config',key,value)
        git('-C',author,'switch','-c','reviewed-standard-only')
        law=author/'standards/skill-law.md'
        expected=law.read_bytes()+b'\nReviewed standard-only merge.\n';law.write_bytes(expected)
        git('-C',author,'add','standards/skill-law.md')
        git('-C',author,'commit','-q','-m','Reviewed standard-only update')
        git('-C',author,'switch','main')
        git('-C',author,'merge','--no-ff','reviewed-standard-only','-m','Merge reviewed standard-only update')
        git('-C',author,'push','origin','main')
        before=json.loads((self.shelf/'.release-manifest.json').read_text())['release_id']
        source_before=(self.repo/'skills/skillify/SKILL.md').read_bytes()
        start=len(fixture.COMMANDS)
        git('pull','--ff-only',cwd=self.repo)
        changed=git('-C',self.repo,'diff','--name-only','ORIG_HEAD','HEAD').stdout.splitlines()
        self.assertEqual(changed,['standards/skill-law.md'])
        deadline=__import__('time').monotonic()+50;receipt=None
        while __import__('time').monotonic()<deadline:
            for path in (self.repo/'skill-state/ships').glob('*.json'):
                try:value=json.loads(path.read_text())
                except ValueError:continue
                if value.get('skill')=='skillify' and value.get('result') in {'shipped','failed'}:receipt=value
            if receipt:break
            __import__('time').sleep(0.1)
        log=self.repo/'skill-state/ships/trigger.log'
        self.assertIsNotNone(receipt,log.read_text() if log.exists() else 'No trigger log')
        self.assertEqual(receipt['result'],'shipped',log.read_text())
        after=json.loads((self.shelf/'.release-manifest.json').read_text())['release_id']
        self.assertNotEqual(before,after)
        snapshot=self.shelf/'skillify/references/skill-law.md'
        self.assertFalse(snapshot.is_symlink());self.assertFalse(snapshot.stat().st_mode&0o222)
        self.assertEqual(snapshot.read_bytes(),expected)
        self.assertEqual((self.repo/'skills/skillify/SKILL.md').read_bytes(),source_before)
        self.assertEqual(os.readlink(self.alias),'../../../standards/skill-law.md')
        commands=fixture.COMMANDS[start:]
        self.assertFalse(any('ship' in command for command in commands),commands)
        self.cli('validate','--candidate',self.shelf)
        (fixture.PROOF/'standard-only-merge-proof.json').write_text(json.dumps(dict(result='pass',
            changed_paths=changed,manual_ship_commands=0,source_alias_preserved=True,frozen_standard_updated=True,
            validated=True,before=before,after=after,receipt=receipt),indent=2)+'\n')

    def test_ship_refuses_a_blank_skill(self):
        # T738: the system-wide release lint left skill_ship.py; the skill's own check still refuses.
        before=(self.shelf/'.release-manifest.json').read_bytes()
        (self.repo/'skills/close/SKILL.md').write_text('')
        result=self.cli('ship','--skill','close','--dry-run',ok=False)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('missing YAML frontmatter',result.stdout+result.stderr)
        self.assertEqual((self.shelf/'.release-manifest.json').read_bytes(),before)

    def test_standard_only_change_is_not_a_noop(self):
        self.standard.write_bytes(self.original+b'\nReviewed standard change.\n');self.commit('standards/skill-law.md')
        stale=self.cli('validate','--candidate',self.shelf,ok=False)
        self.assertNotEqual(stale.returncode,0);self.assertIn('standard snapshot is stale',stale.stderr)
        result=self.cli('ship','--skill','skillify',*self.canaries('skillify'))
        self.assertIn('shipped skillify',result.stdout)
        self.assertEqual((self.shelf/'skillify/references/skill-law.md').read_bytes(),self.standard.read_bytes())

    def test_uncommitted_standard_stops_before_shipping(self):
        self.standard.write_bytes(self.original+b'\nUncommitted change.\n')
        before=(self.shelf/'.release-manifest.json').read_bytes()
        result=self.cli('ship','--skill','skillify','--dry-run',ok=False)
        self.assertNotEqual(result.returncode,0);self.assertIn('Commit the approved standard',result.stderr)
        self.assertEqual((self.shelf/'.release-manifest.json').read_bytes(),before)

    def test_other_source_link_is_rejected(self):
        self.alias.unlink();self.alias.symlink_to('../../../standards/unapproved.md')
        (self.repo/'standards/unapproved.md').write_text('Unapproved.\n')
        result=self.cli('ship','--skill','skillify','--dry-run',ok=False)
        self.assertNotEqual(result.returncode,0);self.assertIn('Unreviewed payload link',result.stderr)

    def test_source_root_link_is_rejected(self):
        source=self.repo/'skills/skillify';stored=self.repo/'held-skillify'
        source.rename(stored);source.symlink_to('../held-skillify')
        result=self.cli('ship','--skill','skillify','--dry-run',ok=False)
        self.assertNotEqual(result.returncode,0)
        self.assertTrue('Unreviewed payload link' in result.stderr or 'no single publication approval' in result.stderr,result.stderr)

    def test_payload_link_is_rejected_for_an_ordinary_ship(self):
        target=self.shelf/'skillify/references/skill-law.md'
        target.parent.chmod(0o755);target.unlink();target.symlink_to(self.standard)
        page=self.repo/'skills/close/SKILL.md';page.write_text(page.read_text().replace('Run the fx-close skill.','Use the fx-close skill.'))
        self.commit('skills/close/SKILL.md')
        result=self.cli('ship','--skill','close',*self.canaries('close'),ok=False)
        self.assertNotEqual(result.returncode,0);self.assertIn('Unreviewed payload link',result.stderr)


if __name__=='__main__':unittest.main()

