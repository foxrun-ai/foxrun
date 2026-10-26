#!/usr/bin/env python3
"""Run memory evals. Default is score only; --write records measurements through the table writer after migration."""
import argparse,importlib.util,json,sqlite3,sys
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))

EVALS=('01_rule.py','02_read.py','03_reliability.py','04_code_first.py','05_trace.py','06_fetch.py','07_triangulate.py','08_field.py','09_portability.py','10_night_shift.py','11_seven_nights.py')
def names():return EVALS

def run():
    result=[]
    for name in names():
        try:
            spec=importlib.util.spec_from_file_location(name[:-3],ROOT/name);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);result.append(module.run())
        except Exception as error:
            result.append(dict(test=name[:2]+'-dispatch',passed=False,numerator=0,denominator=1,failures=[name+': '+type(error).__name__+': '+str(error)[:160]]))
    return result

def record(database,workspace,actor,session,results,system=None):
    database=Path(database).resolve()
    with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as con:
        columns={r[1] for r in con.execute('pragma table_info(work_measure_history)')}
        if not {'id','workspace','measure','as_of','recorded_at','run','value','note'}<=columns:
            raise ValueError('migrated measure tables are absent; old tracker remains unchanged')
    system=Path(system or ROOT.parents[1]);sys.path.insert(0,str(system/'base'))
    from core import execute,connect
    blueprint=system/'base/blueprint'
    at=datetime.now(timezone.utc).isoformat();ctx=dict(writer='agent',actor=actor,session=session,workspace=workspace)
    for row in results:
        number='EV-MEM-'+row['test'].split('-')[0]
        with connect(database,readonly=True) as con:
            prior=con.execute('SELECT id,unit FROM work_measures WHERE workspace=? AND number=?',(workspace,number)).fetchone()
        if prior and prior['unit']!='fraction':raise ValueError('measure unit differs')
        measure=prior['id'] if prior else execute(database,blueprint,'work_measures','insert',dict(workspace=workspace,number=number,name='Memory '+row['test'],unit='fraction'),None,ctx)['id']
        payload=dict(workspace=workspace,measure=measure,as_of=at,value=row['numerator']/row['denominator'] if row['denominator'] else 0,note=json.dumps(row,sort_keys=True))
        identity=execute(database,blueprint,'work_measure_history','insert',payload,None,ctx)['id']
        with connect(database,readonly=True) as con:
            found=con.execute('SELECT value,note FROM work_measure_history WHERE id=?',(identity,)).fetchone()
        if found['value']!=payload['value'] or found['note']!=payload['note']:raise ValueError('measure readback differs')
    return len(results)

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--write',action='store_true');parser.add_argument('--db');parser.add_argument('--workspace');parser.add_argument('--actor');parser.add_argument('--session');a=parser.parse_args()
    results=run();print(json.dumps(results,sort_keys=True))
    if a.write:
        if not all((a.db,a.workspace,a.actor,a.session)):parser.error('--write needs --db --workspace --actor --session')
        print('recorded '+str(record(a.db,a.workspace,a.actor,a.session,results))+' work_measure_history rows')
    return 0 if all(r['passed'] for r in results) else 1
if __name__=='__main__':raise SystemExit(main())
