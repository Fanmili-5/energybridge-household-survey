"""Independent readback of the candidate and preserved research packages.

Assertions check specific controls. Housing functional feasibility is assessed
as unresolved; neither6 nor9m2 room screens are national stock boundaries.
"""
import collections, hashlib, json, math
from pathlib import Path
import numpy as np
from build_census_frame import table,apportion

OUT=Path(__file__).resolve().parent.parent
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(name,data):(OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n')

def main():
    frame=read(OUT/'ORDINARY_CITY_FRAME.json');body=read(OUT/'HOUSEHOLDS1000_JOINT_CANDIDATE.json');p=body['profiles']
    checks=[]
    def check(cond,name):
        if not cond:raise AssertionError(name)
        checks.append(name)
    check(len(p)==1000 and len({x['slot_id'] for x in p})==1000,'1000_unique_household_slots')
    check(sum(x['family']['resident_count'] for x in p)==2524,'2524_residents_read_from_family_rosters')
    check(all(x['housing']['H5']==1 for x in p),'ordinary_city_new_frame')
    byprov=collections.Counter(x['province'] for x in p)
    check(byprov==read(OUT/'ORDINARY_ALLOCATION1000.json')['report']['province_quota'],'all31_province_household_quotas')
    check(abs(sum(x['relative_population_weight'] for x in p)-1000)<1e-6,'finite_cohort_population_weight_normalization')
    _,nr,_=table('A0112a');reference_area=float(nr['全国'][3]);weighted_h6=sum(x['relative_population_weight']*x['housing']['H6_census_building_area_design_m2'] for x in p)/1000
    check(sum(x['housing']['H6_census_building_area_design_m2'] for x in p)==round(reference_area*1000),'unweighted_national_H6_mean_source_constraint')
    room=collections.Counter(x['housing']['H7_bin_detailed'] for x in p)
    check([room[str(i)] for i in range(1,10)]+[room['10+']]==apportion(1000,np.array(frame['ordinary_room10_counts']).sum(0)).tolist(),'national_detailed_H7_categories')
    pcb=collections.Counter(x['housing']['percap_area_bin_index'] for x in p)
    check([pcb[i] for i in range(10)]==apportion(1000,np.array(frame['ordinary_percap_area10_counts']).sum(0)).tolist(),'national_percap_H6_categories')
    qgeneration=collections.Counter(x['family']['generation_count'] for x in p)
    check([qgeneration[i] for i in range(1,6)]==frame['integer_allocation']['national_generation_quotas'],'national_generation_controls')
    province_diagnostics=[]
    for k,prov in enumerate(frame['provinces']):
        subset=[x for x in p if x['province']==prov]
        check(abs(sum(x['relative_population_weight'] for x in subset)-frame['ordinary_household_counts'][k]/frame['official_households']*1000)<1e-6,'weighted_province_share:'+prov)
        for g in range(5):
            for b in range(5):
                actual=sum(x['family']['generation_count']==g+1 and min(x['housing']['H7_independent_natural_rooms_design'],5)==b+1 for x in subset)
                exp=frame['ordinary_generation_room_counts'][k][g][b]/frame['official_households']*1000
                check(math.floor(exp)<=actual<=math.ceil(exp),f'province_generation_broadH7:{prov}:{g}:{b}')
        for b in range(10):
            actual=sum(x['housing']['percap_area_bin_index']==b for x in subset);exp=frame['ordinary_percap_area10_counts'][k][b]/frame['official_households']*1000
            check(math.floor(exp)<=actual<=math.ceil(exp),f'province_percapH6bin:{prov}:{b}')
        mean=sum(x['housing']['H6_census_building_area_design_m2'] for x in subset)/len(subset)
        province_diagnostics.append({'province':prov,'finite_cohort_houses':len(subset),'H6_design_mean_m2':mean,
          'official_ordinary_H6_rounded_mean_m2':frame['ordinary_mean_building_area_m2'][k],
          'difference_m2':mean-frame['ordinary_mean_building_area_m2'][k],'province_H6_mean_was_not_hard_calibrated':True})
    ids=[]
    for x in p:
        family=x['family'];members=family['members'];ids.extend(m['member_id'] for m in members)
        check(len(members)==x['exact_member_count']==family['resident_count'],'roster_matches_target:'+x['slot_id'])
        check(len({m['generation_level'] for m in members})==family['generation_count'],'occupied_generation_levels:'+x['slot_id'])
        check(sum(m['ego_relation_code']==1 for m in members)==1,'single_reference_ego:'+x['slot_id'])
        check(len(family['ego_relationships'])==len(members)-1,'all_ego_relations_exported:'+x['slot_id'])
        check(not family['full_biological_pairwise_parentage_identified'],'no_invented_full_parentage:'+x['slot_id'])
        check(x['housing']['census_source_household_H6_observed'] is None and x['housing']['gross_to_IDF_net_area_ratio'] is None,'source_unknown_and_area_bridge_remain_unknown:'+x['slot_id'])
        check(family['income_calendar_reference_year'] is None,'income_period_not_assumed_from_visit:'+x['slot_id'])
        lo=[1,9,13,17,20,30,40,50,60,70];hi=[8,12,16,19,29,39,49,59,69,math.inf]
        b=x['housing']['percap_area_bin_index'];pc=x['housing']['H6_census_building_area_design_m2']/family['resident_count']
        check(lo[b]<=pc<=hi[b],'independent_percap_area_bin_readback:'+x['slot_id'])
        if family['source_joint_attribute_visit_year']!=2021:
            check(family['modern_asset_group_2_5_19']==[None,None,None],'no_2022_asset_sync_claim:'+x['slot_id'])
        if len(members)==1 and members[0]['age_years']<20:
            check(family['income_reference_bin'] is None and family['modern_asset_group_2_5_19']==[None,None,None],'minor_not_given_adult_finance:'+x['slot_id'])
    check(len(set(ids))==2524,'unique2524_member_identifiers')
    unresolved=[]
    for x in p:
        h=x['housing'];a=h['H6_census_building_area_design_m2'];r=h['H7_independent_natural_rooms_design']
        if a/r<6:unresolved.append({'slot_id':x['slot_id'],'H6_design_m2':a,'H7_design':r,'gross_area_per_counted_room_m2':a/r,
          'meaning':'diagnostic_conventional_room_budget_screen_only; national_historical_stock_not_proven_impossible',
          'resolution':'joint_functional_layout_and_area_allocation_before_IDF; no_target_household_deletion'})
    small_pool=sum(x['family']['selected_coarse_atom_source_count']==1 for x in p)
    result={'assertions_passed':len(checks),'population_controls_checked':True,'1000_families':1000,'2524_residents':2524,
      'H6_design_range_m2':[min(x['housing']['H6_census_building_area_design_m2'] for x in p),max(x['housing']['H6_census_building_area_design_m2'] for x in p)],
      'H6_population_weighted_mean_m2':weighted_h6,'H6_population_weighted_minus_official_mean_m2':weighted_h6-reference_area,
      'national_area_calibration_type':'unweighted1000-cohort_design; population_weights_restore_province_share_but_all_other_moments_not_exact',
      'provincial_mean_area_diagnostics':province_diagnostics,'conventional_room_budget_review_needed':unresolved,
      'selected_coarse_atoms_supported_by_one_source_record':small_pool,'coarsening_is_not_formal_privacy_or_generalization_proof':True,
      'unknown_modern_groups_slots':sum(None in x['family']['modern_asset_group_2_5_19'] for x in p),
      'unknown_income_bins_slots':sum(x['family']['income_reference_bin'] is None for x in p),
      'minor_singleton_world_not_actor_ready_slots':[x['slot_id'] for x in p if len(x['family']['members'])==1 and x['family']['members'][0]['age_years']<20],
      'grafted_motif_slots':[x['slot_id'] for x in p if x['family']['motif_graft_extrapolation']],
      '2022_prior_fallback_slots':[x['slot_id'] for x in p if x['family']['source_joint_attribute_visit_year']==2022],
      'new_household_IDFs':0,'complete_actor_cards':0,'full_joint_population_validated':False,'scientific_benchmark_admitted':False}
    save('CANDIDATE_AUDIT.json',result)
    physical=read(OUT/'ETNA_INDEPENDENT_STEADY_RESULT.json')
    check(len(physical['runs'])==2 and all(r['mean_inside_measured_band'] for r in physical['runs']),'independent_steady_fixture_two_runs_in_source_band')
    check(all(r['negative_control_heater_plus_fan_outside_band'] for r in physical['runs']),'wrong_meter_fixture_negative_control')
    check(physical['time_step_refinement_relative_mean_change']<.001,'fixture_time_step_refinement_source_guidance')
    frozen=0
    for name in ['production_route_v5_20261004','idf_unit_evidence_20261004','end_to_end_plan_20261004','production_route_v4_20261003','construction_chain_20261003','benchmark_foundation_20261004']:
        root=OUT.parent/name
        for rel,expected in read(root/'PACKAGE_MANIFEST.json')['files'].items():
            check(sha(root/rel)==expected,'frozen_file:'+name+'/'+rel);frozen+=1
    for lock in frame['frames']:check(sha(Path(lock['path']))==lock['sha256'],'census_source_lock:'+lock['key'])
    for lock in read(OUT/'INPUT_LOCK.json'):check(sha(Path(lock['path']))==lock['sha256'],'private_or_semantic_input_lock:'+lock['path'])
    floor=read(OUT/'FLOORPLAN_SOURCE_ADMISSION.json');access=read(OUT/'raw/floorplan3000_download.json')
    check(sha(Path(access['rar_path']))==access['rar_sha256'],'floorplan_actual_nested_RAR_lock')
    check(floor['actual_JPEG_files']==9006 and floor['actual_paired_filename_sets']==3002,'floorplan_actual_count_not_advertised_count')
    check(not floor['automatic_IDF_binding_approved'],'dimensionless_images_not_promoted_to_metric_IDFs')
    save('VERIFICATION.json',{'checked_controls_and_source_integrity':True,'assertions':len(checks),'frozen_files_unchanged':frozen,
      'full_joint_national_and_functional_geometry_validated':False,'scientific_benchmark_admitted':False,'collection_release':False,'training_release':False})
    print(json.dumps({k:result[k] for k in ['1000_families','2524_residents','H6_design_range_m2','H6_population_weighted_minus_official_mean_m2','selected_coarse_atoms_supported_by_one_source_record','unknown_modern_groups_slots','unknown_income_bins_slots']},indent=2))
    print(json.dumps({'room_budget_screen_slots':len(unresolved),'frozen_files_unchanged':frozen,'assertions':len(checks)}))

if __name__=='__main__':main()
