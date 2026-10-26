#!/usr/bin/env python3
"""Import legacy JSONL bodies into events_changes after the database migration.
Default: parity check only. --write imports once. --retire-source also removes the
source only after exact readback of every body. A model never writes event rows.
"""
import argparse, datetime, hashlib, json, sqlite3
from pathlib import Path

def import_log(source, database, workspace, write=False, retire=False):
    source=Path(source)
    if source.is_symlink():raise ValueError('symlink source refused')
    raw=source.read_bytes(); digest=hashlib.sha256(raw).hexdigest()
    rows=[json.loads(line) for line in raw.decode('utf-8').splitlines() if line.strip()]
    if not rows:raise ValueError('empty source')
    for row in rows:
        if not isinstance(row.get('body'),str):raise ValueError('body missing')
    con=sqlite3.connect(Path(database).resolve().as_uri()+'?mode='+('rw' if write else 'ro'),uri=True)
    con.create_function('foxrun_workspace_allowed',1,lambda value: value==workspace)
    con.create_function('foxrun_workspace_allowed',2,lambda value,other: value==workspace)
    try:
        columns={r[1] for r in con.execute('pragma table_info(events_changes)')}
        if not {'workspace','subject_type','subject_id','action','actor','new_value','refs'}<=columns:
            raise ValueError('events_changes schema absent; old trackers remain untouched')
        missing=[]
        for number,row in enumerate(rows,1):
            key='legacy-log:'+workspace+':'+digest+':'+str(number)
            matches=con.execute("select new_value from events_changes where workspace=? and subject_type='file' and subject_id=?",(workspace,key)).fetchall()
            if matches and matches != [(row['body'],)]:raise ValueError('duplicate or changed imported record')
            if not matches:missing.append((number,key,row))
        if write:
            with con:
                for number,key,row in missing:
                    occurred=row.get('date')
                    if occurred is not None and con.execute('select julianday(?)',(occurred,)).fetchone()[0] is None:
                        occurred=None  # Preserve the original value in refs; do not invent an occurrence date.
                    con.execute('insert into events_changes (workspace,subject_type,subject_id,action,actor,new_value,occurred_at,recorded_at,refs,source) values (?,?,?,?,?,?,?,?,?,?)',
                      (workspace,'file',key,'imported','keeper',row['body'],occurred,datetime.datetime.now(datetime.timezone.utc).isoformat(),json.dumps([{'source_sha256':digest,'source_line':number,'original_record':row}],sort_keys=True), workspace+'/history/log.jsonl'))
                for number,row in enumerate(rows,1):
                    key='legacy-log:'+workspace+':'+digest+':'+str(number)
                    got=con.execute("select new_value from events_changes where workspace=? and subject_type='file' and subject_id=?",(workspace,key)).fetchall()
                    if got!=[(row['body'],)]:raise ValueError('body parity failed')
        if retire:
            if not write:raise ValueError('--retire-source requires --write')
            if hashlib.sha256(source.read_bytes()).hexdigest()!=digest:raise ValueError('source changed during import')
            source.unlink()
        return {'rows':len(rows),'missing':len(missing),'write':write,'retired':retire}
    finally:con.close()

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',required=True);p.add_argument('--db',required=True);p.add_argument('--workspace',required=True);p.add_argument('--write',action='store_true');p.add_argument('--retire-source',action='store_true');a=p.parse_args()
    print(json.dumps(import_log(a.source,a.db,a.workspace,a.write,a.retire),sort_keys=True))
