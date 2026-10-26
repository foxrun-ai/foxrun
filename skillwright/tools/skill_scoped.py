#!/usr/bin/env python3
"""Record a build and ship one skill through the existing release lifecycle.

The record describes actual shelf bytes. Unpublished imports and host-owned
skills never acquire publication approval from a build snapshot.
"""
from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid
from skill_catalog import read_catalog, catalog_scope, route_plan, apply_route_plan, owned_link_matches
from datetime import datetime, timezone
from catalog_state import approved_catalog

RECORD = '.release-manifest.json'
BAD = {'.env', 'auth.json', 'credentials', 'credentials.json', 'secrets', '.netrc', '.git-credentials'}

def safe_tree(path, *, dojo=None):
    """Reject protected payloads; permit only the explicitly approved source standard alias."""
    if Path(path).is_symlink():raise RuntimeError('Unreviewed payload link; stop: '+str(path))
    for root, dirs, files in os.walk(path, followlinks=False):
        dirs[:] = [name for name in dirs if name not in {'.git', '__pycache__', '.pytest_cache', 'node_modules', '.cache'}]
        for name in dirs + files:
            p = Path(root) / name
            if name.lower() in BAD or name.lower().startswith('.env.'):
                raise RuntimeError('Protected payload; stop: ' + str(p))
            if p.is_symlink() and approved_standard(path,p,dojo) is None:
                raise RuntimeError('Unreviewed payload link; stop: ' + str(p))

def approved_standard(skill, path, dojo):
    if dojo is None:return None
    skill,path,dojo=Path(skill),Path(path),Path(dojo)
    if skill!=dojo/'skills/skillify' or path!=skill/'references/skill-law.md':return None
    if not path.is_symlink() or os.readlink(path)!='../../../standards/skill-law.md':return None
    expected=dojo/'standards/skill-law.md'
    if expected.is_symlink() or not expected.is_file() or expected.resolve()!=dojo.resolve()/'standards/skill-law.md' or path.resolve()!=expected.resolve():return None
    return expected


def reference_rewrites(source, dojo):
    """One explicit source-relative guide has a different depth inside a release."""
    source,dojo=Path(source),Path(dojo)
    if source!=dojo/'skills/clipy':return {}
    page=source/'SKILL.md';payload=page.read_bytes()
    if b'`~/.foxrun/tools/mcp/clipy.md`' in payload:
        return {}
    old=b'[Clipy](../../../tools/mcp/clipy.md)'
    new=b'[Clipy](../../../../tools/mcp/clipy.md)'
    if payload.count(old)!=1:raise RuntimeError('Clipy source guide changed; review its packaging rule.')
    return {'SKILL.md':(payload.replace(old,new),dict(source='../../../tools/mcp/clipy.md',packaged='../../../../tools/mcp/clipy.md'))}


def source_entry(tool, source, dojo):
    """Record source identity separately from the regular-file release payload."""
    source,dojo=Path(source),Path(dojo)
    safe_tree(source,dojo=dojo)
    records=tool.file_records(source);standards={}
    for index,(relative,mode,content) in enumerate(records):
        path=source/relative
        if path.is_symlink():
            target=approved_standard(source,path,dojo)
            if target is None:raise RuntimeError('Unapproved standard alias.')
            content=hashlib.sha256(target.read_bytes()).hexdigest()
            records[index]=(relative,'100644',content)
            standards[relative]=dict(source='standards/skill-law.md',digest=content)
    references={}
    for relative,(payload,rule) in reference_rewrites(source,dojo).items():
        content=hashlib.sha256(payload).hexdigest()
        for index,(name,mode,_content) in enumerate(records):
            if name==relative:records[index]=(name,mode,content);break
        else:raise RuntimeError('Packaged reference page is absent.')
        references[relative]=dict(rule,digest=content)
    digest=hashlib.sha256()
    for relative,mode,content in sorted(records):
        digest.update(relative.encode('utf-8','surrogateescape')+b'\0'+mode.encode()+b'\0'+content.encode()+b'\n')
    entry=dict(source='skills_dojo',digest=digest.hexdigest(),file_count=len(records))
    if standards or references:
        source_digest,source_count=tool.digest_tree(source)
        entry.update(source_digest=source_digest,source_file_count=source_count)
    if standards:entry['standard_snapshots']=standards
    if references:entry['reference_rewrites']=references
    return entry


