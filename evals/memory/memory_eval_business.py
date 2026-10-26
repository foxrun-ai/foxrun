"""Synthetic Sample Shop questions, or an explicit external question set."""
import json,os,sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def question_rows():
 # Business evidence belongs to its workspace. Product checks use fake rows.
 configured=os.environ.get('FOXRUN_EVAL_QUESTIONS')
 if configured:return json.loads(Path(configured).expanduser().read_text())
 statuses={'lead:3':'unknown','lead:4':'unconfirmed','lead:7':'stale','amazon:2':'stale','amazon:7':'unknown'}
 return [dict(id='sample-shop-'+role+':'+str(n),question='Synthetic '+role+' question '+str(n),
              snapshot_answer='Labeled fake evidence',source_route='synthetic fixture',
              as_of='2026-10-14',expected=statuses.get(role+':'+str(n),'dated'))
         for role in ('lead','amazon') for n in range(1,8)]

def build_cases(root):
 rows=question_rows();path=Path(root)/'questions.db'
 workspace=os.environ.get('FOXRUN_EVAL_WORKSPACE','sample-shop')
 with sqlite3.connect(path) as db:
  db.execute('CREATE TABLE memory_sources(id INTEGER,workspace TEXT,title TEXT,captured_at TEXT,details TEXT)')
  for n,row in enumerate(rows,1):
   # These conditions are independent source facts, not the expected answer field.
   identifier=row['id'];complete=not identifier.endswith(('-lead:3','-amazon:7'))
   confirmed=False if identifier.endswith('-lead:4') else None
   live=identifier.endswith(('-lead:7','-amazon:2'))
   details=dict(question_id=identifier,answer=row['snapshot_answer'],source_route=row['source_route'],complete=complete,confirmation=confirmed,requires_live=live)
   db.execute('INSERT INTO memory_sources VALUES(?,?,?,?,?)',(n,workspace,row['question'],row['as_of'],json.dumps(details)))
 return path,rows

def answer(database,identifier,workspace='sample-shop',as_of='2026-10-14'):
 with sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro',uri=True) as db:
  row=db.execute("SELECT id,title,captured_at,details FROM memory_sources WHERE workspace=? AND json_extract(details,'$.question_id')=? ORDER BY captured_at DESC,id DESC LIMIT 1",(workspace,identifier)).fetchone()
 if row is None:return {'status':'unknown','answer':None,'queries':1,'raw_files':0,'current':False}
 detail=json.loads(row[3]);status='dated'
 if not detail['complete']:status='unknown'
 elif detail['confirmation'] is False:status='unconfirmed'
 elif detail['requires_live']:status='stale'
 return {'question_id':identifier,'question':row[1],'status':status,'snapshot_answer':detail['answer'],'as_of':row[2],'source_route':detail['source_route'],'source_id':row[0],'queries':1,'raw_files':0,'current':False}

def score_cases(fetch=False):
 import tempfile
 failures=[];counts=[]
 with tempfile.TemporaryDirectory(prefix='sample-question-') as folder:
  database,rows=build_cases(folder)
  for row in rows:
   result=answer(database,row['id'],os.environ.get('FOXRUN_EVAL_WORKSPACE','sample-shop'));size=len(json.dumps(result,ensure_ascii=False).encode())
   counts.append(dict(question=row['id'],queries=result['queries'],files=0,bytes=size))
   if result['status']!=row['expected'] or result['current'] or result['raw_files'] or not result.get('source_route'):
    failures.append(row['id']+': dated source status or route mismatch')
   if fetch and (result['queries']!=1 or size>12000):failures.append(row['id']+': fetch budget exceeded')
 return {'numerator':len(rows)-len(failures),'denominator':len(rows),'failures':failures,'counts':counts}
