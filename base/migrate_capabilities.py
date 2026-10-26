#!/usr/bin/env python3
"""Load capability rows after the one-database migration. Never use the old tracker.
The default is check only. --write runs one transaction. No table is created.
"""
import argparse, csv, json, sqlite3
from pathlib import Path

def workspaces(home):
    """The default workspace plus the person's workspaces from config/person.json of the system home."""
    if home.name=='one-database' and home.parent.name=='backups':home=home.parent.parent
    try:configured=json.loads((home/'config/person.json').read_text()).get('workspaces') or []
    except (OSError,ValueError):configured=[]
    return {'foxrun-dev'}|{w for w in configured if isinstance(w,str)}

def load(database, table, write=False, portfolio=None):
    with Path(table).open() as source:
        rows=list(csv.DictReader(source, delimiter='\t'))
    if not rows or len({r['name'] for r in rows}) != len(rows):
        raise ValueError('empty or duplicate capability names')
    con=sqlite3.connect(Path(database).as_uri()+'?mode='+('rw' if write else 'ro'), uri=True)
    allowed=workspaces(Path(database).parent)
    con.create_function('foxrun_workspace_allowed',1,lambda value: value in allowed)
    con.create_function('foxrun_workspace_allowed',2,lambda value,other: value in allowed)
    con.execute('pragma foreign_keys=on')
    try:
        columns={r[1] for r in con.execute('pragma table_info(base_capabilities)')}
        wanted=['name','kind','set','workspace','status','runtimes','card_path']
        if not set(wanted)<=columns:raise ValueError('one-database schema is absent; old tracker is unchanged')
        home=Path(database).parent
        # For the staged database under backups/, the installed home is two levels above it.
        if home.name=='one-database' and home.parent.name=='backups':home=home.parent.parent
        portfolio=Path(portfolio).resolve() if portfolio else home.parent/'foxrun'
        seen=set()
        values=[]
        for row in rows:
            path=Path(row['card_path'])
            if path.is_absolute() or '..' in path.parts:raise ValueError('card path must be relative')
            workspace=row.get('workspace') or 'foxrun-dev'
            card=home/path if row.get('set') in ('base','',None) else portfolio/path
            if not card.is_file():raise ValueError('missing card: '+str(card))
            if str(card) in seen:raise ValueError('duplicate card')
            seen.add(str(card))
            runtimes=json.loads(row['runtimes'])
            if not isinstance(runtimes,list) or (not runtimes and row['status']!='dead'):raise ValueError('runtimes must be a nonempty list unless dead')
            value=[row.get(k) or None for k in wanted];value[3]=workspace;value[5]=json.dumps(runtimes)
            old=con.execute('select '+','.join('"'+k+'"' for k in wanted)+' from base_capabilities where name=?',(row['name'],)).fetchone()
            if old and list(old)!=value:raise ValueError('existing row differs: '+row['name'])
            values.append(value)
        if write:
            with con:
                con.executemany('insert or ignore into base_capabilities ('+','.join('"'+k+'"' for k in wanted)+') values (?,?,?,?,?,?,?)',values)
                for value in values:
                    got=con.execute('select '+','.join('"'+k+'"' for k in wanted)+' from base_capabilities where name=?',(value[0],)).fetchone()
                    if list(got)!=value:raise ValueError('readback mismatch')
        return len(values)
    finally:con.close()

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db',required=True);p.add_argument('--rows',required=True);p.add_argument('--portfolio');p.add_argument('--write',action='store_true');a=p.parse_args()
    print('%d capability rows checked%s'%(load(Path(a.db).resolve(),a.rows,a.write,a.portfolio), ' and loaded' if a.write else '; nothing written'))
