"""Generate lint inventory from one new consumer install; standard library only."""
import csv
import re
from pathlib import Path
import sqlite3

def generate(home, portfolio, workspace):
    home, portfolio = Path(home), Path(portfolio)
    policy = home / 'config/lint'
    def table(name, fields, rows):
        with (policy / name).open('w', encoding='utf-8', newline='') as stream:
            writer=csv.writer(stream, delimiter='\t', lineterminator='\n')
            writer.writerow(fields); writer.writerows(rows)
    table('workspaces.tsv', ('id','kind','source'),
          [(workspace,'workspace','Installer choice'),('atlas','shared','Product library')])
    table('business-names.tsv', ('name','source'), [(workspace,'Installer choice')])
    path=policy/'allowed-top.tsv'
    text = path.read_text(encoding='utf-8').replace('<workspace>',workspace)
    with path.open('w', encoding='utf-8', newline='\n') as stream:
        stream.write(text)
    with sqlite3.connect((home/'data.db').as_uri()+'?mode=ro',uri=True) as db:
        columns=db.execute('PRAGMA table_info(tasks)').fetchall()
    fields=('home','path','table','column','format','database_home','workspace_column','workspace_value','source')
    rows=[]
    column_names={row[1] for row in columns}
    scope_column='workspace' if 'workspace' in column_names else 'tags' if 'tags' in column_names else None
    if not scope_column:
        raise ValueError('Installed task schema needs a workspace scope column')
    scope_value=workspace if scope_column=='workspace' else 'workspace:'+workspace
    for _,name,kind,_,_,_ in columns:
        fmt='integer' if 'INT' in kind.upper() else 'text'
        rows.append(('system','data.db','tasks',name,fmt,'system','','','Installed data.db/tasks schema'))
        rows.append((workspace,'data.db','tasks',name,fmt,'system',scope_column,scope_value,'Consumer workspace resolver and installed task schema'))
    table('db.tsv',fields,rows)
    table('db-reasons.tsv',('home','table','row_id','column','case','reason'),
          [('system','tasks','','','empty-table','Fresh install has no user tasks yet'),
           (workspace,'tasks','','','empty-table','Fresh install has no workspace tasks yet')])


def retarget_contract_sources(home):
    """Migrate local lint provenance without replacing the person's schema rows."""
    path = Path(home) / 'config/lint/db.tsv'
    if path.is_symlink():
        raise ValueError('lint database routes must not be linked')
    if not path.exists():
        return False
    raw = path.read_bytes()
    lines = raw.splitlines(keepends=True)
    if not lines or b'source' not in lines[0].rstrip(b'\r\n').split(b'\t'):
        return False
    source = lines[0].rstrip(b'\r\n').split(b'\t').index(b'source')
    migrated = [lines[0]]
    for line in lines[1:]:
        fields = line.split(b'\t')
        if len(fields) > source:
            fields[source] = re.sub(rb'~/\.foxrun/AGENTS\.md(?::[0-9]+)?(?=$|[;#\s])',
                                    b'~/.foxrun/profile/AGENTS.md', fields[source])
        migrated.append(b'\t'.join(fields))
    updated = b''.join(migrated)
    if updated == raw:
        return False
    path.write_bytes(updated)
    return True
