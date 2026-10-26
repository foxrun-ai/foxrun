"""MAP1's 111 reviewed rules, shared by all history and database writers.

The CSV is the reviewed source. A rule answers action, event table, and load.
Specific event/add rules precede existing words. Unknown evidence stays held.
"""

from __future__ import annotations
import csv
from dataclasses import dataclass
from pathlib import Path
from base import person


def migration_source():
    return person.configuration().get('history_migration_source', 'status migration')

CHANGE_ACTIONS = frozenset(('created', 'updated', 'moved', 'archived', 'deleted', 'captured',
                          'imported', 'claimed', 'started', 'finished', 'failed', 'verified',
                          'accepted', 'decided', 'replaced', 'corrected', 'merged', 'released',
                          'published', 'sent', 'fixed', 'restored', 'closed', 'rolled-back'))
ACTION_TABLES = {word: 'work_changes' for word in CHANGE_ACTIONS}
ACTION_TABLES.update(commented='work_comments', attached='work_attachments',
                     approved='base_approvals', rejected='base_approvals', edited='base_approvals',
                     discussed='base_approvals', **{word: 'base_receipts' for word in ('handed-off', 'compacted', 'forked')})
ACTIONS = frozenset(ACTION_TABLES)


@dataclass(frozen=True)
class ActionRule:
    action: str | None
    target_table: str | None
    load: str


with (Path(__file__).resolve().parent / 'history_action_map.csv').open(newline='') as _stream:
    ACTION_RULES = {(row['evidence_kind'], row['evidence']):
                    ActionRule(None if row['action'] == 'none' else row['action'],
                               None if row['target_table'] == 'none' else row['target_table'], row['load'])
                    for row in csv.DictReader(_stream)}

HELD = ActionRule(None, None, 'no: held')


def _rule(kind, evidence):
    return ACTION_RULES.get((kind, evidence))


def add_key(row):
    return tuple(row.get(key) for key in ('subject_type', 'subject_id', 'at', 'note'))


def record_add_keys(rows):
    """Only an evidenced id/stage line identifies the other columns of its add."""
    return {add_key(row) for row in rows if row.get('old_value') in (None, '') and
            ((row.get('field') == 'id' and row.get('source') in ('people cli', 'ugc cli') and
              (row.get('note') == 'added' or str(row.get('note') or '').startswith('accepted P-'))) or
             (row.get('field') == 'stage' and row.get('subject_type') == 'pipeline_stages' and row.get('note') == 'added'))}


def rule_for_row(row, adds=()):
    return history_rule(row.get('field'), row.get('new_value'), old=row.get('old_value'),
                        subject_type=row.get('subject_type'), note=row.get('note'),
                        verb=row.get('verb'), source=row.get('source'), record_add=add_key(row) in adds)


