#!/usr/bin/env python3
"""Bind immutable generated facts to explicit engineering climate contexts.

No population city allocation is performed. Profiles retain their unknown
city; the compile-site is a separate designed exposure, never a residence.
No family/housing resampling based on template or weather success.
"""
import argparse
import copy
import json
from pathlib import Path
from household_model import digest, save, sha
from prototype_rules import describe_target_conditions

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]


def requested_prototype(key, target, case_id, registry=None):
    conditions = describe_target_conditions(key, target, registry=registry)
    design = {
        'kind':'conditional_template_design', 'source_group_id':conditions['source_group_id'],
        'target_signature':conditions['target_signature'], 'use_scope':'assemblies_and_height_only',
        'accepted_unknown_features':conditions['unknown_features'], 'evidence_id':case_id,
        'rationale':'predeclared conditional assembly/height experiment; not a measured local stock match'
    }
    transport = {
        'kind':'engineering_transport_design', 'source_group_id':conditions['source_group_id'],
        'target_signature':conditions['target_signature'], 'use_scope':'assemblies_and_height_only',
        'allowed_mismatches':conditions['mismatch_axes'], 'evidence_id':case_id,
        'rationale':'explicit construction and height transport into a designed city climate context; no empirical transfer accuracy claim'
    }
    return {'prototype_key':key, 'target':target, 'policy':{
        'mode':'transport','use_scope':'assemblies_and_height_only',
        'design_evidence':design,'transport_evidence':transport}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profiles', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('new immutable input-plan directory required')
    args.output.mkdir(parents=True)
    profile_path = args.profiles.resolve()
    profile_sha = sha(profile_path)
    dataset = json.loads(profile_path.read_text())
    profiles = dataset['profiles']
    assert len(profiles)==1000 and len({p['slot_id'] for p in profiles})==1000
    registry = json.loads((HERE/'PROTOTYPE_REGISTRY.json').read_text())
    sources = [g for g in registry['groups'].values()
               if g['source_branch']=='verified_DeST_90zone_apartment']
    weather = json.loads((HERE/'WEATHER_SUPPLEMENT_CATALOG.json').read_text())['weather']
    # Both periods were acquired and retained. The new main exposure is fixed
    # before simulations; the earlier period remains a separate sensitivity.
    byprovince = {w['province']:w for w in weather if w['period']=='2011-2025'}
    assert len(byprovince)==31
    cases, choices = [], []
    for profile in profiles:
        slot = profile['slot_id']
        case_id = 'context_'+slot
        family, housing = copy.deepcopy(profile['family']), copy.deepcopy(profile['housing'])
        source_year = housing.get('building_year_design')
        total_storeys = housing.get('building_total_storeys_design')
        form = ('low_rise_apartment' if total_storeys is not None and total_storeys<=6
                else 'high_rise_slab_apartment' if total_storeys is not None else None)
        context = byprovince[profile['province']]
        def score(group):
            metadata = group['source_metadata']
            year = metadata.get('catalog_vintage_year')
            return (metadata.get('province_label') != profile['province'],
                    form is not None and metadata.get('building_form') != form,
                    abs(year-source_year) if year is not None and source_year is not None else 10**6,
                    group['source_group_id'])
        ranked = sorted(sources,key=score)
        group = ranked[0]
        variant = min(group['variants'],key=lambda v:v['role_key'])
        key = variant['role_key']
        site = {k:context[k] for k in ['province','city','latitude','longitude','altitude_m','timezone']}
        site.update(weather_resource_id=context['id'], coordinate_evidence={
            'status':'declared_city_climate_context_equal_provider_station_coordinates',
            'context_id':context['id'], 'source_epw_sha256':context['epw_sha256'],
            'population_household_city_assigned':False,
            'reason':'engineering exposure separate from the profile residence; station coordinates are not an urban home address'})
        target = {'geometry_family':'single_storey_apartment','building_form':form,
                  'construction_year':source_year,'city':site['city'],'province':site['province'],
                  'feature_evidence':{}}
        for field in ['city','province']:
            target['feature_evidence'][field]={'kind':'declared_station_coincident_design','evidence_id':case_id}
        for field in ['building_form','construction_year']:
            target['feature_evidence'][field]={'kind':'declared_synthetic_housing_condition','evidence_id':slot}
        item = {
            'case_id':case_id, 'population_slot_id':slot,
            'purpose':'generated family/housing under a separate predeclared same-province city-reference climate context; no actual residence geocoding',
            'family':family, 'housing':housing, 'site':site,
            'upstream_residence_site':copy.deepcopy(profile['site']),
            'model_policy':{'gross_to_zone_floor_ratio':1/1.33,'net_ratio_evidence':'declared_geometry_bridge',
                            'floor_position':'top' if total_storeys==2 else 'middle',
                            'floor_number_design':2 if total_storeys is not None and total_storeys>=2 else None,
                            'floor_position_evidence':'declared engineering exposure consistent with generated building total storeys; not an observed household floor',
                            'wall_boundaries':{'west':'Adiabatic','east':'Adiabatic','south':'Outdoors','north':'Outdoors'},
                            'north_axis_deg':0,'air_exchange_ach':.5,'prototype_key':key},
            'prototype_request':requested_prototype(key,target,case_id,registry),
            'generation_binding':{'profile_file_path':str(profile_path),'profile_file_sha256':profile_sha,
                                  'slot_id':slot,'family_semantic_sha256':digest(family),'housing_semantic_sha256':digest(housing)},
            'operation_mode':'building_shell_validation', 'expected_result':None,
            'source_provenance':{'status':'modeled_family_housing_with_separate_engineering_context',
                                 'raw_survey_household_copied':False,'population_city_distribution_identified':False,
                                 'context_is_not_household_residence':True},
            'collection_release':False,'training_release':False
        }
        assert digest(item['family'])==digest(profile['family']) and digest(item['housing'])==digest(profile['housing'])
        cases.append(item)
        choices.append({'slot_id':slot,'case_id':case_id,'climate_context_id':context['id'],
                        'source_group_id':group['source_group_id'],'prototype_key':key,
                        'chosen_score':list(score(group)),
                        'same_rank_count':sum(score(g)[:-1]==score(group)[:-1] for g in sources),
                        'original_family_sha256':digest(family),'original_housing_sha256':digest(housing),
                        'residence_city_assigned':False})
    save(args.output/'EXPERIMENT_INPUTS.json',cases)
    save(args.output/'CONTEXT_PLAN.json',{
        'schema':'eb.generated_household.context_plan.v2','slots_retained':len(cases),
        'profile_file_path':str(profile_path),'profile_file_sha256':profile_sha,
        'prototype_registry_sha256':sha(HERE/'PROTOTYPE_REGISTRY.json'),
        'weather_catalog_sha256':sha(HERE/'WEATHER_CATALOG.json'),
        'source_selection_rule':'apartment assembly source: same catalog province-label preferred, then declared low/high form-label, then vintage-label difference, then source_group_id; canonical role-key tie',
        'source_ranking_scope':'label-based engineering assignment; labels are not local stock measurements',
        'source_candidates':len(sources),
        'climate_selection_rule':'prespecified2011-2025 named same-province city-reference resource; this is a separate engineering exposure, not household city allocation',
        'new_population_city_assignments':0,
        'family_housing_semantics_changed':False,'capacity_or_outcome_used_for_generation':False,
        'choices':choices,'collection_release':False,'training_release':False})
    print(json.dumps({'cases':len(cases),'unique_source_groups':len({c['source_group_id'] for c in choices}),
                      'climate_contexts':len({c['climate_context_id'] for c in choices}),
                      'population_city_assignments':0,'input_plan':str(args.output)},ensure_ascii=False))


if __name__=='__main__':
    main()
