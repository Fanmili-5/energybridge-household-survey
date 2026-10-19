"""Check the sixty frozen baseline plans without changing A or running an engine."""
import argparse
from pathlib import Path
from benchmark.ab_generation.common import read,save,verify
from benchmark.ab_generation.model import program_issues,control_issues
from benchmark.ab_generation.power import site_capacity


def audit(root):
    root=Path(root);verify(root);records=[]
    for path in sorted((root/'contexts').glob('*.json.gz')):
        c=read(path);needs={t['need_id'] for t in c['A']['tasks'] if c['decision_min']<=t['start_min']<1440}
        checked=[n for n in c['needs'] if n['need_id'] in needs and n['kind'] in ('washer','dishwasher','dryer')]
        failures=set(control_issues(c,c['A']))
        for n in checked:failures.update(program_issues(c,c['A'],n['need_id']))
        records.append({'case_id':c['case_id'],'programs_checked':len(checked),'issues':sorted(failures),
                        'power_status':site_capacity(c,c['A'])['status']})
    return {'passed':all(not r['issues'] for r in records),'cases':len(records),'records':records,
        'A_changed':False,'new_engine_runs':0,
        'scope':'baseline_A_plan_constraints;power_envelope_reported_separately;not_physical_validity'}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    result=audit(a.root);save(a.out,result);print({k:v for k,v in result.items() if k!='records'})
    if not result['passed']:raise SystemExit(1)
