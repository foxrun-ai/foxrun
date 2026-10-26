#!/usr/bin/env python3
"""Tests for blueprint v12 (T9, T8). Made-up rows only. Run: python3 v12_tests.py

Each class names the fix, the answer, or the ruling it proves. On the first v12 commit (457707b), 42 of the 45 tests
of round 2 fail; the three that pass there are controls (a load of old history is not held to the guards).
The tests of the evening rulings of 10.06 (the class RulingsOfTheEvening, and the six context values) fail on the round 2 commit 1dad908.
The tests of the second read (the class SecondReadOfTheSendGate) fail on the round 3 commit b584e04.
The tests of the read of 1d390ab (the class ReadOfRound4) fail on 1d390ab.
"""

from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from core import build, connect, execute, load

HERE = Path(__file__).resolve().parent.parent
# People and pack tables come from their add-ons' own blueprints (g-people-ships-with-small-talk).
from base.tests.addons import BLUEPRINT
AGENT = {'writer': 'agent', 'actor': 'comms-lead', 'session': 'v12-tests', 'workspace': 'cedar-shop', 'reason': None}
FEEDER = {'writer': 'feeder', 'actor': 'small-talk', 'source': 'v12-tests feeder', 'workspace': 'cedar-shop', 'session': None, 'reason': None}
IMPORT = {'writer': 'feeder', 'actor': 'staging-loader', 'source': 'v12-tests import', 'workspace': 'cedar-shop', 'reason': 'made-up history', 'import': 1}
sha = lambda text: hashlib.sha256(text.encode()).hexdigest()


class Database(unittest.TestCase):
    """One zero-state build for the class; each test works on its own copy."""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory(prefix='v12-tests-')
        cls.zero = Path(cls.folder.name) / 'zero.db'
        build(cls.zero, BLUEPRINT)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        self.path = Path(self.folder.name) / (self.id().split('.')[-1] + '.db')
        shutil.copy(self.zero, self.path)
        self.serial = 0

    def run_command(self, table, operation, data, identity=None, context=AGENT):
        return execute(self.path, BLUEPRINT, table, operation, data, identity, context)['id']

    def one(self, sql, args=()):
        db = connect(self.path, readonly=True)
        try:
            row = db.execute(sql, args).fetchone()
        finally:
            db.close()
        return row[0] if row is not None and len(row) == 1 else row

    def raw(self, sql, args=(), context=IMPORT):
        db = connect(self.path, context)
        try:
            db.execute(sql, args)
            db.commit()
        finally:
            db.close()

    def corrupt(self, sql, args=(), no_events=False):
        """Plant corruption on made-up rows, then restore the installed guards."""
        match = re.search(r'(?:UPDATE|INTO) ([a-z_]+)', sql)
        if not match:
            raise ValueError('The corruption test must name its table')
        table = match.group(1)
        db = connect(self.path, IMPORT)
        try:
            triggers = [(r['name'], r['sql']) for r in db.execute("SELECT name,sql FROM sqlite_schema WHERE type='trigger' AND tbl_name=?", (table,))
                        if '_state_' in r['name'] or (no_events and (r['name'].endswith('_changed') or r['name']==table+'_created'))]
            for name, _ in triggers:
                db.execute('DROP TRIGGER "' + name + '"')
            db.execute(sql, args)
            for _, definition in triggers:
                db.execute(definition)
            db.commit()
        finally:
            db.close()

    def refused(self, part, fn):
        with self.assertRaises((ValueError, sqlite3.Error)) as caught:
            fn()
        self.assertIn(part, str(caught.exception))

    def conversation(self):
        self.serial += 1
        return self.run_command('people_conversations', 'insert', {'channel': 'email', 'account': 'made-up', 'source_thread_id': 'thread-' + str(self.serial),
                                                                   'source_system': 'gmail', 'group_chat': 0, 'workspace_tags': json.dumps(['cedar-shop'])}, context=FEEDER)

    def message(self, conversation, text):
        self.serial += 1
        return self.run_command('people_messages', 'insert', {'conversation': conversation, 'channel': 'email', 'account': 'made-up', 'source_system': 'gmail',
                                                              'source_message_id': 'message-' + str(self.serial), 'sender_address': 'made-up@example.test',
                                                              'direction': 'outbound', 'text': text}, context=FEEDER)

    def draft(self, text='made-up words', family=None, conversation=None, **extra):
        self.serial += 1
        data = {'conversation': conversation or self.conversation(), 'family_id': family or 'family-' + str(self.serial), 'author': 'agent', 'status': 'draft'}
        if text is not None:
            data.update(text=text, content_hash=sha(text))
        data.update(extra)
        return self.run_command('people_drafts', 'insert', data)

    def yes(self, draft, **change):
        """His approval row for the current version and hash of one draft: the row that authorizes. Returns its seq."""
        version, digest, workspace = self.one('SELECT version,content_hash,workspace FROM people_drafts WHERE id=?', (draft,))
        data = {'subject_type': 'draft', 'subject_id': draft, 'version': version, 'approved_sha256': digest, 'authorization_valid': 1,
                'envelope_ref': 'made-up-envelope', 'go_word': 1, 'person_words': 'made-up yes'}
        data.update(change)
        return self.run_command('base_approvals', 'approved', {k: v for k, v in data.items() if v is not None}, context=dict(AGENT, actor='person', source='made-up chat', workspace=workspace))

    def approve(self, draft):
        self.run_command('people_drafts', 'update', {'approval': self.yes(draft), 'status': 'approved'}, draft)

    def typed_yes(self, draft):
        """An approval row an agent typed: action approved, and it does not authorize."""
        version, digest = self.one('SELECT version,content_hash FROM people_drafts WHERE id=?', (draft,))
        return self.run_command('base_approvals', 'approved', {'subject_type': 'draft', 'subject_id': draft, 'version': version, 'approved_sha256': digest})

    def later_version(self, draft, text='later made-up words', context=AGENT):
        conversation, family = self.one('SELECT conversation,family_id FROM people_drafts WHERE id=?', (draft,))
        return self.run_command('people_drafts', 'insert', {'conversation': conversation, 'family_id': family, 'author': 'agent', 'status': 'draft', 'text': text}, context=context)

    def status(self, draft):
        return self.one('SELECT status FROM people_drafts WHERE id=?', (draft,))

    def record(self):
        """A made-up record a fact can come from."""
        return self.run_command('work_tasks', 'insert', {'title': 'Made-up record', 'status': 'todo', 'reviewer': 'lead', 'reviewed_by': 'chief-of-staff'})

    def fact(self, draft, **data):
        return self.run_command('people_draft_facts', 'insert', dict({'draft': draft, 'text': 'a made-up fact'}, **data))


class Fix1RegenerateOnAnOlderDatabase(unittest.TestCase):
    """The reader's fix 1: regenerate.py on a database made before the new table."""

    def root(self, business_row=False):
        folder = tempfile.TemporaryDirectory(prefix='v12-regenerate-')
        self.addCleanup(folder.cleanup)
        root = Path(folder.name).resolve()
        (root / 'code/foxrun-modules').mkdir(parents=True)
        shutil.copytree(HERE, root / 'code/foxrun-modules/base', ignore=shutil.ignore_patterns('tests', '__pycache__'))
        path = root / 'home/older/data.db'
        build(path, BLUEPRINT)
        if business_row:
            execute(path, BLUEPRINT, 'work_tasks', 'insert', {'title': 'Made-up task', 'status': 'todo', 'reviewer': 'lead', 'reviewed_by': 'chief-of-staff'}, None, dict(AGENT, workspace='system-workspace'))
        older = sqlite3.connect(path)  # Make it older: a database with no fact table and no view of it.
        older.execute('DROP VIEW people_conversations_in_hand')
        older.execute('DROP TABLE people_draft_facts')
        older.commit()
        older.close()
        return root, path

    def test_an_older_database_with_no_business_rows_is_rebuilt(self):
        from regenerate import regenerate
        root, path = self.root()
        desired = regenerate(root, 'home/older/data.db')
        db = connect(path, readonly=True)
        try:
            # The core holds no People table: it comes with Small Talk (g-people-ships-with-small-talk).
            self.assertEqual(db.execute("SELECT count(*) FROM sqlite_schema WHERE name='people_draft_facts'").fetchone()[0], 0)
        finally:
            db.close()
        self.assertEqual(len(list(path.parent.glob('data.db.schema-*.archive'))), 1)
        self.assertEqual(len(desired), 64)

    def test_an_older_database_with_a_business_row_is_refused(self):
        from regenerate import regenerate
        root, path = self.root(business_row=True)
        with self.assertRaises(ValueError) as caught:
            regenerate(root, 'home/older/data.db')
        self.assertIn('preserve business rows', str(caught.exception))
        self.assertIn('work_tasks', str(caught.exception))


class Fix2TheReleaseListNamesTheBlueprint(unittest.TestCase):
    """The reader's fix 2: the committed release list is the list of this blueprint."""

    def test_the_release_list_names_the_blueprint_files_and_every_table_command(self):
        from core import BLUEPRINT as VERSION
        manifest = json.loads(((Path(__file__).resolve().parent / '../distribution/release/manifest.json')).read_text())
        shipped = {row['archive_path'] for row in manifest['files']}
        self.assertEqual(manifest['blueprint_version'], VERSION)
        self.assertEqual({p for p in shipped if p.startswith('base/blueprint/')}, {'base/blueprint/target-v' + VERSION + '.jsonl', 'base/blueprint/columns-v' + VERSION + '.jsonl'})
        self.assertEqual({p.rsplit('/', 1)[1] for p in shipped if p.startswith('base/commands/')}, {p.name for p in ((Path(__file__).resolve().parent / '../commands')).iterdir() if p.is_file() and not p.name.startswith('.')})

    def test_the_shipped_blueprint_keeps_the_guards_of_a_draft(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('v12_sample', (Path(__file__).resolve().parent / '../distribution/sample_workspace.py'))
        sample = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sample)
        targets, columns = sample.portable_blueprint(BLUEPRINT)
        drafts = next(t for t in targets if t['name'] == 'people_drafts')
        effective = next(t for t in load(BLUEPRINT)[0] if t['name']=='people_drafts')
        self.assertEqual(drafts['state_guards'], sample.portable_owner(effective['state_guards']))
        self.assertEqual((drafts['version_columns'], drafts['version_family'], drafts['hash_columns']), (['text', 'content_hash'], 'family_id', {'content_hash': 'text'}))
        self.assertFalse(any('value_set_guard' in c for c in columns))  # A value set is a private pick.


