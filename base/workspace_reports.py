#!/usr/bin/env python3
"""Build ops and frozen daily history from an explicitly bound, read-only workspace database."""
import argparse
import csv
from collections import defaultdict
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import tempfile
from urllib.parse import quote
from page_indexes import cell, safe

BUILT='<!-- Built by workspace_reports.py. Do not edit. -->'
ALIASES={'goals':('work_goals','goals'),'programs':('work_programs','programs'),'streams':('work_projects','projects'),
    'tasks':('work_tasks','tasks'),'measures':('work_measures','measures'),'measure_history':('work_measure_history','measure_history'),
    'decisions':('base_decisions','decisions'),'issues':('work_bugs','bugs'),'functions':('work_functions','functions')}
CLOSED={'done','canceled','cancelled','superseded','replaced','dropped'}

def sha(body):return hashlib.sha256(body.encode('utf-8')).hexdigest()
def q(name):return '"'+name.replace('"','""')+'"'
def label(row):return row.get('title') or row.get('name') or row.get('id')
def mdlink(path,page,name):return '[%s](%s)'%(cell(name),quote(os.path.relpath(str(path),str(page.parent)),safe='/.-_'))
def header(kind,ws,title,day):return [BUILT,'---','type: '+kind,'workspace: '+ws.name,'timestamp: '+day+'T00:00:00Z','---','# '+title,'']
def table(lines,title,columns,rows):
    if title:lines += ['## '+title,'']
    lines += ['| '+' | '.join(columns)+' |','|'+'|'.join('---' for _ in columns)+'|']
    lines += ['| '+' | '.join(cell(value if value not in (None,'') else '(unknown)') for value in row)+' |' for row in rows]
    lines += ['']

class Source:
    def __init__(self,path,workspace):
        self.path=Path(path);self.workspace=workspace
        if self.path.is_symlink() or not self.path.is_file():raise ValueError('Database must be a regular file: '+str(path))
        self.connection=sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',uri=True)
        self.connection.row_factory=sqlite3.Row;self.connection.execute('PRAGMA query_only=ON');self.connection.execute('BEGIN')
        self.tables={r[0] for r in self.connection.execute("select name from sqlite_schema where type in ('table','view')")}
    def close(self):self.connection.close()
    def rows(self,name):
        table=next((t for t in ALIASES.get(name,(name,)) if t in self.tables),None)
        if not table:return []
        columns=[r[1] for r in self.connection.execute('pragma table_info('+q(table)+')')]
        if 'workspace' in columns:
            result=[dict(r) for r in self.connection.execute('select * from '+q(table)+' where workspace=?',(self.workspace,))]
        else:
            # A legacy database belongs to the one workspace named by the caller. Never reuse it for another workspace.
            result=[dict(r) for r in self.connection.execute('select * from '+q(table))]
        filtered=[]
        foreign_projects=set()
        if table in ('activity','work_changes') and 'projects' in self.tables:
            for project in self.connection.execute('select id,extra from projects'):
                try:owner=json.loads(project['extra'] or '{}').get('workspace')
                except (ValueError,AttributeError):owner=None
                if owner and owner!=self.workspace:foreign_projects.add(project['id'])
        for row in result:
            if row.get('subject_type')=='project' and row.get('subject_id') in foreign_projects:continue
            try:owner=json.loads(row.get('extra') or '{}').get('workspace')
            except (ValueError,AttributeError):owner=None
            if not owner or owner==self.workspace:filtered.append(row)
        return sorted(filtered,key=lambda r:(str(r.get('id','')),json.dumps(r,sort_keys=True,default=str)))

def function_paths(ws,rows):
    paths={};by_id={r['id']:r for r in rows}
    def stem(row):
        name=Path(row.get('page') or '').stem or str(row.get('name') or row['id'])
        result=re.sub(r'[^a-z0-9]+','-',name.lower()).strip('-')
        if not result or not safe(result):raise ValueError('Invalid function page name')
        return result
    for row in rows:
        root=row;seen=set()
        while root.get('parent') in by_id:
            if root['id'] in seen:raise ValueError('Function parent cycle')
            seen.add(root['id']);root=by_id[root['parent']]
        paths[row['id']]=ws/'ops/functions'/stem(root)/(stem(row)+'.md')
    if len(set(paths.values()))!=len(rows):raise ValueError('Duplicate function page paths')
    return paths

