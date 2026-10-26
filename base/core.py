#!/usr/bin/env python3
"""Build the blueprint database and enforce its table commands. Standard library only."""
from __future__ import annotations

import sys as _person_sys
from pathlib import Path as _PersonPath
_person_root = next(p for p in _PersonPath(__file__).resolve().parents if (p / "base/person.py").is_file())
_person_sys.path.insert(0, str(_person_root))
from base import person as _fox_person
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import re
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str((Path(__file__).resolve().parent / '../work')))
sys.path.insert(0, str(Path(__file__).resolve().parent / '../events'))
from history_actions import database_action, creation_action

BLUEPRINT = '13'  # The blueprint version the files, the dictionary, and the pages name.
EVENTS = ('work_changes', 'work_comments', 'work_attachments', 'base_approvals', 'base_receipts')
MODEL = ('base_modules', 'base_object_types', 'base_fields', '_foxrun_sequence')
Q = lambda x: '"' + x.replace('"', '""') + '"'
S = lambda x: 'NULL' if x is None else str(int(x)) if isinstance(x,(bool,int)) else str(x) if isinstance(x,float) else "'" + str(x).replace("'", "''") + "'"

def addon_blueprints(home, packs):
    """The model folders of installed add-ons (g-business-packs-do-not-ship, g-people-ships-with-small-talk).

    The core blueprint holds only the core model. A pack or add-on that owns more tables keeps
    their rows in its own blueprint/ folder, at <home>/modules/<pack>/blueprint or <home>/<pack>/blueprint.
    """
    found=[]
    for pack in sorted(packs):
        for folder in (Path(home)/'modules'/pack/'blueprint',Path(home)/pack/'blueprint'):
            if (folder/('target-v'+BLUEPRINT+'.jsonl')).is_file():found.append(folder);break
    return found

def load(blueprint, configure_person=True, addons=()):
    p=Path(blueprint)
    targets=[json.loads(s) for s in (p/('target-v'+BLUEPRINT+'.jsonl')).read_text().splitlines()]
    columns=[json.loads(s) for s in (p/('columns-v'+BLUEPRINT+'.jsonl')).read_text().splitlines()]
    # An add-on's rows join the core rows before the rules apply, so its rules can name its own tables.
    added_rules=[]
    for folder in addons:
        folder=Path(folder)
        if folder.resolve()==p.resolve():continue  # the core blueprint is never its own add-on
        targets+=[json.loads(s) for s in (folder/('target-v'+BLUEPRINT+'.jsonl')).read_text().splitlines() if s]
        columns+=[json.loads(s) for s in (folder/('columns-v'+BLUEPRINT+'.jsonl')).read_text().splitlines() if s]
        if (folder/'implementation-rules.json').exists():added_rules.append(json.loads((folder/'implementation-rules.json').read_text()))
    extension=p/'dictionary-extension.json'
    if extension.exists():
        additions=json.loads(extension.read_text())
        for row in columns:
            if row['table']=='base_fields' and row['column']=='field_type':
                row['allowed_values']=list(dict.fromkeys(row['allowed_values']+['map']))
        columns+=additions['columns']
    rules=p/'implementation-rules.json'
    if rules.exists():
        definitions=json.loads(rules.read_text())
        for extra in added_rules:
            for key,rows in extra.items():
                if isinstance(rows,list):definitions[key]=definitions.get(key,[])+rows
        for addition in definitions['choice_additions']:
            c=next(c for c in columns if c['table']==addition['table'] and c['column']==addition['column'])
            c['allowed_values']=list(dict.fromkeys(c['allowed_values']+addition['allowed_values']))
            c['ruling']=list(dict.fromkeys(c.get('ruling',[])+addition['rulings']))
        for requirement in definitions.get('required_guards',[]):
            c=next(c for c in columns if c['table']==requirement['table'] and c['column']==requirement['column'])
            c['required_guard']=requirement
        for guard in definitions.get('parent_guards',[]):
            t=next(t for t in targets if t['name']==guard['table'])
            t.setdefault('parent_guards',[]).append(guard)
        for guard in definitions.get('state_guards',[]):
            t=next(t for t in targets if t['name']==guard['table'])
            t.setdefault('state_guards',[]).append(guard)
        for guard in definitions.get('value_set_guards',[]):
            c=next(c for c in columns if c['table']==guard['table'] and c['column']==guard['column'])
            c['value_set_guard']=guard
    table_names={t['name'] for t in targets if t['kind']=='table'}
    for c in columns:
        if c['table'] not in table_names:continue
        condition=c.get('required_when') or c.get('conditional_required')
        if not condition:continue
        guard=c.get('required_guard')
        if not guard or guard['source_requirement']!=condition:
            raise ValueError('Uncompiled conditional requirement: '+c['table']+'.'+c['column'])
        if guard.get('not_applicable') and any(x['table']==c['table'] and (x['column'].endswith('_minor') or x['column']=='cost_micro') for x in columns):
            raise ValueError('Inactive amount requirement now has an amount field: '+c['table'])
    if configure_person:
        return _fox_person.configure_values(targets), _fox_person.configure_values(columns)
    return targets, columns

def connect(path, context=None, readonly=False):
    if readonly:
        uri=Path(path).resolve().as_uri()+'?mode=ro'
        db=_fox_person.connect(uri,uri=True)
        try:
            db.execute('SELECT count(*) FROM sqlite_schema').fetchone()
        except sqlite3.OperationalError as error:
            db.close()
            wal=Path(str(path)+'-wal')
            if 'unable to open database file' not in str(error) or (wal.exists() and wal.stat().st_size):
                raise
            # A closed, checkpointed copy has no pending WAL to ignore.
            db=_fox_person.connect(uri+'&immutable=1',uri=True)
    else:
        db=_fox_person.connect(path)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA busy_timeout=10000')
    ctx=context or {}
    ctx.setdefault("import_source", "data.db")
    # Batch 24, 2.4: no schema/import pair on a database containing record rows.
    # There is no made-up-data escape flag. Tests use the guarded feeder context.
    if not readonly and ctx.get('writer')=='schema' and ctx.get('import'):
        records=[r[0] for r in db.execute("SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'") if r[0] not in MODEL]
        if any(db.execute('SELECT 1 FROM '+Q(name)+' LIMIT 1').fetchone() for name in records):
            db.close()
            raise ValueError('schema with import is refused on a database that holds record rows')
    db.create_function('foxrun_write_allowed',0,lambda: int(bool(context)))
    db.create_function('foxrun_context',1,lambda key: ctx.get(key))
    db.create_function('foxrun_action',4,derive_action)
    # The explicit flag distinguishes historical imports from new feeder rows.
    db.create_function('foxrun_creation_action',2,lambda kind,status: creation_action(kind,status,bool(ctx.get('historical_import'))))
    # The hash guard of a draft reads this. A writer connection without it cannot write a draft's text.
    db.create_function('foxrun_sha256',1,lambda text: None if text is None else hashlib.sha256(str(text).encode('utf-8')).hexdigest(),deterministic=True)
    return db

