"""Independent adversarial tests for query boundaries, missing proof, and evaluation results."""
import hashlib,json,sqlite3,tempfile,unittest
from pathlib import Path
from memory_eval_fixtures import AT,build
from memory_eval_queries import query
from run import run,record
class QueryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.db,self.pins=build(self.root)
 def ask(self,q,ws='shop',**kw):return query(self.db,q,ws,AT,**kw)
 def test_workspace_injection_and_unknown_intent(self):
  self.assertEqual([],self.ask('now',"shop' OR 1=1--")['rows']);self.assertEqual(7,len(self.ask('SELECT * FROM secrets')['choices']))
 def test_old_tracker_is_refused_without_writes(self):
  old=self.root/'old.db';sqlite3.connect(old).close();before=old.read_bytes()
  with self.assertRaises(sqlite3.OperationalError):query(old,'now','shop',AT)
  self.assertEqual(before,old.read_bytes())
 def test_missing_freshness_and_approval_stay_unknown(self):
  self.assertEqual('unknown',self.ask('now')['status']);self.assertTrue(all(r['authorized'] is None for r in self.ask('next')['rows']))
 def test_actual_read_has_no_database_write(self):
  before=hashlib.sha256(self.db.read_bytes()).hexdigest()
  for q in ('yesterday','now','blocked','root-cause','next','month','procedure'):self.ask(q,measure=1,capability='sample',procedure_root=self.root,pins=self.pins)
  self.assertEqual(before,hashlib.sha256(self.db.read_bytes()).hexdigest())
 def test_budgets_and_omitted_counts(self):
  with sqlite3.connect(self.db) as c:
   c.executemany('INSERT INTO work_tasks VALUES (?,?,?,?,?,?,?,?)',[(i,'shop','T'+str(i),'x'*4000,'todo',AT,'row:'+str(i),None) for i in range(4,70)])
  a=self.ask('now');self.assertLessEqual(len(json.dumps(a,ensure_ascii=False).encode()),12000);self.assertEqual(68,len(a['rows'])+a['omitted'])
 def test_hypothesis_and_replaced_records_are_excluded(self):
  self.assertEqual(['I1'],[r['number'] for r in self.ask('root-cause')['rows']]);self.assertNotIn('T3',[r['number'] for r in self.ask('now')['rows']])
 def test_month_missing_points_never_become_zero(self):
  a=self.ask('month',measure=1);self.assertEqual([2.0,4.0],[r['value'] for r in a['rows']]);self.assertEqual(29,len(a['gaps']));self.assertTrue(all(r['unit']=='days' for r in a['rows']))
 def test_procedure_needs_an_accepted_hash_and_refuses_tamper(self):
  self.assertEqual('unknown',self.ask('procedure',capability='sample')['status'])
  (self.root/'tools/cli/sample.md').write_text('unaccepted edit')
  with self.assertRaises(ValueError):self.ask('procedure',capability='sample',procedure_root=self.root,pins=self.pins)
 def test_procedure_cannot_open_raw_or_symlink(self):
  with sqlite3.connect(self.db) as c:c.execute("UPDATE base_capabilities SET card_path='raw/draft.md'")
  with self.assertRaises(ValueError):self.ask('procedure',capability='sample',procedure_root=self.root,pins={'raw/draft.md':'bad'})
 def test_missing_business_timezone_is_refused(self):
  with self.assertRaises(ValueError):query(self.db,'yesterday','shop','2026-10-14T12:00:00')
 def test_eval_results_are_scored(self):
  from run import names
  results=run();count=len(names());self.assertIn(count,(11,12));self.assertEqual(count,len(results));self.assertEqual(list(range(1,count+1)),[int(r['test'][:2]) for r in results]);self.assertTrue(all(r['denominator']>0 for r in results));self.assertTrue(all(r['passed']==(r['numerator']==r['denominator']) for r in results))
 def test_measure_writer_refuses_old_tracker(self):
  before=self.db.read_bytes()
  with self.assertRaises(ValueError):record(self.db,'shop','keeper','eval-test',run())
  self.assertEqual(before,self.db.read_bytes())
if __name__=='__main__':unittest.main()