class Fix3EveryRowSaysWhoRuledIt(unittest.TestCase):
    """The reader's fix 3, after his ruling what-a-draft-keeps: no row is stamped as ruled without its decision, and none waits."""

    KEEPS = 'what-a-draft-keeps'

    def test_the_fact_table_and_the_draft_fields_are_ruled_by_what_a_draft_keeps(self):
        targets, columns = load(BLUEPRINT)
        table = next(t for t in targets if t['name'] == 'people_draft_facts')
        self.assertEqual((table['flags'], table['rulings'], table['word_status']), ([], [self.KEEPS, 'his-yes-covers-the-facts-shown-with-the-message'], 'ruled: draft-fact (' + self.KEEPS + ')'))
        self.assertNotIn('waits_for', table)
        self.assertFalse(any('no ruling' in flag for flag in next(t for t in targets if t['name'] == 'people_drafts')['flags']))
        answers = {('people_drafts', 'requested_by'): 'batch 4, answer 1.1', ('people_drafts', 'request'): 'batch 4, answer 1.1', ('people_drafts', 'send_result'): 'batch 4, answer 1.5',
                   ('people_draft_facts', 'source_ref'): 'batch 4, answer 1.2'}
        answers.update({('people_draft_facts', name): 'batch 2, answer 3.A3' for name in ('id', 'draft', 'text', 'source_type', 'source_id', 'reviewed_by')})
        rows = {(c['table'], c['column']): c for c in columns}
        self.assertEqual({key for key in rows if key[0] == 'people_draft_facts'}, {key for key in answers if key[0] == 'people_draft_facts'} | {('people_draft_facts', 'checked_at')})
        self.assertEqual(rows['people_draft_facts', 'checked_at']['ruling'], [self.KEEPS])
        self.assertEqual(rows['people_draft_facts', 'checked_at']['field_type'], 'timestamp')
        for key, answer in answers.items():
            c = rows[key]
            self.assertEqual((c['audit']['verdict'], c['ruling']), ('ruling', [self.KEEPS]), key)
            self.assertEqual(c['audit']['basis'], 'ruled by ' + self.KEEPS + "; storage by the Architect's reading (" + answer + ')', key)
            self.assertEqual(c['storage_reading'], c['audit']['basis'], key)
        self.assertFalse([c for c in columns if c.get('waits_for') or c.get('audit', {}).get('verdict') == 'no ruling'])

    def test_the_ruled_view_and_person_fields_name_their_ruling(self):
        _, columns = load(BLUEPRINT)
        for c in columns:
            if c['table'] == 'people_conversations_in_hand':
                self.assertEqual((c['audit']['verdict'], c['ruling']), ('ruling', ['conversation-in-hand']), c['column'])
            if c['table'] == 'people_contacts' and c['column'] in ('register_from', 'name_used', 'greeting', 'speaks_as', 'voice_notes'):
                self.assertEqual((c['audit']['verdict'], c['ruling']), ('ruling', ['person-voice-fields']), c['column'])
        marked = {(c['table'], c['column']) for c in columns if c.get('reading')}
        self.assertEqual(marked, {('people_drafts', 'text'), ('people_drafts', 'content_hash'), ('people_draft_facts', 'reviewed_by'),
                                  ('people_contacts', 'register_from'), ('people_contacts', 'contexts')})

    def test_the_dictionary_rows_carry_the_ruling_and_the_sentences(self):
        folder = tempfile.TemporaryDirectory(prefix='v12-dictionary-')
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / 'data.db'
        build(path, BLUEPRINT)
        db = connect(path, readonly=True)
        try:
            description, definition = db.execute("SELECT description,definition FROM base_object_types WHERE location='people_draft_facts'").fetchone()
            fields = {r[0]: (r[1], json.loads(r[2])) for r in db.execute("SELECT f.field,f.description,f.source FROM base_fields f JOIN base_object_types o ON o.id=f.object_type WHERE o.location IN ('people_drafts','people_draft_facts') AND f.field IN ('requested_by','request','send_result','source_ref')")}
        finally:
            db.close()
        self.assertEqual(description, 'One fact a draft uses, saved by itself, with where it came from and who checked it.')
        self.assertEqual(json.loads(definition)['word_status'], 'ruled: draft-fact (' + self.KEEPS + ')')
        self.assertEqual({name: sentence for name, (sentence, _) in fields.items()}, {
            'requested_by': 'The person or agent that requested this message.',
            'request': "What the message must do, in the asker's words, with any limit.",
            'send_result': 'What happened at the last send that is not proven delivered; empty when no send was tried or the send arrived.',
            'source_ref': 'The source path, link, or owner statement reference for this fact.'})
        for name, (_, source) in fields.items():
            self.assertEqual(source['rules']['audit']['verdict'], 'ruling', name)


class Fix4TheViewKeepsTheAgent(Database):
    """The reader's fix 4, and the cases its parity test did not cover."""

    def test_the_agent_stays_when_the_workspace_of_the_draft_changes(self):
        draft = self.draft()
        self.assertEqual(self.one('SELECT agent FROM people_conversations_in_hand WHERE draft=?', (draft,)), 'comms-lead')
        self.run_command('people_drafts', 'update', {'workspace': 'system-workspace'}, draft)
        self.assertEqual(tuple(self.one('SELECT agent,workspace FROM people_conversations_in_hand WHERE draft=?', (draft,))), ('comms-lead', 'system-workspace'))

    def test_a_draft_with_no_created_event_shows_with_no_agent(self):
        conversation = self.conversation()
        self.corrupt("INSERT INTO people_drafts (conversation,family_id,version,author,status,workspace,text,content_hash) VALUES (?,?,?,?,?,?,?,?)",
                     (conversation, 'made-up-import', 1, 'agent', 'draft', 'cedar-shop', 'made-up words', sha('made-up words')), no_events=True)
        self.assertEqual(tuple(self.one('SELECT count(*),count(agent) FROM people_conversations_in_hand')), (1, 0))


class AnswerA7TheVersionNamesTheText(Database):
    """Batch 2, answer 3.A7 (settled); bug B-20261006-draft-status-move-advances-version."""

    def test_a_status_move_keeps_the_version_so_his_yes_still_matches(self):
        draft = self.draft()
        self.approve(draft)
        self.assertEqual(tuple(self.one('SELECT d.status,d.version,a.version FROM people_drafts d JOIN base_approvals a ON a.seq=d.approval WHERE d.id=?', (draft,))), ('approved', 1, 1))
        self.assertEqual(self.one("SELECT count(*) FROM work_changes WHERE subject_type='draft' AND subject_id=? AND field='status'", (draft,)), 1)

    def test_a_change_of_text_advances_the_version_by_one(self):
        draft = self.draft()
        self.run_command('people_drafts', 'update', {'text': 'other made-up words', 'content_hash': sha('other made-up words')}, draft)
        self.assertEqual(self.one('SELECT version FROM people_drafts WHERE id=?', (draft,)), 2)
        self.run_command('people_drafts', 'update', {'requested_by': 'reviewer'}, draft)
        self.assertEqual(self.one('SELECT version FROM people_drafts WHERE id=?', (draft,)), 2)

    def test_the_database_refuses_a_version_move_with_the_same_text(self):
        draft = self.draft()
        self.refused('version advances only when text or content_hash changes', lambda: self.raw('UPDATE people_drafts SET version=version+1 WHERE id=?', (draft,)))

    def test_the_lint_is_clean_after_two_status_moves_on_one_version(self):
        from lint import lint
        conversation = self.conversation()
        draft = self.draft(conversation=conversation)
        self.approve(draft)
        self.run_command('people_drafts', 'update', {'sent_message': self.message(conversation, 'made-up words'), 'status': 'sent'}, draft)
        self.assertEqual(tuple(self.one('SELECT status,version FROM people_drafts WHERE id=?', (draft,))), ('sent', 1))
        self.assertEqual(lint(self.path, BLUEPRINT), [])


class AnswerA1ADraftRowBeforeAnyWords(Database):
    """Batch 2, answer 3.A1 (the Architect's reading)."""

    def test_a_draft_row_is_made_with_no_words_and_puts_the_conversation_in_hand(self):
        draft = self.draft(text=None)
        self.assertEqual(tuple(self.one('SELECT text,content_hash,status FROM people_drafts WHERE id=?', (draft,))), (None, None, 'draft'))
        self.assertEqual(self.one('SELECT count(*) FROM people_conversations_in_hand WHERE draft=?', (draft,)), 1)

    def test_approved_and_sent_need_the_words_and_the_hash(self):
        for words, digest in ((None, None), ('', ''), ('   ', sha('   ')), ('made-up words', '')):
            for status in ('approved', 'sent'):
                self.serial += 1
                draft = self.draft(text=None)
                self.raw('UPDATE people_drafts SET text=?,content_hash=? WHERE id=?', (words, digest, draft))
                with self.assertRaises(sqlite3.Error):
                    self.raw('UPDATE people_drafts SET status=? WHERE id=?', (status, draft))
        draft = self.draft(text=None)
        self.raw("UPDATE people_drafts SET status='skipped' WHERE id=?", (draft,))  # A draft with no words can be skipped.


class AnswersA4A6TheReviewOfAFactLine(Database):
    """Batch 2, answers 3.A4 and 3.A6 (the Architect's readings) on the table that waits for his word."""

    def fact(self):
        draft = self.draft()
        fact = self.run_command('people_draft_facts', 'insert', {'draft': draft, 'text': 'a made-up fact'})
        self.run_command('people_draft_facts', 'update', {'reviewed_by': 'reviewer'}, fact, dict(AGENT, actor='reviewer'))
        return fact

    def test_the_field_is_reviewed_by(self):
        _, columns = load(BLUEPRINT)
        names = {c['column'] for c in columns if c['table'] == 'people_draft_facts'}
        self.assertIn('reviewed_by', names)
        self.assertNotIn('checked_by', names)

    def test_a_fact_line_that_changes_after_the_review_loses_its_review(self):
        fact = self.fact()
        self.assertEqual(self.one('SELECT reviewed_by FROM people_draft_facts WHERE id=?', (fact,)), 'reviewer')
        self.run_command('people_draft_facts', 'update', {'text': 'a changed made-up fact'}, fact)
        self.assertIsNone(self.one('SELECT reviewed_by FROM people_draft_facts WHERE id=?', (fact,)))
        events = self.one("SELECT group_concat(field || ':' || coalesce(new_value,'empty') || ':' || actor, ' | ') FROM (SELECT * FROM work_changes WHERE subject_type='draft-fact' AND subject_id=? AND field IS NOT NULL ORDER BY seq)", (fact,))
        self.assertEqual(sorted(events.split(' | ')), sorted(['reviewed_by:reviewer:reviewer', 'text:a changed made-up fact:comms-lead', 'reviewed_by:empty:comms-lead']))

    def test_a_change_of_the_source_also_loses_the_review(self):
        fact = self.fact()
        task = self.run_command('work_tasks', 'insert', {'title': 'Made-up record', 'status': 'todo', 'reviewer': 'lead', 'reviewed_by': 'chief-of-staff'})
        self.run_command('people_draft_facts', 'update', {'source_type': 'task', 'source_id': task}, fact)
        self.assertIsNone(self.one('SELECT reviewed_by FROM people_draft_facts WHERE id=?', (fact,)))

    def test_a_review_in_the_same_write_as_the_fix_stays(self):
        fact = self.fact()
        self.run_command('people_draft_facts', 'update', {'text': 'a fixed made-up fact', 'reviewed_by': 'adviser'}, fact, dict(AGENT, actor='adviser'))
        self.assertEqual(self.one('SELECT reviewed_by FROM people_draft_facts WHERE id=?', (fact,)), 'adviser')