def derive_action(object_type, field, old, new):
    return database_action(object_type, field, old, new)

def hashed(target,data,old=None):
    # The hash is always the sha256 of the exact UTF-8 text. The command writes it; a hash that differs is refused.
    for hash_field,text_field in (target.get('hash_columns') or {}).items():
        if text_field not in data and hash_field not in data:continue
        text=data[text_field] if text_field in data else (old[text_field] if old is not None else None)
        expected=None if text is None else hashlib.sha256(text.encode('utf-8')).hexdigest()
        if hash_field in data and data[hash_field]!=expected:raise ValueError(hash_field+' must be the sha256 of '+text_field)
        if old is None or old[hash_field]!=expected:data[hash_field]=expected

def field_sql(c, primary):
    name=Q(c['column']);sql=name+' '+c['sqlite_type']
    if primary==[c['column']]:sql+=' PRIMARY KEY'
    elif c['required']:sql+=' NOT NULL'
    if 'default' in c and c['default'] is not None:sql+=' DEFAULT '+S(c['default'])
    if c['field_type']=='boolean':sql+=' CHECK ('+name+' IN (0,1))'
    list_pick = c['field_type']=='multi-pick' or (c['field_type']=='json' and c.get('v7_type')=='list')
    if c['column']=='workspace':sql+=' CHECK (foxrun_workspace_allowed('+name+(',1' if c.get('workspace_scope')=='portfolio' else '')+'))'
    if c.get('allowed_values') and c['column']!='workspace' and c['field_type']!='link' and not list_pick:
        choices=c['allowed_values']
        if isinstance(choices,dict):choices=list(dict.fromkeys(v for group in choices.values() for v in group))
        sql+=' CHECK ('+name+' IN ('+','.join(S(v) for v in choices)+'))'
    if c['field_type'] in ('json','multi-pick'):
        sql+=' CHECK ('+name+' IS NULL OR json_valid('+name+'))'
        if c.get('v7_type')=='list' or c['field_type']=='multi-pick':
            sql+=' CHECK ('+name+" IS NULL OR json_type("+name+")='array')"
    if c['field_type']=='date':sql+=' CHECK ('+name+' IS NULL OR (julianday('+name+') IS NOT NULL AND date('+name+')='+name+'))'
    if c['field_type']=='timestamp':sql+=' CHECK ('+name+' IS NULL OR julianday('+name+') IS NOT NULL)'
    return sql

def link_target(c):
    link=c.get('link')
    if isinstance(link,dict) and 'table' in link:return link
    if isinstance(link,str):
        match=re.fullmatch(r'([a-z_]+)\(([^)]+)\)',link)
        if match:return {'table':match[1],'column':match[2].split(',')[-1]}
    return None

def sql_schema(targets, columns):
    by=defaultdict(list)
    for c in columns:by[c['table']].append(c)
    tables=[t for t in targets if t['kind']=='table']
    statements=['PRAGMA foreign_keys=ON;']
    for t in tables:
        name=t['name'];cols=by[name];names={c['column'] for c in cols}
        parts=[]
        for c in cols:parts.append(field_sql(c,t['primary_key']))
        if len(t['primary_key'])>1:parts.append('PRIMARY KEY ('+','.join(map(Q,t['primary_key']))+')')
        rename={c.get('v7_column'):c['column'] for c in cols if c.get('v7_column')}
        rename.update({'supersedes':'replaces','storage_name':'location','ord':'sort_order','checker':'reviewed_by','check_by':'reviewer','checked_by':'reviewed_by','deadline':'due_on','due_date':'due_on'})
        for old_key in t.get('unique_keys',[]):
            key=[rename.get(k,k) for k in old_key]
            assert set(key)<=names,(name,key)
            parts.append('UNIQUE ('+','.join(map(Q,key))+')')
        for c in cols:
            if link_target(c) and c['field_type']=='link':
                link=link_target(c)
                parts.append('FOREIGN KEY ('+Q(c['column'])+') REFERENCES '+Q(link['table'])+'('+Q(link['column'])+') ON UPDATE RESTRICT ON DELETE RESTRICT')
        parts+=t.get('checks_sql',[])
        amounts=[c['column'] for c in cols if c['column'].endswith('_minor') or c['column']=='cost_micro']
        if 'currency' in names and amounts:
            parts.append('CHECK (('+ ' AND '.join(Q(x)+' IS NULL' for x in amounts)+") OR coalesce(length(trim(currency)),0)>0)")
        if name=='people_conversations':parts.append("CHECK (status IS NOT 'snoozed' OR coalesce(length(trim(snoozed_until)),0)>0)")
        if name=='work_tasks':
            # NULL is governed by the required trigger, including the one settled insert exception.
            parts.append("CHECK (reviewer IS NOT 'lead' OR reviewed_by IS NULL OR coalesce(length(trim(reviewed_by)),0)>0)")
            parts.append("CHECK (owner IS NULL OR lower(owner)='@person@' OR reviewer IS NOT NULL)")
        if name=='work_links':parts.append('CHECK (target_id IS NULL OR target_type IS NOT NULL)')
        if name in EVENTS:
            parts.append('CHECK (recorded_at IS NOT NULL)')
        if name=='base_approvals':
            parts.append('CHECK (authorization_valid=0 OR (action=\'approved\' AND version IS NOT NULL AND subject_id IS NOT NULL AND approved_sha256 IS NOT NULL AND length(approved_sha256)=64 AND approved_sha256 NOT GLOB \'*[^0-9a-f]*\' AND envelope_ref IS NOT NULL AND go_word=1))')
        statements.append('CREATE TABLE '+Q(name)+' (\n  '+',\n  '.join(parts)+'\n) STRICT;')
        for i,index in enumerate(t.get('indexes',[])):
            if set(index)<=names:statements.append('CREATE INDEX '+Q(name+'_link_'+str(i))+' ON '+Q(name)+'('+','.join(map(Q,index))+');')
    statements.append('CREATE TABLE "_foxrun_sequence" ("id" INTEGER PRIMARY KEY CHECK(id=1), "value" INTEGER NOT NULL CHECK(value>=0)) STRICT;')
    return _fox_person.render_sql('\n\n'.join(statements)+'\n')

