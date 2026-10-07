#!/usr/bin/env python3
"""Bind completion-year candidates to the already selected current dwelling j.

Aggregate diagnostics only. No property/person identifiers or source rows leave
the private process. Years remain source candidates, including proxy semantics.
"""
import argparse
import collections
import json
import sys
from pathlib import Path
from source_semantics import code
from typed_chain import sha

HERE=Path(__file__).resolve().parent
H1000=HERE.parent
sys.path.insert(0,str(H1000/'chfs_census_bridge_20261003'))
import run_bridge as bridge

def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def vintage(year):
    limits=[1948,1959,1969,1979,1989,1999,2009,2014,2020]
    return next((i for i,hi in enumerate(limits) if year<=hi),None)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--profiles',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    if args.output.exists():raise ValueError('new_output_required')
    args.output.mkdir(parents=True)
    raw=bridge.load_bridge_pool();raw=raw[raw.eligible_for_generation_matching & raw.weight.notna() & (raw.weight>0)]
    yy=bridge.read('hh',['hhid',*[f'c2012a_{j}' for j in range(1,7)]])
    byid={r['hhid']:r for r in yy.to_dict('records')}
    records=[];states=collections.Counter();scope=collections.Counter()
    for r in raw.to_dict('records'):
        if not r['area_scope_supported'] or not r['room_proxy_category']:continue
        room=code(r['room_count_h7_proxy'],range(1,100))
        if room is None or r['area_candidate_m2']/room<1:continue
        j=r['current_dwelling_slot']
        if type(j) not in [int,float] or int(j)!=j:states['current_owned_slot_not_resolved']+=1;continue
        y=code(byid[r['_local_hhid']].get(f'c2012a_{int(j)}'),range(1000,10000))
        if y is None:states['missing_or_non_four_digit_year']+=1;continue
        # Housing in 2022 interviews can refer to July2021, and target is2020.
        if y>2020:states['later_than_target2020_not_used_as2020_reference']+=1;continue
        v=vintage(y)
        states['current_slot_year_candidate_admitted_for_reference_audit']+=1
        scope[r['sharing_scope']]+=1
        records.append({**r,'vintage_category_index_proxy':v})
    body=json.loads(args.profiles.read_text());supports=[]
    for p in body['profiles']:
        h=p['housing']
        if not h['H5_is_ordinary_model_assigned']:
            supports.append({'slot_id':p['slot_id'],'ordinary':False,'year_area_room_reference_applicable':False});continue
        req={'province':p['province'],'size_category':p['size_category'],'generation_category':p['generation_category'],
            'room_proxy_category':h['H7_census_bin'],'vintage_category_index_proxy':h['vintage_category_index']}
        layers=[('same_province_N_G_H7_vintage',list(req)),('national_N_G_H7_vintage',list(req)[1:]),
            ('national_G_H7_vintage',list(req)[2:]),('national_H7_vintage',list(req)[3:])]
        support={name:sum(all(r[k]==req[k] for k in fields) for r in records) for name,fields in layers}
        supports.append({'slot_id':p['slot_id'],'ordinary':True,'target':req,'source_support':support,
            'reference_year_is_candidate_completion_or_rebuild_not_verified_target_observation':True})
    groups=collections.defaultdict(list)
    for r in records:groups[(r['room_proxy_category'],r['vintage_category_index_proxy'])].append(r)
    associations=[]
    for (room,v),xs in sorted(groups.items()):
        w=sum(r['weight'] for r in xs)
        associations.append({'H7_proxy_bin':room,'vintage_proxy_bin':v,'records':len(xs),
            'source_weighted_area_mean_m2':sum(r['weight']*r['area_candidate_m2'] for r in xs)/w,
            'Kish_ESS':w*w/sum(r['weight']**2 for r in xs),
            'meaning':'restricted owned-source conditional reference mean; not national target mean'})
    ordinary=[r for r in supports if r['ordinary']]
    report={'schema':'eb.chfs_current_dwelling_vintage_area_support.v1','source_year_states':dict(states),
        'admitted_records':len(records),'source_sharing_scopes':dict(scope),
        'selection':'member proxy valid, whole scope area+room proxy, field-specific quality quarantine, current owned j, four-digit C2012a candidate <=2020',
        'source_quality_year_cutoff_1000_is_design_not_official':True,
        'source_candidate_year_can_be_completion_rebuild_or_expected_delivery':True,
        'acquisition_year_C2012_not_used':True,'member_reference_pool_or_population_slots_deleted':False,
        'conditional_joint_reference_diagnostics':associations,'slot_support':supports,
        'summary':{name+'_zero':sum(r['source_support'][name]==0 for r in ordinary) for name in ordinary[0]['source_support']},
        'ordinary_slots':len(ordinary),'ordinary_status_of_CHFS_reference_not_observed':True,
        'source_id_or_rows_exported':False,'scope':'source construction diagnostic, not a new housing generator or validity certification'}
    save(args.output/'CURRENT_DWELLING_YEAR_AREA_SUPPORT.json',report)
    save(args.output/'VINTAGE_LOCK.json',{'profile_sha256':sha(args.profiles),'source_hh_sha256':sha(next(bridge.PACKAGE.glob('chfs2021_hh_pub_*.dta'))),
        'bridge_sha256':sha(H1000/'chfs_census_bridge_20261003/run_bridge.py'),
        'rules_sha256':sha(H1000/'chfs_census_bridge_20261003/bridge_rules.py'),
        'audit_code_sha256':sha(__file__),'result_sha256':sha(args.output/'CURRENT_DWELLING_YEAR_AREA_SUPPORT.json')})
    print(json.dumps({'admitted':len(records),'summary':report['summary']},ensure_ascii=False))

if __name__=='__main__':main()