def package_skill(tool, source, destination, dojo):
    """Copy links as links first; replace only the explicitly approved law alias."""
    source,destination=Path(source),Path(destination)
    expected=source_entry(tool,source,dojo)
    shutil.copytree(source,destination,symlinks=True,ignore=shutil.ignore_patterns(*tool.EXCLUDED_PARTS))
    for relative,standard in expected.get('standard_snapshots',{}).items():
        target=approved_standard(source,source/relative,dojo)
        payload=target.read_bytes()
        if hashlib.sha256(payload).hexdigest()!=standard['digest']:raise RuntimeError('Standard changed while packaging.')
        copied=destination/relative;copied.unlink();copied.write_bytes(payload);copied.chmod(0o644)
    for relative,(payload,rule) in reference_rewrites(source,dojo).items():
        if hashlib.sha256(payload).hexdigest()!=expected['reference_rewrites'][relative]['digest']:
            raise RuntimeError('Reference page changed while packaging.')
        (destination/relative).write_bytes(payload)
    safe_tree(destination)
    if tool.digest_tree(destination)!=(expected['digest'],expected['file_count']):
        raise RuntimeError('Packaged skill differs from its source/standard record.')
    return expected


def validate_standard_snapshots(skill, entry):
    for relative,standard in entry.get('standard_snapshots',{}).items():
        if Path(skill).name!='skillify' or relative!='references/skill-law.md' or standard.get('source')!='standards/skill-law.md':
            raise RuntimeError('Unapproved standard snapshot path.')
        path=Path(skill)/relative
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=standard.get('digest'):
            raise RuntimeError('Frozen standard snapshot differs: '+str(path))


def validate_reference_rewrites(skill, entry):
    for relative,rule in entry.get('reference_rewrites',{}).items():
        if Path(skill).name!='clipy' or relative!='SKILL.md' or rule.get('source')!='../../../tools/mcp/clipy.md' or rule.get('packaged')!='../../../../tools/mcp/clipy.md':
            raise RuntimeError('Unapproved packaged guide rule.')
        page=Path(skill)/relative
        if page.is_symlink() or not page.is_file() or hashlib.sha256(page.read_bytes()).hexdigest()!=rule.get('digest'):
            raise RuntimeError('Packaged guide differs from its approved content.')


def skill_names(shelf):
    return sorted(p.name for p in shelf.iterdir() if p.is_dir() and (p / 'SKILL.md').is_file())

