"""Read primary margins and verify outputs independently of generation rules.
Checks are implementation/source-semantics validation, not stock calibration.
"""
import collections,json,math
from pathlib import Path
import pandas as pd
OUT=Path(__file__).resolve().parent.parent;BASE=OUT.parent
def read(p):return json.loads(p.read_text())
def clean(s):return ''.join(str(s).split())
def main():
 if (OUT/'PACKAGE_MANIFEST.json').exists():raise SystemExit('sealed')
 registry=read(OUT/'OFFICIAL_STOCK_SOURCE_REGISTER.json')['sources'];tables={}
 for k in registry:
  a=pd.read_excel(OUT/'raw'/(k+'.xls'),header=None).fillna('');tables[k]={clean(r[0]):list(r) for r in a.values.tolist() if isinstance(r[1],(float,int)) and r[1]>0}
 # Independent column map, retained alongside original Excel headers.
 columns={'building_storeys':('B0901a',list(range(2,6))),'load_bearing_structure':('B0901a',list(range(6,11))),
  'effective_building_epoch':('B0902a',list(range(4,31,3))),'elevator':('B0903a',[2,3]),
  'main_cooking_fuel':('B0903a',list(range(4,9))),'piped_water':('B0903a',[9,10]),'kitchen':('B0903a',[11,12,13]),
  'toilet':('B0903a',list(range(14,19))),'bathing_hot_water':('B0903a',list(range(19,23))),'housing_source':('B0904a',list(range(2,11)))}
 controls=read(OUT/'STOCK_CONTROLS.json');scenarios=read(OUT/'STOCK_SCENARIOS1000.json')['scenarios'];pp=read(BASE/'idf_joint_production_20261005/HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json')['profiles'];ids={p['slot_id'] for p in pp};weight={p['slot_id']:p['relative_population_weight'] for p in pp};checks=[]
 def check(n,passed):checks.append({'check':n,'passed':bool(passed)})
 for c in controls['controls']:
  k,cols=columns[c['feature']];raw=tables[k][c['province']];labels=list(c['source_category_counts']);N=c['target1000_province_count'];counts=c['integer_reference_counts']
  assert raw[1]==c['source_long_form_ordinary_city_households'] and [int(raw[j]) for j in cols]==list(c['source_category_counts'].values())
  assert sum(counts.values())==N
  for label in labels:
   expected=N*c['source_category_counts'][label]/raw[1];assert math.floor(expected-1e-8)<=counts[label]<=math.ceil(expected+1e-8)
  for s in scenarios:
   observed=collections.Counter(r['official_marginal_calibrated_reference_assignments'][c['feature']] for r in s['households'] if r['province']==c['province'])
   assert all(observed[l]==counts[l] for l in labels)
 check('310_source_marginal_blocks_and_three_assignments_match_actual_raw_tables',len(controls['controls'])==310)
 check('source_ordinary_city_denominator19072613_not_building_or_population',tables['B0901a']['全国'][1]==19072613)
 check('B0906_eligible_subset_not_full_household_denominator',tables['B0906a']['全国'][1]!=19072613)
 for s in scenarios:assert len(s['households'])==1000 and {r['household_id'] for r in s['households']}==ids
 check('three_scenarios_keep_exact1000_IDs',True)
 bound=read(OUT/'PARTIAL_IDENTIFICATION.json')
 for pair in bound['pairs']:
  lower=upper=0
  for row in pair['provinces']:
   n,a,b=row['reference_N'],row['integer_A_count'],row['integer_B_count'];lo,hi=row['sharp_integer_both_bounds'];assert (lo,hi)==(max(0,a+b-n),min(a,b));lower+=lo;upper+=hi
   for name in ['lower_endpoint_2x2_witness','upper_endpoint_2x2_witness']:
    t=row[name];assert min(t.values())>=0 and sum(t.values())==n and t['both']+t['A_only']==a and t['both']+t['B_only']==b
  assert [lower,upper]==pair['sharp_reference1000_count_bounds']
 check('six_partial_identification_pairs_and_endpoint_witnesses_valid',len(bound['pairs'])==6)
 device=read(OUT/'DEVICE_PRIOR_ROUTES1000.json')['routes'];assert len(device)==1000 and {r['household_id'] for r in device}==ids
 for r in device:
  assert r['source_pool_count']>=r['selected_coarsened_pattern_count']>0 and r['distinct_physical_asset_lower_bound_count']<=r['positive_asset_service_report_count']
  for a in r['auxiliary_reported_assets']:
   assert not a['observed_for_generated_household'] and not a['installed_in_generated_housing']
   if a['class'] in ['building_central_AC','household_central_AC']:assert a['cooling_capacity_like_bin_not_electric_input'] is None
   if a['class']=='water_heater' and a['type_code']==2:assert a['storage_volume_bin'] is None
 check('1000_device_routes_branch_and_unknown_count_semantics_valid',True)
 assembly=read(OUT/'PRODUCTION_REFERENCE1000.json');assert len(assembly['households'])==1000 and sum(r['N'] for r in assembly['households'])==2524
 check('all1000_co_registered_without_false_full_IDF_or_actor_admission',all(not r['admission']['whole_home_IDF'] and not r['admission']['actor_package'] for r in assembly['households']))
 check('16_no_adult_cases_retained_without_invented_operator',sum(not r['operator_contract']['eligible_reference_adult_member_ids'] for r in assembly['households'])==16)
 check('61_one_storey_cases_require_new_exposure_not_silent_midfloor',sum(not r['building_exposure_reference']['one_storey_old_midfloor_adiabatic_IDF_admissible'] for r in assembly['households'])==61)
 check('independent_exact_geometry_sleep_verification_passed',not read(OUT/'INDEPENDENT_SLEEP_VERIFICATION.json')['failures'])
 check('component_source_units_and_action_negative_controls_passed',all(c['passed'] for c in read(OUT/'COMPONENT_MODEL_VERIFICATION.json')['checks']))
 glaze=read(OUT/'GLAZING_PROVENANCE.json');check('189_native_type_rows_and187_exact_scalar_conversions_traced',glaze['original_used_native_types_traced']==189 and glaze['converted_scalar_comparisons']==187 and glaze['max_abs_converted_scalar_difference']==0)
 pilot=read(OUT/'GLAZING_PILOT_RESULTS.json');check('8_new_empty_shell_runs_zero_severe_fatal',pilot['empty_shell_runs']==8 and pilot['severe_fatal']==0)
 national_max=max(x['max_abs_national_reference_proportion_error'] for x in controls['national'].values());province_worst=max(controls['controls'],key=lambda c:c['maximum_absolute_province_proportion_integerization_error'])
 result={'checks':checks,'all_passed':all(c['passed'] for c in checks),'implementation_not_external_physical_or_behavioral_validation':True,
  'weighted_national_marginal_error_percentage_points':national_max*100,
  'worst_province_integerization_error':{'province':province_worst['province'],'feature':province_worst['feature'],'cohort_n':province_worst['target1000_province_count'],'percentage_points':province_worst['maximum_absolute_province_proportion_integerization_error']*100},
  'small_province_cohorts_not_admitted_as_province_representative_benchmarks':True}
 (OUT/'VERIFICATION.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='checks'},ensure_ascii=False));assert result['all_passed']
if __name__=='__main__':main()
