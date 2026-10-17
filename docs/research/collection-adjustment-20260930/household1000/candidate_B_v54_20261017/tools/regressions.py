"""Regression scenarios for eligible VPP actions, literal axes and causal failures."""
import sys
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *
from planning import ev_window,contexts,program_candidates,program_delta,ev_timer_options
from strengths import definitions,construct,grade_table,selected_levels
from proposals import command_signature
from actual_strength import annotate

def main():
    rows={r['household_id']:r for r in read(OUT/'PAIR_BINDINGS10000.json')['records']};source={r['household_id']:r for r in read(SOURCE_B/'PAIR_BINDINGS10000.json')['records']};tests=[]
    def case(hid,date):return read(OUT/next(r['path']for r in rows[hid]['rounds']if r['date']==date))
    p=case('ordinary-v6-0048','2025-04-02');request=next(r for r in p['proposal']['requested_device_strengths']if r['device_family']=='dishwasher');ctx=request['input_state_plan']
    up=[e for e in ctx['all_event_input_states']if e['direction']=='up'and e['start_min']==1080]
    assert up and up[0]['input_opportunity_min']==0 and all(x['release_min']>=up[0]['end_min']for x in up[0]['service_boundaries'])
    tests.append('0048_release_after_event_has_zero_eligible_up_opportunity')
    chain=[{'need_id':'n','kind':'washer','start_min':1080,'end_min':1200},{'need_id':'n:dry','kind':'dryer','start_min':1200,'end_min':1290}]
    context={'behavior':'normal_response','event':{'start_min':1140,'end_min':1260,'direction':'up','target_kw':.1},'program_service_candidates':[{'need_id':'n','chain':chain,'feasible_candidates':[{'delta_min':-60,'finish_min':1230},{'delta_min':60,'finish_min':1350}]}]}
    assert program_delta({},chain[0],60,60,context,{'washer':{'power_kw':.45},'dryer':{'power_kw':1.6}})==-60
    tests.append('washer_dryer_opportunity_and_direction_use_energy_not_unweighted_minutes')
    a={'start_min':1020,'end_min':1940,'battery_energy_kWh':2.5};param={'charger_kw':7.4,'efficiency':.92};base={'event':{'start_min':1080,'end_min':1140,'target_kw':1,'direction':'down'},'behavior':'normal_response','reserve_budget_fraction':.65,'reserve_placement':'event_start','EV_request_path':'explicit_duration_budget'}
    lo,hi=ev_window(a,param,{},3,base);assert lo==1020 and hi==1050
    tests.append('EV_A_finished_before_down_event_is_not_mechanically_shifted_into_it')
    tail={'start_min':920,'end_min':1940,'battery_energy_kWh':10};context={**base,'event':{'start_min':990,'end_min':1080,'target_kw':.5,'direction':'down'}}
    lo,hi=ev_window(tail,param,{},0,context);assert lo==1070 and hi==1940
    context['event']['direction']='up';lo,hi=ev_window(tail,param,{},0,context);assert lo==930
    tests.append('EV_normal_timer_reduces_or_adds_to_A_event_energy_instead_of_blindly_delaying_a_tail')
    tight={'start_min':1080,'end_min':1140,'battery_energy_kWh':2.5};context['event']={'start_min':1130,'end_min':1220,'target_kw':.5,'direction':'up'}
    lo,hi=ev_window(tight,param,{},0,context);assert lo==1110 and hi-lo>=2.5/(7.4*.92)*60
    tests.append('EV_opportunity_and_normal_timing_keep_required_energy_feasible_at_departure_boundary')
    metrics={'device_family':'ev','asset_ids':['e'],'program_changes':[],'manual_operation_changes':[],'control_segments':[],'EV_window_metrics':[{'A_window_min':[770,1970],'B_window_min':[950,1970],'delay_minutes':180,'B_window_slack_minutes':900,'constant_power_full_charge_minutes':120}]}
    annotate(metrics,{'parameters':{},'grade':'low'})
    assert metrics['actual_strength_axes']['window_fraction_removed']['grade']=='low'and metrics['actual_strength_axes']['start_delay_min']['grade']=='extreme'and metrics['strength_presentation']['overall_grade']is None
    tests.append('EV_3hour_delay_exposed_beside_small_window_fraction_with_no_overall_grade')
    a={'start_min':1070,'end_min':1980,'battery_energy_kWh':10};base['event'].update(start_min=1080,end_min=1110,direction='up');base['behavior']='service_pressure';shapes=[]
    for path in('explicit_duration_budget','event_only_permission','departure_anchored_postponement','event_end_cutoff'):
        lo,hi=ev_window(a,param,{},0,{**base,'EV_request_path':path});shapes.append((lo,hi));assert a['start_min']<=lo<hi<=a['end_min']
    assert len(set(shapes))==4 and shapes[1]==(1080,1110) and shapes[2][1]==1980 and shapes[3]==(1070,1110)
    tests.append('four_EV_request_paths_have_distinct_input_anchors_and_real_connection_bounds')
    late={'start_min':1160,'end_min':1940,'battery_energy_kWh':10}
    assert ev_window(late,param,{},0,{**base,'EV_request_path':'event_end_cutoff'})==(1880,1940)
    tests.append('expired_event_cutoff_uses_departure_budget_instead_of_clamping_to10min')
    lens=[]
    for fraction in(.4,.65,.85,.95,1.05,1.25,1.5):
        lo,hi=ev_window(a,param,{},2,{**base,'EV_request_path':'explicit_duration_budget','reserve_budget_fraction':fraction});lens.append(hi-lo)
    assert len(set(lens))>=6 and min(lens)>10 and max(lens)>10/(7.4*.92)*60
    tests.append('duration_budgets_retain_both_sufficient_and_short_windows_without_fixed10min_template')
    p=case('ordinary-v6-0006','2025-06-16')
    for req in p['proposal']['requested_device_strengths']:
        if req['device_family']in('ac','water_heater'):
            ctx=req['input_state_plan'];st=ctx['event']['native_A_event_state'];assert st['status']=='native_A_reference'and st['mode']in('heating','cooling','mixed','idle')and not st['physical_B_effect_known']
            assert not ctx['thermal_axis_basis'].startswith('given_daily')
    tests.append('0006_thermal_axis_from_native_event_state_with_idle_and_scope_explicit')
    for fam,dur,wanted in [('washer',120,[30,60,120,240]),('dishwasher',90,[30,50,90,180])]:assert [grade_table(fam,i,{'parameters':{'duration_h':dur/60},'types':[fam]})['requested_shift_min']for i in range(4)]==wanted
    tests.append('program_doses_use_each_native_cycle_duration')
    old=read(SOURCE_B/next(r['path']for r in source['ordinary-v6-0001']['rounds']if r['date']=='2025-03-22'));world=read(A_STAGE/old['A_source']['world_path']);defs=definitions(world,old);modified=copy.deepcopy(old);modified['proposal']['level']='extreme'
    assert construct(world,old,defs)==construct(world,modified,definitions(world,modified))
    tests.append('legacy_overall_grade_has_no_effect_on_new_B')
    for key in defs:
        changed=copy.deepcopy(defs);changed[key]['base_grade_index']=(changed[key]['base_grade_index']+1)%4
        assert all(selected_levels(defs)[k]==selected_levels(changed)[k]for k in defs if k!=key)
    tests.append('controller_input_doses_independent_between_devices')
    for r in p['B']['controls']:
        if r['kind']=='ac_setpoint':assert r['cooling_setpoint_C']-r['heating_setpoint_C']>=2
    tests.append('actual_AC_dual_setpoints_keep_native_2C_deadband')
    a=read(OUT/'ACCEPTANCE.json');d=read(OUT/'DESIGN_REVIEW.json');st=read(OUT/'STATE_BINDINGS.json');tv=read(OUT/'THERMAL_EVENT_VALIDATION.json');memo=read(OUT/'NATIVE_COMPILER_REGRESSIONS.json')
    assert a['accepted']and not a['errors']and a['counts']['same100_payload_preserved']==100 and a['counts']['candidate_integrity_checks']==40000 and a['subset50_type_counts']=={'A':5,'B':15,'C':16,'D':5,'E':4,'F':5}
    tests.append('whole10000_fixed100_daily_needs_action_IDs_and_same_source50_retained')
    assert d['normal_or_partial_EV_selected_event_reference_relations'].get('opposing',0)==0
    tests.append('ordinary_EV_selected_event_fixed_reference_has_no_known_reverse_spill_from_timer_formula')
    assert d['passed']and sum(d['EV_path_shortfall_counts'].values())>0 and sum(v>0 for v in d['EV_path_shortfall_counts'].values())>=3
    tests.append('population_EV_shortfalls_arise_from_at_least_three_real_request_paths_without_failure_filter')
    assert st['passed']and st['cases']==10000 and tv['passed']and memo['passed']and not tv['full_AB_physical_acceptance']
    tests.append('whole_A_native_states_and_predeclared_paired_B_readbacks_have_matching_scoped_inputs')
    save(OUT/'REGRESSION_RESULTS.json',{'passed':True,'count':len(tests),'tests':tests,'rules_sha256':rules_id()});print({'passed':True,'tests':tests})
if __name__=='__main__':main()
