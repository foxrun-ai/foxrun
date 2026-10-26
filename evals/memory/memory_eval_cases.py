"""Scored acceptance cases, not unittest dispatch. All mutation probes use temporary homes."""
import argparse,ast,csv,hashlib,importlib.util,io,json,os,sqlite3,subprocess,sys,tempfile
from contextlib import contextmanager,redirect_stdout
from datetime import datetime,timedelta,timezone
from pathlib import Path
from memory_eval_fixtures import build,AT
from memory_eval_queries import query
ROOT=Path(__file__).resolve().parent
NAMES={1:'rule',3:'reliability',4:'code-first',5:'trace',7:'triangulate',8:'field',9:'portability',10:'night-shift',11:'seven-nights',12:'move'}
def home():return Path(os.environ.get('FOXRUN_EVAL_HOME',str(ROOT.parents[1]))).resolve()
def module(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
@contextmanager
def isolated():
 old=dict(os.environ)
 with tempfile.TemporaryDirectory(prefix='memory-eval-') as folder:
  root=Path(folder).resolve();system=root/'system';portfolio=root/'portfolio';(system/'config').mkdir(parents=True)
  for ws in ('consulting','personal','practice'):(portfolio/ws).mkdir(parents=True)
  (system/'config/person.json').write_text(json.dumps({'name':'person','workspaces':['consulting','personal','practice'],'default_workspace':'consulting','system_workspace':'consulting','workspace_settings':{'consulting':{'lead':'lead-consulting'},'personal':{'lead':'lead-personal'},'practice':{'lead':'lead-practice'}}}))
  os.environ.update(FOXRUN_HOME=str(system),FOXRUN_PORTFOLIO=str(portfolio),FOXRUN_STATE=str(root/'service-state'),PYTHONDONTWRITEBYTECODE='1')
  sys.path[:0]=[str(home()),str(home()/'base'),str(home()/'work'),str(home()/'events'),str(home()/'memory')]
  try:yield root,system,portfolio
  finally:os.environ.clear();os.environ.update(old)
class Score:
 def __init__(self,number):self.number=number;self.cases=[];self.details={}
 def case(self,name,fn):
  try:
   value=fn();passed=value is not False;reason='' if passed else 'expected behavior was not observed'
  except Exception as e:passed=False;reason=type(e).__name__+': '+str(e)[:180]
  self.cases.append({'case':name,'passed':passed,'reason':reason})
 def result(self):
  failures=[c for c in self.cases if not c['passed']]
  return dict(test='%02d-%s'%(self.number,NAMES[self.number]),passed=not failures,numerator=len(self.cases)-len(failures),denominator=len(self.cases),failures=[c['case']+': '+c['reason'] for c in failures],cases=self.cases,**self.details)
def expect(value,wanted):
 if value!=wanted:raise AssertionError('expected '+repr(wanted)+', observed '+repr(value))
 return True

def rule_cases(score):
 # Lookup the shipped dictionary binding; ambiguity and missing scope demand review.
 rows=[json.loads(line) for line in (home()/'base/blueprint/target-v13.jsonl').read_text().splitlines()]
 index={}
 for r in rows:index.setdefault((r['module'],r.get('object_type',r['name'])),[]).append(r)
 def route(module_name,kind,workspace,columns):
  matches=index.get((module_name,kind),[])
  if not workspace or len(matches)!=1:return 'review'
  row=matches[0]
  if any(k not in columns for k in row.get('primary_key',[])):return 'review'
  if row['kind']=='table':return workspace+':data.db::'+row['name']
  return row.get('path') or 'review'
 for r in rows:
  key=(r['module'],r.get('object_type',r['name']));expected='review' if len(index[key])!=1 or r['kind']!='table' else 'consulting:data.db::'+r['name']
  score.case('dictionary:'+r['module']+':'+r['name'],lambda r=r,w=expected:expect(route(r['module'],r.get('object_type',r['name']),'consulting',r.get('primary_key',[])+['workspace']),w))
 for r in rows:
  if r.get('primary_key'):score.case('missing key columns:'+r['name'],lambda r=r:expect(route(r['module'],r.get('object_type',r['name']),'consulting',[]),'review'))
 score.case('unknown type needs judgment',lambda:expect(route('base','made-up','consulting',[]),'review'))
 score.case('missing workspace needs judgment',lambda:expect(route('work','task',None,['id','workspace']),'review'))
 score.details['boundary']='Dictionary binding selection only; unknown file ownership remains review. No model runs.'

def reliability_cases(score):
 from memory import model_proposals,source_digest,state,kept
 with isolated() as (root,system,portfolio):
  (root/'fixture').mkdir();db,pins=build(root/'fixture');before=db.read_bytes()
  score.case('eager model proposal has no direct database pen',lambda: _proposal_isolation(model_proposals,system,db,before))
  score.case('replaced decision does not read as live',lambda:_decision_replacement(root))
  raw=root/'source.txt';raw.write_text('old');digest=source_digest.source_digest(raw);raw.write_text('new')
  score.case('stale cached source is rejected',lambda:expect(source_digest.check_source(raw,digest),'changed'))
  score.case('two frozen writers cannot replace accepted content',lambda:_frozen_conflict(kept,portfolio))
  score.case('replay preserves original snapshot bytes',lambda:_frozen_replay(kept,portfolio))
  score.case('late source leaves old decision evidence stale',lambda:expect(source_digest.check_source(raw,digest),'changed'))
  score.details['boundary']='Actual model, frozen-write and digest code; replacement case uses the bounded read route.'
def _decision_replacement(root):
 db=root/'decisions.db'
 with sqlite3.connect(db) as con:
  con.execute('CREATE TABLE decisions(id TEXT,name TEXT,status TEXT,replaces TEXT,statement TEXT)')
  con.executemany('INSERT INTO decisions VALUES(?,?,?,?,?)',[('g-old','old','replaced',None,'Old rule'),('g-new','new','ruled','g-old','New rule')])
 path=home()/'decisions/decisions.py'
 if not path.is_file():raise ValueError('installed decision reader is missing')
 result=subprocess.run([sys.executable,'-B',str(path),'list','--status','ruled','--db',str(db)],env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),text=True,capture_output=True,timeout=20)
 if result.returncode:raise ValueError('decision reader failed: '+result.stderr[:120])
 return [r['id'] for r in json.loads(result.stdout)]==['g-new']

