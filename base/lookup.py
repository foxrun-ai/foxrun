#!/usr/bin/env python3
"""Read the workspace dictionary and workspace-spec path rules. Never write a database."""

from __future__ import annotations

import sys as _person_sys
from pathlib import Path as _PersonPath
_person_root = next(p for p in _PersonPath(__file__).resolve().parents if (p / "base/person.py").is_file())
_person_sys.path.insert(0, str(_person_root))
from base import person as _fox_person

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_sys.path.insert(0, str(_FoxPath(__file__).resolve().parent / '..'))
from base import paths as _fox_paths

import argparse
from contextlib import closing
from difflib import SequenceMatcher
import fnmatch
import json
from pathlib import Path
import re
import sqlite3
import sys

BASE = (Path(__file__).resolve().parent)
import os
SPEC = Path(os.environ.get('FOXRUN_WORKSPACE_SPEC', str(_fox_paths.system_home() / 'config/workspace-spec.md')))
if not SPEC.is_file() and 'FOXRUN_WORKSPACE_SPEC' not in os.environ:
    SPEC = BASE / 'workspace-spec.md'
DECISION = re.compile(r'\b(?:pr-|g-)[a-z0-9]+(?:-[a-z0-9]+)*\b')
KEYS = ('object_type', 'supertype', 'subtype', 'container', 'collection',
        'lens', 'database_type', 'file_kind', 'module', 'decision_id')


