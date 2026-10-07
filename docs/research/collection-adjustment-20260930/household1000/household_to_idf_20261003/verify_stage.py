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
    for record in summary['records']:
        key=record['case_id'];case=folder/'cases'/record['case_folder'];item=load(case/'INPUT.json')
        check(digest(item)==digest(locked[key])==record['input_semantic_sha256'],'frozen_input:'+key)
        check(record['status']==record['expected_result'],'expected_admission:'+key)
        check(not record['collection_release'] and not record['training_release'] and not record['complete_actor_role'],'scope:'+key)
        if record['status']!='idf_ready':check(not (case/'building.idf').exists(),'no_IDF_for_refused_input:'+key);continue
        layout=load(case/'LAYOUT.json');binding=load(case/'ASSEMBLY_BINDING.json')
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
            values=db.execute("""select d.KeyValue,count(*),min(r.Value),max(r.Value) from ReportData r join ReportDataDictionary d using(ReportDataDictionaryIndex)
                join Time t using(TimeIndex) where d.Name='Zone Mean Air Temperature' and coalesce(t.WarmupFlag,0)=0 group by d.KeyValue""").fetchall()
            check(hours==8760 and len(values)==len(load(case/'LAYOUT.json')['spaces']) and all(n==8760 and math.isfinite(lo) and math.isfinite(hi) for _,n,lo,hi in values),'independent_SQL_hourly_count:'+key)
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
    result={'schema':'eb.household_idf.verification.v1','experiment_id':summary.get('experiment_id',summary['batch_id']+'__'+folder.name),'pass':all(x['pass'] for x in checks),'check_count':len(checks),
        'failed':[x for x in checks if not x['pass']],'annual_SQL_readback':annual,'checks':checks,
        'scope':'immutable bytes, input preservation, decision references, source binding, annual output completeness and unassigned1000; independent geometry in separate report',
        'empirical_calibration':False,'complete1000_dataset':False,'collection_release':False,'training_release':False}
    report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:result[k] for k in ['pass','check_count','failed']}))
    if not result['pass']:raise SystemExit(1)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('folder',type=Path);ap.add_argument('--report',required=True,type=Path)
    args=ap.parse_args();main(args.folder.resolve(),args.report)
