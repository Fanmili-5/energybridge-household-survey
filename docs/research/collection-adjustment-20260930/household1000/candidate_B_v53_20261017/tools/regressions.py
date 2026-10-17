"""Behavior regressions protect raw magnitude grading and state-aware construction."""
import sys
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *
from strengths import definitions,construct,grade_table,selected_levels
from planning import ev_window,contexts
from actual_strength import annotate
from proposals import command_signature

def main():
    tests=[];rows=read(OUT/'PAIR_BINDINGS10000.json')['records'];sources={r['household_id']:r for r in read(SOURCE_B/'PAIR_BINDINGS10000.json')['records']}
    def case(hid,date):
        rr=next(x for x in next(r for r in rows if r['household_id']==hid)['rounds']if x['date']==date)
        return read(OUT/rr['path'])
    p=case('ordinary-v6-0001','2025-03-22');ac=next(x for x in p['proposal']['actual_device_strengths']if x['device_family']=='ac')
    assert ac['actual_strength_axes']['setpoint_delta_C']['value']==1 and ac['actual_primary_grade']=='medium'
    for x in p['B']['controls']:
        if x['kind']=='ac_setpoint':assert x['cooling_setpoint_C']-x['heating_setpoint_C']>=2
    tests.append('0001_March22_primary_AC_1C_request_is_real_1C_and_keeps_2C_deadband')
    fake={'device_family':'dishwasher','asset_ids':['d'],'program_changes':[{'start_shift_minutes':-20}],'manual_operation_changes':[],'control_segments':[],'EV_window_metrics':[]}
    annotate(fake,{'parameters':{'program_duration_min':90},'grade':'extreme'})
    assert fake['actual_primary_grade']=='low' and fake['actual_primary_value']==20
    tests.append('nominal_extreme20min_program_request_is_classified_as_actual_low')
    for fam,duration,expected in [('washer',120,[30,60,120,240]),('dishwasher',90,[30,50,90,180])]:
        assert [grade_table(fam,i,{'parameters':{'duration_h':duration/60},'types':[fam]})['requested_shift_min']for i in range(4)]==expected
    tests.append('program_native_doses_use_own_noninterruptible_duration')
    p=case('ordinary-v6-0002','2025-05-15');evening=p['classification']['actual_actions']['events'][1]['EV_event_state_reference']['devices'][0]
    assert 0<evening['power_delta_kw']<2 and evening['response_relation']=='aligned'
    tests.append('0002_May15_EV_actual_fixed_charge_overlaps_up_event_instead_of_midnight_only')
    # All four draft grades can receive different independent reserve budgets;
    # a pressure request can leave energy either short or sufficient.
    a={'start_min':780,'end_min':1980,'battery_energy_kWh':10};params={'charger_kw':7.4,'efficiency':.92};base={'behavior':'service_pressure','event':{'start_min':1080,'end_min':1140,'target_kw':2,'direction':'up'},'reserve_placement':'event_start'}
    windows=[]
    for grade in range(4):
        for fraction in(.4,.65,.85,.95,1.05,1.25,1.5):
            lo,hi=ev_window(a,params,{},grade,{**base,'reserve_budget_fraction':fraction});windows.append(hi-lo)
    assert len(set(windows))>=6 and min(windows)>10 and max(windows)>10/(7.4*.92)*60
    tests.append('EV_pressure_uses_varied_required_time_budgets_and_is_not_tied_to_draft_grade_or10min')
    p=case('ordinary-v6-0001','2025-03-22');r=next(x for x in sources[p['household_id']]['rounds']if x['date']==p['date']);old=read(SOURCE_B/r['path']);w=read(A_STAGE/old['A_source']['world_path']);defs=definitions(w,old)
    changed=copy.deepcopy(old);changed['proposal']['requested_level']='extreme';changed['proposal']['level']='low'
    assert construct(w,old,defs)==construct(w,changed,definitions(w,changed))
    tests.append('legacy_scalar_fields_do_not_change_B_requests')
    chain_source=copy.deepcopy(old)
    wash=next(x for x in old['A']['tasks']if x['kind']=='washer'and x['start_min']>=480)
    event=copy.deepcopy(old['VPP_events'][0]);event.update(start_min=wash['end_min']+10,end_min=wash['end_min']+40,duration_minutes=30)
    chain_source['VPP_events']=[event];ct=contexts(w,chain_source,defs)
    wk=next(k for k in defs if k.startswith('washer:'))
    assert ct[wk]['event']['linked_automatic_dryer_included'] and ct[wk]['event']['A_fixed_program_overlap_min']==30
    tests.append('automatic_dryer_only_event_is_visible_to_whole_chain_state_planner')
    if defs:
        key=next(iter(defs));other=copy.deepcopy(defs);other[key]['base_grade_index']=(other[key]['base_grade_index']+1)%4
        assert all(selected_levels(defs)[k]==selected_levels(other)[k]for k in defs if k!=key)
    tests.append('draft_grade_assignment_is_independent_between_controllers')
    a=read(OUT/'ACCEPTANCE.json');assert a['accepted'] and not a['errors'] and a['counts']['same100_payload_preserved']==100 and a['counts']['candidate_integrity_checks']==40000
    assert a['counts']['constraint_conflict_cases']>0 and a['counts']['negative_EV_window_slack_requests_kept']>0
    tests.append('whole_population_keeps_fixed100_and_failed_requests_without_case_filtering')
    ev=a['EV_failures_by_draft_grade'];assert sum(v for k,v in ev.items()if "'extreme', False"in k)>0 and sum(v for k,v in ev.items()if "'extreme', True"in k)>0
    tests.append('extreme_EV_draft_grade_does_not_deterministically_imply_energy_failure')
    save(OUT/'REGRESSION_RESULTS.json',{'passed':True,'count':len(tests),'tests':tests,'rules_sha256':rules_id()});print({'passed':True,'tests':tests})

if __name__=='__main__':main()
