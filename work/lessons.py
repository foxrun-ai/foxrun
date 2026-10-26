#!/usr/bin/env python3
"""Read open lessons or file one lesson through its installed table command."""

from __future__ import annotations
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import uuid

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',required=True,type=Path);p.add_argument('--workspace');p.add_argument('--json',action='store_true')
    sub=p.add_subparsers(dest='operation',required=True);sub.add_parser('open')
    f=sub.add_parser('file');f.add_argument('--source',choices=['feedback','lesson','failure'],required=True);f.add_argument('--source-ref',required=True);f.add_argument('--subject',required=True);f.add_argument('--text',required=True);f.add_argument('--by',required=True);f.add_argument('--session',required=True)
    a=p.parse_args();root=a.root.resolve();folder=root/'code/foxrun-modules/base';sys.path.insert(0,str(folder));spec=importlib.util.spec_from_file_location('lessons_core',folder/'core.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    db=root/'home/.local/share/foxrun/data.db'
    if a.operation=='file':
        if not a.workspace:p.error('--workspace is required to file a lesson')
        c=m.connect(db,readonly=True);old=c.execute('SELECT number FROM work_lessons WHERE workspace=? AND source_ref=? AND text=?',(a.workspace,a.source_ref,a.text)).fetchone();c.close()
        if old:print(json.dumps({'changed':False,'number':old[0]}));return
        number='local:lesson:'+str(uuid.uuid4());data={'number':number,'source':a.source,'source_ref':a.source_ref,'subject':a.subject,'text':a.text,'status':'open','workspace':a.workspace}
        context={'writer':'agent','actor':a.by,'session':a.session,'workspace':a.workspace,'source':a.source_ref,'reason':'Lesson filed with its source'}
        result=m.execute(db,folder/'blueprint','work_lessons','insert',data,None,context);result['number']=number;print(json.dumps(result,sort_keys=True));return
    c=m.connect(db,readonly=True);q="SELECT number,workspace,source,source_ref,subject,text,status,codified_in,replay_case FROM work_lessons WHERE status='open'";params=()
    if a.workspace:q+=' AND workspace=?';params=(a.workspace,)
    rows=[dict(r) for r in c.execute(q+' ORDER BY workspace,number',params)];c.close()
    if a.json:print(json.dumps(rows,ensure_ascii=False,indent=2))
    else:
        for r in rows:print(r['number']+' · '+r['workspace']+' · '+r['text']+' · '+r['source_ref'])

if __name__=='__main__':main()
