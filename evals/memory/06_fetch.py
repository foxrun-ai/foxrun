#!/usr/bin/env python3
"""Count database/file reads and serialized bytes for the seven questions."""
import json,tempfile
from memory_eval_fixtures import build,AT
from memory_eval_queries import CAPS,QUESTIONS,query

def run():
    failures=[];total=0;counts=[]
    with tempfile.TemporaryDirectory(prefix='memory-fetch-') as folder:
        db,pins=build(folder)
        for question in QUESTIONS:
            total+=1
            try:
                a=query(db,question,'shop',AT,measure=1,capability='sample',procedure_root=folder,pins=pins)
                size=len(json.dumps(a,ensure_ascii=False).encode());counts.append(dict(question=question,queries=a['reads'],files=a['files'],rows=len(a['rows']),bytes=size))
                if a['reads']!=1 or a['files']>(1 if question=='procedure' else 0) or a['raw_files'] or len(a['rows'])>CAPS[question] or size>12000:raise ValueError('fetch budget exceeded')
            except Exception as e:failures.append(question+':'+str(e))
    from memory_eval_business import score_cases
    extra=score_cases(fetch=True)
    total+=extra['denominator'];failures.extend(extra['failures'])
    return dict(test='06-fetch',passed=not failures,numerator=total-len(failures),denominator=total,failures=failures,counts=counts+extra['counts'])
if __name__=='__main__':
    result=run();print(json.dumps(result,sort_keys=True));raise SystemExit(0 if result['passed'] else 1)