def _proposal_isolation(model,system,db,before):
 (system/'memory/adapters').mkdir(parents=True);(system/'memory/adapters/fake.py').write_text('# fixture transport\n')
 (system/'config/models.yaml').write_text(json.dumps({'dream':{'model':'fixture'},'models':[{'id':'fixture','runtime':'fixture','model':'local','adapter':'memory/adapters/fake.py'}]}))
 out=model.model_half(system,'2026-10-14',[],adapter=lambda chosen,request:'Propose a change; do not apply it.')
 return out['state']=='pass' and db.read_bytes()==before and (system/out['proposal']).is_file()
def _frozen_conflict(kept,portfolio):
 code="import sys;from memory.kept import freeze;freeze('consulting',sys.argv[1],identifier='concurrent')"
 env=dict(os.environ,PYTHONPATH=str(home()),PYTHONDONTWRITEBYTECODE='1')
 calls=[subprocess.Popen([sys.executable,'-B','-c',code,text],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for text in ('first writer','second writer')]
 results=[]
 for call in calls:
  call.communicate(timeout=20);results.append(call.returncode)
 path=portfolio/'consulting/history/snapshots/concurrent.md'
 if sorted(results)!=[0,1] or not path.is_file():return False
 before=path.read_bytes()
 try:kept.freeze('consulting','third writer',identifier='concurrent');return False
 except ValueError:return path.read_bytes()==before

def _frozen_replay(kept,portfolio):
 path=kept.freeze('consulting','replay',identifier='replay');before=path.read_bytes();kept.freeze('consulting','replay',identifier='replay');return path.read_bytes()==before

def code_cases(score):
 design=json.loads((ROOT/'design-flow.json').read_text())['foxrun'];names={n[0] for n in design['tree']};modes={}
 for phase,steps in design['streams']:
  for step in steps:
   label=phase+':'+step['row']+':'+step['t'];mode=step.get('m','person/runtime');modes[mode]=modes.get(mode,0)+1
   def flow_check(s=step,m=mode):
    if any(ref not in names for k in ('runs','reads','writes') for ref in s.get(k,[])):raise ValueError('flow references an undeclared node')
    if m not in ('code','model','both','person/runtime'):raise ValueError('flow step has no declared executor')
    if m in ('model','both') and not s.get('say'):raise ValueError('model step has no stated semantic purpose')
    return True
   score.case('declared flow:'+label,flow_check)
 score.details['design_steps']=sum(modes.values());score.details['design_modes']=modes
 tree=ast.parse((home()/'memory/dream.py').read_text());functions={n.name for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
 assignment=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='CODE_STEPS' for t in n.targets))
 steps=assignment.value.elts
 for item in steps:
  name=ast.literal_eval(item.elts[0]);purpose=ast.literal_eval(item.elts[1]);fn=item.elts[2].id
  score.case('code step:'+name,lambda p=purpose,f=fn:bool(p.strip()) and f in functions)
 model=(home()/'memory/model_proposals.py').read_text()
 score.case('model step explains semantic proposal need',lambda:'Return proposed improvements for human review' in model and 'You have no tools' in model)
 score.case('model output has no automatic admission',lambda:'For review. No page or row was changed' in model and "state='pass'" in model)
 score.details.update(code_steps=len(steps),model_steps=1,boundary='Checks all twenty approved flow declarations and references, then the implemented nightly job; artifact declarations do not prove runtime deployment.')