class AnswersB1B2ThePersonFields(Database):
    """Batch 2, answers 3.B2 and 3.B1 with 2.G7 (the Architect's readings)."""

    def person(self, **data):
        self.serial += 1
        return self.run_command('people_contacts', 'insert', dict({'name': 'Made-up Person ' + str(self.serial)}, **data))

    def test_register_from_has_the_default_default(self):
        self.assertEqual(tuple(self.one('SELECT register,register_from,speaks_as FROM people_contacts WHERE id=?', (self.person(),))), ('professional', 'default', 'person'))

    def test_contexts_takes_only_values_of_the_seeded_set(self):
        import value_sets
        message = 'contexts needs one or more values of the set contact-context'
        self.refused(message, lambda: self.person(contexts=json.dumps(['friend'])))  # Before the seed the set is empty.
        self.assertEqual(value_sets.seed(self.path, BLUEPRINT, dict(AGENT, workspace='system-workspace')), 6)
        self.assertEqual(value_sets.seed(self.path, BLUEPRINT, dict(AGENT, workspace='system-workspace')), 0)
        self.assertEqual(self.one("SELECT group_concat(value) FROM (SELECT value FROM base_values WHERE \"set\"='contact-context' ORDER BY sort_order)"), 'family,friend,builder,service,creator,other')  # creator: person-context-gains-creator
        person = self.person(contexts=json.dumps(['friend', 'builder']))
        self.assertEqual(self.one('SELECT contexts FROM people_contacts WHERE id=?', (person,)), json.dumps(['friend', 'builder']))
        self.assertEqual(self.one('SELECT contexts FROM people_contacts WHERE id=?', (self.person(contexts=json.dumps(['creator'])),)), json.dumps(['creator']))
        self.assertIsNone(self.one('SELECT contexts FROM people_contacts WHERE id=?', (self.person(),)))  # Not filled yet.
        for bad in (['made-up-word'], ['friend', 'made-up-word'], [], [None]):
            self.refused(message, lambda: self.person(contexts=json.dumps(bad)))
            self.refused(message, lambda: self.run_command('people_contacts', 'update', {'contexts': json.dumps(bad)}, person))
        self.run_command('people_contacts', 'update', {'contexts': json.dumps(['other'])}, person)

    def test_an_import_keeps_its_source_list(self):
        self.raw('INSERT INTO people_contacts (name,number,contexts) VALUES (?,?,?)', ('Made-up Import', 'made-up-import', json.dumps(['made-up-old-word', 'cedar-shop'])))
        self.assertEqual(self.one("SELECT count(*) FROM people_contacts WHERE number='made-up-import'"), 1)


class Batch9TheStatusMovesOfADraft(Database):
    """Batch 9, answers 1.1 and 1.2. Lines 1 to 3 are settled; lines 4 to 7 are the Architect's reading."""

    def move(self, draft, status, **more):
        self.run_command('people_drafts', 'update', dict(more, status=status), draft)

    def test_1_1_a_draft_does_not_move_straight_to_sent(self):
        conversation = self.conversation()
        draft = self.draft(conversation=conversation)
        message = self.message(conversation, 'made-up words')
        with self.assertRaises((ValueError, sqlite3.Error)):
            self.move(draft, 'sent', sent_message=message)
        self.refused('a draft moves to sent only after approved', lambda: self.move(draft, 'sent', sent_message=message, approval=self.yes(draft)))
        self.assertEqual(self.status(draft), 'draft')

    def test_1_2_line_1_approved_needs_his_approval_row_for_this_version_and_hash(self):
        need = 'approved and sent need his approval row for this exact version and hash'
        draft, other = self.draft(), self.draft()
        self.refused(need, lambda: self.move(draft, 'approved'))  # No approval row.
        self.refused(need, lambda: self.move(draft, 'approved', approval=self.yes(other)))  # Another draft's approval.
        self.refused(need, lambda: self.move(draft, 'approved', approval=self.typed_yes(draft)))  # A row that does not authorize.
        edited = self.run_command('base_approvals', 'edited', {'subject_type': 'draft', 'subject_id': draft, 'version': 1, 'summary': 'made-up edit'})
        self.refused(need, lambda: self.move(draft, 'approved', approval=edited))  # An edit is never a yes.
        seq = self.yes(draft)
        later = self.later_version(draft, 'newer made-up words')
        self.refused(need, lambda: self.move(later, 'approved', approval=seq))
        self.move(later, 'approved', approval=self.yes(later))
        self.assertEqual(tuple(self.one('SELECT status,version FROM people_drafts WHERE id=?', (later,))), ('approved', 2))
        self.assertEqual(self.one("SELECT count(*) FROM work_needs_me WHERE subject_type='draft' AND subject_id=?", (later,)), 0)
        wordless = self.draft(text=None)
        self.refused(need, lambda: self.move(wordless, 'approved'))

    def test_1_2_line_2_sent_needs_the_read_back_of_that_exact_text(self):
        need = 'sent needs the read-back'
        conversation = self.conversation()
        draft = self.draft(conversation=conversation)
        self.approve(draft)
        self.refused(need, lambda: self.move(draft, 'sent'))
        self.refused(need, lambda: self.move(draft, 'sent', sent_message=self.message(conversation, 'other made-up words')))
        self.assertEqual(self.status(draft), 'approved')  # A failed send keeps approved; the conversation stays in hand.
        self.assertEqual(self.one('SELECT count(*) FROM people_conversations_in_hand WHERE draft=?', (draft,)), 1)
        self.move(draft, 'sent', sent_message=self.message(conversation, 'made-up words'))
        self.assertEqual(self.status(draft), 'sent')

    def test_1_2_line_4_draft_or_approved_moves_to_skipped(self):
        conversation = self.conversation()
        draft, approved = self.draft(), self.draft(conversation=conversation)
        self.approve(approved)
        for each in (draft, approved):
            self.move(each, 'skipped')
            self.assertEqual(self.status(each), 'skipped')
        # His no after his yes: the approval row stays, the status stops the send (batch 9 second run, answer 1.2).
        self.refused('sent, skipped, and replaced are ends', lambda: self.move(approved, 'sent', sent_message=self.message(conversation, 'made-up words')))

    def test_1_2_line_5_replaced_needs_a_later_version_in_the_family(self):
        need = 'replaced needs a later version in the same family'
        draft = self.draft(family='made-up-family')
        self.refused(need, lambda: self.move(draft, 'replaced'))
        self.later_version(draft)  # The later version replaces the open one in the same write.
        self.assertEqual(self.status(draft), 'replaced')

    def test_1_2_line_6_approved_does_not_go_back_to_draft(self):
        draft = self.draft()
        self.approve(draft)
        self.refused('approved does not go back to draft', lambda: self.move(draft, 'draft'))

    def test_1_2_line_7_sent_skipped_and_replaced_are_ends(self):
        conversation = self.conversation()
        sent = self.draft(conversation=conversation)
        self.approve(sent)
        self.move(sent, 'sent', sent_message=self.message(conversation, 'made-up words'))
        skipped = self.draft()
        self.move(skipped, 'skipped')
        replaced = self.draft(family='made-up-family')
        self.later_version(replaced)
        for draft, was in ((sent, 'sent'), (skipped, 'skipped'), (replaced, 'replaced')):
            for status in ('draft', 'approved', 'sent', 'skipped', 'replaced'):
                if status != was:
                    self.refused('sent, skipped, and replaced are ends', lambda: self.move(draft, status))
            self.assertEqual(self.status(draft), was)

    def test_the_load_of_old_history_is_not_a_move(self):
        draft = self.draft()
        yes = self.typed_yes(draft)
        conversation = self.one('SELECT conversation FROM people_drafts WHERE id=?', (draft,))
        message = self.message(conversation, 'made-up words')
        self.raw("UPDATE people_drafts SET status='sent',approval=?,sent_message=? WHERE id=?", (yes, message, draft))
        self.assertEqual(self.status(draft), 'sent')  # History skips the move order and keeps its evidence.


class Batch11TheSendGate(Database):
    """Batch 11, answers 2.1 to 2.5 and 2.A to 2.C. 2.1 to 2.4, 2.A, and the meaning in 2.C are settled; 2.5 is the Architect's reading."""

    def test_2_C_a_new_row_takes_the_next_number_of_its_family(self):
        first = self.draft(family='made-up-family')
        second = self.later_version(first)
        third = self.later_version(second, 'third made-up words')
        self.assertEqual(self.one("SELECT group_concat(version || ':' || status, ' ') FROM (SELECT * FROM people_drafts WHERE family_id='made-up-family' ORDER BY version)"), '1:replaced 2:replaced 3:draft')
        self.assertEqual(self.one("SELECT count(*) FROM work_changes WHERE subject_type='draft' AND subject_id=? AND field='status' AND new_value='replaced'", (first,)), 1)
        self.assertEqual(self.one('SELECT version FROM people_drafts WHERE id=?', (self.draft(),)), 1)  # Another family starts at 1.
        self.assertEqual(self.one('SELECT count(*) FROM people_conversations_in_hand WHERE draft IN (?,?,?)', (first, second, third)), 1)

    def test_2_1_the_hash_is_always_the_hash_of_the_text(self):
        draft = self.run_command('people_drafts', 'insert', {'conversation': self.conversation(), 'family_id': 'made-up-family', 'author': 'agent', 'status': 'draft', 'text': 'made-up words'})
        self.assertEqual(self.one('SELECT content_hash FROM people_drafts WHERE id=?', (draft,)), sha('made-up words'))
        self.run_command('people_drafts', 'update', {'text': 'other made-up words'}, draft)
        self.assertEqual(self.one('SELECT content_hash FROM people_drafts WHERE id=?', (draft,)), sha('other made-up words'))
        need = 'content_hash must be the sha256 of text'
        self.refused(need, lambda: self.run_command('people_drafts', 'update', {'content_hash': sha('made-up words')}, draft))
        self.refused(need, lambda: self.run_command('people_drafts', 'update', {'text': 'third made-up words', 'content_hash': sha('wrong made-up words')}, draft))
        self.refused(need, lambda: self.draft(text=None, content_hash=sha('made-up words')))

    def test_2_1_the_words_do_not_change_after_his_yes(self):
        draft = self.draft()
        self.approve(draft)
        for change in ({'text': 'changed made-up words'}, {'text': None}):
            with self.assertRaises((ValueError, sqlite3.Error)):
                self.run_command('people_drafts', 'update', change, draft)
        skipped = self.draft()
        self.run_command('people_drafts', 'update', {'status': 'skipped'}, skipped)
        self.refused('the text and its hash change only while the status is draft', lambda: self.run_command('people_drafts', 'update', {'text': 'changed made-up words'}, skipped))
        self.assertEqual(tuple(self.one('SELECT text,content_hash,version,status FROM people_drafts WHERE id=?', (draft,))), ('made-up words', sha('made-up words'), 1, 'approved'))

    def test_2_3_a_new_row_is_not_approved_or_sent(self):
        for status in ('approved', 'sent'):
            self.refused('a new draft row is not approved or sent', lambda: self.draft(status=status))

    def test_2_4_another_approval_is_not_linked_after_his_yes(self):
        draft, other = self.draft(), self.draft()
        self.approve(draft)
        need = 'approved and sent need his approval row for this exact version and hash'
        self.refused(need, lambda: self.run_command('people_drafts', 'update', {'approval': self.yes(other)}, draft))
        self.refused(need, lambda: self.run_command('people_drafts', 'update', {'approval': None}, draft))
        self.refused(need, lambda: self.run_command('people_drafts', 'update', {'workspace': 'system-workspace'}, draft))

    def test_2_5_a_yes_on_a_draft_needs_his_words_and_the_place_he_said_them(self):
        draft = self.draft()
        need = 'a yes on a draft needs his words and the place he said them'
        self.refused(need, lambda: self.yes(draft, person_words=None))
        self.refused(need, lambda: self.yes(draft, person_words='  '))
        version, digest = self.one('SELECT version,content_hash FROM people_drafts WHERE id=?', (draft,))
        row = {'subject_type': 'draft', 'subject_id': draft, 'version': version, 'approved_sha256': digest, 'authorization_valid': 1, 'envelope_ref': 'made-up-envelope', 'go_word': 1, 'person_words': 'made-up yes'}
        self.refused(need, lambda: self.run_command('base_approvals', 'approved', row, context=dict(AGENT, actor='person')))  # No source.
        self.refused('Authorization requires Person', lambda: self.run_command('base_approvals', 'approved', row, context=dict(AGENT, source='made-up chat')))
        self.assertGreater(self.yes(draft), 0)


