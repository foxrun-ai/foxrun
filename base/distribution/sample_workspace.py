#!/usr/bin/env python3
"""Generate a made-up workspace from the reviewed core blueprint. No live writes."""
from __future__ import annotations
import sys
from pathlib import Path
_product_root = next(p for p in Path(__file__).resolve().parents if (p / "base/person.py").is_file())
sys.path.insert(0, str(_product_root))
from base import person as _fox_person
from base import pack_policy

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import re

HERE = (Path(__file__).resolve().parent)
TARGET_KEYS = {
    'kind', 'name', 'module', 'object_type', 'supertype', 'lens', 'collection',
    'database_type', 'primary_key', 'display_key', 'unique_keys', 'indexes',
    'foreign_keys', 'strict', 'checks_sql', 'state_write_columns', 'definition', 'parent_guards',
    # Blueprint v12: the write guards and version rules of a draft ship with the model. A value set is a private pick and does not ship.
    'state_guards', 'version_columns', 'version_family', 'hash_columns', 'family_replace', 'review_reset',
}
COLUMN_KEYS = {
    'table', 'column', 'sqlite_type', 'field_type', 'required', 'allowed_values',
    'link', 'default', 'v7_type', 'required_when', 'conditional_required',
    'conditional_reference', 'polymorphic', 'check', 'check_rule', 'check_contract',
    'constraint', 'encoding', 'shape', 'unique', 'unit', 'value_condition', 'required_guard',
}


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + '\n').encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def portable_owner(value):
    if isinstance(value, dict):
        return {key: portable_owner(item) for key, item in value.items()}
    if isinstance(value, list):
        return [portable_owner(item) for item in value]
    if isinstance(value, str):
        # Personal author and reviewer values belong to an install. Keep model identifiers exact.
        return re.sub(r'(?<![\w])(?:' + '|'.join(re.escape(t) for t in _fox_person.private_terms()) + r')(?![\w])', 'owner', value, flags=re.I)
    return value


def portable_blueprint(source, workspaces=(), template=False):
    """Keep model names and constraints; omit private import mappings and workspace picks."""
    # Compile the source rules before making the portable copy. Commands use these guards too.
    core = module(source.parent / 'core.py', 'portable_core')
    targets, columns = core.load(source, configure_person=not template)
    targets = [{key: value for key, value in row.items() if key in TARGET_KEYS} for row in targets]
    columns = [{key: value for key, value in row.items() if key in COLUMN_KEYS} for row in columns]
    targets, columns = portable_owner(targets), portable_owner(columns)
    for row in columns:
        if row['column'] in ('workspace', 'workspace_tags'):
            row['allowed_values'] = list(workspaces) or None
        if row['table'] == 'base_fields' and row['column'] == 'field_type':
            row['allowed_values'] = list(dict.fromkeys(row['allowed_values'] + ['map']))
    return targets, columns


def model(source, workspaces=()):
    core = module(source / 'core.py', 'sample_core')
    views = module(source / 'views.py', 'sample_views')
    return core, views, portable_blueprint(source / 'blueprint', workspaces)


