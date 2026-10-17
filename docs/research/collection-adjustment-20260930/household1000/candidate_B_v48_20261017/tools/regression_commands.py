"""Regress the reported false differences against unchanged real inputs, plus VPP factors."""
import sys,collections
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *
from proposals import command_signature
from executable import commands
from event_proposals import make,thermal,eligible
from thermal_flex import make_preconditioning
from temporal import event_relations
from events import for_case

def main():
    old=BASE/'candidate_B_v47_20261017';findings=read(OUT/'trials/B47_readonly_findings.json');fixed=[]
    def fixture(x):
        p=read(old/x['path']);w=read(A_STAGE/p['A_source']['world_path']);c=read(A_STAGE/p['A_source']['case_path']);c['VPP_events']=p['VPP_events'];c['input_design_assignment']=p['proposal']['input_design_assignment'];return w,c,p
    for x in findings['false_difference_cases']:
        w,c,p=fixture(x)
        for index in range(4):
            plan,q=make(w,c,index)
            assert command_signature(plan)==command_signature(c['A'])
            assert q['actual_command_intensity']=='unchanged'
            assert q['same_command_as_A']and q['actual_unique_dose_count']==1 and q['equivalent_design_levels']==LEVELS and q['portfolio_families']==[]
            assert all(ch['control_action_direction']=='unchanged'and not ch['deliberate_reverse_direction']for ch in q['changes'])
        fixed.append(c['case_id'])
    preparation_tests=0
    for x in findings['zero_preparation_requests']:
        w,c,p=fixture(x);e=next(e for e in c['VPP_events']if e['event_id']==x['change']['selected_event_id']);level=LEVELS.index(p['proposal']['intensity_design']);plan=copy.deepcopy(c['A']);ch=make_preconditioning(plan,w,c,e,level)
        z=ch['preconditioning'];phase=z['phases'][0]
        assert not z['preparation_command_changed']and not phase['is_actual_command_change']and phase['control_action_direction']=='unchanged'
        assert not any(phase['actual_minutes_by_asset'].values())and not any(phase['A_permission_added_minutes_by_asset'].values())
        assert commands(plan,end=e['start_min'])==commands(c['A'],end=e['start_min'])
        assert event_relations(c,plan,[e])[0]['requested_command_relation']=='first_changes_during_event'
        preparation_tests+=1
    # Same physical request, arbitrarily resegmented/reordered/relabelled records.
    w,c,_=fixture(findings['false_difference_cases'][0]);split=copy.deepcopy(c['A']);xs=[]
    for x in split['controls']:
        xs.extend([{**x,'start_min':t,'end_min':min(t+10,x['end_min']),'need_id':'representation:'+str(t)}for t in range(x['start_min'],x['end_min'],10)]if x['kind']=='ac_setpoint'else[x])
    split['controls']=list(reversed(xs));split['tasks'].reverse();split['operations'].reverse()
    assert command_signature(split)==command_signature(c['A'])
    changed=copy.deepcopy(split);ac=next(x for x in changed['controls']if x['kind']=='ac_setpoint');ac['cooling_setpoint_C']+=.25
    assert command_signature(changed)!=command_signature(split)
    fan=copy.deepcopy(split);ac=next(x for x in fan['controls']if x['kind']=='ac_setpoint');ac['fan_operating_mode']=1-ac['fan_operating_mode']
    assert command_signature(fan)!=command_signature(split)
    gap=copy.deepcopy(split);gap['controls'].remove(next(x for x in gap['controls']if x['kind']=='ac_setpoint'))
    assert command_signature(gap)!=command_signature(split)
    for kind,values,changedkey in [('ev_charge_window',{'stop_at_target_soc':.85},'stop_at_target_soc'),('tank_setpoint',{'value_C':60.},'value_C')]:
        p={'tasks':[],'operations':[],'controls':[{'kind':kind,'asset_id':'x','start_min':600,'end_min':660,**values}]};q=copy.deepcopy(p)
        q['controls'][0].update(battery_energy_kWh=99,actual_charge_end_min=630,need_id='other',projection_basis='not a command')
        assert command_signature(p)==command_signature(q)
        q['controls'][0][changedkey]+=.1;assert command_signature(p)!=command_signature(q)
    try:commands({'tasks':[],'operations':[],'controls':[{'kind':'unregistered','asset_id':'x','start_min':0,'end_min':10}]})
    except ValueError:pass
    else:raise AssertionError('unknown control silently dropped')
    # Many dates of a fixed station exercise independent direction and goal factors;
    # calendar date and station only, regardless of assets, IDs, A or answers.
    basecase=copy.deepcopy(c);original=copy.deepcopy(w);shapes=collections.Counter()
    for day in range(365):
        z={'date':str(dt.date(2025,1,1)+dt.timedelta(days=day))};evs=for_case(original,z)
        other=copy.deepcopy(original);other.update(household_id='different',members=[],parameter_pack={},human_answers={'anything':True});alt={**z,'A':{'nonsense':True},'B':{'arbitrary':True},'human_response':True}
        assert evs==for_case(other,alt)
        if len(evs)>1:shapes[('mixed'if len({e['direction']for e in evs})>1 else'same','unequal'if len({e['target_kw']for e in evs})>1 else'equal')]+=1
    assert set(shapes)=={(a,b)for a in ['same','mixed']for b in ['equal','unequal']}
    report={'passed':True,'rules_sha256':rules_id(),'reported13_cases_all_four_doses_equal_A':fixed,'zero_preparation_requests_corrected':preparation_tests,'normalization_invariant_to_splitting_order_IDs':True,'actual_setpoint_fan_gap_EV_target_tank_target_changes_detected':True,'unknown_control_kind_rejected':True,'zero_preparation_chronology_starts_during_event':True,'station_date_only_VPP_independent_of_household_and_outcomes':True,'VPP_factor_fixture_counts':{'+'.join(k):v for k,v in shapes.items()},'B47_input_fixture_preserved':True,'physical_success_or_acceptance_filter':False}
    save(OUT/'COMMAND_REGRESSION.json',report);print(canonical(report))
if __name__=='__main__':main()
