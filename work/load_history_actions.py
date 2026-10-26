#!/usr/bin/env python3
"""Import only old blank tracker actions into practice. Existing history stays unchanged."""

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
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import types

sys.path.insert(0, str(Path(__file__).resolve().parent / '../events'))
from history_actions import history_action, record_add_keys, rule_for_row

PRACTICE = (_fox_paths.state() / 'staging/2026-10-05')
SUBJECTS = {
    'task': ('work_tasks', 'tasks'), 'project': ('work_projects', 'projects'),
    'function': ('work_functions', 'functions'), 'goal': ('work_goals', 'goals'),
    'theme': ('work_themes', 'themes'), 'program': ('work_programs', 'programs'),
    'run': ('work_runs', 'runs'), 'decision': ('base_decisions', 'decisions'),
    'incident': ('work_incidents', 'incidents'), 'bug': ('work_bugs', 'bugs'),
    'link': ('work_links', 'record_links'),
}
SUBJECTS.update({
    'persons': ('people_contacts', 'persons'), 'handles': ('people_handles', 'handles'),
    'organizations': ('people_organizations', 'organizations'),
    'organization_memberships': ('people_organization_memberships', 'organization_memberships'),
    'pipelines': ('people_pipelines', 'pipelines'), 'pipeline_stages': ('people_pipeline_stages', 'pipeline_stages'),
    'opportunities': ('people_opportunities', 'opportunities'), 'creator_cycles': ('people_opportunities', 'creator_cycles'),
    'interactions': ('people_interactions', 'interactions'), 'agreements': ('people_agreements', 'agreements'),
    'deliverables': ('ugc_deliverables', 'deliverables'), 'proposal': ('base_proposals', 'proposals'),
})
KINDS = {'persons': 'contact', 'handles': 'handle', 'organizations': 'organization',
         'organization_memberships': 'organization-membership', 'pipelines': 'pipeline',
         'pipeline_stages': 'pipeline-stage', 'opportunities': 'opportunity', 'creator_cycles': 'opportunity',
         'interactions': 'interaction', 'agreements': 'agreement', 'deliverables': 'deliverable'}


