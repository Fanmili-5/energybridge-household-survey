"""Co-register 1000 source-calibrated profiles, reference facets and model ports.

The output is an executable, guarded production specification. It is not a
claim that independently calibrated facets already agree with old shell IDFs.
Per-world source/evidence/geometry/service admissions remain separate.
"""
import collections,hashlib,json
from pathlib import Path
OUT=Path(__file__).resolve().parent.parent;BASE=OUT.parent;V7=BASE/'idf_joint_production_20261005';V8=BASE/'household_housing_evidence_20261006'
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(name,d):(OUT/name).write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def eligible_ports(asset):
 c=asset['class'];ports=[]
 if c=='washer' and asset['type_code']==4 and asset['capacity_bin']==5 and asset['duration_bin']==7:
  ports.append({'port':'Miele_WTD160_wash_test','mode':'washing_function_reference_only_not_same_hardware_identity','source_test_duration_bin_compatible':True})
 if c=='washer_dryer_combo_report':ports.append({'port':'Miele_WTD160_wash_test','mode':'declared_combo_reference_candidate_unresolved_crossmodule_identity','source_capacity_and_program_not_identified':True})
 if c=='water_heater' and asset['type_code']==1 and asset['fuel_code']==1 and asset['storage_volume_bin']==2:
  ports.append({'port':'Haier_ES60H_AFV2AU1_reference_tank','mode':'scalar_volume_power_reference_well_mixed_topology_design'})
 if c=='split_AC' and asset['cooling_capacity_like_bin_not_electric_input']==3:
  ports.append({'port':'Haier_KFR26GW_06ZFA22_rated_cooling','mode':'rated_point_only_no_full_climate_curve'})
 if c=='refrigerator' and asset['volume_bin']==5:
  ports.append({'port':'Haier_BCD342WLHFD9DB9U1_label','mode':'daily_label_mean_reference_not_cold_food_or_compressor_model'})
 return ports
def facility_overlay(f,q,hid):
 kitchen=f['kitchen'];toilet=f['toilet'];bath=f['bathing_hot_water']
 return {'kitchen_zone':{'legacy_zone_ID':'kitchen','functional_use':'reserved_non_kitchen_service_space' if kitchen=='none' else 'cooking_space',
   'target_household_kitchen_access':kitchen,'whole_dwelling_q_is_not_kitchen_sharing_count':True,
   'exclusive_target_usage_requires_reassigning_auxiliary_rights':kitchen=='exclusive' and q>1,
   'shared_context_outside_existing_q_required':kitchen=='shared' and q==1,
   'other_sharers_N_and_kitchen_usage_unknown':True},
  'toilet_zone':{'legacy_zone_ID':'bath_wc','toilet_facility':toilet,'no_toilet_means_remove_fixture_and_retain_non_H7_service_space':toilet=='none'},
  'bath_service':{'local_bathing_hot_water':bath,'self_heater_means_thermal_service_requirement_not_electric_fuel':bath=='self_installed_heater',
    'central_service_not_personal_metered_heater':bath=='central','none_local_is_not_no_bathing_anywhere':bath=='none'},
  'piped_water_service':{'present':f['piped_water']=='present','absence_is_not_zero_household_water_use':True,'actual_supply_pressure_flow_and_drainage':None},
  'main_cooking_fuel':{'code':f['main_cooking_fuel'],'local_cooktop_and_use_clock_not_observed':True},
  'H7_original_classification_N_H6_q_not_changed_by_fixture_removal_or_hall_sleep':True,
  'facility_overlay_is_declared_design_and_requires_new_compilation_not_old_IDF_automatic_admission':True}
