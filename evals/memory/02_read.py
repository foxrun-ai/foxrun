#!/usr/bin/env python3
"""Score all seven CEO read routes on isolated records."""
import json,tempfile
from pathlib import Path
from memory_eval_fixtures import build,AT
from memory_eval_queries import QUESTIONS,query

def run():
    failures=[];total=0
    with tempfile.TemporaryDirectory(prefix='memory-read-') as folder:
        db,pins=build(folder)
        for ws in ('shop','personal','practice'):
            for question in QUESTIONS:
                total+=1
                try:
                    a=query(db,question,ws,AT,measure=1,capability='sample',procedure_root=folder,pins=pins)
                    if a['raw_files'] or not a['rows']:raise ValueError('missing bounded records')
                    if question=='now' and (a['status']!='unknown' or any(r['status']=='replaced' for r in a['rows'])):raise ValueError('unproven or replaced fact is current')
                    if question=='root-cause' and [r['number'] for r in a['rows']]!=['I1']:raise ValueError('unaccepted hypothesis returned')
                    if question=='next' and (a['rows'][1]['ready'] or a['rows'][1]['authorized'] is not None):raise ValueError('blocked work is authorized')
                    if question=='month' and (len(a['rows'])!=2 or len(a['gaps'])!=29):raise ValueError('gaps were invented as zero')
                    if question=='procedure' and 'Accepted procedure' not in a.get('procedure',''):raise ValueError('accepted procedure missing')
                except Exception as e:failures.append(ws+':'+question+':'+str(e))
    from memory_eval_business import score_cases
    extra=score_cases(fetch=False)
    total+=extra['denominator'];failures.extend(extra['failures'])
    return dict(test='02-read',passed=not failures,numerator=total-len(failures),denominator=total,failures=failures,sample_shop_cases=extra['denominator'])
if __name__=='__main__':
    result=run();print(json.dumps(result,sort_keys=True));raise SystemExit(0 if result['passed'] else 1)