# Trace fixture uses the ruled memory_evidence/source columns. Hash checking calls the real digest implementation.
def trace(database,claim,root):
 from memory.source_digest import check_source
 with sqlite3.connect(Path(database).as_uri()+'?mode=ro',uri=True) as db:
  rows=db.execute('SELECT e.subject_id,e.locator,e.actor,e.created_at,s.path,s.sha256,s.made_by,s.made_at,s.status FROM memory_evidence e JOIN memory_sources s ON s.id=e.source WHERE e.subject_type=? AND e.subject_id=?',('lesson',claim)).fetchall()
 if len(rows)!=1:raise ValueError('missing or ambiguous evidence')
 row=rows[0]
 page=Path(root)/row[1].split('#',1)[0]
 if not page.is_file():raise ValueError('claim page is missing')
 content=page.read_text()
 if 'status: accepted' not in content or ('source_id: '+str(row[0])) not in content or ('quote_sha256: '+row[5]) not in content:raise ValueError('page admission or exact-quote binding differs')
 if row[-1]!='ok' or check_source(Path(root)/row[4],row[5])!='ok':raise ValueError('source is not current')
 if not all(row[i] for i in (1,2,3,4,5,6,7)):raise ValueError('incomplete source chain')
 return {'row':row[0],'page':row[1],'actor':row[2],'recorded_at':row[3],'raw':row[4],'sha256':row[5],'speaker':row[6],'spoken_at':row[7]}
def trace_cases(score):
 with tempfile.TemporaryDirectory(prefix='memory-trace-') as folder:
  root=Path(folder).resolve();db=root/'trace.db'
  with sqlite3.connect(db) as c:
   c.executescript('CREATE TABLE memory_sources(id INTEGER,path TEXT,sha256 TEXT,made_by TEXT,made_at TEXT,status TEXT);CREATE TABLE memory_evidence(subject_type TEXT,subject_id INTEGER,source INTEGER,locator TEXT,actor TEXT,created_at TEXT);')
   for i in range(100):
    path=root/('quote-%03d.txt'%i);raw=('exact source quote '+str(i)+'\n').encode();path.write_bytes(raw)
    c.execute('INSERT INTO memory_sources VALUES(?,?,?,?,?,?)',(i,path.name,hashlib.sha256(raw).hexdigest(),'speaker-'+str(i),AT,'ok'))
    page=root/('wiki/concepts/page-%03d.md'%i);page.parent.mkdir(parents=True,exist_ok=True);page.write_text('---\nstatus: accepted\nsource_id: '+str(i)+'\nquote_sha256: '+hashlib.sha256(raw).hexdigest()+'\n---\n'+raw.decode())
    c.execute('INSERT INTO memory_evidence VALUES(?,?,?,?,?,?)',('lesson',i,i,'wiki/concepts/page-%03d.md#claim'%i,'capture-agent',AT))
  for i in range(100):score.case('source chain %03d'%i,lambda i=i:expect(trace(db,i,root)['sha256'],hashlib.sha256(('exact source quote '+str(i)+'\n').encode()).hexdigest()))
  (root/'quote-000.txt').write_text('altered')
  def tamper():
   try:trace(db,0,root);return False
   except ValueError:return True
  score.case('changed exact quote refuses trace',tamper)
  score.details['boundary']='A single eval command walks 100 registered evidence chains; no live business claim is admitted.'

