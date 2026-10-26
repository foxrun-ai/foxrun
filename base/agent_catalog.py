#!/usr/bin/env python3
"""Resolve global shipped skills, catalog routing, and explicit tool permissions."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from base import simple_yaml


def shipped_skills(path):
    """Read the installed public shelf, never the workshop's unpublished sources."""
    shelf = Path(path).parent.parent / 'skills'
    if not shelf.is_dir():
        return []
    return sorted(p.name for p in shelf.iterdir() if (p / 'SKILL.md').is_file())


def route(catalog, skill):
    if skill in catalog.get('exclude', {}):
        return []
    value = catalog.get('where', {}).get(skill, 'global')
    if value == 'off':
        return []
    if value in ('global', 'base'):
        return ['base']
    if isinstance(value, str) and value:
        return [value]
    if isinstance(value, list) and value and all(isinstance(v, str) and v for v in value):
        return list(dict.fromkeys(value))
    raise ValueError('invalid skill route: ' + skill)


def expand(data, path):
    catalog = simple_yaml.safe_load(Path(path).read_text())
    definitions = catalog.get('sets', {})
    selected = data.get('sets', ['base'])
    if not isinstance(selected,list) or not all(isinstance(s,str) for s in selected):
        raise ValueError('sets must be a list of catalog set names')
    selected = list(dict.fromkeys(['base'] + selected))
    resolved = dict(data)
    resolved['sets'] = selected
    resolved['skills'] = []
    resolved['tools'] = []
    resolved['commands'] = []
    candidates = shipped_skills(path)
    for name in selected:
        if name not in definitions:
            raise ValueError('unknown capability set: ' + name)
        definition = definitions[name]
        for field in ('skills','tools','commands'):
            values = definition.get(field, [])
            if not isinstance(values,list) or not all(isinstance(v,str) for v in values):
                raise ValueError('invalid catalog ' + field + ': ' + name)
            if field == 'commands' and any(Path(v).is_absolute() or v.startswith('~') or '..' in Path(v).parts or not v for v in values):
                raise ValueError('invalid catalog command path: ' + name)
            if field == 'skills':
                candidates.extend(values)
            else:
                resolved[field].extend(v for v in values if v not in resolved[field])
        if 'claude_tools' in definition:
            values=definition['claude_tools']
            if not isinstance(values,list) or not all(isinstance(v,str) for v in values):
                raise ValueError('invalid Claude tool permissions: ' + name)
            if 'claude_tools' in resolved and resolved['claude_tools']!=values:
                raise ValueError('conflicting Claude tool permission sets')
            resolved['claude_tools']=values
    # Routing restrictions override every selected set, including old migrated lists.
    for skill in dict.fromkeys(candidates):
        if set(route(catalog, skill)).intersection(selected):
            resolved['skills'].append(skill)
    return resolved


