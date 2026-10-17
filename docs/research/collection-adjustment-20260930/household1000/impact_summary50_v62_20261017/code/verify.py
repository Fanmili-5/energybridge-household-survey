"""Independent readback of complete actual occupancy, exposure bins and provenance."""
from regenerate import *


def close(a,b):
    assert abs(a-b)<1e-7,(a,b)


def expand(spans):
    return [m for p in spans for m in range(p['start_min'],p['end_min'],10)]


def check_exposure(exposure,arm,indices,date):
    assert exposure['occupied_minutes']==len(indices)*10
    assert expand(exposure['occupied_periods'])==[i*10 for i in indices]
    for period in exposure['occupied_periods']:
        lo,hi=period['start_min']//10,period['end_min']//10
        assert period['air_temperature_range_C']==limits(arm['air_C'][lo:hi])
        assert period['radiant_temperature_range_C']==limits(arm['radiant_C'][lo:hi])
        assert period['RH_range_percent']==limits(arm['RH_percent'][lo:hi])
        assert period['start']==wall(date,period['start_min'])and period['end']==wall(date,period['end_min'])
    assert sum(b['total_minutes']for b in exposure['air_temperature_bins'])==len(indices)*10
    for b in exposure['air_temperature_bins']:
        hit=[i*10 for i in indices if(b['lower_inclusive_C']is None or arm['air_C'][i]>=b['lower_inclusive_C'])and(b['upper_exclusive_C']is None or arm['air_C'][i]<b['upper_exclusive_C'])]
        assert b['total_minutes']==len(hit)*10
        assert expand(b['periods'])==hit


def check_durations(metrics,points,indices):
    for threshold in THRESHOLDS:
        for direction,sign in [('B_warmer',1),('B_cooler',-1)]:
            hits=[i*10 for i in indices if sign*(points['B']['air_C'][i]-points['A']['air_C'][i])>threshold+EPS]
            m=metrics[str(threshold)][direction]
            assert m['total_minutes']==len(hits)*10
            assert expand(m['periods'])==hits
            longest=streak=0;last=None
            for minute in hits:
                streak=streak+10 if last is not None and minute==last+10 else 10
                longest=max(longest,streak);last=minute
            assert m['longest_continuous_minutes']==longest