def topic(database,workspace,tag):
 with sqlite3.connect(Path(database).as_uri()+'?mode=ro',uri=True) as db:
  rows=[dict(zip(('id','family','canonical_url','path','note'),r)) for r in db.execute('SELECT id,family,canonical_url,path,note FROM memory_sources WHERE workspace=? AND tags=? ORDER BY id',(workspace,tag))]
 origins={r['canonical_url'] or r['path'] for r in rows}
 return {'sources':rows,'origins':len(origins),'single_source':len(origins)==1}
def triangulate_cases(score):
 with tempfile.TemporaryDirectory(prefix='memory-topic-') as folder:
  db=Path(folder)/'topic.db'
  with sqlite3.connect(db) as c:
   c.execute('CREATE TABLE memory_sources(id INTEGER,workspace TEXT,tags TEXT,family TEXT,canonical_url TEXT,path TEXT,note TEXT)')
   for row in [(1,'shop','stock','raw','origin:a','raw/a','source fact'),(2,'shop','stock','raw','origin:b','raw/b','independent source'),(3,'shop','stock','raw','origin:a','raw/copy','copied source'),(4,'shop','stock','episodic','origin:a','history/event','dated event'),(5,'shop','stock','semantic','origin:b','wiki/claim','contradiction'),(6,'shop','one','semantic','origin:a','wiki/one','one source'),(7,'other','stock','raw','origin:private','raw/private','wrong workspace')]:c.execute('INSERT INTO memory_sources VALUES(?,?,?,?,?,?,?)',row)
  result=topic(db,'shop','stock')
  score.case('all five raw/event/claim/contradiction links',lambda:expect([r['id'] for r in result['sources']],[1,2,3,4,5]))
  score.case('copies share two independent origin groups',lambda:expect(result['origins'],2))
  score.case('one-source flag',lambda:expect(topic(db,'shop','one')['single_source'],True))
  score.details['boundary']='Registered topic links only; copied material does not add an independent origin.'

def field_cases(score):
 rows=json.loads((ROOT/'field-evidence.json').read_text())
 for row in rows:
  score.case(row['departure'],lambda r=row:bool(r['owner_need'] and r['cost'] and r['precedents']) and all(x['sha256'] and x['source'] and x['excerpt'] for x in r['precedents']))
 score.details['boundary']='Six documented owner needs, first-hand source captures and accepted costs; relative merit remains opinion.'

def portability_cases(score):
 from base import paths,tracker
 with isolated() as (root,system,portfolio):
  from memory import state
  for workspace in ('consulting','personal','practice'):
   folder=portfolio/workspace
   for name in ('AGENTS.md','RESOLVER.md'): (folder/name).write_text('# '+name+'\n')
   db=folder/'data.db'
   with sqlite3.connect(db) as c:c.execute('CREATE TABLE tasks(id TEXT,title TEXT,status TEXT,project TEXT,parent TEXT,tags TEXT,created_on TEXT)');c.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?)',('T1','Generic work','todo',None,None,None,AT))
   def check_scope(ws=workspace):
    text=state.render(ws,datetime.fromisoformat(AT));return tracker.tracker(ws)==portfolio/ws/'data.db' and ('# State: '+ws) in text and not any((portfolio/ws/x).exists() for x in ('commerce','amazon','creator_cycles'))
   score.case('installed neutral workspace:'+workspace,check_scope)
  score.details['boundary']='Three minimal selected-module homes use actual installed tracker/state readers; full product packaging is a separate hold.'

