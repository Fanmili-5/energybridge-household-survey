"""Device-native grades drive executable requests without outcome selection."""
import sys
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *
from strengths import definitions,construct,selected_levels,grade_table
from generate import rebuild
from proposals import command_signature

def main():
    rows=read(SOURCE_B/'PAIR_BINDINGS10000.json')['records'];tests=[];fixtures={}
    for row in rows:
        for rr in row['rounds']:
            old=read(SOURCE_B/rr['path']);w=read(A_STAGE/old['A_source']['world_path']);defs=definitions(w,old)
            if len(defs)>1 and 'multi'not in fixtures:fixtures['multi']=(w,old,defs)
            if not defs and 'same'not in fixtures:fixtures['same']=(w,old,defs)
            if old['case_id']=='ordinary-v6-0145__2025-07-08':fixtures['fallback']=(w,old,defs)
            if len(fixtures)==3:break
        if len(fixtures)==3:break
    w,old,defs=fixtures['multi'];baseline=construct(w,old,defs)
    mutation=copy.deepcopy(old)
    mutation['proposal'].update(level='extreme',requested_level='extreme',design_level='extreme',effective_level='low',actual_command_intensity='extreme')
    mutation['classification']['design_intent'].update(requested_level='low',design_level='extreme')
    assert definitions(w,mutation)==defs and construct(w,mutation,definitions(w,mutation))==baseline
    tests.append('mutating_legacy_global_strength_does_not_change_device_grades_or_B_commands')
    first=next(iter(defs));changed=copy.deepcopy(defs);changed[first]['base_grade_index']=(changed[first]['base_grade_index']+1)%4
    levels=selected_levels(defs);newlevels=selected_levels(changed)
    assert all(newlevels[k]==v for k,v in levels.items()if k!=first) and newlevels[first]!=levels[first]
    tests.append('changing_one_device_grade_does_not_change_other_device_grades')
    for fam,duration,expected in [('washer',120,[30,60,120,240]),('dishwasher',90,[30,50,90,180])]:
        d={'types':[fam],'parameters':{'duration_h':duration/60}}
        assert [grade_table(fam,i,d)['requested_shift_min']for i in range(4)]==expected
    tests.append('washer_and_dishwasher_use_their_own_noninterruptible_program_duration')
    ac={'types':['ac'],'parameters':{}};tank={'types':['water_heater'],'parameters':{'maximum_C':65}}
    assert [grade_table('ac',i,ac)['setpoint_delta_C']for i in range(4)]==[.5,1,1.5,2]
    assert [grade_table('water_heater',i,tank)['target_delta_C']for i in range(4)]==[1,2,3,5]
    assert [grade_table('ev',i,{})['connection_slack_removal_fraction']for i in range(4)]==[.25,.5,1,1.25]
    tests.append('EB_AC_anchors_and_declared_benchmark_tank_and_EV_grids_are_distinct')
    w,old,defs=fixtures['fallback'];new=rebuild(w,old)
    for x in new['classification']['actual_actions']['control_changes']:
        if x['kind']=='tank_setpoint'and x['A']and x['B']:assert abs(x['A']['value_C']-x['B']['value_C'])<=5
    assert command_signature(new['B'])!=command_signature(old['A'])
    tests.append('0145_July8_old_program_extreme_fallback_no_longer_causes15C_tank_drop')
    w,old,defs=fixtures['same'];assert not defs
    for i in range(4):assert construct(w,old,defs,i)==old['B']
    tests.append('fixed_unchanged_case_payload_is_preserved_for_all_input_vectors')
    accept=read(OUT/'ACCEPTANCE.json')
    assert accept['accepted'] and accept['counts']['candidate_integrity_checks']==40000 and accept['counts']['same100_payload_preserved']==100
    assert accept['counts']['negative_EV_window_slack_requests_kept']>0 and accept['counts']['constraint_conflict_cases']>0
    tests.append('infeasible_EV_slack_and_given_constraint_conflicts_are_retained_without_success_filtering')
    assert accept['counts']['mixed_grade_cases']>0
    tests.append('whole_population_contains_mixed_device_grades_with_no_household_scalar')
    result={'passed':True,'count':len(tests),'tests':tests,'rules_sha256':rules_id(),'human_labels_created':0}
    save(OUT/'REGRESSION_RESULTS.json',result);print(canonical(result))

if __name__=='__main__':main()
