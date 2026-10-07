#!/usr/bin/env python3
"""Read back all population-context bindings, including refused cases.

This checks identity, byte/semantic provenance and support accounting. It does
not test synthetic-population validity, local calibration or human responses.
"""
import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path): return json.loads(Path(path).read_text())
def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def save(path,obj): Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run-dir',required=True,type=Path)
    ap.add_argument('--plan',required=True,type=Path)
    ap.add_argument('--output',required=True,type=Path)
    args=ap.parse_args();run=args.run_dir.resolve();plan=read(args.plan/'CONTEXT_PLAN.json')
    summary=read(run/'SUMMARY.json');lock=read(run/'INPUT_LOCK.json')
    profile_path=Path(plan['profile_file_path']);profile_sha=sha(profile_path)
    profiles={p['slot_id']:p for p in read(profile_path)['profiles']}
    inputs={x['case_id']:x for x in read(args.plan/'EXPERIMENT_INPUTS.json')}
    batch_inputs={x['case_id']:x for x in read(run/'EXPERIMENT_INPUTS.json')}
    choices={x['case_id']:x for x in plan['choices']}
    checks=[]
    def check(name,passed,detail=None): checks.append({'check':name,'pass':bool(passed),'detail':detail})
    check('profile_actual_bytes_match_plan',profile_sha==plan['profile_file_sha256'])
    check('1000_unique_cases_and_slots',len(inputs)==len(batch_inputs)==len(profiles)==len(summary['records'])==1000)
    check('exact_input_plan_preserved',digest(inputs)==digest(batch_inputs))
    check('registries_actual_bytes_match_lock',all(sha(lock[k+'_path'])==lock[k+'_sha256'] for k in ['prototype_registry','weather_registry']))
    check('context_plan_registry_versions_match_lock',plan['prototype_registry_sha256']==lock['prototype_registry_sha256'] and plan['weather_catalog_sha256']==lock['weather_registry_sha256'])
    check('copied_code_bytes_match_lock',all(sha(run/'code'/name)==value for name,value in lock['code'].items()))
    check('population_city_assignment_not_performed',plan['new_population_city_assignments']==0 and all(p['site']['city'] is None for p in profiles.values()))
    manifest=read(run/'MANIFEST.json')
    check('parent_manifest_all_original_files_match',all(sha(run/name)==value for name,value in manifest['files'].items()))
    readiness=[];failures=[];errors=Counter();stages=Counter();dwelling=defaultdict(Counter);province=defaultdict(Counter)
    source_groups=set();weather_files=set();epw_cache={}
    required=['INPUT.json','STATUS.json','LAYOUT.json','ASSEMBLY_BINDING.json','WEATHER_MATCH.json',
              'PROTOTYPE_REQUEST.json','PROTOTYPE_MATCH.json','INDEPENDENT_GEOMETRY_CHECK.json',
              'IDF_OBJECT_LINEAGE.json','building.idf','OPERATIONAL_BINDING_INTERFACE.json']
    for record in summary['records']:
        case_id=record['case_id'];item=inputs[case_id];p=profiles[item['population_slot_id']];folder=run/'cases'/record['case_folder']
        actual=read(folder/'INPUT.json');binding=item['generation_binding'];choice=choices[case_id]
        local=[]
        def demand(condition,label):
            if not condition: local.append(label)
        demand(digest(actual)==digest(item)==record['input_semantic_sha256'],'frozen_compile_input')
        demand(sha(folder/'INPUT.json')==record['input_sha256'],'input_file_hash')
        demand(read(folder/'STATUS.json')==record,'status_readback')
        demand(digest(item['family'])==digest(p['family'])==binding['family_semantic_sha256']==choice['original_family_sha256'],'family_identity')
        demand(digest(item['housing'])==digest(p['housing'])==binding['housing_semantic_sha256']==choice['original_housing_sha256'],'housing_identity')
        demand(binding['profile_file_sha256']==profile_sha and binding['slot_id']==p['slot_id'],'generation_source_identity')
        demand(item['upstream_residence_site']==p['site'],'unknown_residence_site_preserved')
        demand(item['site']['province']==p['province'] and item['site']['coordinate_evidence']['population_household_city_assigned'] is False,'context_separate_same_province')
        demand(item['site']['weather_resource_id']==choice['climate_context_id'],'predeclared_climate_resource')
        demand(item['prototype_request']['target']['construction_year']==p['housing'].get('building_year_design'),'prototype_target_known_or_unknown_design_year')
        demand(item['model_policy']['prototype_key']==choice['prototype_key'],'predeclared_prototype_source')
        demand((folder/'GENERATION_BINDING_CHECK.json').exists(),'generation_check_record_exists')
        if (folder/'GENERATION_BINDING_CHECK.json').exists():
            demand(read(folder/'GENERATION_BINDING_CHECK.json')['status']=='pass','generation_check_pass')
        is_ready=record['status']=='idf_ready'
        if is_ready:
            demand(all((folder/name).is_file() for name in required),'complete_accepted_bundle')
            demand(sha(folder/'building.idf')==record['idf_sha256'],'accepted_idf_bytes')
            demand(read(folder/'INDEPENDENT_GEOMETRY_CHECK.json')['status']=='pass','mandatory_independent_geometry_pass')
            match=read(folder/'PROTOTYPE_MATCH.json');weather=read(folder/'WEATHER_MATCH.json')['selected']
            demand(match['eligible'] and match['selected_group_id']==record['prototype_source_group_id']==choice['source_group_id'],'prototype_admission_bound')
            demand(weather['id']==item['site']['weather_resource_id'] and weather['province']==p['province'],'weather_identity')
            path=record['weather_epw_path']
            if path not in epw_cache: epw_cache[path]=sha(path)
            demand(epw_cache[path]==record['weather_epw_sha256'],'weather_actual_bytes')
            demand(record['natural_room_count']==p['housing']['H7_natural_rooms_exact'],'H7_semantics_preserved')
            demand(record['H6_building_area_m2']==p['housing']['H6_building_area_m2'],'H6_value_preserved')
            total=p['housing'].get('building_total_storeys_design');floor=item['model_policy']['floor_number_design']
            demand(total is not None and 2<=floor<=total and
                   (item['model_policy']['floor_position']=='top' and floor==total or
                    item['model_policy']['floor_position']=='middle' and floor<total),'floor_position_consistent_with_building_storeys')
            operation=read(folder/'OPERATIONAL_BINDING_INTERFACE.json')
            demand(all(operation[k] is None for k in ['people_gains','appliance_inventory_and_power','device_access_control','occupancy_schedules','HVAC_and_controls']),'unknown_operations_not_invented')
            source_groups.add(record['prototype_source_group_id']);weather_files.add(record['weather_epw_sha256'])
        else:
            demand(record['status']=='blocked' and len(record['errors'])>0,'explicit_refusal_reason')
            demand(not(folder/'building.idf').exists(),'no_admitted_idf_for_refused_case')
            errors.update(record['errors']);stages.update([record['stage_reached']])
        if local: failures.append({'case_id':case_id,'errors':local})
        dwelling[p['housing']['dwelling_type']].update(['total','accepted' if is_ready else 'refused'])
        province[p['province']].update(['total','accepted' if is_ready else 'refused'])
        readiness.append({'slot_id':p['slot_id'],'case_id':case_id,'generated_family_housing_ready':True,
                          'conditional_shell_status':record['status'],'conditional_shell_errors':record['errors'],
                          'family_semantic_sha256':binding['family_semantic_sha256'],'housing_semantic_sha256':binding['housing_semantic_sha256'],
                          'actual_household_city_assignment':'pending','occupancy_devices_HVAC_and_metering':'pending',
                          'actor_card_and_scenario_display_validation':'pending','actor_answers':None,
                          'questionnaire_collectable':False,'collection_release':False,'training_release':False})
    check('all1000_identity_and_support_checks',not failures,failures)
    check('no_slots_lost',len(readiness)==1000 and {x['slot_id'] for x in readiness}==set(profiles))
    check('ready_refused_counts_match_summary',sum(x['conditional_shell_status']=='idf_ready' for x in readiness)==summary['IDF_ready'] and sum(x['conditional_shell_status']=='blocked' for x in readiness)==summary['blocked'])
    check('candidate_results_not_misrepresented_as_expected_controls',summary['expected_controls_count']==0 and summary['unprespecified_candidate_count']==1000)
    args.output.mkdir(parents=True,exist_ok=False)
    save(args.output/'BINDING_READINESS.json',{'schema':'eb.binding_readiness.v2','profiles':readiness,
        'complete_family_housing_candidates':1000,'actual_household_city_assignments':0,'complete_operational_roles':0,
        'collectable_questionnaires':0,'collection_release':False,'training_release':False})
    report={'schema':'eb.context_binding_verification.v2','experiment_id':summary['experiment_id'],
            'checks':checks,'pass':all(x['pass'] for x in checks),'check_groups':len(checks),'cases_read_back':1000,
            'profile_sha256':profile_sha,'input_plan_sha256':sha(args.plan/'EXPERIMENT_INPUTS.json'),
            'static_summary_sha256':sha(run/'SUMMARY.json'),'ready':summary['IDF_ready'],'refused':summary['blocked'],
            'unique_admitted_source_groups':len(source_groups),'unique_admitted_weather_files':len(weather_files),
            'refusal_error_counts':dict(errors),'refusal_stage_counts':dict(stages),
            'support_by_dwelling_type':{k:dict(v) for k,v in sorted(dwelling.items())},
            'support_by_province':{k:dict(v) for k,v in sorted(province.items())},
            'counts_are_support_of_fixed_generated_cohort_not_population_weights':True,
            'semantic_and_byte_verification_is_not_empirical_validation':True,'failures':failures}
    save(args.output/'CONTEXT_BINDING_VERIFICATION.json',report)
    print(json.dumps({k:v for k,v in report.items() if k not in ['checks','failures','support_by_province']},ensure_ascii=False))
    if not report['pass']: raise SystemExit(1)


if __name__=='__main__': main()
