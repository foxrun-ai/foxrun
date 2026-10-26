#!/usr/bin/env python3
"""Schema-update path for the blueprint dictionary. No business-table writes."""
from __future__ import annotations

import sys as _person_sys
from pathlib import Path as _PersonPath
_person_root = next(p for p in _PersonPath(__file__).resolve().parents if (p / "base/person.py").is_file())
_person_sys.path.insert(0, str(_person_root))
from base import person as _fox_person
import argparse
from collections import defaultdict
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from core import BLUEPRINT,connect as core_connect

Q=lambda s:'"'+s.replace('"','""')+'"'
S=lambda s:'NULL' if s is None else str(int(s)) if isinstance(s,(int,bool)) else "'"+str(s).replace("'","''")+"'"
META=('base_modules','base_object_types','base_fields','_foxrun_sequence')

def connect(path,readonly=False):
    return core_connect(path,{'writer':'schema','actor':'schema-update','workspace':_fox_person.workspace('system'),'reason':'dictionary definitions'},readonly=readonly)

def definitions(sql):
    body=sql[sql.index('(')+1:sql.rindex(')')];parts=[];pending=[];depth=0;quote=None;i=0
    while i<len(body):
        ch=body[i];pending.append(ch)
        if quote:
            if ch==quote:
                if i+1<len(body) and body[i+1]==quote:pending.append(body[i+1]);i+=1
                else:quote=None
        elif ch in ('"',"'"):quote=ch
        elif ch=='(':depth+=1
        elif ch==')':depth-=1
        elif ch==',' and depth==0:parts.append(''.join(pending[:-1]).strip());pending=[]
        i+=1
    if pending:parts.append(''.join(pending).strip())
    return parts

def migrate(db):
    info=list(db.execute('PRAGMA table_info(base_fields)'))
    present={r['name'] for r in info}
    current=db.execute("SELECT sql FROM sqlite_schema WHERE name='base_fields'").fetchone()[0]
    if 'storage_type' in present and 'sql_definition' in present and "'map'" in current:return False
    objects=list(db.execute("SELECT type,sql FROM sqlite_schema WHERE tbl_name='base_fields' AND type IN ('trigger','index') AND sql IS NOT NULL"))
    sql=current.replace('CREATE TABLE "base_fields"','CREATE TABLE "_t137_fields"',1).replace('CREATE TABLE base_fields','CREATE TABLE "_t137_fields"',1)
    sql=sql.replace("'yes/no'))","'yes/no','map'))",1)
    assert "'map'" in sql,'field type CHECK was not found'
    additions=[]
    if 'storage_type' not in present:additions.append('"storage_type" TEXT')
    if 'sql_definition' not in present:additions.append('"sql_definition" TEXT')
    parts=definitions(sql)
    column_parts=[p for p in parts if p.startswith('"')]
    constraints=[p for p in parts if not p.startswith('"')]
    sql='CREATE TABLE "_t137_fields" (\n  '+',\n  '.join(column_parts+additions+constraints)+'\n) STRICT'
    db.execute(sql)
    names=','.join(Q(r['name']) for r in info)
    db.execute('INSERT INTO _t137_fields ('+names+') SELECT '+names+' FROM base_fields')
    db.execute('DROP TABLE base_fields')
    db.execute('ALTER TABLE _t137_fields RENAME TO base_fields')
    for row in objects:db.execute(row['sql'])
    return True

def blueprint_rows(blueprint):
    from core import load
    return load(blueprint)

