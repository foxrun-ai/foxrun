"""Labeled fake rows for deterministic database tests. Never use on business data."""

from __future__ import annotations

import sys as _person_sys
from pathlib import Path as _PersonPath
_person_root = next(p for p in _PersonPath(__file__).resolve().parents if (p / "base/person.py").is_file())
_person_sys.path.insert(0, str(_person_root))
from base import person as _fox_person
import hashlib
import json
from collections import defaultdict
from core import EVENTS,Q,link_target

class Fixtures:
    def __init__(self,db,targets,columns):
        self.db=db;self.targets={t['name']:t for t in targets if t['kind']=='table'};self.columns=defaultdict(list);self.serial=0
        for c in columns:self.columns[c['table']].append(c)
    def value(self,c):
        self.serial+=1;n=self.serial;f=c['column'];kind=c['field_type'];choices=c.get('allowed_values')
        if choices and kind!='link':
            if isinstance(choices,dict):return next(iter(choices.values()))[0]
            list_pick=kind=='multi-pick' or (kind=='json' and c.get('v7_type')=='list')
            return json.dumps([choices[0]]) if list_pick else choices[0]
        link=link_target(c)
        if link and kind=='link':
            row=self.db.execute('SELECT '+Q(link['column'])+' FROM '+Q(link['table'])+' LIMIT 1').fetchone()
            if row is None:self.row(link['table']);row=self.db.execute('SELECT '+Q(link['column'])+' FROM '+Q(link['table'])+' LIMIT 1').fetchone()
            return row[0]
        if isinstance(c.get('link'),dict) and c['link'].get('polymorphic'):
            type_column=c['link']['type_column'];choices=next((x.get('allowed_values') for x in self.columns[c['table']] if x['column']==type_column),None)
            typ=choices[0] if choices else 'task'
            table=next((t['name'] for t in self.targets.values() if t['object_type']==typ and t['name']!='amazon_accounts'),None)
            return self.first(table) if table else 1
        if c['sqlite_type']=='INTEGER':return 0 if kind=='boolean' else n
        if kind in ('integer','number','money','boolean'):return 0 if kind=='boolean' else n
        if kind=='date':return '2026-01-01'
        if kind=='timestamp':return '2026-01-01T00:00:00Z'
        if kind in ('json','multi-pick'):return '[]' if c.get('v7_type')=='list' or kind=='multi-pick' else '{}'
        if f=='currency':return 'USD'
        if f=='workspace':return _fox_person.workspace('system')
        return 'fixture-'+str(n)
    def data(self,table,extra=None):
        data={}
        for c in self.columns[table]:
            if c['column'] in ('id','seq'):continue
            feeder_required=c.get('required_guard',{}).get('fixture') in ('feeder','imported') and self.db.execute("SELECT foxrun_context('writer')").fetchone()[0]=='feeder'
            if c['required'] and c.get('default') is None or c.get('required_guard',{}).get('fixture')=='new' or feeder_required:
                data[c['column']]=self.value(c)
        names={c['column'] for c in self.columns[table]}
        if 'currency' in names:data['currency']='USD'
        if table=='base_capabilities':
            # Live capabilities require these conditional fields even though the columns are nullable.
            for field in ('set','runtimes'):
                if field not in data:
                    data[field]=self.value(next(c for c in self.columns[table] if c['column']==field))
        if table=='work_tasks':data.update(reviewer='lead',reviewed_by='fixture')
        if table=='work_attachments':data['path']='fixture/evidence.md'
        if table=='base_receipts':data['last_seq']=self.db.execute('SELECT value FROM _foxrun_sequence').fetchone()[0]
        if table=='base_values':data['active']=1
        if table=='base_proposals':
            data['table_name']='work_tasks';data['subject_id']=self.first('work_tasks')
            data['workspace']=self.db.execute('SELECT workspace FROM work_tasks WHERE id=?',(data['subject_id'],)).fetchone()[0]
        if table=='people_pipelines':data['name']='clients'
        if table=='people_drafts':
            data.update(text='fixture words',content_hash=hashlib.sha256(b'fixture words').hexdigest())
            # One open draft per conversation: a made-up draft gets its own conversation.
            if 'conversation' not in (extra or {}):data['conversation']=self.row('people_conversations')
        if table=='people_opportunities':
            data['stage']=self.first('people_pipeline_stages')
        if table=='people_pipeline_stages':
            name=self.db.execute('SELECT name FROM people_pipelines WHERE id=?',(data['pipeline'],)).fetchone()[0]
            c=next(c for c in self.columns[table] if c['column']=='stage');data['stage']=c['allowed_values'][name][0]
        if table in EVENTS:
            data.update(seq=self.db.execute('SELECT value+1 FROM _foxrun_sequence').fetchone()[0],actor='fixture',session='fixture',occurred_at='2026-01-01T00:00:00Z',recorded_at='2026-01-01T00:00:00Z')
            if data.get('subject_type')=='task':data['subject_id']=self.first('work_tasks')
        data.update(extra or {})
        if table=='commerce_accounts' and data.get('source_system')=='amazon':
            data['workspace']=self.db.execute("SELECT foxrun_context('workspace')").fetchone()[0]
        return data
    def row(self,table,**extra):
        if table=='amazon_accounts' and 'id' not in extra:extra['id']=self.row('commerce_accounts',source_system='amazon')
        data=self.data(table,extra)
        closed=table=='work_tasks' and data.get('status')=='done'
        if closed:data['status']='todo'
        try:
            result=self.db.execute('INSERT INTO '+Q(table)+' ('+','.join(map(Q,data))+') VALUES ('+','.join('?' for _ in data)+')',tuple(data.values())).lastrowid
            if closed:
                row=self.db.execute('SELECT workspace,reviewer,reviewed_by,version FROM work_tasks WHERE id=?',(result,)).fetchone()
                reviewer=_fox_person.name() if row['reviewer']==_fox_person.name() else row['reviewed_by']
                self.db.execute("INSERT INTO work_changes(seq,workspace,subject_type,subject_id,subject_version,action,actor,source,occurred_at,recorded_at) VALUES ((SELECT value+1 FROM _foxrun_sequence),?,'task',?,?,'verified',?,'fixture','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')",(row['workspace'],result,str(row['version']),reviewer))
                self.db.execute("UPDATE work_tasks SET status='done' WHERE id=?",(result,))
        except Exception as error:raise AssertionError('fixture '+table+' '+str(error)+' '+str(data)) from error
        return data.get('seq',data.get('id',result))
    def first(self,table):
        key='seq' if table in EVENTS else 'id';row=self.db.execute('SELECT '+key+' FROM '+Q(table)+' LIMIT 1').fetchone()
        return row[0] if row else self.row(table)