def build_database(source, fixture, destination=':memory:'):
    fixture = shipped_fixture(source, fixture)
    workspaces = fixture.get('workspaces', [fixture['workspace']])
    if (not isinstance(workspaces, list) or not workspaces or
        fixture['workspace'] not in workspaces or len(workspaces) != len(set(workspaces)) or
        any(not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9-]{1,80}', name) for name in workspaces)):
        raise ValueError('The install must supply its workspace names.')
    core, views, (targets, columns) = model(source, workspaces)
    db = core.connect(destination, {'writer': 'schema', 'workspace': fixture['workspace'],
                                   'actor': 'sample-loader', 'reason': 'Made-up sample data.'})
    try:
        # This fresh install's roster comes from its validated install input.
        db.create_function('foxrun_workspace_allowed', 1, lambda value: int(value is None or value in workspaces))
        db.create_function('foxrun_workspace_allowed', 2, lambda value, portfolio: int(value is None or value in workspaces or bool(portfolio) and value=='foxrun'))
        db.executescript(portable_owner(core.sql_schema(targets, columns)))
        _fox_person.record_workspaces(db, workspaces)
        db.executescript(views.view_sql(targets, columns))
        core.seed_rows(db, targets, columns)
        if not db.execute("SELECT 1 FROM base_modules WHERE name='wiki'").fetchone():
            db.execute("INSERT INTO base_modules(name,job,tier,version,source_path) VALUES('wiki','Compiled knowledge.','base',?,'wiki')", (core.BLUEPRINT,))
        by_table = {}
        for column in columns:
            by_table.setdefault(column['table'], []).append(column)
        for table, rows in fixture['tables'].items():
            for supplied in rows:
                row = dict(supplied)
                for column in by_table[table]:
                    name = column['column']
                    if name == 'workspace':
                        row[name] = fixture['workspace']
                    elif name in ('created_at', 'updated_at', 'fetched_at'):
                        row.setdefault(name, fixture['timestamp'])
                    elif name not in row and column.get('default') is not None:
                        row[name] = column['default']
                keys = list(row)
                db.execute('INSERT INTO ' + core.Q(table) + '(' + ','.join(map(core.Q, keys)) +
                           ') VALUES(' + ','.join('?' for _ in keys) + ')', [row[k] for k in keys])
        blueprint_hash = digest(encoded([targets, columns]))
        for name in fixture['modules']:
            identity = db.execute('SELECT id FROM base_modules WHERE name=?', (name,)).fetchone()[0]
            db.execute('INSERT INTO base_installs(actor,blueprint_hash,module,status,version,workspace,installed_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                       ('sample-loader', blueprint_hash, identity, 'complete', core.BLUEPRINT, fixture['workspace'], fixture['timestamp'], fixture['timestamp']))
        db.commit()
        db.executescript(core.guard_sql(targets, columns))
        if list(db.execute('PRAGMA foreign_key_check')):
            raise ValueError('Sample links fail the foreign key check.')
        for target in targets:
            if target['kind'] == 'view':
                db.execute('SELECT * FROM ' + core.Q(target['name']) + ' LIMIT 0').fetchall()
        return db
    except Exception:
        db.close()
        raise


def shipped_fixture(source, fixture):
    """Filter sample rows and install records through the manifest marks."""
    installed = pack_policy.shipped_names(source.parent, fixture['modules'])
    targets, _ = portable_blueprint(source / 'blueprint')
    owners = {row['name']: row['module'] for row in targets}
    return dict(fixture, modules=installed,
                tables={table: rows for table, rows in fixture['tables'].items()
                        if owners.get(table) in installed})


def pages(db, fixture):
    fixture = shipped_fixture(Path(__file__).resolve().parent.parent, fixture)
    workspace = fixture['workspace']
    blueprint_version = db.execute("SELECT version FROM base_modules WHERE name='base'").fetchone()[0]
    head = f"---\ntype: doc\nworkspace: {workspace}\ntimestamp: {fixture['timestamp']}\ntags: [sample]\n---\n\n"
    output = {}
    snapshot = []
    for name, kind, sql in db.execute("SELECT name,type,sql FROM sqlite_schema WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        fields = [r['name'] for r in db.execute('PRAGMA table_info("' + name + '")')]
        rows = db.execute('SELECT * FROM "' + name + '"' + (' WHERE workspace=?' if 'workspace' in fields else ''),
                          (workspace,) if 'workspace' in fields else ()).fetchall()
        # Views with date('now') are evaluated by the database, not saved as a second state store.
        if kind == 'table':
            output['data/' + name + '.jsonl'] = b''.join((json.dumps(dict(r), sort_keys=True, ensure_ascii=False) + '\n').encode() for r in rows)
            snapshot.append({'name': name, 'kind': kind, 'count': len(rows), 'sql': sql})
    output['data/schema.json'] = encoded({'workspace': workspace, 'tables': snapshot})
    output['history/outputs/sample-input.json'] = encoded(fixture)
    output['AGENTS.md'] = (head + '# Cedar Shop\n\nThis is a made-up ecommerce workspace for garden tools.\nUse the core data.db for records.\nUse files for knowledge, playbooks, and history.\nAll sample rows are made-up.\n\n## Work\n\nOpen [[cedar-shop]] for work and [[commerce]] for the function.\nRead [[RESOLVER]], [[SCHEMA]], and [[CONCEPTS]] before changes.\nAsk the owner before a send, purchase, or production change.\n').encode()
    output['CLAUDE.md'] = (head + '# Claude\n\n@AGENTS.md\n').encode()
    output['RESOLVER.md'] = (head + '# Resolver\n\nThe core data.db owns records.\nThe data/ files are exports. They never own current state.\nThe sample loader supplies made-up mirror rows.\nUse table commands for later record changes.\nRead [[SCHEMA]] for storage and [[CONCEPTS]] for business words.\n').encode()
    output['SCHEMA.md'] = (head + f'# Schema\n\nBlueprint v{blueprint_version} supplies table, field, link, and allowed status names.\nThe core data.db holds each table once.\nWorkspace rows carry workspace. Shared rows carry no workspace.\nInstalled-module rows record module versions.\nKnowledge and playbooks use files. Records use rows. History uses frozen files or rows.\nSee [[index]] for the generated table list.\n').encode()
    output['CONCEPTS.md'] = (head + '# Concepts\n\nCedar Shop is a made-up brand for garden tools.\nGarden trowel: a small hand tool for planting.\nSeed tray: a tray for starting plants.\nThe approved sample tag is sample.\nModel words belong to the Portfolio.\n').encode()
    output['BRAND.md'] = (head + '# Brand\n\nCedar Shop sells garden tools in this made-up sample.\nUse simple words. Show the tool and its use.\n').encode()
    output['DESIGN.md'] = (head + '# Design\n\nUse short pages and clear links.\nCheck product images before publication.\nRead [[BRAND]] for the sample brand.\n').encode()
    output['CAPABILITIES.md'] = (head + '# Capabilities\n\nGenerated from the installed-module rows and the sample input.\n\n## Agents\n\nNo agent identity is installed.\n\n## Skills\n\nThe shipped lookup skill reads the dictionary.\n\n## CLIs\n\nThe core table commands read and write records.\n\n## MCPs\n\nNone are installed.\n\n## Schedules\n\nNone are installed.\n\n## Hooks\n\nNone are installed.\n\n## Plugins\n\nNone are installed.\n').encode()
    tasks = db.execute('SELECT t.number,t.title,t.status FROM work_open_tasks v JOIN work_tasks t ON t.id=v.id WHERE t.workspace=? ORDER BY t.id', (workspace,)).fetchall()
    output[workspace + '.md'] = (head + '# Cedar Shop\n\nThis report reads the made-up database rows.\n\n## Work\n\n| Task | Title | Status |\n| --- | --- | --- |\n' + ''.join('| ' + ' | '.join(r) + ' |\n' for r in tasks) + '\nOpen [[commerce]], [[index]], and [[CAPABILITIES]].\n').encode()
    output['commerce.md'] = (head + '# Commerce\n\nCommerce is the sample function. Its owner is sample-owner.\nProduct examples are Garden trowel and Seed tray.\nThe default install loads product rows only when the commerce manifest ships.\nThe sample connects no outside account.\nNo feeder or schedule runs.\nOpen [[cedar-shop]] for work and [[index]] for collections.\n').encode()
    index = head + f'# Index\n\nGenerated from blueprint v{blueprint_version} and the made-up database rows.\n\n'
    for path in ['AGENTS.md', 'CLAUDE.md', 'RESOLVER.md', 'SCHEMA.md', 'CONCEPTS.md', 'BRAND.md', 'DESIGN.md', 'CAPABILITIES.md', workspace + '.md', 'commerce.md']:
        index += '- [[' + path[:-3] + ']] · ' + path + '\n'
    index += '\nFolders: data/, wiki/, notes/, history/daily/, history/snapshots/, history/handoffs/, history/outputs/.\n\n'
    index += 'Source receipts: CAPABILITIES.md.sources.json, ' + workspace + '.md.sources.json, commerce.md.sources.json, index.md.sources.json\n\n'
    index += '| Table | Rows | Export |\n| --- | ---: | --- |\n'
    index += ''.join(f"| {r['name']} | {r['count']} | data/{r['name']}.jsonl |\n" for r in snapshot)
    index += '\nThe exports are copies. The core data.db remains the source.\n'
    output['index.md'] = index.encode()
    for name in ['CAPABILITIES.md', workspace + '.md', 'commerce.md', 'index.md']:
        sources = ['history/outputs/sample-input.json', 'data/schema.json', 'data/work_tasks.jsonl', 'data/base_installs.jsonl']
        output[name + '.sources.json'] = encoded({'output_sha256': digest(output[name]),
            'sources': [{'path': path, 'sha256': digest(output[path])} for path in sources],
            **({'schema_snapshot': 'data/schema.json'} if name == 'index.md' else {})})
    return output


def generate(source, target, fixture_path=(Path(__file__).resolve().parent / 'sample/rows.json')):
    fixture = json.loads(fixture_path.read_text())
    if fixture.get('made_up') is not True:
        raise ValueError('The sample input must declare made_up: true.')
    if target.name != fixture['workspace'] or target.is_symlink():
        raise ValueError('Use the named sample workspace without a symlink.')
    db = build_database(source, fixture)
    try:
        outputs = pages(db, fixture)
    finally:
        db.close()
    changed = [name for name, raw in outputs.items() if (target / name).is_symlink() or
               ((target / name).exists() and (target / name).read_bytes() != raw)]
    if changed:
        raise ValueError('Refuse changed sample files: ' + ', '.join(changed))
    for folder in ['wiki', 'notes', 'history/daily', 'history/snapshots', 'history/handoffs', 'history/outputs', 'data']:
        (target / folder).mkdir(parents=True, exist_ok=True)
    for name, raw in outputs.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(raw)
    return outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core', type=Path, required=True)
    parser.add_argument('--target', type=Path, required=True)
    args = parser.parse_args()
    try:
        outputs = generate(args.core.resolve(), args.target.absolute())
    except (OSError, ValueError, sqlite3.Error) as error:
        print('FAIL sample workspace: ' + str(error), file=sys.stderr)
        return 1
    print(f'PASS sample workspace: {len(outputs)} files; made-up data; blueprint v12')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
