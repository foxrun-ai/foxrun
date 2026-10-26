"""Prove workflow precedence and runnable starter bindings without starting a model."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('workflow_homes_flow', ROOT/'work/flow.py')
FLOW = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FLOW)


def definition(purpose):
    return json.dumps(dict(version=1,flow='review',purpose=purpose,members={'writer': {'what':'Writes.'}},
        graph={'draft': {'member':'writer','done_when':{'file':'draft.md'}}}))


class WorkflowHomes(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='workflow-homes-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home, self.portfolio = self.root/'system', self.root/'portfolio'
        self.shelf = self.home/'skillwright/workflows'
        self.product = self.shelf/'.product'
        self.local = self.portfolio/'shop/workflows'
        self.product.mkdir(parents=True)
        self.local.mkdir(parents=True)
        (self.portfolio/'shop/AGENTS.md').write_text('# shop\n')
        self.env = patch.dict(os.environ, {'FOXRUN_HOME':str(self.home), 'FOXRUN_PORTFOLIO':str(self.portfolio)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_local_then_shelf_then_product_and_personal_source_never_runs_unreleased(self):
        (self.product/'review.yaml').write_text(definition('Product.'))
        entry, _, _ = FLOW.resolve('review')
        self.assertEqual(entry['level'],'product')
        (self.shelf/'review.yaml').write_text(definition('Shelf.'))
        entry, _, _ = FLOW.resolve('review')
        self.assertEqual(entry['level'],'shared')
        (self.local/'review.yaml').write_text(definition('Local.'))
        entry, _, context = FLOW.resolve('review','shop')
        self.assertEqual((entry['level'],context),('workspace','shop'))
        person = self.portfolio/'skillwright/workflows'
        person.mkdir(parents=True)
        (person/'unreleased.yaml').write_text(definition('Unreleased.').replace('review','unreleased'))
        with self.assertRaises(FLOW.FlowError): FLOW.resolve('unreleased')

    def test_invalid_lower_priority_definition_and_unreadable_local_place_fail_closed(self):
        (self.shelf/'review.yaml').write_text(definition('Shelf.'))
        (self.product/'review.yaml').write_text('{}')
        with self.assertRaises(FLOW.FlowError): FLOW.resolve('review')
        (self.product/'review.yaml').write_text(definition('Product.'))
        self.local.rmdir()
        self.local.write_text('A file cannot be a workflow folder.')
        with self.assertRaises(FLOW.FlowError): FLOW.resolve('review','shop')

    def test_two_valid_local_definitions_still_conflict_and_paths_keep_workspace(self):
        (self.local/'review.yaml').write_text(definition('Local.'))
        entry, _, context = FLOW.resolve(str(self.local/'review.yaml'))
        self.assertEqual(context,'shop')
        skill = self.portfolio/'shop/skills/review'
        skill.mkdir(parents=True)
        (skill/'flow.yaml').write_text(definition('Different local flow.'))
        with self.assertRaises(FLOW.FlowError): FLOW.resolve('review','shop')

    def test_both_product_starters_have_real_seats_skills_and_the_review_repairs_every_read(self):
        (self.home/'agents').mkdir()
        for seat in ('architect','keeper','toolsmith','skillwright'):
            shutil.copyfile(ROOT/'agents'/f'{seat}.md', self.home/'agents'/f'{seat}.md')
        for skill in ('log','runtime-session-search'):
            dest = self.home/'skillwright/skills'/skill
            dest.mkdir(parents=True)
            shutil.copyfile(ROOT/'skillwright/skills'/skill/'SKILL.md',dest/'SKILL.md')
        for name in ('research','review'):
            shutil.copyfile(ROOT/'skillwright/workflows'/f'{name}.yaml',self.shelf/f'{name}.yaml')
            entry, _, _ = FLOW.resolve(name)
            self.assertFalse(FLOW.disk_problems(entry['normal'],None))
            skills = [step['skill'] for step in entry['normal']['graph'].values() if step['skill']]
            self.assertEqual(set(skills), {'log','runtime-session-search'})
            self.assertTrue(all(FLOW.skill_built(skill,None) for skill in skills))
            self.assertTrue(all(member['seat'] for member in entry['normal']['members'].values()))
        review = FLOW.load(self.shelf/'review.yaml')
        self.assertEqual(review['loop']['repair']['max_rounds'],3)
        self.assertEqual(review['loop']['repair']['repeat'],['build','routine-read','recheck','read'])
        self.assertTrue(review['graph']['read']['verdict'])
        shutil.rmtree(self.home/'skillwright/skills/log')
        self.assertFalse(FLOW.skill_built('log',None))
        self.assertTrue(FLOW.skill_built('runtime-session-search',None))


    def test_member_tier_resolves_native_model_and_preserves_role_effort(self):
        from base.agent_catalog import model_policy, resolve_model
        (self.home/'config').mkdir()
        (self.home/'config/models.yaml').write_text(json.dumps(model_policy(ROOT)))
        for runtime, tier, effort in [('codex', 'code', 'high'), ('codex', 'cheap', 'medium'), ('claude', 'judgment', 'high')]:
            with self.subTest(runtime=runtime, tier=tier):
                member = {'model':None, 'tier':tier, 'effort':effort}
                argv = [runtime, 'exec', '-m', 'outdated'] if runtime == 'codex' else [runtime, '-p']
                result = FLOW.with_member(argv,member,self.root,self.root)
                flag = '-m' if runtime == 'codex' else '--model'
                self.assertEqual(result[result.index(flag)+1],resolve_model(tier,runtime,self.home))
                if runtime == 'codex': self.assertIn('model_reasoning_effort='+effort,result)
                else: self.assertEqual(result[result.index('--effort')+1],effort)
        raw=json.loads((ROOT/'skillwright/workflows/review.yaml').read_text())
        self.assertFalse(FLOW.problems(raw,'review'))
        raw['members']['builder']['model']='test-model'
        self.assertTrue(any('choose tier' in problem for problem in FLOW.problems(raw,'review')))


if __name__ == '__main__':
    unittest.main()
