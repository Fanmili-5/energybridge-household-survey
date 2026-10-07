#!/usr/bin/env python3
"""Aggregate source-domain audit; no household IDs or microdata rows exported."""
import collections
import hashlib
import json
from pathlib import Path
import generate_candidates as gen

HERE=Path(__file__).resolve().parent
def main():
    gen.MODEL.update(age_bin_width=5,birthyear_upper_probability=.5,shrinkage_tau=20.0)
    records=gen.load_references()
    body=json.loads((HERE/'final_tilt_tau20/FAMILY_HOUSING_CANDIDATES.json').read_text())
    rows=[]
    for p in body['profiles']:
        h=p['housing']
        if not h['H5_is_ordinary_model_assigned']:continue
        room=h['H7_census_bin']
        pool,_=gen.select_pool(records,p['province'],p['size_category'],p['generation_category'],'area',room)
        low=[]
        for b in h['area_reference']['predictive_area_bins']:
            relevant=[r for r in pool if b['lower_m2']<=r['area_candidate_m2']<=b['upper_m2']]
            if not relevant:continue
            vals=[float(r['area_candidate_m2']) for r in relevant]
            byroom=collections.Counter();byscope=collections.Counter();bymethod=collections.Counter()
            for r in relevant:
                byroom[str(r['room_proxy_category'])]+=float(r['weight'])
                byscope[str(r['sharing_scope'])]+=float(r['weight'])
                bymethod[str(r.get('area_method','not_recorded'))]+=float(r['weight'])
            low.append({'coarse_bin_m2':[b['lower_m2'],b['upper_m2']],
                'source_records':len(vals),'aggregate_source_min_m2':min(vals),'aggregate_source_max_m2':max(vals),
                'source_weighted_mass':sum(float(r['weight']) for r in relevant),
                'source_room_bin_weight_mass':dict(byroom),'source_scope_weight_mass':dict(byscope),'source_area_method_weight_mass':dict(bymethod)})
        ratio=h['sharing_model']['whole_to_exclusive_design_ratio']
        area=h['H6_building_area_m2'];unallocated=area/ratio
        inside=any(b['aggregate_source_min_m2']-.005/ratio<=unallocated<=b['aggregate_source_max_m2']+.005/ratio for b in low)
        rows.append({'slot_id':p['slot_id'],'province':p['province'],'size_category':p['size_category'],'generation_category':p['generation_category'],
            'modeled_H6_m2':area,'H7_exact':h['H7_natural_rooms_exact'],'H7_bin':room,'modeled_occupancy_scope':h['occupancy_scope'],
            'model_exclusive_area_ratio':ratio,'generated_area_within_conditioned_empirical_bin_endpoints':inside,
            'current_mixture_room_relaxation':[c for c in h['area_reference']['reference_mixture']['components'] if c['mass']>0 and c['room_condition_relaxed']],
            'predictive_bin_source_aggregate_support':low})
    out={'schema':'eb.area_empirical_endpoint_audit.v1','source_records_admitted':len(records),'profile_sha256':hashlib.sha256((HERE/'final_tilt_tau20/FAMILY_HOUSING_CANDIDATES.json').read_bytes()).hexdigest(),
        'ordinary_profiles':len(rows),'outside_empirical_bin_endpoint_profiles':sum(not r['generated_area_within_conditioned_empirical_bin_endpoints'] for r in rows),
        'aggregate_source_support_only_not_original_rows':True,'microdata_IDs_exported':False,'profiles':rows,
        'policy_issue':'uniform whole coarse-bin support may extend below/above actual conditional source support; source-scope mixture and same-room relaxation need separate policies'}
    (HERE/'AREA_SOURCE_ENDPOINT_AUDIT.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:v for k,v in out.items() if k!='profiles'},ensure_ascii=False))
    for r in rows:
        if r['slot_id'] in ['cityslot-0253','cityslot-0368']:
            print(json.dumps(r,ensure_ascii=False))

if __name__=='__main__':main()
