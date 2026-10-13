"""Measured scoped acceptance and public claim boundaries; no human answers."""
import collections,math
from common import *
def main():
    school_guard();inputs=read(OUT/'INPUT_AUDIT.json');sr=read(OUT/'STATIC_REVIEW.json');rr=read(OUT/'READBACK_all_REVIEW.json');ss=read(OUT/'READBACK_sensitivity_REVIEW.json');wr=read(OUT/'WEATHER_SOLVER_REVIEW.json');wb=read(OUT/'WORLD_BUILD_REVIEW.json')
    assert inputs['failures']==[] and inputs['pairs']==10000 and sr['pairs']==10000 and sr['integrity_failures']==[]
    assert rr['checked_pairs']==500 and not rr['failures'] and ss['checked_pairs']==200 and not ss['failures']
    assert rr['maximum_pre_notice_difference']==rr['maximum_meter_residual_J']==rr['maximum_spatial_SQL_difference']==0
    assert ss['maximum_pre_notice_difference']==ss['maximum_meter_residual_J']==ss['maximum_spatial_SQL_difference']==0
    assert rr['A_circuit_exceeded_pairs']==rr['A_home_exceeded_pairs']==0
    stats=collections.Counter();byfamily=collections.defaultdict(collections.Counter);near=[]
    for f in sorted((OUT/'readback/base7').glob('*/*.json')):
        r=read(f);p=read(OUT/'pairs'/r['household_id']/f.name);family=p['proposal']['family'];e=r['energy']['event'];delta=e['A_minus_B_kWh']
        assert r['pair_sha256']==sha(OUT/'pairs'/r['household_id']/f.name)
        assert r['world_sha256']==sha(OUT/'worlds'/(r['household_id']+'.json'))
        # Goal is0.5kW mean over onehour; event has60min by contract.
        duration=(p['event_window_min'][1]-p['event_window_min'][0])/60.;mean=delta/duration
        category='event_target_met' if mean>=.5-1e-6 else 'event_zero_effect' if abs(delta)<1e-6 else 'event_increase' if delta<0 else 'event_positive_below_target'
        stats[category]+=1;byfamily[family][category]+=1
        for side in ('A','B'):
            hot=r['services'][side].get('hot_water',[]);ev=r['services'][side].get('EV',{})
            stats[side+'_hot_water_goal_failed_pairs']+=bool(hot and any(not x['temperature_pass'] for x in hot))
            stats[side+'_EV_target_failed_pairs']+=bool(ev and any(not x['target_pass'] for x in ev['goals']))
            stats[side+'_EV_trip_shortfall_pairs']+=bool(ev and any(x['shortfall_kWh']>1e-6 for x in ev['trips']))
            stats[side+'_EV_reserve_failed_pairs']+=bool(ev and any(not x['reference_reserve_pass'] for x in ev['trips']))
        variants=[]
        for name in ('base7','prior14','seasonal7','seasonal14'):
            path=OUT/'readback'/name/r['household_id']/f.name
            if path.exists():
                variant=read(path);assert variant['pair_sha256']==r['pair_sha256'] and variant['world_sha256']==r['world_sha256'];variants.append(variant)
        if len(variants)==4:
            ds=[v['energy']['living_day']['A_minus_B_kWh'] for v in variants]
            near.append({'household_id':r['household_id'],'round_index':r['round_index'],'range_min_kWh':min(ds),'range_max_kWh':max(ds),'range_includes_zero':min(ds)<0<max(ds)})
    assert stats['A_hot_water_goal_failed_pairs']==stats['A_EV_target_failed_pairs']==stats['A_EV_trip_shortfall_pairs']==stats['A_EV_reserve_failed_pairs']==0,dict(stats)
    save(OUT/'PROPOSAL_DIAGNOSTICS.json',{'schema':'eb.proposal_model_diagnostics.v19','existing_original50_pairs':500,'counts':dict(stats),'by_proposal_family':{k:dict(v) for k,v in byfamily.items()},'sensitivity_case_ranges':near,
        'outcomes_not_used_for_date_or_proposal_reselection':True,'bad_B_retained':True,'these_are_not_human_rejection_labels':True,'human_answers':0})
    save(OUT/'STRICT_WEATHER_REFERENCE_COMPARISON.json',{'strict_point_reference_agreement_pass':wr['strict_point_reference_agreement_pass'],
        'original_prespecified_tolerance_C':.05,'maximum_error_C':wr['minimal_reported_wetbulb_comparison']['maximum_error_C'],
        'strict_failure_retained':not wr['strict_point_reference_agreement_pass'],'branch_diagnostic_is_not_strict_gate_replacement':True,
        'source':'current weather-only and affected-case SQL; details in WEATHER_SOLVER_REVIEW.json'})
    save(OUT/'AUDIT_COUNTS_CORRECTION.json',{'date':'2026-10-09','source':'V18 DIAGNOSTICS.json under6_ages: age0=16,age1=19,age2=20',
        'prior_audit_under3_count_reported':54,'correct_under3_count':55,'why':'arithmetic undercount byone; anchor source roster hasnot changed','source_rosters_changed':False})
    claims={'schema':'eb.scientific_claim_boundaries.v19','scientific_benchmark_admitted':False,'human_answers':0,
        'supported':['same1000populationhousinganchors andoriginal10dates','source-aware known/unknown fields and explicit reference activity/care/transport conditions','normative/reference calendar and resource checks across30000 datedhouseholddays','all20000 staticIDFbindings','original50 actualSQLimplementation,metering,occupancy,power andfiniteboundary comparisons','originalfrontendmaterials/versionbindings'],
        'not_established':['national fulljoint activity or appliance ownership distribution','actual2025 occupation/diary/licence/preference ofsynthetic people','calibrated realhousehold physics or bills','human role comprehension/effect orholdout predictivebenchmark validity','other950 physical outcomes'],
        'experimental_unit':'fixed-reference-role bysampleddate condition; ages/co-residents areheldfixed,not a realannual cohorttrajectory',
        'physical_vs_human_history':'7/14day exogenousAinitialization isnot actorfeedbackhistory; no actualfeedbackhistory invented',
        'remaining_assumptions':['declared eligible activitylevel allocation isnot a fittednational probability','Beijingschoolcalendar transferredprototypeelsewhere','conservativefreewindows do notexhaust negotiatednearbycare-compatibleactions','genericEBhardware/bodyheat/external18Cheating/referenceDHWdoses lackfieldcalibration'],
        'next_gate':'boundoriginalfrontendreadability andindependentactorrole evidence; preserve originalrawresponses andfeedbackbudget'}
    save(OUT/'SCIENTIFIC_CLAIM_BOUNDARIES.json',claims)
    renderer=OUT/'engineering_render_records/RENDER_REVIEW.json';clock=OUT/'FRONTEND_CLOCK_REVIEW.json'
    front=renderer.exists() and clock.exists() and read(renderer)['status']=='pass' and read(clock)['status']=='pass'
    records=[{'id':'F01','reference_implementation_accepted':True,'evidence':'INPUT_AUDIT/WORLD_BUILD_REVIEW','limit':'experimental activity levels; national joint diary remains unidentified'},
        {'id':'F02','reference_implementation_accepted':True,'evidence':'age sleep/nap/care/calendar INPUT_AUDIT plusRULE_EVIDENCE','limit':'healthy reference/rest windows and prototype calendar,not measured clinicalsleep/real local diaries'},
        {'id':'F03','reference_implementation_accepted':True,'evidence':'transport_contracts anddriver/journey checks','limit':'given authorisation/vehicleaccess,not observed licence or national modefrequencies'},
        {'id':'F04','reference_implementation_accepted':True,'evidence':'actualZonePeopleCount/lightScheduleValue vscontinuousactivity/operationledger inoriginal50','limit':'genericEBbodyheat,not physiologicalcalibration'},
        {'id':'F05','reference_implementation_accepted':True,'evidence':'PROPOSAL_DIAGNOSTICS andinput-onlySTATIC_REVIEW','limit':'actualhuman interpretation and response areunknown'},
        {'id':'F06','reference_implementation_accepted':True,'evidence':'original50actualreadbacks,200sensitivitypairs,powerlimits andWEATHER_SOLVER_REVIEW','limit':'strictwetbulbpoint gatefailed;fieldcalibration andother950outcomes unestablished'},
        {'id':'F07','reference_implementation_accepted':False,'material_engineering_accepted':front,'actual_human_evidence':0,'limit':'actualreadability,roleeffect andholdout answers pending'}]
    save(OUT/'REPAIR_ACCEPTANCE.json',{'schema':'eb.scoped_reference_repair_acceptance.v19','date':'2026-10-09','records':records,
        'reference_foundation_and_original50_physics_accepted':True,'original_frontend_engineering_accepted':front,
        'whole_program_scientific_completion':False,'formal_benchmark_admitted':False,'actual_human_answers':0,
        'statistics':{'input_households':1000,'input_pairs':10000,'dated_days_checked':inputs['dated_household_days'],'original50default_pairs':500,'sensitivity_pairs':200,
            'unknown_adult_free_minutes':inputs['unknown_adult_dated_free_minutes'],'transport_modes':wb['transport_contracts'],'service_and_event_counts':dict(stats)},
        'source_rule_provenance':'RULE_EVIDENCE.json','claim_boundaries':'SCIENTIFIC_CLAIM_BOUNDARIES.json'})
    print({'reference_checks_accepted':True,'frontend_engineering_accepted':front,'human_answers':0,'service_and_event_counts':dict(stats),'max_sensitivity_delta_change':ss['sensitivity']['maximum_absolute_A_minus_B_energy_difference_kWh']},flush=True)
if __name__=='__main__':main()
