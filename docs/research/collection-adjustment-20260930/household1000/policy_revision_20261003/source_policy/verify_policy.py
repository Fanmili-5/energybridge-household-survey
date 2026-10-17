"""Directed policy examples and counterexamples, independent of physics code."""
from pathlib import Path
from copy import deepcopy
import hashlib
import json
from policy_checks import digest, singleton_eligibility, resolve_fact, validate_experiment

HERE=Path(__file__).resolve().parent
S=lambda s:hashlib.sha256(s.encode()).hexdigest()
checks=[]
def check(name,ok,details=None):checks.append({'name':name,'passed':bool(ok),'details':details})

for n,interval,expected in [
 (1,[19,19],'excluded_under20_singleton'),(1,[20,20],'eligible'),
 (1,[19,20],'unknown_age_boundary'),(1,None,'unknown_singleton_age'),
 (2,None,'eligible_age_boundary_not_applicable'),(1,[18,19],'excluded_under20_singleton'),
 (1,[21,22],'eligible'),(True,[20,20],'unknown_invalid_resident_count')]:
 check('singleton_boundary_'+str(n)+'_'+str(interval),singleton_eligibility(n,interval)==expected)

base_e={'source_id':'CHFS2021-public','source_sha256':S('source metadata'),
 'field':'c2012a_2','question_or_document_locator':'2021PDF69/78',
 'reference_time':'2021','dwelling_binding_id':'current-owned-index2',
 'verification_id':'documented-binding','scope':'current_dwelling',
 'tenure':1,'current_owned_dwelling_index':2,'current_owned_marker_count':1}
c={'value':2010,'evidence':base_e}
check('same_current_j_year_allowed',resolve_fact('building_construction_year',c)['value']==2010)
for name,key,value in [('wrong_dwelling','current_owned_dwelling_index',1),('multiple_current_markers','current_owned_marker_count',2),('nonowned_cannot_borrow_asset','tenure',2),('disposed_property','disposed',True),('acquisition_not_construction','field','c2012_2'),('catalog_label_not_observation','scope','source_catalog_label')]:
 x=deepcopy(c);x['evidence'][key]=value
 check(name,resolve_fact('building_construction_year',x)['status']=='unknown')
for field in ['dwelling_form','household_internal_storeys']:
 for source in ['CHFS2021-public','census2020-H8']:
  x=deepcopy(c);x.update(value='apartment' if field=='dwelling_form' else 1);x['evidence']['source_id']=source
  check('no_shape_inference_'+field+'_'+source,resolve_fact(field,x)['status']=='unknown')
check('unknown_shape_retained',resolve_fact('dwelling_form')['value'] is None)
x=deepcopy(c);x.update(value=2);x['evidence'].update(source_id='external_floorplan',kind='verified_current_dwelling',independent_verified=True)
check('verified_external_internal_levels_allowed',resolve_fact('household_internal_storeys',x)['value']==2)
x['evidence']['independent_verified']=False
check('unverified_external_levels_refused',resolve_fact('household_internal_storeys',x)['status']=='unknown')

target={'geometry_family':'single_storey_apartment','city':'成都','province':'四川','construction_year':None,'building_form':None}
exposure={'north_axis_deg':0,'infiltration_ach':.5,'gross_to_zone_floor_ratio':1/1.33,
 'floor_position':'top','geometry_family':'single_storey_apartment','ground_temperature_c':18}
r={'claim_track':'conditional_engineering','population_frequency_claim':False,'empirical_transport_verified':False,
 'family_slot_id':'designed-policy-example','profile_file_sha256':S('profiles'),
 'housing_before_sha256':S('housing null shape'),'housing_after_sha256':S('housing null shape'),
 'family_before_sha256':S('family'),'family_after_sha256':S('family'),
 'prototype_group_id':'prototype_example','source_idf_sha256':S('source'),'parent_idf_sha256':S('parent'),'weather_sha256':S('epw'),
 'prototype_target':target,'exposure':exposure,'unknown_population_fields':['dwelling_type','household_storeys','actual_city'],
 'actual_mismatch_axes':['city'], 'first_run_at':'2026-10-03T13:01:00+08:00'}
r['conditional_evidence']={'kind':'predeclared_conditional_design','evidence_id':'example-plan-only',
 'rationale':'synthetic policy test;not an actual household or executed simulation',
 'source_group_id':r['prototype_group_id'],'target_sha256':digest(target),'exposure_sha256':digest(exposure),
 'accepted_unknown_population_fields':r['unknown_population_fields'][:],
 'approved_mismatch_axes':r['actual_mismatch_axes'][:],'population_type_identified':False}