def events(source,day):
    # Preserve every activity field. Blank action words remain unknown, not invented actions.
    name=next((n for n in ('work_changes','activity') if n in source.tables),None)
    if not name:raise ValueError('No supported event table in '+str(source.path))
    rows=source.rows(name);groups=defaultdict(list);invalid=[]
    for row in rows:
        raw=row.get('occurred_at') or row.get('at');key=str(raw or '')[:10]
        try:datetime.strptime(key,'%Y-%m-%d')
        except ValueError:invalid.append(row);continue
        if key<=day:groups[key].append(row)
    for key in groups:groups[key].sort(key=lambda r:(str(r.get('occurred_at') or r.get('at')),str(r.get('seq') or r.get('id'))))
    return name,groups,invalid

def event_words(row,summary=True):
    verb=row.get('action') or row.get('verb') or '(action unknown)'
    subject=str(row.get('subject_type') or '(subject unknown)')+' '+str(row.get('subject_id') or '')
    field='.'+str(row['field']) if row.get('field') else ''
    words=str(row.get('summary') or row.get('note') or '') if summary else ''
    return verb+' '+subject+field+(': '+words if words else '')

def history_pages(ws,source,day,output_root=None):
    destination=output_root or ws
    name,groups,invalid=events(source,day);pages={};manifest_path=destination/'history/daily/frozen.json'
    old=json.loads(manifest_path.read_text()) if manifest_path.is_file() else {'days':{}}
    manifest={'format':'foxrun-frozen-daily/v1','workspace':ws.name,'source_table':name,'days':{}}
    for date,rows in sorted(groups.items()):
        target=destination/'history/daily'/(date+'.md')
        fingerprint=hashlib.sha256(json.dumps(rows,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        previous=old.get('days',{}).get(date)
        if previous:
            if previous['events_sha256']!=fingerprint:raise ValueError('Frozen source rows changed for '+date)
            if not target.is_file() or sha(target.read_text())!=previous['page_sha256']:raise ValueError('Frozen page was edited: '+str(target))
            pages[target]=target.read_text();manifest['days'][date]=previous;continue
        lines=header('log',ws,'History: '+date,date)+['Event rows for this day. Their original dates and action words stay unchanged.','']
        lines += ['Source: '+mdlink(source.path,target,name)+'.','']
        table(lines,'Events',['Event','Time','What happened','By'],[[r.get('seq') or r.get('id'),r.get('occurred_at') or r.get('at'),event_words(r),r.get('actor') or r.get('author')] for r in rows])
        body='\n'.join(lines)+'\n';pages[target]=body
        if date<day:manifest['days'][date]={'events_sha256':fingerprint,'page_sha256':sha(body),'rows':len(rows),'frozen_before':day}
    # Missing or removed frozen days are never silently retired.
    for date,entry in old.get('days',{}).items():
        if date not in manifest['days']:raise ValueError('Frozen event day disappeared: '+date)
    pages[manifest_path]=json.dumps(manifest,sort_keys=True,indent=2)+'\n'
    target=destination/'history/LOG.md';dates=sorted(groups,reverse=True);total=sum(map(len,groups.values()))
    lines=header('log',ws,'Log: '+ws.name,day)+['This page is built from event rows in the bound workspace database.','', '```',
        'ENTRIES            '+str(total+len(invalid)),'WITH NO DATE       '+str(len(invalid)),'DAYS WITH AN ENTRY  '+str(len(dates)),
        'FIRST              '+(min(dates) if dates else '(unknown)'), 'NEWEST             '+(max(dates) if dates else '(unknown)'), 'MADE               '+day+' 00:00','```','', '## The 5 newest days','']
    for date in dates[:5]:
        lines += ['### '+date,'',mdlink(destination/'history/daily'/(date+'.md'),target,date),'']
        table(lines,None,['Time','What happened','By','Tag'],[[r.get('occurred_at') or r.get('at'),event_words(r,False),r.get('actor') or r.get('author'),r.get('subject_type')] for r in groups[date]])
    months=defaultdict(lambda:[0,0])
    for date in dates[5:]:months[date[:7]][0]+=len(groups[date]);months[date[:7]][1]+=1
    table(lines,'Older',['Month','Entries','Days with an entry'],[[month,*counts] for month,counts in sorted(months.items(),reverse=True)])
    pages[target]='\n'.join(lines)+'\n'
    return pages,{'source_table':name,'events':total,'undated_events':len(invalid),'days':len(groups),'frozen_days':len(manifest['days']), 'unknown_actions':sum(not (r.get('action') or r.get('verb')) for rs in groups.values() for r in rs)}

def render(workspace,source,day,seat=None,session=None,output_root=None):
    destination=output_root or workspace
    data={key:source.rows(key) for key in ALIASES};pages={};functions=data['functions'];paths=function_paths(destination,functions)
    aliases={};catalog=workspace/'config/report-labels.tsv'
    if catalog.is_file():
        with catalog.open(newline='') as stream:
            for row in csv.DictReader(stream,delimiter='\t'):
                if not row.get('source'):raise ValueError('A report display label requires its source.')
                aliases[(row['id'],row['field'],row['source_value'])]=row['display_value']
    def display(row):
        for field in ('title','name'):
            value=row.get(field);name=aliases.get((row.get('id'),field,value))
            if name:return name+' (stored '+field+': `'+value+'`)'
        return label(row)
    for kind in ('goals','programs','streams','tasks','measures','decisions','issues'):
        target=destination/'ops'/(kind+'.md');records=data[kind]
        lines=header('index',workspace,kind.title()+': '+workspace.name,day)+['This page is built from source rows. Change a row, then rebuild this page.','', 'Source: '+mdlink(source.path,target,'Database')+'.','']
        if kind=='measures':
            history=data['measure_history'];measure_rows=[]
            for row in records:
                observations=[r for r in history if r.get('measure')==row['id'] and str(r.get('as_of') or '')[:10]<=day]
                latest=max(observations,key=lambda r:(str(r.get('as_of')),str(r.get('id')))) if observations else {}
                measure_rows.append([display(row),latest.get('value'),latest.get('as_of'),row.get('target')])
            table(lines,'Rows',['Measure','Observed','Date','Target'],measure_rows)
        else:
            fields=['id','title' if any('title' in r for r in records) else 'name','status','project' if kind=='tasks' else 'owner']
            table(lines,'Rows',['ID',kind.title()[:-1] if kind.endswith('s') else kind.title(),'Status','Stream' if kind=='tasks' else 'Owner'],[[display(r) if k in ('title','name') else r.get(k) for k in fields] for r in records])
        pages[target]='\n'.join(lines)+'\n'
    for row in functions:
        target=paths[row['id']];lines=header('index',workspace,str(row.get('name') or row['id']),day)+['This page is built from the function row and its work rows.','']
        table(lines,'Function',['Field','Value'],[['ID',row['id']],['Owner',row.get('owner')],['Parent',row.get('parent')]])
        related=[r for r in data['tasks'] if r.get('function')==row['id'] or any(p['id']==r.get('project') and p.get('function')==row['id'] for p in data['streams'])]
        table(lines,'Tasks',['Task','Title','Status','Owner'],[[r['id'],display(r),r.get('status'),r.get('owner')] for r in related])
        pages[target]='\n'.join(lines)+'\n'
    target=destination/'ops/DASHBOARD.md';programs=data['programs'];streams=data['streams'];tasks=data['tasks']
    lines=header('index',workspace,'Dashboard: '+workspace.name,day)+['This page shows the business rows and their function pages.','',
        '**Go to:** [State](../STATE.md) · [Team](../team/TEAM.md) · [Log](../history/LOG.md)','', '```','PROGRAMS        '+str(len(programs)),
        'STREAMS         '+str(len(streams)), 'FUNCTION PAGES  '+str(len(functions)),'OPEN TASKS      '+str(sum(r.get('status') not in CLOSED for r in tasks)), 'MADE            '+day+' 00:00','```','']
    table(lines,'Programs',['Program','Objective','Status'],[[display(r),r.get('objective'),r.get('status')] for r in programs])
    counts=[]
    for row in streams:
        group=[r for r in tasks if r.get('project')==row['id'] and not r.get('parent')]
        counts.append([display(row),sum(r.get('status') not in CLOSED for r in group),sum(r.get('status')=='in-review' for r in group),sum(r.get('status')=='done' for r in group)])
    table(lines,'Streams',['Stream','Open','In review','Done'],counts)
    by_id={r['id']:r for r in functions}
    # Link each function page while preserving the three-column approved dashboard form.
    lines += ['## Functions','','| Function | Under | In the rows |','|---|---|---|']
    for row in functions:lines += ['| '+mdlink(paths[row['id']],target,label(row))+' | '+cell(label(by_id[row['parent']]) if row.get('parent') in by_id else 'None')+' | yes |']
    pages[target]='\n'.join(lines)+'\n'
    more,proof=history_pages(workspace,source,day,destination);pages.update(more)
    return pages,proof

def generate(workspace,db,day,check=False,output_root=None):
    source=Source(db,workspace.name)
    try:pages,proof=render(workspace,source,day,output_root=output_root)
    finally:source.close()
    stale=[];changed=0
    for path,body in pages.items():
        if path.is_symlink():raise ValueError('Linked output refused')
        if not path.is_file() or path.read_text()!=body:
            if check:stale.append(str(path))
            else:path.parent.mkdir(parents=True,exist_ok=True);path.write_text(body);changed+=1
    return {'pages':len(pages),'changed':changed,'stale':stale,**proof}

def refresh_frontmatter(workspace):
    """Repair only metadata on this builder's clean generated ops pages."""
    changed=[];held=[]
    legacy='<!-- generated: fix/z5r2/fix_rule.py; dated file tracker snapshot -->'
    for path in sorted((workspace/'ops').rglob('*.md')):
        if path.is_symlink() or not path.is_file():continue
        old=path.read_text()
        current=old.startswith(BUILT+'\n---\n')
        prior=legacy in old[:300] and not old.startswith('---\n')
        if not (current or prior):continue
        relative=path.relative_to(workspace)
        state=subprocess.run(['git','status','--porcelain=v1','--',str(relative)],
                             cwd=workspace,capture_output=True,text=True)
        if state.stdout.strip():held.append(str(relative));continue
        if current:
            boundary=old.find('\n---\n',len(BUILT)+5)
            if boundary<0:held.append(str(relative));continue
            head=old[:boundary]
            updated=re.sub(r'(?m)^workspace: .*$', 'workspace: '+workspace.name, head)
            if updated==head:continue
            new=updated+old[boundary:]
        else:
            stamp=datetime.now().astimezone().isoformat(timespec='seconds')
            new=('---\ntype: index\nworkspace: '+workspace.name+
                 '\ntimestamp: '+stamp+'\n---\n'+old)
        with tempfile.NamedTemporaryFile('w',suffix='.md',encoding='utf-8') as temp:
            temp.write(new);temp.flush()
            gate=subprocess.run(['python3',str(Path.home()/'.foxrun/base/lint_gate.py'),
                                 '--mode','write','--target',str(path),'--body',temp.name],
                                capture_output=True,text=True)
            if gate.returncode:raise ValueError('lint gate failed for '+str(relative)+': '+gate.stderr[:120])
        mode=stat.S_IMODE(path.stat().st_mode)
        try:
            if not (mode&stat.S_IWUSR):path.chmod(mode|stat.S_IWUSR)
            path.write_text(new)
        finally:
            if not (mode&stat.S_IWUSR):path.chmod(mode)
        changed.append(str(relative))
    return {'changed':changed,'held':held}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--workspace',required=True,type=Path);p.add_argument('--db',required=True,type=Path);p.add_argument('--as-of',required=True);p.add_argument('--check',action='store_true');p.add_argument('--frontmatter-only',action='store_true');p.add_argument('--output-root',type=Path,help='Store ops and history here; keep --workspace as the row scope');a=p.parse_args()
    if a.frontmatter_only:
        print(json.dumps(refresh_frontmatter(a.workspace.resolve())))
        return 0
    try:result=generate(a.workspace,a.db,a.as_of,a.check,a.output_root)
    except ValueError as e:print(json.dumps({'error':str(e)}));return 1
    print(json.dumps(result));return int(bool(result['stale'] or result['undated_events']))
if __name__=='__main__':raise SystemExit(main())
