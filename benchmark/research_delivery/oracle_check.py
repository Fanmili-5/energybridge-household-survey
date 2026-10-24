"""Production CP oracle checked against independent actual-device equations."""
import itertools
from pathlib import Path
from benchmark.ab_generation.common import digest,save
from benchmark.ab_generation.unified.exhaustive import fixtures
from benchmark.ab_generation.unified.candidates import Oracle
from benchmark.ab_generation.unified.contract import config
from benchmark.ab_generation.unified.ipog import generate


def run():
    contexts={}
    for name,c,b,truth in fixtures():contexts.setdefault(name,c)
    mismatches=[];details=[]
    for name,c in contexts.items():
        if name=='midnight_transfer':continue  # separate window test; no 18-19 path
        values=[]
        for task in c['A']['tasks']:
            nid=task['need_id'];ops=[o for o in c['A']['operations'] if o['need_id']==nid];vs=[None]
            for delta in (-20,20):
                changed=[{**task,'start_min':task['start_min']+delta,'end_min':task['end_min']+delta}]
                moved=[{**o,'start_min':o['start_min']+delta,'end_min':o['end_min']+delta} for o in ops]
                patches=[dict(type='rows',collection='tasks',identity='task_id',rows=changed),dict(type='rows',collection='operations',identity='operation_id',rows=moved)]
                vs.append(dict(id=digest(patches),unit=nid,family=task['kind'],asset_id=task['asset_id'],service_need_id=nid,
                    mechanism='shift_chain',relative_level='small_relative',absolute_level='small',patches=patches,
                    needs=[nid]+([task['depends_on_need_id']] if task.get('depends_on_need_id') else []),
                    profiles={'A':[task],'B':changed},known_event_reduction_kWh=0,unknown_thermal_response=False,
                    magnitude=dict(machine_shift_min=20,signed_machine_shift_min=delta,manual_total_shift_min=40,
                        manual_max_shift_min=20,service_slack_min=1920-moved[-1]['end_min'],dose_coordinate=20)))
            values.append(vs)
        g=dict(values=values,descriptors=[[dict(label=str(i),ids=[i]) for i in range(3)] for _ in range(2)],domains=[[0,1,2]]*2)
        oracle=Oracle(c,g,config({'rows_per_unit':100,'queries_per_row':20,'oracle_deterministic_time':1}),None)
        correct=[]
        for x in itertools.product(range(3),repeat=2):
            delta=[(0,-20,20)[i] for i in x]
            expected=any(x) and 1080+20+delta[0]+10<=1080+40+delta[1]-10
            status,witness,reason=oracle(dict(enumerate(x)))
            if status!=('feasible' if expected else 'infeasible'):
                mismatches.append(dict(fixture=name,assignment=list(x),expected=expected,status=status,reason=reason))
            if expected:correct.append(list(x))
        generated=generate(g['domains'],oracle)
        for t in generated['coverage']:
            expected=any(all(x[i]==v for i,v in t['target']) for x in correct)
            if expected!=(t['witness_row'] is not None):mismatches.append(dict(fixture=name,coverage=t,expected=expected))
        details.append(dict(fixture=name,assignments=9,independent_valid=sum(1 for _ in correct),
            oracle_queries=oracle.calls,complete=generated['complete']))
    return dict(passed=not mismatches,actual_production_oracle=True,assignment_cases=sum(r['assignments'] for r in details),
                details=details,mismatches=mismatches,scope='finite real-device fixture domain with explicit event relevance;not_all_physical_space')


if __name__=='__main__':
    import sys
    result=run();save(Path(sys.argv[1]),result);print(result)
