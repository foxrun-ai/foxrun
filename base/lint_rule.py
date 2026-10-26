#!/usr/bin/env python3
"""Add one rule of an existing kind after a good and bad fixture prove it."""
import argparse
import csv
import hashlib
from pathlib import Path
import shutil
import sys
import tempfile
from lint import Lint, KINDS, POLICY, protected

FIELDS = ['id', 'words', 'kind', 'scope', 'level']

def grow(policy, rule, task, evidence, good, bad, write=False):
    if not task.strip() or not evidence.is_file() or protected(evidence) or evidence.is_symlink():
        raise ValueError('A task and a readable finding source are required.')
    if rule['kind'] not in KINDS or rule['level'] not in ('error','warning'):
        raise ValueError('Use an existing kind and severity.')
    if not rule['id'].strip() or any('\t' in str(v) or '\n' in str(v) for v in rule.values()):
        raise ValueError('Rule cells cannot contain tabs or newlines.')
    Lint.validate_scope(rule['scope'])
    if policy.is_symlink() or protected(policy):
        raise ValueError('Unsafe policy folder.')
    with (policy/'rules.tsv').open() as stream:
        reader = csv.DictReader(stream, delimiter='\t')
        rows = list(reader); columns = reader.fieldnames
    rule = dict(rule)
    if 'write' in columns:rule.setdefault('write', 'warning')
    if any(row['id']==rule['id'] for row in rows):
        raise ValueError('Rule ID already exists; edit it with reviewed fixtures instead.')
    with tempfile.TemporaryDirectory() as temporary:
        candidate=Path(temporary)/'policy'
        shutil.copytree(policy,candidate,symlinks=True)
        with (candidate/'rules.tsv').open('a') as stream:
            csv.DictWriter(stream,fieldnames=columns,delimiter='\t',lineterminator='\n').writerow(rule)
        passed=Lint(good[0],good[1],candidate).run(rule['id'])
        failed=Lint(bad[0],bad[1],candidate).run(rule['id'])
        if passed or not failed:
            raise ValueError('Good fixture must pass; bad fixture must produce a finding.')
        if any('cannot complete' in r['what'].lower() for r in failed):
            raise ValueError('Bad fixture must fail the rule, not a missing input.')
        if write:
            # Only the explicit --write path changes the selected policy; fixtures never change.
            source_hash=hashlib.sha256(evidence.read_bytes()).hexdigest()
            record=dict(id=rule['id'],task=task,evidence='evidence/'+source_hash+'.txt',sha256=source_hash,good='0 findings',bad=str(len(failed))+' findings')
            ledger=policy/'rule-evidence.tsv'
            if not ledger.is_file() or ledger.is_symlink():
                raise ValueError('The evidence ledger must exist before adding a rule.')
            archive=policy/record['evidence']
            if archive.parent.is_symlink() or archive.is_symlink():
                raise ValueError('The evidence archive cannot be linked.')
            archive.parent.mkdir(exist_ok=True)
            if archive.exists() and hashlib.sha256(archive.read_bytes()).hexdigest()!=source_hash:
                raise ValueError('The retained evidence hash differs.')
            if not archive.exists():shutil.copyfile(evidence,archive)
            shutil.copyfile(candidate/'rules.tsv',policy/'rules.tsv')
            with ledger.open('a') as stream:
                csv.DictWriter(stream,fieldnames=list(record),delimiter='\t',lineterminator='\n').writerow(record)
    return dict(good=0,bad=len(failed),written=write)

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--policy',type=Path,default=POLICY)
    for name in ('id','words','kind','scope','task'):p.add_argument('--'+name,required=True)
    p.add_argument('--level',default='error')
    p.add_argument('--evidence',type=Path,required=True)
    for name in ('good-home','good-workspaces','bad-home','bad-workspaces'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--write',action='store_true')
    a=p.parse_args(argv)
    try:
        result=grow(a.policy,{k:getattr(a,k) for k in FIELDS},a.task,a.evidence,
                    (a.good_home,a.good_workspaces),(a.bad_home,a.bad_workspaces),a.write)
        print(result);return 0
    except (OSError,ValueError) as error:print('FAIL '+str(error),file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())