def record_digest(skills):
    return hashlib.sha256(json.dumps(skills, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def record_for(tool, source, shelf, source_name, shelf_name):
    policy = read_catalog(source / 'config/catalog.yaml', source)
    raw_policy = (source / 'config/catalog.yaml').read_bytes()
    head = subprocess.run(['git', '-C', str(source), 'rev-parse', 'HEAD'],
                          check=True, capture_output=True, text=True).stdout.strip()
    skills = {}
    for name in skill_names(shelf):
        safe_tree(shelf / name)
        digest, count = tool.digest_tree(shelf / name)
        authored = source / 'skills' / name
        if name in policy['publish']:
            safe_tree(authored,dojo=source)
            source_kind = 'skills_dojo'
        elif name in policy['host_specific']:
            source_kind = 'host_snapshot'
        else:
            raise RuntimeError('Shelf skill has no publication classification: ' + name)
        skills[name] = dict(source=source_kind, digest=digest, file_count=count)
        if source_kind == 'skills_dojo':
            predicted=source_entry(tool,authored,source)
            if (predicted['digest'],predicted['file_count'])==(digest,count):skills[name]=predicted
            else:
                source_digest,source_count=tool.digest_tree(authored)
                skills[name].update(source_digest=source_digest,source_file_count=source_count,
                                    source_drift='hold until the owner reconciles these extra source files')
    if set(policy['publish']) - set(skills):
        raise RuntimeError('Published source is absent from shelf: ' + ', '.join(sorted(set(policy['publish']) - set(skills))))
    release_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + head[:12]
    return dict(version=3, kind='build_snapshot', release_id=release_id,
                dojo_commit=head, candidate=str(source_name), active_shelf=str(shelf_name),
                policy=dict(version=policy['version'], path=str(Path(source_name) / 'config/catalog.yaml'),
                            digest=hashlib.sha256(raw_policy).hexdigest()),
                skills=skills, excluded=policy['exclude'], digest=record_digest(skills),
                canary_checklist=tool.canary_checklist(), runtime_canaries='pending')

def pin_path():
    return Path(os.environ.get('SKILLS_PIN_PATH', '~/.foxrun/agents/execution/skills.yaml')).expanduser()

def validate_record(tool, shelf):
    record = tool.load_json(shelf / RECORD)
    if record.get('version') != 3 or record.get('digest') != record_digest(record['skills']):
        raise RuntimeError('The release record is invalid. Stop.')
    if skill_names(shelf) != sorted(record['skills']):
        raise RuntimeError('Shelf membership differs from its release record. Stop.')
    for name, entry in record['skills'].items():
        safe_tree(shelf / name)
        validate_standard_snapshots(shelf/name,entry)
        validate_reference_rewrites(shelf/name,entry)
        if tool.digest_tree(shelf / name) != (entry['digest'], entry['file_count']):
            raise RuntimeError('Shelf bytes differ from the release record: ' + name)
    return record

def record_build(tool, args):
    source, shelf, output = Path(args.source), Path(args.shelf), Path(args.output)
    record = record_for(tool, source, shelf, args.record_source or source, args.record_shelf or shelf)
    output.mkdir(parents=True, exist_ok=True)
    tool.write_json(output / RECORD, record)
    tool.write_json(output / 'shipped.yaml', record)
    tool.write_json(output / 'skills.yaml', dict(gaps=[], release=record['release_id']))
    # This describes the existing directory. It does not fabricate link activation.
    tool.write_json(output / 'release-state.json', dict(version=1, scoped=True, release_id=record['release_id'],
                    current=dict(kind='directory', path=record['active_shelf']), previous=None))
    tool.write_json(output / 'receipt.json', dict(version=1, result='build_snapshot', release_id=record['release_id'],
                    source_commit=record['dojo_commit'], digest=record['digest'], skill_count=len(record['skills']),
                    runtime_canaries='pending', activated=False))
    print('build record ' + record['release_id'] + '; skills=' + str(len(record['skills'])) + '; digest=' + record['digest'])
    return 0

def load_skillify(tool):
    path = tool.source_home('skillify')[0] / 'skills/skillify/bin/skillify'
    loader = importlib.machinery.SourceFileLoader('scoped_skillify', str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module

def json_snapshot(path):
    return path.read_text() if path.is_file() else None

def restore_json(tool, path, content):
    if content is None:
        if path.exists():
            path.unlink()
    else:
        tool.write_json(path, json.loads(content))

def read_transaction(tool):
    recover_workspace(tool)
    path = tool.STATE / 'scoped-transaction.json'
    if not path.is_file():
        return
    transaction = tool.load_json(path)
    # Recovery always restores the exact pre-ship directory/link and metadata.
    previous = transaction['previous']
    if tool.ACTIVE.is_symlink() and tool.ACTIVE.resolve() not in {
            Path(transaction['candidate']), Path(previous['path'])}:
        raise RuntimeError('The shelf changed outside this transaction. Stop recovery.')
    for value in transaction.get('links_created', []):
        link = Path(value)
        if link.is_symlink() and os.readlink(link) == str(tool.ACTIVE / transaction['skill']):
            link.unlink()
    if tool.ACTIVE.is_symlink():
        tool.ACTIVE.unlink()
    if previous['kind'] == 'directory':
        storage = Path(previous['path'])
        if storage.exists() and not tool.ACTIVE.exists():
            os.rename(storage, tool.ACTIVE)
    elif not tool.ACTIVE.exists():
        tool.switch_link(Path(previous['path']))
    restore_workspace_routes(tool, transaction)
    restore_json(tool, tool.DIST, transaction['distribution_before'])
    restore_json(tool, pin_path(), transaction['pin_before'])
    restore_json(tool, tool.STATE_FILE, transaction['state_before'])
    path.unlink()

def name_policy(tool, name):
    """Read the catalog against the repo that holds the skill, so a person-owned skill keeps its scope."""
    return read_catalog(tool.POLICY, tool.source_home(name)[0])

def target_policy(tool, name, *, preview=False):
    if not tool.SAFE_ID.fullmatch(name) or name != Path(name).name:
        raise RuntimeError('Unsafe skill name. Stop.')
    policy = name_policy(tool, name)
    if name not in policy.get('publish', []) and name not in policy.get('workspace_publish', {}):
        raise RuntimeError('This skill has no single publication approval. Stop: ' + name)
    # The person's source wins over a product skill with the same name.
    home, _owner = tool.source_home(name)
    path = home / 'skills' / name
    safe_tree(path,dojo=home)
    alias=path/'references/skill-law.md'
    if approved_standard(path,alias,home) and tool.git_in(home,'status','--porcelain','--','standards/skill-law.md'):
        raise RuntimeError('Commit the approved standard before shipping.')
    tool.validate_frontmatter(path / 'SKILL.md')
    relative = 'skills/' + name + '/'
    if tool.git_in(home, 'status', '--porcelain', '--', relative):
        raise RuntimeError('Commit the checked skill before shipping: ' + name)
    # Validate the named skill, never the unrelated imports or host catalog.
    skillify = load_skillify(tool)
    changed = not (preview and os.environ.get('SKILLIFY_PREVIEW_CHANGED') == '0')
    skillify.check_law(home, name, changed=changed)
    skillify.run_replays(home, name)
    skillify.run_skill_tests(path)
    return path, policy

def check_consumer(tool, root, name, label, *, allow_missing=False):
    target = root / name
    expected = (tool.ACTIVE / name).resolve()
    if root.is_symlink():
        if allow_missing and root.resolve() == tool.ACTIVE.resolve() and not target.exists() and not target.is_symlink():
            return
        valid = root.resolve() == tool.ACTIVE.resolve() and target.is_dir() and target.resolve() == expected
    elif not target.exists() and not target.is_symlink() and allow_missing:
        return
    else:
        valid = target.is_symlink() and target.is_dir() and target.resolve() == expected
    if not valid:
        raise RuntimeError(label + ' has no stable shelf link for ' + name + '. Stop and restore the shelf.')

def refresh_workspace_views(tool):
    """Update the installed workspace views after a shelf release changes skill rows."""
    home = tool.DOJO.parent
    script = home / 'base/make_workspaces_view.py'
    if not script.is_file():
        return  # An isolated skill release fixture has no installed workspace builder.
    portfolio = Path(os.environ.get('FOXRUN_PORTFOLIO', '~/foxrun')).expanduser()
    result = subprocess.run([sys.executable, '-B', str(script), '--system-home', str(home),
                             '--workspace-root', str(portfolio)], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('workspace views did not refresh: ' + (result.stderr or result.stdout).strip())
    check = subprocess.run([sys.executable, '-B', str(script), '--system-home', str(home),
                            '--workspace-root', str(portfolio), '--check'], capture_output=True, text=True)
    if check.returncode:
        raise RuntimeError('workspace views stayed stale: ' + (check.stderr or check.stdout).strip())


def ship_one(tool, args):
    with tool.lifecycle_lock():
        read_transaction(tool)
        catalog_version = approved_catalog(tool.DOJO, state=tool.STATE, expected=os.environ.get('SKILLS_CATALOG_DIGEST'))[1]
        name = args.skill
        if not tool.SAFE_ID.fullmatch(name) or name != Path(name).name:
            raise RuntimeError('Unsafe skill name.')
        before = validate_record(tool, tool.ACTIVE) if (tool.ACTIVE / RECORD).is_file() else None
        removed = tool.removed_person_skills(before) if before else []
        retiring = name in removed
        if before and not removed and name in before.get('removed', []) and name not in before['skills']:
            if not (tool.source_home(name)[0] / 'skills' / name / 'SKILL.md').is_file():
                print('no-op: ' + name + ' already removed; release ' + before['release_id'])
                return 0
        if not retiring and before and name in before['skills']:
            if not (tool.source_home(name)[0] / 'skills' / name / 'SKILL.md').is_file():
                raise RuntimeError('Released skill has no source or proven person retirement: ' + name)
        if retiring:
            source, policy = None, {}
        else:
            scope_policy = name_policy(tool, name)
            # Scope reads the repo that holds the skill; a person-owned skill is not off.
            if catalog_scope(scope_policy, name, tool.source_home(name)[0]) == 'off':
                return ship_workspace(tool, args, None, scope_policy, catalog_version)
            source, policy = target_policy(tool, name, preview=args.dry_run)
        if args.dry_run:
            print('dry-run: checked ' + name + '; no shelf, runtime, pin, or release write')
            return 0
        if name in policy.get('workspace_publish', {}):
            return ship_workspace(tool, args, source, policy, catalog_version)
        if tool.git('status', '--porcelain', '--', 'config/catalog.yaml'):
            raise RuntimeError('Commit the catalog before shipping.')
        home, owner = (tool.PERSON, 'person') if retiring else tool.source_home(name)
        preflight = tool.ship_preflight(repo=home)
        if removed and home != tool.PERSON:
            tool.ship_preflight(repo=tool.PERSON)
        before = validate_record(tool, tool.ACTIVE)
        if before['skills'].get(name, {}).get('owner') == 'person' and owner != 'person':
            raise RuntimeError('This released skill is the person\'s; a product copy never replaces it. Restore its source: ' + name)
        route_state, route_owned, retire_plan = retiring_workspace_routes(tool, name)
        for root, label in ((tool.CLAUDE, 'Claude'), (tool.CODEX, 'Codex'), (tool.AGENTS, 'Agents')):
            if not retiring:
                check_consumer(tool, root, name, label, allow_missing=True)
        held = before['skills'].get(name, {})
        # A drift hold lasts until the owner changes the held source; the same source stays refused.
        if not retiring and held.get('source_drift') and tool.digest_tree(source) == (held.get('source_digest'), held.get('source_file_count')):
            raise RuntimeError('This skill has extra unshipped source files. Ask its owner to reconcile them: ' + name)
        if tool.load_json(tool.DIST) != before or tool.load_json(pin_path()).get('release') != before['release_id']:
            raise RuntimeError('The shelf, shipped list, and pin do not agree. Stop.')
        entry = source_entry(tool,source,home) if not retiring else None
        if entry is not None:
            entry['owner'] = owner
        if before['skills'].get(name) == entry and not retire_plan and not removed:
            print('no-op: ' + name + '; release ' + before['release_id'])
            return 0
        release_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + preflight['dojo_commit'][:12]
        candidate = tool.RELEASES / release_id
        tool.RELEASES.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix='.scoped-', dir=tool.RELEASES))
        record = json.loads(json.dumps(before))
        record.update(kind='scoped_release', release_id=release_id, dojo_commit=preflight['dojo_commit'], runtime_canaries='pending')
        if entry is not None:
            record['skills'][name] = entry
        for other in removed:
            record['skills'].pop(other)
        record['removed'] = sorted((set(before.get('removed', [])) | set(removed)) - set(record['skills']))
        # Infer ownership only from an existing source, never from its absence.
        for other, other_entry in record['skills'].items():
            other_home, other_owner = tool.source_home(other)
            if (other_home / 'skills' / other / 'SKILL.md').is_file():
                other_entry.setdefault('owner', other_owner)
        record.setdefault('excluded', {}).pop(name, None)
        record['digest'] = record_digest(record['skills'])
        record['policy']['digest'] = hashlib.sha256(tool.POLICY.read_bytes()).hexdigest()
        for other in record['skills']:
            origin = source if other == name else tool.ACTIVE / other
            if other==name:package_skill(tool,source,staging/other,home)
            else:shutil.copytree(origin,staging/other,symlinks=True,ignore=shutil.ignore_patterns(*tool.EXCLUDED_PARTS))
        tool.write_json(staging / RECORD, record)
        validate_record(tool, staging)
        tool.make_read_only(staging)
        os.rename(staging, candidate)
        previous = dict(kind='release' if tool.ACTIVE.is_symlink() else 'directory',
                        path=str(tool.ACTIVE.resolve() if tool.ACTIVE.is_symlink() else tool.STATE / 'shelf-before' / release_id))
        receipt = dict(version=1, release_id=release_id, result='running', skill=name,
                       previous_release_id=before['release_id'], previous=previous,
                       candidate=str(candidate), links_created=[], removed=removed,
                       distribution_before=json_snapshot(tool.DIST), pin_before=json_snapshot(pin_path()),
                       state_before=json_snapshot(tool.STATE_FILE))
        receipt['route_state_before'] = json_snapshot(route_state)
        receipt['workspace_routes_retired'] = {row['target']: os.readlink(row['target']) for row in retire_plan if row['action'] == 'retire_owned'}
        receipt_path = tool.SHIPS / (release_id + '.json')
        transaction = tool.STATE / 'scoped-transaction.json'
        tool.write_json(receipt_path, receipt)
        tool.write_json(transaction, receipt)
        try:
            approved_catalog(tool.DOJO, state=tool.STATE, expected=catalog_version)
            if previous['kind'] == 'directory':
                storage = Path(previous['path'])
                storage.parent.mkdir(parents=True, exist_ok=True)
                os.rename(tool.ACTIVE, storage)
            tool.switch_link(candidate)
            # Existing consumer pointers target the stable shelf; reject absent routes.
            for root, label in (() if retiring else ((tool.CLAUDE, 'Claude'), (tool.CODEX, 'Codex'), (tool.AGENTS, 'Agents'))):
                target = root / name
                if root.is_symlink():
                    check_consumer(tool, root, name, label)
                    continue
                if not target.exists() and not target.is_symlink():
                    root.mkdir(parents=True, exist_ok=True)
                    receipt['links_created'].append(str(target))
                    tool.write_json(transaction, receipt)
                    os.symlink(tool.ACTIVE / name, target)
                check_consumer(tool, root, name, label)
            remaining_routes = apply_route_plan(retire_plan, route_owned)
            tool.write_json(route_state, dict(version=1, links=remaining_routes))
            overrides = tool.parse_canary_overrides(args.canary_command)
            required = [] if retiring else [name]
            canaries = tool.run_fresh_canaries(required, tool.canary_prompt(required), overrides,
                                               tool.hidden_from_model(candidate, required))
            approved_catalog(tool.DOJO, state=tool.STATE, expected=catalog_version)
            # Canary details stay in the receipt; payload records agree across all three files.
            record['runtime_canaries'] = 'passed'
            manifest = candidate / RECORD
            candidate.chmod(0o755)
            manifest.chmod(0o644)
            tool.write_json(manifest, record)
            manifest.chmod(0o444)
            candidate.chmod(0o555)
            tool.write_json(tool.DIST, record)
            tool.write_json(pin_path(), dict(gaps=[], release=release_id))
            tool.write_json(tool.STATE_FILE, dict(version=1, scoped=True, release_id=release_id,
                            current=dict(kind='release', path=str(candidate)), previous=previous))
            refresh_workspace_views(tool)
            receipt.update(result='shipped', digest=record['digest'], canaries=canaries)
            tool.write_json(receipt_path, receipt)
            transaction.unlink()
        except Exception as exc:
            read_transaction(tool)
            receipt.update(result='failed', failure=str(exc), rollback='restored')
            keep_failure_output(tool, receipt, exc)
            tool.write_json(receipt_path, receipt)
            raise
        print('shipped ' + name + '; release ' + release_id)
        return 0

def keep_failure_output(tool, receipt, error):
    """Save a failed step's command output beside the receipt and print where it is."""
    output = getattr(error, 'output', None)
    if output is None:
        return None
    receipt['failure_output'] = output
    folder = tool.SHIPS / (receipt['release_id'] + '-evidence')
    folder.mkdir(parents=True, exist_ok=True)
    tool.write_json(folder / 'failure.json', dict(failure=str(error), output=output))
    runtimes = output.get('runtimes', {}) if isinstance(output, dict) else {}
    for runtime, result in runtimes.items():
        if result.get('result') == 'passed':
            continue
        for stream in ('stdout', 'stderr'):
            (folder / (runtime + '.' + stream + '.txt')).write_text(result.get(stream) or '')
    receipt['evidence'] = str(folder)
    print('failure output: ' + str(folder), file=sys.stderr)
    return folder


def rollback_one(tool, args):
    with tool.lifecycle_lock():
        read_transaction(tool)
        state = tool.load_json(tool.STATE_FILE)
        release_id = state['release_id']
        if args.authorize_reviewed != release_id:
            raise RuntimeError('Read the ship receipt and authorize its exact release ID.')
        validate_record(tool, tool.ACTIVE)
        receipt = tool.load_json(tool.SHIPS / (release_id + '.json'))
        if receipt['result'] != 'shipped':
            raise RuntimeError('The release has no successful ship receipt. Stop.')
        previous = receipt['previous']
        validate_record(tool, Path(previous['path']))
        tool.write_json(tool.STATE / 'scoped-transaction.json', receipt)
        read_transaction(tool)
        receipt['rollback'] = 'restored'
        tool.write_json(tool.SHIPS / (release_id + '.json'), receipt)
        print('rolled back to ' + receipt['previous_release_id'])
        return 0


def recover_workspace(tool):
    """Restore an interrupted scope transaction without overwriting divergent runtime entries."""
    transaction = tool.STATE / 'workspace-transaction.json'
    if not transaction.exists():
        return
    saved = tool.load_json(transaction)
    previous = saved.get('global_previous')
    if previous:
        active = tool.ACTIVE
        new = Path(saved['global_candidate'])
        if active.is_symlink():
            if active.resolve() not in {new, Path(previous['path'])}:
                raise RuntimeError('Global shelf changed outside the scope transaction; preserve it.')
            active.unlink()
        if previous['kind'] == 'directory':
            storage = Path(previous['path'])
            if storage.exists():
                if active.exists(): raise RuntimeError('Scope recovery found two shelf directories.')
                os.rename(storage, active)
        else:
            tool.switch_link(Path(previous['path']))
    divergent = []
    for target, before in saved['native_before'].items():
        p = Path(target)
        expected = saved['native_after'][target]
        if p.exists() or p.is_symlink():
            if not p.is_symlink() or expected is None or str(p.resolve()) != expected:
                divergent.append(target)
                continue
            p.unlink()
        if before is not None:
            p.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(before, p)
    for name, value in saved['metadata_before'].items():
        restore_json(tool, Path(name), value)
    transaction.unlink()
    receipt = tool.load_json(Path(saved['receipt']))
    receipt.update(result='failed', rollback='restored', divergent_private_entries_preserved=divergent)
    tool.write_json(Path(saved['receipt']), receipt)


def ship_workspace(tool, args, source, policy, catalog_version):
    """Publish a workspace skill or remove an off skill from every owned global route."""
    name = args.skill
    scope = catalog_scope(policy, name, tool.source_home(name)[0])
    portfolio = Path(os.environ.get('FOXRUN_WORKSPACE_ROOT', '~/foxrun')).expanduser()
    route_state = tool.STATE / 'catalog-routes.json'
    owned = tool.load_json(route_state).get('links', {}) if route_state.exists() else {}
    before = validate_record(tool, tool.ACTIVE)
    removed = tool.removed_person_skills(before)
    related = {p: value for p, value in owned.items() if Path(p).name == name}
    unrelated = {p: value for p, value in owned.items() if Path(p).name != name}
    roots = [tool.CLAUDE, tool.CODEX, tool.AGENTS]
    # Old per-skill links are adopted only when their exact stable target and shipped record prove ownership.
    if name in before['skills']:
        for root in roots:
            target = root / name
            if not root.is_symlink() and target.is_symlink() and target.resolve() == (tool.ACTIVE / name).resolve():
                related[str(target)] = str(target.resolve())
    if args.dry_run:
        print('dry-run: catalog scope ' + str(scope) + ' for ' + name + '; no writes')
        return 0
    if scope == 'off' and name not in before['skills'] and not related and not removed:
        if not (tool.source_home(name)[0] / 'skills' / name / 'SKILL.md').is_file():
            raise RuntimeError('Unknown skill: ' + name)
        print('no-op: ' + name + ' stays in Skillwright; no published route')
        return 0
    if tool.git('status', '--porcelain', '--', 'config/catalog.yaml'):
        raise RuntimeError('Commit the catalog before applying its scope.')
    preflight = tool.ship_preflight(repo=tool.source_home(name)[0])
    if removed and tool.source_home(name)[0] != tool.PERSON:
        tool.ship_preflight(repo=tool.PERSON)
    ident = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-scope-' + preflight['dojo_commit'][:12]
    candidate = tool.RELEASES / (ident + '-workspace')
    candidate.mkdir(parents=True)
    if scope != 'off':
        package_skill(tool,source,candidate/name,tool.source_home(name)[0])
        digest, count = tool.digest_tree(candidate / name)
    else:
        digest, count = None, 0
    tool.write_json(candidate / '.workspace-release.json', dict(version=1, release_id=ident,
                    skill=name, digest=digest, file_count=count, where=scope,
                    catalog_digest=hashlib.sha256(tool.POLICY.read_bytes()).hexdigest()))
    tool.make_read_only(candidate)
    raw = json.loads(tool.POLICY.read_text())
    raw['where'] = dict(raw.get('where', {}))
    homes = [tool.DOJO] + ([tool.PERSON] if tool.PERSON is not None else [])
    for other in {path.name for home in homes for path in tool.authored_skills(home).iterdir()}:
        if other != name:
            raw['where'][other] = 'off'
    # Route from the repo that holds the skill; a person's workspace skill is not in the Dojo.
    plan = route_plan(raw, tool.source_home(name)[0], candidate, portfolio, roots, related)
    native_before = {row['target']: os.readlink(row['target']) if Path(row['target']).is_symlink() else None
                     for row in plan if row['action'] in {'link', 'private_link', 'retire_owned'}}
    native_after = {row['target']: row['source'] if row['action'] != 'retire_owned' else None
                    for row in plan if row['target'] in native_before}
    global_candidate = None
    global_record = None
    previous = None
    if name in before['skills'] or removed:
        global_candidate = tool.RELEASES / (ident + '-global')
        global_candidate.mkdir()
        global_record = json.loads(json.dumps(before))
        global_record.update(kind='scoped_release', release_id=ident + '-global', dojo_commit=preflight['dojo_commit'], runtime_canaries='pending')
        global_record['skills'].pop(name, None)
        for other in removed:
            global_record['skills'].pop(other)
        global_record['removed'] = sorted((set(before.get('removed', [])) | set(removed)) - set(global_record['skills']))
        global_record['digest'] = record_digest(global_record['skills'])
        global_record['policy']['digest'] = hashlib.sha256(tool.POLICY.read_bytes()).hexdigest()
        global_record.setdefault('excluded', {})[name] = dict(reason='Catalog scope: ' + str(scope), status='source_only', claude='absent')
        for other in global_record['skills']:
            shutil.copytree(tool.ACTIVE/other,global_candidate/other,symlinks=True,ignore=shutil.ignore_patterns(*tool.EXCLUDED_PARTS))
        tool.write_json(global_candidate / RECORD, global_record)
        validate_record(tool, global_candidate)
        tool.make_read_only(global_candidate)
        previous = dict(kind='release' if tool.ACTIVE.is_symlink() else 'directory',
                        path=str(tool.ACTIVE.resolve() if tool.ACTIVE.is_symlink() else tool.STATE / 'shelf-before' / ident))
    receipt_path = tool.SHIPS / (ident + '.json')
    receipt = dict(version=1, kind='workspace_release', release_id=ident, skill=name,
                   where=scope, candidate=str(candidate), global_candidate=str(global_candidate) if global_candidate else None,
                   result='running', actions=plan, removed=removed)
    tool.write_json(receipt_path, receipt)
    metadata = [route_state, tool.DIST, pin_path(), tool.STATE_FILE]
    transaction = tool.STATE / 'workspace-transaction.json'
    tool.write_json(transaction, dict(version=1, skill=name, receipt=str(receipt_path),
                    native_before=native_before, native_after=native_after, global_previous=previous,
                    global_candidate=str(global_candidate) if global_candidate else None,
                    metadata_before={str(p): json_snapshot(p) for p in metadata}))
    try:
        approved_catalog(tool.DOJO, state=tool.STATE, expected=catalog_version)
        # Retire old per-skill global pointers while their stable shelf targets still resolve.
        updated = apply_route_plan(plan, related)
        if global_candidate:
            if previous['kind'] == 'directory':
                storage = Path(previous['path']); storage.parent.mkdir(parents=True, exist_ok=True)
                os.rename(tool.ACTIVE, storage)
            tool.switch_link(global_candidate)
        overrides = tool.parse_canary_overrides(args.canary_command)
        required = [name] if scope != 'off' else []
        prompt = tool.canary_prompt(required) + '\nWorkspace homes: ' + str(portfolio) + '; catalog scope: ' + str(scope)
        canaries = tool.run_fresh_canaries(required, prompt, overrides)
        approved_catalog(tool.DOJO, state=tool.STATE, expected=catalog_version)
        tool.write_json(route_state, dict(version=1, links={**unrelated, **updated}))
        if global_candidate:
            global_record['runtime_canaries'] = 'passed'
            global_candidate.chmod(0o755)
            tool.write_json(global_candidate / RECORD, global_record)
            (global_candidate / RECORD).chmod(0o444); global_candidate.chmod(0o555)
            tool.write_json(tool.DIST, global_record)
            tool.write_json(pin_path(), dict(gaps=[], release=global_record['release_id']))
            tool.write_json(tool.STATE_FILE, dict(version=1, scoped=True, release_id=global_record['release_id'],
                            current=dict(kind='release', path=str(global_candidate)), previous=previous))
        refresh_workspace_views(tool)
        receipt.update(result='shipped', canaries=canaries)
        tool.write_json(receipt_path, receipt)
        transaction.unlink()
    except Exception as error:
        recover_workspace(tool)
        restored = tool.load_json(receipt_path)
        restored['failure'] = str(error)
        keep_failure_output(tool, restored, error)
        tool.write_json(receipt_path, restored)
        raise
    print('shipped catalog scope ' + str(scope) + ' for ' + name + '; release ' + ident)
    return 0


def retiring_workspace_routes(tool, name):
    state = tool.STATE / 'catalog-routes.json'
    owned = tool.load_json(state).get('links', {}) if state.exists() else {}
    portfolio = Path(os.environ.get('FOXRUN_WORKSPACE_ROOT', '~/foxrun')).expanduser().resolve()
    targets = {}
    for value, source in owned.items():
        path = Path(value)
        if path.name == name and path.is_relative_to(portfolio):
            targets[value] = source
    plan = [dict(action='retire_owned' if owned_link_matches(Path(p), source) else 'keep_private',
                 target=p, source=source) for p, source in sorted(targets.items())]
    return state, owned, plan


def restore_workspace_routes(tool, transaction):
    for target, linktext in transaction.get('workspace_routes_retired', {}).items():
        path = Path(target)
        if not path.exists() and not path.is_symlink():
            path.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(linktext, path)
    if 'route_state_before' in transaction:
        restore_json(tool, tool.STATE / 'catalog-routes.json', transaction['route_state_before'])
