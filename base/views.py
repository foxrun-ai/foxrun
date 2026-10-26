"""Executable views for the blueprint. No business rows are supplied."""

from __future__ import annotations

import sys as _person_sys
from pathlib import Path as _PersonPath
_person_root = next(p for p in _PersonPath(__file__).resolve().parents if (p / "base/person.py").is_file())
_person_sys.path.insert(0, str(_person_root))
from base import person as _fox_person
from collections import defaultdict

def view_sql(targets,columns):
    by=defaultdict(list)
    for c in columns:by[c['table']].append(c['column'])
    sql=[]
    # A view is built only when the loaded blueprint names it. Add-on views come with their add-on's rows.
    wanted={t['name'] for t in targets if t['kind']=='view'}
    tables={t['name'] for t in targets if t['kind']=='table'}
    def view(name,source,aliases,extra=None,where='',tail=''):
        if name not in wanted:return
        expressions=dict(extra or {})
        for alias,table in aliases:
            for field in by[table]:expressions.setdefault(field,alias+'."'+field+'"')
        missing=set(by[name])-expressions.keys()
        if missing:raise ValueError(name+' lacks view expressions: '+str(missing))
        select=', '.join(expressions[f]+' AS "'+f+'"' for f in by[name])
        sql.append('CREATE VIEW "'+name+'" AS SELECT '+select+' FROM '+source+(' WHERE '+where if where else '')+(' '+tail if tail else '')+';')
    open_task="t.status NOT IN ('done','canceled','replaced') AND t.parent IS NULL"
    view('work_open_tasks','work_tasks t',[('t','work_tasks')],{'planned':'t.planned_on'},open_task)
    view('work_this_week','work_tasks t',[('t','work_tasks')],{'planned':'t.planned_on'},open_task+" AND (t.planned_on<=date('now','+7 days') OR t.due_on<=date('now','+7 days'))")
    view('work_eisenhower','work_tasks t',[('t','work_tasks')],{'task':'t.id','task_workspace':'t.workspace','quadrant':'CASE WHEN t.important=1 AND t.urgent=1 THEN 1 WHEN t.important=1 THEN 2 WHEN t.urgent=1 THEN 3 ELSE 4 END'},open_task)
    view('work_in_review','work_tasks t',[('t','work_tasks')],{'evidence_path':"(SELECT a.path FROM work_attachments a WHERE a.subject_type='task' AND a.subject_id=t.id AND a.workspace=t.workspace ORDER BY a.seq DESC LIMIT 1)"},"t.status='in-review'")
    view('work_next_step','work_tasks t',[('t','work_tasks')],where="t.parent IS NOT NULL AND t.status IN ('todo','in-progress') AND t.id=(SELECT x.id FROM work_tasks x WHERE x.parent=t.parent AND x.status IN ('todo','in-progress') ORDER BY x.sort_order,x.id LIMIT 1)")
    view('work_latest_run_per_task','work_runs r',[('r','work_runs')],{'run':'r.id','task':'r.subject_id'},"r.subject_type='task' AND NOT EXISTS(SELECT 1 FROM work_runs n WHERE n.subject_type='task' AND n.subject_id=r.subject_id AND n.workspace=r.workspace AND (n.started_at>r.started_at OR (n.started_at IS r.started_at AND n.id>r.id)))")
    view('work_runs_to_place','work_runs r JOIN work_tasks t ON t.id=r.subject_id AND t.workspace=r.workspace',[('r','work_runs')],{'run':'r.id','standing_task':'t.id'},"r.subject_type='task' AND t.idempotency_key='session-holding-task'")
    needs="t.status NOT IN ('done','canceled','replaced') AND (lower(t.owner)='@person@' OR (t.status='in-review' AND t.reviewer='@person@') OR (t.status='blocked' AND EXISTS(SELECT 1 FROM work_links l JOIN work_tasks b ON b.id=l.subject_id WHERE l.target_id=t.id AND l.subject_type='task' AND l.target_type='task' AND l.relation='blocks' AND lower(b.owner)='@person@' AND b.status NOT IN ('done','canceled','replaced'))))"
    view('work_needs_me','work_tasks t',[('t','work_tasks')],{'subject_id':'t.id','subject_type':"'task'",'reason':"CASE WHEN lower(t.owner)='@person@' THEN 'owner' WHEN t.reviewer='@person@' THEN 'reviewer' ELSE 'dependency' END"},needs)
    # Proposals and drafts remain their own rows in the same saved list.
    sql[-1]=sql[-1][:-1]+" UNION ALL SELECT 'proposal',p.status,p.id,'proposal',p.why,p.workspace FROM base_proposals p WHERE p.status='open' AND NOT EXISTS(SELECT 1 FROM base_approvals a WHERE a.subject_type='proposal' AND a.subject_id=p.id AND a.workspace=p.workspace AND a.action='approved' AND a.authorization_valid=1 AND a.approved_sha256=p.content_hash);"
    if 'people_drafts' in tables:sql[-1]=sql[-1][:-1]+" UNION ALL SELECT 'draft',d.status,d.id,'draft',d.text,d.workspace FROM people_drafts d WHERE d.status='draft' AND NOT EXISTS(SELECT 1 FROM base_approvals a WHERE a.subject_type='draft' AND a.subject_id=d.id AND a.workspace=d.workspace AND a.action='approved' AND a.authorization_valid=1 AND a.version=d.version AND a.approved_sha256=d.content_hash);"
    view('work_open_promises','work_tasks t',[('t','work_tasks')],{'task':'t.id','about':"(SELECT group_concat(l.target_id) FROM work_links l WHERE l.subject_id=t.id AND l.subject_type='task' AND l.relation='about')",'source':"(SELECT group_concat(l.path) FROM work_links l WHERE l.subject_id=t.id AND l.subject_type='task' AND l.relation='source')"},"t.status NOT IN ('done','canceled','replaced') AND EXISTS(SELECT 1 FROM work_links l JOIN base_values v ON v.id=l.target_id WHERE l.subject_id=t.id AND l.subject_type='task' AND l.relation='tagged' AND l.target_type='value' AND v.value='promise')")
    count=lambda condition: '(SELECT count(*) FROM work_tasks z WHERE z.project=p.id AND z.parent IS NULL AND '+condition+')'
    live=count("z.status<>'canceled'");done=count("z.status='done'");backlog=count("z.status='backlog'")
    eligible='('+live+'-'+backlog+')'
    view('work_program_plan','work_projects p JOIN work_programs g ON g.id=p.program LEFT JOIN work_themes h ON h.id=p.theme LEFT JOIN work_tasks t ON t.project=p.id AND t.parent IS NULL',[('t','work_tasks')],{'workspace':'p.workspace','program':'g.name','theme':'h.name','theme_sort_order':'h.sort_order','stream':'p.title','stream_id':'p.id','stream_id_workspace':'p.workspace','stream_sort_order':'p.sort_order','stream_status':'p.status','owner':'p.owner','task':'t.title','task_id':'t.id','task_id_workspace':'t.workspace','task_sort_order':'t.sort_order','live_tasks':live,'done_tasks':done,'backlog_tasks':backlog,'percent_done':'CASE WHEN '+eligible+'=0 THEN 0 ELSE 100.0*'+done+'/'+eligible+' END'},"p.status<>'replaced'")
    verified="EXISTS(SELECT 1 FROM work_changes c WHERE c.subject_type='task' AND c.subject_id=t.id AND c.workspace=t.workspace AND c.action IN ('verified','accepted') AND c.subject_version=CAST(t.version AS TEXT) AND c.actor=CASE WHEN t.reviewer='@person@' THEN '@person@' ELSE t.reviewed_by END)"
    view('work_ready_to_merge','work_tasks t JOIN work_links l ON l.subject_type=\'task\' AND l.subject_id=t.id AND l.workspace=t.workspace AND l.relation=\'produced\' AND l.system=\'github\'',[('t','work_tasks')],{'task':'t.id','task_workspace':'t.workspace','check_passed':verified,'pull_request':'l.path','pull_request_source_database':'l.system','pull_request_source_table':'l.target_type'},"t.status='in-review' AND "+verified+" AND NOT EXISTS(SELECT 1 FROM work_changes c WHERE c.subject_id=t.id AND c.subject_type='task' AND c.workspace=t.workspace AND c.action='merged' AND EXISTS(SELECT 1 FROM json_each(c.refs) r WHERE r.value=l.path))")
    view('base_dictionary','base_object_types o JOIN base_modules m ON m.id=o.module LEFT JOIN base_fields f ON f.object_type=o.id',[('f','base_fields'),('o','base_object_types')],{'object_type':'o.name','module':'m.name','ordinal':'f.sort_order'})
    view('base_open_decisions','base_decisions d LEFT JOIN work_projects p ON p.id=d.project LEFT JOIN work_functions f ON f.id=d.function',[('d','base_decisions')],{'workspace':'coalesce(p.workspace,f.workspace)'},"d.status IN ('open','soft')")
    event_fields=by['base_timeline']
    union=[]
    for table in ('work_changes','work_comments','work_attachments','base_approvals','base_receipts'):
        union.append('SELECT '+','.join(("'"+table+"'" if field=='table' else '"'+field+'"')+' AS "'+field+'"' for field in event_fields)+' FROM '+table)
    sql.append('CREATE VIEW base_timeline AS '+' UNION ALL '.join(union)+' ORDER BY seq;')
    view('amazon_families','amazon_listings l',[('l','amazon_listings')],{'child_count':'count(DISTINCT l.asin)'},'l.parent_asin IS NOT NULL','GROUP BY l.parent_asin,l.marketplace')
    view('amazon_open_compliance_cases','amazon_compliance_cases c LEFT JOIN amazon_listings l ON l.id=c.listing LEFT JOIN commerce_accounts a ON a.id=c.account',[('c','amazon_compliance_cases'),('l','amazon_listings')],{'account_workspace':'a.workspace'},"c.status NOT IN ('closed','resolved')")
    view('amazon_suppressed_listings','amazon_listings l',[('l','amazon_listings')],{'suppression_reason':'l.status_reason'},'l.is_suppressed=1')
    avail_source="""(SELECT account,marketplace,sku_ref FROM amazon_listing_changes UNION SELECT account,marketplace,sku_ref FROM amazon_listings WHERE sku_ref IS NOT NULL) k
 LEFT JOIN amazon_listing_changes s ON s.id=(SELECT x.id FROM amazon_listing_changes x WHERE x.account=k.account AND x.marketplace=k.marketplace AND x.sku_ref=k.sku_ref ORDER BY x.created_at DESC,x.id DESC LIMIT 1)
 LEFT JOIN amazon_listing_submissions u ON u.id=(SELECT x.id FROM amazon_listing_submissions x WHERE x.listing_change=s.id ORDER BY x.submitted_at DESC,x.id DESC LIMIT 1)
 LEFT JOIN amazon_listings l ON l.account=k.account AND l.marketplace=k.marketplace AND l.sku_ref=k.sku_ref"""
    compliance="EXISTS(SELECT 1 FROM amazon_compliance_cases c JOIN amazon_listings z ON z.id=c.listing WHERE c.account=k.account AND z.sku_ref=k.sku_ref AND z.marketplace=k.marketplace AND c.status NOT IN ('closed','resolved'))"
    documents="EXISTS(SELECT 1 FROM amazon_compliance_cases c JOIN amazon_listings z ON z.id=c.listing WHERE c.account=k.account AND z.sku_ref=k.sku_ref AND z.marketplace=k.marketplace AND c.status NOT IN ('closed','resolved') AND c.doc_status='submitted')"
    active="CASE WHEN max(CASE WHEN l.is_buyable=1 AND lower(l.fulfillment)='fba' THEN 1 ELSE 0 END)=1 AND max(CASE WHEN l.is_buyable=1 AND lower(l.fulfillment)='fbm' THEN 1 ELSE 0 END)=1 THEN 'active-both' WHEN max(CASE WHEN l.is_buyable=1 AND lower(l.fulfillment)='fba' THEN 1 ELSE 0 END)=1 THEN 'active-fba' ELSE 'active-fbm' END"
    status="CASE WHEN max(l.is_buyable)=1 THEN "+active+" WHEN s.status='retired' THEN 'closed' WHEN "+documents+" THEN 'documents-submitted' WHEN "+compliance+" THEN 'blocked' WHEN lower(u.result) IN ('failed','error','rejected') OR s.status='blocked' THEN 'blocked' WHEN s.status='submitted' THEN CASE s.change_type WHEN 'offer' THEN 'offer-submitted' WHEN 'fba-switch' THEN 'fba-submitted' ELSE 'listing-submitted' END WHEN max(l.is_suppressed)=1 THEN 'suppressed' WHEN max(CASE WHEN l.source_status='missing-required' THEN 1 ELSE 0 END)=1 THEN 'missing-required' WHEN max(CASE WHEN l.source_status='no-channel' THEN 1 ELSE 0 END)=1 THEN 'no-channel' WHEN count(l.id)=0 THEN 'no-listing' WHEN max(l.is_own_offer)=0 THEN 'other-seller-only' WHEN max(l.quantity)=0 THEN 'no-offer' ELSE 'no-buyable-offers' END"
    stage="CASE WHEN max(l.is_buyable)=1 THEN 'buyable' WHEN s.status='retired' THEN 'closed' WHEN "+compliance+" THEN 'compliance' WHEN lower(u.result) IN ('failed','error','rejected') OR s.status='blocked' OR max(l.is_suppressed)=1 OR max(CASE WHEN l.source_status='missing-required' THEN 1 ELSE 0 END)=1 THEN 'to-fix' WHEN s.status='submitted' THEN 'waiting' WHEN count(l.id)=0 THEN 'not-started' WHEN max(l.quantity)=0 OR max(l.is_own_offer)=0 THEN 'created' ELSE 'waiting' END"
    view('amazon_market_availability',avail_source,[],{'account':'k.account','marketplace':'k.marketplace','sku_ref':'k.sku_ref','stage':stage,'status':status,'is_buyable':'max(l.is_buyable)','fetched_at':'max(l.fetched_at)'},tail='GROUP BY k.sku_ref,k.account,k.marketplace')
    view('amazon_scope_buyable','amazon_listings l',[('l','amazon_listings')],{'buyable_asins':'count(DISTINCT l.asin)','target':"(SELECT m.target FROM work_measures m WHERE m.workspace=l.workspace AND m.source='amazon_scope_buyable' ORDER BY m.id LIMIT 1)"},"l.is_buyable=1 AND l.marketplace IN ('US','CA') AND EXISTS(SELECT 1 FROM amazon_listing_changes s WHERE s.sku_ref=l.sku_ref AND s.account=l.account AND s.marketplace=l.marketplace AND s.status='draft')",'GROUP BY l.marketplace')
    view('commerce_low_stock','commerce_inventory_levels i JOIN commerce_accounts a ON a.id=i.account',[('i','commerce_inventory_levels')],{'amazon_account_id':"CASE WHEN a.source_system='amazon' THEN a.id END",'amazon_account_workspace':"CASE WHEN a.source_system='amazon' THEN a.workspace END",'commerce_account_id':'a.id','commerce_account_source_system':'a.source_system','source_account_id':'a.source_account_id','source_system':'a.source_system'},'i.available<=0')
    mirror=[]
    for t in targets:
        if t['kind']=='table' and t.get('database_type')=='mirror' and 'fetched_at' in by[t['name']]:
            n=t['name'];run="(SELECT status FROM work_runs WHERE id=(SELECT refresh_run FROM "+n+" ORDER BY fetched_at DESC LIMIT 1))" if 'refresh_run' in by[n] else 'NULL'
            mirror.append("SELECT CAST(strftime('%s','now') AS INTEGER)-CAST(strftime('%s',max(fetched_at)) AS INTEGER) AS age_seconds,"+run+" AS last_run_status,max(fetched_at) AS newest_fetched_at,count(*) AS row_count,'"+n+"' AS \"table\" FROM "+n)
    if 'commerce_mirror_age' in wanted:sql.append('CREATE VIEW commerce_mirror_age AS '+' UNION ALL '.join(mirror)+';')
    view('commerce_open_support_cases','commerce_support_cases c',[('c','commerce_support_cases')],{'source':'c.platform'},"c.status NOT IN ('closed','resolved')")
    view('commerce_restock_due','commerce_restocks r',[('r','commerce_restocks')],{'days_overdue':"CAST(julianday(date('now'))-julianday(r.due_on) AS INTEGER)", 'destination_location_id':'r.destination_location_id'},"r.status IN ('planned','approved','ordered','in-transit') AND r.due_on IS NOT NULL AND r.due_on<=date('now')")
    rec=lambda source:"(SELECT x.recommended_quantity FROM commerce_restock_recommendations x WHERE x.restock=r.id AND x.source='"+source+"' ORDER BY x.as_of DESC,x.id DESC LIMIT 1)"
    sent='(SELECT sum(li.quantity) FROM commerce_shipments sh JOIN commerce_line_items li ON li."order"=sh."order" WHERE sh.id=r.shipment AND li.sku_ref=r.sku_ref)'
    view('commerce_restock_plan','commerce_restocks r',[('r','commerce_restocks')],{'restock':'r.id','amazon_recommended':rec('amazon'),'helium_10_recommended':rec('helium-10'),'sent':sent,'short':'r.approved_quantity-'+sent,'delta':rec('amazon')+'-'+rec('helium-10'),'shipbob_percent':'100.0*'+sent+'/nullif(r.approved_quantity,0)'})
    last='(SELECT max(i.occurred_at) FROM people_interactions i WHERE i.contact=c.id)'
    due='date('+last+", '+' || CASE c.tier WHEN 1 THEN 4 WHEN 2 THEN 14 WHEN 3 THEN 30 WHEN 4 THEN 90 END || ' days')"
    view('people_contacts_due','people_contacts c',[('c','people_contacts')],{'contact':'c.id','last_contact_at':last,'due_on':due},last+" IS NULL OR "+due+"<=date('now')")
    view('people_contacts_without_handles','people_contacts c',[('c','people_contacts')],where='NOT EXISTS(SELECT 1 FROM people_handles h WHERE h.contact=c.id)')
    effective="coalesce(m.workspace_tags,c.workspace_tags,'[]')"
    view('people_message_workspaces','people_messages m JOIN people_conversations c ON c.id=m.conversation',[('m','people_messages')],{'workspace_tags':'CASE WHEN json_array_length('+effective+")=0 THEN '[\"@personal_workspace@\"]' ELSE "+effective+' END'})
    view('people_messages_sent_by_person','people_messages m',[('m','people_messages')],{'message':'m.id'},"m.direction IN ('out','outbound','sent') AND NOT EXISTS(SELECT 1 FROM people_drafts d WHERE d.sent_message=m.id)")
    # conversation-in-hand: an open draft row puts its conversation in hand. The agent is the actor of the draft's created event.
    hand_agent="(SELECT x.actor FROM work_changes x WHERE x.subject_type='draft' AND x.subject_id=d.id AND x.action='created' ORDER BY x.seq LIMIT 1)"
    hand_change="(SELECT max(z.at) FROM (SELECT coalesce(d.updated_at,d.created_at) AS at UNION ALL SELECT x.occurred_at FROM work_changes x JOIN people_draft_facts f ON f.id=x.subject_id WHERE x.subject_type='draft-fact' AND f.draft=d.id) z)"
    view('people_conversations_in_hand','people_drafts d',[('d','people_drafts')],{'draft':'d.id','agent':hand_agent,'last_change_at':hand_change,'stale':'CASE WHEN '+hand_change+" IS NULL THEN NULL WHEN julianday('now')-julianday("+hand_change+')>=1 THEN 1 ELSE 0 END'},"d.status NOT IN ('sent','skipped','replaced')")
    conversation_extra={'workspace':"CASE WHEN json_array_length(c.workspace_tags)=0 THEN '@personal_workspace@' ELSE json_extract(c.workspace_tags,'$[0]') END",'function_workspace':'f.workspace','last_message_at':'(SELECT max(m.sent_at) FROM people_messages m WHERE m.conversation=c.id)','participant_count':'(SELECT count(*) FROM people_participants p WHERE p.conversation=c.id)'}
    view('people_open_conversations','people_conversations c LEFT JOIN work_functions f ON f.id=c.function',[('c','people_conversations')],conversation_extra,"c.status='open'")
    next_source="""work_tasks t JOIN work_links a ON a.subject_type='task' AND a.subject_id IN (t.id,t.parent) AND a.target_type='opportunity' AND a.target_id=o.id AND a.workspace=o.workspace AND a.relation='about'
 JOIN work_links tag ON tag.subject_type='task' AND tag.subject_id=t.id AND tag.relation='tagged' AND tag.target_type='value'
 JOIN base_values v ON v.id=tag.target_id AND v."set"='next-action'
 WHERE t.parent IS NOT NULL AND t.status NOT IN ('done','canceled','replaced') ORDER BY t.sort_order,t.id LIMIT 1"""
    next_value=lambda value:'(SELECT '+value+' FROM '+next_source+')'
    direction="(SELECT m.direction FROM people_interactions i JOIN people_messages m ON m.id=i.source_message WHERE i.opportunity=o.id ORDER BY m.sent_at DESC,m.id DESC LIMIT 1)"
    move='coalesce('+next_value('t.owner')+",CASE "+direction+" WHEN 'inbound' THEN '@person@' WHEN 'outbound' THEN c.name END)"
    reason='coalesce('+next_value('v.value')+",CASE "+direction+" WHEN 'inbound' THEN 'reply' WHEN 'outbound' THEN 'reply' END)"
    view('people_opportunities_by_stage','people_pipeline_stages s LEFT JOIN people_opportunities o ON o.stage=s.id AND o.pipeline=s.pipeline AND o.outcome=\'open\' LEFT JOIN people_contacts c ON c.id=o.contact',[('o','people_opportunities'),('s','people_pipeline_stages')],{'opportunity':'o.id','opportunity_workspace':'o.workspace','contact_name':'c.name','stage_pipeline':'s.pipeline','stage':'s.id','pipeline':'s.pipeline','days_in_stage':"CAST(julianday(date('now'))-julianday(date(coalesce((SELECT max(x.occurred_at) FROM work_changes x WHERE x.subject_id=o.id AND x.subject_type='opportunity' AND x.workspace=o.workspace AND x.field='stage'),o.created_at))) AS INTEGER)",'next_step':next_value('t.title'),'whose_move':move,'whose_move_reason':reason})
    view('treasury_money_owed','treasury_scheduled_transactions t',[('t','treasury_scheduled_transactions')],{'days_overdue':"CAST(julianday(date('now'))-julianday(t.due_on) AS INTEGER)"},"t.direction='in' AND t.status IN ('expected','due')")
    view('treasury_payments','treasury_transactions t',[('t','treasury_transactions')],{'amount_minor':'t.amount_milliunits/10.0'},'t.deleted=0')
    quantity='(SELECT count(*) FROM ugc_deliverable_content dc WHERE dc.deliverable=d.id)'
    files="(SELECT count(DISTINCT m.file_hash) FROM ugc_media_files m WHERE m.deliverable=d.id AND m.identity_status='verified')"
    available="(SELECT count(DISTINCT m.file_hash) FROM ugc_media_files m WHERE m.deliverable=d.id AND m.identity_status='verified' AND m.availability='available' AND (m.expires_at IS NULL OR julianday(m.expires_at)>julianday('now')))"
    view('ugc_missing_content','ugc_deliverables d JOIN people_opportunities o ON o.id=d.opportunity',[('d','ugc_deliverables')],{'deliverable':'d.id','deliverable_workspace':'d.workspace','opportunity_workspace':'o.workspace','delivered_quantity':quantity,'accepted_quantity':"(SELECT count(*) FROM ugc_deliverable_content dc JOIN design_content c ON c.id=dc.content WHERE dc.deliverable=d.id AND c.status IN ('approved','published'))",'observed_file_count':files,'available_file_count':available,'open_file_request_count':"(SELECT count(*) FROM ugc_file_requests f WHERE f.opportunity=d.opportunity AND f.status NOT IN ('closed','canceled','received'))"},"d.status<>'waived' AND ("+quantity+'<d.quantity OR d.quantity IS NULL)')
    paid="CASE WHEN tx.deleted=0 AND tx.currency=s.currency AND tx.amount_milliunits<0 THEN -tx.amount_milliunits/10.0 END"
    view('ugc_payments_owed','treasury_scheduled_transactions s JOIN people_opportunities o ON o.id=s.opportunity JOIN people_pipelines p ON p.id=o.pipeline LEFT JOIN treasury_transactions tx ON tx.id=s."transaction" LEFT JOIN work_attachments a ON a.subject_type=\'scheduled-transaction\' AND a.subject_id=s.id AND a.workspace=s.workspace AND a.seq=(SELECT max(x.seq) FROM work_attachments x WHERE x.subject_type=\'scheduled-transaction\' AND x.subject_id=s.id AND x.workspace=s.workspace)',[('o','people_opportunities')],{'scheduled_transaction':'s.id','scheduled_transaction_workspace':'s.workspace','opportunity':'o.id','opportunity_workspace':'o.workspace','paid_minor':paid,'owed_minor':'s.amount_minor-('+paid+')','currency':'s.currency','approval_seq':"(SELECT max(b.seq) FROM base_approvals b WHERE b.subject_type='scheduled-transaction' AND b.subject_id=s.id AND b.workspace=s.workspace AND b.action='approved')",'proof_attachment':'a.seq','ask_person':'CASE WHEN ('+paid+') IS NULL THEN 1 ELSE 0 END'},"p.name='creators' AND s.direction='out' AND s.status NOT IN ('skipped','written-off','canceled')")
    view('ugc_reply_queue','people_open_conversations c JOIN work_functions f ON f.id=c.function',[('c','people_open_conversations')],where="f.name='ugc'")
    rights="CASE WHEN r.status<>'granted' THEN r.status WHEN r.valid_from IS NULL OR r.valid_until IS NULL OR r.platform IS NULL OR r.territory IS NULL THEN 'unknown_scope' WHEN r.valid_until<date('now') THEN 'expired' WHEN r.valid_until<=date('now','+30 days') THEN 'expiring' ELSE 'check_required' END"
    view('ugc_rights_expiring','ugc_usage_rights r LEFT JOIN design_content c ON c.id=r.content',[('r','ugc_usage_rights')],{'content_workspace':'c.workspace','days_remaining':"CAST(julianday(r.valid_until)-julianday(date('now')) AS INTEGER)",'rights_status':rights},"r.status<>'granted' OR r.valid_from IS NULL OR r.valid_until IS NULL OR r.platform IS NULL OR r.territory IS NULL OR r.valid_until<=date('now','+30 days')")
    expected={t['name'] for t in targets if t['kind']=='view'}
    built={s.split('CREATE VIEW ',1)[1].split(' AS ',1)[0].strip('"') for s in sql}
    if expected!=built:raise ValueError('View coverage mismatch: '+str(expected^built))
    return _fox_person.render_sql('\n\n'.join(sql)+'\n')
