"""Generate bad writes from the effective blueprint, including both sides of parent rules."""

from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'base/tests', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()
import json
import sqlite3
from core import EVENTS,Q,load
from fixtures import Fixtures

CONTEXT={'writer':'feeder','import':1,'workspace':'system-workspace','actor':'fixture','session':'fixture','source':'fixture','reason':'fixture'}

def verify(db,blueprint):
    targets,columns=load(blueprint);tables={t['name']:t for t in targets if t['kind']=='table'}
    f=Fixtures(db,targets,columns);counts={'required':0,'choices':0,'parent':0};tested=[]
    ctx=dict(CONTEXT)
    db.create_function('foxrun_context',1,lambda key:ctx.get(key))
    def insert(table,data):return db.execute('INSERT INTO '+Q(table)+' ('+','.join(map(Q,data))+') VALUES ('+','.join('?' for _ in data)+')',tuple(data.values()))
    def check(label,fn,bad=True,message=None):
        db.execute('SAVEPOINT derived_guard')
        try:
            try:fn()
            except (sqlite3.Error,AssertionError,ValueError) as error:
                if not bad:raise
                if message and message not in str(error):raise AssertionError(label+' refused for wrong reason: '+str(error))
                tested.append(label);return
            if bad:raise AssertionError(label+' accepted bad write')
        finally:db.execute('ROLLBACK TO derived_guard');db.execute('RELEASE derived_guard')
    def data(table):
        result=f.data(table)
        if table=='work_measure_history':result['measure']=f.row('work_measures')
        if table=='base_installs':result['module']=f.row('base_modules')
        if table=='people_pipelines':result['name']='ventures'
        if table=='people_pipeline_stages':
            pipeline=result['pipeline'];name=db.execute('SELECT name FROM people_pipelines WHERE id=?',(pipeline,)).fetchone()[0]
            choices=next(c['allowed_values'][name] for c in columns if c['table']==table and c['column']=='stage')
            result['stage']=next(v for v in choices if not db.execute('SELECT 1 FROM people_pipeline_stages WHERE pipeline=? AND stage=?',(pipeline,v)).fetchone())
        if table=='amazon_accounts':result['id']=f.row('commerce_accounts',source_system='amazon')
        return result
    for c in columns:
        table=c['table'];field=c['column']
        if table not in tables:continue
        requirement=c.get('required_guard');native=c['required']
        if not native and (not requirement or requirement.get('not_applicable')):continue
        counts['required']+=1
        if native and table not in EVENTS:
            key=f.first(table)
            check(table+'.'+field+' required',lambda:db.execute('UPDATE '+Q(table)+' SET '+Q(field)+'=NULL WHERE id=?',(key,)))
            continue
        values=data(table);ctx.update(CONTEXT)
        if requirement:
            kind=requirement['fixture']
            if kind=='new':ctx['import']=0
            elif kind=='amount':
                amount=next(x['column'] for x in columns if x['table']==table and (x['column'].endswith('_minor') or x['column']=='cost_micro'));values[amount]=1
            elif kind=='agent':ctx['writer']='agent'
            elif kind=='feeder':ctx.update(writer='feeder',source='fixture');values['source']='fixture'
            elif kind=='snoozed':values.update(status='snoozed',snoozed_until='2026-01-01T00:00:00Z')
            elif kind=='creator':
                creator=db.execute("SELECT id FROM people_pipelines WHERE name='creators'").fetchone()
                creator=creator[0] if creator else f.row('people_pipelines',name='creators')
                stage=db.execute("SELECT id FROM people_pipeline_stages WHERE pipeline=? AND stage='outreach'",(creator,)).fetchone()
                stage=stage[0] if stage else f.row('people_pipeline_stages',pipeline=creator,stage='outreach')
                values.update(pipeline=creator,stage=stage,round_key='fixture-round',round_name='Fixture round');ctx['import']=0
            elif kind=='imported':ctx.update(writer='feeder',source='fixture');values['source_system']='fixture'
            elif kind=='target':values.update(target_type='task',target_id=f.first('work_tasks'))
            elif kind=='reviewer':values.update(reviewer='lead',reviewed_by='fixture')
        # Establish the complete write is valid before removing exactly one field.
        check(table+'.'+field+' control',lambda:insert(table,values),False)
        bad=dict(values);bad[field]=None
        check(table+'.'+field+' required',lambda:insert(table,bad))
        ctx.update(CONTEXT)
    for c in columns:
        table=c['table'];field=c['column'];choices=c.get('allowed_values')
        if table not in tables or not choices:continue
        counts['choices']+=1;ctx.update(CONTEXT)
        if table in EVENTS:
            values=data(table);check(table+'.'+field+' choice control',lambda:insert(table,values),False)
            values[field]='not-a-choice';check(table+'.'+field+' choices',lambda:insert(table,values))
        else:
            key=f.first(table)
            bad=999999 if c['sqlite_type']=='INTEGER' else '["not-a-choice"]' if c['field_type']=='multi-pick' else 'not-a-choice'
            check(table+'.'+field+' choices',lambda:db.execute('UPDATE '+Q(table)+' SET '+Q(field)+'=? WHERE id=?',(bad,key)))
            if c['field_type']=='multi-pick':
                for value in ('[null]',json.dumps([choices[0],None])):
                    check(table+'.'+field+' NULL item update',lambda:db.execute('UPDATE '+Q(table)+' SET '+Q(field)+'=? WHERE id=?',(value,key)))
                    values=data(table);values[field]=value;check(table+'.'+field+' NULL item insert',lambda:insert(table,values))
                for value in (json.dumps([choices[0]]),'[]',None):
                    check(table+'.'+field+' valid list or whole NULL',lambda:db.execute('UPDATE '+Q(table)+' SET '+Q(field)+'=? WHERE id=?',(value,key)),bool(value is None and c['required']))
                    values=data(table);values[field]=value;check(table+'.'+field+' valid list insert',lambda:insert(table,values),bool(value is None and c['required']))
    # Imported unknown state remains unknown. New writes still satisfy their predicates.
    ctx.update(CONTEXT)
    for table,field in [('work_bugs','status'),('base_proposals','status'),('people_opportunities','stage'),('treasury_cancellations','status'),('treasury_scheduled_transactions','status')]:
        values=data(table);values[field]=None
        check(table+'.'+field+' historical NULL',lambda:insert(table,values),False)
    values=data('base_approvals');values.update(occurred_at=None,subject_id=None,version=None,authorization_valid=0)
    check('historical incomplete approval cannot authorize',lambda:insert('base_approvals',values),False)
    values['authorization_valid']=1
    check('historical incomplete approval refused authorization',lambda:insert('base_approvals',values))
    for table in EVENTS:
        values=data(table);values['occurred_at']=None
        check(table+' historical unknown source occurrence',lambda:insert(table,values),False)
    for c in columns:
        rule=c.get('required_guard')
        if not rule or not rule.get('not_applicable'):continue
        assert rule['predicate']=='0'
        values=data(c['table']);values[c['column']]=None
        check(c['table']+'.'+c['column']+' amount condition has no amount fields',lambda:insert(c['table'],values),False)
    # All mutations and their predicates come from the same source rules as the compiler.
    ctx.update(CONTEXT)
    program=f.first('work_programs');pp=f.row('work_projects',program=program);parent_project=f.row('work_projects');child_project=f.row('work_projects')
    parent=f.row('work_tasks',project=parent_project);child=f.row('work_tasks',parent=parent,project=child_project)
    params={'parent':parent,'child':child,'other':f.row('work_tasks'),'wrong_workspace':f.row('work_tasks',workspace='sample-finance'),'program':program,'program_project':pp,'program_task':f.row('work_tasks',project=pp),'parent_project':parent_project,'child_project':child_project}
    for t in targets:
        for rule in t.get('parent_guards',[]):
            for statement in rule['cases']:
                counts['parent']+=1
                permits_program = rule['name'] in ('program','subtask_program')
                check(t['name']+'.'+rule['name']+' '+statement,lambda:db.execute(statement,params),bad=not permits_program)
    db.execute('UPDATE work_tasks SET project=:program_project WHERE id=:child',params)
    assert db.execute('SELECT project FROM work_tasks WHERE id=:child',params).fetchone()[0]==pp
    db.execute('UPDATE work_tasks SET project=:child_project WHERE id=:child',params)
    assert db.execute('SELECT project FROM work_tasks WHERE id=:child',params).fetchone()[0]==child_project
    # View fields also occur in the blueprint. SQLite refuses their writes outright.
    view_names={t['name'] for t in targets if t['kind']=='view'}
    for c in columns:
        if c['table'] not in view_names:continue
        table=c['table'];field=c['column']
        assert field in {r[1] for r in db.execute('PRAGMA table_info('+Q(table)+')')},table+'.'+field+' view field missing'
        if c['required'] or c.get('required_when') or c.get('conditional_required'):
            counts['required']+=1
            check(table+'.'+field+' read-only required',lambda:db.execute('INSERT INTO '+Q(table)+' ('+Q(field)+') VALUES (NULL)'),message='cannot modify')
        if c.get('allowed_values'):
            counts['choices']+=1
            check(table+'.'+field+' read-only choice',lambda:db.execute('INSERT INTO '+Q(table)+' ('+Q(field)+') VALUES (?)',('not-a-choice',)),message='cannot modify')
    db.create_function('foxrun_context',1,lambda k:CONTEXT.get(k))
    for family,count in counts.items():print('PASS blueprint-derived '+family+' guard count '+str(count))
    return tested