def night_cases(score):
 from memory import source_digest,model_proposals,state,kept
 from base import tracker
 with isolated() as (root,system,portfolio):
  folder=root/'fixture';folder.mkdir();db,pins=build(folder)
  score.case('permitted cold worker task is visible',lambda:expect([r['number'] for r in query(db,'next','shop',AT)['rows']],['T1','T2']))
  score.case('missing approval is never inferred',lambda:all(r['authorized'] is None for r in query(db,'next','shop',AT)['rows']))
  file=root/'source';file.write_text('source');digest=source_digest.source_digest(file);file.write_text('late')
  score.case('stale source blocks a current claim',lambda:expect(source_digest.check_source(file,digest),'changed'))
  score.case('wrong workspace supplies no task',lambda:expect(query(db,'next','other',AT)['rows'],[]))
  score.case('absent model remains a reported skip',lambda:expect(model_proposals.model_half(system,'2026-10-14',[],dry_run=True)['state'],'skipped-no-model'))
  # Exclusive publication survives a dead pending writer: no pending file becomes current.
  snapshots=portfolio/'consulting/history/snapshots';snapshots.mkdir(parents=True);(snapshots/'.kept-dead').write_text('uncommitted')
  score.case('killed writer cannot publish its pending bytes',lambda:_frozen_replay(kept,portfolio) and (snapshots/'.kept-dead').read_text()=='uncommitted')
  score.details['boundary']='Six cold-worker cases; no external sends, model transport, or unattended runtime starts.'

def week_fault(label,root,system,at):
 """Exercise real code for each fault. A failure receipt is not successful recovery."""
 from memory import model_proposals,kept,state,dream
 from unittest.mock import patch
 if label=='model failure':
  (system/'memory/adapters').mkdir(parents=True,exist_ok=True);(system/'memory/adapters/fake.py').write_text('# fixture transport\n')
  (system/'config/models.yaml').write_text(json.dumps({'dream':{'model':'fixture'},'models':[{'id':'fixture','runtime':'fixture','model':'local','adapter':'memory/adapters/fake.py'}]}))
  def bad_adapter(chosen,request):raise OSError('fixture model unavailable')
  result=model_proposals.model_half(system,at.date().isoformat(),[],adapter=bad_adapter)
  return 'fail',('Actual tool-free model adapter failure is retained; successful recovery remains unproven' if result['state']=='fail' else 'Model failure injection was not observed')
 if label=='bad input':
  source=root/'bad-input.txt';source.write_text('   ')
  try:kept.freeze('consulting',source.read_text(),identifier='bad-input')
  except ValueError:return 'fail','Blank input refused; its original source bytes remain'
  return 'fail','Blank input was unexpectedly accepted'
 if label=='duplicate events':
  importer=module('week_log_import',home()/'events/import_log.py');database=root/'event-copy.db'
  with sqlite3.connect(database) as db:
   db.execute('CREATE TABLE events_changes(seq INTEGER PRIMARY KEY,workspace TEXT,subject_type TEXT,subject_id TEXT,action TEXT,actor TEXT,new_value TEXT,refs TEXT,occurred_at TEXT,recorded_at TEXT,summary TEXT,source TEXT,session TEXT)')
  source=root/'one-event.jsonl';source.write_text(json.dumps({'body':'one admitted event','date':at.date().isoformat()})+'\n')
  importer.import_log(source,database,'consulting',True);importer.import_log(source,database,'consulting',True)
  with sqlite3.connect(database) as db:count=db.execute('SELECT count(*) FROM events_changes').fetchone()[0]
  return ('pass' if count==1 else 'fail','Actual event importer replays without a second row')
 if label=='restart':
  checkpoint=Path(os.environ['FOXRUN_STATE'])/'session-nightly/state.json';dream.save_state(checkpoint,{'flagged':{'event:1':True}})
  code="from memory.dream import Config;import json;assert json.loads(Config().state_file.read_text())['flagged']['event:1'];print('checkpoint retained')"
  env=dict(os.environ,PYTHONPATH=str(home())+os.pathsep+str(home()/'memory'))
  result=subprocess.run([sys.executable,'-B','-c',code],env=env,text=True,capture_output=True,timeout=20)
  return ('pass' if result.returncode==0 else 'fail','Fresh process reads the actual Config nightly checkpoint')
 if label=='stale lease':
  # The accepted runner holds dead locks for explicit recovery. It has no timed-lease recovery API.
  text=(home()/'work/flow.py').read_text()
  return 'fail','Current runner requires manual recovery of dead locks; automatic stale-lease recovery is unproven'
 if label=='disk pressure':
  page=root/'published.md';page.write_text('accepted old page\n');old=page.read_bytes()
  with patch('os.replace',side_effect=OSError(28,'fixture disk full')):
   try:state.write_once(page,'replacement\n')
   except OSError:
    if page.read_bytes()!=old:raise ValueError('accepted page was damaged')
    return 'fail','Actual atomic writer preserves the old page on ENOSPC; no quota/catch-up recovery exists'
  return 'fail','Disk-full injection was not observed'
 if label=='bad backup':
  from base import backup
  database=root/'corrupt.db';database.write_bytes(b'not a SQLite database');archive=root/'last-good.jsonl';archive.write_text('last good backup\n');old=archive.read_bytes()
  try:backup.export_state(database,root/'new-backup')
  except Exception:
   if archive.read_bytes()!=old:raise ValueError('last good backup was lost')
   return 'fail','Actual backup exporter refuses corrupt input; last-good bytes stay; successful recovery remains unproven'
  return 'fail','Corrupt backup input was not refused'
 raise ValueError('unknown fault scenario')