def main():
    bindings=read(ROOT/'SUMMARY_BINDINGS50.json');source=read(SOURCE/'PHYSICAL_BINDINGS50.json')
    parents={r['case_id']:r for r in source['records']};manifest={r['path']:r['sha256']for r in read(SOURCE/'FILE_MANIFEST50.json.gz')['files']}
    assert sha(SOURCE/'FINAL_SEAL50.json')==SOURCE_SEAL
    assert sha(SOURCE/'PHYSICAL_BINDINGS50.json')==SOURCE_BINDINGS
    assert sha(ROOT/'code/regenerate.py')==bindings['summary_logic_sha256']
    assert sha(ROOT/'SUMMARY_POLICY.json')==bindings['policy_sha256']
    assert {r['case_id']for r in bindings['records']}==set(parents)and len(parents)==500
    cases={};tested=[];untested=[];own_room_count=0;other_arm_empty_cases=set()
    for r in bindings['records']:
        assert sha(ROOT/r['path'])==r['sha256']
        assert sha(ROOT/r['temperature_timeline_path'])==r['temperature_timeline_sha256']
        summary=read(ROOT/r['path']);parent=parents[r['case_id']]
        assert sha(SOURCE/parent['path'])==parent['sha256']
        previous=read(SOURCE/parent['path']);cases[r['case_id']]=summary
        for key in ('A','B','VPP_events','recovery','source_B_constraint_flags','delta_primary_kWh','delta_rollout_kWh','specified_initial_state','source_pair_sha256'):
            assert summary[key]==previous[key],('SOURCE_PHYSICS_MISMATCH',r['case_id'],key)
        assert summary['human_acceptance']is None and summary['display']['human_acceptance']is None
        assert not summary['energy_changes']['energy_saving_or_human_acceptance_inferred']
        assert not summary['energy_changes']['subjective_comfort_equivalence_verified']
        assert 'electricity_comparison'not in summary
        for period,key in [('primary','primary'),('observation','rollout')]:
            close(summary['energy_changes'][period]['facility_B_minus_A_kWh'],previous['B'][key+'_energy_kWh']['facility']-previous['A'][key+'_energy_kWh']['facility'])
        coverage=summary['sensitivity_coverage']
        (tested if coverage['individually_assessed_with_distinct_scenarios']else untested).append(r['case_id'])
        assert not coverage['joint_history_and_airflow_perturbations_tested']and not coverage['range_is_confidence_interval_or_guaranteed_bound']
        assert not coverage['full_observation_thermal_sensitivity_validated']
        for label,sides in summary['source_physics']['trace_evidence'].items():
            for proof in sides.values():
                for kind in ('trace','result'):assert manifest[proof[kind+'_path']]==proof[kind+'_sha256']
        timeline=read(ROOT/r['temperature_timeline_path']);assert timeline['interval_start_min']==list(range(480,1920,10))
        display={r['room']:r for r in summary['display']['temperature_card']['rows']}
        for room in summary['thermal_impacts']['rooms']:
            primary=room['primary'];point=timeline['rooms'][room['room']]['scenarios']['reference']
            # Convert delivered primary arrays to absolute-minute indices.
            points={s:{k:[0]*48+v for k,v in point[s].items()}for s in ('A','B')}
            common=[i for i in range(48,192)if points['A']['occupants'][i]>0 and points['B']['occupants'][i]>0]
            assert primary['common_occupied_air_B_minus_A_range_C']==limits([points['B']['air_C'][i]-points['A']['air_C'][i]for i in common])
            check_durations(primary['air_delta_durations'],points,common)
            for side in ('A','B'):
                own_room_count+=1;other='B'if side=='A'else'A';arm=points[side]
                occupied=[i for i in range(48,192)if arm['occupants'][i]>0]
                only=[i for i in occupied if points[other]['occupants'][i]<=0]
                check_exposure(primary[side]['actual_occupied_exposure'],arm,occupied,r['date'])
                check_exposure(primary[side]['other_arm_empty_exposure'],arm,only,r['date'])
                check_durations(primary[side]['own_occupied_same_clock_air_delta_durations'],points,occupied)
                if only:other_arm_empty_cases.add(r['case_id'])
                if room['room']in display:
                    assert display[room['room']][side+'_actual_occupied_exposure']==primary[side]['actual_occupied_exposure']
                    assert display[room['room']][side+'_other_arm_empty_exposure']==primary[side]['other_arm_empty_exposure']
            band=timeline['rooms'][room['room']]['tested_single_factor_range']
            if not coverage['individually_assessed_with_distinct_scenarios']:
                assert band is None and room['tested_single_factor_range']is None
            else:
                for i in range(144):
                    deltas=[p['air_B_minus_A_C'][i]for p in timeline['rooms'][room['room']]['scenarios'].values()]
                    assert band['air_B_minus_A_C_min'][i]==min(deltas)and band['air_B_minus_A_C_max'][i]==max(deltas)
    assert len(tested)==200 and len(untested)==300
    coverage=read(ROOT/'COVERAGE50.json');assert set(tested)==set(coverage['distinct_sensitivity_case_ids'])
    # Real counterexample: B's new17:00 washroom visit must survive the summary.
    shifted=cases['ordinary-v6-0490__2025-03-01'];room=next(r for r in shifted['thermal_impacts']['rooms']if r['room']=='WASHROOM')
    assert 1020 in expand(room['primary']['B']['other_arm_empty_exposure']['occupied_periods'])
    failed=cases['ordinary-v6-0181__2025-05-21'];assert failed['energy_changes']['known_task_delivery_deficit_present']
    assert failed['energy_changes']['task_delivery']['B']['future_unexecuted_batches']==8
    cold=cases['ordinary-v6-0490__2025-01-01'];assert cold['sensitivity_coverage']['individually_assessed_with_distinct_scenarios']
    assert cold['sensitivity_coverage']['background_leakage_ACH_tested']==[.175,.7]
    save(ROOT/'VERIFICATION50.json',{'schema':SCHEMA,'passed':True,'summaries_verified':500,'temperature_timelines_verified':500,
         'source_physical_outcome_pairs_unchanged':500,'actual_occupied_room_sides_verified':own_room_count,
         'cases_with_other_arm_empty_exposure':len(other_arm_empty_cases),'effective_sensitivity_cases':200,
         'cases_not_individually_assessed':300,'diagnostic_comparisons':632,'human_labels_created':0,
         'new_energyplus_runs_in_summary_generation':0,'full1000_deferred_by_user':True,
         'source_seal_sha256':SOURCE_SEAL,'summary_bindings_sha256':sha(ROOT/'SUMMARY_BINDINGS50.json')})
    print(json.dumps({'passed':True,'summaries':500,'actual_room_sides':own_room_count,'tested':200,'not_tested':300}),flush=True)


if __name__=='__main__':main()
