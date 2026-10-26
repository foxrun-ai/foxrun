"""Parity fixtures for every blueprint view. Expected values come from rows and rulings."""

from __future__ import annotations

import sys as _fox_sys
from pathlib import Path as _FoxPath
_fox_root = next(p for p in _FoxPath(__file__).resolve().parents if (p / 'base/core.py').is_file())
_fox_sys.path[:0] = [str(_fox_root / p) for p in ('base', 'base/tests', 'work', 'events', 'decisions', 'memory', 'people', 'design', 'capture')]
_fox_sys.path.insert(0, str(_fox_root))
from base.tests.support import setup as _fox_test_setup
_fox_test_setup()
import json
from datetime import date,timedelta
from core import build,connect,load,Q
from fixtures import Fixtures
from guard_tests import SCHEMA

def verify(path,blueprint):
    build(path,blueprint);targets,columns=load(blueprint);db=connect(path,SCHEMA);f=Fixtures(db,targets,columns);tested=set()
    today=date.fromisoformat(db.execute("SELECT date('now')").fetchone()[0]);day=lambda n:(today+timedelta(days=n)).isoformat()
    def row(view,where='',args=()):return db.execute('SELECT * FROM '+Q(view)+(' WHERE '+where if where else ''),args).fetchone()
    def seen(name):tested.add(name)
    def yes(draft):
        version,digest,workspace=db.execute('SELECT version,content_hash,workspace FROM people_drafts WHERE id=?',(draft,)).fetchone()
        return f.row('base_approvals',workspace=workspace,subject_type='draft',subject_id=draft,action='approved',version=version,approved_sha256=digest,authorization_valid=1,envelope_ref='fixture',go_word=1,person_words='fixture yes',source='fixture chat',actor='person')
    # Open task metrics include recurring parents, exclude children and closed states.
    parent=f.row('work_tasks',workspace='system-workspace',status='todo',planned_on=day(2),important=1,urgent=1,idempotency_key='recurring-fixture')
    child=f.row('work_tasks',workspace='system-workspace',status='todo',parent=parent,sort_order=2)
    first=f.row('work_tasks',workspace='system-workspace',status='todo',parent=parent,sort_order=1)
    finished=f.row('work_tasks',workspace='system-workspace',status='done')
    for view in ('work_open_tasks','work_this_week','work_eisenhower'):
        ids={r['id'] if 'id' in r.keys() else r['task'] for r in db.execute('SELECT * FROM '+view)}
        assert parent in ids and child not in ids and finished not in ids,view;seen(view)
    assert row('work_eisenhower','task=?',(parent,))['quadrant']==1
    for important,urgent,quadrant in [(1,0,2),(0,1,3),(0,0,4)]:
        key=f.row('work_tasks',important=important,urgent=urgent,status='todo');assert row('work_eisenhower','task=?',(key,))['quadrant']==quadrant
    assert row('work_next_step','parent=?',(parent,))['id']==first;seen('work_next_step')
    review=f.row('work_tasks',workspace='system-workspace',status='in-review')
    f.row('work_attachments',workspace='system-workspace',subject_type='task',subject_id=review,path='old-evidence')
    f.row('work_attachments',workspace='system-workspace',subject_type='task',subject_id=review,path='new-evidence')
    assert row('work_in_review','id=?',(review,))['evidence_path']=='new-evidence';seen('work_in_review')
    program=f.row('work_programs',workspace='system-workspace');project=f.row('work_projects',workspace='system-workspace',program=program,status='in-progress')
    for status in ('done','todo','backlog','canceled'):f.row('work_tasks',workspace='system-workspace',project=project,status=status)
    plan=row('work_program_plan','stream_id=?',(project,));assert (plan['live_tasks'],plan['done_tasks'],plan['backlog_tasks'],plan['percent_done'])==(3,1,1,50.0);seen('work_program_plan')
    standing=f.row('work_tasks',workspace='system-workspace',status='todo',idempotency_key='session-holding-task')
    oldrun=f.row('work_runs',workspace='system-workspace',subject_type='task',subject_id=standing,started_at='2026-01-01T00:00:00Z')
    newrun=f.row('work_runs',workspace='system-workspace',subject_type='task',subject_id=standing,started_at='2026-01-02T00:00:00Z')
    assert row('work_latest_run_per_task','task=?',(standing,))['run']==newrun;seen('work_latest_run_per_task')
    assert {r['run'] for r in db.execute('SELECT * FROM work_runs_to_place WHERE standing_task=?',(standing,))}=={oldrun,newrun};seen('work_runs_to_place')
    promise=f.row('base_values',set='task-kind',value='promise',active=1)
    f.row('work_links',workspace='system-workspace',subject_type='task',subject_id=parent,relation='tagged',target_type='value',target_id=promise)
    f.row('work_links',workspace='system-workspace',subject_type='task',subject_id=parent,relation='source',path='fixture-message')
    assert row('work_open_promises','task=?',(parent,))['source']=='fixture-message';seen('work_open_promises')
    f.row('work_links',workspace='system-workspace',subject_type='task',subject_id=review,relation='produced',system='github',path='fixture-PR-1',target_type='file')
    f.row('work_links',workspace='system-workspace',subject_type='task',subject_id=review,relation='produced',system='github',path='fixture-PR-2',target_type='file')
    f.row('work_changes',workspace='system-workspace',subject_type='task',subject_id=review,subject_version='1',action='verified',actor='other')
    assert row('work_ready_to_merge','task=?',(review,)) is None
    f.row('work_changes',workspace='system-workspace',subject_type='task',subject_id=review,subject_version='1',action='verified',actor='fixture')
    f.row('work_changes',workspace='system-workspace',subject_type='task',subject_id=review,subject_version='1',action='merged',refs=json.dumps(['fixture-PR-1']))
    assert {r['pull_request'] for r in db.execute('SELECT * FROM work_ready_to_merge WHERE task=?',(review,))}=={'fixture-PR-2'};seen('work_ready_to_merge')
    mine=f.row('work_tasks',workspace='system-workspace',owner='person',status='todo')
    draft=f.row('people_drafts',workspace='system-workspace',status='draft',version=1)
    assert row('work_needs_me',"subject_type='task' AND subject_id=?",(mine,))
    assert row('work_needs_me',"subject_type='draft' AND subject_id=?",(draft,))
    yes(draft)
    assert row('work_needs_me',"subject_type='draft' AND subject_id=?",(draft,)) is None;seen('work_needs_me')
    # Dictionary joins have one row per actual table field, with module ownership.
    expected=db.execute("SELECT count(*) FROM base_fields f JOIN base_object_types o ON o.id=f.object_type JOIN base_modules m ON m.id=o.module").fetchone()[0]
    assert db.execute('SELECT count(*) FROM base_dictionary WHERE field IS NOT NULL').fetchone()[0]==expected;seen('base_dictionary')
    opened=f.row('base_decisions',status='open');ruled=f.row('base_decisions',status='ruled')
    assert row('base_open_decisions','id=?',(opened,)) and not row('base_open_decisions','id=?',(ruled,));seen('base_open_decisions')
    seqs=[r['seq'] for r in db.execute('SELECT * FROM base_timeline')];assert seqs==list(range(1,db.execute('SELECT value FROM _foxrun_sequence').fetchone()[0]+1));seen('base_timeline')
    # Commerce source-view parity and recommendation arithmetic.
    account=f.row('commerce_accounts',workspace='cedar-shop',source_system='amazon')
    low=f.row('commerce_inventory_levels',workspace='cedar-shop',account=account,available=0,sku='low-fixture');high=f.row('commerce_inventory_levels',workspace='cedar-shop',account=account,available=1,sku='high-fixture')
    assert row('commerce_low_stock',"sku='low-fixture'")['amazon_account_id']==account and row('commerce_low_stock',"sku='high-fixture'") is None;seen('commerce_low_stock')
    support=f.row('commerce_support_cases',status='open',platform='amazon');closed=f.row('commerce_support_cases',status='closed')
    assert row('commerce_open_support_cases','id=?',(support,))['source']=='amazon' and row('commerce_open_support_cases','id=?',(closed,)) is None;seen('commerce_open_support_cases')
    due=f.row('commerce_restocks',status='planned',due_on=day(-2));future=f.row('commerce_restocks',status='planned',due_on=day(2));received=f.row('commerce_restocks',status='received',due_on=day(-2))
    assert row('commerce_restock_due','id=?',(due,))['days_overdue']==2 and not row('commerce_restock_due','id=?',(future,)) and not row('commerce_restock_due','id=?',(received,));seen('commerce_restock_due')
    sku=f.row('commerce_skus');order=f.row('commerce_orders');shipment=f.row('commerce_shipments',order=order)
    f.row('commerce_line_items',order=order,sku_ref=sku,quantity=6)
    restock=f.row('commerce_restocks',sku_ref=sku,shipment=shipment,approved_quantity=10)
    f.row('commerce_restock_recommendations',restock=restock,source='amazon',recommended_quantity=14,as_of='2026-01-01')
    f.row('commerce_restock_recommendations',restock=restock,source='amazon',recommended_quantity=12,as_of='2026-01-02')
    f.row('commerce_restock_recommendations',restock=restock,source='helium-10',recommended_quantity=8,as_of='2026-01-02')
    plan=row('commerce_restock_plan','restock=?',(restock,));assert tuple(plan[k] for k in ('amazon_recommended','helium_10_recommended','sent','short','delta','shipbob_percent'))==(12,8,6,4,4,60.0);seen('commerce_restock_plan')
    age=db.execute("SELECT a.age_seconds, CAST(strftime('%s','now') AS INTEGER)-CAST(strftime('%s',a.newest_fetched_at) AS INTEGER) expected FROM commerce_mirror_age a WHERE a.\"table\"='commerce_line_items'").fetchone();assert age[0]==age[1];seen('commerce_mirror_age')
    # Amazon distinct ASINs count once across FBA and FBM; active text is insufficient.
    scope=f.row('amazon_listing_changes',workspace='cedar-shop',account=account,sku_ref=sku,marketplace='US',status='draft')
    f.row('work_measures',workspace='cedar-shop',source='amazon_scope_buyable',target=36)
    fba=f.row('amazon_listings',workspace='cedar-shop',account=account,sku_ref=sku,asin='fixture-ASIN',parent_asin='fixture-parent',marketplace='US',fulfillment='FBA',is_buyable=1,is_own_offer=1,is_suppressed=0)
    fbm=f.row('amazon_listings',workspace='cedar-shop',account=account,sku_ref=sku,asin='fixture-ASIN',parent_asin='fixture-parent',marketplace='US',fulfillment='FBM',is_buyable=1,is_own_offer=1,is_suppressed=0)
    assert row('amazon_families',"parent_asin='fixture-parent'")['child_count']==1;seen('amazon_families')
    assert row('amazon_scope_buyable',"marketplace='US'")['buyable_asins']==1 and row('amazon_scope_buyable',"marketplace='US'")['target']==36;seen('amazon_scope_buyable')
    available=row('amazon_market_availability','sku_ref=? AND account=? AND marketplace=?',(sku,account,'US'));assert (available['stage'],available['status'])==('buyable','active-both')
    db.execute('UPDATE amazon_listings SET is_buyable=0,source_status=\'active\' WHERE id IN (?,?)',(fba,fbm))
    assert row('amazon_market_availability','sku_ref=? AND account=? AND marketplace=?',(sku,account,'US'))['stage']!='buyable'
    db.execute('UPDATE amazon_listings SET is_suppressed=1 WHERE id=?',(fba,))
    assert row('amazon_suppressed_listings',"asin='fixture-ASIN' AND account=?",(account,));seen('amazon_suppressed_listings')
    case=f.row('amazon_compliance_cases',account=account,listing=fba,status='open',doc_status='submitted')
    assert row('amazon_open_compliance_cases','id=?',(case,));seen('amazon_open_compliance_cases')
    assert row('amazon_market_availability','sku_ref=? AND account=? AND marketplace=?',(sku,account,'US'))['status']=='documents-submitted'
    db.execute("UPDATE amazon_compliance_cases SET status='closed' WHERE id=?",(case,));db.execute('UPDATE amazon_listings SET is_suppressed=0 WHERE id IN (?,?)',(fba,fbm))
    db.execute("UPDATE amazon_listing_changes SET status='submitted',change_type='offer' WHERE id=?",(scope,))
    submission=f.row('amazon_listing_submissions',listing_change=scope,result='accepted',submitted_at='2026-01-01T00:00:00Z')
    assert row('amazon_market_availability','sku_ref=? AND account=? AND marketplace=?',(sku,account,'US'))['status']=='offer-submitted'
    f.row('amazon_listing_submissions',listing_change=scope,result='failed',submitted_at='2026-01-02T00:00:00Z')
    assert row('amazon_market_availability','sku_ref=? AND account=? AND marketplace=?',(sku,account,'US'))['stage']=='to-fix';seen('amazon_market_availability')
    # Contacts, effective tags, message provenance, stage targets and next action.
    contact=f.row('people_contacts',tier=1,register='casual');fresh_contact=f.row('people_contacts',tier=1)
    f.row('people_interactions',contact=contact,occurred_at=day(-5)+'T00:00:00Z')
    f.row('people_interactions',contact=fresh_contact,occurred_at=day(0)+'T00:00:00Z')
    assert row('people_contacts_due','contact=?',(contact,))['due_on']==day(-1) and not row('people_contacts_due','contact=?',(fresh_contact,));seen('people_contacts_due')
    assert row('people_contacts_without_handles','id=?',(contact,))
    f.row('people_handles',contact=contact)
    assert row('people_contacts_without_handles','id=?',(contact,)) is None;seen('people_contacts_without_handles')
    ugc=f.row('work_functions',workspace='cedar-shop',name='ugc');other_function=f.row('work_functions',workspace='cedar-shop',name='other')
    conversation=f.row('people_conversations',function=ugc,status='open',workspace_tags=json.dumps(['cedar-shop']),channel='email')
    other_conversation=f.row('people_conversations',function=other_function,status='open',workspace_tags=json.dumps(['cedar-shop']),channel='email')
    inherited=f.row('people_messages',conversation=conversation,direction='outbound',workspace_tags=None,sent_at='2026-01-01T00:00:00Z',source_message_id='fixture-inherited')
    explicit=f.row('people_messages',conversation=conversation,direction='outbound',workspace_tags='[]',sent_at='2026-01-02T00:00:00Z',source_message_id='fixture-explicit')
    assert json.loads(row('people_message_workspaces',"source_message_id='fixture-inherited'")['workspace_tags'])==['cedar-shop']
    assert json.loads(row('people_message_workspaces',"source_message_id='fixture-explicit'")['workspace_tags'])==['personal-workspace'];seen('people_message_workspaces')
    assert row('people_messages_sent_by_person','message=?',(inherited,))
    f.row('people_drafts',sent_message=explicit)
    assert row('people_messages_sent_by_person','message=?',(explicit,)) is None;seen('people_messages_sent_by_person')
    f.row('people_participants',conversation=conversation,contact=contact,meeting=None)
    opened=row('people_open_conversations','id=?',(conversation,));assert opened['participant_count']==1 and opened['last_message_at']=='2026-01-02T00:00:00Z';seen('people_open_conversations')
    assert row('ugc_reply_queue','id=?',(conversation,)) and row('ugc_reply_queue','id=?',(other_conversation,)) is None;seen('ugc_reply_queue')
    # A conversation is in hand through an open draft; 24 hours with no change is stale; a change to a fact line counts.
    held=f.row('people_drafts',conversation=conversation,workspace='cedar-shop',status='draft',created_at=day(0)+'T00:00:00Z',updated_at=day(0)+'T00:00:00Z')
    waiting=f.row('people_drafts',conversation=other_conversation,workspace='cedar-shop',status='draft',created_at=day(-3)+'T00:00:00Z',updated_at=day(-3)+'T00:00:00Z')
    db.execute("UPDATE people_drafts SET status='approved',approval=? WHERE id=?",(yes(waiting),waiting))
    finished_draft=f.row('people_drafts',conversation=other_conversation,workspace='cedar-shop',status='draft')
    proof=f.row('people_messages',conversation=other_conversation,direction='outbound',text='fixture words',source_message_id='fixture-finished-send')
    db.execute("UPDATE people_drafts SET status='sent',approval=?,sent_message=? WHERE id=?",(yes(finished_draft),proof,finished_draft))
    hand=row('people_conversations_in_hand','draft=?',(held,));assert (hand['conversation'],hand['agent'],hand['status'],hand['stale'])==(conversation,'fixture','draft',0)
    assert row('people_conversations_in_hand','draft=?',(waiting,))['stale']==1 and row('people_conversations_in_hand','draft=?',(finished_draft,)) is None
    db.execute("UPDATE people_drafts SET workspace='system-workspace' WHERE id=?",(held,));assert row('people_conversations_in_hand','draft=?',(held,))['agent']=='fixture'
    for ended in ('skipped','replaced'):assert row('people_conversations_in_hand','draft=?',(f.row('people_drafts',conversation=other_conversation,workspace='cedar-shop',status=ended),)) is None
    fact_draft=f.row('people_drafts',conversation=other_conversation,workspace='cedar-shop',status='draft',created_at=day(-3)+'T00:00:00Z',updated_at=day(-3)+'T00:00:00Z')
    assert row('people_conversations_in_hand','draft=?',(fact_draft,))['stale']==1
    moment=db.execute("SELECT strftime('%Y-%m-%dT%H:%M:%fZ','now')").fetchone()[0]
    f.row('people_draft_facts',draft=fact_draft)
    hand=row('people_conversations_in_hand','draft=?',(fact_draft,));assert hand['stale']==0 and hand['last_change_at']>=moment;seen('people_conversations_in_hand')
    pipeline=f.row('people_pipelines',name='creators');stage=f.row('people_pipeline_stages',pipeline=pipeline,stage='outreach',target_days=14)
    opportunity=f.row('people_opportunities',workspace='cedar-shop',pipeline=pipeline,stage=stage,contact=contact,outcome='open',created_at=day(-3)+'T00:00:00Z')
    round_task=f.row('work_tasks',workspace='cedar-shop',status='todo');step=f.row('work_tasks',workspace='cedar-shop',parent=round_task,status='todo',owner='person',title='Fixture next step')
    next_action=f.row('base_values',set='next-action',value='content',active=1)
    f.row('work_links',workspace='cedar-shop',subject_type='task',subject_id=round_task,target_type='opportunity',target_id=opportunity,relation='about')
    f.row('work_links',workspace='cedar-shop',subject_type='task',subject_id=step,target_type='value',target_id=next_action,relation='tagged')
    board=row('people_opportunities_by_stage','opportunity=?',(opportunity,));assert tuple(board[k] for k in ('next_step','whose_move','whose_move_reason','days_in_stage','target_days'))==('Fixture next step','person','content',3,14);seen('people_opportunities_by_stage')
    # sample-finance and creator obligations: missing proof remains unknown.
    incoming=f.row('treasury_scheduled_transactions',direction='in',status='due',due_on=day(-1));outgoing=f.row('treasury_scheduled_transactions',direction='out',status='due',due_on=day(-1))
    assert row('treasury_money_owed','id=?',(incoming,))['days_overdue']==1 and not row('treasury_money_owed','id=?',(outgoing,));seen('treasury_money_owed')
    tx=f.row('treasury_transactions',deleted=0,amount_milliunits=-60000,currency='USD',source_id='fixture-payment')
    assert row('treasury_payments',"source_id='fixture-payment'")['amount_minor']==-6000.0;seen('treasury_payments')
    obligation=f.row('treasury_scheduled_transactions',opportunity=opportunity,direction='out',status='settled',amount_minor=10000,currency='USD',transaction=None)
    payment=row('ugc_payments_owed','scheduled_transaction=?',(obligation,));assert payment['paid_minor'] is None and payment['owed_minor'] is None and payment['ask_person']==1
    db.execute('UPDATE treasury_scheduled_transactions SET "transaction"=? WHERE id=?',(tx,obligation))
    payment=row('ugc_payments_owed','scheduled_transaction=?',(obligation,));assert (payment['paid_minor'],payment['owed_minor'],payment['ask_person'])==(6000.0,4000.0,0);seen('ugc_payments_owed')
    deliverable=f.row('ugc_deliverables',opportunity=opportunity,status='agreed',quantity=2)
    content=f.row('design_content',status='approved')
    f.row('ugc_deliverable_content',deliverable=deliverable,content=content)
    for availability,hash_,identity,expires in [('available','same','verified',None),('available','same','verified',None),('available','old','verified','2000-01-01'),('available','unknown','unknown',None)]:
        f.row('ugc_media_files',deliverable=deliverable,availability=availability,file_hash=hash_,identity_status=identity,expires_at=expires)
    missing=row('ugc_missing_content','deliverable=?',(deliverable,));assert tuple(missing[k] for k in ('delivered_quantity','accepted_quantity','observed_file_count','available_file_count'))==(1,1,2,1)
    waived=f.row('ugc_deliverables',opportunity=opportunity,status='waived',quantity=2);assert not row('ugc_missing_content','deliverable=?',(waived,));seen('ugc_missing_content')
    rights=f.row('ugc_usage_rights',status='granted',platform='instagram',territory='US',valid_from=day(-10),valid_until=day(5))
    unknown=f.row('ugc_usage_rights',status='granted',platform=None,territory='US',valid_from=day(-10),valid_until=day(50))
    assert row('ugc_rights_expiring','id=?',(rights,))['rights_status']=='expiring' and row('ugc_rights_expiring','id=?',(rights,))['days_remaining']==5
    assert row('ugc_rights_expiring','id=?',(unknown,))['rights_status']=='unknown_scope';seen('ugc_rights_expiring')
    expected={t['name'] for t in targets if t['kind']=='view'};assert tested==expected,'view parity coverage '+str(expected-tested)
    db.close();return sorted(tested)