class Batch11OneOpenDraftPerConversation(Database):
    """Batch 11, answers 4.1 and 4.2 (the Architect's reading)."""

    NEED = 'the conversation is in hand: one open draft per conversation'

    def test_a_second_open_draft_on_one_conversation_is_refused(self):
        conversation = self.conversation()
        first = self.draft(conversation=conversation)
        self.refused(self.NEED, lambda: self.draft(conversation=conversation))
        self.approve(first)
        self.refused(self.NEED, lambda: self.draft(conversation=conversation))  # Approved is open too.
        self.assertEqual(tuple(self.one('SELECT count(*),count(DISTINCT conversation) FROM people_conversations_in_hand')), (1, 1))
        self.run_command('people_drafts', 'update', {'status': 'skipped'}, first)
        self.draft(conversation=conversation)  # After the end of the first, the conversation takes a new draft.

    def test_an_open_draft_does_not_move_to_a_conversation_in_hand(self):
        first, second = self.draft(), self.draft()
        target = self.one('SELECT conversation FROM people_drafts WHERE id=?', (first,))
        self.refused(self.NEED, lambda: self.run_command('people_drafts', 'update', {'conversation': target}, second))

    def test_another_agent_takes_over_only_a_stale_draft(self):
        other = dict(AGENT, actor='reviewer')
        draft = self.draft()
        self.refused(self.NEED, lambda: self.later_version(draft, context=other))  # Fresh, and another agent's.
        self.raw("UPDATE people_drafts SET created_at=datetime('now','-2 days'),updated_at=datetime('now','-2 days') WHERE id=?", (draft,), IMPORT)
        self.assertEqual(self.one('SELECT stale FROM people_conversations_in_hand WHERE draft=?', (draft,)), 1)
        taken = self.later_version(draft, context=other)
        self.assertEqual(self.status(draft), 'replaced')
        self.assertEqual(tuple(self.one('SELECT draft,agent,stale FROM people_conversations_in_hand')), (taken, 'reviewer', 0))

    def test_a_load_of_old_history_is_not_held_to_it(self):
        conversation = self.conversation()
        for family in ('made-up-old-1', 'made-up-old-2'):
            self.raw('INSERT INTO people_drafts (conversation,family_id,version,author,status,workspace) VALUES (?,?,1,?,?,?)', (conversation, family, 'agent', 'draft', 'cedar-shop'))
        self.assertEqual(tuple(self.one('SELECT count(*),count(DISTINCT conversation) FROM people_conversations_in_hand')), (2, 1))


class Batch11TheFactLinesAndHisYes(Database):
    """Batch 11, answers 1 and 3 (the Architect's reading), on the table that waits for his word."""

    def test_1_the_fact_lines_are_frozen_once_the_draft_is_not_a_draft(self):
        need = 'a fact line changes only while its draft is a draft'
        draft = self.draft()
        fact = self.run_command('people_draft_facts', 'insert', {'draft': draft, 'text': 'a made-up fact', 'reviewed_by': 'reviewer', 'source_type': 'task', 'source_id': self.record()})
        self.approve(draft)
        self.refused(need, lambda: self.run_command('people_draft_facts', 'insert', {'draft': draft, 'text': 'a late made-up fact'}))
        self.refused(need, lambda: self.run_command('people_draft_facts', 'update', {'text': 'a changed made-up fact'}, fact))
        self.refused(need, lambda: self.run_command('people_draft_facts', 'update', {'reviewed_by': 'adviser'}, fact))
        for end in ('skipped',):
            ended = self.draft()
            line = self.run_command('people_draft_facts', 'insert', {'draft': ended, 'text': 'a made-up fact', 'reviewed_by': 'reviewer'})
            self.run_command('people_drafts', 'update', {'status': end}, ended)
            self.refused(need, lambda: self.run_command('people_draft_facts', 'update', {'text': 'a changed made-up fact'}, line))
        self.assertEqual(tuple(self.one('SELECT text,reviewed_by FROM people_draft_facts WHERE id=?', (fact,))), ('a made-up fact', 'reviewer'))

    def test_1_the_draft_of_a_fact_line_never_changes(self):
        draft, other = self.draft(), self.draft()
        fact = self.run_command('people_draft_facts', 'insert', {'draft': draft, 'text': 'a made-up fact'})
        self.refused('the draft of a fact line never changes', lambda: self.run_command('people_draft_facts', 'update', {'draft': other}, fact))

    def test_3_a_source_kind_and_its_id_are_both_filled_or_both_empty(self):
        draft = self.draft()
        task = self.run_command('work_tasks', 'insert', {'title': 'Made-up record', 'status': 'todo', 'reviewer': 'lead', 'reviewed_by': 'chief-of-staff'})
        self.refused('CHECK', lambda: self.run_command('people_draft_facts', 'insert', {'draft': draft, 'text': 'a made-up fact', 'source_type': 'task'}))
        with self.assertRaises((ValueError, sqlite3.Error)):
            self.run_command('people_draft_facts', 'insert', {'draft': draft, 'text': 'a made-up fact', 'source_id': task})
        self.run_command('people_draft_facts', 'insert', {'draft': draft, 'text': 'a made-up fact', 'source_type': 'task', 'source_id': task})
        self.run_command('people_draft_facts', 'insert', {'draft': draft, 'text': 'a made-up fact with no record'})

    def test_3_a_fact_with_no_record_and_no_reviewer_holds_the_move_to_approved(self):
        need = 'a fact with no record waits for his decision'
        draft = self.draft()
        fact = self.run_command('people_draft_facts', 'insert', {'draft': draft, 'text': 'a made-up fact with no record'})
        seq = self.yes(draft)
        self.refused(need, lambda: self.run_command('people_drafts', 'update', {'approval': seq, 'status': 'approved'}, draft))
        # His decision: his approval row is on the draft, then the reviewer of the marked line becomes person, then the status moves.
        self.run_command('people_draft_facts', 'update', {'reviewed_by': 'person'}, fact, dict(AGENT, actor='chief-of-staff'))
        self.run_command('people_drafts', 'update', {'approval': seq, 'status': 'approved'}, draft)
        self.assertEqual(self.status(draft), 'approved')

    def test_3_a_typed_reviewer_person_is_not_his_decision(self):
        need = 'the reviewer person needs his approval row on the draft'
        draft = self.draft()
        self.refused(need, lambda: self.run_command('people_draft_facts', 'insert', {'draft': draft, 'text': 'a made-up fact', 'reviewed_by': 'person'}))
        fact = self.run_command('people_draft_facts', 'insert', {'draft': draft, 'text': 'a made-up fact'})
        self.refused(need, lambda: self.run_command('people_draft_facts', 'update', {'reviewed_by': 'person'}, fact))
        self.typed_yes(draft)
        self.refused(need, lambda: self.run_command('people_draft_facts', 'update', {'reviewed_by': 'person'}, fact))  # A typed approval row does not count.


class RulingsOfTheEvening(Database):
    """what-a-draft-keeps (ruled 10.06, evening). The names and types are the Architect's reading: batch 4, answers 1.1, 1.2, 1.5."""

    def test_the_draft_keeps_the_ask_in_the_askers_words_and_who_asked(self):
        draft = self.draft(requested_by='reviewer', request='a made-up ask, under five lines')
        self.assertEqual(tuple(self.one('SELECT requested_by,request,version FROM people_drafts WHERE id=?', (draft,))), ('reviewer', 'a made-up ask, under five lines', 1))
        self.run_command('people_drafts', 'update', {'request': 'a changed made-up ask'}, draft)
        self.assertEqual(tuple(self.one('SELECT request,version FROM people_drafts WHERE id=?', (draft,))), ('a changed made-up ask', 1))  # The ask is not the text.
        self.assertEqual(self.one("SELECT count(*) FROM work_changes WHERE subject_type='draft' AND subject_id=? AND field='request'", (draft,)), 1)
        self.assertIsNone(self.one('SELECT request FROM people_drafts WHERE id=?', (self.draft(),)))  # It may be empty.

    def test_a_send_that_is_not_proven_takes_one_of_three_marks(self):
        conversation = self.conversation()
        draft = self.draft(conversation=conversation)
        self.refused('CHECK', lambda: self.run_command('people_drafts', 'update', {'send_result': 'failed'}, draft))  # No send is tried on a draft.
        self.refused('CHECK', lambda: self.draft(send_result='failed'))
        self.approve(draft)
        for mark in ('not-delivered', 'failed', 'could-not-check'):
            self.run_command('people_drafts', 'update', {'send_result': mark}, draft)
            self.assertEqual(tuple(self.one('SELECT status,send_result,version FROM people_drafts WHERE id=?', (draft,))), ('approved', mark, 1))
        for bad in ('delivered', 'sent', 'not delivered'):
            self.refused('CHECK', lambda: self.run_command('people_drafts', 'update', {'send_result': bad}, draft))
        self.assertEqual(self.one('SELECT count(*) FROM people_conversations_in_hand WHERE draft=?', (draft,)), 1)  # Not proven: it stays in hand.
        self.assertEqual(self.one("SELECT count(*) FROM work_changes WHERE subject_type='draft' AND subject_id=? AND field='send_result'", (draft,)), 3)

    def test_a_draft_with_a_send_mark_is_not_sent(self):
        conversation = self.conversation()
        draft = self.draft(conversation=conversation)
        self.approve(draft)
        self.run_command('people_drafts', 'update', {'send_result': 'could-not-check'}, draft)
        message = self.message(conversation, 'made-up words')
        self.refused('CHECK', lambda: self.run_command('people_drafts', 'update', {'status': 'sent', 'sent_message': message}, draft))
        self.assertEqual(self.status(draft), 'approved')
        self.run_command('people_drafts', 'update', {'status': 'sent', 'sent_message': message, 'send_result': None}, draft)  # The send arrived: the mark is empty.
        self.assertEqual(tuple(self.one('SELECT status,send_result FROM people_drafts WHERE id=?', (draft,))), ('sent', None))
        self.refused('CHECK', lambda: self.raw("UPDATE people_drafts SET send_result='failed' WHERE id=?", (draft,)))  # Also for a load.

    def test_his_no_after_a_send_that_failed_keeps_the_mark(self):
        draft = self.draft()
        self.approve(draft)
        self.run_command('people_drafts', 'update', {'send_result': 'failed'}, draft)
        self.run_command('people_drafts', 'update', {'status': 'skipped'}, draft)
        self.assertEqual(tuple(self.one('SELECT status,send_result FROM people_drafts WHERE id=?', (draft,))), ('skipped', 'failed'))

    def test_a_fact_keeps_where_it_came_from_when_no_record_holds_it(self):
        draft = self.draft()
        fact = self.fact(draft, source_ref='made-up/path/of-a-file.md')
        self.assertEqual(tuple(self.one('SELECT source_ref,source_type,source_id FROM people_draft_facts WHERE id=?', (fact,))), ('made-up/path/of-a-file.md', None, None))
        self.run_command('people_draft_facts', 'update', {'reviewed_by': 'reviewer'}, fact, dict(AGENT, actor='reviewer'))
        self.run_command('people_draft_facts', 'update', {'source_ref': 'made-up/other-path.md'}, fact)  # A change of the source loses the review.
        self.assertIsNone(self.one('SELECT reviewed_by FROM people_draft_facts WHERE id=?', (fact,)))
        # A line with a path and no record is still marked: he decides.
        seq = self.yes(draft)
        self.refused('a fact with no record waits for his decision', lambda: self.run_command('people_drafts', 'update', {'approval': seq, 'status': 'approved'}, draft))
        self.run_command('people_draft_facts', 'update', {'reviewed_by': 'person'}, fact, dict(AGENT, actor='chief-of-staff'))
        self.run_command('people_drafts', 'update', {'approval': seq, 'status': 'approved'}, draft)
        self.refused('a fact line changes only while its draft is a draft', lambda: self.run_command('people_draft_facts', 'update', {'source_ref': 'made-up/late-path.md'}, fact))


