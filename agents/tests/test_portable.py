from __future__ import annotations
import sys
from pathlib import Path as _SupportPath
sys.path.insert(0, str(_SupportPath(__file__).resolve().parents[2] / "base"))
sys.path.insert(0, str(_SupportPath(__file__).resolve().parents[1]))
# agents/ goes ahead of base/ so tests.support is this folder, not base/tests (collision since 9e44892 T595)
sys.path.insert(0, str(_SupportPath(__file__).resolve().parents[1] / "tools"))

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import agent_new
import simple_yaml
import paths

ROOT=Path(__file__).resolve().parents[1]
class PortableTests(unittest.TestCase):
    def test_every_shipped_yaml_matches_stored_expected_json(self):
        expected=json.loads((ROOT/'tests/yaml-expected.json').read_text())
        found={str(p.relative_to(ROOT)) for p in ROOT.rglob('*.yaml') if 'not-shipped' not in p.parts}
        self.assertEqual(found,set(expected))
        for name,value in expected.items():
            with self.subTest(file=name):
                found_value=simple_yaml.safe_load((ROOT/name).read_text())
                if name=='execution/skills.yaml':
                    # skills.yaml is the live skills pin; each skillify release rewrites its release id (src/skillwright/tools/skill_scoped.py SKILLS_PIN_PATH)
                    self.assertRegex(str(found_value.pop('release','')),r'^\d{8}T\d{12}Z-[0-9a-f]{12}$'); value={k:v for k,v in value.items() if k!='release'}
                self.assertEqual(found_value,value)

    def test_yaml_subset_and_duplicate_rejection(self):
        source='''# one comment
items:
  - name: "quoted # text"
    flags: [true, false, null, 3, 'hello: world']
empty: {}
plain: the person\'s words
'''
        self.assertEqual(simple_yaml.safe_load(source),{'items':[{'name':'quoted # text','flags':[True,False,None,3,'hello: world']}],'empty':{},'plain':"the person's words"})
        for source in ('x: 1\nx: 2\n','{"x": 1, "x": 2}', 'x: &anchor bad'):
            with self.assertRaises(simple_yaml.YAMLError): simple_yaml.safe_load(source)

    def test_model_override_changes_both_core_capes(self):
        identity=agent_new.load_identity('architect',ROOT)
        with tempfile.TemporaryDirectory() as temp:
            system=Path(temp); (system/'config').mkdir()
            source=json.loads(simple_yaml.safe_dump(agent_new.policy(ROOT)))
            source['allowed'].append('test-person-model')
            source['tiers']['judgment']['codex']['model']='test-person-model'
            source['tiers']['judgment']['claude']['model']='test-person-model'
            (system/'config/models.yaml').write_text(json.dumps(source))
            with patch.dict(os.environ,{'FOXRUN_HOME':str(system)}):
                self.assertIn('test-person-model',agent_new.claude_cape(identity,ROOT))
                self.assertIn('test-person-model',agent_new.codex_cape(identity,ROOT))

    def test_draft_seats_have_format_marker_length_and_sources(self):
        for seat in ('adviser','scout','skillwright','toolsmith'):
            with self.subTest(seat=seat):
                identity=agent_new.load_identity(seat,ROOT)
                # docs/identity-format.md caps the body at 120 lines (6c6b391); seats grew past 60 with T285 write-state and T740 front matter
                self.assertLess(len(identity.path.read_text().splitlines()),120)
                self.assertEqual(identity.body.splitlines()[0],'Draft from rows, 10.12; the person who owns Foxrun reviews it.')
                # seats nest the section under Judgment as ### since 4a024f1 (T740); create scaffolds the same
                self.assertIn(agent_new.WRITE_STATE_SECTION.replace('## ','### '),identity.body)

    def test_reviewed_keeper_is_generic_and_owns_its_ruled_parts(self):
        # T627: the Keeper seat left draft; g-capture-owns-raw-keeper-owns-memory-knowledge-and-lint names its parts.
        identity=agent_new.load_identity('keeper',ROOT)
        text=identity.path.read_text()
        self.assertNotIn('Draft from rows',identity.body)
        self.assertLessEqual(len(identity.body.splitlines()),120)
        self.assertIn(agent_new.WRITE_STATE_SECTION.replace('## ','### '),identity.body)
        for part in ('memory','events','wiki','backups','archive','STATE.md','base/lint.py','base/page_indexes.py'):
            self.assertIn(part,identity.data['owns'])
        self.assertNotIn('raw',identity.data['owns'])
        # A synthetic forbidden-person marker and the host account name stand in for the source owner.
        for private in ('Wren Example','/Users/','foxrun-hq'):
            self.assertNotIn(private,text)
        account=re.split(r'[ ._-]+',pwd.getpwuid(os.getuid()).pw_name)[0]
        if len(account)>2:
            self.assertNotIn(account.lower(),text.lower())

    def test_tools_work_in_empty_home_without_hermes(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp).resolve(); system=base/'system'; portfolio=base/'portfolio'; state=base/'state'; home=base/'home'
            for p in (system,portfolio,state,home): p.mkdir()
            # generated/ is local runtime output (codex alias links), not shipped since 70223c8 (T630)
            shutil.copytree(ROOT,system/'agents',ignore=shutil.ignore_patterns('.git','not-shipped','__pycache__','generated','test_acceptance.py','moves.tsv','unplaced.tsv'))
            (system/'base').mkdir()
            shutil.copyfile(ROOT.parent/'base/simple_yaml.py',system/'base/simple_yaml.py')
            # agent_new expands catalog sets and checks ownership since 4a024f1 (T740); copy those base modules and config
            for name in ('agent_catalog.py','ownership.py','paths.py'): shutil.copyfile(ROOT.parent/'base'/name,system/'base'/name)
            (system/'config').mkdir()
            (system/'config/models.yaml').write_text(json.dumps(json.loads(simple_yaml.safe_dump(agent_new.policy(ROOT)))))
            names={'base'}
            for page in ROOT.glob('*.md'):
                text=page.read_text()
                if text.startswith('---\n'): names|=set((simple_yaml.safe_load(text[4:].split('\n---\n',1)[0]) or {}).get('sets') or [])
            (system/'config/catalog.yaml').write_text(json.dumps({'sets':{n:{'skills':[],'tools':[]} for n in sorted(names)}}))
            env={**os.environ,'HOME':str(home),'FOXRUN_HOME':str(system),'FOXRUN_PORTFOLIO':str(portfolio),'FOXRUN_STATE':str(state),'PATH':'/usr/bin:/bin','FOXRUN_SEAT':'chief-of-staff'}  # base/ownership.py: chief-of-staff owns agents/ (4a024f1 T740 write guard)
            self.assertIsNone(shutil.which('hermes',path=env['PATH']))
            def run(script,*args,expected=0):
                result=subprocess.run(['/usr/bin/python3',str(system/'agents/tools'/script),*args],env=env,cwd=system/'agents',capture_output=True,text=True)
                self.assertEqual(result.returncode,expected,result.stdout+result.stderr)
                return result.stdout
            run('agent_new.py','create','sample-agent','--role','Checks samples','--summary','Checks sample facts.','--tier','work','--skills','','--tools','','--shared','--client','system','--runtimes','claude,codex','--hermes-mode','none','--dry-run')
            self.assertFalse((system/'agents/sample-agent.md').exists())
            run('agent_new.py','create','sample-agent','--role','Checks samples','--summary','Checks sample facts.','--tier','work','--skills','','--tools','','--shared','--client','system','--runtimes','claude,codex','--hermes-mode','none')
            run('agent_new.py','render','sample-agent','--json')
            # system seats render under runs/generated/agents/<runtime>/ since 4a024f1 (T740)
            for runtime,suffix in [('claude','.md'),('codex','.toml')]: self.assertTrue((system/'runs/generated/agents'/runtime/('sample-agent'+suffix)).is_file())
            # Render the system seats so profile_check can inspect all core capes.
            listing=json.loads(run('agent_new.py','list','--json'))
            for row in listing['identities']: run('agent_new.py','render',row['id'],'--json')
            self.assertIn('Claude and Codex on day one.',run('profile_check.py','--include-core','--declared-runtimes-only','--json',expected=2))
            self.assertIn('Claude and Codex on day one.',run('tool_probe.py','sample-agent','--json',expected=2))
            run('render_capabilities.py','--repo',str(system/'agents'),'--vault',str(portfolio),'--workspace',str(portfolio),'--skill-shelf',str(system/'skills'),'--output',str(base/'capabilities.md'),'--installed-layout')
            # eval_run invokes the tests once; avoid recursion from this smoke case.
            shutil.copytree(system/'agents/tests',base/'saved-tests')
            shutil.rmtree(system/'agents/tests')
            (system/'agents/tests').mkdir()
            (system/'agents/tests/test_local.py').write_text('import unittest\nclass Local(unittest.TestCase):\n def test_ok(self): self.assertEqual(2+2,4)\n')
            (system/'agents/execution/skills.yaml').write_text('{"release": "example-release", "gaps": []}')
            self.assertIn('"verdict": "PASS"',run('eval_run.py','--json'))
