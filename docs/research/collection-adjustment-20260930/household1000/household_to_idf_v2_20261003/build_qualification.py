#!/usr/bin/env python3
"""Materialize current1000 support and runtime qualification for consumers.

Each slot is retained. Legacy allocation.status is not a current role status.
Thermal-shell execution is separate from operational or questionnaire release.
"""
import json
from collections import Counter
from pathlib import Path
from household_model import save,sha

HERE=Path(__file__).resolve().parent


def main():
    static=HERE/'population_contexts_v1';annual=HERE/'annual_witnesses_v1'
    inputs={x['case_id']:x for x in json.loads((static/'EXPERIMENT_INPUTS.json').read_text())}
    summary=json.loads((static/'SUMMARY.json').read_text())
    witnesses={x['case_id']:x for x in json.loads((annual/'SUMMARY.json').read_text())['runtime']}
    rows=[];refusal=Counter();stages=Counter();by_NG={};by_scope={}
    for record in summary['records']:
        case_id=record['case_id'];item=inputs[case_id];housing=item['housing'];runtime=witnesses.get(case_id)
        if record['status']=='blocked':
            if housing['H5_status']!='ordinary_declared_or_matched': reason='nonordinary_outside_supported_writer'
            elif housing['occupancy_scope']!='whole_household_private': reason='ordinary_shared_scope_outside_supported_writer'
            elif housing['dwelling_type']=='single_storey_ordinary_house_design': reason='urban_single_storey_house_outside_supported_writer'
            elif housing['household_storeys']!=1: reason='household_multistorey_outside_supported_writer'
            elif 'template_capacity_failure_no_area_or_H7_repair' in record['errors']: reason='declared_rectangular_layout_capacity_failure'
            else: reason='other_explicit_admission_failure'
            refusal.update([reason]);runtime_state='static_refused'
        elif runtime is None: reason=None;runtime_state='annual_not_tested'
        elif runtime['status']!='pass': reason=None;runtime_state='annual_failed'
        elif runtime.get('severity',{}).get('warning',0): reason=None;runtime_state='annual_complete_with_warning_markers'
        else: reason=None;runtime_state='annual_complete_without_warning_markers'
        stages.update([runtime_state])
        ng=str(item['family']['resident_count'])+'persons/'+str(item['family']['generation_count_design'])+'generations'
        by_NG.setdefault(ng,Counter()).update(['total','static_ready' if record['status']=='idf_ready' else 'static_refused'])
        scope=housing['H5_status']+'/'+housing['occupancy_scope']
        by_scope.setdefault(scope,Counter()).update(['total','static_ready' if record['status']=='idf_ready' else 'static_refused'])
        rows.append({'slot_id':item['population_slot_id'],'case_id':case_id,'current_state':runtime_state,
            'generated_fact_version_sha256':item['generation_binding']['profile_file_sha256'],
            'family_semantic_sha256':item['generation_binding']['family_semantic_sha256'],
            'housing_semantic_sha256':item['generation_binding']['housing_semantic_sha256'],
            'static_shell_status':record['status'],'all_refusal_errors':record['errors'],
            'exclusive_refusal_summary_class':reason,'case_path':str(static/'cases'/record['case_folder']),
            'IDF_sha256':record.get('idf_sha256'),'source_group_id':record.get('prototype_source_group_id'),
            'weather_epw_sha256':record.get('weather_epw_sha256'),'annual_engine_status':runtime['status'] if runtime else None,
            'raw_warning_marker_count_includes_recurring_summaries':runtime.get('severity',{}).get('warning',0) if runtime else None,
            'actual_household_city_assigned':False,'operational_people_devices_HVAC_metering_bound':False,
            'actor_card_complete':False,'questionnaire_collectable':False,'training_release':False})
    save(HERE/'DOWNSTREAM_QUALIFICATION.json',{'schema':'eb.current_slot_qualification.v2','slots':rows,
        'denominator':1000,'static_ready':summary['IDF_ready'],'static_refused':summary['blocked'],
        'annual_states':dict(stages),'exclusive_refusal_summary':dict(refusal),
        'support_by_exact_N_G':{k:dict(v) for k,v in sorted(by_NG.items())},
        'support_by_H5_occupancy_scope':{k:dict(v) for k,v in sorted(by_scope.items())},
        'static_summary_sha256':sha(static/'SUMMARY.json'),'annual_summary_sha256':sha(annual/'SUMMARY.json'),
        'source_allocation_status_is_historical':True,'field_current_state_is_authoritative_here':True,
        'engineering_exposure_is_not_residence':True,'all1000_annual_runs_performed':False,
        'collection_release':False,'training_release':False})
    print(json.dumps({'denominator':len(rows),'states':dict(stages),'refusal_summary':dict(refusal)},ensure_ascii=False))


if __name__=='__main__':main()
