"""Try bad writes against each installed write-guard family and table."""

from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'base/tests', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from core import build,connect,execute,load,EVENTS,Q,link_target
from fixtures import Fixtures

SCHEMA={'writer':'feeder','source':'made-up fixtures','import':1,'workspace':'system-workspace','actor':'fixture','session':'fixture','reason':'fixture'}
AGENT={'writer':'agent','workspace':'system-workspace','actor':'fixture','session':'fixture','reason':'fixture'}

def verify(path,blueprint):
    build(path,blueprint);targets,columns=load(blueprint);db=connect(path,SCHEMA);f=Fixtures(db,targets,columns);tested=[]
    def refused(label,fn,message=None):
        db.execute('SAVEPOINT bad_write')
        try:
            try:fn()
            except (sqlite3.Error,ValueError,AssertionError) as error:
                if message and message.lower() not in str(error).lower() and not (message=='CHECK' and 'new row requires ' in str(error)):raise AssertionError(label+' refused for wrong reason: '+str(error))
                tested.append(label);return
            raise AssertionError(label+' accepted bad write')
        finally:db.execute('ROLLBACK TO bad_write');db.execute('RELEASE bad_write')
    def change(table,key,field,value):
        pk='seq' if table in EVENTS else 'id'
        return db.execute('UPDATE '+Q(table)+' SET '+Q(field)+'=? WHERE '+pk+'=?',(value,key))
    for t in targets:
        if t['kind']!='table':continue
        table=t['name'];key=f.first(table);pk='seq' if table in EVENTS else 'id'
        row=dict(db.execute('SELECT * FROM '+Q(table)+' WHERE '+pk+'=?',(key,)).fetchone())
        if table in EVENTS:
            refused(table+' append-only update',lambda:change(table,key,'actor','bad'),'append-only')
            refused(table+' append-only delete',lambda:db.execute('DELETE FROM '+Q(table)+' WHERE seq=?',(key,)),'append-only')
            bad=f.data(table);bad['seq']=db.execute('SELECT value FROM _foxrun_sequence').fetchone()[0]
            refused(table+' global sequence',lambda:db.execute('INSERT INTO '+Q(table)+' ('+','.join(map(Q,bad))+') VALUES ('+','.join('?' for _ in bad)+')',tuple(bad.values())),'sequence')
            bad['seq']=db.execute('SELECT value+1 FROM _foxrun_sequence').fetchone()[0];bad['session']=None
            no_session=connect(path,dict(SCHEMA,writer='agent',session=None))
            # Same transaction connection owns the fixture; change its context functions temporarily.
            db.create_function('foxrun_context',1,lambda k:dict(SCHEMA,writer='agent',session=None).get(k))
            refused(table+' writer session',lambda:db.execute('INSERT INTO '+Q(table)+' ('+','.join(map(Q,bad))+') VALUES ('+','.join('?' for _ in bad)+')',tuple(bad.values())),'session')
            no_session.close();db.create_function('foxrun_context',1,lambda k:SCHEMA.get(k))
            for c in (c for c in columns if c['table']==table and c['column']!='seq'):
                values=f.data(table);kind=c['field_type'];choices=c.get('allowed_values');field=c['column']
                cases=[]
                if choices:cases.append(('choices','not-a-choice','CHECK'))
                if kind=='boolean':cases.append(('boolean',2,'CHECK'))
                if kind in ('json','multi-pick'):cases.append(('JSON','{bad','CHECK'))
                if kind in ('date','timestamp'):cases.append((kind,'not-a-date','CHECK'))
                if c['required']:cases.append(('required',None,'NOT NULL'))
                if field in ('occurred_at','recorded_at'):cases.append(('event time',None,'CHECK'))
                if field=='actor':cases.append(('actor identity','','CHECK'))
                if c.get('required_guard'):cases=[(a,b,None if b is None else e) for a,b,e in cases]
                for label,bad_value,expected in cases:
                    bad=dict(values);bad[field]=bad_value
                    if field=='workspace' and values.get('subject_id') is not None and values.get('subject_type')!='session':expected='polymorphic reference'
                    if field=='subject_type' and bad_value is None and values.get('subject_id') is not None:expected='polymorphic reference'
                    if field=='occurred_at' and bad_value is None:db.create_function('foxrun_context',1,lambda k:0 if k=='import' else SCHEMA.get(k))
                    refused(table+'.'+field+' '+label,lambda:db.execute('INSERT INTO '+Q(table)+' ('+','.join(map(Q,bad))+') VALUES ('+','.join('?' for _ in bad)+')',tuple(bad.values())),expected)
                    db.create_function('foxrun_context',1,lambda k:SCHEMA.get(k))
        else:
            refused(table+' archive-only delete',lambda:db.execute('DELETE FROM '+Q(table)+' WHERE id=?',(key,)),'archive')
            other_id=f.row('commerce_accounts',source_system='amazon') if table=='amazon_accounts' else key+100000
            refused(table+' immutable hidden id',lambda:change(table,key,'id',other_id),'immutable')
            if isinstance(row.get('version'),int):refused(table+' version counter',lambda:change(table,key,'version',row['version']+2),'version')
            for c in (c for c in columns if c['table']==table):
                field=c['column'];kind=c['field_type'];choices=c.get('allowed_values')
                if choices and kind!='link':
                    bad='["not-a-choice"]' if kind=='multi-pick' else 999999 if c['sqlite_type']=='INTEGER' else 'not-a-choice'
                    expected='linked stages' if table=='people_pipelines' and field=='name' else 'linked pipeline' if table=='people_pipeline_stages' and field=='stage' else 'invalid list pick' if kind=='multi-pick' else 'CHECK'
                    if field=='workspace' and table in ('base_proposals','work_links','work_runs') and row.get('subject_id') is not None:expected='polymorphic reference'
                    refused(table+'.'+field+' choices',lambda:change(table,key,field,bad),expected)
                if kind=='boolean':refused(table+'.'+field+' boolean',lambda:change(table,key,field,2),'CHECK')
                if kind in ('json','multi-pick'):refused(table+'.'+field+' JSON',lambda:change(table,key,field,'{bad'),'malformed JSON' if kind=='multi-pick' and choices else 'CHECK')
                if kind in ('date','timestamp'):refused(table+'.'+field+' '+kind,lambda:change(table,key,field,'not-a-date'),'CHECK')
                if kind=='link' and link_target(c):
                    # The stage guard intentionally refuses before the fixed FK.
                    refused(table+'.'+field+' foreign key',lambda:change(table,key,field,999999))
            if 'status' in row and next(c for c in columns if c['table']==table and c['column']=='status').get('allowed_values') and 'canceled' in next(c for c in columns if c['table']==table and c['column']=='status')['allowed_values']:
                db.create_function('foxrun_context',1,lambda k:None if k=='reason' else SCHEMA.get(k))
                refused(table+' cancellation reason',lambda:change(table,key,'status','canceled'),'reason')
                db.create_function('foxrun_context',1,lambda k:SCHEMA.get(k))
            amounts=[c['column'] for c in columns if c['table']==table and (c['column'].endswith('_minor') or c['column']=='cost_micro')]
            if 'currency' in row and amounts:
                refused(table+' currency',lambda:db.execute('UPDATE '+Q(table)+' SET '+Q(amounts[0])+'=1,currency=NULL WHERE id=?',(key,)),'CHECK')
        # Every table has a raw-write guard, independent of its other checks.
        db.create_function('foxrun_write_allowed',0,lambda:0)
        if table not in EVENTS:refused(table+' raw update',lambda:change(table,key,pk,key),'table command')
        else:
            data=f.data(table)
            refused(table+' raw insert',lambda:db.execute('INSERT INTO '+Q(table)+' ('+','.join(map(Q,data))+') VALUES ('+','.join('?' for _ in data)+')',tuple(data.values())),'table command')
        db.create_function('foxrun_write_allowed',0,lambda:1)
    # Required new timestamps: test each trigger with import disabled, otherwise valid INSERT.
    by_type={t['object_type']:t['name'] for t in targets if t['kind']=='table' and t['name']!='amazon_accounts'}
    for c in columns:
        link=c.get('link')
        if not isinstance(link,dict) or not link.get('polymorphic'):continue
        table=c['table'];field=c['column'];type_column=link['type_column'];key=f.first(table)
        if table in EVENTS:
            data=f.data(table);data[field]=0
            refused(table+'.'+field+' positive polymorphic key',lambda:db.execute('INSERT INTO '+Q(table)+' ('+','.join(map(Q,data))+') VALUES ('+','.join('?' for _ in data)+')',tuple(data.values())),'polymorphic reference')
        else:refused(table+'.'+field+' positive polymorphic key',lambda:db.execute('UPDATE '+Q(table)+' SET '+Q(field)+'=0,'+Q(type_column)+'=? WHERE id=?',('work_tasks' if type_column=='table_name' else 'task',key)),'polymorphic reference')
        type_field=next(x for x in columns if x['table']==table and x['column']==type_column)
        typ='work_tasks' if type_column=='table_name' else next(v for v in type_field.get('allowed_values',[]) if v in by_type) if any(v in by_type for v in type_field.get('allowed_values',[])) else None
        if typ:
            if table in EVENTS:
                data=f.data(table);data[field]=999999;data[type_column]=typ
                refused(table+'.'+field+' existing polymorphic record',lambda:db.execute('INSERT INTO '+Q(table)+' ('+','.join(map(Q,data))+') VALUES ('+','.join('?' for _ in data)+')',tuple(data.values())),'polymorphic reference')
            else:
                refused(table+'.'+field+' existing polymorphic record',lambda:db.execute('UPDATE '+Q(table)+' SET '+Q(field)+'=999999,'+Q(type_column)+'=? WHERE id=?',(typ,key)),'polymorphic reference')
            linked_table=typ if type_column=='table_name' else by_type[typ]
            names={r[1] for r in db.execute('PRAGMA table_info('+Q(linked_table)+')')}
            own_names={r[1] for r in db.execute('PRAGMA table_info('+Q(table)+')')}
            if 'workspace' in names and 'workspace' in own_names and field!='target_id':
                record=f.first(linked_table);pk='seq' if linked_table in EVENTS else 'id'
                workspace=db.execute('SELECT workspace FROM '+Q(linked_table)+' WHERE '+pk+'=?',(record,)).fetchone()[0]
                wrong='sample-finance' if workspace!='sample-finance' else 'system-workspace'
                if table in EVENTS:
                    data=f.data(table);data.update({field:record,type_column:typ,'workspace':wrong})
                    refused(table+'.'+field+' approved wrong workspace',lambda:db.execute('INSERT INTO '+Q(table)+' ('+','.join(map(Q,data))+') VALUES ('+','.join('?' for _ in data)+')',tuple(data.values())),'polymorphic reference')
                else:
                    refused(table+'.'+field+' approved wrong workspace',lambda:db.execute('UPDATE '+Q(table)+' SET '+Q(field)+'=?,'+Q(type_column)+'=?,workspace=? WHERE id=?',(record,typ,wrong,key)),'polymorphic reference')
    proposal=f.first('base_proposals')
    refused('proposal actual record table',lambda:change('base_proposals',proposal,'table_name','missing-table'),'polymorphic reference')
    for c in columns:
        if not c.get('required_when','').startswith('New row.') or c['table'] in EVENTS:continue
        table=c['table'];data=f.data(table);data[c['column']]=None
        if table=='amazon_accounts':data['id']=f.row('commerce_accounts',source_system='amazon')
        db.create_function('foxrun_context',1,lambda k:0 if k=='import' else SCHEMA.get(k))
        refused(table+'.'+c['column']+' required new row',lambda:db.execute('INSERT INTO '+Q(table)+' ('+','.join(map(Q,data))+') VALUES ('+','.join('?' for _ in data)+')',tuple(data.values())),'new row requires')
        db.create_function('foxrun_context',1,lambda k:SCHEMA.get(k))
    refused('counter skips number',lambda:db.execute('UPDATE _foxrun_sequence SET value=value+2'),'sequence')
    refused('counter without event',lambda:db.execute('UPDATE _foxrun_sequence SET value=value+1'),'event')
    value=f.first('base_values')
    refused('value active flag',lambda:change('base_values',value,'active',2),'CHECK')
    data=f.data('base_receipts');data['last_seq']=None
    refused('receipt bookmark',lambda:db.execute('INSERT INTO base_receipts ('+','.join(map(Q,data))+') VALUES ('+','.join('?' for _ in data)+')',tuple(data.values())),'CHECK')
    data=f.data('work_attachments');data.update(path=None,url=None,payload=None)
    refused('attachment evidence',lambda:db.execute('INSERT INTO work_attachments ('+','.join(map(Q,data))+') VALUES ('+','.join('?' for _ in data)+')',tuple(data.values())),'CHECK')
    data=f.data('work_attachments');data.update(subject_type='page',action='published',payload='{}')
    refused('page publication version',lambda:db.execute('INSERT INTO work_attachments ('+','.join(map(Q,data))+') VALUES ('+','.join('?' for _ in data)+')',tuple(data.values())),'version payload')
    task=f.first('work_tasks')
    refused('lead reviewer identity',lambda:change('work_tasks',task,'reviewed_by',None),'CHECK')
    refused('agent reviewer',lambda:db.execute("UPDATE work_tasks SET owner='agent',reviewer=NULL WHERE id=?",(task,)),'CHECK')
    conv=f.first('people_conversations')
    refused('snoozed timestamp',lambda:db.execute("UPDATE people_conversations SET status='snoozed',snoozed_until=NULL WHERE id=?",(conv,)),'CHECK')
    link=f.first('work_links')
    refused('target type',lambda:db.execute('UPDATE work_links SET target_id=1,target_type=NULL WHERE id=?',(link,)),'new row requires target_type')
    approval=f.first('base_approvals')
    task_workspace=db.execute('SELECT workspace FROM work_tasks WHERE id=?',(task,)).fetchone()[0]
    refused('approval envelope',lambda:db.execute('INSERT INTO base_approvals(seq,workspace,subject_type,subject_id,action,actor,session,occurred_at,recorded_at,version,authorization_valid) VALUES(?,?,?,?,?,?,?,?,?,1,1)',(db.execute('SELECT value+1 FROM _foxrun_sequence').fetchone()[0],task_workspace,'task',task,'approved','fixture','fixture','2026-01-01','2026-01-01')),'CHECK')
    pipeline=f.first('people_pipelines');stage=f.first('people_pipeline_stages')
    refused('grouped pipeline stage',lambda:change('people_pipeline_stages',stage,'stage','outreach'),'linked pipeline')
    other=f.row('people_pipelines',name='creators');other_stage=f.row('people_pipeline_stages',pipeline=other,stage='outreach')
    opportunity=f.first('people_opportunities')
    refused('opportunity linked stage',lambda:db.execute('UPDATE people_opportunities SET pipeline=?,stage=? WHERE id=?',(pipeline,other_stage,opportunity)),'stage is not in pipeline')
    db.execute('UPDATE people_opportunities SET pipeline=?,stage=? WHERE id=?',(pipeline,stage,opportunity))
    refused('referenced stage pipeline',lambda:db.execute("UPDATE people_pipeline_stages SET pipeline=?,stage='outreach' WHERE id=?",(other,stage)),'linked opportunities')
    refused('pipeline name linked choices',lambda:db.execute("UPDATE people_pipelines SET name='ventures' WHERE id=?",(pipeline,)),'linked stages')
    parent=f.row('work_tasks');child=f.row('work_tasks',parent=parent)
    refused('subtask depth',lambda:f.row('work_tasks',parent=child),'standalone parent')
    refused('subtask workspace',lambda:f.row('work_tasks',parent=parent,workspace='sample-finance'),'standalone parent')
    program=f.first('work_programs');project=f.row('work_projects',program=program);program_task=f.row('work_tasks',project=project)
    program_child=f.row('work_tasks',parent=program_task,project=project)
    assert db.execute('SELECT parent FROM work_tasks WHERE id=?',(program_child,)).fetchone()[0]==program_task
    other_project=f.row('work_projects')
    change('work_tasks',program_child,'project',other_project)
    assert db.execute('SELECT project FROM work_tasks WHERE id=?',(program_child,)).fetchone()[0]==other_project
    refused('program subtask depth',lambda:f.row('work_tasks',parent=program_child),'standalone parent')
    nonamazon=f.row('commerce_accounts',source_system='shopify')
    refused('Amazon extension',lambda:f.row('amazon_accounts',id=nonamazon),'Amazon commerce account')
    from derived_guard_tests import verify as derived_verify
    tested+=derived_verify(db,blueprint)
    db.commit();db.close()
    return tested
