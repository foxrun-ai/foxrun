"""Independent synthetic multi-workspace records; no live database or outside source is touched."""
import hashlib,json,sqlite3
from pathlib import Path
AT='2026-10-14T12:00:00-04:00'
def build(root):
    root=Path(root);db=root/'data.db';c=sqlite3.connect(db)
    c.executescript('''CREATE TABLE events_changes(seq INTEGER,workspace TEXT,subject_type TEXT,subject_id INTEGER,summary TEXT,occurred_at TEXT,recorded_at TEXT,source TEXT);
CREATE TABLE work_tasks(id INTEGER,workspace TEXT,number TEXT,title TEXT,status TEXT,updated_at TEXT,source TEXT,problem TEXT);
CREATE TABLE work_links(workspace TEXT,subject_id INTEGER,subject_type TEXT,target_id INTEGER,target_type TEXT,relation TEXT);
CREATE TABLE work_incidents(id INTEGER,workspace TEXT,number TEXT,title TEXT,root_cause TEXT,source TEXT,ended_at TEXT,status TEXT);
CREATE TABLE work_measures(id INTEGER,workspace TEXT,name TEXT,unit TEXT);
CREATE TABLE work_measure_history(measure INTEGER,workspace TEXT,as_of TEXT,value REAL);
CREATE TABLE base_capabilities(id INTEGER,workspace TEXT,name TEXT,status TEXT,card_path TEXT);''')
    for ws in ('shop','personal','practice'):
        c.execute('INSERT INTO events_changes VALUES (1,?,?,?,?,?,?,?)',(ws,'task',1,'stock checked','2026-10-13T09:00:00-04:00',AT,'receipt:1'))
        c.executemany('INSERT INTO work_tasks VALUES (?,?,?,?,?,?,?,?)',[(1,ws,'T1','blocked work','blocked',AT,'task:1','supplier'),(2,ws,'T2','next work','todo',AT,'task:2',None),(3,ws,'T3','old task','replaced',AT,'task:3',None)])
        c.execute('INSERT INTO work_links VALUES (?,?,?,?,?,?)',(ws,1,'task',2,'task','blocks'))
        c.executemany('INSERT INTO work_incidents VALUES (?,?,?,?,?,?,?,?)',[(1,ws,'I1','closed finding','late supplier','evidence:1',AT,'closed'),(2,ws,'I2','hypothesis','model guess',None,None,'open')])
        c.execute('INSERT INTO work_measures VALUES (1,?,?,?)',(ws,'delivery','days'))
        c.executemany('INSERT INTO work_measure_history VALUES (?,?,?,?)',[(1,ws,'2026-10-12',2.0),(1,ws,'2026-10-14',4.0)])
        c.execute('INSERT INTO base_capabilities VALUES (1,?,?,?,?)',(ws,'sample','live','tools/cli/sample.md'))
    c.commit();c.close()
    card=root/'tools/cli/sample.md';card.parent.mkdir(parents=True);card.write_text('# Accepted procedure\nUse the named command.\n')
    return db,{'tools/cli/sample.md':hashlib.sha256(card.read_bytes()).hexdigest()}