def guard_sql(targets,columns):
    by=defaultdict(list)
    for c in columns:by[c['table']].append(c)
    tables=[t for t in targets if t['kind']=='table']
    sql=[]
    by_type={}
    for t in tables:
        if t['name']=='amazon_accounts':continue  # commerce_accounts owns the shared account id.
        by_type[t['object_type']]=t
    for name in [t['name'] for t in tables]+['_foxrun_sequence']:
        for op in ('INSERT','UPDATE','DELETE'):
            if name in EVENTS and op!='INSERT':
                body="SELECT RAISE(ABORT,'event table is append-only');"
            elif op=='DELETE':body="SELECT RAISE(ABORT,'archive rows; deletes are refused');"
            else:body="SELECT CASE WHEN foxrun_write_allowed()<>1 THEN RAISE(ABORT,'use the table command') END;"
            sql.append('CREATE TRIGGER '+Q(name+'_guard_'+op.lower())+' BEFORE '+op+' ON '+Q(name)+' BEGIN '+body+' END;')
    # Batch 24, 2.3: definitions only, including on an empty database after guards are installed.
    for t in tables:
        if t['name'] in MODEL:continue
        for op in ('INSERT','UPDATE'):
            sql.append('CREATE TRIGGER '+Q(t['name']+'_schema_definitions_only_'+op.lower())+' BEFORE '+op+' ON '+Q(t['name'])+" WHEN foxrun_context('writer')='schema' BEGIN SELECT RAISE(ABORT,'the schema writer changes definitions only'); END;")
    for name in EVENTS:
        sql.append('CREATE TRIGGER '+Q(name+'_writer')+' BEFORE INSERT ON '+Q(name)+" WHEN foxrun_context('writer') IS NULL OR (foxrun_context('writer')='agent' AND coalesce(length(trim(NEW.session)),0)=0) OR (foxrun_context('writer') IN ('feeder','cron') AND coalesce(length(trim(NEW.source)),0)=0) BEGIN SELECT RAISE(ABORT,'writer requires session or feeder source'); END;")
        sql.append('CREATE TRIGGER '+Q(name+'_seq_insert')+' BEFORE INSERT ON '+Q(name)+" BEGIN SELECT CASE WHEN NEW.seq<>(SELECT value+1 FROM _foxrun_sequence WHERE id=1) THEN RAISE(ABORT,'sequence must be allocated by the database') END; END;")
        sql.append('CREATE TRIGGER '+Q(name+'_seq_advance')+' AFTER INSERT ON '+Q(name)+' BEGIN UPDATE _foxrun_sequence SET value=NEW.seq WHERE id=1; END;')
    sql.append("CREATE TRIGGER _foxrun_sequence_monotonic BEFORE UPDATE ON _foxrun_sequence WHEN NEW.id<>OLD.id OR NEW.value<>OLD.value+1 BEGIN SELECT RAISE(ABORT,'sequence only advances by one'); END;")
    present=' OR '.join('EXISTS(SELECT 1 FROM '+Q(name)+' WHERE seq=NEW.value)' for name in EVENTS)
    sql.append("CREATE TRIGGER _foxrun_sequence_event BEFORE UPDATE ON _foxrun_sequence WHEN NOT ("+present+") BEGIN SELECT RAISE(ABORT,'sequence requires its appended event'); END;")
    for t in tables:
        name=t['name'];cols=by[name];names={c['column'] for c in cols}
        if 'status' in names:
            for op in ('INSERT','UPDATE'):
                sql.append('CREATE TRIGGER '+Q(name+'_cancellation_'+op.lower())+' BEFORE '+op+' ON '+Q(name)+" WHEN NEW.status='canceled' AND coalesce(length(trim(foxrun_context('reason'))),0)=0 BEGIN SELECT RAISE(ABORT,'canceled requires a reason'); END;")
        for c in cols:
            if (c['field_type']=='multi-pick' or (c['field_type']=='json' and c.get('v7_type')=='list')) and (c.get('allowed_values') or c['column']=='workspace_tags'):
                value='NEW.'+Q(c['column'])
                if c['field_type']=='json':
                    # Let the JSON CHECK reject malformed text before the list-value guard parses it.
                    value='CASE WHEN json_valid('+value+') THEN '+value+" ELSE '[]' END"
                test='EXISTS (SELECT 1 FROM json_each('+value+') WHERE value IS NULL OR value NOT IN ('+','.join(map(S,c.get('allowed_values') or []))+'))'
                if c['column']=='workspace_tags':
                    test='EXISTS (SELECT 1 FROM json_each('+value+') WHERE value IS NULL OR NOT foxrun_workspace_allowed(value))'
                for op in ('INSERT','UPDATE'):
                    sql.append('CREATE TRIGGER '+Q(name+'_'+c['column']+'_'+op.lower())+' BEFORE '+op+' ON '+Q(name)+" WHEN "+test+" BEGIN SELECT RAISE(ABORT,'invalid list pick'); END;")
            rule=c.get('value_set_guard')
            if rule:
                # A new write names values of its value set. An import keeps its source list.
                field='NEW.'+Q(c['column'])
                member='EXISTS(SELECT 1 FROM base_values v WHERE v."set"='+S(rule['set'])+' AND v.value=j.value AND v.active=1)'
                bad='CASE WHEN json_valid('+field+') AND json_type('+field+")='array' THEN json_array_length("+field+')<'+str(int(rule['minimum']))+' OR EXISTS(SELECT 1 FROM json_each('+field+') j WHERE j.value IS NULL OR NOT '+member+') ELSE 0 END'
                for op in rule['operations']:
                    fields=' OF '+Q(c['column']) if op=='UPDATE' else ''
                    sql.append('CREATE TRIGGER '+Q(name+'_'+c['column']+'_value_set_'+op.lower())+' BEFORE '+op+fields+' ON '+Q(name)+' WHEN ('+rule['predicate']+') AND '+field+' IS NOT NULL AND '+bad+' BEGIN SELECT RAISE(ABORT,'+S(rule['message'])+'); END;')
            link=c.get('link')
            if isinstance(link,dict) and link.get('polymorphic'):
                type_column=link['type_column'];tests=[]
                for typ,linked in by_type.items():
                    key=linked['primary_key'][0];target_cols={x['column'] for x in by[linked['name']]}
                    type_value=linked['name'] if type_column=='table_name' else typ
                    scope=' AND r.workspace=NEW.workspace' if 'workspace' in target_cols and 'workspace' in names and c['column']!='target_id' else ''
                    tests.append('(NEW.'+Q(type_column)+'='+S(type_value)+' AND NOT EXISTS(SELECT 1 FROM '+Q(linked['name'])+' r WHERE r.'+Q(key)+'=NEW.'+Q(c['column'])+scope+'))')
                predicate='NEW.'+Q(c['column'])+' IS NOT NULL AND (NEW.'+Q(type_column)+' IS NULL OR NEW.'+Q(c['column'])+'<=0 OR '+' OR '.join(tests)+')'
                if type_column=='table_name':
                    allowed_tables=[t['name'] for t in tables if t['name'] not in EVENTS]
                    predicate='('+predicate+') OR NEW.table_name NOT IN ('+','.join(map(S,allowed_tables))+')'
                if c['column']=='workspace_tags':
                    test='EXISTS (SELECT 1 FROM json_each('+value+') WHERE value IS NULL OR NOT foxrun_workspace_allowed(value))'
                for op in ('INSERT','UPDATE'):
                    sql.append('CREATE TRIGGER '+Q(name+'_'+c['column']+'_reference_'+op.lower())+' BEFORE '+op+' ON '+Q(name)+' WHEN '+predicate+" BEGIN SELECT RAISE(ABORT,'polymorphic reference must exist in its subject workspace'); END;")
        for c in cols:
            requirement=c.get('required_guard')
            if not requirement:continue
            for op in requirement['operations']:
                fields=' OF '+','.join(map(Q,requirement.get('update_columns',[c['column']]))) if op=='UPDATE' and (requirement['fixture']=='new' or requirement.get('update_columns')) else ''
                predicate='('+requirement['predicate']+') AND NEW.'+Q(c['column'])+' IS NULL'
                if op=='INSERT' and requirement.get('insert_exception'):
                    predicate+=' AND NOT coalesce(('+requirement['insert_exception']['predicate']+'),0)'
                sql.append('CREATE TRIGGER '+Q(name+'_'+c['column']+'_required_'+op.lower())+' BEFORE '+op+fields+' ON '+Q(name)+' WHEN '+predicate+" BEGIN SELECT RAISE(ABORT,'new row requires "+c['column']+"'); END;")
        for rule in t.get('parent_guards',[]):
            for op in rule['operations']:
                sql.append('CREATE TRIGGER '+Q(name+'_parent_'+rule['name']+'_'+op.lower())+' BEFORE '+op+' ON '+Q(name)+' WHEN '+rule['predicate']+' BEGIN SELECT RAISE(ABORT,'+S(rule['message'])+'); END;')
        for rule in t.get('state_guards',[]):
            for op in rule['operations']:
                predicate=rule['predicate']
                if op=='INSERT' and rule.get('insert_exception'):
                    predicate='('+predicate+') AND NOT coalesce(('+rule['insert_exception']['predicate']+'),0)'
                sql.append('CREATE TRIGGER '+Q(name+'_state_'+rule['name']+'_'+op.lower())+' BEFORE '+op+' ON '+Q(name)+' WHEN '+predicate+' BEGIN SELECT RAISE(ABORT,'+S(rule['message'])+'); END;')
        reset=t.get('review_reset')
        if reset:
            # A review covers the line it saw. A change by someone who does not review in the same write empties it.
            review=Q(reset['review_column']);moved=' OR '.join('NEW.'+Q(f)+' IS NOT OLD.'+Q(f) for f in reset['columns'])
            sql.append('CREATE TRIGGER '+Q(name+'_review_reset')+' AFTER UPDATE OF '+','.join(map(Q,reset['columns']))+' ON '+Q(name)+' WHEN OLD.'+review+' IS NOT NULL AND NEW.'+review+' IS OLD.'+review+' AND ('+moved+') BEGIN UPDATE '+Q(name)+' SET '+review+'=NULL WHERE id=NEW.id; END;')
        if name in EVENTS:continue
        if 'id' not in names:raise ValueError('No hidden id: '+name)
        scope='NEW.workspace' if 'workspace' in names else "foxrun_context('workspace')"
        event_fields='seq,workspace,subject_type,subject_id,field,old_value,new_value,action,actor,session,source,occurred_at,recorded_at,subject_version,summary,refs'
        context=["foxrun_context('actor')","foxrun_context('session')","foxrun_context('source')","strftime('%Y-%m-%dT%H:%M:%fZ','now')","strftime('%Y-%m-%dT%H:%M:%fZ','now')"]
        ver='CAST(NEW.version AS TEXT)' if 'version' in names else 'NULL'
        def event(field,old,new,action,refs='NULL'):
            vals=['(SELECT value+1 FROM _foxrun_sequence WHERE id=1)',scope,S(t['object_type']),'NEW.id',field,old,new,action]+context+[ver,"foxrun_context('reason')",refs]
            return 'INSERT INTO work_changes ('+event_fields+') VALUES ('+','.join(vals)+');'
        states=[field for field in t.get('state_write_columns',[]) if field in names]
        initial='json_object('+','.join(S(f)+',CAST(NEW.'+Q(f)+' AS TEXT)' for f in states)+')'
        birth='foxrun_creation_action('+S(t['object_type'])+','+('NEW.status' if 'status' in names else 'NULL')+')'
        create=event('NULL','NULL','NULL',birth,"json_array(json_object('initial',"+initial+"))")
        # A feeder records its batch in work_runs, not one birth per source row.
        if t.get('database_type') not in ('mirror','trend'):
            sql.append('CREATE TRIGGER '+Q(name+'_created')+' AFTER INSERT ON '+Q(name)+" WHEN foxrun_context('writer') IS NOT 'schema' BEGIN "+create+' END;')
        # Approval and send checks also consume these exact proof changes.
        proof_fields={'people_drafts': tuple(c['column'] for c in cols),
                      'people_draft_facts': tuple(c['column'] for c in cols),
                      'people_messages': ('source_message_id',)}.get(name,())
        tracked=set(states)|set(proof_fields)
        for c in cols:
            field=c['column']
            if field not in tracked or field in ('id','version','updated_at'):continue
            action='foxrun_action('+S(t['object_type'])+','+S(field)+',CAST(OLD.'+Q(field)+' AS TEXT),CAST(NEW.'+Q(field)+' AS TEXT))'
            update=event(S(field),'CAST(OLD.'+Q(field)+' AS TEXT)','CAST(NEW.'+Q(field)+' AS TEXT)',action)
            proof=" AND EXISTS(SELECT 1 FROM people_drafts d WHERE d.sent_message=NEW.id AND d.status='sent')" if name=='people_messages' else ''
            sql.append('CREATE TRIGGER '+Q(name+'_'+field+'_changed')+' AFTER UPDATE OF '+Q(field)+' ON '+Q(name)+' WHEN OLD.'+Q(field)+' IS NOT NEW.'+Q(field)+proof+" AND foxrun_context('writer') IS NOT 'schema' BEGIN "+update+' END;')
        sql.append('CREATE TRIGGER '+Q(name+'_id_immutable')+' BEFORE UPDATE OF id ON '+Q(name)+" WHEN NEW.id<>OLD.id BEGIN SELECT RAISE(ABORT,'hidden id is immutable'); END;")
        if any(c['column']=='version' and c['sqlite_type']=='INTEGER' for c in cols):
            sql.append('CREATE TRIGGER '+Q(name+'_version')+' BEFORE UPDATE OF version ON '+Q(name)+" WHEN NEW.version<>OLD.version+1 BEGIN SELECT RAISE(ABORT,'version only advances by one'); END;")
            named=t.get('version_columns')
            if named:
                # The version names these fields. No other change moves it.
                same=' AND '.join('NEW.'+Q(f)+' IS OLD.'+Q(f) for f in named)
                sql.append('CREATE TRIGGER '+Q(name+'_version_columns')+' BEFORE UPDATE OF version ON '+Q(name)+' WHEN NEW.version IS NOT OLD.version AND '+same+" BEGIN SELECT RAISE(ABORT,'version advances only when "+' or '.join(named)+" changes'); END;")
                # And the other way: a change of these fields always moves the version, so a text that is changed and changed back is a new version.
                # A yes for the old number never matches again. A load of old history writes the versions of its source.
                moved=' OR '.join('NEW.'+Q(f)+' IS NOT OLD.'+Q(f) for f in named)
                sql.append('CREATE TRIGGER '+Q(name+'_version_moves')+' BEFORE UPDATE OF '+','.join(map(Q,named))+' ON '+Q(name)+" WHEN coalesce(foxrun_context('import'),0)=0 AND NEW.version IS OLD.version AND ("+moved+") BEGIN SELECT RAISE(ABORT,'a change of "+' or '.join(named)+" advances the version'); END;")
        for hash_field,text_field in (t.get('hash_columns') or {}).items():
            # The hash is always the sha256 of the text. A load of old history keeps the hash of its source.
            for op,fields in (('INSERT',''),('UPDATE',' OF '+Q(text_field)+','+Q(hash_field))):
                sql.append('CREATE TRIGGER '+Q(name+'_'+hash_field+'_hash_'+op.lower())+' BEFORE '+op+fields+' ON '+Q(name)+" WHEN coalesce(foxrun_context('import'),0)=0 AND NEW."+Q(hash_field)+' IS NOT foxrun_sha256(NEW.'+Q(text_field)+") BEGIN SELECT RAISE(ABORT,'"+hash_field+' must be the sha256 of '+text_field+"'); END;")
        replace=t.get('family_replace')
        if replace:
            # A later version of a family replaces its open earlier versions in the same write. A load of old history sets its own statuses.
            family=Q(replace['family'])
            sql.append('CREATE TRIGGER '+Q(name+'_family_replace')+' AFTER INSERT ON '+Q(name)+" WHEN coalesce(foxrun_context('import'),0)=0 BEGIN UPDATE "+Q(name)+' SET status='+S(replace['status'])+' WHERE '+family+'=NEW.'+family+' AND version<NEW.version AND status IN ('+','.join(map(S,replace['open']))+'); END;')
    # Cross-table guards of add-on tables run only when the build has those tables (People ships with Small Talk).
    built={t['name'] for t in tables}
    people={'people_opportunities','people_pipeline_stages','people_pipelines'}<=built
    # G002 is included in property triggers even though v10 omitted its write_contract.
    amazon={'amazon_accounts','commerce_accounts'}<=built
    for op in ('INSERT','UPDATE'):
        if people:
            sql.append('CREATE TRIGGER '+Q('people_opportunities_stage_pipeline_'+op.lower())+' BEFORE '+op+" ON people_opportunities WHEN NEW.stage IS NOT NULL AND NOT EXISTS(SELECT 1 FROM people_pipeline_stages WHERE id=NEW.stage AND pipeline=NEW.pipeline) BEGIN SELECT RAISE(ABORT,'stage is not in pipeline'); END;")
            groups=next(c['allowed_values'] for c in columns if c['table']=='people_pipeline_stages' and c['column']=='stage')
            valid=' OR '.join('(p.name='+S(pipeline)+' AND NEW.stage IN ('+','.join(map(S,choices))+'))' for pipeline,choices in sorted(groups.items()))
            sql.append('CREATE TRIGGER '+Q('people_pipeline_stages_choice_'+op.lower())+' BEFORE '+op+' ON people_pipeline_stages WHEN NOT EXISTS(SELECT 1 FROM people_pipelines p WHERE p.id=NEW.pipeline AND ('+valid+")) BEGIN SELECT RAISE(ABORT,'stage is not allowed by its linked pipeline'); END;")
        if amazon:
            sql.append('CREATE TRIGGER '+Q('amazon_accounts_amazon_'+op.lower())+' BEFORE '+op+" ON amazon_accounts WHEN NOT EXISTS(SELECT 1 FROM commerce_accounts WHERE id=NEW.id AND source_system='amazon') BEGIN SELECT RAISE(ABORT,'Amazon account must extend Amazon commerce account'); END;")
    sql.append("CREATE TRIGGER work_attachments_page_version BEFORE INSERT ON work_attachments WHEN NEW.subject_type='page' AND NEW.action='published' BEGIN SELECT CASE WHEN coalesce(json_valid(NEW.payload),0)=0 THEN RAISE(ABORT,'page publication requires version payload') END; SELECT CASE WHEN coalesce(length(trim(CAST(json_extract(NEW.payload,'$.version') AS TEXT))),0)=0 THEN RAISE(ABORT,'page publication requires version payload') END; END;")
    if people:
        sql.append("CREATE TRIGGER people_pipeline_stages_referenced BEFORE UPDATE OF pipeline ON people_pipeline_stages WHEN EXISTS(SELECT 1 FROM people_opportunities o WHERE o.stage=NEW.id AND o.pipeline IS NOT NEW.pipeline) BEGIN SELECT RAISE(ABORT,'linked opportunities require the same pipeline'); END;")
        groups=next(c['allowed_values'] for c in columns if c['table']=='people_pipeline_stages' and c['column']=='stage')
        valid=' OR '.join('(NEW.name='+S(pipeline)+' AND s.stage IN ('+','.join(map(S,choices))+'))' for pipeline,choices in sorted(groups.items()))
        sql.append('CREATE TRIGGER people_pipelines_stage_choices BEFORE UPDATE OF name ON people_pipelines WHEN EXISTS(SELECT 1 FROM people_pipeline_stages s WHERE s.pipeline=NEW.id AND NOT ('+valid+")) BEGIN SELECT RAISE(ABORT,'pipeline name conflicts with its linked stages'); END;")
    return _fox_person.render_sql('\n'.join(sql)+'\n')