class SecondReadOfTheSendGate(Database):
    """The second read of b584e04 (F/T9-read/legacy-judge/result.md). Each test is one of its planted cases."""

    YES = 'approved and sent need his approval row for this exact version and hash'
    FROZEN = 'a fact line changes only while its draft is a draft and before his yes'
    PROOF = 'sent needs the read-back: an outbound message of this conversation with this exact text and its platform id'

    def link(self, draft, seq):
        self.run_command('people_drafts', 'update', {'approval': seq, 'status': 'approved'}, draft)

    # Fix 1. His yes covers the facts he saw.
    def test_fact_added_after_yes_before_status(self):
        draft = self.draft()
        self.fact(draft, source_type='task', source_id=self.record(), reviewed_by='reviewer')
        seq = self.yes(draft)
        self.refused(self.FROZEN, lambda: self.fact(draft, source_type='task', source_id=self.record(), reviewed_by='reviewer'))
        self.link(draft, seq)
        self.assertEqual((self.status(draft), self.one('SELECT count(*) FROM people_draft_facts WHERE draft=?', (draft,))), ('approved', 1))

    def test_fact_changed_after_yes_before_status(self):
        draft = self.draft()
        fact = self.fact(draft, source_type='task', source_id=self.record(), reviewed_by='reviewer')
        seq = self.yes(draft)
        for change in ({'text': 'a changed made-up fact'}, {'reviewed_by': 'adviser'}, {'source_ref': 'made-up/path.md'}, {'reviewed_by': None}):
            self.refused(self.FROZEN, lambda: self.run_command('people_draft_facts', 'update', change, fact))
        self.refused(self.FROZEN, lambda: self.run_command('people_draft_facts', 'update', {'text': 'a changed made-up fact', 'reviewed_by': 'person'}, fact))
        self.link(draft, seq)
        self.assertEqual(tuple(self.one('SELECT text,reviewed_by FROM people_draft_facts WHERE id=?', (fact,))), ('a made-up fact', 'reviewer'))

    def test_a_new_version_of_the_text_opens_the_facts_again(self):
        draft = self.draft()
        fact = self.fact(draft, source_type='task', source_id=self.record())
        self.yes(draft)
        later = self.later_version(draft, 'newer made-up words')
        new_fact = self.fact(later, source_type='task', source_id=self.record())
        self.run_command('people_draft_facts', 'update', {'text': 'a changed made-up fact'}, new_fact)
        self.assertEqual(self.one('SELECT text FROM people_draft_facts WHERE id=?', (new_fact,)), 'a changed made-up fact')
        self.assertEqual(self.one('SELECT text FROM people_draft_facts WHERE id=?', (fact,)), 'a made-up fact')

    # Fix 2. The proof of a send.
    def approved(self):
        conversation = self.conversation()
        draft = self.draft(conversation=conversation)
        self.approve(draft)
        return conversation, draft

    def sent(self):
        conversation, draft = self.approved()
        message = self.message(conversation, 'made-up words')
        self.run_command('people_drafts', 'update', {'status': 'sent', 'sent_message': message}, draft)
        return conversation, draft, message

    def other_message(self, conversation, **change):
        self.serial += 1
        data = {'conversation': conversation, 'channel': 'email', 'account': 'made-up', 'source_system': 'gmail', 'source_message_id': 'message-' + str(self.serial),
                'sender_address': 'made-up@example.test', 'direction': 'outbound', 'text': 'made-up words'}
        data.update(change)
        return self.run_command('people_messages', 'insert', data, context=FEEDER)

    def test_send_inbound(self):
        conversation, draft = self.approved()
        for direction in ('inbound', 'other', 'unknown', None):
            self.refused(self.PROOF, lambda: self.run_command('people_drafts', 'update', {'status': 'sent', 'sent_message': self.other_message(conversation, direction=direction)}, draft))
        self.assertEqual(self.status(draft), 'approved')

    def test_send_wrong_conversation(self):
        conversation, draft = self.approved()
        self.refused(self.PROOF, lambda: self.run_command('people_drafts', 'update', {'status': 'sent', 'sent_message': self.other_message(self.conversation())}, draft))
        self.assertEqual(self.status(draft), 'approved')

    def test_sent_with_empty_platform_id(self):
        conversation, draft = self.approved()
        for empty in ('', '  '):
            self.refused(self.PROOF, lambda: self.run_command('people_drafts', 'update', {'status': 'sent', 'sent_message': self.other_message(conversation, source_message_id=empty)}, draft))
        self.assertEqual(self.status(draft), 'approved')

    def test_sent_readback_removed(self):
        conversation, draft, message = self.sent()
        self.refused(self.PROOF, lambda: self.run_command('people_drafts', 'update', {'sent_message': None}, draft))
        self.refused(self.PROOF, lambda: self.run_command('people_drafts', 'update', {'sent_message': self.other_message(conversation, direction='inbound')}, draft))
        self.assertEqual(tuple(self.one('SELECT status,sent_message FROM people_drafts WHERE id=?', (draft,))), ('sent', message))

    def test_sent_message_text_changed(self):
        conversation, draft, message = self.sent()
        need = 'a message that proves a send does not change'
        for change in ({'text': 'changed made-up words'}, {'direction': 'inbound'}, {'conversation': self.conversation()}, {'source_message_id': ''}):
            self.refused(need, lambda: self.run_command('people_messages', 'update', change, message, FEEDER))
        other = self.other_message(conversation)
        self.run_command('people_messages', 'update', {'text': 'changed made-up words'}, other, FEEDER)  # A message that proves nothing may change.
        self.run_command('people_messages', 'update', {'sender_name': 'Made-up Name'}, message, FEEDER)  # Other fields of the proof may change.

    # Fix 3. The review of a fact.
    def test_fact_reviewer_or_source_blank(self):
        draft = self.draft()
        for blank in ('', '   '):
            self.refused('CHECK', lambda: self.fact(draft, reviewed_by=blank))
        fact = self.fact(draft)
        self.refused('CHECK', lambda: self.run_command('people_draft_facts', 'update', {'reviewed_by': ''}, fact))
        self.refused('CHECK', lambda: self.raw("UPDATE people_draft_facts SET reviewed_by='' WHERE id=?", (fact,)))  # Also for a load.

    def test_fact_reviewer_or_source_space_person(self):
        draft = self.draft()
        for spaced in ('person ', ' person', 'person '):
            with self.assertRaises((ValueError, sqlite3.Error)):
                self.fact(draft, reviewed_by=spaced)
        fact = self.fact(draft)
        self.refused('the reviewer person needs his approval row on the draft', lambda: self.run_command('people_draft_facts', 'update', {'reviewed_by': 'person '}, fact))
        seq = self.yes(draft)
        self.refused('CHECK', lambda: self.run_command('people_draft_facts', 'update', {'reviewed_by': 'person '}, fact))  # With his yes, the name is still exact.
        self.refused('a fact with no record waits for his decision', lambda: self.link(draft, seq))

    def test_fact_reviewer_or_source_file(self):
        draft = self.draft()
        self.refused('CHECK', lambda: self.fact(draft, source_type='file', source_id=999999, reviewed_by='reviewer'))
        self.fact(draft, source_ref='made-up/path/of-a-file.md')  # A file is named in source_ref; the line stays marked.

    def test_fact_reviewer_or_source_session(self):
        draft = self.draft()
        self.refused('CHECK', lambda: self.fact(draft, source_type='session', source_id=999999, reviewed_by='reviewer'))
        self.refused('polymorphic reference', lambda: self.fact(draft, source_type='task', source_id=999999))

    def test_another_reviewer_does_not_decide_a_fact_with_no_record(self):
        draft = self.draft()
        fact = self.fact(draft, reviewed_by='reviewer')
        seq = self.yes(draft)
        self.refused('a fact with no record waits for his decision', lambda: self.link(draft, seq))
        self.run_command('people_draft_facts', 'update', {'reviewed_by': 'person'}, fact, dict(AGENT, actor='chief-of-staff'))
        self.link(draft, seq)
        self.assertEqual(self.status(draft), 'approved')

    # Fix 4. His no after his yes.
    def no(self, draft):
        return self.run_command('base_approvals', 'rejected', {'subject_type': 'draft', 'subject_id': draft, 'version': 1, 'summary': 'made-up no', 'person_words': 'made-up no'},
                                context=dict(AGENT, actor='person', source='made-up chat'))

    def test_no_after_yes_without_skip(self):
        conversation, draft = self.approved()
        self.no(draft)
        need = self.YES + ', and no later no'
        self.refused(need, lambda: self.run_command('people_drafts', 'update', {'status': 'sent', 'sent_message': self.message(conversation, 'made-up words')}, draft))
        self.refused(need, lambda: self.run_command('people_drafts', 'update', {'send_result': 'failed'}, draft))  # Nothing goes on as approved.
        self.assertEqual(self.status(draft), 'approved')
        self.run_command('people_drafts', 'update', {'status': 'skipped'}, draft)  # The one move left.
        self.assertEqual(self.status(draft), 'skipped')

    def test_a_no_before_his_yes_does_not_stop_a_later_yes(self):
        draft = self.draft()
        self.no(draft)
        self.approve(draft)
        self.assertEqual(self.status(draft), 'approved')

    def test_a_no_between_his_yes_and_the_status_move_stops_the_move(self):
        draft = self.draft()
        seq = self.yes(draft)
        self.no(draft)
        self.refused(self.YES + ', and no later no', lambda: self.link(draft, seq))

    # Fix 5. A draft family with two versions passes the lint.
    def test_a_family_with_two_versions_passes_the_lint(self):
        from lint import lint
        first = self.draft(family='made-up-family')
        second = self.later_version(first)
        self.assertEqual(self.one("SELECT group_concat(subject_version) FROM work_changes WHERE subject_type='draft' AND subject_id=?", (second,)), '2')
        self.assertEqual(lint(self.path, BLUEPRINT), [])
        conversation = self.conversation()
        for version in (1, 2):  # A load writes a family as its source holds it.
            self.raw('INSERT INTO people_drafts (conversation,family_id,version,author,status,workspace,text,content_hash) VALUES (?,?,?,?,?,?,?,?)',
                     (conversation, 'made-up-loaded-family', version, 'agent', 'replaced' if version == 1 else 'draft', 'cedar-shop', 'made-up words', sha('made-up words')))
        self.assertEqual(lint(self.path, BLUEPRINT), [])
        self.run_command('people_drafts', 'update', {'text': 'made-up words, in place'}, second)  # A text change in place: the row becomes the next text of its family.
        self.assertEqual((self.one('SELECT version FROM people_drafts WHERE id=?', (second,)), lint(self.path, BLUEPRINT)), (3, []))

    # Fix 6. Two rules that only the command held.
    def test_false_hash_raw_then_approved(self):
        writer = dict(AGENT)  # An ordinary writer context, on a raw connection.
        draft = self.draft()
        need = 'content_hash must be the sha256 of text'
        self.refused(need, lambda: self.raw('UPDATE people_drafts SET content_hash=?,version=version+1 WHERE id=?', (sha('other made-up words'), draft), writer))
        self.refused(need, lambda: self.raw('UPDATE people_drafts SET text=?,version=version+1 WHERE id=?', ('other made-up words', draft), writer))
        self.refused(need, lambda: self.raw('INSERT INTO people_drafts (conversation,family_id,version,author,status,workspace,text,content_hash) VALUES (?,?,1,?,?,?,?,?)',
                                            (self.conversation(), 'made-up-raw', 'agent', 'draft', 'cedar-shop', 'made-up words', 'not-a-hash'), writer))
        self.raw('UPDATE people_drafts SET text=?,content_hash=?,version=version+1 WHERE id=?', ('other made-up words', sha('other made-up words'), draft), writer)
        self.assertEqual(self.one('SELECT content_hash FROM people_drafts WHERE id=?', (draft,)), sha('other made-up words'))

    def test_raw_worker_authorization(self):
        draft = self.draft()
        version, digest = self.one('SELECT version,content_hash FROM people_drafts WHERE id=?', (draft,))
        row = "INSERT INTO base_approvals (seq,workspace,subject_type,subject_id,action,actor,session,source,occurred_at,recorded_at,version,approved_sha256,authorization_valid,envelope_ref,go_word,person_words) VALUES ((SELECT value+1 FROM _foxrun_sequence),'cedar-shop','draft',?,'approved',?,'made-up','made-up chat','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z',?,?,1,'made-up-envelope',1,'made-up yes')"
        for actor in ('worker', 'comms-lead', 'person '[:-1] + 'x', ''):
            with self.assertRaises(sqlite3.Error):
                self.raw(row, (draft, actor, version, digest), dict(AGENT))
        self.refused('Authorization requires Person', lambda: self.raw(row, (draft, 'worker', version, digest), dict(AGENT)))
        self.refused('Authorization requires Person', lambda: self.raw(row, (draft, 'worker', version, digest)))  # Also for a load.
        self.raw(row, (draft, 'person', version, digest), dict(AGENT))
        self.assertEqual(self.one("SELECT count(*) FROM base_approvals WHERE subject_type='draft' AND subject_id=? AND authorization_valid=1", (draft,)), 1)


