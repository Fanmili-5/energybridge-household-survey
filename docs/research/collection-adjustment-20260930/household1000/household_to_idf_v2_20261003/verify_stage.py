#!/usr/bin/env python3
"""Read back immutable experiment outputs, provenance and annual SQL evidence."""
import argparse
import hashlib
import json
import math
import re
import sqlite3
from pathlib import Path

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def digest(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def load(p):return json.loads(p.read_text())

def main(folder,report):
    checks=[]
    def check(ok,name):checks.append({'check':name,'pass':bool(ok)})
    manifest=load(folder/'MANIFEST.json')
    for path,expected in manifest['files'].items():check((folder/path).exists() and sha(folder/path)==expected,'experiment_hash:'+path)
    summary=load(folder/'SUMMARY.json');inputs=load(folder/'EXPERIMENT_INPUTS.json')
    locked={x['case_id']:x for x in inputs}
    lock=load(folder/'INPUT_LOCK.json')
    for key in ['prototype_catalog','resource_catalog']:check(sha(Path(lock[key+'_path']))==lock[key+'_sha256'],key+'_unchanged')
    for key in ['prototype_registry','weather_registry']:check(sha(Path(lock[key+'_path']))==lock[key+'_sha256'],key+'_unchanged')
    for record in summary['records']:
        key=record['case_id'];case=folder/'cases'/record['case_folder'];item=load(case/'INPUT.json')
        check(digest(item)==digest(locked[key])==record['input_semantic_sha256'],'frozen_input:'+key)
        if record['expected_result'] in ['idf_ready','blocked']:check(record['status']==record['expected_result'],'expected_admission:'+key)
        check(not record['collection_release'] and not record['training_release'] and not record['complete_actor_role'],'scope:'+key)
        if 'generation_binding' in item and isinstance(item.get('family'),dict) and isinstance(item.get('housing'),dict):
            generation=load(case/'GENERATION_BINDING_CHECK.json')
            check(sha(case/'GENERATION_BINDING_CHECK.json')==record['generation_binding_check_sha256'],'generation_report_byte_binding:'+key)
            check(generation['status']==record['generation_binding_status'],'generation_report_status_binding:'+key)
            if generation['status']=='pass':
                check(not generation['errors'],'generation_verified_without_errors:'+key)
                check(sha(Path(generation['profile_file_path']))==generation['profile_file_sha256'],'generation_profile_actual_byte_binding:'+key)
                check(generation['family_semantic_sha256']==digest(item['family']) and generation['housing_semantic_sha256']==digest(item['housing']),'generation_family_housing_semantics:'+key)
        if record['status']!='idf_ready':check(not (case/'building.idf').exists(),'no_IDF_for_refused_input:'+key);continue
        layout=load(case/'LAYOUT.json');binding=load(case/'ASSEMBLY_BINDING.json')
        prototype=load(case/'PROTOTYPE_MATCH.json')
        check(prototype['eligible'] and record['prototype_status']==prototype['status'],'mandatory_prototype_admission:'+key)
        check(sha(case/'PROTOTYPE_MATCH.json')==record['prototype_match_sha256'],'prototype_admission_report_binding:'+key)
        check(prototype['selected_catalog_row']['source_idf_sha256']==binding['source_idf_sha256'] and prototype['selected_catalog_row']['parent_idf_sha256']==binding['parent_idf_sha256'],'prototype_selected_source_binding:'+key)
        if 'generation_binding' in item:
            generation=load(case/'GENERATION_BINDING_CHECK.json')
            check(generation['status']=='pass' and not generation['errors'] and record['generation_binding_status']=='pass','generation_profile_consistency:'+key)
            check(sha(Path(generation['profile_file_path']))==generation['profile_file_sha256'],'generation_profile_actual_byte_binding:'+key)
            check(generation['family_semantic_sha256']==digest(item['family']) and generation['housing_semantic_sha256']==digest(item['housing']),'generation_family_housing_semantics:'+key)
        independent=load(case/'INDEPENDENT_GEOMETRY_CHECK.json')
        check(independent['status']=='pass' and not independent['errors'] and record.get('independent_geometry_status')=='pass','mandatory_independent_geometry:'+key)
        check(independent['idf_sha256']==sha(case/'building.idf'),'independent_geometry_IDF_binding:'+key)
        check(independent['layout_sha256']==sha(case/'LAYOUT.json'),'independent_geometry_layout_binding:'+key)
        check(independent['checker_sha256']==sha(folder/'code/geometry_gate.py')==record['independent_geometry_checker_sha256'],'independent_geometry_checker_binding:'+key)
        check(sha(case/'INDEPENDENT_GEOMETRY_CHECK.json')==record['independent_geometry_check_sha256'],'independent_geometry_report_binding:'+key)
        check(not load(case/'IDF_STATIC_CHECK.json')['errors'] and not load(case/'LAYOUT_CHECK.json')['errors'],'static_geometry:'+key)
        check(sum(s['kind']=='natural_room' for s in layout['spaces'])==item['housing']['H7_natural_rooms_exact'],'exact_H7:'+key)
        check(math.isclose(sum((s['rect_m'][2]-s['rect_m'][0])*(s['rect_m'][3]-s['rect_m'][1]) for s in layout['spaces']),item['housing']['H6_building_area_m2']*item['model_policy']['gross_to_zone_floor_ratio'],abs_tol=1e-6),'H6_ratio_zone_area:'+key)
        check(binding['H6_building_area_m2']==item['housing']['H6_building_area_m2'],'H6_not_repaired:'+key)
        for stem in ['source','parent']:check(sha(Path(binding[stem+'_idf_path']))==binding[stem+'_idf_sha256'],stem+'_prototype_hash:'+key)
        decisions={x['decision_id'] for x in load(case/'DECISION_TRACE.json')['decisions']}
        lineage=load(case/'IDF_OBJECT_LINEAGE.json')
        check(all(set(x['source_decision_ids'])<=decisions and x['source_decision_ids'] for x in lineage),'object_decision_references:'+key)
        operational=load(case/'OPERATIONAL_BINDING_INTERFACE.json')
        check(sorted(operational['member_sleep_zone'])==sorted(item['family']['resident_member_ids']),'member_zone_interface:'+key)
        check(all(operational[k] is None for k in ['people_gains','appliance_inventory_and_power','device_access_control','occupancy_schedules','HVAC_and_controls']),'operational_unknowns_preserved:'+key)
        text=(case/'building.idf').read_text().lower()
        check(not re.search(r'(?m)^\s*(people|lights|electricequipment|zonehvac:idealloadsairsystem|zonegroup)\s*,',text),'no_inherited_occupancy_devices_HVAC_or_multiplier:'+key)
    annual=[]
    for r in summary['runtime']:
        key=r['case_id'];runtime=folder/'runtime'/key;case=folder/'cases'/key
        check(r['status']=='pass' and r['returncode']==0 and not r['errors'],'actual_annual_completion:'+key)
        check(not r['severity'].get('severe',0) and not r['severity'].get('fatal',0),'strict_engine_errors:'+key)
        check(sha(case/'building.idf')==r['input_idf_sha256'],'runtime_IDF_binding:'+key)
        weather=load(case/'WEATHER_MATCH.json')['selected'];check(sha(Path(weather['epw_absolute_path']))==r['weather_sha256'],'runtime_EPW_binding:'+key)
        check(r['effective_location_matches_selected_epw'],'EIO_effective_location:'+key)
        db=sqlite3.connect(runtime/'eplusout.sql')
        try:
            hours=db.execute('select count(*) from Time where coalesce(WarmupFlag,0)=0 and Interval=60').fetchone()[0]
            values=db.execute("""select d.KeyValue,count(*),min(r.Value),max(r.Value),count(r.Value),count(distinct r.TimeIndex),
                sum(case when typeof(r.Value) in ('real','integer') then 1 else 0 end) from ReportData r join ReportDataDictionary d using(ReportDataDictionaryIndex)
                join Time t using(TimeIndex) where d.Name='Zone Mean Air Temperature' and coalesce(t.WarmupFlag,0)=0 and t.Interval=60 group by d.KeyValue""").fetchall()
            expected_times={r[0] for r in db.execute('select TimeIndex from Time where coalesce(WarmupFlag,0)=0 and Interval=60')}
            zone_times={v[0]:set() for v in values}
            for name,index in db.execute("""select d.KeyValue,r.TimeIndex from ReportData r join ReportDataDictionary d using(ReportDataDictionaryIndex)
                join Time t using(TimeIndex) where d.Name='Zone Mean Air Temperature' and coalesce(t.WarmupFlag,0)=0 and t.Interval=60"""):zone_times[name].add(index)
            check(hours==len(expected_times)==8760 and len(values)==len(load(case/'LAYOUT.json')['spaces'])
                and all(n==nonnull==distinct==numeric==8760 and isinstance(lo,(int,float)) and isinstance(hi,(int,float))
                    and math.isfinite(lo) and math.isfinite(hi) and zone_times[name]==expected_times
                    for name,n,lo,hi,nonnull,distinct,numeric in values),'independent_SQL_hourly_count:'+key)
            area=db.execute('select sum(FloorArea) from Zones').fetchone()[0]
            check(math.isclose(area,load(case/'LAYOUT.json')['net_proxy_m2'],abs_tol=1e-5),'independent_SQL_floor_area:'+key)
            annual.append({'case_id':key,'hours':hours,'zone_count':len(values),'area_m2':area})
        finally:db.close()
    prereq=load(folder/'TARGET1000_PREREQUISITE_AUDIT.json')
    root=Path(__file__).resolve().parent.parent
    allocation=load(root/'evidence_contract_20261001/POPULATION_ALLOCATION_CANDIDATE_V2.json')
    check(len(prereq['slots'])==1000 and not prereq['quotas_changed'],'1000_slot_count_unchanged')
    check(all(all(a[k]==b[k] for k in a) for a,b in zip(allocation['slots'],prereq['slots'])),'1000_all_original_slot_fields_unchanged')
    check(prereq['actual_IDF_slots']==0 and all(not s['IDF_created'] and not s['input_family_invented_to_fill_slot'] for s in prereq['slots']),'1000_unknowns_not_filled_by_examples')
    check(summary['generated_family_housing_bound_cases']==sum(r.get('generation_binding_status')=='pass' for r in summary['records']),'generated_profile_case_accounting')
    check(summary['conditional_context_IDFs']==prereq['conditional_context_IDF_cases']==sum(r.get('generation_binding_status')=='pass' and r['status']=='idf_ready' for r in summary['records']),'conditional_context_IDF_accounting')
    check(prereq['generated_family_housing_verified_slots']==len({r['generation_slot_id'] for r in summary['records'] if r.get('generation_binding_status')=='pass'}),'generated_profile_slot_accounting')
    check(summary['actual_household_city_IDFs']==0 and not summary['actual_household_city_binding_certified'],'actual_home_geography_not_inferred')
    result={'schema':'eb.household_idf.verification.v1','experiment_id':summary.get('experiment_id',summary['batch_id']+'__'+folder.name),'pass':all(x['pass'] for x in checks),'check_count':len(checks),
        'failed':[x for x in checks if not x['pass']],'annual_SQL_readback':annual,'checks':checks,
        'scope':'immutable bytes, input preservation, mandatory per-case independent rectangular geometry gate, decision references, source binding, annual output completeness and unassigned1000; no arbitrary-geometry/calibration certification',
        'empirical_calibration':False,'complete1000_dataset':False,'collection_release':False,'training_release':False}
    report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:result[k] for k in ['pass','check_count','failed']}))
    if not result['pass']:raise SystemExit(1)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('folder',type=Path);ap.add_argument('--report',required=True,type=Path)
    args=ap.parse_args();main(args.folder.resolve(),args.report)