def row_sets(db,blueprint):
    targets,columns=blueprint_rows(blueprint)
    by={(c['table'],c['column']):c for c in columns}
    target_by={t['name']:t for t in targets if t['kind']!='import'}
    table_names={r[0] for r in db.execute("SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    modules=sorted({t['module'] for t in target_by.values()}|{'wiki'})
    modids={name:i+1 for i,name in enumerate(modules)}
    modrows=[]
    for name,identity in modids.items():
        tier='base' if name in ('base','work','wiki') else 'workspace-type' if name=='commerce' else 'add-on'
        modrows.append({'id':identity,'name':name,'job':'Collections and commands for '+name+'.','tier':tier,'version':BLUEPRINT,'source_path':'code/foxrun-modules/'+name,'built_by':'kit' if name=='wiki' else 'foxrun'})
    objs=[];fields=[];identity=0;field_id=0
    def add_obj(name,module,supertype,lens,collection,location,description,definition,source,database_type=None):
        nonlocal identity
        identity+=1
        row={'id':identity,'name':name,'module':modids[module],'supertype':supertype,'lens':lens,'collection':collection,'location':location,'description':description,'definition':json.dumps(definition,sort_keys=True),'source':source,'database_type':database_type,'why':'One source for the definition at '+location+'.','example':'Read the definition for '+name+'.'}
        objs.append(row);return identity
    for name,t in sorted(target_by.items()):
        native=db.execute('SELECT sql FROM sqlite_schema WHERE name=?',(name,)).fetchone()
        sql=native[0] if native else None
        meta=dict(t)
        meta.update(one_entry=t.get('definition') or t['object_type']+' in '+t['collection'],generated=t['kind']=='view',path_base='install',platform_sql=sql,
                    writer=t.get('writer_contract') or t.get('write_contract') or ('read-only view' if t['kind']=='view' else 'one-door-per-home: use the table command'),
                    source_binding=t.get('sources',[]))
        if t['object_type']=='installed-module':meta['word_status']='open: pr-db-new-words-refine'
        desc=t.get('definition') or t['object_type']+' in '+t['collection']+'.'
        lens=t.get('lens','records');lens='records' if lens=='view' else lens
        oid=add_obj(t['object_type'],t['module'],t.get('supertype','record'),lens,t['collection'],name,desc,meta,'blueprint v'+BLUEPRINT+': '+name,t.get('database_type') or ('view' if t['kind']=='view' else 'table'))
        raw_fields={}
        if sql and t['kind']=='table':
            for part in definitions(sql):
                if part.startswith('"'):raw_fields[part.split('"',2)[1]]=part
        actual=list(db.execute('PRAGMA table_info('+Q(name)+')')) if native else []
        actual_by={r['name']:r for r in actual}
        names=list(actual_by) if actual else [c['column'] for c in columns if c['table']==name]
        for ordinal,field in enumerate(names,1):
            field_id+=1
            c=by.get((name,field),{'column':field,'field_type':'text','sqlite_type':'TEXT','required':False,'ruling':['schema']})
            if name=='base_fields' and field=='field_type':
                c=dict(c,allowed_values=list(dict.fromkeys((c.get('allowed_values') or [])+['map'])),ruling=c.get('ruling',[])+['schema'])
            value=c.get('allowed_values')
            if isinstance(value,dict):values=list(dict.fromkeys(v for group in value.values() for v in group))
            else:values=value
            typ={'integer':'number','money':'number','timestamp':'time','boolean':'yes/no','long text':'text','json':'list' if c.get('v7_type')=='list' else 'map','multi-pick':'list'}.get(c['field_type'],c['field_type'])
            stored=actual_by[field]['type'] if field in actual_by else c['sqlite_type']
            required=bool(actual_by[field]['notnull'] or actual_by[field]['pk']) if field in actual_by else bool(c['required'])
            definition=raw_fields.get(field) if sql else None
            if t['kind']=='view' and sql:definition=sql
            proof={'blueprint':'v'+BLUEPRINT,'table':name,'column':field,'rules':c,'draft_only':not bool(native)}
            desc=c.get('description') or field+' uses '+c['field_type']+' in '+name+'.'
            fields.append({'id':field_id,'object_type':oid,'field':field,'sort_order':ordinal,'required':int(required),'field_type':typ,'pick_values':json.dumps(values) if values is not None else None,'pick_source':json.dumps({'rulings':c.get('ruling',[]),'grouped_values':value if isinstance(value,dict) else None},sort_keys=True),'description':desc,'source':json.dumps(proof,sort_keys=True),'indexed':int(any(field in k for k in t.get('indexes',[]))),'link_target':json.dumps(c['link'],sort_keys=True) if c.get('link') else None,'storage_type':stored,'sql_definition':definition})
    # Dictionary coverage includes the implementation table without a new model type.
    name='_foxrun_sequence';native=db.execute('SELECT sql FROM sqlite_schema WHERE name=?',(name,)).fetchone()[0]
    oid=add_obj(name,'base','record','history','timeline',name,'The database counter gives each event its next sequence number.',{'implementation':True,'platform_sql':native,'one_entry':'One counter for all five event tables.','writer':'database event trigger','path_base':'install'},'pr-db-event-seq','table')
    parts={p.split('"',2)[1]:p for p in definitions(native) if p.startswith('"')}
    for ordinal,r in enumerate(db.execute('PRAGMA table_info(_foxrun_sequence)'),1):
        field_id+=1
        fields.append({'id':field_id,'object_type':oid,'field':r['name'],'sort_order':ordinal,'required':int(bool(r['notnull'] or r['pk'])),'field_type':'number','description':'Singleton key.' if r['name']=='id' else 'Last allocated event number.','source':'pr-db-event-seq','storage_type':r['type'],'sql_definition':parts[r['name']]})
    # These five file kinds come from the existing Wiki kit. Their native schema is not invented.
    for name,supertype,lens,folder,writer in [('concept','document','knowledge','concepts','Keeper'),('entity','document','knowledge','entities','Keeper'),('comparison','document','knowledge','comparisons','Keeper'),('raw-source','source','history','raw','Evidence importer and keeper'),('query','document','knowledge','queries','Research author and keeper')]:
        add_obj(name,'wiki',supertype,lens,'wiki/'+folder,'{{workspace}}/wiki/'+folder+'/*',name+' from the native Wiki kit.',{'writer':writer,'path_base':'workspace','platform_sql':None,'generated':False,'one_entry':'One native '+name+' file.','native_schema':'{{workspace}}/wiki/SCHEMA.md','rule':'Add, never rename.'},'code/foxrun-modules/memory/README.md')
    assert table_names<={o['location'] for o in objs},'missing installed table definitions'
    return modrows,objs,fields

def seed_sql(groups):
    lines=['-- schema dictionary seed. Generated from blueprint v'+BLUEPRINT+' and installed SQL.','-- Change this source path, then apply, generate, and check.']
    for table,rows in zip(('base_modules','base_object_types','base_fields'),groups):
        for row in rows:
            names=list(row)
            sql='INSERT INTO '+table+' ('+','.join(map(Q,names))+') VALUES ('+','.join(S(row[k]) for k in names)+') ON CONFLICT(id) DO UPDATE SET '+','.join(Q(k)+'=excluded.'+Q(k) for k in names if k!='id')+';'
            lines.append(sql)
    return '\n'.join(lines)+'\n'

def apply(path,blueprint,seed_path,backup_dir):
    path=Path(path);backup_dir=Path(backup_dir);backup_dir.mkdir(parents=True,exist_ok=True)
    db=connect(path)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup=backup_dir/('schema-'+stamp+'.db')
    saved=_fox_person.connect(backup);db.backup(saved);saved.close()
    try:
        db.execute('PRAGMA foreign_keys=OFF');db.execute('BEGIN IMMEDIATE')
        changed=migrate(db)
        groups=row_sets(db,blueprint);seed=seed_sql(groups)
        # Explicit keys preserve definitions and make the second apply stable.
        for table,rows in zip(('base_modules','base_object_types','base_fields'),groups):
            for row in rows:
                names=list(row)
                old=db.execute('SELECT '+','.join(map(Q,names))+' FROM '+table+' WHERE id=?',(row['id'],)).fetchone()
                if old and dict(old)==row:continue
                changed=True
                db.execute('INSERT INTO '+table+' ('+','.join(map(Q,names))+') VALUES ('+','.join('?' for _ in names)+') ON CONFLICT(id) DO UPDATE SET '+','.join(Q(k)+'=excluded.'+Q(k) for k in names if k!='id'),tuple(row.values()))
        if list(db.execute('PRAGMA foreign_key_check')):raise ValueError('dictionary foreign keys failed')
        db.commit();db.execute('PRAGMA foreign_keys=ON')
        if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('dictionary quick_check failed')
        Path(seed_path).write_text(seed)
        return backup,changed
    except BaseException:db.rollback();raise
    finally:db.close()

def snapshot(path):
    db=connect(path,True)
    obj=[dict(r) for r in db.execute('SELECT * FROM base_object_types ORDER BY id')]
    fields=[dict(r) for r in db.execute('SELECT * FROM base_fields ORDER BY object_type,sort_order,id')]
    modules=[dict(r) for r in db.execute('SELECT * FROM base_modules ORDER BY id')]
    db.close();return {'modules':modules,'object_types':obj,'fields':fields}

def render(path):
    data=snapshot(path)
    field_by=defaultdict(list)
    for f in data['fields']:field_by[f['object_type']].append(f)
    table_count=sum(o['database_type']=='table' or o['database_type'] in ('mirror','trend') for o in data['object_types'])
    lines=['---','type: doc','workspace: '+_fox_person.workspace('system'),'timestamp: 2026-10-05T00:00:00-04:00','tags: [data-model-definition]','---','','# Data dictionary','','Generated through schema-update from blueprint v'+BLUEPRINT+' and installed SQL.','','| Item | Count |','|---|---|',f'| Table definitions | {table_count} |',f'| Object definitions | {len(data["object_types"])} |',f'| Field definitions | {len(data["fields"])} |','','The guide preserves source choices. It does not rule a new name.','Views use installed SQL. Wiki file kinds retain their native schema.','','| Module | Tier | Source path |','|---|---|---|']
    lines += ['| '+m['name']+' | '+m['tier']+' | '+m['source_path']+' |' for m in data['modules']]
    cell=lambda x:'' if x is None else str(x).replace('|','&#124;').replace('\n','<br>')
    for o in data['object_types']:
        lines += ['', '## '+o['location'],'',o['description'],'','| Field | Type | Required | SQLite type | Pick values |','|---|---|---|---|---|']
        for f in field_by[o['id']]:lines.append('| '+' | '.join(cell(f[k]) for k in ('field','field_type','required','storage_type','pick_values'))+' |')
    return {'dictionary.md':'\n'.join(lines)+'\n','dictionary.json':json.dumps(data,sort_keys=True,indent=2)+'\n'}

def generate(path,out,check=False):
    out=Path(out);files=render(path)
    if check:
        bad=[name for name,body in files.items() if not (out/name).exists() or (out/name).read_text()!=body]
        if bad:raise ValueError('generated dictionary differs: '+', '.join(bad))
    else:
        out.mkdir(parents=True,exist_ok=True)
        for name,body in files.items():
            if not (out/name).exists() or (out/name).read_text()!=body:(out/name).write_text(body)

def restore(path,backup):
    source=_fox_person.connect(Path(backup).resolve().as_uri()+'?mode=ro',uri=True);dest=connect(path)
    source.backup(dest);source.close();dest.close()

def main():
    p=argparse.ArgumentParser();p.add_argument('--db',required=True);p.add_argument('--blueprint');p.add_argument('--seed');p.add_argument('--backup-dir');p.add_argument('--out');p.add_argument('--apply',action='store_true');p.add_argument('--generate',action='store_true');p.add_argument('--check',action='store_true');p.add_argument('--undo');p.add_argument('--restore')
    a=p.parse_args()
    if a.undo or a.restore:restore(a.db,a.undo or a.restore);print('PASS restored '+str(a.undo or a.restore))
    if a.apply:
        backup,changed=apply(a.db,a.blueprint,a.seed,a.backup_dir);print('PASS dictionary apply; changed='+str(changed));print('Backup: '+str(backup));print('Undo: python3 '+str((Path(__file__).resolve().parent / 'dictionary_v11.py'))+' --db '+a.db+' --undo '+str(backup))
    if a.generate or a.check:generate(a.db,a.out,a.check);print('PASS dictionary '+('check' if a.check else 'generate'))
    return 0
if __name__=='__main__':sys.exit(main())
