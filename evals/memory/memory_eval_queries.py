"""Seven bounded read routes. No draft, raw source, or unrestricted SQL is read."""
from datetime import datetime,timedelta,timezone
import hashlib,json,sqlite3
from pathlib import Path
QUESTIONS=('yesterday','now','blocked','root-cause','next','month','procedure')
CAPS=dict(zip(QUESTIONS,(50,20,50,10,20,31,1)))
SQL={
'yesterday':"SELECT seq AS id,subject_type,subject_id,summary,occurred_at,recorded_at,source FROM events_changes WHERE workspace=? AND julianday(occurred_at)>=julianday(?) AND julianday(occurred_at)<julianday(?) ORDER BY occurred_at,seq",
'now':"SELECT id,number,title,status,updated_at,source FROM work_tasks WHERE workspace=? AND status NOT IN ('done','canceled','replaced') ORDER BY id",
'blocked':"SELECT t.id,t.number,t.title,t.problem,t.updated_at,group_concat(l.subject_id) AS blockers FROM work_tasks t LEFT JOIN work_links l ON l.workspace=t.workspace AND l.target_type='task' AND l.target_id=t.id AND l.relation='blocks' WHERE t.workspace=? AND t.status='blocked' GROUP BY t.id ORDER BY t.id",
'root-cause':"SELECT id,number,title,root_cause,source,ended_at FROM work_incidents WHERE workspace=? AND status='closed' AND root_cause IS NOT NULL AND trim(root_cause)<>'' AND source IS NOT NULL AND trim(source)<>'' ORDER BY ended_at DESC,id",
'next':"SELECT t.id,t.number,t.title,t.status,t.updated_at,t.source,CASE WHEN t.status IN ('todo','in-progress') AND NOT EXISTS (SELECT 1 FROM work_links l JOIN work_tasks b ON b.id=l.subject_id AND b.workspace=l.workspace WHERE l.workspace=t.workspace AND l.target_id=t.id AND l.target_type='task' AND l.subject_type='task' AND l.relation='blocks' AND b.status NOT IN ('done','canceled','replaced')) THEN 1 ELSE 0 END AS ready,NULL AS authorized FROM work_tasks t WHERE t.workspace=? AND t.status IN ('todo','in-progress','blocked') ORDER BY t.id",
'month':"SELECT date(h.as_of) AS day,m.name,m.unit,h.measure,avg(h.value) AS value,count(h.value) AS observations FROM work_measure_history h JOIN work_measures m ON m.id=h.measure AND m.workspace=h.workspace WHERE h.workspace=? AND h.measure=? AND h.as_of>=? AND h.as_of<? GROUP BY date(h.as_of),h.measure ORDER BY day",
'procedure':"SELECT id,name,status,card_path FROM base_capabilities WHERE workspace=? AND name=? AND status='live' ORDER BY id"
}
ROUTES={'yesterday':['events_changes'],'now':['work_tasks'],'blocked':['work_tasks','work_links'],'root-cause':['work_incidents'],'next':['work_tasks','work_links'],'month':['work_measure_history','work_measures'],'procedure':['base_capabilities']}

def query(database,question,workspace,at,measure=None,capability=None,procedure_root=None,pins=None):
    if question not in QUESTIONS:return {'choices':list(QUESTIONS),'status':'unknown','rows':[],'reads':0,'files':0}
    stamp=datetime.fromisoformat(at)
    if stamp.tzinfo is None:raise ValueError('at requires the business timezone offset')
    if not workspace:raise ValueError('workspace is required')
    args=[workspace]
    if question=='yesterday':
        end=stamp.replace(hour=0,minute=0,second=0,microsecond=0);start=end-timedelta(days=1)
        args+=[start.isoformat(),end.isoformat()]
    elif question=='month':
        if measure is None:raise ValueError('month needs one measure')
        end=stamp.replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)
        start=end-timedelta(days=31);args+=[measure,start.date().isoformat(),end.date().isoformat()]
    elif question=='procedure':
        if not capability:raise ValueError('procedure needs one capability')
        args+=[capability]
    path=Path(database).resolve()
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row;db.execute('PRAGMA query_only=ON')
        # COUNT and bounds are computed in this one SELECT; the wrapper includes the full omitted count.
        sql='WITH selected AS ('+SQL[question]+') SELECT *,count(*) OVER() AS _total FROM selected LIMIT ?'
        fetched=[dict(r) for r in db.execute(sql,args+[CAPS[question]])]
    total=fetched[0].get('_total',0) if fetched else 0
    for row in fetched:row.pop('_total',None)
    answer={'question':question,'workspace':workspace,'as_of':at,'route':ROUTES[question],'status':'records',
            'rows':fetched,'omitted':max(0,total-len(fetched)),'reads':1,'files':0,'raw_files':0,
            'source_age':'unknown','evidence_watermark':None}
    if question=='now':
        # No ruled memory_current table or evidence watermark exists. Do not call an unproven claim current.
        answer['status']='unknown';answer['warning']='Authoritative task rows only; memory-current and freshness proof are unavailable.'
    if question=='next':answer['warning']='Ready does not prove approval; authorized stays unknown until an approval reader exists.'
    if question=='root-cause' and not fetched:answer['status']='unknown'
    if question=='month':
        have={r['day'] for r in fetched};answer['gaps']=[(start+timedelta(days=i)).date().isoformat() for i in range(31) if (start+timedelta(days=i)).date().isoformat() not in have]
    if question=='procedure' and fetched:
        rel=Path(fetched[0]['card_path']);root=Path(procedure_root).resolve() if procedure_root else None
        expected=(pins or {}).get(str(rel))
        if root is None or expected is None:answer['status']='unknown';answer['warning']='Accepted or released procedure hash is required.'
        else:
            if rel.is_absolute() or '..' in rel.parts or rel.parts[0] not in ('tools','skills'):raise ValueError('procedure must be a tools or skills path')
            candidate=root/rel
            if any(p.is_symlink() for p in [candidate]+list(candidate.parents)):raise ValueError('procedure symlink refused')
            raw=candidate.read_bytes();answer['files']=1
            if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('procedure differs from its accepted/released hash')
            answer['procedure']=raw.decode('utf-8');answer['procedure_sha256']=expected
    elif question=='procedure':answer['status']='unknown'
    # Bound actual serialized UTF-8 bytes, even for large row bodies or a large procedure.
    while len(json.dumps(answer,ensure_ascii=False).encode('utf-8'))>12000 and answer['rows']:
        answer['rows'].pop();answer['omitted']+=1;answer.pop('procedure',None)
        if question=='procedure':answer['status']='unknown';answer['warning']='Procedure exceeds the result byte budget.'
    if len(json.dumps(answer,ensure_ascii=False).encode('utf-8'))>12000:raise ValueError('result envelope exceeds byte budget')
    return answer