def week_cases(score):
 from memory import dream,health,state,model_proposals
 with isolated() as (root,system,portfolio):
  (system/'runs').mkdir();ledger=root/'events.jsonl';ledger.write_text('')
  scenarios=('model failure','bad input','duplicate events','restart','stale lease','disk pressure','bad backup')
  for i,label in enumerate(scenarios):
   at=datetime(2026,10,1,tzinfo=timezone.utc)+timedelta(days=i);folder=system/'runs'/('2026-10-%02d-dream'%(i+1));folder.mkdir()
   saved=ledger.read_bytes()
   def failing(h,now):return week_fault(label,root,system,now)
   def preserving(h,now):
    # Fixture ledger is admitted before the fault; actual code dispatcher must still execute this later step.
    ledger.write_bytes(saved+json.dumps({'id':i,'at':now.isoformat()}).encode()+b'\n');return 'pass','event retained'
   rows=dream.code_half(system,folder,steps=[('fault',label,failing),('record','Retain admitted fixture event',preserving)],now=at)
   def recovery(rows=rows,saved=saved):
    if rows[1]['result']!='pass' or not ledger.read_bytes().startswith(saved):raise ValueError('admitted event retention failed')
    # Detection and continuing another step are not recovery of the failed mechanism.
    if not any(r['step']=='fault' and r['result']=='pass' for r in rows):raise ValueError(rows[0]['detail'])
    return True
   score.case('night %d recovery: %s'%(i+1,label),recovery)
  score.case('all seven admitted fixture events survive',lambda:expect(len(ledger.read_text().splitlines()),7))
  # Independent health must report a missing scheduler run; it does not claim an OS notification was delivered.
  with redirect_stdout(io.StringIO()):status=health.check_health()
  score.case('independent health detects absent completed job',lambda:expect(status,1))
  score.details.update(boundary='Fault-injected code-dispatch week. Detection is measured separately from successful recovery. Unrecovered fault receipts fail; no lease, quota or OS alert implementation is inferred.',live_week=live_week())
  score.case('live seven-night proof',lambda:score.details['live_week']['passed'])
  score.details['local_alert']=local_alert()
  score.case('independent local-alert delivery proof',lambda:score.details['local_alert']['passed'])
