"""Verify actual old packages/inputs, write bounded review and seal new package.
Active V5 is preserved. Only a research attachment is added to LATEST.
"""
import ast,hashlib,json,shutil
from pathlib import Path
OUT=Path(__file__).resolve().parent.parent;BASE=OUT.parent;V7=BASE/'idf_joint_production_20261005';V8=BASE/'household_housing_evidence_20261006'
OLD=['idf_joint_production_20261005','production_route_v6_20261004','benchmark_foundation_20261004','idf_unit_evidence_20261004','production_route_v5_20261004','end_to_end_plan_20261004','production_route_v4_20261003','construction_chain_20261003','household_housing_evidence_20261006']
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text())
def save(name,d):(OUT/name).write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def main():
 if (OUT/'PACKAGE_MANIFEST.json').exists():raise SystemExit('sealed;use audit_manifest.py for read-only checks')
 snapshot=OUT/'LATEST_BEFORE_PRODUCTION_EVIDENCE.json'
 if not snapshot.exists():shutil.copyfile(BASE/'LATEST.json',snapshot)
 before=read(snapshot);assert before['active_stage']=='production_route_v5_household_scope_tenure_conditionals_and_native_layout_evidence'
 old=[];inputs={}
 def add(p,expected=None):
  p=Path(p).resolve();h=sha(p)
  if isinstance(expected,dict):expected=expected['sha256']
  if expected:assert h==expected,'changed_actual_input:'+str(p)
  inputs[str(p)]=h
 for folder in OLD:
  path=BASE/folder;manifest=read(path/'PACKAGE_MANIFEST.json')
  for name,h in manifest['files'].items():assert sha(path/name)==h,folder+'/'+name
  add(path/'PACKAGE_MANIFEST.json');old.append({'package':folder,'files':len(manifest['files']),'manifest_sha256':sha(path/'PACKAGE_MANIFEST.json')})
 assert sum(r['files'] for r in old)==10803
 for p,h in read(V8/'INPUT_LOCK.json')['files'].items():add(p,h)
 for name in ['HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json','RUNTIME.json','code/reference_world.py','code/compile_reference_idfs.py']:add(V7/name)
 for p in V7.glob('worlds/*.json'):add(p)
 for p in V7.glob('reference_idfs/*.idf'):add(p)
 for p in V8.rglob('*'):
  if p.is_file() and ('__pycache__' not in p.parts) and p.suffix in ['.py','.json']:add(p)
 for p in (BASE/'crecs_admission_20261003/private_raw').glob('CRECS2012.*'):add(p)
 for p in (BASE/'crecs_admission_20261003/private_metadata').glob('CRECS2012*'):add(p)
 # The copied primary source tables/cached public evidence are in this package
 # manifest; original source input tables are independently locked as well.
 for k in ['B0901a','B0902a','B0903a','B0904a','B0906a']:
  orig=BASE/'evidence_contract_20261001/raw'/(k+'.xls');add(orig);assert sha(orig)==sha(OUT/'raw'/(k+'.xls'))
 save('INPUT_LOCK.json',{'files':inputs,'actual_external_inputs_hash_checked_now':True,'new_cached_sources_and_outputs_are_manifest_members':True,
  'source_private_microdata_not_published':True,'private_sourceIDs_not_exported_into_generated_reference_profiles':True})
 runtime=read(V7/'RUNTIME.json');save('RUNTIME.json',{'stable_PYTHONPATH':runtime['stable_PYTHONPATH'],'python':'/Users/fanmili/studytest/.venv/bin/python',
  'energyplus':'/Applications/EnergyPlus-24-1-0/energyplus','source_runtime_readonly':'../idf_joint_production_20261005/RUNTIME.json',
  'new_packages_installed':False,'source_parser_or_engine_versions_changed':False})
 assert read(OUT/'VERIFICATION.json')['all_passed']
 for p in OUT.glob('code/*.py'):
  t=p.read_text();ast.parse(t,filename=str(p))
  if p.name!='audit_manifest.py':assert 'PACKAGE_MANIFEST.json' in t,'missing_seal_guard:'+p.name
 components=read(OUT/'COMPONENT_MODEL_VERIFICATION.json');glaze=read(OUT/'GLAZING_PROVENANCE.json');pilot=read(OUT/'GLAZING_PILOT_RESULTS.json');production=read(OUT/'PRODUCTION_REFERENCE1000.json');sleep=read(OUT/'INDEPENDENT_SLEEP_VERIFICATION.json')
 current={'date_HKT':'2026-10-06','phase':'official_controls_and_specific_appliance_and_reference_model_production_contract',
  'fixed_households':1000,'fixed_residents':2524,'official_province_feature_controls':310,'reference_couplings':3,'sharp_two_event_bounds':6,
  'weighted_national_new_marginal_error_percentage_points':read(OUT/'VERIFICATION.json')['weighted_national_marginal_error_percentage_points'],
  'reference_sleep0_6m_verified':sleep['counts']['verified_witness_baseline0_6m'],'reference_sleep0_8m_verified':sleep['counts']['verified_witness_alternative0_8m'],
  'original_used_native_window_types_traced':glaze['original_used_native_types_traced'],'optical_pair_fields_quarantined_models':glaze['models_with_quarantined_optical_pairs'],
  'new_glazing_empty_shell_runs':pilot['empty_shell_runs'],'new_glazing_severe_fatal':pilot['severe_fatal'],'new_glazing_warning_entries':pilot['warning_entries'],
  'component_semantic_and_units_controls':len(components['checks']),'specific_historical_device_routes':1000,
  'reference_component_candidate_households':production['summary']['source_specific_reference_ports_households'],
  'one_storey_requires_new_boundary_cases':61,'no_default_adult_operator_cases':16,
  'production_evidence_contract_traceable':True,'whole_joint_housing_facility_device_world_assembled':False,
  'complete_household_IDFs':0,'complete_actor_packages':0,'formal_human_answers':0,'scientific_benchmark_admitted':False,
  'actual_population_stock_joint_or_physical_energy_calibrated':False,'collection_release':False,'training_release':False,
  'active_V5_not_replaced':True,'prior9_sealed_packages_unchanged':True}
 save('CURRENT.json',current)
 review={'reviewer_position':'internal evidence and method audit, not external endorsement',
  'methodological_improvements_supported':['official city ordinary frame ten-feature controls','typed source unit and branch interpretation',
   'specified unknown couplings and sharp two-event bounds','exact checked reference geometry sleeping witnesses','traceable native scalar window reference',
   'historical same-record specific positive appliance reports','source test-condition component kernels and operation legality','1000 co-registered guarded production specifications'],
  'remaining_material_execution_gates':[{'priority':'blocking_for_complete_IDF','issue':'housing facets/facility rights/building exposure/native parameters must be jointly recompiled and geometry+sleep rechecked','known_cases':'61 one-storey old-midfloor rejection plus missing/shared/none facilities'},
   {'priority':'blocking_for_actor_and_load_benchmark','issue':'resolve installed instance identity/fuel/meters/operator presence and authorization/tasks','known_cases':'16 profiles no adult operator;only340 with selected source-compatible reference ports'},
   {'priority':'blocking_for_real_stock_energy_claim','issue':'independent whole-home/enduse calibration plus geographic/year/frame sensitivity','known_cases':'8 empty-shell runs and16 component controls are implementation evidence only'},
   {'priority':'blocking_for_behavior_claim','issue':'formal human assigned-role responses and collection/evaluation protocol','known_cases':'formal_human_answers0'}],
  'unidentifiable_truth_is_not_resolved_by_more_authoritative_citations':True,
  'admission_now':'bounded reference-production method and evidence contract;not complete calibrated whole-home or human benchmark',
  'publication_wording':'population-marginal-calibrated synthetic city ordinary-household reference profiles and explicitly specified experimental residential/service worlds',
  'national2020_real_joint_or_scope_all_China_claim_allowed':False}
 save('SCIENTIFIC_REVIEW.json',review)
 save('INTEGRITY.json',{'prior_sealed_packages':old,'prior_sealed_files_verified_unchanged':10803,
  'actual_external_input_files_hash_checked':len(inputs),'active_V5_preserved':True,'Python_AST_and_write_entrypoint_guards_passed':True,
  'new_package_is_research_only':True,'source_cache_failures_retained':True})
 report=(OUT/'METHODS_AND_RESULTS.md').read_text()
 for token in ['310','2524','0.0637616','78.7967','998','923','189','187','24条warning','0.1455625','1327','61户','16户','340户','10803','完整户级IDF=0']:
  assert token in report,'report_metric_missing:'+token
 files={str(p.relative_to(OUT)):sha(p) for p in sorted(OUT.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.name!='PACKAGE_MANIFEST.json'}
 save('PACKAGE_MANIFEST.json',{'schema':'research_evidence_package_v1','date_HKT':'2026-10-06','files':files,'collection_release':False,'training_release':False})
 latest=read(BASE/'LATEST.json');assert latest==before,'LATEST_changed_during_run'
 latest['production_evidence_completion_v9']={**current,'report':str((OUT/'METHODS_AND_RESULTS.md').relative_to(BASE)),
  'current':str((OUT/'CURRENT.json').relative_to(BASE)),'production_contract':str((OUT/'PRODUCTION_CONTRACT.json').relative_to(BASE)),
  'reference_specs':str((OUT/'PRODUCTION_REFERENCE1000.json').relative_to(BASE)),
  'review':str((OUT/'SCIENTIFIC_REVIEW.json').relative_to(BASE)),'manifest_sha256':sha(OUT/'PACKAGE_MANIFEST.json'),'package_files':len(files)}
 (BASE/'LATEST.json').write_text(json.dumps(latest,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
 assert read(BASE/'LATEST.json')['active_stage']==before['active_stage']
 print(json.dumps({'new_package_files':len(files),'input_files':len(inputs),'old_sealed_files_unchanged':10803,
  'manifest_sha256':sha(OUT/'PACKAGE_MANIFEST.json'),'active_V5_preserved':True,'scientific_benchmark_admitted':False},ensure_ascii=False))
if __name__=='__main__':main()
