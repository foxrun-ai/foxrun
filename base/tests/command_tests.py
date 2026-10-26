"""Exercise table commands, state events, rollback, and counter contention."""

from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'base/tests', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()
import concurrent.futures
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from core import build,connect,execute,load,EVENTS,Q
from fixtures import Fixtures
from guard_tests import SCHEMA,AGENT

def verify(path,blueprint):
    build(path,blueprint);targets,columns=load(blueprint);tables={t['name']:t for t in targets if t['kind']=='table'}
    insert_path=Path(path).with_name('insert-commands.db');build(insert_path,blueprint)
    insert_db=connect(insert_path,SCHEMA);insert_f=Fixtures(insert_db,targets,columns)
    inserted=[]
    for table,target in tables.items():
        if table in EVENTS:continue
        data=insert_f.data(table);identity=None
        if table=='people_pipelines':
            used={r[0] for r in insert_db.execute('SELECT name FROM people_pipelines')};data['name']=next(n for n in ('clients','creators','ventures') if n not in used)
        if table=='people_pipeline_stages':
            name=insert_db.execute('SELECT name FROM people_pipelines WHERE id=?',(data['pipeline'],)).fetchone()[0]
            choices=next(c['allowed_values'][name] for c in columns if c['table']==table and c['column']=='stage')
            used={r[0] for r in insert_db.execute('SELECT stage FROM people_pipeline_stages WHERE pipeline=?',(data['pipeline'],))}
            data['stage']=next(v for v in choices if v not in used)
        if table=='amazon_accounts':identity=insert_f.row('commerce_accounts',source_system='amazon')
        controlled={'id','seq','action','actor','session','recorded_at','occurred_at','created_at','updated_at'}
        for c in columns:
            if c['table']==table and (c['column']=='version' and c['sqlite_type']=='INTEGER' or c['field_type']=='timestamp' and c.get('required_when','').startswith('New row.') and not c['column'].startswith('source_')):controlled.add(c['column'])
        data={k:v for k,v in data.items() if k not in controlled}
        context=dict(AGENT,workspace=data.get('workspace','system-workspace'))
        if table=='amazon_accounts':context['workspace']=insert_db.execute('SELECT workspace FROM commerce_accounts WHERE id=?',(identity,)).fetchone()[0]
        if target.get('database_type')=='mirror':context.update(writer='feeder',source='fixture feeder',session=None)
        insert_db.commit()
        try:result=execute(insert_path,blueprint,table,'insert',data,identity,context)
        except Exception as error:raise AssertionError(table+' actual insert: '+str(error)) from error
        assert insert_db.execute('SELECT count(*) FROM '+Q(table)+' WHERE id=?',(result['id'],)).fetchone()[0]==1
        inserted.append(table+' actual insert')
    insert_db.close()
    db=connect(path,SCHEMA);f=Fixtures(db,targets,columns);tested=list(inserted)
    for table in tables:
        wrapper=Path(blueprint).parent/'commands'/table
        result=subprocess.run([str(wrapper),'--help'],text=True,capture_output=True)
        assert result.returncode==0,table+' executable table command';tested.append(table+' command')
    wrapper=Path(blueprint).parent/'commands/work_tasks'
    result=subprocess.run([str(wrapper),'--db',str(path),'--actor','fixture','--workspace','system-workspace','--session','fixture','--table','commerce_accounts','insert','--json',json.dumps({'title':'Fixed table fixture','status':'todo','reviewer':'lead','reviewed_by':'fixture'})],text=True,capture_output=True)
    assert result.returncode==0,'named command table override: '+result.stderr
    assert db.execute("SELECT count(*) FROM work_tasks WHERE title='Fixed table fixture'").fetchone()[0]==1
    tested.append('named command cannot change its table')
    for c in columns:
        if c['table'] not in tables or c['table'] in EVENTS or c['column'] not in tables[c['table']].get('state_write_columns',[]):continue
        table=c['table'];field=c['column'];key=f.first(table)
        row=db.execute('SELECT * FROM '+Q(table)+' WHERE id=?',(key,)).fetchone();old=row[field];choices=c.get('allowed_values')
        if c['field_type']=='link' and field=='stage':
            pipeline=row['pipeline'];stage=db.execute('SELECT stage FROM people_pipeline_stages WHERE pipeline=? LIMIT 1',(pipeline,)).fetchone()
            name=db.execute('SELECT name FROM people_pipelines WHERE id=?',(pipeline,)).fetchone()[0]
            choices=next(x['allowed_values'][name] for x in columns if x['table']=='people_pipeline_stages' and x['column']=='stage')
            used={r[0] for r in db.execute('SELECT stage FROM people_pipeline_stages WHERE pipeline=?',(pipeline,))}
            new=f.row('people_pipeline_stages',pipeline=pipeline,stage=next(v for v in choices if v not in used))
        elif isinstance(choices,dict):
            name=db.execute('SELECT name FROM people_pipelines WHERE id=?',(row['pipeline'],)).fetchone()[0]
            used={r[0] for r in db.execute('SELECT stage FROM people_pipeline_stages WHERE pipeline=?',(row['pipeline'],))}
            new=next(v for v in choices[name] if v not in used)
        elif table=='people_drafts' and field=='status':new='skipped'
        elif choices:new=next(v for v in choices if v!=old and v not in ('canceled','snoozed'))
        else:new='fixture state'
        db.commit();ctx=dict(AGENT,workspace=row['workspace'] if 'workspace' in row.keys() else 'system-workspace')
        if tables[table].get('database_type')=='mirror':ctx.update(writer='feeder',source='fixture feeder',session=None)
        before=db.execute('SELECT value FROM _foxrun_sequence').fetchone()[0]
        assert execute(path,blueprint,table,'update',{field:new},key,ctx)['changed']
        changes=list(db.execute('SELECT * FROM work_changes WHERE seq>?',(before,)))
        state=[r for r in changes if r['field']==field]
        assert len(state)==1 and state[0]['new_value']==str(new) and state[0]['old_value']==(None if old is None else str(old)),table+'.'+field+' one event'
        count=db.execute('SELECT value FROM _foxrun_sequence').fetchone()[0]
        assert not execute(path,blueprint,table,'update',{field:new},key,ctx)['changed']
        assert db.execute('SELECT value FROM _foxrun_sequence').fetchone()[0]==count,table+' echo';tested.append(table+'.'+field+' atomic state/no-op')
    task=f.row('work_tasks',workspace='system-workspace',status='todo');db.commit()
    def refused(fn):
        try:fn()
        except (ValueError,sqlite3.Error):return
        raise AssertionError('command accepted invalid request')
    before=db.execute('SELECT value FROM _foxrun_sequence').fetchone()[0]
    refused(lambda:execute(path,blueprint,'work_tasks','update',{'status':'in-progress','important':2},task,AGENT))
    assert db.execute('SELECT status FROM work_tasks WHERE id=?',(task,)).fetchone()[0]=='todo'
    assert db.execute('SELECT value FROM _foxrun_sequence').fetchone()[0]==before;tested.append('state rollback preserves counter')
    execute(path,blueprint,'work_changes','verified',{'subject_type':'task','subject_id':task,'subject_version':'1','summary':'fixture verified'},None,AGENT)
    refused(lambda:execute(path,blueprint,'work_changes','accepted',{'subject_type':'task','subject_id':task,'subject_version':'1'},None,dict(AGENT,actor='other')))
    refused(lambda:execute(path,blueprint,'work_changes','verified',{'subject_type':'task','subject_id':task,'subject_version':'9'},None,AGENT));tested.append('reviewer exact-version milestones')
    approval={'subject_type':'task','subject_id':task,'version':1,'approved_sha256':'a'*64,'envelope_ref':'fixture-envelope','go_word':1,'authorization_valid':1}
    execute(path,blueprint,'base_approvals','approved',approval,None,dict(AGENT,actor='person'))
    refused(lambda:execute(path,blueprint,'base_approvals','approved',approval,None,AGENT))
    refused(lambda:execute(path,blueprint,'base_approvals','approved',dict(approval,version=2),None,dict(AGENT,actor='person')))
    refused(lambda:execute(path,blueprint,'base_approvals','approved',dict(approval,approved_sha256='z'*64),None,dict(AGENT,actor='person')))
    refused(lambda:execute(path,blueprint,'work_tasks','update',{'version':99},task,AGENT))
    run=f.first('work_runs');db.commit()
    refused(lambda:execute(path,blueprint,'work_runs','update',{'started_at':'1900-01-01T00:00:00Z'},run,AGENT))
    for response in ('rejected','edited','discussed'):execute(path,blueprint,'base_approvals',response,{'subject_type':'task','subject_id':task,'version':1,'summary':'fixture response'},None,AGENT)
    tested.append('approval responses and authorization gates')
    execute(path,blueprint,'work_comments','insert',{'subject_type':'task','subject_id':task,'body':'Fixture command comment'},None,AGENT)
    tested.append('comment table command')
    page=f.row('base_pages',workspace='system-workspace');db.commit()
    execute(path,blueprint,'work_attachments','published',{'subject_type':'page','subject_id':page,'role':'produced','path':'fixture-page','payload':json.dumps({'version':'fixture-1'})},None,AGENT)
    refused(lambda:execute(path,blueprint,'work_attachments','published',{'subject_type':'page','subject_id':page,'role':'produced','path':'fixture-page'},None,AGENT));tested.append('page publication version')
    for moment in ('handed-off','compacted','forked','closed'):
        execute(path,blueprint,'base_receipts','insert',{'subject_type':'session','subject_id':1,'summary':'fixture'},None,dict(AGENT,moment=moment))
    tested.append('receipt moments and bookmarks');db.close()
    def insert(n):return execute(path,blueprint,'work_tasks','insert',{'title':'Concurrent fixture '+str(n),'status':'todo','reviewer':'lead','reviewed_by':'fixture'},None,AGENT)['id']
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:ids=list(pool.map(insert,range(12)))
    db=connect(path,readonly=True)
    assert len(ids)==len(set(ids))==12
    numbers=[r[0] for r in db.execute('SELECT number FROM work_tasks WHERE id IN ('+','.join('?' for _ in ids)+')',ids)]
    assert len(numbers)==len(set(numbers))==12
    seqs=[r[0] for r in db.execute('SELECT seq FROM base_timeline ORDER BY seq')]
    assert seqs==list(range(1,db.execute('SELECT value FROM _foxrun_sequence').fetchone()[0]+1));db.close()
    tested.append('concurrent hidden ids, display numbers, and global sequence');return tested