def local_alert():
 selected=os.environ.get('FOXRUN_EVAL_LOCAL_ALERT_RECEIPT')
 if not selected:return {'passed':False,'reason':'No approved local-alert delivery receipt supplied.'}
 path=Path(selected)
 if path.is_symlink():return {'passed':False,'reason':'Symlink alert receipt refused.'}
 row=json.loads(path.read_text());at=row.get('checked_at')
 try:datetime.fromisoformat(at);valid=True
 except (TypeError,ValueError):valid=False
 return {'passed':row.get('mode')=='live' and row.get('source')=='nightly-watchdog' and row.get('delivered') is True and row.get('scheduler_loaded') is False and row.get('launchctl_exit') != 0 and row.get('while_scheduler_dead') is True and row.get('channel')=='macOS' and valid and isinstance(row.get('receipt_age_seconds'), (int, float)) and isinstance(row.get('window_seconds'), (int, float)) and row['receipt_age_seconds'] >= row['window_seconds'],'reason':'Actual local delivery from an independent watcher while launchd had no nightly job is required.'}

def live_week():
 selected=os.environ.get('FOXRUN_EVAL_LIVE_WEEK')
 if not selected:return {'passed':False,'reason':'No explicit live-week receipt directory supplied; missing evidence is not a pass.'}
 root=Path(selected).resolve();dates=set();failures=[]
 for path in sorted(root.glob('*-dream*/manifest.json')):
  if path.is_symlink():failures.append('symlink receipt');continue
  row=json.loads(path.read_text())
  if row.get('mode')!='live' or row.get('result')!='pass' or not row.get('finished_at') or row.get('code_sha256')!=hashlib.sha256((home()/'memory/dream.py').read_bytes()).hexdigest():failures.append(path.parent.name+': incomplete live receipt')
  else:dates.add(row.get('date'))
 try:
  ordered=sorted(datetime.fromisoformat(x).date() for x in dates)
  consecutive=any((ordered[i+6]-ordered[i]).days==6 for i in range(max(0,len(ordered)-6)))
 except (TypeError,ValueError):consecutive=False
 return {'passed':consecutive and not failures,'dates':sorted(dates),'failures':failures,'reason':'Seven consecutive, completed live receipts required.'}

def move_cases(score):
 fixture=ROOT/'move-input.jsonl';frozen=[json.loads(x) for x in fixture.read_text().splitlines()]
 selected=os.environ.get('FOXRUN_EVAL_MOVE_MANIFEST');observed={r['source_id']:r for r in (json.loads(Path(selected).read_text()) if selected else frozen)}
 rows=[observed.get(r['source_id'],dict(r,disposition='unresolved',destinations=[])) for r in frozen];seen=set()
 for row in rows:
  key=row['source_id'];unique=key not in seen;seen.add(key)
  def check_move(r=row,u=unique):
   if not u:raise ValueError('duplicate input identity')
   if r.get('disposition') in ('stay','drop','archive'):
    if not r.get('ruled') or not r.get('reason') or not r.get('execution_verified'):raise ValueError('ruled disposition has no verified execution receipt')
    return True
   if r.get('disposition') not in ('copy','move','rows'):raise ValueError('unresolved or unsupported move disposition')
   if not r.get('ruled') or not r.get('reason'):raise ValueError('final home has no ruling')
   destinations=r.get('destinations',[])
   if len(destinations)!=1:raise ValueError('one ruled final home is required')
   if not r.get('payload_sha256') or r.get('verified_sha256')!=r['payload_sha256']:raise ValueError('final content readback is unverified')
   if not r.get('links_verified'):raise ValueError('retained links are unverified')
   return True
  score.case('move:'+key,check_move)
 score.case('frozen design count',lambda:expect(len(rows),28980))
 score.details.update(boundary='Frozen 28,980-item population, metadata only. Unapplied/unverified destinations fail; no source path is opened.',input_sha256=hashlib.sha256(fixture.read_bytes()).hexdigest())

def run(number):
 sys.path[:0]=[str(home()),str(home()/'base'),str(home()/'work'),str(home()/'events'),str(home()/'memory')]
 score=Score(number)
 work={1:rule_cases,3:reliability_cases,4:code_cases,5:trace_cases,7:triangulate_cases,8:field_cases,9:portability_cases,10:night_cases,11:week_cases,12:move_cases}[number]
 try:work(score)
 except Exception as e:score.case('required fixture or installed dependency',lambda:(_ for _ in ()).throw(e))
 return score.result()
def main(number):
 result=run(number);print(json.dumps(result,sort_keys=True));return 0 if result['passed'] else 1
