#!/usr/bin/env python3
"""Paired input audit and area-weighted hourly free-floating temperature readback."""
import argparse
import copy
import json
import math
import sqlite3
from pathlib import Path
from household_model import save,sha,digest

def read_temperature(folder):
    db=sqlite3.connect(folder/'eplusout.sql')
    try:
        areas={r[0].upper():r[1] for r in db.execute('select ZoneName,FloorArea from Zones')}
        rows=db.execute("""select t.TimeIndex,d.KeyValue,r.Value from ReportData r
            join ReportDataDictionary d using(ReportDataDictionaryIndex) join Time t using(TimeIndex)
            where d.Name='Zone Mean Air Temperature' and coalesce(t.WarmupFlag,0)=0 order by t.TimeIndex,d.KeyValue""").fetchall()
        weighted={}
        for t,z,v in rows:weighted[t]=weighted.get(t,0)+v*areas[z.upper()]/sum(areas.values())
        values=list(weighted.values())
        assert len(values)==8760 and all(math.isfinite(v) for v in values)
        return values,{'area_weighted_annual_mean_C':sum(values)/len(values),'minimum_hourly_area_weighted_C':min(values),
            'maximum_hourly_area_weighted_C':max(values),'zone_floor_area_m2':sum(areas.values()),'hourly_count':len(values)}
    finally:db.close()

def paired_input_equal(a,b,path):
    a,b=copy.deepcopy(a),copy.deepcopy(b)
    for x in [a,b]:
        for k in ['case_id','purpose','paired_reference','factor_path','template_transport_evidence']:x.pop(k,None)
        obj=x;parts=path.split('.')
        for p in parts[:-1]:obj=obj[p]
        obj.pop(parts[-1])
    return digest(a)==digest(b)

def main(folder,report):
    inputs={x['case_id']:x for x in json.loads((folder/'EXPERIMENT_INPUTS.json').read_text())}
    summary=json.loads((folder/'SUMMARY.json').read_text())
    passed={r['case_id'] for r in summary['runtime'] if r['status']=='pass'}
    statistics={};series={}
    for key in sorted(passed):series[key],statistics[key]=read_temperature(folder/'runtime'/key)
    paired=[]
    for key,item in inputs.items():
        if key not in passed or 'paired_reference' not in item:continue
        ref=item['paired_reference'];factor=item['factor_path'];assert ref in passed
        equal=paired_input_equal(item,inputs[ref],factor);assert equal
        diff=[a-b for a,b in zip(series[key],series[ref])]
        paired.append({'case_id':key,'reference':ref,'factor_path':factor,'other_conditional_inputs_identical':equal,
            'family_hash_unchanged':digest(item['family'])==digest(inputs[ref]['family']),
            'housing_hash_unchanged':digest(item['housing'])==digest(inputs[ref]['housing']),
            'annual_mean_delta_C':sum(diff)/len(diff),'hourly_area_weighted_temperature_RMSE_C':math.sqrt(sum(v*v for v in diff)/len(diff)),
            'maximum_absolute_hourly_difference_C':max(map(abs,diff)),
            'interpretation':'conditional numerical sensitivity; climate pairs hold Chengdu prototype fixed and are not local-stock matches'})
    save(report,{'schema':'eb.household_idf.sensitivity.v1','experiment_id':summary.get('experiment_id',summary['batch_id']+'__'+folder.name),'input_sha256':sha(folder/'EXPERIMENT_INPUTS.json'),
        'batch_summary_sha256':sha(folder/'SUMMARY.json'),'statistics':statistics,'paired_comparisons':paired,
        'metric_definition':'hourly sum(zone floor area * zone mean air temperature)/sum(zone floor area), then average over8760h; area weighting is a declared diagnostic',
        'hypothesis_tested':'prespecified geometry/boundary/orientation/ACH/weather perturbations change annual free-floating thermal-shell outputs while family and housing inputs stay fixed',
        'energy_or_electricity_result':False,'empirical_calibration':False,'population_inference':False,
        'limitations':['single source prototype and baseline family; no statistical uncertainty or generalization claim','not measured indoor temperature or comfort; no people/device/HVAC gains','net ratio changes geometry and weighting; weather changes do not validate template transport']})
    print(json.dumps({'paired_comparisons':len(paired),'all_single_factor_inputs_verified':all(p['other_conditional_inputs_identical'] for p in paired)},ensure_ascii=False))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('folder',type=Path);ap.add_argument('--report',required=True,type=Path)
    args=ap.parse_args();main(args.folder.resolve(),args.report)
