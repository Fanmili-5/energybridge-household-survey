"""Seal bounded joint reference evidence; preserve earlier packages and activeV5."""
import ast,collections,shutil,platform,subprocess
from common import *
OLD=['idf_joint_production_20261005','production_route_v6_20261004','benchmark_foundation_20261004','idf_unit_evidence_20261004',
 'production_route_v5_20261004','end_to_end_plan_20261004','production_route_v4_20261003','construction_chain_20261003',
 'household_housing_evidence_20261006','production_evidence_completion_20261006']
def main():
 guard();snapshot=OUT/'LATEST_BEFORE_JOINT_WORLDS.json'
 if not snapshot.exists():shutil.copyfile(BASE/'LATEST.json',snapshot)
 before=read(snapshot);assert before['active_stage']=='production_route_v5_household_scope_tenure_conditionals_and_native_layout_evidence'
 old=[];inputs={}
 def add(p,expected=None):
  p=Path(p).resolve();h=sha(p)
  if isinstance(expected,dict):expected=expected['sha256']
  if expected:assert h==expected,'actual_input_changed:'+str(p)
  inputs[str(p)]=h
 for folder in OLD:
  path=BASE/folder;manifest=read(path/'PACKAGE_MANIFEST.json')
  for name,h in manifest['files'].items():assert sha(path/name)==h,folder+'/'+name
  add(path/'PACKAGE_MANIFEST.json');old.append({'package':folder,'files':len(manifest['files']),'manifest_sha256':sha(path/'PACKAGE_MANIFEST.json')})
 assert sum(x['files'] for x in old)==11175
 for p,h in read(V9/'INPUT_LOCK.json')['files'].items():add(p,h)
 # Lock actual immediate inherited sources too, including reference catalogues,
 # original OEM primary documents and helper code used by this stage.
 for name,h in read(V9/'PACKAGE_MANIFEST.json')['files'].items():add(V9/name,h)
 for model in read(OUT/'HORIZONTAL_SOURCE_ADMISSION.json')['models']:add(model['native_path'],model['native_sha256'])
 b=read(OUT/'JOINT_WORLD_BINDINGS.json');s=read(OUT/'SERVICE_PORT_BINDINGS.json');j=read(OUT/'JOINT_RUNTIME_RESULTS.json');ind=read(OUT/'INDEPENDENT_JOINT_VERIFICATION.json');g=read(OUT/'GROUND_SENSITIVITY.json');wash=read(OUT/'WASH_CLOCK_EXPERIMENT.json');design=read(OUT/'HISTORICAL_DESIGN_SCREEN.json');area=read(OUT/'INDEPENDENT_AREA_SENSITIVITY_VERIFICATION.json')
 assert b['assembled']==1000 and not b['failures_retained'] and not ind['failures'] and all(x['detected'] for x in ind['negative_controls'])
 assert not read(OUT/'INDEPENDENT_HORIZONTAL_VERIFICATION.json')['failures'] and not area['failures'] and area['negative_control']['detected']
 keys=collections.defaultdict(set)
 for r in s['records']:
  add(r['weather']['path'],r['weather']['sha256'])
  for pathkey,hashkey in [('world_path','world_sha256'),('service_world_path','service_world_sha256'),('IDF_path','IDF_sha256'),('service_IDF_path','service_IDF_sha256')]:assert sha(OUT/r[pathkey])==r[hashkey]
  c=read(OUT/r['service_world_path']);assert not c['all_ten_stock_facets_physically_realized_or_validated'] and not c['whole_home_devices_people_and_services_complete']
  keys[r['service_IDF_sha256']+'__'+r['weather']['sha256']].add(r['household_id'])
 engine=Path('/Applications/EnergyPlus-24-1-0/energyplus');enginehash=sha(engine);assert enginehash=='83511dd2626cfa4132134e93d5e9bc074ad567584187df2b313683e1be3d38e8'
 for r in j['unique_runs']:
  assert set(r['household_IDs'])==keys.pop(r['group_key']) and not r['failed'] and not r['fatal_severe'] and r['returncode']==0
  assert r['engine_sha256']==enginehash and sha(OUT/r['source_service_IDF'])==r['source_IDF_sha256'] and sha(OUT/r['run_path']/'eplusout.sql')==r['SQL_sha256']
 assert not keys and j['summary']['unique_inputs_run']==984 and j['summary']['households_covered']==1000
 for case in wash['cases']+[x for w in g['worlds'] for x in w['cases']]:
  folder=OUT/case['run_path'];assert sha(folder/'eplusout.sql')==case['SQL_sha256'] and sha(folder.parent/'input.idf')==case['IDF_sha256'] and case['returncode']==0 and case['severe_fatal']==0
 assert all(x['rejected'] for x in wash['negative_legality_controls']) and len(wash['cases'])==3 and g['runs']==10
 for case in wash['cases'][:2]:assert not case['warnings'] and abs(case['wash_cycle_energy_kWh']-.72)<1e-9
 assert wash['cases'][2]['relative_cycle_energy_error_vs_OEM_test']>.05
 for name in ['energyplus','Energy+.schema.epJSON','Documentation/InputOutputReference.pdf','Documentation/EngineeringReference.pdf']:add('/Applications/EnergyPlus-24-1-0/'+name)
 add(V7/'RUNTIME.json');add(V7/'HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json')
 for path in OUT.glob('code/*.py'):
  node=ast.parse(path.read_text(),filename=str(path));entry=any(isinstance(x,ast.If) and '__name__' in ast.unparse(x.test) for x in node.body)
  if entry and path.name!='audit_manifest.py':
   main=next(x for x in node.body if isinstance(x,ast.FunctionDef) and x.name=='main');assert any(isinstance(x,ast.Call) and isinstance(x.func,ast.Name) and x.func.id=='guard' for x in ast.walk(main)),path.name
 version=subprocess.run([str(engine),'--version'],capture_output=True,text=True,check=True).stdout.strip()
 save(OUT/'RUNTIME.json',{'python':sys.executable,'Python_version':platform.python_version(),'platform':platform.platform(),'stable_PYTHONPATH':read(V7/'RUNTIME.json')['stable_PYTHONPATH'],
  'EnergyPlus_version':version,'engine_sha256':enginehash,'new_packages_installed':False,'parent_runtime_readonly':'../idf_joint_production_20261005/RUNTIME.json'})
 save(OUT/'INPUT_LOCK.json',{'files':inputs,'actual_external_inputs_hash_checked_now':True,'cached_new_primary_sources_and_outputs_are_new_manifest_members':True,
  'no_private_microdata_published':True,'inherited_actual_input_hashes_checked_and_explicit_immediate_sources_added':True})
 sources=[
  {'id':'census2020_scheme','original_author':'National Bureau of Statistics and State Council Seventh Census Office','URL':'https://www.fuzhou.gov.cn/book/fztjnj/2020rkpcnj/fzrp2020/htms/347.htm','cached':'raw/census2020_scheme_Fuzhou.html','sha256':sha(OUT/'raw/census2020_scheme_Fuzhou.html'),
   'locations':'H6/H7 filling explanation;long-form H8-H17 definitions;extracted text lines893-900,992-1009','used_for':'area counting and facility meaning','cannot_identify':'actual unit/external-common split,fixture type,size,plumbing pressure,stock joint,energy/control rights'},
  {'id':'GB50096_2011_committee','original_author':'National GB50096-2011 standard preparation committee,January2012','URL':read(OUT/'raw/GB50096_2011_committee_explanation.manifest.json')['URL'],'cached':'raw/GB50096_2011_committee_explanation.pdf','sha256':sha(OUT/'raw/GB50096_2011_committee_explanation.pdf'),
   'PDF_pages_1based':[17,25,28,29,30,31,32],'used_for':'historical selected design comparisons and scope;not current certification','cannot_identify':'all2020 occupied stock legality,full reference world design conformity'},
  {'id':'destep_original_converter','original_author':'hongyuanjia/destep source','URL':read(OUT/'raw/destep_pinned.manifest.json')['URL'],'commit':'1d93a51c5dd6a48e0a108d9646f00a496f23d1ec','cached':'raw/destep_pinned.tar.gz','sha256':sha(OUT/'raw/destep_pinned.tar.gz'),
   'locations':'conv-const.R154-170 and211-253 namespaces;356 ordering;433-454 SIDE1 reversal','used_for':'KIND3/4/5 naming and layer schema','execution':'R source read only,not executed','cannot_identify':'asbuilt surface layer direction or actual household geometry'},
  {'id':'native_Access189','input_registry':'HORIZONTAL_SOURCE_ADMISSION.json','independent_check':'INDEPENDENT_HORIZONTAL_VERIFICATION.json','used_for':'189 actual used horizontal3/4/5 constructions567records,scalar layers','cannot_identify':'actualhouse stock frequencies/frame mechanics/asbuilt energy'},
  {'id':'EnergyPlus24_1','local_primary_docs':['/Applications/EnergyPlus-24-1-0/Documentation/InputOutputReference.pdf','/Applications/EnergyPlus-24-1-0/Documentation/EngineeringReference.pdf'],
   'official_URL':'https://energyplus.net/assets/nrel_custom/pdfs/pdfs_v24.1.0/InputOutputReference.pdf','locations':'IO1.8.11.1.6 ScheduleAverage,1.11.9/10 Kiva;Engineering3.11 initialization','used_for':'object legality,units,solver and timestep semantics','cannot_identify':'Chinese soil,product calibration,stabilized ground,actual whole-home energy'},
  {'id':'IKEA_worktop2024','original_author':'IKEA','URL':read(OUT/'raw/IKEA_worktop_primary2024.manifest.json')['URL'],'cached':'raw/IKEA_worktop_primary2024.pdf','sha256':sha(OUT/'raw/IKEA_worktop_primary2024.pdf'),
   'PDF_pages_1based':[96],'visual_readback':'raw/IKEA_worktop_primary2024_p96.png','used_for':'SKU00479874 LILLTRASK1.23x0.635m footprint','cannot_identify':'Chinese2020 fixture frequency/full installed kitchen functions'},
  {'id':'sealedV9_sources','input_package':'../production_evidence_completion_20261006/PACKAGE_MANIFEST.json','used_for':'official310controls,historical CRECS2012 same-record reports,specific OEM program energy/body sizes,bunk restrictions and partial operation kernels',
   'cannot_identify':'2012-to2020 target transport,full hardware identity/timeuse,whole-home energy'},
  {'id':'An2023','authors':['Jingjing An','Yi Wu','Chenxi Gui','Da Yan'],'title':'Chinese prototype building models for simulating the energy performance of the nationwide building stock','year':2023,'journal':'Building Simulation','volume':16,'issue':8,'pages':'1559-1582','DOI':'10.1007/s12273-023-1058-5','URL':'https://www.sciopen.com/article/10.1007/s12273-023-1058-5',
   'read_boundary':'publisher abstract and metadata refreshed;underlying native models inspected separately','used_for':'Chinese prototype parameter method background,not1000 sample size proof'},
  {'id':'procedural_review_skill','authors_initials':['T. Kassis','V. Agarwal','Y. He','D. Patel','A. M. Brueckner'],'URL':'https://arxiv.org/abs/2609.00065','year':2026,'latest_checked_version':'v2','date':'2026-09-02',
   'used_for':'procedural source/assumption/evidence critique only;not Chinese population or physical authority'}]
 save(OUT/'SOURCE_REGISTER.json',{'date_HKT':'2026-10-06','review_type':'targeted primary source verification,not systematic review','sources':sources,
  'source_failure_log':[{'URL':'https://api.github.com/repos/hongyuanjia/destep','status':'HTTP403 observed in session;response not archived','resolution':'exact pinned codeload archive fetched and hashed,no source execution'},
   {'URL':'https://nj.tjj.beijing.gov.cn/tjnj/rkpc-2020/e/zk/html/fu06.pdf','status':'requests SSL retrieval failure observed;no PDF cached','resolution':'official Fuzhou full scheme cached and read'},
   {'URL':'https://www.ikea.com/at/en/p/lilltraesk-worktop-white-laminate-00479874/','status':'direct browser opening failure','resolution':'original IKEA2024 guide PDFp96 visually read'},
   {'stage':'Fuzhou local extraction','status':'bs4 not installed;HTML had already been cached','resolution':'stdlib HTMLParser used,no install'}]})
 groundmax={name:max(x['max_abs_zone_hourly_difference_from_baseline_C'] for w in g['worlds'] for x in w['cases'] if x['scenario']==name) for name in ['soil_k0_5','soil_k1_5','side_exposed','initial10C']}
 current={'date_HKT':'2026-10-06','phase':'executed_joint_area_rights_sleep_exposure_and_partial_device_reference_worlds','households':1000,'residents':2524,
  'compiled_reference_housing_worlds':1000,'native_models_checked':189,'horizontal_kind_records_checked':567,'source_models_selected':len({r['source_model_key'] for r in b['records']}),
  'one_storey_roof_ground_worlds':61,'no_adult_default_manual_disabled':16,'reference_device_households':239,'reference_device_ports':244,
  'port_counts':{'washer_program':30,'refrigerator_label_mean':44,'water_heater_standby':170},'kitchen_worktop_witnesses':969,
  'unique_IDF_weather_inputs_run':984,'runtime_severe_fatal':0,'runtime_warning_entries':21,'warning_identity':'Lhasa time zone versus meridian difference2.0',
  'independent_joint_check_failures':0,'joint_negative_controls_detected':5,'independent_stress_negative_controls_detected':1,
  'H6_external_common_area_stress':area['scenarios'],'historical_design_screen_households_below':design['households_below_by_criterion'],
  'ground_empty_shell_diagnostic_runs':10,'ground_max_scenario_difference_C':groundmax,'ground_initialization_stable_or_calibrated':False,
  'wash_clock_runs':3,'wash_cycle_kWh_preserved':.72,'wash_defaultNo_negative_relative_error':wash['cases'][2]['relative_cycle_energy_error_vs_OEM_test'],
  'all_ten_stock_facets_physically_realized':False,'complete_household_IDFs':0,'complete_actor_packages':0,'formal_human_answers':0,
  'empirical_population_joint_or_full_energy_calibrated':False,'scientific_benchmark_admitted':False,'collection_release':False,'training_release':False,
  'active_V5_not_replaced':True,'prior10_sealed_files_unchanged':11175}
 save(OUT/'CURRENT.json',current)
 review={'reviewer_position':'internal evidence audit,not external endorsement','admitted_now':'covered partial experimental reference worlds with explicit source identities and independent implementation checks',
  'sustainable_benchmark_route':'population-marginal-calibrated synthetic city ordinary households plus explicit residential/service experimental scenarios and later assigned-role response observations',
  'repaired':['KIND4/5 source namespace error','separate common/private area,kitchen use andenergy allocation','exact recompiled geometry and operator gates','one-storey ground/roof exposure','physically placed and scoped OEM reference ports','minute clock Average and energy oracle','separate historical design comparison and2020stock eligibility'],
  'remaining_major_gates':[
   {'gate':'complete_household_services','status':'not_met','missing':'complete kitchen/WC/shower/drainage,fuel and hardware/meters/permissions,People/tasks/full HVAC,structural-facet realization'},
   {'gate':'physical_identification','status':'not_met','missing':'H6 externalcommon/unit split,actual unit storey/side exposure/layer orientation/measured parameters','evidence':'gamma20pct finite grammar fails5;chosen design screens below criteria retained'},
   {'gate':'long_term_ground_initialization','status':'not_met','missing':'stabilization or sensitivity under season/year scenarios andindependent observations','evidence':'two preselected empty shells initial setting max8.0519509653C difference'},
   {'gate':'national_real_energy_stock','status':'not_met','missing':'2012 appliance target transportation,unidentified joint relationships,independent wholehome/enduse calibration'},
   {'gate':'actor_human_response_benchmark','status':'not_met','missing':'complete role/task rights and collection/evaluation protocol,formalhuman responses'}],
  'no_new_authoritative_citation_can_identify_missing_household_joint_or_permission_by_itself':True,
  'publication_wording_allowed':'executed experimental reference residential worlds covering stated geometry/facility-right/exposure and selected service components',
  'publication_wording_disallowed':['1000observed representative actual Chinese homes','fullnational household energybenchmark','allfeatures physicaltruth','calibratedground or realHVAC energy','humanconsent/willingness']}
 save(OUT/'SCIENTIFIC_REVIEW.json',review)
 save(OUT/'INTEGRITY.json',{'prior_sealed_packages':old,'prior_sealed_files_verified_unchanged':11175,'actual_external_inputs_checked':len(inputs),
  'all_final_binding_IDF_and_world_hashes_checked':True,'all984_run_input_engine_and_SQL_hashes_checked':True,'13_component_ground_run_input_and_SQL_hashes_checked':True,
  'AST_and_write_entrypoint_guards_passed':True,'active_V5_preserved':True,'input_metadata_updates_did_not_change_runtime_IDF_bytes':True})
 report=(OUT/'METHODS_AND_RESULTS.md').read_text()
 for token in ['2524','984','239','244','567','8.051951','995','5.660377','完整户级IDF=0','11175','KIND4']:
  assert token in report,'report_value_missing:'+token
 files={str(p.relative_to(OUT)):sha(p) for p in sorted(OUT.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.name!='PACKAGE_MANIFEST.json'}
 assert read(BASE/'LATEST.json')==before,'LATEST_changed_during_run'
 save(OUT/'PACKAGE_MANIFEST.json',{'schema':'research_evidence_package_v1','date_HKT':'2026-10-06','files':files,'collection_release':False,'training_release':False})
 latest=read(BASE/'LATEST.json');latest['joint_housing_service_worlds_v10']={**current,'report':str((OUT/'METHODS_AND_RESULTS.md').relative_to(BASE)),
  'current':str((OUT/'CURRENT.json').relative_to(BASE)),'review':str((OUT/'SCIENTIFIC_REVIEW.json').relative_to(BASE)),
  'manifest_sha256':sha(OUT/'PACKAGE_MANIFEST.json'),'package_files':len(files)}
 save(BASE/'LATEST.json',latest);assert read(BASE/'LATEST.json')['active_stage']==before['active_stage']
 print({'package_files':len(files),'actual_inputs_checked':len(inputs),'old_sealed_files_unchanged':11175,'manifest_sha256':sha(OUT/'PACKAGE_MANIFEST.json'),'activeV5_preserved':True})
if __name__=='__main__':main()
