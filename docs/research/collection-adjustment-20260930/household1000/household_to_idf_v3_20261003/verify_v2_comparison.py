#!/usr/bin/env python3
"""Compare actual frozen INPUT/status/bindings, without compiling or resampling."""
import argparse,collections,hashlib,json
from pathlib import Path

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main(old,new,output):
    a=json.loads((old/'SUMMARY.json').read_text());b=json.loads((new/'SUMMARY.json').read_text())
    am={r['case_id']:r for r in a['records']};bm={r['case_id']:r for r in b['records']};errors=[];gains=[];pairs=[]
    if set(am)!=set(bm):errors.append('case_set_changed')
    for key in sorted(set(am)&set(bm)):
        x,y=am[key],bm[key];op=old/'cases'/key;np=new/'cases'/key
        oi=json.loads((op/'INPUT.json').read_text());ni=json.loads((np/'INPUT.json').read_text())
        issues=[]
        if oi!=ni:issues.append('entire_input_semantics_changed')
        if sha(op/'INPUT.json')!=sha(np/'INPUT.json'):issues.append('actual_input_bytes_changed')
        if x['status']=='idf_ready' and y['status']!='idf_ready':issues.append('previously_admitted_case_regressed')
        if y['status']=='idf_ready' and (y.get('functional_layout_status')!='not_validated' or y.get('device_placement_status')!='not_validated' or y.get('collectable') is not False):issues.append('functional_or_device_claim_promoted')
        for name in ['WEATHER_MATCH.json','PROTOTYPE_MATCH.json']:
            if not (op/name).exists() or not (np/name).exists():continue
            ox=json.loads((op/name).read_text());nx=json.loads((np/name).read_text())
            if name=='WEATHER_MATCH.json':
                ow=ox.get('selected');nw=nx.get('selected')
                if ow and nw and (ow['id'],ow['epw_sha256'])!=(nw['id'],nw['epw_sha256']):issues.append('weather_reselected')
            elif ox.get('eligible') and nx.get('eligible'):
                if (ox['selected_group_id'],ox['selected_role_key'])!=(nx['selected_group_id'],nx['selected_role_key']):issues.append('prototype_reselected')
        if x['status']=='blocked' and y['status']=='idf_ready':
            gains.append({'case_id':key,'old_errors':x['errors'],'H6':oi['housing']['H6_building_area_m2'],'H7':oi['housing']['H7_natural_rooms_exact'],'n':oi['family']['resident_count'],'gain_layer':'compact_thermal_partition' if 'template_capacity_failure_no_area_or_H7_repair' in x['errors'] else 'single_storey_roof_ground','functional_layout_status':y['functional_layout_status']})
        pairs.append({'case_id':key,'actual_input_sha256':sha(np/'INPUT.json'),'old_status':x['status'],'new_status':y['status'],'issues':issues})
        errors.extend(key+':'+v for v in issues)
    result={'V2_summary_path':str(old/'SUMMARY.json'),'V2_summary_sha256':sha(old/'SUMMARY.json'),'V3_summary_path':str(new/'SUMMARY.json'),'V3_summary_sha256':sha(new/'SUMMARY.json'),'input_cases_compared':len(pairs),'entire_input_semantics_and_bytes_identical':not any('input_' in e for e in errors),'before_ready':a['IDF_ready'],'after_ready':b['IDF_ready'],'before_blocked':a['blocked'],'after_blocked':b['blocked'],'gain_counts':dict(collections.Counter(r['gain_layer'] for r in gains)),'gains':gains,'pairs':pairs,'errors':errors,'status':'pass' if not errors else 'fail','population_or_weather_reselection':False,'furniture_or_habitability_verified':False,'ready_scope':'conditional thermal shells; functional and device layout not_validated; collectable false','verifier_sha256':sha(Path(__file__))}
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k not in ['pairs','gains']},ensure_ascii=False))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--old',type=Path,required=True);ap.add_argument('--new',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args();main(args.old.resolve(),args.new.resolve(),args.output.resolve())
