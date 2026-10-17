"""Review actual coverage, chronology, and narrative/data correspondence across all pairs."""
import sys,collections
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *
from temporal import event_relations
from event_proposals import tank,mechanism_eligibility

def main():
    rows=read(OUT/'PAIR_BINDINGS10000.json')['records'];inputplan=read(OUT/'INPUT_COVERAGE_PLAN.json');bad=[];counts=collections.Counter();relations=collections.Counter();combos=collections.Counter();examples={}
    for r in rows:
        wanted_coordinated=0
        for rr in r['rounds']:
            p=read(OUT/rr['path']);q=p['proposal'];assignment=inputplan['assignments'][p['case_id']];wanted_coordinated+=assignment['mechanism']=='coordinated';counts['cases']+=1
            acase=read(A_STAGE/p['A_source']['case_path'])
            if not mechanism_eligibility(acase)[assignment['mechanism']]or q['fallback_reason']or q['requested_mechanism']!=q['realized_mechanism']:bad.append([p['case_id'],'UNAVAILABLE_MECHANISM_OR_FALLBACK'])
            policy=q['multi_event_policy'];counts['policy_'+policy]+=1
            if policy=='joint_all_events'and set(q['joint_event_ids_considered'])!={e['event_id']for e in p['VPP_events']}:bad.append([p['case_id'],'JOINT_EVENT_OMITTED'])
            if len(p['VPP_events'])>1:
                ref=p['VPP_response_reference']['events'];focus_ref=next(x for x in ref if x['event_id']==q['focus_VPP_event_id'])
                others=[x for x in ref if x['event_id']!=q['focus_VPP_event_id']]
                if focus_ref['requested_known_response_average_kw']>1e-8 and any(x['requested_known_response_average_kw']<-1e-8 for x in others):counts['known_focus_positive_other_negative_'+policy]+=1
            if q['input_design_assignment']!=assignment or assignment['selection_used_B_results']:bad.append([p['case_id'],'INPUT_ASSIGNMENT_CHANGED'])
            for e in p['event_relations']:relations[e['requested_command_relation']]+=1
            focus=next(x for x in p['event_relations']if x['event_id']==q['focus_VPP_event_id']);counts['focus_'+focus['requested_command_relation']]+=1
            if q['same_command_as_A']and focus['requested_command_relation']!='no_command_change':bad.append([p['case_id'],'NO_OP_NOT_REPORTED'])
            for ch in q['changes']:
                if ch['device_family']=='ac':
                    counts['thermal_changes_with_no_mode_guess']+=1
                    if ch['thermal_direction_basis']!='dual_thermostat_bounds;no_outdoor_mode_guess'or ch['response_status']!='uncertain_pending_physics':bad.append([p['case_id'],'UNSUPPORTED_THERMAL_DIRECTION_CLAIM'])
                    if ch['effective_request_direction']=='up'and(ch['heating_delta_C']<0 or ch['cooling_delta_C']>0):bad.append([p['case_id'],'UP_CONTROL_BOUND_DIRECTION_REVERSED'])
                    if ch['effective_request_direction']=='down'and(ch['heating_delta_C']>0 or ch['cooling_delta_C']<0):bad.append([p['case_id'],'DOWN_CONTROL_BOUND_DIRECTION_REVERSED'])
                if ch['device_family']=='water_heater':
                    counts['tank_descriptions']+=1
                    if any(s in ch['description']for s in('事件内启动储水加热','事件前预热、事件后恢复')):bad.append([p['case_id'],'UNCONDITIONAL_TANK_PROMISE'])
                    if '修改后加热许可为'not in ch['description']or'实际加热与供水待仿真'not in ch['description']:bad.append([p['case_id'],'TANK_DESCRIPTION_INCOMPLETE'])
            if q['realized_mechanism']=='coordinated':
                key='+'.join(q['portfolio_families']);combos[key]+=1
                if len(q['portfolio_families'])>=2:examples.setdefault(key,{'case_id':p['case_id'],'path':rr['path'],'sha256':rr['sha256']})
            if p['needs_A']!=p['needs_B']or any(v is not None for v in p['human_response'].values()):bad.append([p['case_id'],'NEEDS_OR_HUMAN_LABELS_CHANGED'])
        if wanted_coordinated!=2:bad.append([r['household_id'],'INPUT_PORTFOLIO_SLOTS_NOT_TWO'])
    # The old out-of-event hot-water narrative error is caught by a literal interval fixture.
    old={'kind':'tank_setpoint','asset_id':'tank','start_min':950,'end_min':1180,'value_C':60.0};plan={'controls':[copy.deepcopy(old)],'tasks':[],'operations':[]}
    c={'case_id':'toy'};e={'start_min':1200,'end_min':1260,'direction':'up'};change=tank(plan,{},c,[old],e,3)
    assert change['segments_B_min']==[[1170,1180]]and'不与事件重叠'in change['description']and'事件内启动储水加热'not in change['description']
    a={'controls':[],'operations':[],'tasks':[{'kind':'washer','asset_id':'x','need_id':'n','start_min':1300,'end_min':1420}]};b=copy.deepcopy(a);b['tasks'][0].update(start_min=1310,end_min=1430)
    toy=event_relations({'A':a},b,[{'event_id':'x','start_min':1080,'end_min':1140}]);assert toy[0]['requested_command_relation']=='only_after_event'
    sparse={k:v for k,v in combos.items()if'+'in k and v<10}
    report={'accepted':not bad and counts['cases']==10000,'counts':dict(counts),'errors':bad,'actual_coordinated_portfolio_counts':dict(combos),'requested_portfolio_counts':inputplan['requested_portfolio_counts'],'event_chronology_counts':dict(relations),'sparse_actual_combinations_below10':sparse,'minimum_actual_pair_cell':min((v for k,v in combos.items()if k.count('+')==1),default=0),'minimum_actual_triple_cell':min((v for k,v in combos.items()if k.count('+')==2),default=0),'input_plan_sha256':sha(OUT/'INPUT_COVERAGE_PLAN.json'),'wrong_hotwater_narrative_regression_passed':True,'late_response_classification_regression_passed':True,'actual_physical_success_or_human_labels_generated':False,'full_physical_acceptance':False}
    save(OUT/'DESIGN_REVIEW.json',report);save(OUT/'review/实际跨设备组合示例.json',examples);print(canonical(report))
    if not report['accepted']:raise SystemExit(2)
    import runpy
    runpy.run_path(str(OUT/'tools/review_four_points.py'),run_name='__main__')
if __name__=='__main__':main()