def history_rule(field, new=None, *, old=None, command=None, subject_type='task', note=None,
                 verb=None, source=None, record_add=False, call=None, status=None):
    """Return the reviewed rule. No missing record can turn a double into a load."""
    if command in ('comment', 'link'):
        return _rule('command', command)
    if field in ('comment', 'receipt', 'link'):
        return _rule('field', field)
    if field == 'approval' or command == 'approval-add':
        response = call or new
        return (_rule('command', 'approval-add; call ' + str(response)) if command == 'approval-add'
                else _rule('field', 'approval; new ' + str(response))) or HELD
    proposal = subject_type in ('proposal', 'proposals', 'base_proposals')
    if field == 'state' and proposal:
        if new == 'accepted':
            return _rule('field', 'state; proposal; new accepted')
        if old in (None, '') and new == 'pending':
            return _rule('field', 'state; proposal; old empty; new pending')
    if record_add and old in (None, ''):
        if field == 'id':
            return _rule('field', 'id; old empty; note added or accepted P-...; source people cli or ugc cli')
        if field == 'stage' and subject_type == 'pipeline_stages':
            return _rule('field', 'stage; pipeline stage; old empty; note added')
        return _rule('field', 'any other field; old empty; same record and same time and same note as a record add')
    for held_field in ('replaced_by', 'notion_link', 'notion-page', 'notion-projection'):
        if field == held_field:
            return _rule('field', field)
    if field in ('created_at', 'updated_at', 'evidence_refs'):
        return _rule('field', field + '; the record exists')
    if verb == 'migrated' and source == migration_source() and field in ('status', 'doc_status', 'stage'):
        return _rule('status', 'any new value; old word migrated; source status migration')
    if str(verb or '').strip() and verb not in ACTIONS and not (
        (verb in ('placed', 'unplaced') and field == 'parent') or
        (verb in ('blocked', 'canceled') and field in ('status', 'doc_status', 'stage') and new == verb)
    ):
        return HELD
    if command == 'decision-add' or (field in ('create', 'created') and subject_type == 'decision'):
        ruled = status == 'ruled' or 'status=ruled' in (note or '').split('; ')
        return _rule('command', 'decision-add; status ruled' if ruled else 'decision-add; any other status')
    if command == 'task-update' and field == 'parent':
        return _rule('command', 'task-update; field parent')
    if _rule('command', command):
        return _rule('command', command)
    if field in ('status', 'doc_status', 'stage'):
        exact = _rule('status', 'new ' + str(new) + '; note is exactly ' + str(note))
        if exact:
            return exact
        if subject_type == 'decision' and new == 'ruled':
            return _rule('status', 'decision; new ruled')
        if subject_type in ('deliverable', 'deliverables', 'ugc_deliverables') and old == 'proposed' and new == 'agreed':
            return _rule('status', 'deliverable; old proposed; new agreed')
        found = _rule('status', 'new ' + str(new))
        if found:
            return found
        if new == 'ruled':
            return _rule('status', 'new ruled; not a decision')
    if field in ('value', 'currency', 'agreed_amount') and str(note or '').startswith('accepted P-'):
        return _rule('field', 'value or currency or agreed_amount; the record exists; note accepted P-...')
    found = _rule('field', field)
    if found:
        return found
    if verb in ACTIONS:
        return ActionRule(verb, ACTION_TABLES[verb], 'yes')
    return HELD


def history_action(field, new=None, **evidence):
    return history_rule(field, new, **evidence).action


def database_action(object_type, field, old, new):
    """Database columns are schema-checked before this writer derives their word."""
    rule = history_rule(field, new, old=old, subject_type=object_type)
    if rule.action is not None:
        return rule.action
    # Section e: a later real field change is updated.
    return 'moved' if field in ('status', 'doc_status', 'stage') else 'updated'


def creation_action(object_type, status=None, imported=False):
    """An import is not a record's birth; fresh ruled decisions are decided."""
    if imported:
        return _rule('field', 'load').action
    return history_action('create', command='decision-add' if object_type == 'decision' else 'create',
                          subject_type=object_type, status=status)