def main():
 if (OUT/'PACKAGE_MANIFEST.json').exists():raise SystemExit('sealed')
 pp=read(V7/'HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json')['profiles'];stock=read(OUT/'STOCK_SCENARIOS1000.json')['scenarios'];ss={s['scenario_id']:{r['household_id']:r for r in s['households']} for s in stock}
 devices={r['household_id']:r for r in read(OUT/'DEVICE_PRIOR_ROUTES1000.json')['routes']};sleep={r['household_id']:r for r in read(OUT/'MIXED_SLEEP_SCENARIOS1000.json')['cases']};regional={r['household_id']:r for r in read(V8/'MATCHING_SCENARIOS1000.json')['routes']}
 rows=[];count=collections.Counter();forbidden={}
 for p in pp:
  hid=p['slot_id'];a=devices[hid];f=ss['hash_reference'][hid]['official_marginal_calibrated_reference_assignments'];q=p['housing']['shared_household_count_design'];overlay=facility_overlay(f,q,hid)
  refs=[]
  for report in a['auxiliary_reported_assets']:
   ports=eligible_ports(report);count.update(port['port'] for port in ports)
   refs.append({'report_reference_id':report['report_reference_id'],'class':report['class'],'reference_model_candidates':ports,
    'source_reference_year':2012,'actual_device_model_at_source_unknown':True,'installation_zone':None,'installed_model':None,
    'source_schedule_bins_not_exact_clock':True,'requires_explicit_instance_identity_fuel_zone_and_operator_permission':True,
    'component_candidates_are_not_automatically_installed':True})
  adult=[m['member_id'] for m in p['family']['members'] if m['age_years']>=18]
  gaps=['actual_household_city_and_construction_year','detailed_native_glazing_frame_boundary',
    'joint_stock_geometry_and_facility_overlay_compilation','source_specific_model_to_installed_device_identity',
    'whole_home_fuel_meter_balance_and_infiltration_lighting_cooking','body_mass_mobility_care_privacy_and_door_swing',
    'actual_behavior_or_formal_human_answers']
  if f['building_storeys']=='one_storey':count['one_storey_requires_roof_outdoors_floor_ground_new_boundary']+=1
  count['source_matching_all_fallback_routes']+=1;count['source_specific_reference_ports_households']+=bool(any(r['reference_model_candidates'] for r in refs))
  count['no_adult_reference_operator']+=not bool(adult)
  rows.append({'household_id':hid,'province':p['province'],'N':p['family']['resident_count'],'G':p['family']['generation_count'],
   'H6_m2':p['housing']['H6_census_building_area_design_m2'],'H7_design':p['housing']['H7_independent_natural_rooms_design'],'q_design':q,
   'relative_population_weight':p['relative_population_weight'],
   'population_anchor_path':str(V7/'HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json'),'population_anchor_sha256':sha(V7/'HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json'),
   'family_observed_for_generated_household':False,'current_address_co_residence_matched_truth_identified':False,
   'three_stock_reference_assignments':{sid:ss[sid][hid]['official_marginal_calibrated_reference_assignments'] for sid in ss},
   'stock_features_are_reference_assignments_not_observed_home_attributes':True,'functional_facility_overlay':overlay,
   'building_exposure_reference':{'category':f['building_storeys'],'one_storey_old_midfloor_adiabatic_IDF_admissible':f['building_storeys']!='one_storey',
    'actual_dwelling_floor_number':None,'boundary_options':'one_storey: ground+roof;otherwise expose top/bottom/corner/midfloor as conditional scenarios',
    'census_macro_structure_is_not_opaque_layer_or_native_prototype_type':True,'effective_epoch_is_not_code_compliance':True},
   'reference_world_and_IDF':{'world_path':str(V7/p['housing']['world_path']),'IDF_path':str(V7/p['reference_IDF_path']),
    'sleep_reference0_6m_found':sleep[hid]['baseline0_6m']['found'],'sleep_route':sleep[hid]['baseline0_6m']['route'],
    'sleep0_8m_found':sleep[hid]['alternative0_8m']['found'],'witness_applies_only_to_exact_checked_geometry':True,
    'regional_candidates':regional[hid]['same_province_opaque_reference_and_WMO_coordinate_weather_candidates'],
    'regional_parameter_or_exposure_change_requires_new_geometry_and_sleep_check':True},
   'device_reports':refs,'device_prior_route':a['match_route'],'device_prior_source_pool_count':a['source_pool_count'],
   'true_total_installed_device_count':None,'positive_service_report_count':a['positive_asset_service_report_count'],
   'distinct_historical_physical_asset_lower_bound':a['distinct_physical_asset_lower_bound_count'],
   'operator_contract':{'eligible_reference_adult_member_ids':adult,'default_selected_operator_ID':None,'presence_calendar':None,
    'remote_capability_and_control_permission':None,'future_assigned_role_design_or_observation_required':True},
   'admission':{'official_marginal_production_controls_verified':True,'historical_auxiliary_report_route_traceable':True,
    'conditional_reference_sleep_witness_verified':True,'all_facets_joint_physical_assembly_verified':False,
    'whole_home_IDF':False,'actor_package':False,'formal_human_answers':0},'evidence_truth_gaps_retained':gaps})
 save('PRODUCTION_REFERENCE1000.json',{'households':rows,'fixed_households':1000,'fixed_residents':sum(r['N'] for r in rows),
  'scope':'2020 ordinary-residential city family household reference profiles;town/rural/collective excluded',
  'product':'guarded production specification, not complete household IDFs or actor packages','summary':dict(count)})
 schema={'estimand':{'later_human_role_benchmark':'conditional distribution of responses to explicitly assigned profile+reference housing/service world+plan+event',
  'current_reference_population_moments':'controlled margins in declared2020 city ordinary frame',
  'unconditional_real_China_energy_or_behavior_estimand_identified':False,
  'human_participant_or_role_repeats_not_1000_IID_actual_households':True},
  'source_truth_layers':['official aggregate calibration','same-record survey auxiliary prior','author native prototype parameters','declared reference geometry/services','future human conditional responses'],
  'field_evidence_contract_required':['value','unit','reference_epoch','population_scope','source_ID_and_field_or_page','construction_rule','observed_calibrated_matched_or_design_status','uncertainty_or_transport_flag','owner_and_meter_scope'],
  'generation_order':['freeze target and complete source semantics','solve marginals and partial-identification region','freeze reference coupling alternatives','construct geometric housing and facility/access rights',
    'validate exact geometry+sleep+building exposures','qualify appliance reports and resolve physical instance identity','instantiate fuel-compatible source-parameter models and meters',
    'declare operator presence permission tasks and clock','compile IDF/weather plus component interface','verify geometry units balances controls and scenario sensitivity','independent physical calibration gate','actor-package and human-data gate'],
  'automatic_rejection_rules':['town/rural or H5 nonordinary in target','blank interpreted as absence','CHFS group used as individual appliance','washer+combo duplicate hardware',
    'central HVAC copied as private split unit','thermal capacity used as electric power','unasked branch value used as observed parameter','native optical pairs used without valid boundary',
    'census year used as guaranteed energy code','prototype file counts used as stock weights','one-storey assigned to unchanged adiabatic-midfloor shell',
    'stock facets claimed installed without facility overlay compile','old geometry sleep witness reused after wall thickness change','no operator or permission for manual start',
    'active dryer cut by externally controlled socket','kitchen-sharing count identified from whole-dwelling q','compiler pass called national physical or behavioral calibration'],
  'claims_allowed_now':['1000 fixed marginal-calibrated reference profiles','310 provincial housing-feature controls','sharp specified two-event bounds conditional on margins',
   'exact checked reference geometry conditional sleeping witnesses','traceable historical individual appliance reports','189 native scalar window parameter reference bundles','selected tested component reference kernels'],
  'claims_not_allowed_now':['1000 observed Chinese households','national multivariate household-stock-device joint distribution recovered','complete calibrated whole-home IDFs','safe/private inhabited homes',
    'real national annual/peak household electricity','human response validity or empirical consent labels'],
  'original_population_and_nine_prior_sealed_packages_preserved':True,'collection_release':False,'training_release':False}
 save('PRODUCTION_CONTRACT.json',schema);print(json.dumps(dict(count),ensure_ascii=False))
if __name__=='__main__':main()
