#!/usr/bin/env python3
"""Reproduce aggregate domain/companion review without editing source values."""
import argparse
import collections
import json
import sys
from pathlib import Path
import numpy as np
from source_semantics import code
from typed_chain import sha

HERE=Path(__file__).resolve().parent;H1000=HERE.parent
sys.path.insert(0,str(H1000/'chfs_census_bridge_20261003'))
import run_bridge as bridge

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    if args.output.exists():raise ValueError('new_quality_review_required')
    frame=bridge.load_bridge_pool();frame=frame[frame.eligible_for_generation_matching & frame.weight.notna() & (frame.weight>0)]
    yy=bridge.read('hh',['hhid',*[f'c2012a_{j}' for j in range(1,7)]]);years={r['hhid']:r for r in yy.to_dict('records')};rs=[]
    for r in frame.to_dict('records'):
        rooms=code(r['room_count_h7_proxy'],range(1,100));j=r['current_dwelling_slot']
        if not r['area_scope_supported'] or not r['room_proxy_category'] or rooms is None or r['area_candidate_m2']/rooms<1 or type(j) not in [int,float] or int(j)!=j:continue
        if code(years[r['_local_hhid']].get(f'c2012a_{int(j)}'),range(1000,2021)) is not None:rs.append(r)
    a=np.array([r['area_candidate_m2'] for r in rs]);w=np.array([r['weight'] for r in rs]);outside=[r for r in rs if r['area_candidate_m2']>2000]
    report={'schema':'eb.area_source_quality_review.v1','source_records':len(rs),
        'area_quantiles_m2':{str(q):float(np.quantile(a,q)) for q in [0,.25,.5,.75,.95,.99,1]},
        'weighted_area_mean_m2':float(np.sum(a*w)/sum(w)),
        'above_prior_declared_generator_domain_records':len(outside),
        'above_domain_weighted_mass':float(sum(r['weight'] for r in outside)/sum(w)),
        'above_domain_related_invalid_field_stems':dict(collections.Counter(s.split('_')[0] for r in outside for s in r['area_invalid_fields'])),
        'above_domain_usable_area_present':int(sum(bool(r['recorded_usable_area_m2'] is not None and np.isfinite(r['recorded_usable_area_m2'])) for r in outside)),
        'above_domain_consistent_with_source_auto0p7':int(sum(bool(r['consistent_with_source_auto0_7']) for r in outside)),
        'quality_cutoffs_are_declared_reference_model_design_not_official_housing_limits':True,
        'raw_values_changed':0,'rows_or_IDs_exported':False,'typo_or_nonordinary_status_adjudicated':False,
        'next_source_check':'verify native numeric units, field-specific missing codes, current-property versus family-exclusive scope and ordinary-housing applicability before choosing area reference admission',
        'review_after_holdout_diagnostic':True,'code_sha256':sha(__file__),
        'native_source_hh_sha256':sha(next(bridge.PACKAGE.glob('chfs2021_hh_pub_*.dta')))}
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ['source_records','above_prior_declared_generator_domain_records','above_domain_weighted_mass','raw_values_changed']}))

if __name__=='__main__':main()
