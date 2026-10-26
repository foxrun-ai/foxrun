#!/usr/bin/env python3
"""Plan the ruled run-trail transfer. Default: read only. --move is a switch step.
Stop writers before --move. Keep an old-root link and a rollback receipt.
Disjoint same-name folders merge. Differing same-path files refuse the whole plan.
No file is deleted. Equal duplicates remain in the source backup for undo.
"""
import argparse, hashlib, json, os, tempfile, time
from pathlib import Path

BAD={'.env','.ssh','.netrc','auth.json','credentials','credentials.json','secrets','id_rsa','.git-credentials'}

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def plan(source,destination):
    source=Path(source).absolute();destination=Path(destination).absolute()
    if source==destination or source in destination.parents or destination in source.parents:
        raise ValueError('roots must be separate')
    if source.is_symlink() or destination.is_symlink():raise ValueError('root symlink refused')
    if not source.is_dir():raise ValueError('source root absent')
    rows=[];dirs=[]
    for path in sorted(source.rglob('*')):
        rel=path.relative_to(source)
        if any(part.lower() in BAD or part.lower().startswith('.env.') for part in rel.parts):
            raise ValueError('protected path in run trails; no move starts')
        target=destination/rel
        if path.is_symlink() or target.is_symlink() or any(x.is_symlink() for x in target.parents):
            raise ValueError('link in transfer; no move starts')
        if path.is_dir():
            if target.exists() and not target.is_dir():raise ValueError('directory/file collision: '+str(rel))
            dirs.append(str(rel));continue
        if not path.is_file():raise ValueError('special file refused')
        digest=sha(path)
        if target.exists() and (not target.is_file() or sha(target)!=digest):
            raise ValueError('different duplicate: '+str(rel))
        rows.append({'path':str(rel),'sha256':digest,'action':'same' if target.exists() else 'move'})
    return {'source':str(source),'destination':str(destination),'files':rows,'dirs':dirs}

def record(receipt,data):
    # A new private temporary file (mkstemp: 0600, O_EXCL), so a link planted at a fixed name is never followed.
    descriptor,tmp=tempfile.mkstemp(prefix='.'+receipt.name+'.',suffix='.tmp',dir=str(receipt.parent))
    try:
        with os.fdopen(descriptor,'w') as stream:stream.write(json.dumps(data,indent=2)+'\n')
        os.replace(tmp,receipt)
    except BaseException:
        if os.path.exists(tmp):os.unlink(tmp)
        raise

def transfer(source,destination):
    data=plan(source,destination);source=Path(data['source']);destination=Path(data['destination'])
    stamp=time.strftime('%Y%m%dT%H%M%S')
    hold=source.with_name(source.name+'.before-run-transfer-'+stamp)
    receipt=destination.parent/('run-transfer-'+stamp+'.json')
    if hold.exists() or receipt.exists():raise ValueError('receipt collision')
    data.update(backup=str(hold),moved=[],created_dirs=[],state='prepared')
    destination.mkdir(parents=True,exist_ok=True);record(receipt,data)
    try:
        for rel in data['dirs']:
            target=destination/rel
            if not target.exists():target.mkdir();data['created_dirs'].append(rel);record(receipt,data)
        for item in data['files']:
            src=source/item['path'];dst=destination/item['path']
            if sha(src)!=item['sha256']:raise ValueError('source changed before move')
            if item['action']=='same':
                if not dst.is_file() or sha(dst)!=item['sha256']:raise ValueError('duplicate changed before move')
                continue
            if dst.exists():raise ValueError('destination appeared after plan')
            dst.parent.mkdir(parents=True,exist_ok=True)
            data['pending']=item['path'];record(receipt,data)
            os.rename(src,dst);data['moved'].append(item['path']);data.pop('pending',None);record(receipt,data)
        os.rename(source,hold);data['state']='source-held';record(receipt,data)
        os.symlink(destination,source);data['state']='linked';record(receipt,data)
        return receipt
    except BaseException:
        rollback(receipt);raise

def rollback(receipt):
    receipt=Path(receipt);data=json.loads(receipt.read_text())
    source=Path(data['source']);destination=Path(data['destination']);hold=Path(data['backup'])
    moved=list(data['moved'])
    if data.get('pending'):
        name=data['pending']
        if (destination/name).exists() and not (source/name).exists():moved.append(name)
    hashes={r['path']:r['sha256'] for r in data['files']}
    # Preflight all undo content before changing the alias or any moved file.
    for name in moved:
        if not (destination/name).is_file() or sha(destination/name)!=hashes[name]:
            raise ValueError('transferred file changed; undo stops before any mutation')
    if source.is_symlink():
        if source.resolve()!=destination.resolve():raise ValueError('old-root alias changed')
        source.unlink()
    if hold.exists():
        if source.exists():raise ValueError('source root appeared; undo refused')
        os.rename(hold,source)
    for name in reversed(moved):
        target=source/name
        if target.exists():raise ValueError('undo source collision')
        target.parent.mkdir(parents=True,exist_ok=True);os.rename(destination/name,target)
    for name in reversed(data['created_dirs']):
        target=destination/name
        if target.is_dir() and not any(target.iterdir()):target.rmdir()
    data['state']='undone';record(receipt,data)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source');p.add_argument('--destination');p.add_argument('--move',action='store_true');p.add_argument('--undo');a=p.parse_args()
    if a.undo:rollback(a.undo);print('undone; receipt retained')
    elif not a.source or not a.destination:p.error('--source and --destination are required')
    elif a.move:print(transfer(a.source,a.destination))
    else:
        d=plan(a.source,a.destination);print(json.dumps({'files':len(d['files']),'move':sum(r['action']=='move' for r in d['files']),'same':sum(r['action']=='same' for r in d['files']),'writes':0},sort_keys=True))
