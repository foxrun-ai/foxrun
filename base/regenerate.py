#!/usr/bin/env python3
"""Regenerate the core database and dictionary from committed blueprint sources."""

from __future__ import annotations

import sys as _person_sys
from pathlib import Path as _PersonPath
_person_root = next(p for p in _PersonPath(__file__).resolve().parents if (p / "base/person.py").is_file())
_person_sys.path.insert(0, str(_person_root))
from base import person as _fox_person
import argparse
import hashlib
from pathlib import Path
import sqlite3
from core import build,connect,load,sql_schema,guard_sql,schema_hash,pages,Q,MODEL
from views import view_sql
from dictionary_v11 import row_sets,snapshot,apply,generate,seed_sql

def write(path,body):
    if path.exists() and path.read_text()==body:return
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(body)

FORWARDER='#!/usr/bin/env python3\n"""Forward a checked table command to the shared implementation."""\nimport os\nfrom pathlib import Path\nimport sys\nhere = Path(__file__).resolve().parent.parent\nos.execv(sys.executable, [sys.executable, str(here / \'core.py\'), *sys.argv[1:], \'--table\', {table!r}])\n'

def generate_commands(tools,targets):
    # Only the core blueprint's tables get a command here. A pack or add-on ships its own
    # commands beside its own blueprint (g-business-packs-do-not-ship, g-people-ships-with-small-talk).
    tables={t['name'] for t in targets if t['kind']=='table'}
    for target in targets:
        if target['kind']!='table':continue
        command=Path(tools)/'commands'/target['name']
        write(command, FORWARDER.format(table=target['name']))
        if not command.stat().st_mode&0o111:command.chmod(command.stat().st_mode|0o111)
    # A forwarder this tool made for a table the core no longer holds is stale. Remove only exact forwarders.
    folder=Path(tools)/'commands'
    for command in sorted(folder.iterdir()) if folder.is_dir() else ():
        if command.is_file() and command.name not in tables and command.read_text()==FORWARDER.format(table=command.name):
            command.unlink()

def regenerate(root,database='home/.local/share/foxrun/data.db'):
    root=Path(root).resolve();tools=root/'code/foxrun-modules/base';blueprint=tools/'blueprint'
    path=(root/database).resolve()
    if not path.is_relative_to(root):raise ValueError('Database must be inside target root')
    targets,columns=load(blueprint);schema=sql_schema(targets,columns);guards=guard_sql(targets,columns);views=view_sql(targets,columns)
    expected=_fox_person.connect(':memory:');expected.executescript(schema);expected.executescript(views);expected.executescript(guards);desired=schema_hash(expected);expected.close()
    if path.exists():
        db=connect(path,readonly=True);actual=schema_hash(db)
        if actual!=desired:
            # A database made before this blueprint lacks the new tables. Count the tables it has.
            present={r[0] for r in db.execute("SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'")}-set(MODEL)
            business=sorted(name for name in present if db.execute('SELECT count(*) FROM '+Q(name)).fetchone()[0])
            if business:db.close();raise ValueError('Schema differs; preserve business rows and apply the reviewed schema delta: '+', '.join(business))
            db.close();archive=path.with_name(path.name+'.schema-'+actual+'.archive')
            if archive.exists():raise ValueError('Archive already exists: '+str(archive))
            path.rename(archive)
            for suffix in ('-wal','-shm'):
                sibling=Path(str(path)+suffix)
                if sibling.exists():sibling.rename(Path(str(archive)+suffix))
            build(path,blueprint)
        else:db.close()
    else:build(path,blueprint)
    db=connect(path,readonly=True);groups=row_sets(db,blueprint);db.close()
    current=snapshot(path)
    expected_rows=dict(zip(('modules','object_types','fields'),groups))
    if any([{k:r.get(k) for k in wanted} for r,wanted in zip(current[name],rows)]!=rows or len(current[name])!=len(rows) for name,rows in expected_rows.items()):
        apply(path,blueprint,path.parent/'dictionary-seed.sql',path.parent/'dictionary-backups')
    write(tools/'schema.sql',schema);write(tools/'guards.sql',guards);write(tools/'views.sql',views);write(tools/'schema.sha256',desired+'\n');write(tools/'dictionary-seed.sql',seed_sql(groups))
    generate_commands(tools,targets)
    out=root/'vault'/_fox_person.workspace('system')/'docs/data-db'
    for name,body in pages(targets,columns).items():write(out/name,body)
    generate(path,out/'dictionary')
    db=connect(path,readonly=True);assert schema_hash(db)==desired;db.close()
    print('PASS regeneration schema '+desired)
    return desired

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root');parser.add_argument('--database',default='home/.local/share/foxrun/data.db')
    args=parser.parse_args()
    try:regenerate(args.root,args.database)
    except (ValueError,sqlite3.Error,AssertionError) as error:print('FAIL regeneration: '+str(error));raise SystemExit(1)
