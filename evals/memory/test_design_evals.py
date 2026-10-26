"""Independent failure tests for the scored acceptance scripts, not substitutes for them."""
import hashlib,json,os,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import memory_eval_cases as cases
from memory_eval_business import answer,build_cases,question_rows,score_cases
class EvalFailureTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve()
 def test_dated_paid_snapshot_does_not_confirm_payment(self):
  database,rows=build_cases(self.root);result=answer(database,'sample-shop-lead:4')
  self.assertEqual('unconfirmed',result['status']);self.assertFalse(result['current'])
 def test_default_questions_need_no_business_file(self):
  with patch.dict(os.environ,{'FOXRUN_EVAL_QUESTIONS':'','FOXRUN_EVAL_WORKSPACE':'sample-shop'}):
   with patch.object(Path,'read_text',side_effect=AssertionError('Business file opened')):
    rows=question_rows()
   self.assertEqual(14,len(rows));self.assertTrue(all(r['source_route']=='synthetic fixture' for r in rows))
   self.assertFalse(score_cases()['failures'])
 def test_explicit_workspace_question_file_is_used(self):
  with patch.dict(os.environ,{'FOXRUN_EVAL_QUESTIONS':''}):rows=question_rows()
  for row in rows:row['id']=row['id'].replace('sample-shop','fake-business')
  path=self.root/'questions.json';path.write_text(json.dumps(rows))
  with patch.dict(os.environ,{'FOXRUN_EVAL_QUESTIONS':str(path),'FOXRUN_EVAL_WORKSPACE':'fake-business'}):
   database,_=build_cases(self.root)
   self.assertEqual('unconfirmed',answer(database,'fake-business-lead:4','fake-business')['status'])
   self.assertEqual('unknown',answer(database,'fake-business-lead:4','sample-shop')['status'])
 def test_missing_explicit_question_file_fails(self):
  with patch.dict(os.environ,{'FOXRUN_EVAL_QUESTIONS':str(self.root/'missing.json')}):
   with self.assertRaises(FileNotFoundError):question_rows()
 def test_wrong_workspace_never_returns_sample_shop_question(self):
  database,rows=build_cases(self.root);self.assertEqual('unknown',answer(database,'sample-shop-lead:4','other')['status'])
 def test_empty_view_gap_does_not_mean_zero_waiting(self):
  database,rows=build_cases(self.root);result=answer(database,'sample-shop-lead:3');self.assertEqual('unknown',result['status']);self.assertFalse(result['current'])
 def test_missing_cost_fails_field_evidence(self):
  original=json.loads((cases.ROOT/'field-evidence.json').read_text());original[0]['cost']=''
  (self.root/'field-evidence.json').write_text(json.dumps(original))
  score=cases.Score(8)
  with patch.object(cases,'ROOT',self.root):cases.field_cases(score)
  result=score.result();self.assertEqual(5,result['numerator']);self.assertEqual(6,result['denominator']);self.assertFalse(result['passed'])
 def test_accounted_move_without_readback_fails(self):
  row={'source_id':'one','destinations':['system:raw/one'],'disposition':'copy','ruled':True,'reason':'approved final home','payload_sha256':'abc','verified_sha256':None,'links_verified':False}
  (self.root/'move-input.jsonl').write_text(json.dumps(row)+'\n');score=cases.Score(12)
  with patch.object(cases,'ROOT',self.root),patch.dict(os.environ,{'FOXRUN_EVAL_MOVE_MANIFEST':''}):cases.move_cases(score)
  self.assertFalse(score.cases[0]['passed']);self.assertIn('readback',score.cases[0]['reason'])
 def test_fixture_week_never_satisfies_live_week(self):
  for i in range(1,8):
   folder=self.root/('2026-10-%02d-dream'%i);folder.mkdir();(folder/'manifest.json').write_text(json.dumps({'mode':'fixture','date':'2026-10-%02d'%i,'result':'pass','finished_at':'2026-10-%02dT04:00:00Z'%i}))
  with patch.dict(os.environ,{'FOXRUN_EVAL_LIVE_WEEK':str(self.root)}):self.assertFalse(cases.live_week()['passed'])
 def test_synthetic_alert_never_proves_delivery(self):
  path=self.root/'alert.json';path.write_text(json.dumps({'mode':'fixture','delivered':True,'while_scheduler_dead':True,'channel':'macOS','checked_at':'2026-10-14T12:00:00-04:00'}))
  with patch.dict(os.environ,{'FOXRUN_EVAL_LOCAL_ALERT_RECEIPT':str(path)}):self.assertFalse(cases.local_alert()['passed'])
 def test_every_numbered_eval_is_a_real_script(self):
  from run import EVALS,names
  self.assertEqual(11,len(EVALS));self.assertEqual(len(EVALS),len(set(EVALS)))
  for name in EVALS:self.assertTrue((cases.ROOT/name).is_file())
  self.assertEqual(names(),EVALS)

 def move_score(self,row):
  (self.root/'move-input.jsonl').write_text(json.dumps(row)+'\n');score=cases.Score(12)
  with patch.object(cases,'ROOT',self.root),patch.dict(os.environ,{'FOXRUN_EVAL_MOVE_MANIFEST':''}):cases.move_cases(score)
  return score.cases[0]
 def test_unresolved_move_with_matching_metadata_fails(self):
  row={'source_id':'one','destinations':['system:raw/one'],'disposition':'unresolved','ruled':False,'reason':'','payload_sha256':'abc','verified_sha256':'abc','links_verified':True}
  result=self.move_score(row);self.assertFalse(result['passed']);self.assertIn('unresolved',result['reason'])
 def test_unruled_and_unknown_moves_fail(self):
  row={'source_id':'one','destinations':['system:raw/one'],'disposition':'copy','ruled':True,'reason':'approved final home','payload_sha256':'abc','verified_sha256':'abc','links_verified':True}
  for changes in ({'ruled':False},{'reason':''},{'disposition':'unknown'}):
   with self.subTest(changes=changes):self.assertFalse(self.move_score(dict(row,**changes))['passed'])
 def test_verified_ruled_moves_still_pass(self):
  row={'source_id':'one','destinations':['system:raw/one'],'disposition':'copy','ruled':True,'reason':'approved final home','payload_sha256':'abc','verified_sha256':'abc','links_verified':True}
  for disposition in ('copy','move','rows'):
   with self.subTest(disposition=disposition):self.assertTrue(self.move_score(dict(row,disposition=disposition))['passed'])
 def test_verified_nonmove_dispositions_still_pass(self):
  for disposition in ('stay','drop','archive'):
   with self.subTest(disposition=disposition):self.assertTrue(self.move_score({'source_id':'one','disposition':disposition,'ruled':True,'reason':'approved disposition','execution_verified':True})['passed'])
 def test_broken_fault_handling_fails_direct_and_week_scores(self):
  # Replace real handlers with broken handlers. The evaluator must reject their success.
  from memory import kept,state,model_proposals
  from base import backup
  from datetime import datetime,timezone
  probes=(('bad input',kept,'freeze',None,'unexpectedly accepted'),
          ('disk pressure',state,'write_once',None,'not observed'),
          ('bad backup',backup,'export_state',None,'not refused'),
          ('model failure',model_proposals,'model_half',{'state':'pass'},'not observed'))
  for label,owner,name,value,reason in probes:
   with self.subTest(label=label),patch.object(owner,name,return_value=value):
    with cases.isolated() as (root,system,portfolio):
     result,detail=cases.week_fault(label,root,system,datetime.now(timezone.utc))
     self.assertEqual('fail',result);self.assertIn(reason,detail)
    score=cases.Score(11);cases.week_cases(score)
    case=next(c for c in score.cases if c['case'].endswith('recovery: '+label))
    self.assertFalse(case['passed']);self.assertIn(reason,case['reason'])

if __name__=='__main__':unittest.main()