def readonly(path):
    db = _fox_person.connect(Path(path).resolve(strict=True).as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    return db


def snapshot(db):
    """Exact row multiset per table, independent of storage order."""
    return {r[0]: sorted(json.dumps(list(row), ensure_ascii=False, default=str) for row in
                        db.execute('SELECT * FROM "' + r[0].replace('"', '""') + '"'))
            for r in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")}


def subject_id(db, source, row, workspace, database):
    definition = SUBJECTS.get(row['subject_type'])
    if definition is None:
        return None
    table, old_table = definition
    columns = {r[1] for r in db.execute('PRAGMA table_info("' + table + '")')}
    if not columns:
        return None
    if 'number' in columns:
        scope = workspace
        if row['subject_type'] == 'function':
            exists = source.execute("SELECT 1 FROM sqlite_schema WHERE name='functions'").fetchone()
            if exists:
                old = source.execute('SELECT organization FROM functions WHERE id=?', (row['subject_id'],)).fetchone()
                if old:
                    scope = old[0]
        query, values = 'SELECT id FROM "' + table + '" WHERE number=?', [row['subject_id']]
        if 'workspace' in columns:
            query += ' AND workspace IS ?'
            values.append(scope)
        found = db.execute(query, values).fetchall()
    else:
        key = str(row['subject_id']).split('|') if row['subject_type'] == 'pipeline_stages' else [row['subject_id']]
        refs = [database + ':' + old_table + ':' + str(row['subject_id']),
                database + ':' + old_table + ':' + json.dumps(key, separators=(',', ':'))]
        found = db.execute("SELECT DISTINCT subject_id FROM work_changes WHERE subject_type=? AND action IN ('created','imported') AND source IN (?,?)",
                           (KINDS.get(row['subject_type'], row['subject_type']), *refs)).fetchall()
    if len(found) > 1:
        raise ValueError('Ambiguous history subject')
    return found[0][0] if found else None


def subject_workspace(db, row, parent, workspace):
    table = SUBJECTS[row['subject_type']][0]
    if 'workspace' in {r[1] for r in db.execute('PRAGMA table_info("'+table+'")')}:
        return db.execute('SELECT workspace FROM "'+table+'" WHERE id=?', (parent,)).fetchone()[0]
    return workspace


def history_holds(db, source, workspace, database, core, *, include_worded=False):
    """Use source-note's reviewed rule: hold an incomplete state trail as a whole."""
    guarded = {'status', 'doc_status', 'stage'}
    if hasattr(core, 'load'):
        _, columns = core.load(Path(core.__file__).parent/'blueprint')
        guarded.update(c['column'] for c in columns if c.get('write_contract'))
    groups = {}
    rows = [dict(r) for r in source.execute('SELECT * FROM activity ' +
            ('' if include_worded else "WHERE coalesce(trim(verb),'')='' ") + 'ORDER BY id')]
    adds = record_add_keys(rows)
    for row in rows:
        field = {'check_by':'reviewer', 'checked_by':'reviewed_by'}.get(row['field'], row['field'])
        rule = rule_for_row(row, adds)
        if field not in guarded or rule.load != 'yes' or rule.target_table != 'work_changes':
            continue
        parent = subject_id(db, source, row, workspace, database)
        definition = SUBJECTS.get(row['subject_type'])
        if parent is None or definition is None:
            continue
        table = definition[0]
        if field not in {r[1] for r in db.execute('PRAGMA table_info("'+table+'")')}:
            continue
        key = json.dumps([row['id']], separators=(',', ':'))
        if db.execute("SELECT 1 FROM work_changes WHERE json_extract(refs,'$[0].source_database')=? "
                      "AND json_extract(refs,'$[0].source_table')='activity' AND json_extract(refs,'$[0].source_key')=?",
                      (database, key)).fetchone():
            continue
        scope = subject_workspace(db, row, parent, workspace)
        groups.setdefault((scope,row['subject_type'],parent,field,table), []).append(row)
    held = set()
    for (scope, kind, parent, field, table), rows in groups.items():
        current = db.execute('SELECT "'+field+'" FROM "'+table+'" WHERE id=?', (parent,)).fetchone()[0]
        current = None if current is None else str(current)
        events = [dict(r) for r in db.execute('SELECT old_value,new_value FROM work_changes WHERE workspace=? '
                                             'AND subject_type=? AND subject_id=? AND field=? ORDER BY seq',
                                             (scope,kind,parent,field))] + rows
        if events[-1]['new_value'] != current or any(a['new_value'] != b['old_value'] for a,b in zip(events, events[1:])):
            held.update(row['id'] for row in rows)
    return held


def load(source_path, target_path, workspace, backup_path, core, validate=None):
    source_path = Path(source_path).resolve(strict=True)
    target_path = Path(target_path).resolve(strict=True)
    backup_path = Path(backup_path).resolve()
    if source_path == target_path or backup_path in (source_path, target_path) or backup_path.exists():
        raise ValueError('Source, target, and new backup must be distinct')
    database = workspace + '.sqlite'
    source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    context = {'writer': 'staging-loader', 'workspace': workspace, 'actor': 'sol',
               'source': 'F2 history import', 'reason': 'source-note reviewed MAP1; original history retained'}
    report = {'source': str(source_path), 'source_sha256': source_hash, 'workspace': workspace,
              'backup': str(backup_path), 'blank_lines': 0, 'loaded': 0, 'new_rows': 0,
              'lines': 0, 'doubles': 0, 'held': 0, 'waiting': 0, 'held_by_field': {}, 'waiting_by_field': {}, 'rows': []}
    held, waiting = Counter(), Counter()
    with closing(readonly(source_path)) as source, closing(core.connect(target_path, context)) as db:
        source.execute('BEGIN')
        db.execute('BEGIN IMMEDIATE')
        try:
            # A reserved lock prevents another writer between the backup and the import.
            with closing(readonly(target_path)) as original, closing(_fox_person.connect(backup_path)) as saved:
                original.backup(saved)
                if saved.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('Backup integrity failed')
            backup_path.chmod(0o600)
            before = snapshot(db)
            incomplete = history_holds(db, source, workspace, database, core)
            rows = [dict(r) for r in source.execute('SELECT * FROM activity ORDER BY id')]
            adds = record_add_keys(rows)
            # Keep the previously reviewed blank trail together. Then check new
            # worded candidates against that completed trail before appending.
            ordered = sorted(rows, key=lambda row: (bool(str(row['verb'] or '').strip()), row['id']))
            worded_checked = False
            for row in ordered:
                if str(row['verb'] or '').strip() and not worded_checked:
                    incomplete = history_holds(db, source, workspace, database, core, include_worded=True)
                    worded_checked = True
                report['lines'] += 1
                report['blank_lines'] += int(not str(row['verb'] or '').strip())
                rule = rule_for_row(row, adds)
                action = rule.action
                receipt = {'id': row['id'], 'field': row['field'], 'action': action,
                           'target_table': rule.target_table, 'load': rule.load}
                report['rows'].append(receipt)
                if rule.load == 'no: double' or (rule.load == 'yes' and rule.target_table != 'work_changes'):
                    receipt.update(outcome='double', reason='The event has its own row; never load this line into work_changes')
                    report['doubles'] += 1
                    continue
                if rule.load == 'no: held' or action is None:
                    receipt['outcome'] = 'held'
                    receipt['reason'] = 'No table rule for this field and value'
                    held[str(row['field'])] += 1
                    continue
                parent = subject_id(db, source, row, workspace, database)
                if parent is None:
                    receipt['outcome'] = 'waiting'
                    receipt['reason'] = 'Source record is not loaded'
                    waiting[str(row['field'])] += 1
                    continue
                if row['id'] in incomplete or row['old_value'] == row['new_value'] or not row['actor'] or not row['source'] or not row['at']:
                    receipt.update(outcome='held', reason='Original history fails the reviewed state or event checks')
                    held[str(row['field'])] += 1
                    continue
                field = {'check_by': 'reviewer', 'checked_by': 'reviewed_by',
                         'value': 'value_minor', 'agreed_amount': 'agreed_amount_minor'}.get(row['field'], row['field'])
                data = {'workspace': subject_workspace(db, row, parent, workspace),
                        'subject_type': KINDS.get(row['subject_type'], row['subject_type']), 'subject_id': parent,
                        'field': field, 'old_value': row['old_value'], 'new_value': row['new_value'],
                        'action': action, 'actor': row['actor'], 'source': row['source'],
                        'occurred_at': row['at'], 'summary': row['note']}
                key = json.dumps([row['id']], separators=(',', ':'))
                old = db.execute("SELECT * FROM work_changes WHERE json_extract(refs,'$[0].source_database')=? "
                                 "AND json_extract(refs,'$[0].source_table')='activity' AND json_extract(refs,'$[0].source_key')=?",
                                 (database, key)).fetchall()
                if len(old) > 1 or (old and any(old[0][k] != v for k, v in data.items())):
                    raise ValueError('Existing history differs: ' + database + ':activity:' + str(row['id']))
                if old:
                    receipt.update(outcome='loaded', seq=old[0]['seq'])
                    report['loaded'] += 1
                    continue
                if action == 'created' and db.execute(
                    "SELECT 1 FROM work_changes WHERE workspace=? AND subject_type=? AND subject_id=? AND action='created'",
                    (data['workspace'], data['subject_type'], parent)
                ).fetchone():
                    receipt.update(outcome='double', reason='This record already has its source-time creation event')
                    report['doubles'] += 1
                    continue
                data['seq'] = db.execute('SELECT value+1 FROM _foxrun_sequence WHERE id=1').fetchone()[0]
                data['recorded_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
                data['refs'] = json.dumps([{'source_database': database, 'source_table': 'activity', 'source_key': key,
                                           'original_verb': row['verb'], 'original_field': row['field'],
                                           'action_table': 'events/history_actions.py', 'task': 'source-note'}])
                db.execute('SAVEPOINT history_row')
                try:
                    db.execute('INSERT INTO work_changes (' + ','.join(data) + ') VALUES (' + ','.join('?' for _ in data) + ')', tuple(data.values()))
                except sqlite3.IntegrityError:
                    db.execute('ROLLBACK TO history_row')
                    receipt.update(outcome='held', reason='Target constraint rejects the original row')
                    held[str(row['field'])] += 1
                else:
                    receipt.update(outcome='loaded', seq=data['seq'])
                    report['loaded'] += 1
                    report['new_rows'] += 1
                finally:
                    db.execute('RELEASE history_row')
            after = snapshot(db)
            for table, rows in before.items():
                if table == '_foxrun_sequence':
                    continue
                if table == 'work_changes':
                    if not set(rows).issubset(after[table]) or len(after[table])-len(rows) != report['new_rows']:
                        raise ValueError('Existing history changed')
                elif rows != after[table]:
                    raise ValueError('Unrelated table changed: ' + table)
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or list(db.execute('PRAGMA foreign_key_check')):
                raise ValueError('Target integrity failed')
            if validate:
                validate(db)
            if hashlib.sha256(source_path.read_bytes()).hexdigest() != source_hash:
                raise ValueError('Source changed during import')
            report.update(held=sum(held.values()), waiting=sum(waiting.values()),
                          held_by_field=dict(sorted(held.items())), waiting_by_field=dict(sorted(waiting.items())),
                          existing_rows_unchanged=True, integrity='ok', foreign_keys=0)
            assert report['lines'] == report['loaded'] + report['doubles'] + report['held'] + report['waiting']
            db.commit()
        except BaseException:
            db.rollback()
            raise
    return report


def snapshot_pending(source, target):
    """Copy uncommitted rows without Python 3.11 serialization APIs."""
    target.executescript("\n".join(source.iterdump()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--target', type=Path, required=True)
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--backup', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if args.target.resolve() != PRACTICE/'home/.local/share/foxrun/data.db':
        parser.error('Only the named practice database is writable')
    if (_fox_paths.portfolio()) in args.source.resolve().parents:
        parser.error('Use a frozen source copy, never the live tracker')
    sys.path.insert(0, str(PRACTICE/'code/foxrun-modules/base'))
    import core
    import lint
    def validate(db):
        # Lint sees this transaction's exact pending bytes, before any commit.
        with closing(_fox_person.connect(':memory:')) as pending:
            snapshot_pending(db, pending)
            pending.row_factory = sqlite3.Row
            check = types.FunctionType(lint.lint.__code__, dict(lint.lint.__globals__,
                                       connect=lambda path, readonly=True: pending))
            findings = check('', Path(core.__file__).parent/'blueprint')
        if findings:
            raise ValueError('Target lint failed: ' + str(findings[:3]))
    report = load(args.source, args.target, args.workspace, args.backup, core, validate)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps({k: report[k] for k in ('workspace','blank_lines','loaded','new_rows','held','waiting')}))


if __name__ == '__main__':
    main()
