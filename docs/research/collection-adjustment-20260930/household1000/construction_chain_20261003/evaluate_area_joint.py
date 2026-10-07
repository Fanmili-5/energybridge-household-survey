#!/usr/bin/env python3
"""Prespecified owned-source holdout diagnostic for retaining housing vintage.

No IDF results, official-mean fitting, human labels or raw identifiers are used
as predictors. Source identifiers only keep whole households in fixed folds.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path
import numpy as np
from typed_chain import sha
from source_semantics import code
from audit_chfs_vintage import vintage

HERE=Path(__file__).resolve().parent;H1000=HERE.parent
sys.path.insert(0,str(H1000/'chfs_census_bridge_20261003'))
import run_bridge as bridge

def distribution(records):
    if not records:return None
    xs=np.array([r['area_candidate_m2'] for r in records],float);ws=np.array([r['weight'] for r in records],float)
    order=np.argsort(xs);xs=xs[order];ws=ws[order]/ws.sum()
    c=np.cumsum(ws);q=np.cumsum(ws*xs)
    spread=float(np.sum(ws*(xs*(2*(c-ws)+ws-1))))
    return {'x':xs,'w':ws,'mean':float(np.sum(xs*ws)),'half_pairwise_distance':spread,
        'maximum_source_weight':float(ws.max()),'ESS':float(1/np.sum(ws*ws))}

def crps(d,y):return float(np.sum(d['w']*abs(d['x']-y))-d['half_pairwise_distance'])

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    if args.output.exists():raise ValueError('new_evaluation_directory_required')
    args.output.mkdir(parents=True)
    frame=bridge.load_bridge_pool();frame=frame[frame.eligible_for_generation_matching & frame.weight.notna() & (frame.weight>0)]
    years=bridge.read('hh',['hhid',*[f'c2012a_{j}' for j in range(1,7)]])
    year_by_id={r['hhid']:r for r in years.to_dict('records')};records=[]
    salt='EB_CHFS_WHOLE_HOUSEHOLD_FOLDS_20261003_V1'
    for r in frame.to_dict('records'):
        if not r['area_scope_supported'] or not r['room_proxy_category']:continue
        rooms=code(r['room_count_h7_proxy'],range(1,100));j=r['current_dwelling_slot']
        if rooms is None or r['area_candidate_m2']/rooms<1 or type(j) not in [int,float] or int(j)!=j:continue
        y=code(year_by_id[r['_local_hhid']].get(f'c2012a_{int(j)}'),range(1000,2021))
        if y is None:continue
        r['v']=vintage(y)
        # Normalized floating hhid representation is used only in private RAM.
        r['fold']=int(hashlib.sha256((salt+'|'+str(r['_local_hhid'])).encode()).hexdigest(),16)%5
        records.append(r)
    if len(records)!=2628:raise ValueError('source_cohort_changed_reaudit_required')
    metrics=[];gaps=0;post=[]
    for fold in range(5):
        train=[r for r in records if r['fold']!=fold];test=[r for r in records if r['fold']==fold]
        plain={room:distribution([r for r in train if r['room_proxy_category']==room]) for room in ['1','2','3','4','5+']}
        joint={(room,v):distribution([r for r in train if r['room_proxy_category']==room and r['v']==v]) for room in plain for v in range(9)}
        accum={'A_weighted_error':0.0,'B_weighted_error':0.0,'A_weighted_CRPS':0.0,'B_weighted_CRPS':0.0,'common_weight':0.0,'common_records':0}
        missing=0;ESS=[];dominance=[]
        for r in test:
            a=plain[r['room_proxy_category']];b=joint[(r['room_proxy_category'],r['v'])]
            if a is None or b is None:missing+=1;continue
            y=r['area_candidate_m2'];w=r['weight']
            accum['A_weighted_error']+=w*abs(a['mean']-y);accum['B_weighted_error']+=w*abs(b['mean']-y)
            accum['A_weighted_CRPS']+=w*crps(a,y);accum['B_weighted_CRPS']+=w*crps(b,y)
            accum['common_weight']+=w;accum['common_records']+=1;ESS.append(b['ESS']);dominance.append(b['maximum_source_weight'])
        metrics.append({'fold':fold,'train_households':len(train),'test_households':len(test),'unavailable_joint_predictions':missing,
            'A_MAE_m2':accum['A_weighted_error']/accum['common_weight'],'B_MAE_m2':accum['B_weighted_error']/accum['common_weight'],
            'A_CRPS_m2':accum['A_weighted_CRPS']/accum['common_weight'],'B_CRPS_m2':accum['B_weighted_CRPS']/accum['common_weight'],
            'joint_reference_minimum_ESS':min(ESS),'joint_reference_maximum_source_weight':max(dominance),
            'common_records':accum['common_records'],'common_test_weight':accum['common_weight']})
        gaps+=missing;post.append(accum)
    weight=sum(x['common_weight'] for x in post)
    summary={k:sum(x[k] for x in post)/weight for k in ['A_weighted_error','B_weighted_error','A_weighted_CRPS','B_weighted_CRPS']}
    report={'schema':'eb.owned_source_area_vintage_holdout.v1','source_households':len(records),
        'models':{'A':'weighted empirical area reference conditional on H7 proxy bin only',
            'B':'weighted empirical area reference conditional on H7 proxy bin and current-dwelling vintage candidate'},
        'source_fold_salt':salt,'source_fold_count':5,'source_fold_unit':'whole source household; not member/property rows',
        'model_definitions_fixed_in_code_before_evaluation':True,'raw_IDs_not_predictors_or_exported':True,
        'sparse_empty_reference_policy':'no prediction retained as gap; no quiet wrong-H7/vintage fallback',
        'folds':metrics,'weighted_common_support_metrics':summary,'total_unavailable_joint_predictions':gaps,
        'source_selection_and_proxy_limits':['current whole-owned branch only; no rented H7 reference',
            'same source frame and visit-year/time proxy; not independent target2020 validation',
            'CHFS shi and completion/rebuild candidate semantics unresolved',
            'household weights used once; no survey-design standard errors or inferential significance claimed',
            'no exact official aggregate mean was fitted, and no generative within-bin density was validated'],
        'evaluation_selects_formal1000_generator':False,'collection_release':False,'training_release':False}
    (args.output/'AREA_JOINT_HOLDOUT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    lock={'code':{n:sha(HERE/n) for n in ['evaluate_area_joint.py','audit_chfs_vintage.py','source_semantics.py']},
        'source_files':{str(p):sha(p) for p in sorted(bridge.PACKAGE.glob('chfs2021_*_pub_*.dta'))},
        'report_sha256':sha(args.output/'AREA_JOINT_HOLDOUT.json')}
    (args.output/'EVALUATION_LOCK.json').write_text(json.dumps(lock,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'weighted_common_support_metrics':summary,'prediction_gaps':gaps},ensure_ascii=False))

if __name__=='__main__':main()
