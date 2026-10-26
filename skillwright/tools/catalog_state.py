#!/usr/bin/env python3
"""Approve canonical catalog bytes and plan named shipping through the real catalog alias."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def digest(payload):return hashlib.sha256(payload).hexdigest()
def state_home(dojo,state=None):return Path(state or os.environ.get('SKILL_STATE_ROOT',str(Path(dojo)/'skill-state')))
def canonical(dojo):
    dojo=Path(dojo).resolve();alias=dojo/'config/catalog.yaml'
    if alias.is_symlink() and alias.resolve()!=dojo.parent/'config/catalog.yaml':
        raise RuntimeError('Catalog alias must point to ../../config/catalog.yaml; preserve it and use the canonical owner.')
    return alias.resolve()

def parse(payload):
    raw=json.loads(payload)
    if not isinstance(raw,dict) or raw.get('version')!=1 or not isinstance(raw.get('where',{}),dict):
        raise RuntimeError('Catalog needs version 1 and a where mapping.')
    for name,value in raw.get('where',{}).items():
        if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9._-]*',name):raise RuntimeError('Unsafe catalog skill name.')
        if value!='off' and not (isinstance(value,list) and value and len(set(value))==len(value) and all(isinstance(x,str) and re.fullmatch(r'[a-z0-9][a-z0-9-]*',x) for x in value)):
            raise RuntimeError('where must be off or a nonempty workspace list: '+name)
    return raw

def atomic(path,payload,mode=0o644):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name('.'+path.name+'.'+str(os.getpid())+'.tmp')
    with temporary.open('xb') as stream:stream.write(payload);stream.flush();os.fsync(stream.fileno())
    temporary.chmod(mode);os.replace(temporary,path)

def snapshot(state,payload):
    ident=digest(payload);path=Path(state)/'catalog/approved'/(ident+'.json')
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if path.read_bytes()!=payload:raise RuntimeError('Approved catalog snapshot changed.')
    else:atomic(path,payload,0o444)
    return ident

def approve_existing(dojo,by,state=None,previous=None):
    """Record an explicitly approved baseline. Used by installation and isolated fixtures."""
    path=canonical(dojo);payload=path.read_bytes();parse(payload);state=state_home(dojo,state)
    ident=snapshot(state,payload)
    record=dict(version=1,digest=ident,previous=previous,canonical_path=str(path),by=by)
    atomic(state/'catalog-approved.json',(json.dumps(record,indent=2,sort_keys=True)+'\n').encode())
    return record

def approved_catalog(dojo,state=None,expected=None):
    path=canonical(dojo);payload=path.read_bytes();raw=parse(payload);state=state_home(dojo,state)
    if (state/'catalog-transaction.json').exists():
        raise RuntimeError('Catalog transaction is incomplete; preserve its snapshots and resolve it before shipping.')
    approval=state/'catalog-approved.json'
    # Standalone regular-file fixtures may use their committed catalog. Installed aliases require approval.
    if not approval.is_file() and not (Path(dojo)/'config/catalog.yaml').is_symlink():
        if expected and expected!=digest(payload):raise RuntimeError('Catalog version changed before shipping.')
        return raw,digest(payload),None
    if not approval.is_file():raise RuntimeError('Catalog has no approved version; use the canonical catalog owner.')
    record=json.loads(approval.read_text());ident=record['digest']
    old=state/'catalog/approved'/(ident+'.json')
    if record.get('version')!=1 or record.get('canonical_path')!=str(path) or not old.is_file() or digest(old.read_bytes())!=ident or payload!=old.read_bytes():
        raise RuntimeError('Canonical catalog differs from its approved snapshot; use the catalog owner.')
    if expected and expected!=ident:raise RuntimeError('Catalog version changed before shipping; retry the current owner notification.')
    return raw,ident,record

def changed_skills(old,new):
    a,b=old.get('where',{}),new.get('where',{})
    return sorted(name for name in set(a)|set(b) if a.get(name)!=b.get(name))

@contextmanager
def lifecycle(dojo):
    path=state_home(dojo)/'lifecycle.lock';path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+') as stream:
        try:fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('Skill lifecycle is busy; retry the catalog change later.')
        try:yield
        finally:fcntl.flock(stream.fileno(),fcntl.LOCK_UN)

def apply_catalog(dojo,payload,expected,by):
    """The canonical owner writes once and hands the exact approved version to the trigger."""
    if not by.strip():raise RuntimeError('Catalog changes need a named actor.')
    parse(payload);dojo=Path(dojo).resolve()
    with lifecycle(dojo):
        _,old,record=approved_catalog(dojo)
        if old!=expected:raise RuntimeError('Catalog changed after review; rebase the proposal.')
        if digest(payload)==old:return dict(changed=False,digest=old,previous=record.get('previous') if record else None,notification='Use notify to retry the approved version.')
        state=state_home(dojo);snapshot(state,canonical(dojo).read_bytes());new=snapshot(state,payload)
        # Preserve a recoverable transaction if either atomic write fails. No trigger can use mismatched bytes.
        atomic(state/'catalog-transaction.json',json.dumps(dict(before=old,after=new,by=by)).encode())
        atomic(canonical(dojo),payload)
        approve_existing(dojo,by,state=state,previous=old)
        (state/'catalog-transaction.json').unlink()
    notify(dojo,new)
    return dict(changed=True,digest=new,previous=old,notification='started')

def notify(dojo,expected):
    dojo=Path(dojo).resolve()
    _,ident,record=approved_catalog(dojo,expected=expected)
    if record is None or not record.get('previous'):raise RuntimeError('Approved version has no prior snapshot to notify.')
    subprocess.run([str(dojo/'tools/skill-ship-trigger.sh'),'catalog-change',record['previous'],ident],
                   cwd=dojo,env=dict(os.environ,SKILLS_DOJO_ROOT=str(dojo)),check=True)
    return dict(digest=ident,notification='started')

def trigger_plan(dojo,hook,base,previous,expected,source=None):
    raw,ident,record=approved_catalog(dojo,expected=expected or None)
    if hook=='catalog-change':
        if record is None or record.get('previous')!=previous:raise RuntimeError('Catalog notification does not match its approved prior snapshot.')
        path=state_home(dojo)/'catalog/approved'/(previous+'.json')
        payload=path.read_bytes()
        if digest(payload)!=previous:raise RuntimeError('Approved prior catalog snapshot changed.')
        names=changed_skills(parse(payload),raw)
    else:
        # The changed skills come from the repository that was committed: the Dojo or the person's source.
        result=subprocess.run(['git','-C',str(source or dojo),'diff','--no-renames','--name-only',base,'HEAD'],text=True,capture_output=True,check=True)
        changed=set(result.stdout.splitlines())
        names={path.split('/')[1] for path in changed if path.startswith('skills/') and len(path.split('/'))>2}
        # This dependency matches the one explicitly approved source alias and release packager.
        standard_dependents={'standards/skill-law.md': ('skillify',)}
        for path,dependents in standard_dependents.items():
            if path in changed:names.update(dependents)
        names=sorted(names)
    for name in names:
        if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9._-]*',name):raise RuntimeError('Unsafe changed skill name.')
    return ident,names

def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    plan=sub.add_parser('trigger-plan');plan.add_argument('--dojo',required=True);plan.add_argument('--hook',required=True)
    plan.add_argument('--base',default='');plan.add_argument('--source',default='');plan.add_argument('--previous',default='');plan.add_argument('--expected',default='')
    args=parser.parse_args()
    try:
        ident,names=trigger_plan(Path(args.dojo),args.hook,args.base,args.previous,args.expected,Path(args.source) if args.source else None)
        print(ident)
        for name in names:print(name)
    except (RuntimeError,ValueError,OSError,subprocess.SubprocessError) as error:
        print('catalog trigger: '+str(error),file=sys.stderr);return 1
    return 0
if __name__=='__main__':raise SystemExit(main())