class ReadOfRound4(Database):
    """The read of 1d390ab (F/T9-read/legacy-judge/out-5.txt). His yes covers the exact text and the exact facts of its version."""

    WRITER = dict(AGENT)  # An ordinary writer context on a raw connection, as the reader used.
    YES = 'approved and sent need his approval row for this exact version and hash'
    FROZEN = 'a fact line changes only while its draft is a draft and before his yes'

    def seen(self):
        """A draft with one marked fact line, his yes, and his decision on the line."""
        draft = self.draft()
        fact = self.fact(draft, source_ref='made-up original')
        seq = self.yes(draft)
        self.raw("UPDATE people_draft_facts SET reviewed_by='person' WHERE id=?", (fact,), self.WRITER)
        return draft, fact, seq

    def approve_with(self, draft, seq):
        self.raw("UPDATE people_drafts SET status='approved',approval=? WHERE id=?", (seq, draft), self.WRITER)

    def test_fact_freeze_escape_workspace(self):
        draft, fact, seq = self.seen()
        self.refused('his yes freezes this version', lambda: self.run_command('people_drafts', 'update', {'workspace': 'system-workspace'}, draft))
        self.refused(self.FROZEN, lambda: self.raw("UPDATE people_draft_facts SET text='an unseen made-up fact',reviewed_by='peer' WHERE id=?", (fact,), self.WRITER))
        self.approve_with(draft, seq)
        self.assertEqual(self.status(draft), 'approved')

    def test_fact_freeze_escape_text(self):
        draft, fact, seq = self.seen()
        moved = 'UPDATE people_drafts SET text=?,content_hash=?,version=version+1 WHERE id=?'
        self.refused('his yes freezes this version', lambda: self.raw(moved, ('temporary made-up words', sha('temporary made-up words'), draft), self.WRITER))
        self.refused(self.FROZEN, lambda: self.raw("UPDATE people_draft_facts SET text='an unseen made-up fact',reviewed_by='peer' WHERE id=?", (fact,), self.WRITER))
        self.approve_with(draft, seq)
        self.assertEqual(self.status(draft), 'approved')

    def test_a_change_newer_than_his_yes_makes_the_yes_fail_whatever_is_changed_back(self):
        """The same two states, planted by a load, which no freeze holds: the gate at approved reads the change rows."""
        for plant in ("UPDATE people_draft_facts SET text='an unseen made-up fact' WHERE draft=?", "UPDATE people_draft_facts SET text='an unseen made-up fact' WHERE draft=?|UPDATE people_draft_facts SET text='a made-up fact' WHERE draft=?",
                      "UPDATE people_drafts SET text='temporary made-up words' WHERE id=?|UPDATE people_drafts SET text='made-up words' WHERE id=?",
                      "INSERT INTO people_draft_facts (draft,text,reviewed_by) VALUES (?,'a late made-up fact','person')"):
            draft, fact, seq = self.seen()
            for statement in plant.split('|'):
                self.corrupt(statement, (draft,))  # Deliberately corrupt made-up rows.
            self.corrupt("UPDATE people_draft_facts SET reviewed_by='person' WHERE draft=?", (draft,))
            self.refused(self.YES, lambda: self.approve_with(draft, seq))
            self.assertEqual(self.status(draft), 'draft')
        draft, fact, seq = self.seen()  # The control: his decision alone is newer than his yes, and the yes holds.
        self.approve_with(draft, seq)
        self.assertEqual(self.status(draft), 'approved')

    def sent(self):
        conversation = self.conversation()
        draft = self.draft(conversation=conversation)
        self.approve(draft)
        message = self.message(conversation, 'made-up words')
        self.run_command('people_drafts', 'update', {'status': 'sent', 'sent_message': message}, draft)
        return draft, message

    def test_raw_proof_source_message_id(self):
        draft, message = self.sent()
        need = 'a message that proves a send does not change'
        feeder = dict(FEEDER)
        self.refused(need, lambda: self.raw("UPDATE people_messages SET source_message_id='another-made-up-id' WHERE id=?", (message,), feeder))
        self.refused(need, lambda: self.run_command('people_messages', 'update', {'source_message_id': 'another-made-up-id'}, message, FEEDER))
        self.assertEqual(self.one('SELECT count(*) FROM people_messages WHERE id=? AND source_message_id LIKE ?', (message, 'message-%')), 1)

    def test_the_lint_reports_a_yes_older_than_its_text_or_facts(self):
        from lint import lint
        finding = 'people_drafts has a draft approved or sent whose text or facts changed after his yes'
        draft, fact, seq = self.seen()
        self.approve_with(draft, seq)
        self.assertEqual(lint(self.path, BLUEPRINT), [])  # His decision after his yes is no finding.
        self.corrupt("UPDATE people_draft_facts SET text='an unseen made-up fact' WHERE id=?", (fact,))  # A load can still write it.
        self.assertIn(finding, lint(self.path, BLUEPRINT))
        self.corrupt("UPDATE people_draft_facts SET text='a made-up fact',reviewed_by='person' WHERE id=?", (fact,))  # Changed back: still reported.
        self.assertIn(finding, lint(self.path, BLUEPRINT))
        other, _, seq = self.seen()
        self.approve_with(other, seq)
        self.corrupt("UPDATE people_drafts SET text='temporary made-up words' WHERE id=?", (other,))
        self.corrupt("UPDATE people_drafts SET text='made-up words' WHERE id=?", (other,))
        self.assertIn(finding, lint(self.path, BLUEPRINT))

    def test_the_lint_reports_a_proof_of_send_whose_platform_id_changed(self):
        from lint import lint
        draft, message = self.sent()
        self.assertEqual(lint(self.path, BLUEPRINT), [])
        self.raw("DROP TRIGGER people_messages_state_proof_of_send_stays_update")
        self.raw("UPDATE people_messages SET source_message_id='another-made-up-id' WHERE id=?", (message,))  # Deliberately corrupt made-up proof.
        self.assertEqual(lint(self.path, BLUEPRINT), ['people_messages has a proof of send whose platform id changed'])


