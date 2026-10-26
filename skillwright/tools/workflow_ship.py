"""Release standalone workflows through skill-ship; source files never become live by editing them."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import csv
import io
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from base import paths
from work import flow

RECORD = '.release-manifest.json'


def regular(path):
    """Reject links at every component, including a missing destination's parents."""
    path = Path(os.path.abspath(str(path)))
    for part in (path, *path.parents):
        if part.is_symlink():
            raise RuntimeError('Workflow paths cannot traverse links: ' + str(part))
    return path


def records(shelf):
    record = regular(shelf / RECORD)
    if not record.exists():
        return {'version': 1, 'workflows': {}}
    data = json.loads(record.read_text())
    if data.get('version') != 1 or not isinstance(data.get('workflows'), dict):
        raise RuntimeError('Invalid workflow release manifest: ' + str(record))
    return data


def check_name(name, approval=None):
    if not re.fullmatch(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*', name):
        raise RuntimeError('A workflow name uses lowercase words separated by dashes.')
    words = name.split('-')
    if any(word in ('my', 'and') or re.fullmatch(r'v\d+', word) for word in words):
        raise RuntimeError('A workflow name cannot contain my, and, or a version word.')
    if len(words) <= 2:
        return
    if approval is None:
        raise RuntimeError('A workflow name has at most two words; --approval needs the person approval id.')
    database = paths.database()
    try:
        with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as db:
            row = db.execute('SELECT call,person_words,subject_id,subject_type FROM approvals WHERE id=?', (approval,)).fetchone()
            cited = False
            if row and row[0] == 'approve' and row[2] != name and row[3] == 'task':
                task = db.execute('SELECT body,note,acceptance,context FROM tasks WHERE id=?', (row[2],)).fetchone()
                if task:
                    texts = list(task)
                    texts.extend(value[0] for value in db.execute(
                        "SELECT body FROM comments WHERE subject_type='task' AND subject_id=?", (row[2],)))
                    citation = r'\bapproval\s+#?' + re.escape(str(approval)) + r'\b'
                    cited = any(re.search(citation, text or '', re.IGNORECASE) for text in texts)
    except sqlite3.Error as error:
        raise RuntimeError('Cannot check the workflow name approval: ' + str(error)) from error
    if not row or row[0] != 'approve' or not row[1] or (name != row[2] and not cited):
        raise RuntimeError('The approval must approve this workflow name: ' + name)


def source_for(args):
    name = args.workflow
    if args.workspace and args.source:
        raise RuntimeError('Use --workspace or --source, not both.')
    person = paths.portfolio() / 'skillwright/workflows' / (name + '.yaml')
    if args.workspace:
        return regular(paths.workspace(args.workspace) / 'workflows' / (name + '.yaml')), 'person'
    if args.source:
        source = regular(Path(args.source).expanduser())
        if not source.is_absolute() or source.name != name + '.yaml':
            raise RuntimeError('--source must name <workflow>.yaml.')
        product_root = source.parent.parent.parent
        is_product = (source.parent == product_root / 'skillwright/workflows'
                      and (product_root / 'product-manifest.tsv').is_file())
        owner = 'product' if is_product else 'person'
        return source, owner
    if person.exists():
        return regular(person), 'person'
    # The installed shelf is never its own source. Product builders pass --source
    # when they run the installed tool rather than the source-tree command.
    product = regular(ROOT / 'skillwright/workflows' / (name + '.yaml'))
    if ROOT == paths.system_home():
        raise RuntimeError('No personal workflow source; pass --source with the product source file.')
    return product, 'product'


def payloads(source, name):
    if not source.is_file():
        raise RuntimeError('Workflow source is missing: ' + str(source))
    raw = source.read_bytes()
    try:
        data = flow.load(source)
    except (ValueError, OSError) as error:
        raise RuntimeError('Cannot read workflow source: ' + str(error)) from error
    bad = flow.problems(data, name)
    if data.get('kind', 'workflow') != 'workflow':
        bad.append('Only standalone workflows use --workflow; a flow ships with its skill.')
    if bad:
        raise RuntimeError('Invalid workflow: ' + '; '.join(bad))
    files = {source.name: raw}
    page = regular(source.with_suffix('.md'))
    if page.exists():
        if not page.is_file():
            raise RuntimeError('Workflow page must be a regular file: ' + str(page))
        files[page.name] = page.read_bytes()
    return files


def file_rows(files):
    return {name: {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
            for name, raw in sorted(files.items())}


def manifest_updates(name, files, owner):
    """Change only this workflow's product rows; a personal override is not product content."""
    changes = {}
    for relative in ('product-manifest.tsv', 'base/product-manifest.tsv'):
        path = regular(paths.system_home() / relative)
        if not path.exists():
            continue
        reader = csv.DictReader(io.StringIO(path.read_text()), delimiter='\t')
        if reader.fieldnames != ['path', 'bytes', 'sha256']:
            raise RuntimeError('Invalid product manifest: ' + str(path))
        rows = {row['path']: row for row in reader}
        for filename in (name + '.yaml', name + '.md'):
            key = 'skillwright/workflows/' + filename
            rows.pop(key, None)
            if owner == 'product':
                rows.pop('skillwright/workflows/.product/' + filename, None)
        if owner == 'product':
            for filename, row in file_rows(files).items():
                for prefix in ('skillwright/workflows/', 'skillwright/workflows/.product/'):
                    rows[prefix + filename] = dict(path=prefix + filename, **row)
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=['path', 'bytes', 'sha256'], delimiter='\t', lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows[key] for key in sorted(rows))
        changes[path] = stream.getvalue().encode()
    return changes


@contextmanager
def locked(state):
    state.mkdir(parents=True, exist_ok=True)
    with regular(state / 'workflows.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def atomic(path, raw):
    path = regular(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=str(path.parent), delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(str(temporary), str(path))
    finally:
        if temporary.exists():
            temporary.unlink()


def ship_one(args):
    """One command releases source or promotes a workspace workflow; dry-run writes nothing."""
    check_name(args.workflow, args.approval)
    source, owner = source_for(args)
    shelf = regular(paths.system_home() / 'skillwright/workflows')
    if source == shelf / source.name:
        raise RuntimeError('The shelf is a released copy, never a workflow source.')
    files = payloads(source, args.workflow)
    promoted_from = str(source) if args.workspace else None
    promotion = regular(paths.portfolio() / 'skillwright/workflows') if args.workspace else None
    if promotion is not None:
        for name, raw in files.items():
            target = regular(promotion / name)
            if target.exists() and (not target.is_file() or target.read_bytes() != raw):
                raise RuntimeError('Personal workflow source already differs: ' + str(target))
        source = promotion / source.name
    rows = file_rows(files)
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
    report = {'workflow': args.workflow, 'owner': owner, 'source': str(source), 'shelf': str(shelf),
              'digest': digest, 'files': rows, 'approval': args.approval, 'dry_run': args.dry_run,
              'promoted_from': promoted_from}
    state = regular(paths.system_home() / 'skillwright/skill-state')

    def prepare():
        manifest = records(shelf)
        previous = manifest['workflows'].get(args.workflow)
        for name in (args.workflow + '.yaml', args.workflow + '.md'):
            target = regular(shelf / name)
            if target.exists() and not target.is_file():
                raise RuntimeError('Workflow shelf target is not a regular file: ' + str(target))
        if previous:
            for name, row in previous['files'].items():
                if Path(name).name != name or name not in (args.workflow + '.yaml', args.workflow + '.md'):
                    raise RuntimeError('Invalid workflow release file: ' + name)
                target = regular(shelf / name)
                if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != row['sha256']:
                    raise RuntimeError('Released workflow drift: ' + str(target))
        same = (previous is not None and previous['digest'] == digest and previous['source'] == str(source)
                and previous['owner'] == owner and all((shelf / n).is_file() and (shelf / n).read_bytes() == b for n, b in files.items()))
        same = same and all(path.read_bytes() == raw for path, raw in manifest_updates(args.workflow, files, owner).items())
        report['action'] = 'unchanged' if same else 'release'
        report['previous_release_id'] = previous.get('release_id') if previous else None
        # Preview also checks every destination that a real release would write.
        for name in (args.workflow + '.yaml', args.workflow + '.md'):
            target = regular(shelf / '.product' / name)
            if target.exists() and not target.is_file():
                raise RuntimeError('Product workflow target is not a regular file: ' + str(target))
        regular(shelf / RECORD)
        manifest_updates(args.workflow, files, owner)
        return manifest, previous

    if args.dry_run:
        prepare()
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    with locked(state):
        manifest, previous = prepare()
        if report['action'] == 'unchanged':
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0
        release_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + digest[:12]
        release = regular(state / 'workflow-releases' / release_id)
        release.mkdir(parents=True)
        old_files = {args.workflow + '.yaml', args.workflow + '.md'} | (set(previous['files']) if previous else set())
        # Keep original bytes, including unrecorded first-release shelf files, before replacement.
        before = {name: (shelf / name).read_bytes() if (shelf / name).is_file() else None for name in old_files | {RECORD}}
        for name, raw in before.items():
            if raw is not None:
                atomic(release / 'backup' / name, raw)
                if (release / 'backup' / name).read_bytes() != raw:
                    raise RuntimeError('Workflow backup differs: ' + name)
        product_before = {name: (shelf / '.product' / name).read_bytes() if (shelf / '.product' / name).is_file() else None for name in old_files}
        for name, raw in product_before.items():
            if raw is not None:
                atomic(release / 'backup/product' / name, raw)
                if (release / 'backup/product' / name).read_bytes() != raw:
                    raise RuntimeError('Product workflow backup differs: ' + name)
        updates = manifest_updates(args.workflow, files, owner)
        manifest_before = {path: path.read_bytes() for path in updates}
        for path, raw in manifest_before.items():
            saved = release / 'backup/system' / path.relative_to(paths.system_home())
            atomic(saved, raw)
            if saved.read_bytes() != raw:
                raise RuntimeError('Product manifest backup differs: ' + str(path))
        promotion_before = {name: (promotion / name).read_bytes() if (promotion / name).is_file() else None for name in files} if promotion else {}
        try:
            if promotion is not None:
                for name, raw in files.items():
                    atomic(promotion / name, raw)
            for name, raw in files.items():
                atomic(shelf / name, raw)
                if owner == 'product':
                    atomic(shelf / '.product' / name, raw)
            for name in old_files - set(files):
                target = regular(shelf / name)
                if target.exists(): target.unlink()
                if owner == 'product':
                    target = regular(shelf / '.product' / name)
                    if target.exists(): target.unlink()
            for path, raw in updates.items():
                atomic(path, raw)
            entry = dict(report, release_id=release_id)
            manifest['workflows'][args.workflow] = entry
            atomic(shelf / RECORD, (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode())
            if any((source.parent / name).read_bytes() != raw for name, raw in files.items()):
                raise RuntimeError('Workflow source changed during release.')
            if any((shelf / name).read_bytes() != raw for name, raw in files.items()):
                raise RuntimeError('Workflow source/shelf byte comparison failed.')
            report.update(release_id=release_id, source_equals_shelf=True)
            atomic(release / 'receipt.json', (json.dumps(report, indent=2, sort_keys=True) + '\n').encode())
        except BaseException:
            for path, raw in manifest_before.items():
                atomic(path, raw)
            for name, raw in promotion_before.items():
                target = regular(promotion / name)
                if raw is None:
                    if target.exists(): target.unlink()
                else: atomic(target, raw)
            for name, raw in before.items():
                target = regular(shelf / name)
                if raw is None:
                    if target.exists(): target.unlink()
                else: atomic(target, raw)
            for name, raw in product_before.items():
                target = regular(shelf / '.product' / name)
                if raw is None:
                    if target.exists(): target.unlink()
                else: atomic(target, raw)
            raise
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0
