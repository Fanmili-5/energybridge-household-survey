"""Interpret coarse dwelling inputs using an explicit shared reference policy.

Unknown survey floors/areas/materials stay unknown. A selected policy defines
experimental context,not factual imputation or stock matching. This adapter
does not generate or adopt household profiles and does not grant admission.
"""
import argparse
import copy
from pathlib import Path

from .common import ROOT,read,require,save,digest
from .condition_housing import plan,CATALOG
from .reference_workflow import ref
from .source_adapter import source_file


def resolve(value,policy_ref,*,consent=False,reference_kind=None,reference_site=None,root=ROOT):
    policy=read(source_file(policy_ref,root))
    require(policy['schema']=='national_idf.shared_reference_context_policy.v1','CONTEXT_POLICY_SCHEMA')
    for evidence in policy['sources'].values():source_file(evidence,root)
    country=value.get('country');dwelling=copy.deepcopy(value.get('dwelling') or {})
    result={'schema':'national_idf.shared_reference_context_resolution.v1','country':country,
        'source_dwelling':dwelling,'source_dwelling_sha256':digest(dwelling),'policy':policy_ref,
        'survey_facts_modified':False,'new_household_or_AB_generated':False,
        'physical_or_reference_admission_granted':False,'gaps':[]}
    known={'type','reference_area_m2','area_is_reference_input','source_size_measure'}
    extra=sorted(k for k in set(dwelling)-known if dwelling[k] is not None)
    if extra:result['gaps'].append({'code':'SURVEY_FIELDS_REQUIRE_SEMANTIC_MAPPING','fields':extra})
    candidates=policy['source_type_to_reference_kinds'].get(dwelling.get('type'),[])
    result['reference_kind_candidates']=candidates
    if reference_kind:
        require(reference_kind in candidates,'CONTEXT_KIND_CONFLICTS_WITH_SOURCE_TYPE')
        candidates=[reference_kind]
    if len(candidates)!=1:result['gaps'].append({'code':'REFERENCE_HOUSING_CLASS_AMBIGUOUS_OR_UNKNOWN'})
    if dwelling.get('area_is_reference_input') is not True or dwelling.get('reference_area_m2') is None:
        result['gaps'].append({'code':'REFERENCE_AREA_NOT_DECLARED'})
    if not consent:result['gaps'].append({'code':'EXPLICIT_REFERENCE_POLICY_SELECTION_REQUIRED'})
    sites=[s for s in read(root/CATALOG)['sites'] if s['country']==country]
    site_id=reference_site or policy['reference_weather_exemplars'].get(country)
    chosen=[s for s in sites if s['id']==site_id]
    if len(chosen)!=1:result['gaps'].append({'code':'REFERENCE_SITE_NOT_AVAILABLE_OR_CONFLICTING'})
    if result['gaps']:
        result['status']='candidate_or_missing_conditions';return result
    kind=candidates[0]
    context={**policy['reference_contexts'][kind],
             **policy.get('source_type_reference_contexts',{}).get(dwelling.get('type'),{})}
    request={'schema':'national_idf.housing_condition_request.v1','country':country,'site_id':site_id,
        'survey_housing':dwelling,'reference_housing':{**context,'kind':kind,
            'conditioned_area_m2':dwelling['reference_area_m2'],
            'area_basis':'declared_reference_conditioned_floor_area',
            'acknowledge_reference_not_survey_home':True}}
    planned=plan(request,root=root)
    require(planned['status']=='constructible_reference','CONTEXT_POLICY_NOT_CONSTRUCTIBLE')
    result.update(status='reference_conditions_expressible_not_physics_admitted',housing_request=request,
        reference_site=chosen[0],actual_household_location_inferred=False,
        unobserved_survey_conditions_remain_unknown=['conditioned-area measurement','floor/stories','shared facades','construction','precise location'],
        reference_parameter_provenance={
            'area':'Upstream explicit reference area is adopted as this experiment conditioned-area design input;source measurement label preserved,not a measured-area conversion',
            'stories_adjacency_and_vertical_context':policy['context_provenance'][kind],
            'source_type_context':policy.get('source_type_context_provenance',{}).get(dwelling.get('type')),
            'site':'Explicit policy-selected reference station;not inferred household address or national weather representation'},
        new_geometry_site_and_service_still_need_validation=True)
    return result


def screen(projection_ref,policy_ref,out,*,root=ROOT):
    from collections import Counter
    data=read(source_file(projection_ref,root));counts=Counter();gaps=Counter();rows=[]
    for item in data['households']:
        result=resolve({'country':item['country'],'dwelling':item['dwelling']},policy_ref,consent=True,root=root)
        counts[result['status']]+=1
        for gap in result['gaps']:gaps[gap['code']]+=1
        rows.append({'country':item['country'],'source_type':item['dwelling']['type'],'status':result['status'],'gaps':result['gaps']})
    report={'schema':'national_idf.reference_context_input_screen.v1','source_projection':projection_ref,
        'policy':policy_ref,'status_counts':dict(counts),'gap_counts':dict(gaps),'rows':rows,
        'context_policy_explicitly_selected_for_interface_test_only':True,
        'count_is_not_successfully_constructed_or_admitted_households':True,
        'household_or_global_physical_coverage_rate':None,'production_bindings':0,
        'households_generated_or_modified':False,'original_AB_changed':False}
    save(out,report);return report


def prepare(value,policy_ref,out,cache,*,consent=False,reference_kind=None,reference_site=None):
    """Resolve and prepare one explicit reference request through the same cache."""
    from .housing_pipeline import prepare as prepare_housing
    out=Path(out).resolve()
    require(out.is_relative_to(ROOT) and not out.exists(),'CONTEXT_PREPARATION_OUTPUT_EXISTS')
    result=resolve(value,policy_ref,consent=consent,reference_kind=reference_kind,reference_site=reference_site)
    out.mkdir(parents=True);save(out/'RESOLUTION.json',result)
    if result['gaps']:return result
    save(out/'HOUSING_REQUEST.json',result['housing_request'])
    preparation=prepare_housing(result['housing_request'],cache)
    save(out/'PREPARATION.json',preparation)
    return preparation


if __name__=='__main__':
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='action',required=True)
    q=sub.add_parser('resolve');q.add_argument('--input',type=Path,required=True);q.add_argument('--policy',type=Path,required=True);q.add_argument('--select-reference-policy',action='store_true');q.add_argument('--reference-kind');q.add_argument('--reference-site');q.add_argument('--out',type=Path,required=True)
    q=sub.add_parser('prepare');q.add_argument('--input',type=Path,required=True);q.add_argument('--policy',type=Path,required=True);q.add_argument('--select-reference-policy',action='store_true');q.add_argument('--reference-kind');q.add_argument('--reference-site');q.add_argument('--out',type=Path,required=True);q.add_argument('--cache',type=Path,required=True)
    q=sub.add_parser('screen');q.add_argument('--projection',type=Path,required=True);q.add_argument('--policy',type=Path,required=True);q.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    if a.action=='resolve':save(a.out,resolve(read(a.input),ref(a.policy),consent=a.select_reference_policy,reference_kind=a.reference_kind,reference_site=a.reference_site))
    elif a.action=='prepare':prepare(read(a.input),ref(a.policy),a.out,a.cache,consent=a.select_reference_policy,reference_kind=a.reference_kind,reference_site=a.reference_site)
    else:screen(ref(a.projection),ref(a.policy),a.out)