class ReadOfRound6(Database):
    """The read of 45e21ea. Ordinary conflict writes and approval timing; made-up rows only."""

    WRITER = dict(AGENT)
    YES = 'approved and sent need his approval row for this exact version and hash'

    def seen(self):
        draft = self.draft()
        fact = self.fact(draft, source_ref='made-up original')
        seq = self.yes(draft)
        self.raw("UPDATE people_draft_facts SET reviewed_by='person' WHERE id=?", (fact,), self.WRITER)
        return draft, fact, seq

    def approve_with(self, draft, seq):
        self.raw("UPDATE people_drafts SET status='approved',approval=? WHERE id=?", (seq, draft), self.WRITER)

    def test_fact_deleted_readded_replace_other(self):
        draft, fact, seq = self.seen()
        other = self.draft()
        self.refused('the draft of a fact line never changes', lambda: self.raw(
            "INSERT OR REPLACE INTO people_draft_facts(id,draft,text) VALUES (?,?,'replacement made-up fact')",
            (fact, other), self.WRITER))
        self.assertEqual(self.one('SELECT draft FROM people_draft_facts WHERE id=?', (fact,)), draft)
        self.approve_with(draft, seq)
        conversation = self.one('SELECT conversation FROM people_drafts WHERE id=?', (draft,))
        message = self.message(conversation, 'made-up words')
        self.raw("UPDATE people_drafts SET status='sent',sent_message=? WHERE id=?", (message, draft), self.WRITER)
        self.assertEqual(self.status(draft), 'sent')

    def test_fact_conflict_forms_keep_the_original_draft(self):
        statements = [
            "REPLACE INTO people_draft_facts(id,draft,text) VALUES (?,?,'replacement')",
            *["INSERT OR " + form + " INTO people_draft_facts(id,draft,text) VALUES (?,?,'replacement')"
              for form in ('REPLACE', 'ABORT', 'FAIL', 'IGNORE', 'ROLLBACK')],
            "INSERT INTO people_draft_facts(id,draft,text) VALUES (?,?,'replacement') ON CONFLICT(id) DO UPDATE SET draft=excluded.draft,text=excluded.text",
            "INSERT INTO people_draft_facts(id,draft,text) VALUES (?,?,'replacement') ON CONFLICT DO NOTHING",
            "UPDATE OR REPLACE people_draft_facts SET draft=? WHERE id=?",
        ]
        for statement in statements:
            for context in (AGENT, FEEDER, dict(AGENT, writer='cron', source='made-up cron')):
                with self.subTest(statement=statement, writer=context['writer']):
                    draft, fact, seq = self.seen()
                    other = self.draft()
                    args = (other, fact) if statement.startswith('UPDATE') else (fact, other)
                    self.refused('the draft of a fact line never changes', lambda: self.raw(statement, args, context))
                    self.assertEqual(self.one('SELECT draft FROM people_draft_facts WHERE id=?', (fact,)), draft)
                    self.approve_with(draft, seq)

    def test_upsert_before_his_yes_can_update_the_same_fact(self):
        draft = self.draft()
        fact = self.fact(draft)
        self.raw("INSERT INTO people_draft_facts(id,draft,text) VALUES (?,?,'changed made-up fact') ON CONFLICT(id) DO UPDATE SET text=excluded.text",
                 (fact, draft), self.WRITER)
        self.assertEqual(self.one('SELECT text FROM people_draft_facts WHERE id=?', (fact,)), 'changed made-up fact')

    def test_lint_reports_fact_deleted_readded_replace_other(self):
        from lint import lint
        draft, fact, seq = self.seen()
        self.approve_with(draft, seq)
        self.assertEqual(lint(self.path, BLUEPRINT), [])
        # Plant the former hole through the unchanged import exception. Its creation events remain.
        self.corrupt("INSERT OR REPLACE INTO people_draft_facts(id,draft,text) VALUES (?,?,'replacement made-up fact')", (fact, self.draft()))
        self.assertIn('people_draft_facts has a fact line created more than once', lint(self.path, BLUEPRINT))

    def raw_yes(self, draft, version, digest, context=AGENT):
        self.raw("INSERT INTO base_approvals(seq,workspace,subject_type,subject_id,version,approved_sha256,authorization_valid,envelope_ref,go_word,person_words,source,actor,session,action,occurred_at,recorded_at) "
                 "VALUES ((SELECT value+1 FROM _foxrun_sequence),'cedar-shop','draft',?,?,?,1,'made-up',1,'made-up yes','made-up chat','person','made-up','approved','2026-01-01','2026-01-01')",
                 (draft, version, digest), context)
        return self.one("SELECT max(seq) FROM base_approvals WHERE subject_type='draft' AND subject_id=?", (draft,))

    def test_two_approvals_future_text_same_write(self):
        draft = self.draft()
        self.yes(draft)
        self.refused('a draft approval needs its existing version and exact text hash',
                     lambda: self.raw_yes(draft, 2, sha('future made-up words')))
        self.assertEqual(self.one('SELECT count(*) FROM base_approvals WHERE subject_id=?', (draft,)), 1)
        self.assertEqual((self.status(draft), self.one('SELECT version FROM people_drafts WHERE id=?', (draft,))), ('draft', 1))

    def test_raw_approval_matches_existing_text_and_hash(self):
        draft = self.draft()
        for version, digest in ((2, sha('made-up words')), (1, sha('unseen made-up words'))):
            with self.subTest(version=version, digest=digest):
                self.refused('a draft approval needs its existing version and exact text hash', lambda: self.raw_yes(draft, version, digest))
        # A false stored hash from a load is not evidence of the exact text.
        self.raw('UPDATE people_drafts SET content_hash=? WHERE id=?', (sha('unseen made-up words'), draft))
        self.refused('a draft approval needs its existing version and exact text hash', lambda: self.raw_yes(draft, 1, sha('unseen made-up words')))

    def test_current_write_cannot_change_text_and_save_approved(self):
        draft = self.draft()
        self.yes(draft)
        # A load can still plant a future approval. The ordinary draft write must check NEW and OLD directly.
        self.corrupt("INSERT INTO base_approvals(seq,workspace,subject_type,subject_id,version,approved_sha256,authorization_valid,envelope_ref,go_word,person_words,source,actor,session,action,occurred_at,recorded_at) VALUES ((SELECT value+1 FROM _foxrun_sequence),'cedar-shop','draft',?,2,?,1,'made-up',1,'made-up yes','made-up chat','person','made-up','approved','2026-01-01','2026-01-01')", (draft, sha('future made-up words')))
        seq = self.one("SELECT max(seq) FROM base_approvals WHERE subject_type='draft' AND subject_id=?", (draft,))
        self.refused(self.YES, lambda: self.raw(
            "UPDATE people_drafts SET text=?,content_hash=?,version=2,approval=?,status='approved' WHERE id=?",
            ('future made-up words', sha('future made-up words'), seq, draft), self.WRITER))
        self.assertEqual(tuple(self.one('SELECT status,text,version FROM people_drafts WHERE id=?', (draft,))), ('draft', 'made-up words', 1))

    def test_lint_reports_a_future_approval_before_and_after_the_atomic_write(self):
        from lint import lint
        draft = self.draft()
        self.yes(draft)
        self.corrupt("INSERT INTO base_approvals(seq,workspace,subject_type,subject_id,version,approved_sha256,authorization_valid,envelope_ref,go_word,person_words,source,actor,session,action,occurred_at,recorded_at) VALUES ((SELECT value+1 FROM _foxrun_sequence),'cedar-shop','draft',?,2,?,1,'made-up',1,'made-up yes','made-up chat','person','made-up','approved','2026-01-01','2026-01-01')", (draft, sha('future made-up words')))
        seq = self.one("SELECT max(seq) FROM base_approvals WHERE subject_type='draft' AND subject_id=?", (draft,))
        finding = 'base_approvals has a draft approval for a version that was not current at his yes'
        self.assertIn(finding, lint(self.path, BLUEPRINT))
        self.corrupt("UPDATE people_drafts SET text=?,content_hash=?,version=2,approval=?,status='approved' WHERE id=?",
                 ('future made-up words', sha('future made-up words'), seq, draft))
        self.assertIn(finding, lint(self.path, BLUEPRINT))
        self.assertIn('people_drafts has a draft approved or sent whose text or facts changed after his yes', lint(self.path, BLUEPRINT))

    def test_two_approvals_for_existing_versions_work(self):
        from lint import lint
        draft = self.draft()
        old = self.yes(draft)
        later = self.later_version(draft, text='new made-up words')
        self.refused(self.YES, lambda: self.approve_with(later, old))
        fresh = self.yes(later)
        self.approve_with(later, fresh)
        conversation = self.one('SELECT conversation FROM people_drafts WHERE id=?', (later,))
        self.raw("UPDATE people_drafts SET status='sent',sent_message=? WHERE id=?", (self.message(conversation, 'new made-up words'), later), self.WRITER)
        self.assertEqual((self.status(later), lint(self.path, BLUEPRINT)), ('sent', []))


class Round8DraftVersions(Database):
    """Batch 24, 1.4: once his yes exists, edit through a new version row."""

    def replace(self, draft, form='INSERT OR REPLACE', new_id=None, text='changed made-up words'):
        row = dict(self.one('SELECT * FROM people_drafts WHERE id=?', (draft,)))
        row.update(id=new_id or draft, conversation=self.conversation(), text=text, content_hash=sha(text), status='draft', approval=None, sent_message=None)
        names = list(row)
        statement = form + ' INTO people_drafts (' + ','.join(names) + ') VALUES (' + ','.join('?' for _ in names) + ')'
        if form == 'UPSERT':
            statement = statement.replace('UPSERT', 'INSERT', 1) + ' ON CONFLICT(id) DO UPDATE SET ' + ','.join(n + '=excluded.' + n for n in names if n != 'id')
        self.raw(statement, tuple(row[n] for n in names), AGENT)

    def test_draft_replace_text_and_restore_old_yes(self):
        draft = self.draft()
        self.approve(draft)
        with self.assertRaises(sqlite3.Error):
            self.replace(draft)
        self.assertEqual(tuple(self.one('SELECT text,status,version FROM people_drafts WHERE id=?', (draft,))), ('made-up words', 'approved', 1))

    def test_no_facts_replace_resets_sent(self):
        draft = self.draft()
        self.approve(draft)
        conversation = self.one('SELECT conversation FROM people_drafts WHERE id=?', (draft,))
        self.run_command('people_drafts', 'update', {'status': 'sent', 'sent_message': self.message(conversation, 'made-up words')}, draft)
        with self.assertRaises(sqlite3.Error):
            self.replace(draft, text='made-up words')
        self.assertEqual(self.status(draft), 'sent')

    def test_approval_row_freezes_text_before_the_status_move(self):
        draft = self.draft()
        self.yes(draft)
        with self.assertRaises(sqlite3.Error):
            self.raw('UPDATE people_drafts SET text=?,content_hash=?,version=version+1 WHERE id=?', ('new made-up words', sha('new made-up words'), draft), AGENT)

    def test_conflicts_keep_the_row_and_version_that_his_yes_names(self):
        for form in ('REPLACE', 'INSERT OR REPLACE', 'UPSERT'):
            with self.subTest(form=form):
                draft = self.draft()
                self.yes(draft)
                with self.assertRaises(sqlite3.Error):
                    self.replace(draft, form)
                self.assertEqual(self.one('SELECT version FROM people_drafts WHERE id=?', (draft,)), 1)
        draft = self.draft()
        self.approve(draft)
        with self.assertRaises(sqlite3.Error):
            self.replace(draft, new_id=draft + 10000)
        with self.assertRaises(sqlite3.Error):
            self.raw('DELETE FROM people_drafts WHERE id=?', (draft,), AGENT)

    def test_a_new_version_needs_its_own_yes(self):
        draft = self.draft()
        self.approve(draft)
        old_yes = self.one('SELECT approval FROM people_drafts WHERE id=?', (draft,))
        later = self.later_version(draft)
        self.assertEqual(self.status(draft), 'replaced')
        with self.assertRaises((ValueError, sqlite3.Error)):
            self.run_command('people_drafts', 'update', {'approval': old_yes, 'status': 'approved'}, later)
        self.approve(later)
        self.assertEqual(self.status(later), 'approved')


class Round8EditedApproval(Database):
    """Batch 22, 2.1 and 2.2: a later edit waits for a new yes."""

    def edit(self, draft):
        return self.run_command('base_approvals', 'edited', {'subject_type': 'draft', 'subject_id': draft, 'version': self.one('SELECT version FROM people_drafts WHERE id=?', (draft,))}, context=dict(AGENT, actor='person'))

    def send(self, draft):
        conversation = self.one('SELECT conversation FROM people_drafts WHERE id=?', (draft,))
        text = self.one('SELECT text FROM people_drafts WHERE id=?', (draft,))
        self.run_command('people_drafts', 'update', {'status': 'sent', 'sent_message': self.message(conversation, text)}, draft)

    def test_a_later_edit_stops_the_send(self):
        draft = self.draft()
        self.approve(draft)
        self.edit(draft)
        with self.assertRaises((ValueError, sqlite3.Error)):
            self.send(draft)
        self.run_command('people_drafts', 'update', {'status': 'skipped'}, draft)
        self.assertEqual(self.status(draft), 'skipped')

    def test_edit_then_yes_and_a_new_edited_version_can_send(self):
        draft = self.draft()
        self.edit(draft)
        self.approve(draft)
        self.send(draft)
        self.assertEqual(self.status(draft), 'sent')
        old = self.draft()
        self.approve(old)
        self.edit(old)
        later = self.later_version(old)
        self.edit(later)
        self.approve(later)
        self.send(later)
        self.assertEqual((self.status(old), self.status(later)), ('replaced', 'sent'))

    def test_an_edit_after_sent_does_not_reopen_or_stop_the_sent_row(self):
        draft = self.draft()
        self.approve(draft)
        self.send(draft)
        self.edit(draft)
        self.raw("UPDATE people_drafts SET updated_at='2026-01-01T00:00:00Z' WHERE id=?", (draft,), AGENT)
        self.assertEqual(self.status(draft), 'sent')


