"""Freeze1000 research composition only after complete new original50 acceptance.

This checks source conditions and hypothetical rule feasibility in memory.
It writes only an allocation/aggregate contract, never1000worlds,IDFs or EP jobs.
"""
import copy,collections,concurrent.futures,datetime as dt
from common import *
from type_model import candidates,allocate,TYPES,SEED
from worlds import build
from activity_model import dated
from plans import make_A
from checks import assess


def support_one(h):
    source=read(SOURCE/h['world_path']);assert sha(SOURCE/h['world_path'])==h['world_sha256']
    support=candidates(source);feasible=copy.deepcopy(support);problems={}
    for typ in TYPES:
        if not support['allowed'][typ]:continue
        try:
            world=build(source,typ)
            for item in world['random10_date_selection']['dates']:
                date=dt.date.fromisoformat(item['date']);ns,A,ws,initial=make_A(world,date)
                # Verify normal schedule against common contract before final
                # production. No counterfactual B or physical result is selected.
                from execution import realize
                ex=realize(world,A,ws,ns)
                if any(not x['delivered_before_given_bound']for x in ex['program_services'])or any(not x['succeeded']for x in ex['operations']):raise ValueError('normal_reference_service_or_handling')
        except Exception as e:
            feasible['allowed'][typ]=False;problems[typ]=str(e)[:250]
    return source,feasible,problems


def main():
    school_guard();accepted=read(OUT/'FINAL_ACCEPTANCE.json')
    if not accepted['new_original50_reference_acceptance_passed']:raise RuntimeError('composition hold: new original50 acceptance missing/failed')
    from finalize_pilot import verify_acceptance_inputs
    verify_acceptance_inputs(accepted)
    rows=read(SOURCE/'SELECTION1000.json')['records'];assert len(rows)==1000
    worlds=[];support=[];fail=[]
    with concurrent.futures.ProcessPoolExecutor(max_workers=24)as pool:
        for w,s,problems in pool.map(support_one,rows):
            worlds.append(w);support.append(s)
            if problems:fail.append({'household_id':w['household_id'],'unsupported_rule_candidates':problems})
    unmatched=[w['household_id']for w,s in zip(worlds,support)if not any(s['allowed'].values())]
    save(OUT/'COMPOSITION_SUPPORT1000.json',{'checked_source_households':1000,
        'support_counts':{t:sum(s['allowed'][t]for s in support)for t in TYPES},'unmatched':unmatched,
        'candidate_rule_failures':fail,'source_selection_sha256':sha(SOURCE/'SELECTION1000.json'),
        'in_memory_calendar_service_feasibility_only':True,'new1000worlds_written':0,'IDFs':0,'EP_calls':0})
    if unmatched:raise RuntimeError('composition hold: source households unclassified;no silent dropping')
    fixed=read(OUT/'TYPE_ASSIGNMENT50.json')['assignment']
    assignment,base=allocate(worlds,minimum=50,support_override=support,weighted_reference=True,fixed_assignment=fixed)
    assert all(assignment[h]==t for h,t in fixed.items())
    sensitivity=[]
    for auto in [.2,.5,.8]:
        _,report=allocate(worlds,minimum=50,auto_share=auto,support_override=support,weighted_reference=True,fixed_assignment=fixed);sensitivity.append(report)
    report={'schema':'eb.frozen_structure_constrained_type_composition.v27','reference_year':2020,
        'target_households':1000,'excluded':['town','rural','collective','nonordinary'],
        'counts':base['integer_counts'],'conditional_reference':base,'type_assignment_for_future_generation':assignment,
        'automatic_permission_split_sensitivity':sensitivity,
        'proportions_are_measured_natural_prevalence':False,
        'preference_and_type_mixture_status':'researcher_given conditional on verified source structure and rule feasibility',
        'minimum50_each_is_coverage_design_not_power_or_population_statistic':True,
        'source_structural_controls_changed':False,'original50_acceptance_sha256':sha(OUT/'FINAL_ACCEPTANCE.json'),
        'accepted_original50_type_policy_preserved':True,'original50_type_binding_sha256':sha(OUT/'TYPE_ASSIGNMENT50.json'),
        'source_selection_sha256':sha(SOURCE/'SELECTION1000.json'),'rules_seed':SEED,
        'implementation_code_sha256':{p.name:sha(p)for p in (OUT/'code').glob('*')if p.is_file()},
        'actual1000new_world_coverage_verified':False,'full1000_EP_allowed':False,
        'new1000worlds_written':0,'EP_calls':0}
    save(OUT/'FROZEN_COMPOSITION1000.json',report)
    print({k:v for k,v in report.items()if k not in ('type_assignment_for_future_generation','implementation_code_sha256','automatic_permission_split_sensitivity')},flush=True)


if __name__=='__main__':main()
