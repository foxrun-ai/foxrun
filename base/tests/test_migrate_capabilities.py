"""Tests for the independent checked migration route; legacy CSV API stays unchanged."""
import csv,json,sqlite3,subprocess,sys,tempfile,unittest
from pathlib import Path
from base import migrate_capabilities
class MigrationTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve();self.db=self.root/'data.db';self.rows=self.root/'rows.tsv'
  with sqlite3.connect(self.db) as c:c.execute('CREATE TABLE base_capabilities(id INTEGER PRIMARY KEY,name TEXT UNIQUE,kind TEXT,"set" TEXT,workspace TEXT,status TEXT,runtimes TEXT,card_path TEXT)')
  p=self.root/'tools/cli/sample.md';p.parent.mkdir(parents=True);p.write_text('# Current card\n')
  self.write(dict(name='sample',kind='cli',set='base',workspace='foxrun-dev',status='live',runtimes='["codex"]',card_path='tools/cli/sample.md'))
 def write(self,row):
  with self.rows.open('w') as f:
   w=csv.DictWriter(f,list(row),delimiter='\t');w.writeheader();w.writerow(row)
 def count(self):
  with sqlite3.connect(self.db) as c:return c.execute('select count(*) from base_capabilities').fetchone()[0]
 def test_default_check_does_not_load(self):
  self.assertEqual(1,migrate_capabilities.load(self.db,self.rows));self.assertEqual(0,self.count())
 def test_write_and_idempotent_readback(self):
  self.assertEqual(1,migrate_capabilities.load(self.db,self.rows,True));self.assertEqual(1,migrate_capabilities.load(self.db,self.rows,True));self.assertEqual(1,self.count())
 def test_missing_card_refuses_before_write(self):
  (self.root/'tools/cli/sample.md').unlink()
  with self.assertRaises(ValueError):migrate_capabilities.load(self.db,self.rows,True)
  self.assertEqual(0,self.count())
 def test_existing_row_difference_refuses(self):
  migrate_capabilities.load(self.db,self.rows,True)
  with sqlite3.connect(self.db) as c:c.execute("update base_capabilities set status='parked'")
  with self.assertRaises(ValueError):migrate_capabilities.load(self.db,self.rows,True)
 def test_cli_rows_check_and_write(self):
  script=Path(migrate_capabilities.__file__)
  for suffix,count in [([],0),(['--write'],1)]:
   result=subprocess.run([sys.executable,'-B',str(script),'--db',str(self.db),'--rows',str(self.rows),*suffix],text=True,capture_output=True)
   self.assertEqual(0,result.returncode,result.stderr);self.assertEqual(count,self.count())
 def test_old_tracker_is_refused(self):
  old=self.root/'old.db';sqlite3.connect(old).close();before=old.read_bytes()
  with self.assertRaises(ValueError):migrate_capabilities.load(old,self.rows,True)
  self.assertEqual(before,old.read_bytes())
if __name__=='__main__':unittest.main()