class Round8ProofOfSend(Database):
    """Batch 22, 1.1 to 1.5: keep proof values, compare the live links."""

    def sent(self):
        draft = self.draft()
        self.approve(draft)
        conversation = self.one('SELECT conversation FROM people_drafts WHERE id=?', (draft,))
        message = self.message(conversation, 'made-up words')
        self.run_command('people_drafts', 'update', {'status': 'sent', 'sent_message': message}, draft)
        return draft, message

    def test_import_keeps_all_four_proof_fields(self):
        draft, message = self.sent()
        for field, value in (('text', 'different made-up words'), ('conversation', self.conversation()), ('direction', 'inbound'), ('source_message_id', 'different-made-up-id')):
            with self.subTest(field=field):
                with self.assertRaises(sqlite3.Error):
                    self.raw('UPDATE people_messages SET ' + field + '=? WHERE id=?', (value, message))
        self.raw("UPDATE people_messages SET sender_name='Made-up New Name' WHERE id=?", (message,))
        self.assertEqual(self.one('SELECT sender_name FROM people_messages WHERE id=?', (message,)), 'Made-up New Name')

    def test_lint_finds_a_changed_proof_without_a_change_row(self):
        from lint import lint
        for field, value in (('text', 'different made-up words'), ('conversation', self.conversation()), ('direction', 'inbound'), ('source_message_id', '')):
            with self.subTest(field=field):
                draft, message = self.sent()
                db = connect(self.path, IMPORT)
                for row in db.execute("SELECT name FROM sqlite_schema WHERE type='trigger' AND tbl_name='people_messages'").fetchall():
                    db.execute('DROP TRIGGER "' + row[0] + '"')
                db.execute('UPDATE people_messages SET ' + field + '=? WHERE id=?', (value, message))
                db.commit()
                db.close()
                self.assertIn('people_drafts has a sent draft whose read-back does not prove its exact send', lint(self.path, BLUEPRINT))

    def test_an_edit_is_a_new_message_and_keeps_the_old_proof(self):
        from lint import lint
        draft, message = self.sent()
        conversation = self.one('SELECT conversation FROM people_drafts WHERE id=?', (draft,))
        newer = self.message(conversation, 'edited made-up words')
        self.run_command('people_messages', 'update', {'replaces': message}, newer, FEEDER)
        self.assertEqual(self.one('SELECT sent_message FROM people_drafts WHERE id=?', (draft,)), message)
        self.assertEqual(lint(self.path, BLUEPRINT), [])


class Round8Contexts(Database):
    """Batch 24, 2.3 to 2.5; batch 21, 4. No context changes a value's meaning."""

    def test_lint_compares_a_protected_fact_with_its_newest_event(self):
        from lint import lint
        draft = self.draft()
        fact = self.fact(draft, source_ref='made-up first source')
        self.run_command('people_draft_facts', 'update', {'source_ref': 'made-up reviewed source'}, fact)
        self.yes(draft)
        db = connect(self.path, IMPORT)
        for row in db.execute("SELECT name FROM sqlite_schema WHERE type='trigger' AND tbl_name='people_draft_facts'").fetchall():
            db.execute('DROP TRIGGER "' + row[0] + '"')
        db.execute("UPDATE people_draft_facts SET source_ref='made-up silent source' WHERE id=?", (fact,))
        db.commit()
        db.close()
        self.assertIn('people_draft_facts.source_ref differs from newest event', lint(self.path, BLUEPRINT))

    def test_unique_update_replace_cannot_remove_another_approved_version(self):
        for context in (AGENT, IMPORT):
            with self.subTest(context=context['writer'], imported=context.get('import')):
                draft = self.draft()
                self.approve(draft)
                other = self.draft()
                family = self.one('SELECT family_id FROM people_drafts WHERE id=?', (draft,))
                with self.assertRaises(sqlite3.Error):
                    self.raw('UPDATE OR REPLACE people_drafts SET family_id=? WHERE id=?', (family, other), context)
                self.assertEqual(self.status(draft), 'approved')

    def test_dictionary_schema_connection_updates_definitions_with_installed_guards(self):
        from dictionary_v11 import connect as dictionary_connect
        db = dictionary_connect(self.path)
        try:
            db.execute("UPDATE base_modules SET job='Made-up schema definition' WHERE name='people'")
            db.commit()
        finally:
            db.close()
        self.assertEqual(self.one("SELECT job FROM base_modules WHERE name='people'"), 'Made-up schema definition')

    def test_schema_with_import_is_refused_when_record_rows_exist(self):
        self.draft()
        with self.assertRaises(ValueError):
            db = connect(self.path, dict(IMPORT, writer='schema'))
            db.close()

    def test_schema_writer_only_changes_definitions(self):
        draft = self.draft()
        schema = dict(AGENT, writer='schema')
        for statement, args in (("UPDATE people_drafts SET request='changed made-up request' WHERE id=?", (draft,)),
                                ("INSERT INTO work_tasks(workspace,number,title,status,reviewer,reviewed_by) VALUES ('cedar-shop','made-up-schema','Made-up Task','todo','lead','made-up')", ())):
            with self.subTest(statement=statement):
                with self.assertRaises(sqlite3.Error):
                    self.raw(statement, args, schema)
        self.raw("UPDATE base_modules SET job='Made-up definition' WHERE name='people'", context=schema)
        self.assertEqual(self.one("SELECT job FROM base_modules WHERE name='people'"), 'Made-up definition')

    def test_import_approved_and_sent_need_evidence_on_insert_and_update(self):
        for status in ('approved', 'sent'):
            with self.subTest(status=status):
                draft = self.draft()
                with self.assertRaises(sqlite3.Error):
                    self.raw('UPDATE people_drafts SET status=? WHERE id=?', (status, draft))
                with self.assertRaises(sqlite3.Error):
                    self.raw("INSERT INTO people_drafts(conversation,family_id,version,author,status,workspace,text,content_hash) VALUES (?, ?, 1, 'agent', ?, 'cedar-shop', 'made-up words', ?)", (self.conversation(), 'made-up-no-evidence-' + status, status, sha('made-up words')))

    def test_import_obeys_the_freeze_and_the_fact_parent(self):
        draft = self.draft()
        fact = self.fact(draft, source_ref='made-up source')
        self.yes(draft)
        for statement, args in (("UPDATE people_drafts SET text=?,content_hash=?,version=version+1 WHERE id=?", ('changed made-up words', sha('changed made-up words'), draft)),
                                ("UPDATE people_draft_facts SET text='changed made-up fact' WHERE id=?", (fact,)),
                                ("UPDATE people_draft_facts SET draft=? WHERE id=?", (self.draft(), fact))):
            with self.subTest(statement=statement):
                with self.assertRaises(sqlite3.Error):
                    self.raw(statement, args)

    def test_import_reviewer_person_needs_an_approval(self):
        draft = self.draft()
        fact = self.fact(draft)
        with self.assertRaises(sqlite3.Error):
            self.raw("UPDATE people_draft_facts SET reviewed_by='person' WHERE id=?", (fact,))
        with self.assertRaises(sqlite3.Error):
            self.raw("INSERT INTO people_draft_facts(draft,text,reviewed_by) VALUES (?,'made-up fact','person')", (draft,))

    def test_import_cannot_add_or_replace_a_fact_after_his_yes(self):
        for replace in (False, True):
            with self.subTest(replace=replace):
                draft = self.draft()
                fact = self.fact(draft)
                self.yes(draft)
                statement = "INSERT OR REPLACE INTO people_draft_facts(id,draft,text) VALUES (?,?,'changed made-up fact')" if replace else "INSERT INTO people_draft_facts(draft,text) VALUES (?,'new made-up fact')"
                with self.assertRaises(sqlite3.Error):
                    self.raw(statement, (fact, draft) if replace else (draft,))

    def test_old_yes_proves_history_but_cannot_authorize_a_new_send(self):
        draft = self.draft()
        yes = self.typed_yes(draft)
        self.raw("UPDATE people_drafts SET status='approved',approval=? WHERE id=?", (yes, draft))
        conversation = self.one('SELECT conversation FROM people_drafts WHERE id=?', (draft,))
        message = self.message(conversation, 'made-up words')
        with self.assertRaises((ValueError, sqlite3.Error)):
            self.run_command('people_drafts', 'update', {'status': 'sent', 'sent_message': message}, draft)
        self.raw("UPDATE people_drafts SET status='sent',sent_message=? WHERE id=?", (message, draft))
        self.assertEqual(self.status(draft), 'sent')

    def test_import_sent_still_needs_an_exact_read_back(self):
        draft = self.draft()
        self.approve(draft)
        with self.assertRaises(sqlite3.Error):
            self.raw("UPDATE people_drafts SET status='sent' WHERE id=?", (draft,))


class Round8ReleaseAndMarks(unittest.TestCase):
    """Batch 24, bug 4; batch 22, 4: marks and install rows state the truth."""

    def test_his_yes_fact_point_names_the_settled_ruling(self):
        decision = 'his-yes-covers-the-facts-shown-with-the-message'
        rules = json.loads((BLUEPRINT / 'implementation-rules.json').read_text())  # People rules join from Small Talk's blueprint
        names = ('holds_his_yes', 'holds_his_yes_new', 'frozen', 'frozen_new',
                 'draft_never_changes', 'draft_never_changes_on_conflict')
        for name in names:
            with self.subTest(guard=name):
                guard = next(g for g in rules['state_guards'] if g['name']==name)
                self.assertIn(decision, guard['rulings'])
                # Each complete guard also carries a reading outside the scope of this ruling.
                self.assertEqual(guard['mark'], "Architect's reading, not a Person ruling")
        target = next(json.loads(line) for line in (BLUEPRINT / 'target-v13.jsonl').read_text().splitlines()
                      if json.loads(line)['name']=='people_draft_facts')
        self.assertIn(decision, target['rulings'])
        freeze = next(c for c in target['changes'] if 'His yes covers the facts he saw' in c['change'])
        self.assertTrue(freeze['basis'].startswith('Settled by ' + decision))
        self.assertIn("Architect's reading, not a Person ruling", freeze['basis'])
        for change in target['changes']:
            if change is not freeze and 'Architect' in change['basis']:
                self.assertNotIn(decision, change['basis'])

    def sample(self):
        import importlib.util
        path = (Path(__file__).resolve().parent / '../distribution/sample_workspace.py')
        spec = importlib.util.spec_from_file_location('round8_sample', path)
        sample = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sample)
        fixture = json.loads(((Path(__file__).resolve().parent / '../distribution/sample/rows.json')).read_text())
        return sample, fixture

    def test_install_rows_name_blueprint_12(self):
        sample, fixture = self.sample()
        db = sample.build_database(HERE, fixture)
        try:
            self.assertEqual({r[0] for r in db.execute('SELECT version FROM base_installs')}, {'13'})
            self.assertTrue(all(r[0] for r in db.execute('SELECT blueprint_hash FROM base_installs')))
        finally:
            db.close()

    def test_sample_pages_read_the_module_version(self):
        sample, fixture = self.sample()
        db = sample.build_database(HERE, fixture)
        try:
            db.execute("UPDATE base_modules SET version='made-up-version' WHERE name='base'")
            pages = sample.pages(db, fixture)
            self.assertIn(b'Blueprint vmade-up-version', pages['SCHEMA.md'])
            self.assertIn(b'blueprint vmade-up-version', pages['index.md'])
        finally:
            db.close()

    def test_release_label_and_module_versions_name_12(self):
        distribution = (Path(__file__).resolve().parent / '../distribution')
        import importlib.util
        spec = importlib.util.spec_from_file_location('round8_build_release', (Path(__file__).resolve().parent / '../distribution/build_release.py'))
        module = importlib.util.module_from_spec(spec)
        import sys
        sys.path.insert(0, str(distribution))
        spec.loader.exec_module(module)
        self.assertEqual(module.VERSION, '13-night.1')
        self.assertEqual(json.loads(((Path(__file__).resolve().parent / '../distribution/release/manifest.json')).read_text())['version'], '13-night.1')


if __name__ == '__main__':
    unittest.main(verbosity=2)
