#!/usr/bin/env python3
"""Bind revised facts to separate, predeclared engineering conditions.

No dwelling form or city residence is filled into the household profile.
Assembly selection never reads geometry acceptance or annual outputs.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
H1000=HERE.parent
V2=H1000/'household_to_idf_v2_20261003'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def save(path,value):Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def request_for(key,target,case_id,registry,module):
    result=module.describe_target_conditions(key,target,registry=registry)
    common={'source_group_id':result['source_group_id'],'target_signature':result['target_signature'],
            'use_scope':'assemblies_and_height_only','evidence_id':case_id,
            'rationale':'predeclared conditional construction/height exposure; local housing applicability not observed'}
    return {'prototype_key':key,'target':target,'policy':{
        'mode':'transport','use_scope':'assemblies_and_height_only',
        'design_evidence':dict(common,kind='conditional_template_design',accepted_unknown_features=result['unknown_features']),
        'transport_evidence':dict(common,kind='engineering_transport_design',allowed_mismatches=result['mismatch_axes'])}}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--profiles',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    if args.output.exists():raise ValueError('new immutable input-plan directory required')
    source=args.profiles.resolve();source_sha=sha(source);dataset=json.loads(source.read_text());profiles=dataset['profiles']
    if len(profiles)!=1000 or len({p['slot_id'] for p in profiles})!=1000:raise ValueError('complete1000 required')
    spec=importlib.util.spec_from_file_location('prototype_policy_v2_reference',V2/'prototype_rules.py')
    prototype_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(prototype_module)
    registry=json.loads((V2/'PROTOTYPE_REGISTRY.json').read_text())
    groups=[g for g in registry['groups'].values() if g['source_branch']=='verified_DeST_90zone_apartment']
    byprovince={w['province']:w for w in json.loads((V2/'WEATHER_SUPPLEMENT_CATALOG.json').read_text())['weather'] if w['period']=='2011-2025'}
    if len(byprovince)!=31:raise ValueError('fixed31 climate contexts missing')
    cases,choices=[],[]
    for p in profiles:
        slot=p['slot_id'];case_id='revised_context_'+slot
        family,housing=copy.deepcopy(p['family']),copy.deepcopy(p['housing'])
        year=housing.get('building_year_design');total=housing.get('building_total_storeys_design')
        climate=byprovince[p['province']]
        def score(g):
            meta=g['source_metadata'];v=meta.get('catalog_vintage_year')
            return (meta.get('province_label')!=p['province'],abs(v-year) if v is not None and year is not None else 10**6,g['source_group_id'])
        ranked=sorted(groups,key=score);group=ranked[0];key=min(v['role_key'] for v in group['variants'])
        site={k:climate[k] for k in ['province','city','latitude','longitude','altitude_m','timezone']}
        site.update(weather_resource_id=climate['id'],coordinate_evidence={
            'status':'declared_city_climate_context_equal_provider_station_coordinates',
            'context_id':climate['id'],'source_epw_sha256':climate['epw_sha256'],
            'population_household_city_assigned':False,
            'reason':'separate engineering exposure; no household urban geocoding or population city allocation'})
        target={'geometry_family':'single_storey_apartment','building_form':None,
                'construction_year':year,'city':site['city'],'province':site['province'],
                'feature_evidence':{}}
        for field in ['city','province']:
            target['feature_evidence'][field]={'kind':'declared_station_coincident_design','evidence_id':case_id}
        if year is not None:
            target['feature_evidence']['construction_year']={'kind':'declared_synthetic_housing_condition','evidence_id':slot}
        # Every row is a conditional single-level thermal-shell experiment.
        # This does not assert a population fraction of single-level dwellings.
        geometry={'kind':'conditional_engineering_design','dwelling_type':'apartment',
                  'household_storeys':1,'does_not_identify_population_type':True,
                  'evidence_id':case_id,
                  'rationale':'one declared single-level thermal partition of generated H6/H7; actual household dwelling form/storeys remain unknown'}
        policy={'gross_to_zone_floor_ratio':1/1.33,'net_ratio_evidence':'declared_geometry_bridge',
                'floor_position':'ground' if total==1 else 'top' if total==2 else 'middle',
                'floor_number_design':1 if total==1 else 2 if total is not None else None,
                'floor_position_evidence':'separate conditional engineering exposure, not observed household position',
                'wall_boundaries':{'west':'Adiabatic','east':'Adiabatic','south':'Outdoors','north':'Outdoors'},
                'north_axis_deg':0,'air_exchange_ach':0.5,'prototype_key':key}
        if total==1:
            policy.update(ground_temperature_method='explicit_research_boundary',
                          ground_monthly_temperatures_C=[18.0]*12,
                          ground_temperature_evidence='declared18C constant research boundary; not measured ground temperature')
        item={'case_id':case_id,'population_slot_id':slot,
              'purpose':'revised household facts under explicit single-level thermal-shell conditions; no dwelling-type population inference',
              'family':family,'housing':housing,'site':site,'upstream_residence_site':copy.deepcopy(p['site']),
              'geometry_condition':geometry,'model_policy':policy,
              'prototype_request':request_for(key,target,case_id,registry,prototype_module),
              'generation_binding':{'profile_file_path':str(source),'profile_file_sha256':source_sha,
                  'slot_id':slot,'family_semantic_sha256':digest(family),'housing_semantic_sha256':digest(housing)},
              'operation_mode':'building_shell_validation','expected_result':None,
              'source_provenance':{'status':'modeled_family_housing_with_separate_engineering_context',
                  'raw_survey_household_copied':False,'population_city_distribution_identified':False,
                  'context_is_not_household_residence':True,'geometry_condition_is_not_population_form_assignment':True},
              'collection_release':False,'training_release':False}
        cases.append(item)
        choices.append({'slot_id':slot,'case_id':case_id,'source_group_id':group['source_group_id'],
                        'prototype_key':key,'chosen_score':list(score(group)),
                        'climate_context_id':climate['id'],'weather_epw_sha256':climate['epw_sha256'],
                        'prespecified_alternative_source_groups':[g['source_group_id'] for g in ranked[1:3]],
                        'family_sha256':digest(family),'housing_sha256':digest(housing),
                        'actual_household_shape_or_city_identified':False})
    if sha(source)!=source_sha:raise ValueError('profile changed while planning contexts')
    args.output.mkdir(parents=True)
    save(args.output/'EXPERIMENT_INPUTS.json',cases)
    save(args.output/'CONTEXT_PLAN.json',{'schema':'eb.revised_conditional_context_plan.v1','slots_retained':1000,
        'profile_file_path':str(source),'profile_file_sha256':source_sha,
        'prototype_registry_sha256':sha(V2/'PROTOTYPE_REGISTRY.json'),
        'prototype_rules_reference_sha256':sha(V2/'prototype_rules.py'),
        'weather_catalog_sha256':sha(V2/'WEATHER_CATALOG.json'),'builder_sha256':sha(__file__),
        'source_ranking_rule':'catalog province-label, vintage-label distance, lexical content-source-group; no inferred low/high form threshold',
        'source_ranking_is':'engineering selection only; not empirical local stock matching',
        'geometry_rule':'explicit single-level thermal condition for each retained slot; no population shape frequency assigned',
        'factual_unknowns_preserved':True,'outcomes_or_capacity_used_for_assignment':False,
        'population_city_or_shape_assignments':0,'choices':choices,'collection_release':False,'training_release':False})
    save(args.output/'ENGINEERING_SENSITIVITY_PLAN.json',{'schema':'eb.prespecified_engineering_sensitivity.v1',
        'status':'design locked before revised cohort annual outcomes; full ensemble not yet executed',
        'base':{'north_axis_deg':0,'air_exchange_ach':0.5,'gross_to_zone_floor_ratio':1/1.33,'ground_temperature_C':18},
        'one_factor_conditions':{'north_axis_deg':[90,180,270],'air_exchange_ach':[0.3,0.8],
            'gross_to_zone_floor_ratio':[0.65,0.85],'ground_temperature_C':[10,25],
            'assembly_source':'two prespecified alternative source groups per input choice'},
        'distributions_or_probabilities_identified':False,
        'selection_policy':'smallest eligible slot for each ground/non-ground branch, then input area/room/person extrema; retain failures',
        'full_population_energy_calibration_claim_allowed':False})
    print(json.dumps({'cases':len(cases),'source_groups':len({x['source_group_id'] for x in choices}),
                      'actual_residence_or_shape_assignments':0,'profile_sha256':source_sha}))


if __name__=='__main__':main()
