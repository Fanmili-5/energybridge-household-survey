#!/usr/bin/env python3
"""One typed join across all1000 candidate facts, contexts and source gaps.

No field is filled from a reference count, successful IDF or old household.
"""
import json
from pathlib import Path
from typed_chain import digest,sha

HERE=Path(__file__).resolve().parent;H1000=HERE.parent
def main():
    source=H1000/'generation_model_v2_20261003/empirical_support_tilt_qc1/FAMILY_HOUSING_CANDIDATES.json'
    context=H1000/'policy_revision_20261003/revised_context_plan_v2/EXPERIMENT_INPUTS.json'
    support_path=HERE/'references_final/SLOT1000_REFERENCE_SUPPORT.json'
    year_path=HERE/'chfs_vintage_v1/CURRENT_DWELLING_YEAR_AREA_SUPPORT.json'
    out=HERE/'CANDIDATE1000_CHAIN_INDEX.json'
    if out.exists():raise ValueError('new_immutable_index_required')
    body=json.loads(source.read_text());lock=json.loads((source.parent/'GENERATOR_LOCK.json').read_text())
    if sha(source)!=lock['output_sha256'] or body['generation_model']!=lock['settings']:
        raise ValueError('profile_model_lock_mismatch')
    byslot={p['slot_id']:p for p in body['profiles']};cases=json.loads(context.read_text())
    supports={p['slot_id']:p for p in json.loads(support_path.read_text())['rows']}
    years={p['slot_id']:p for p in json.loads(year_path.read_text())['slot_support']}
    if len(byslot)!=1000 or set(byslot)!=set(supports) or set(byslot)!=set(years) or len(cases)!=1000:
        raise ValueError('complete1000_denominator_mismatch')
    rows=[];source_sha=sha(source)
    for c in cases:
        slot=c['population_slot_id'];p=byslot[slot];b=c['generation_binding']
        if b['profile_file_sha256']!=source_sha or b['slot_id']!=slot or digest(c['family'])!=digest(p['family']) or digest(c['housing'])!=digest(p['housing']):
            raise ValueError('family_housing_context_mismatch:'+slot)
        if digest(p['family'])!=b['family_semantic_sha256'] or digest(p['housing'])!=b['housing_semantic_sha256']:
            raise ValueError('semantic_binding_mismatch:'+slot)
        rows.append({'slot_id':slot,'profile_version':p['profile_version'],
            'family_semantic_sha256':digest(p['family']),'housing_semantic_sha256':digest(p['housing']),
            'facts_byte_binding_status':'pass_not_population_validity',
            'actual_city':p['site'].get('city'),'actual_dwelling_form':p['housing']['dwelling_type'],
            'actual_household_interior_storeys':p['housing']['household_storeys'],
            'conditional_context_case_id':c['case_id'],'conditional_context_semantic_sha256':digest(c),
            'engineering_condition_separate_from_facts':True,
            'historical_asset_reference_support':supports[slot],
            'current_owned_vintage_area_proxy_support':years[slot],
            'asset_instances':[],'asset_status':'pending_task_relevant_instance_and_model_generation',
            'operations':None,'role_permissions':None,'physical_service_result':None,
            'functional_layout_status':'not_validated','actor_display':None,'observed_answer':None,
            'completion_requires':['task-relevant coherent kinship and member time budgets',
                'functional room/installation design','assets with separate source/design provenance',
                'device model and meter/zone links','operator/access/role-control contract',
                'same-state tasks and service verification','display and comprehension pilot'],
            'candidate_replaced_after_source_or_IDF_failure':False,'collection_release':False,'training_release':False})
    payload={'schema':'eb.candidate_household_context_assets_chain_index.v1',
        'input_sha256':{str(p):sha(p) for p in [source,context,support_path,year_path]},
        'rows':rows,'slots':1000,'complete_actor_roles':0,'missing_asset_instances_means':'pending, never zero ownership',
        'full_population_generation_approved':False,'collection_release':False,'training_release':False}
    out.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'slots':1000,'exact_family_housing_context_bindings':1000,'actor_ready':0,'unknown_city_and_form_preserved':True}))

if __name__=='__main__':main()
