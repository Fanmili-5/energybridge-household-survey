"""Seal scoped reference evidence, preserve empirical gaps and prior packages."""
import ast,collections,platform,shutil,subprocess,importlib.metadata
from common import *
OLD=['idf_joint_production_20261005','production_route_v6_20261004','benchmark_foundation_20261004','idf_unit_evidence_20261004','production_route_v5_20261004','end_to_end_plan_20261004','production_route_v4_20261003','construction_chain_20261003','household_housing_evidence_20261006','production_evidence_completion_20261006','joint_housing_service_worlds_20261006']
def main():
 guard();snapshot=OUT/'LATEST_BEFORE_OPERATIONAL_COMPLETION.json'
 if not snapshot.exists():shutil.copyfile(BASE/'LATEST.json',snapshot)
 before=read(snapshot);assert before['active_stage']=='production_route_v5_household_scope_tenure_conditionals_and_native_layout_evidence';old=[];inputs={}
 def add(p,expected=None):
  p=Path(p).resolve();h=sha(p)
  if isinstance(expected,dict):expected=expected['sha256']
  if expected:assert h==expected,'input_changed:'+str(p)
  inputs[str(p)]=h
 for name in OLD:
  p=BASE/name;m=read(p/'PACKAGE_MANIFEST.json')
  for n,h in m['files'].items():assert sha(p/n)==h,'old_package_changed:'+name+'/'+n
  old.append({'package':name,'files':len(m['files']),'manifest_sha256':sha(p/'PACKAGE_MANIFEST.json')});add(p/'PACKAGE_MANIFEST.json')
 assert sum(x['files'] for x in old)==28733
 for p,h in read(V10/'INPUT_LOCK.json')['files'].items():add(p,h)
 for r in read(V10/'SERVICE_PORT_BINDINGS.json')['records']:
  for pk,hk in [('service_world_path','service_world_sha256'),('service_IDF_path','service_IDF_sha256')]:add(V10/r[pk],r[hk])
  add(r['weather']['path'],r['weather']['sha256'])
 for r in read(V10/'JOINT_WORLD_BINDINGS.json')['records']:
  if r['one_storey_roof_ground']:add(V10/r['IDF_path'],r['IDF_sha256'])
 for name in ['SERVICE_PORT_BINDINGS.json','JOINT_WORLD_BINDINGS.json','GROUND_EXPERIMENT_SELECTION.json']:add(V10/name)
 for name in ['NATIVE_REFERENCE_REGISTRY.json','ADDITIONAL_REGIONAL_REFERENCES.json']:add(V8/name)
 for name in ['DEVICE_PRIOR_ROUTES1000.json']:add(V9/name)
 add(V7/'HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json');add(V7/'RUNTIME.json')
 for name in ['conv-people.R','conv-outdoor-air.R']:add(V10/'raw/destep_R_source'/name)
 for n in ['energyplus','Energy+.schema.epJSON','Documentation/InputOutputReference.pdf','Documentation/EngineeringReference.pdf','Documentation/EMSApplicationGuide.pdf']:add('/Applications/EnergyPlus-24-1-0/'+n)
 for r in read(OUT/'NATIVE_OCCUPANT_SOURCE189.json')['models']:add(r['source_path'],r['source_sha256'])
 events=read(OUT/'EVENT_RESULTS.json');occ=read(OUT/'OCCUPIED_RUNTIME_RESULTS1000.json');c=read(OUT/'COUPLED_UNIFORM_MINUTE_RESULTS.json');roles=read(OUT/'ROLE_PACKET_BINDINGS1000.json');g=read(OUT/'DIRECT_SQL_GROUND_CONVERGENCE61.json');iv=read(OUT/'INDEPENDENT_COMPLETION_VERIFICATION.json');ic=read(OUT/'INDEPENDENT_OCCUPIED_COUPLED_VERIFICATION.json');im=read(OUT/'INDEPENDENT_UNIFORM_MINUTE_VERIFICATION.json')
 assert len(events['pairs'])==200 and len(events['runs'])==400 and occ['inputs_run']==1000 and not occ['failures']
 assert c['inputs_run']==874 and len(c['pairs'])==437 and not c['failures']
 strict=read(OUT/'STRICT_HVAC_HISTORY_ADMISSION437.json');assert strict['both_reported_history_days_and_active_strict_admitted']==133 and strict['evaluation_day_only8_not_promoted_to_full_history_source_valid']==8
 assert g['passed']==61 and g['worst_finalyear_C']<=.1 and not iv['role_failures'] and not ic['verification_failures'] and not im['verification_failures']
 assert len(roles['records'])==1000 and roles['formal_human_answers']==0 and not roles['collection_release']
 for d in [iv,ic,im]:assert all(x['detected'] for x in d['negative_controls'])
 engine=Path('/Applications/EnergyPlus-24-1-0/energyplus');assert sha(engine)=='83511dd2626cfa4132134e93d5e9bc074ad567584187df2b313683e1be3d38e8'
 # Check current and all explicitly archived stage result inputs where a
 # runtime record has its own hashed paths. Archives have relocation maps;
 # their bytes are still sealed even when legacy relative paths are retained.
 runtime_records=events['runs']+occ['runs']+c['runs']+read(OUT/'GROUND_HISTORY_RESULTS.json')['runs']+read(OUT/'GROUND_EXTENDED_RESULTS.json')['runs']+read(OUT/'COUPLED_REFINED_RESULTS.json')['runs']
 for r in runtime_records:
  assert sha(OUT/r['IDF_path'])==r['IDF_sha256'] and sha(OUT/r['SQL_path'])==r['SQL_sha256'] and r['engine_sha256']==sha(engine)
  add(r['weather_path'],r['weather_sha256']) if 'weather_path' in r else add(r['weather']['path'],r['weather_sha256'])
 for r in roles['records']:
  for pk,hk in [('packet_path','packet_sha256'),('public_card_path','public_card_sha256'),('private_labels_path','private_labels_sha256')]:assert sha(OUT/r[pk])==r[hk]
 for path in OUT.glob('code/*.py'):
  tree=ast.parse(path.read_text(),filename=str(path));entry=any(isinstance(x,ast.If) and '__name__' in ast.unparse(x.test) for x in tree.body)
  if entry and path.name!='audit_manifest.py':
   main=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='main');assert any(isinstance(x,ast.Call) and isinstance(x.func,ast.Name) and x.func.id=='guard' for x in ast.walk(main)),path.name
 families=collections.Counter(('source_supported_active' if p['physical_source_QP_label_admitted_for_this_declared_emulator'] else 'source_supported_inactive' if p['source_domain_complete_both_variants'] else 'outside_source_domain') for p in c['pairs']);assert sum(families.values())==437
 current={'date_HKT':'2026-10-06','phase':'bounded_reference_pipeline_operational_evidence_and1000_role_review_candidates','target':'2020China city ordinary familyhouseholds;no towns/rural/collective/nonordinary','households':1000,'residents':2524,
  'occupied_reference_IDFs':1000,'roster_People_instances':2524,'occupied_runtime_inputs':1000,'occupied_runtime_severe_fatal':0,'occupied_warning_entries':21,
  'native_occupant_sources_re_read':189,'ground_cases':61,'ground_history_runs':132,'ground_initial_temperature_perturbation_within_declared_empty_scenario_complete':True,'ground_worst_finalyear_10vs30C_difference_C':g['worst_finalyear_C'],'ground_warning_entries':114,'occupied_or_measured_ground_calibrated':False,
  'component_tasks':200,'component_task_households':196,'component_final_runs':400,'positive_component_event_changes':59,'zero_component_event_changes':141,'component_final_severe_fatal':0,'component_final_warning_entries':12,'water_service_metric':'5minuteaverage internal draw outlet>=40C;not instantaneous actual shower','minimum_shifted_average_outlet_C':min(r['service']['min_draw_timestep_average_outlet_C'] for r in events['runs'] if r['service'] and r['variant']=='shifted'),
  'OEM_paired_HVAC_models':4,'OEM_graph_lines':10,'HVAC_source_parameter_candidate_households':437,'HVAC_final_uniform_timestep_minutes':1,'HVAC_final_uniform_runs':874,'HVAC_final_numerically_clean_pairs':437,'HVAC_final_severe_fatal':0,'HVAC_final_warning_entries':sum(len(r['warnings']) for r in c['runs']),
  'HVAC_final_coverage':dict(families),'HVAC_strict_reported_history_source_active_admitted':133,'HVAC_evaluation_day_only8_not_full_history_admitted':8,'HVAC_source_QP_mask_scope':'evaluationday July2;strict133 additionally require both reportedJuly1/2 source support;neither validates numericalwarmup as measured history','HVAC_QP_source_admission_not_full_latent_or_auto_controller_validation':True,'HVAC_original15minute_warmup_failed_households_retained':8,'HVAC_all8_finegrid_recovery_runs':16,'HVAC_uniform_recompute_after_development_not_blind_confirmatory':True,
  'role_review_packets':1000,'role_functional_condition_episodes':771,'role_information_elicitation_episodes':33,'role_no_adult':16,'role_material_schema_complete':True,'human_collection_and_benchmark_estimand_protocol_written':True,
  'complete_realistic_wholehousehold_IDFs':0,'complete_wholehome_actor_worlds':0,'human_role_reviews':0,'formal_human_answers':0,'empirical_national_household_energy_or_behavior_validated':False,'scientific_benchmark_release_admitted':False,'collection_release':False,'training_release':False,'activeV5_preserved':True,'prior11_sealed_files_unchanged':28733}
 save(OUT/'CURRENT.json',current)
 matrix=[
  {'item':'population_profile_generation','completion':'implemented_and_frozen','evidence':'V6/V7/V9 source controls and input locks','scope':'1000 marginal-calibrated synthetic city ordinary familyhouseholds','empirical_national_joint_identified':False},
  {'item':'roster_to_thermal_IDF','completion':'implemented_and_independently_checked_all1000','evidence':'OCCUPIED_REFERENCE_BINDINGS1000.json;INDEPENDENT_OCCUPIED_COUPLED_VERIFICATION.json','scope':'2524 exactPeople with source prototype thermal/moisture values and declared presence/air delivery','daily_diary_age_specific_metabolism_and_actual_ventilation_identified':False},
  {'item':'long_ground_history','completion':'passed_all61_with_frozen0_1C_test','evidence':'DIRECT_SQL_GROUND_CONVERGENCE61.json','scope':'initial10vs30C sensitivity in fixed empty cases,all original failures retained','other_ground_or_occupied_or_empirical_validation':False},
  {'item':'component_meter_and_state_pairing','completion':'implemented_and_checked200tasks','evidence':'EVENT_RESULTS.json;PAIRED_ENERGY_ACCOUNTING.json','scope':'wash/tank only,permission/operator/service context stipulated;zero cases retained','wholehome_actual_energy_or_acceptance':False},
  {'item':'source_specific_HVAC_coupling','completion':'implemented_all437_with_874_clean_uniform_minute_runs_and_source_masks','evidence':'COUPLED_UNIFORM_MINUTE_RESULTS.json;INDEPENDENT_UNIFORM_MINUTE_VERIFICATION.json;STRICT_HVAC_HISTORY_ADMISSION437.json','evaluation_day_source_domain_coverage':dict(families),'strict_both_reported_history_days_and_active_mask':133,'evaluation_day_only_conditional_diagnostics':8,'scope':'active totalsetP/netQ aggregate model with explicitly held ISOlatent split and designed dutycontroller;not wholehome or measured initialhistory','full_OEM_or_fullhousehold_HVAC_or_realhardware_identity':False},
  {'item':'role_material_production','completion':'implemented_all1000_review_candidates','evidence':'ROLE_PACKET_BINDINGS1000.json;COLLECTION_AND_BENCHMARK_PROTOCOL.md','scope':'196 componenttask roles+771 functionalcondition roles+33unknowninformation roles','human_comprehension_or_full_lifeworld_validation':False},
  {'item':'complete_wholehousehold_world','completion':'not_complete','missing':'full lighting/cooking/fuel/installeddevices,daily occupancy/services/permissions,fixture/plumbing/structural realization anduncertainty validation','how_to_close':'acquire appropriate measurements OR declare separate complete designed scenarios with explicit reference parameters and validate their target use;never copy historical missing values as0'},
  {'item':'national_real_energy_and_response','completion':'not_identified_from_current_inputs','missing':'target-time stock joint,inventories/diaries,independent wholehome/enduse observations andtransport/selection evidence','how_to_close':'additional targetframe observations;paper citations and source matching alone cannot identify'},
  {'item':'human_benchmark_release','completion':'not_complete','missing':'human card/task comprehension review,frozen formal allocation/analysis andreal actor responses','how_to_close':'use supplied assigned-role protocol,keep physics/behavior labels andactor/role clusters distinct','formal_answers_now':0}
 ]
 save(OUT/'ADMISSION_MATRIX.json',{'method_object':'population-marginal-calibrated synthetic profiles plus explicit residential/service reference scenarios and future assigned-role responses','status_dimensions_not_collapsed':True,'rows':matrix})
 save(OUT/'SCIENTIFIC_REVIEW.json',{'reviewer':'internal audit;no external reviewer endorsement','conclusion':'bounded construction and reference component-emulator method has primary sources,actual outputs,negative controls andtraceability;complete1000realistic homes/nationalenergy/humanbenchmark claims remain unsupported',
  'implementation_completion_is_not_empirical_identification':True,'major_repaired':['roster_people/moisture/unit matching','all61ground initialization history','pre-intervention state pairing','draw clock/tank finalstate/energy ledger','OEMindoor+outdoor Q/P versus mechanicalOutput','no performance curve extrapolation','EMS same-step physical actuation','controller timestep/warmup failure retention and uniform recompute','1000role unknown masks andexplicit behavioral estimand'],
  'remaining_major_scope_gates':[r for r in matrix if r['completion'] in ['not_complete','not_identified_from_current_inputs']],
  'publication_wording_allowed':'1000 marginal-calibrated synthetic city ordinary roles with traced reference housing,controlled occupancy andcovered component-emulator tasks;future assigned-role judgments',
  'publication_wording_disallowed':['1000 observed representative Chinese homes','1000 fullrealistic household IDFs','empirically validated national wholehome energy','OEMauto inverter physically validated','1000 human answers or accepted consent','all failures eliminated from historical evidence']})
 downloads=read(OUT/'PRIMARY_DOWNLOADS.json')
 for r in downloads['sources']:
  if 'original_manufacturer_host' in r:r['original_primary_host']=r.pop('original_manufacturer_host')
 save(OUT/'PRIMARY_DOWNLOADS.json',downloads)
 parameter_candidates=read(OUT/'ADDITIONAL_HVAC_PARAMETER_CANDIDATES1000.json');parameter_candidates['technical_followup_current_results']='COUPLED_UNIFORM_MINUTE_RESULTS.json';parameter_candidates['strict_scientific_source_history_masks']='STRICT_HVAC_HISTORY_ADMISSION437.json';parameter_candidates['candidate_identity_is_not_observed_actual_installation']=True
 for r in parameter_candidates['records']:
  for p in r['supported_reference_parameter_candidates']:p['status']='reference_parameter_candidate;paired technicalsource/implementation resolved in companion where masked;actual installation andfullOEMlatent/automaticgovernor not identified'
 save(OUT/'ADDITIONAL_HVAC_PARAMETER_CANDIDATES1000.json',parameter_candidates)
 sources=[{'id':'inherited_census_CHFS_CRECS_prototypes_geometry_and_OEMports','source_registers':[{'path':str((p/'SOURCE_REGISTER.json').relative_to(BASE)),'sha256':sha(p/'SOURCE_REGISTER.json')} for p in [V7,V8,V9,V10]],'source_years':'census2020;CHFS2021;CRECS2012;prototype/originalOEMyears individually retained','use':'unchanged source-specific scopes;not newer empirical ownership/behavior'},
  {'id':'Mitsubishi_OBH789','URL':'https://library.mitsubishielectric.co.uk/pdf/download_full/3756','path':'raw/Mitsubishi_OBH789.pdf','sha256':sha(OUT/'raw/Mitsubishi_OBH789.pdf'),'pages1based':[6,15,16,17],'read_scope':'full PDFtext;performance/specification pages inspected;vector extraction15/16','used':'4model nominalnetQ/totalsetP and ratedfrequency temperature corrections','not_identified':'auto governor,full latent map,actual role household hardware'},
  {'id':'Mitsubishi_OBH788','URL':'https://library.mitsubishielectric.co.uk/pdf/download_full/3755','path':'raw/Mitsubishi_OBH788.pdf','sha256':sha(OUT/'raw/Mitsubishi_OBH788.pdf'),'pages1based':[4,12],'read_scope':'full text andvisual specification p4','used':'matchedindoorfanflow/input andcool command range;functionalcontrol caveats','not_identified':'full airside/refrigerant model or actual installation/permissions'},
  {'id':'native_Occupant189','catalog':'NATIVE_OCCUPANT_SOURCE189.json','used':'actual bedroom gain table,unit/distribution values;not source densities as syntheticresidentcounts','converter_commit':'1d93a51c5dd6a48e0a108d9646f00a496f23d1ec','converter_files':'V10raw/destep_R_source/conv-people.R53–118;conv-outdoor-air.R'},
  {'id':'EnergyPlus24_1_official_installed','paths':['/Applications/EnergyPlus-24-1-0/Documentation/InputOutputReference.pdf','/Applications/EnergyPlus-24-1-0/Documentation/EngineeringReference.pdf','/Applications/EnergyPlus-24-1-0/Documentation/EMSApplicationGuide.pdf'],'locations':'IO1.14.10 OtherEquipment,1.24.2.2.2 finaltanktemperature,2.28 tankenergy;Engineering3.11.7 Kiva;EMSinternalgainactuators andcallpoints','use':'documented implementation/initialization semantics,not physical household field validation'},
  {'id':'WaterThermalTanks_fixed_source','URL':'https://raw.githubusercontent.com/NREL/EnergyPlus/v24.1.0/src/EnergyPlus/WaterThermalTanks.cc','path':'raw/WaterThermalTanks_v24_1.cc','sha256':sha(OUT/'raw/WaterThermalTanks_v24_1.cc'),'locations':'mass/density around6885;net signedenergy around7410','use':'exact native signedthermal accounting'},
  {'id':'BOPTEST2021','URL':'https://www.pnnl.gov/publications/building-optimization-testing-framework-boptest-simulation-based-benchmarking-control','path':'raw/BOPTEST_PNNL.html','sha256':sha(OUT/'raw/BOPTEST_PNNL.html'),'DOI':'10.1080/19401493.2021.1986574','citation':'Blum etal2021.JBPS14(5)586–610','read_scope':'originalresearchinstitution abstract/citation only;PDFnotretrieved','use':'explicit emulators,controls andKPI design rationale;not Chinaorours validation'},
  {'id':'procedural_review_skill','citation':'Kassis T.,Agarwal V.,He Y.,Patel D.,Brueckner A.M.(2026).Scientific Agent Skills:A Library of Procedural Knowledge for Research Agents','URL':'https://arxiv.org/abs/2609.00065','version':'v2,2026-09-02','use':'procedural evidence critique;not population/physical authority'}]
 save(OUT/'SOURCE_REGISTER.json',{'date_HKT':'2026-10-06','review_type':'directed originalsource verification,not systematic review','sources':sources,'download_attempts':downloads,'rejected_material':[{'id':'Daikin_HK_technical104','path':'raw/Daikin_HK_technical104.pdf','reason':'multi-split indoor combinations and nominal data not singlesplit expanded Q/P curves'}],'other_failed_retrievals':'raw/additional_sources.manifest.json;no index/abstract relabelled fullpaperread'})
 versions={}
 for n in ['numpy','pandas','pypdf','requests','shapely','access-parser-c']:
  try:versions[n]=importlib.metadata.version(n)
  except importlib.metadata.PackageNotFoundError:versions[n]='distribution_metadata_unavailable;inherited stablePYTHONPATH and actual imported runtime used'
 add(sys.executable)
 save(OUT/'RUNTIME.json',{'Python_executable':sys.executable,'Python_executable_sha256':sha(sys.executable),'Python_version':platform.python_version(),'platform':platform.platform(),'stable_PYTHONPATH':read(V7/'RUNTIME.json')['stable_PYTHONPATH'],'libraries':versions,'EnergyPlus_version':subprocess.run([str(engine),'--version'],capture_output=True,text=True,check=True).stdout.strip(),'engine_sha256':sha(engine),'new_packages_installed':False})
 save(OUT/'INPUT_LOCK.json',{'files':inputs,'transitive_previous_input_closure_inherited_and_checked':True,'actual_immediate_sources_added':True,'new_cached_primary_sources_are_manifest_members':True,'not_externalpublication_of_private_microdata':True})
 save(OUT/'INTEGRITY.json',{'prior_sealed_packages':old,'prior_sealed_files_verified_unchanged':28733,'actual_and_transitive_external_inputs_checked':len(inputs),'current_runtime_input_SQL_engine_weather_hashes_checked':len(runtime_records),'all1000role_packet_card_private_label_hashes_checked':True,'AST_and_write_entrypoint_guards_checked':True,'activeV5_preserved':True,'all_development_failures_and_zero_unsupported_results_retained':True})
 report=(OUT/'METHODS_AND_RESULTS.md').read_text()
 for token in ['2524','132','0.091815338','45.976973','0.271698113','4.656612873','完整户级IDF=0','28733','Scientific Agent Skills']:assert token in report,token
 assert read(BASE/'LATEST.json')==before,'LATEST changed during stage'
 files={str(p.relative_to(OUT)):sha(p) for p in sorted(OUT.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.name!='PACKAGE_MANIFEST.json'}
 save(OUT/'PACKAGE_MANIFEST.json',{'schema':'research_evidence_package_v1','date_HKT':'2026-10-06','files':files,'collection_release':False,'training_release':False})
 latest=read(BASE/'LATEST.json');latest['operational_evidence_completion_v11']={**current,'report':str((OUT/'METHODS_AND_RESULTS.md').relative_to(BASE)),'current':str((OUT/'CURRENT.json').relative_to(BASE)),'admission_matrix':str((OUT/'ADMISSION_MATRIX.json').relative_to(BASE)),'human_protocol':str((OUT/'COLLECTION_AND_BENCHMARK_PROTOCOL.md').relative_to(BASE)),'manifest_sha256':sha(OUT/'PACKAGE_MANIFEST.json'),'package_files':len(files)};save(BASE/'LATEST.json',latest)
 print({'files_sealed':len(files),'inputs':len(inputs),'old_unchanged':28733,'manifest_sha256':sha(OUT/'PACKAGE_MANIFEST.json'),'current_HVAC_coverage':dict(families),'activeV5_preserved':True})
if __name__=='__main__':main()