def seed_rows(db,targets,columns):
    tables=[t for t in targets if t['kind']=='table']
    modules=sorted({t['module'] for t in targets})
    for i,name in enumerate(modules,1):
        tier='base' if name in ('base','work') else 'workspace-type' if name=='commerce' else 'add-on'
        db.execute('INSERT INTO base_modules(id,name,job,tier,version,source_path) VALUES(?,?,?,?,?,?)',(i,name,'Collections and commands for '+name+'.',tier,BLUEPRINT,'code/foxrun-modules/'+name))
    modids={r['name']:r['id'] for r in db.execute('SELECT id,name FROM base_modules')}
    objids={};field_id=0
    for i,t in enumerate(tables,1):
        name=t['name'];objids[name]=i
        desc=t.get('definition') or next((x.get('change') for x in t.get('changes',[]) if isinstance(x,dict) and x.get('change')),None) or t['object_type']+' records in '+t['collection']+'.'
        db.execute('INSERT INTO base_object_types(id,name,supertype,lens,collection,module,location,description,definition,source,why,example) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(i,t['object_type'],t['supertype'],t['lens'],t['collection'],modids[t['module']],name,desc,json.dumps(t,sort_keys=True),'blueprint v'+BLUEPRINT+': '+name,'One definition for '+name+'.','Read '+name+' through its table command.'))
        table_cols=[c for c in columns if c['table']==name]
        for ordinal,c in enumerate(table_cols,1):
            field_id+=1
            typ={'integer':'number','money':'number','timestamp':'time','boolean':'yes/no','long text':'text','json':'list' if c.get('v7_type')=='list' else 'text','multi-pick':'list'}.get(c['field_type'],c['field_type'])
            choices=c.get('allowed_values')
            if isinstance(choices,dict):choices=list(dict.fromkeys(v for group in choices.values() for v in group))
            vals=json.dumps(choices) if choices is not None else None
            evidence={'blueprint':'v'+BLUEPRINT,'table':name,'column':c['column'],'storage_type':c['sqlite_type'],'sql_definition':field_sql(c,t['primary_key']),'rules':c}
            description=c.get('description') or (c['column']+' uses '+c['field_type']+' in '+name+'.')
            db.execute('INSERT INTO base_fields(id,object_type,field,sort_order,required,field_type,pick_values,pick_source,description,source,indexed,link_target) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(field_id,i,c['column'],ordinal,int(c['required']),typ,vals,'; '.join(c.get('ruling',[])) or 'blueprint v'+BLUEPRINT,description,json.dumps(evidence,sort_keys=True),int(any(c['column'] in x for x in t.get('indexes',[]))),json.dumps(c['link'],sort_keys=True) if c.get('link') else None))
    # The sequence is an implementation table, not a new model object type.
    i=len(tables)+1
    db.execute('INSERT INTO base_object_types(id,name,supertype,lens,collection,module,location,description,definition,source,why,example) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(i,'_foxrun_sequence','record','history','timeline',modids['base'],'_foxrun_sequence','Database counter for the five event tables.','{"implementation":true,"primary_key":["id"],"unique_keys":[["id"]]}','pr-db-event-seq','Allocate each event number once.','The first appended event gets seq 1.'))
    for ordinal,(name,desc) in enumerate([('id','Singleton key. The only value is 1.'),('value','Last allocated event number. It starts at zero.')],1):
        field_id+=1
        db.execute('INSERT INTO base_fields(id,object_type,field,sort_order,required,field_type,description,source) VALUES(?,?,?,?,?,?,?,?)',(field_id,i,name,ordinal,1,'number',desc,json.dumps({'storage_type':'INTEGER','blueprint':'pr-db-event-seq','implementation':True},sort_keys=True)))
    db.execute('INSERT INTO _foxrun_sequence VALUES(1,0)')

def pages(targets,columns):
    tables=[t for t in targets if t['kind']=='table']
    head='---\ntype: doc\nworkspace: '+_fox_person.workspace('system')+'\ntimestamp: 2026-10-05T00:00:00-04:00\ntags: [data-model-definition]\n---\n\n'
    keys=head+'# Keys\n\nGenerated from blueprint v'+BLUEPRINT+'. Hidden ids join rows. Display keys preserve visible numbers.\n\n| Table | Hidden key | Display key | Unique keys |\n|---|---|---|---|\n'
    for t in tables:keys+='| '+t['name']+' | '+', '.join(t['primary_key'])+' | '+', '.join(t.get('display_key') or [])+' | '+'; '.join(', '.join(k) for k in t.get('unique_keys',[]))+' |\n'
    owners=head+'# Word owners\n\nGenerated from blueprint v'+BLUEPRINT+'. The table owns the word in its module.\n\n| Word | Module | Collection | Table |\n|---|---|---|---|\n'
    for t in tables:owners+='| '+t['object_type']+' | '+t['module']+' | '+t['collection']+' | '+t['name']+' |\n'
    modules=sorted({t['module'] for t in tables})
    grid=head+'# Module grid\n\nGenerated from blueprint v'+BLUEPRINT+'. Own means the module supplies the table. Link means a foreign key uses it.\n\n| Table | '+' | '.join(modules)+' |\n|---|'+'---|'*len(modules)+'\n'
    for t in tables:
        cells=[]
        for module in modules:
            uses=any(x['module']==module and any(fk['table']==t['name'] for fk in x.get('foreign_keys',[])) for x in tables)
            cells.append('Own' if module==t['module'] else 'Link' if uses else '')
        grid+='| '+t['name']+' | '+' | '.join(cells)+' |\n'
    return {'keys.md':keys,'word-owners.md':owners,'module-grid.md':grid}

def schema_hash(db):
    rows=[tuple(r) for r in db.execute("SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY type,name")]
    return hashlib.sha256(json.dumps(rows,separators=(',',':')).encode()).hexdigest()

def build(path,blueprint):
    path=Path(path)
    if path.exists():raise ValueError('Refuse existing database. Verify it or choose a new path.')
    path.parent.mkdir(parents=True,exist_ok=True)
    targets,columns=load(blueprint)
    db=connect(path,{'writer':'schema','workspace':_fox_person.workspace('system'),'actor':'schema-update','reason':'schema definitions'})
    try:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript(sql_schema(targets,columns))
        from views import view_sql
        db.executescript(view_sql(targets,columns))
        # Keep schema's schema-update path and definitions in the clean build.
        sys.path.insert(0,str(Path(blueprint).resolve().parent))
        from dictionary_v11 import apply as apply_dictionary
        apply_dictionary(path,blueprint,path.parent/'dictionary-seed.sql',path.parent/'dictionary-backups')
        db.execute('INSERT INTO _foxrun_sequence VALUES(1,0)');db.commit()
        db.executescript(guard_sql(targets,columns))
        db.commit()
        if list(db.execute('PRAGMA foreign_key_check')):raise ValueError('Foreign key check failed')
        for t in targets:
            if t['kind']=='view':db.execute('SELECT * FROM '+Q(t['name'])+' LIMIT 0').fetchall()
        return schema_hash(db)
    finally:db.close()

def installed_addons(home):
    """Every add-on model folder in an installed home: <home>/modules/<pack>/blueprint and <home>/<add-on>/blueprint."""
    home=Path(home)
    names=[f.parent.name for f in sorted(home.glob('modules/*/blueprint'))]+[f.parent.name for f in sorted(home.glob('*/blueprint'))]
    return addon_blueprints(home,[n for n in dict.fromkeys(names) if n!='base'])

def execute(path,blueprint,table,operation,data,identity,context,addons=()):
    targets,columns=load(blueprint,addons=addons);targets={t['name']:t for t in targets if t['kind']=='table'}
    if table not in targets:raise ValueError('Unknown table command')
    if context.get('writer') not in ('agent','feeder','cron'):raise ValueError('Writer must be agent, feeder, or cron')
    if not context.get('actor') or not context.get('workspace'):raise ValueError('Actor and workspace are required')
    if context['writer']=='agent' and not context.get('session'):raise ValueError('Agent requires session')
    if context['writer'] in ('feeder','cron') and not context.get('source'):raise ValueError('Feeder or cron requires source')
    cs={c['column']:c for c in columns if c['table']==table};data=dict(data)
    if not set(data)<=cs.keys():raise ValueError('Unknown fields: '+str(set(data)-cs.keys()))
    forbidden={'id','seq','action','actor','session','recorded_at','occurred_at','created_at','updated_at'} & data.keys()
    forbidden|={k for k in data if cs[k]['field_type']=='timestamp' and cs[k].get('required_when','').startswith('New row.') and not k.startswith('source_')}
    forbidden|={k for k in data if table not in EVENTS and k=='version' and cs[k]['sqlite_type']=='INTEGER'}
    if forbidden:raise ValueError('Command owns these fields: '+', '.join(sorted(forbidden)))
    if targets[table].get('database_type')=='mirror' and context['writer']!='feeder':raise ValueError('Mirror requires its feeder')
    db=connect(path,context)
    try:
        db.execute('BEGIN IMMEDIATE')
        now=datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')
        if table=='work_changes' and operation in ('verified','accepted','merged','released','rolled-back'):
            if set(data)-{'subject_type','subject_id','subject_version','summary','refs'}:raise ValueError('Milestone owns its event fields')
            subject=next((t for t in targets.values() if t['object_type']==data.get('subject_type')),None)
            if not subject:raise ValueError('Milestone requires a model record')
            row=db.execute('SELECT * FROM '+Q(subject['name'])+' WHERE id=?',(data.get('subject_id'),)).fetchone()
            if row is None:raise ValueError('Milestone subject does not exist')
            if 'workspace' in row.keys() and row['workspace']!=context['workspace']:raise ValueError('Milestone workspace differs from subject')
            if 'version' in row.keys() and str(data.get('subject_version'))!=str(row['version']):raise ValueError('Milestone requires the exact version')
            if subject['name']=='work_tasks' and operation in ('verified','accepted'):
                reviewer=_fox_person.name() if row['reviewer']==_fox_person.name() else row['reviewed_by']
                if not reviewer or context['actor'].lower()!=reviewer.lower():raise ValueError('Task milestone requires its reviewer')
            data['action']=operation;operation='insert'
        if table=='base_approvals' and operation in ('approved','rejected','edited','discussed'):
            data['action']=operation;operation='insert'
        if table=='work_attachments' and operation=='published':
            data['action']='published';operation='insert'
        if operation=='update':
            old=db.execute('SELECT * FROM '+Q(table)+' WHERE '+Q('seq' if table in EVENTS else 'id')+'=?',(identity,)).fetchone()
            if old is None:raise ValueError('Record does not exist')
            data={k:v for k,v in data.items() if old[k]!=v}
            if not data:db.rollback();return {'changed':False,'id':identity}
            if table in EVENTS:raise ValueError('Event table is append-only')
            hashed(targets[table],data,old)
            if 'updated_at' in cs:data['updated_at']=now
            if table=='work_runs' and data.get('status') in ('succeeded','failed','partial','canceled'):data['ended_at']=now
            named=targets[table].get('version_columns')
            if 'version' in cs and cs['version']['sqlite_type']=='INTEGER' and (not named or set(named)&set(data)):data['version']=old['version']+1
            db.execute('UPDATE '+Q(table)+' SET '+','.join(Q(k)+'=?' for k in data)+' WHERE id=?',tuple(data.values())+(identity,))
            result=identity
        elif operation=='insert':
            if 'workspace' in cs:data.setdefault('workspace',context['workspace'])
            if table=='amazon_accounts':
                if identity is None:raise ValueError('Amazon extension requires --id of its commerce account')
                data['id']=identity
            if table not in EVENTS:
                if 'actor' in cs:data['actor']=context['actor']
                if 'session' in cs:data['session']=context.get('session')
                if 'version' in cs and cs['version']['sqlite_type']=='INTEGER':
                    # Where the version numbers the texts of a family, a new row takes the next number of its family.
                    family=targets[table].get('version_family')
                    data['version']=1 if not family else 1+db.execute('SELECT coalesce(max(version),0) FROM '+Q(table)+' WHERE '+Q(family)+' IS ?',(data.get(family),)).fetchone()[0]
                hashed(targets[table],data)
            for c in cs.values():
                k=c['column']
                if k in ('created_at','updated_at','recorded_at','occurred_at') or (c['field_type']=='timestamp' and c.get('required_when','').startswith('New row.') and not k.startswith('source_')):
                    data.setdefault(k,now)
                if c['field_type']=='boolean' and (c['required'] or c.get('required_guard')):data.setdefault(k,0)
            if 'number' in cs and 'number' not in data:
                prefix={'work_tasks':'T','work_projects':'P','work_programs':'PG','work_runs':'R'}.get(table,'')
                where=' WHERE workspace=?' if 'workspace' in cs else ''
                params=(context['workspace'],) if where else ()
                values=[str(r[0]) for r in db.execute('SELECT number FROM '+Q(table)+where,params)]
                nums=[int(v[len(prefix):]) for v in values if v.startswith(prefix) and v[len(prefix):].isascii() and v[len(prefix):].isdigit()]
                data['number']=prefix+str(max(nums,default=0)+1)
            if table in EVENTS:
                if table=='work_changes' and 'action' not in data:raise ValueError('Change rows require a milestone operation')
                data['seq']=db.execute('SELECT value+1 FROM _foxrun_sequence').fetchone()[0]
                data.update(actor=context['actor'],session=context.get('session'),source=context.get('source'),occurred_at=now,recorded_at=now)
                if table=='work_comments':data['action']='commented'
                elif table=='work_attachments':data.setdefault('action','attached')
                elif table=='base_approvals':
                    if 'action' not in data:raise ValueError('Approval requires a response operation')
                    if data.get('authorization_valid'):
                        if context['actor'].lower()!=_fox_person.name().lower():raise ValueError(f'Authorization requires {_fox_person.display_name()}')
                        subject=next((t for t in targets.values() if t['object_type']==data.get('subject_type')),None)
                        if not subject:raise ValueError('Authorization subject has no model table')
                        row=db.execute('SELECT * FROM '+Q(subject['name'])+' WHERE id=?',(data.get('subject_id'),)).fetchone()
                        if row is None or 'version' not in row.keys() or row['version']!=data.get('version'):raise ValueError('Authorization requires the current exact version')
                        if 'workspace' in row.keys() and row['workspace']!=context['workspace']:raise ValueError('Authorization workspace differs from subject')
                        if 'content_hash' in row.keys() and row['content_hash']!=data.get('approved_sha256'):raise ValueError('Authorization hash differs from subject')
                elif table=='base_receipts':
                    moment=context.get('moment')
                    if moment not in ('handed-off','compacted','forked','closed'):raise ValueError('Receipt command requires a session moment')
                    data['action']=moment
                    if moment!='forked':data.setdefault('last_seq',db.execute('SELECT value FROM _foxrun_sequence').fetchone()[0])
            result=db.execute('INSERT INTO '+Q(table)+' ('+','.join(map(Q,data))+') VALUES ('+','.join('?' for _ in data)+')',tuple(data.values())).lastrowid
        else:raise ValueError('Only insert and update are supported')
        db.commit();return {'changed':True,'id':result}
    except BaseException:db.rollback();raise
    finally:db.close()

def main():
    p=argparse.ArgumentParser();p.add_argument('--db',required=True);p.add_argument('--blueprint',default=str((Path(__file__).resolve().parent / 'blueprint')))
    p.add_argument('--table',required=True);p.add_argument('--actor',required=True);p.add_argument('--workspace',required=True)
    p.add_argument('--writer',choices=['agent','feeder','cron'],default='agent');p.add_argument('--session');p.add_argument('--source');p.add_argument('--reason');p.add_argument('--moment')
    p.add_argument('operation',choices=['insert','update','approved','rejected','edited','discussed','verified','accepted','merged','released','rolled-back','published']);p.add_argument('--id',type=int);p.add_argument('--json',required=True)
    # An add-on's table command passes --with-addons: its rows live in the add-on's own blueprint folder.
    p.add_argument('--with-addons',action='store_true')
    a=p.parse_args();ctx={k:getattr(a,k) for k in ('actor','workspace','writer','session','source','reason','moment')}
    try:print(json.dumps(execute(a.db,a.blueprint,a.table,a.operation,json.loads(a.json),a.id,ctx,installed_addons(Path(a.blueprint).resolve().parent.parent) if a.with_addons else ()),sort_keys=True))
    except (ValueError,sqlite3.Error) as e:print('FAIL '+str(e),file=sys.stderr);return 1
    return 0

if __name__=='__main__':sys.exit(main())