def dictionary(db):
    """Use a supplied dictionary read-only; otherwise seed only an in-memory DB."""
    if db:
        path = Path(db).expanduser().resolve()
        with closing(_fox_person.connect(path.as_uri() + '?mode=ro', uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            tables = {r[0] for r in conn.execute('SELECT name FROM sqlite_master')}
            if {'object_types', 'fields'} <= tables:
                return [dict(r) for r in conn.execute('SELECT * FROM object_types')], str(path)
    with closing(_fox_person.connect(':memory:')) as conn:
        conn.row_factory = sqlite3.Row
        for filename in ('dictionary.sql', 'dictionary-seed.sql'):
            conn.executescript((BASE / filename).read_text())
        return [dict(r) for r in conn.execute('SELECT * FROM object_types')], 'bundled dictionary (in memory)'


def normal(value):
    return re.sub(r'[\s-]+', '_', value.lower().strip())


def singular(value):
    return value[:-1] if value.endswith('s') and not value.endswith('ss') else value


def name_match(query, rows):
    query = normal(query)
    ranked = []
    for row in rows:
        names = [normal(row['name']), normal(row['storage_name'])]
        score = max(1.0 if query == name else
                    0.99 if singular(query) == singular(name) else
                    SequenceMatcher(None, query, name).ratio() for name in names)
        ranked.append((score, row['name'], row))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    if not ranked or ranked[0][0] < 0.80:
        return None, 'unknown'
    if len(ranked) > 1 and ranked[0][0] < 0.99 and ranked[0][0] - ranked[1][0] < 0.08:
        return None, 'ambiguous'
    return ranked[0][2], 'exact' if ranked[0][0] == 1 else 'fuzzy'


def from_row(row):
    result = dict.fromkeys(KEYS)
    result.update({key: row.get(key) for key in KEYS if key in row})
    storage = row['storage_name']
    result.update(object_type=row['name'], collection=row.get('collection') or
                  (storage if row['container'] == 'collection' else None),
                  file_kind=None if row.get('database_type') else Path(storage).suffix.lstrip('.') or None,
                  source=row.get('source'))
    decisions = DECISION.findall(' '.join(str(row.get(k) or '') for k in
                                         ('decision_id', 'source', 'description')))
    result['decision_id'] = row.get('decision_id') or next(iter(dict.fromkeys(decisions)), None)
    result['decision_ids'] = list(dict.fromkeys(decisions))
    return result


def path_rules():
    """Read annotated tree rows, retaining source gaps instead of filling them."""
    stack = []
    for line in SPEC.read_text().splitlines():
        match = re.match(r'^(.*?)[├└]── (\S+)\s+\[lens: ([^;]+); module: ([^\]]+)\] (.*)$', line)
        if not match:
            continue
        prefix, name, lens, module, refs = match.groups()
        depth = len(prefix) // 4
        stack = stack[:depth]
        path = '/'.join(stack + [name.rstrip('/')])
        if name.endswith('/'):
            stack.append(name.rstrip('/'))
        yield path, name.endswith('/'), lens.split(',')[0], module, refs


def path_match(query, rows):
    parts = Path(query).parts
    matches = []
    for rule, folder, lens, module, refs in path_rules():
        pattern = rule.split('/')
        for start in range(len(parts) - len(pattern) + 1):
            end = start + len(pattern)
            if (not folder and end != len(parts)) or not all(
                    fnmatch.fnmatchcase(a, b) for a, b in zip(parts[start:end], pattern)):
                continue
            matches.append((len(pattern), not folder, rule, folder, lens, module, refs))
    if not matches:
        return None
    _, _, rule, folder, lens, module, refs = max(matches)
    # Dictionary contract definitions take precedence only for root contract rules.
    if not folder and '/' not in rule:
        row = next((r for r in rows if r['storage_name'] == Path(query).name), None)
        if row:
            return from_row(row)
    kind = {'outputs': 'output', 'notes': 'note', 'snapshots': 'snapshot',
            'handoffs': 'handoff', 'docs/shaping': 'shaping', 'docs/specs': 'spec',
            'docs/adr': 'adr', 'design/briefs': 'brief'}.get(rule)
    result = dict.fromkeys(KEYS)
    result.update(object_type=kind, supertype='document' if kind else None,
                  subtype=kind, container='collection' if folder else 'workspace',
                  collection=rule + '/' if folder else None,
                  lens=None if lens in ('none', 'unassigned') else lens,
                  file_kind=Path(query).suffix.lstrip('.') or None,
                  module=module, source=str(SPEC), decision_ids=DECISION.findall(refs))
    result['decision_id'] = next(iter(result['decision_ids']), None)
    result['note'] = 'Folder rule sets the home and lens; extension identifies the file kind. Module gaps remain explicit.'
    return result


def lookup(query, rows, source):
    is_path = '/' in query or bool(Path(query).suffix)
    if is_path:
        result = path_match(query, rows)
        match = 'path rule' if result else 'unknown'
    else:
        row, match = name_match(query, rows)
        result = from_row(row) if row else None
    if result is None:
        result = dict.fromkeys(KEYS)
        result['note'] = ('No reliable dictionary or path match. Add the owning module definition; '
                          'unknown does not mean the object does not exist.')
    return dict(query=query, match=match, dictionary_source=source, **result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('name', nargs='+', help='Object name or file path; quote paths containing spaces')
    parser.add_argument('--db', help='Existing workspace SQLite database (read-only)')
    parser.add_argument('--json', action='store_true', help='Return one JSON object; unknown fields are null')
    args = parser.parse_args()
    try:
        rows, source = dictionary(args.db)
        result = lookup(' '.join(args.name), rows, source)
    except (OSError, sqlite3.Error, KeyError) as exc:
        if args.json:
            print(json.dumps({'error': str(exc)}))
        else:
            print(f'Lookup failed: {exc}', file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"{result['query']} — {result['match']}")
        for fields in (KEYS[:3], KEYS[3:6], KEYS[6:9], KEYS[9:]):
            print(' | '.join(f"{k.replace('_', ' ')}: {result[k] or 'unknown'}" for k in fields))
        if result.get('note'):
            print(result['note'])
    return 1 if result['match'] in ('unknown', 'ambiguous') else 0


if __name__ == '__main__':
    sys.exit(main())