# Model choices have one writer: config/models.yaml. Consumers keep their own effort.
def model_policy(home=None):
    import os
    root = Path(home or os.environ.get('FOXRUN_HOME', Path.home() / '.foxrun'))
    file = root / 'config/models.yaml'
    data = simple_yaml.safe_load(file.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or not isinstance(data.get('tiers'), dict):
        raise ValueError('config/models.yaml must define tiers')
    allowed, banned = data.get('allowed'), data.get('banned')
    if not all(isinstance(items, list) and items and all(isinstance(v, str) and v for v in items)
               and len(items) == len(set(items)) for items in (allowed, banned)):
        raise ValueError('config/models.yaml needs non-empty allowed and banned lists without duplicates')
    if set(allowed).intersection(banned):
        raise ValueError('allowed and banned lists overlap')
    if set(data['tiers']) != {'judgment', 'work', 'cheap', 'code'}:
        raise ValueError('expected judgment, work, cheap, and code tiers')
    for tier, runtimes in data['tiers'].items():
        if not isinstance(runtimes, dict) or set(runtimes) != {'claude', 'codex', 'hermes'}:
            raise ValueError('each tier must name every runtime: ' + tier)
        for runtime, entry in runtimes.items():
            if entry is None:
                continue
            if not isinstance(entry, dict) or entry.get('model') not in allowed:
                raise ValueError('unallowed model: ' + tier + '/' + runtime)
            if 'reasoning_effort' in entry or 'effort' in entry:
                raise ValueError('effort belongs to the squad role: ' + tier + '/' + runtime)
    return data


def resolve_model(tier, runtime, home=None):
    data = model_policy(home)
    entry = data['tiers'].get(tier, {}).get(runtime)
    if not entry:
        raise ValueError('model tier unavailable: ' + str(tier) + '/' + str(runtime))
    return entry['model']


# One exemption policy for the doctor and source checks. T352 keeps evidence and
# outside payloads intact. Pending installed copies qualify only while the
# preferred authoring source is clean; the next full release replaces them.
MODEL_SCAN_EXEMPTIONS = {
    'directories': frozenset({'history', 'raw', 'archive', 'backups',
        'skill-state', 'skill-releases', '.git', 'node_modules',
        '__pycache__', '.venv', 'venv', '.cache', '.pytest_cache'}),
    'home_directories': frozenset({'state', 'run', 'runs'}),
    'imported_skills': frozenset({'vault-.agents-skills-gstack',
        'vault-.claude-skills-gstack', 'hermes-docs'}),
    'imported_subtrees': (('browse', 'references', 'gstack-runtime'),),
    'origin_fields': frozenset({'imported', 'vendored', 'source', 'origin'}),
    'generated': {
        'SCHEMA.md': 'base/generate_pages.py; fields row object_type=runs, field=model; description is historical schema text',
    },
    'binary_suffixes': frozenset({'.db', '.sqlite', '.sqlite3', '.pyc', '.png', '.jpg', '.pdf', '.woff', '.woff2'}),
}


def imported_model_payload(folder):
    """Only explicit origin metadata grants an import exemption, never a mention."""
    import json
    import re
    policy = MODEL_SCAN_EXEMPTIONS
    if folder.name in policy['imported_skills']:
        return True
    if any(tuple(folder.parts[-len(tail):]) == tail for tail in policy['imported_subtrees']):
        return True
    def marked(data):
        if not isinstance(data, dict):
            return False
        for key, value in data.items():
            if key in policy['origin_fields']:
                if key in ('imported', 'vendored') and value is True:
                    return True
                if isinstance(value, str) and re.match(r'^(imported|vendored)(?:$|[: /-])', value, re.I):
                    return True
            if isinstance(value, dict) and marked(value):
                return True
        return False
    skill = folder / 'SKILL.md'
    if skill.is_file() and not skill.is_symlink():
        text = skill.read_text(encoding='utf-8')
        if text.startswith('---\n') and '\n---' in text[4:]:
            front = text[4:].split('\n---', 1)[0]
            try:
                if marked(simple_yaml.safe_load(front)):
                    return True
            except simple_yaml.YAMLError:
                # The small policy parser does not support YAML block scalars.
                # Match explicit metadata only; never exempt on a body mention.
                if re.search(r'(?im)^\s*(?:(?:imported|vendored):\s*true|(?:source|origin):\s*[\'"]?(?:imported|vendored)(?:$|[: /-]))', front):
                    return True
    for name in ('manifest.json', 'manifest.yaml', 'manifest.yml'):
        manifest = folder / name
        if not manifest.is_file() or manifest.is_symlink():
            continue
        data = json.loads(manifest.read_text()) if manifest.suffix == '.json' else simple_yaml.safe_load(manifest.read_text())
        if marked(data):
            return True
    catalog = folder.parent.parent / 'config/manifest.json'
    if skill.is_file() and catalog.is_file() and not catalog.is_symlink():
        for row in json.loads(catalog.read_text()).get('skills', []):
            if row.get('name') == folder.name and marked(row):
                return True
    return False


def model_id_hits(root, policy, registry=None, source_roots=None, exemptions=None):
    """Find model literals, including unknown family IDs, within the owned source scope."""
    import os
    import re
    root = Path(root)
    scope = MODEL_SCAN_EXEMPTIONS
    canonical = Path(registry) if registry is not None else root / 'config/models.yaml'
    home = canonical.parent.parent
    from base.paths import portfolio, discover_workspaces
    portfolio_root = portfolio()
    home_roots = {home, portfolio_root}
    if portfolio_root.is_dir():
        home_roots.update(portfolio_root / name for name in discover_workspaces(portfolio_root))
    if source_roots is None:
        source_roots = [portfolio_root / 'skillwright/skills']
    installed_roots = [home / 'skills', home / 'skillwright/skills']
    def exempt_folder(folder):
        reason, source = None, None
        if (folder.name in scope['directories'] or
                folder.name in scope['home_directories'] and folder.parent in home_roots):
            reason = 'evidence, release, or runtime data'
        elif imported_model_payload(folder):
            reason = 'imported or vendored outside payload'
        elif any(folder.parent == shelf or folder.parent == shelf.resolve() for shelf in installed_roots):
            source = next((Path(base) / folder.name for base in source_roots
                           if (Path(base) / folder.name / 'SKILL.md').is_file()), None)
            if source is not None and source.resolve() != folder.resolve():
                if not model_id_hits(source, policy, canonical, source_roots=()):
                    # Only stale model literals qualify. A clean released copy
                    # clears the exemption, even if unrelated source bytes differ.
                    if model_id_hits(folder, policy, canonical, source_roots=()):
                        reason = 'installed skill pending full release; preferred source passes model check'
        if reason and exemptions is not None:
            exemptions.append({'path': str(folder), 'reason': reason,
                               **({'source': str(source)} if source is not None else {})})
        return reason
    family = r'(?<![A-Za-z0-9_])(?:gpt-\d[\w.-]*|claude-(?:opus|haiku|sonnet)[\w.-]*)(?![A-Za-z0-9_])'
    names = '|'.join(re.escape(v) for v in sorted(set(policy['allowed'] + policy['banned']), key=len, reverse=True))
    pattern = re.compile(family + r'|(?<![A-Za-z0-9_])(?:' + names + r')(?![A-Za-z0-9_])')
    result = []
    for current, dirs, files in os.walk(root, followlinks=False):
        if exempt_folder(Path(current)):
            dirs[:] = []
            continue
        dirs[:] = sorted(d for d in dirs if not (Path(current)/d).is_symlink()
                         and not d.startswith('.env') and not exempt_folder(Path(current)/d))
        for name in sorted(files):
            file = Path(current) / name
            if file == canonical or file.is_symlink() or name.startswith(('.env', 'auth', 'credential')):
                continue
            note = scope['generated'].get(file.relative_to(home).as_posix()) if file.is_relative_to(home) else None
            if note:
                if exemptions is not None:
                    exemptions.append({'path': str(file), 'reason': 'generated page: ' + note})
                continue
            # Opening and closing a WAL shared-memory file can release this
            # process's SQLite locks. Database sidecars are never text sources.
            database = Path(name.rsplit('-', 1)[0]) if name.endswith(('-wal', '-shm', '-journal')) else file
            if database.suffix.lower() in scope['binary_suffixes']:
                continue
            try:
                body = file.read_text(encoding='utf-8')
            except UnicodeDecodeError:
                continue
            for number, line in enumerate(body.splitlines(), 1):
                ids = [match.group(0) for match in pattern.finditer(line)]
                if ids:
                    result.append({'path': str(file), 'line': number, 'ids': ids})
    return result


def check_models(home, extra_roots=()):
    """One doctor rule owns the model-literal check; never silently permits existing literals."""
    policy = model_policy(home)
    from base.paths import portfolio, discover_workspaces
    roots = [Path(home)] + [Path(p) for p in extra_roots]
    portfolio_root = portfolio()
    if portfolio_root.is_dir():
        roots.extend(portfolio_root / name / 'skills'
                     for name in sorted(discover_workspaces(portfolio_root))
                     if (portfolio_root / name / 'skills').is_dir())
    hits = []
    seen = set()
    for root in roots:
        if root.resolve() in seen:
            continue
        seen.add(root.resolve())
        hits.extend(model_id_hits(root, policy, Path(home) / 'config/models.yaml'))
    if hits:
        raise ValueError('model IDs outside config/models.yaml:\n' + '\n'.join(
            '{path}:{line}: {ids}'.format(**dict(hit, ids=', '.join(hit['ids']))) for hit in hits))
    return policy