def history_action_sql():
    """Compile the reviewed evidence into SQLite's independent source projection.

    The alias line names the source activity row. Command evidence is absent
    from historical lines. CASE order follows history_rule's specific rules.
    """
    quote = lambda value: 'NULL' if value is None else "'" + str(value).replace("'", "''") + "'"
    clauses = []
    def add(condition, rule):
        clauses.append('WHEN ' + condition + ' THEN ' + quote(rule.action))
    state = "line.field IN ('status','doc_status','stage')"
    empty = "coalesce(line.old_value,'')=''"
    same_add = "EXISTS(SELECT 1 FROM activity seed WHERE seed.subject_type IS line.subject_type AND seed.subject_id IS line.subject_id AND seed.at IS line.at AND seed.note IS line.note AND coalesce(seed.old_value,'')='' AND ((seed.field='id' AND seed.source IN ('people cli','ugc cli') AND (seed.note='added' OR seed.note LIKE 'accepted P-%')) OR (seed.field='stage' AND seed.subject_type='pipeline_stages' AND seed.note='added')))"
    for field in ('comment','receipt','link'):
        add('line.field=' + quote(field), _rule('field',field))
    for call in ('approve','wrong','edit','discuss'):
        add("line.field='approval' AND line.new_value=" + quote(call), _rule('field','approval; new '+call))
    add("line.field='approval'", HELD)
    proposal = "line.subject_type IN ('proposal','proposals','base_proposals') AND line.field='state'"
    add(proposal + " AND line.new_value='accepted'", _rule('field','state; proposal; new accepted'))
    add(proposal + ' AND ' + empty + " AND line.new_value='pending'", _rule('field','state; proposal; old empty; new pending'))
    add(same_add + ' AND ' + empty + " AND line.field='id'", _rule('field','id; old empty; note added or accepted P-...; source people cli or ugc cli'))
    add(same_add + ' AND ' + empty + " AND line.field='stage' AND line.subject_type='pipeline_stages'", _rule('field','stage; pipeline stage; old empty; note added'))
    add(same_add + ' AND ' + empty, _rule('field','any other field; old empty; same record and same time and same note as a record add'))
    for field in ('replaced_by','notion_link','notion-page','notion-projection'):
        add('line.field=' + quote(field), _rule('field',field))
    for field in ('created_at','updated_at','evidence_refs'):
        add('line.field=' + quote(field), _rule('field',field+'; the record exists'))
    add(state + " AND line.verb='migrated' AND line.source=" + quote(migration_source()), _rule('status','any new value; old word migrated; source status migration'))
    allowed = ','.join(quote(word) for word in sorted(ACTIONS))
    whitespace = 'char(9,10,11,12,13,28,29,30,31,32,133,160,5760,8192,8193,8194,8195,8196,8197,8198,8199,8200,8201,8202,8232,8233,8239,8287,12288)'
    nonblank = 'coalesce(trim(line.verb,' + whitespace + "),'')<>''"
    aliases = "((line.verb IN ('placed','unplaced') AND line.field='parent') OR (line.verb IN ('blocked','canceled') AND " + state + ' AND line.new_value=line.verb))'
    add(nonblank + ' AND line.verb NOT IN (' + allowed + ') AND NOT ' + aliases, HELD)
    decision_add = "line.field IN ('create','created') AND line.subject_type='decision'"
    ruled = "instr('; '||coalesce(line.note,'')||'; ', '; status=ruled; ')>0"
    add(decision_add + ' AND ' + ruled, _rule('command','decision-add; status ruled'))
    add(decision_add, _rule('command','decision-add; any other status'))
    for (kind, evidence), rule in ACTION_RULES.items():
        if kind != 'status' or evidence.startswith('any new value;'):
            continue
        condition = state
        if evidence.startswith('decision;'):
            condition += " AND line.subject_type='decision' AND line.new_value='ruled'"
        elif evidence.startswith('deliverable;'):
            condition += " AND line.subject_type IN ('deliverable','deliverables','ugc_deliverables') AND line.old_value='proposed' AND line.new_value='agreed'"
        else:
            condition += ' AND line.new_value=' + quote(evidence.split(';')[0][4:])
            if 'note is exactly ' in evidence:
                condition += ' AND line.note=' + quote(evidence.split('note is exactly ')[1])
            if 'not a decision' in evidence:
                condition += " AND line.subject_type IS NOT 'decision'"
        add(condition,rule)
    add("line.field IN ('value','currency','agreed_amount') AND line.note LIKE 'accepted P-%'", _rule('field','value or currency or agreed_amount; the record exists; note accepted P-...'))
    for (kind,evidence), rule in ACTION_RULES.items():
        if kind == 'field' and ';' not in evidence:
            add('line.field=' + quote(evidence),rule)
    clauses.append('WHEN line.verb IN (' + allowed + ') THEN line.verb')
    return 'CASE ' + ' '.join(clauses) + ' ELSE NULL END'


def history_source_select():
    return ('SELECT line.id,line.subject_type,line.subject_id,'
            "CASE line.field WHEN 'check_by' THEN 'reviewer' WHEN 'checked_by' THEN 'reviewed_by' ELSE line.field END,"
            'line.old_value,line.new_value,line.actor,line.source,line.at,line.note,' +
            history_action_sql() + ' FROM activity AS line')


def write_history(db, subject_type, subject_id, field, old, new, actor, source, at,
                  note=None, *, verb=None, row_id=None, known_field=False, **evidence):
    """Stamp a new line from this table without changing legacy schemas."""
    word = history_action(field, new, old=old, subject_type=subject_type, note=note,
                          verb=verb, source=source, **evidence)
    if word is None:
        if known_field:
            word = database_action(subject_type, field, old, new)
        else:
            raise ValueError('No reviewed history action: ' + str(field))
    data = dict(subject_type=subject_type, subject_id=subject_id, field=field,
                old_value=None if old is None else str(old), new_value=None if new is None else str(new),
                actor=actor, source=source, at=at, note=note)
    if row_id is not None:
        data['id'] = row_id
    columns = {r[1] for r in db.execute('PRAGMA table_info(activity)')}
    data = {key: value for key, value in data.items() if key in columns}
    if 'verb' in columns:
        data['verb'] = word
    db.execute('INSERT INTO activity (' + ','.join(data) + ') VALUES (' + ','.join('?' for _ in data) + ')', tuple(data.values()))
