#!/usr/bin/env python3
"""Schema, meaningful rejection checks, residuals and precise resource counts."""
import argparse, collections as C, copy, json, time
from pathlib import Path
from verify_smallbatch import read,sha,check_schedule

HERE=Path(__file__).resolve().parent

def main(batch,report):
    start=time.monotonic()
    import jsonschema
    schema=read(HERE/'SCHEMA.json');jsonschema.Draft202012Validator.check_schema(schema)
    pv=jsonschema.Draft202012Validator(schema)
    tv=jsonschema.Draft202012Validator({'$ref':'#/$defs/task','$defs':schema['$defs']})
    mv=jsonschema.Draft202012Validator({'$ref':'#/$defs/material_source','$defs':schema['$defs']})
    profiles=[read(p) for p in sorted((batch/'mapped_old300').glob('*.json'))]
    cases=sorted((batch/'cases').iterdir());new=[read(p/'profile.json') for p in cases]
    for p in profiles+new:pv.validate(p)
    task_count=material_count=evals=unserved=0;known_false=0
    for p in profiles:
        for a in p['assets']:
            if a.get('control_scope_design')=='none_for_ours':
                assert a['controllable_design'] is False;known_false+=1
    for folder in cases:
        A=read(folder/'A.json');B=read(folder/'B.json')
        for t in A['tasks']:tv.validate(t)
        for m in A['material_sources']:mv.validate(m)
        task_count+=len(A['tasks']);material_count+=len(A['material_sources']);evals+=B['candidate_evaluations']
        unserved+=sum(s.get('unserved_trip_demand_kWh_design',0) for s in A['states'])
    p=read(cases[0]/'profile.json');A=read(cases[0]/'A.json');negative={}
    t=copy.deepcopy(A['tasks']);dryer=next(ti for ti in t if ti['device_class']=='dryer');dep=next(ti for ti in t if ti['task_id']==dryer['predecessor_task_ids'][0]);dryer['start_abs_min']=dep['start_abs_min']
    negative['dryer_before_wet_batch']=bool(check_schedule(p,t,A['material_sources']))
    mats=copy.deepcopy(A['material_sources']);mats[0]['available_abs_min']=10**9
    negative['dirty_batch_not_released']=bool(check_schedule(p,A['tasks'],mats))
    t=copy.deepcopy(A['tasks']);ev=next(ti for ti in t if ti['device_class']=='home_ev');ev['start_abs_min']=ev['next_departure_abs_min']
    negative['EV_after_departure']=bool(check_schedule(p,t,A['material_sources']))
    q=copy.deepcopy(p);next(a for a in q['assets'] if a['device_class']=='washer')['accessible_design']=None
    negative['unknown_asset_access']=bool(check_schedule(q,A['tasks'],A['material_sources']))
    q=copy.deepcopy(p)
    for m in q['members']:m['weekday_home_windows_min']=[];m['weekend_home_windows_min']=[]
    negative['operator_absent']=bool(check_schedule(q,A['tasks'],A['material_sources']))
    assert all(negative.values())
    selection=read(batch/'SELECTION_BIAS.json');residual={}
    for k in ['H7','generation','province','size']:
        b=selection['before'][k];a=selection['after'][k];residual[k]={key:a.get(key,0)-b.get(key,0) for key in set(a)|set(b)}
        assert not any(residual[k].values())
    assert selection['before']['elder_households']==selection['after']['elder_households']
    qualified=selection['qualified_profile_subset'];qualified_residual={k:{key:qualified[k].get(key,0)-selection['before'][k].get(key,0) for key in set(qualified[k])|set(selection['before'][k])} for k in ['H7','generation','province','size']}
    unknown_households=sum(any(m['weekday_home_windows_min'] is None or m['weekend_home_windows_min'] is None for m in p['members']) for p in profiles)
    unknown_members=sum(m['weekday_home_windows_min'] is None or m['weekend_home_windows_min'] is None for p in profiles for m in p['members'])
    # Same age definitions, both compared routes. No 1000 regenerated here.
    priornew=[read(f)['profile'] for f in sorted((HERE.parent/'candidate_v2/roles').glob('*.json')) if int(f.stem.split('-')[1])>300]
    elder={str(age):{'old300':sum(any(m['age_design']>=age for m in p['members']) for p in profiles),
        'prior_new700':sum(any(m['age_years_design']>=age for m in p['members']) for p in priornew)} for age in [60,65]}
    result={'batch_id':read(batch/'SUMMARY.json')['batch_id'],'pass':True,'profile_schema_checked':len(profiles)+len(new),
        'task_schema_checked':task_count,'material_schema_checked':material_count,'known_false_control_assets_preserved':known_false,
        'old300_unknown_window_households':unknown_households,'old300_unknown_window_members':unknown_members,'elder_age_definitions':elder,
        'negative_cases_rejected':negative,'all_case_marginal_residuals':residual,'qualified_subset_residuals':qualified_residual,
        'qualified_subset_elder65_residual':qualified['elder_households']-selection['before']['elder_households'],
        'total_B_candidate_evaluations':evals,'unserved_trip_demand_kWh_design':unserved,
        'batch_bytes':sum(p.stat().st_size for p in batch.rglob('*') if p.is_file()),'physics_engine_calls':0,
        'schema_sha256':sha(HERE/'SCHEMA.json'),'checker_sha256':sha(__file__),'wall_seconds':round(time.monotonic()-start,3)}
    assert report.resolve().is_relative_to(HERE)
    with report.open('x') as f:json.dump(result,f,ensure_ascii=False,sort_keys=True,indent=2);f.write('\n')
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('batch',type=Path);ap.add_argument('--report',type=Path,required=True);a=ap.parse_args();main(a.batch,a.report)