pair={'source_group_id':r['prototype_group_id'],'prototype_target_sha256':digest(target),'weather_sha256':r['weather_sha256'],
      'source_idf_sha256':r['source_idf_sha256'],'parent_idf_sha256':r['parent_idf_sha256']}
lock={'frozen_before_first_run':True,'locked_at':'2026-10-03T13:00:00+08:00','profile_file_sha256':r['profile_file_sha256'],
 'source_registry_sha256':S('registry'),'weather_registry_sha256':S('weather registry'),'code_sha256':{'executor':S('code')},
 'admitted_transport_pairs':[pair],'sensitivity_grids':{'north_axis_deg':[0,90,180,270],'infiltration_ach':[.3,.5,.8],
 'gross_to_zone_floor_ratio':[.65,1/1.33,.85],'floor_position':['top'],'geometry_family':['single_storey_apartment'],'ground_temperature_c':[10,18,25]},
 'main_conditions':deepcopy(exposure),'pairing_unit':'family_slot_id','variant_is_new_population_sample':False,
 'family_slots':['designed-policy-example'],'keep_refusals_in_denominator':True,'select_by_output':False}
r['experiment_lock_sha256']=digest(lock)
check('separate_unknown_fact_conditional_design_allowed',validate_experiment(r,lock)['passed'])
mutations=[
 ('shape_promoted','conditional_evidence.population_type_identified',True),
 ('housing_changed','housing_after_sha256',S('changed housing')),
 ('wrong_profile_bytes','profile_file_sha256',S('other profiles')),
 ('wrong_source_group','conditional_evidence.source_group_id','other'),
 ('wrong_parent_bytes','parent_idf_sha256',S('other parent')),
 ('wrong_target_city','prototype_target.city','上海'),
 ('wrong_exposure','exposure.infiltration_ach',.8),
 ('unknown_omitted','conditional_evidence.accepted_unknown_population_fields',['dwelling_type']),
 ('transport_axis_omitted','conditional_evidence.approved_mismatch_axes',[]),
 ('population_frequency_claim','population_frequency_claim',True),
 ('empirical_transfer_claim','empirical_transport_verified',True),
 ('late_lock','first_run_at','2026-10-03T12:59:00+08:00'),
 ('unregistered_slot','family_slot_id','other'),
 ('nonfinite','exposure.infiltration_ach',float('inf'))]
for name,path,value in mutations:
 x=deepcopy(r);keys=path.split('.');d=x
 for k in keys[:-1]:d=d[k]
 d[keys[-1]]=value
 result=validate_experiment(x,lock)
 check('negative_'+name,not result['passed'],result['errors'])
for name,path,value in [('sourcepair_unregistered','admitted_transport_pairs',[]),('sensitivity_posthoc','frozen_before_first_run',False),('refusals_dropped','keep_refusals_in_denominator',False),('outcome_cherry_pick','select_by_output',True),('paired_variants_newN','variant_is_new_population_sample',True)]:
 l=deepcopy(lock);l[path]=value;x=deepcopy(r);x['experiment_lock_sha256']=digest(l)
 result=validate_experiment(x,l);check('negative_'+name,not result['passed'],result['errors'])
for field,value in [('north_axis_deg',90),('infiltration_ach',.3),('gross_to_zone_floor_ratio',.65),('ground_temperature_c',10)]:
 x=deepcopy(r);x['exposure'][field]=value;x['conditional_evidence']['exposure_sha256']=digest(x['exposure'])
 check('prelocked_one_factor_'+field,validate_experiment(x,lock)['passed'])
report={'schema':'eb.source_policy.verification.v1','checks':len(checks),'passed':sum(x['passed'] for x in checks),
 'failures':sum(not x['passed'] for x in checks),'results':checks,
 'code_sha256':{name:hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in ['policy_checks.py','verify_policy.py','build_policy_review.py']},
 'scope':'directed policy counterexamples only;not empirical validation,geometry check or CHFS microdata QC',
 'examples':'fully synthetic designed_policy_examples;no1000 household mapping or physical run asserted'}
(HERE/'POLICY_VERIFICATION.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
(HERE/'CONDITIONAL_POLICY_EXAMPLE.json').write_text(json.dumps({'example_status':'designed_schema_test_only;not an executed simulation','record':r,'lock':lock},ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:report[k] for k in ['checks','passed','failures']}))
raise SystemExit(bool(report['failures']))
