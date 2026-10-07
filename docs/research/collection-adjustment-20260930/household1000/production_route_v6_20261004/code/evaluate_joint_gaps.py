"""Whole-household held-out test of preserving age-role pairs.

Compare coarsened joint pairs to separately sampled role-age marginals, using
identical training strata and the SAME coarsening. Not full-generator validation.
"""
import collections
import json
from pathlib import Path
import numpy as np
from joint_motifs import load_source, fold, coarse_age_pmf

OUT = Path(__file__).resolve().parent.parent


def pairs(r, kind):
    root = next(a for a in r['atom'] if a[0] == 1)
    if kind == 'partner':
        others = [a for a in r['atom'] if a[0] == 2]
    else:
        others = [a for a in r['atom'] if a[0] == 6]
    return [(root,a) for a in others]


def observed_gaps(r,kind):
    roots = [v for rel,v in r['raw_birthyears'] if rel == 1]
    others = [v for rel,v in r['raw_birthyears'] if rel == (2 if kind == 'partner' else 6)]
    if kind == 'partner': return [abs(v-roots[0]) for v in others]
    return [v-roots[0] for v in others]


def distribution(training, kind, joint):
    pmf = collections.Counter(); root_marginal = collections.Counter(); other_marginal = collections.Counter()
    mass = 0
    for r in training:
        for a,b in pairs(r,kind):
            pa,pb = coarse_age_pmf(a),coarse_age_pmf(b); weight = r['weight']
            for x,p in pa.items(): root_marginal[x] += weight*p
            for y,p in pb.items(): other_marginal[y] += weight*p
            for x,px in pa.items():
                for y,py in pb.items():
                    gap = abs(x-y) if kind == 'partner' else x-y
                    pmf[gap] += weight*px*py
            mass += weight
    if not joint:
        pmf = collections.Counter()
        for x,wx in root_marginal.items():
            for y,wy in other_marginal.items():
                gap = abs(x-y) if kind == 'partner' else x-y
                pmf[gap] += wx*wy/mass
    if not mass: raise ValueError('no_pair_source_training_support')
    support = np.array(sorted(pmf),dtype=float); p = np.array([pmf[k]/sum(pmf.values()) for k in support])
    assert abs(p.sum()-1) < 1e-10
    spread = float(np.sum(np.abs(support[:,None]-support[None,:])*p[:,None]*p[None,:])/2)
    return support,p,spread


def crps(pred,y):
    support,p,spread = pred
    return float(np.sum(np.abs(support-y)*p)-spread)


def main():
    records,qc = load_source(); records = [r for r in records if r['visit_year'] == 2021]
    results = []
    for kind in ['partner','parent_child']:
        folds = []; totals = np.zeros(3); scored_households = set(); scored_pairs = 0
        for f in range(5):
            train = [r for r in records if fold(r) != f and pairs(r,kind)]
            test = [r for r in records if fold(r) == f and pairs(r,kind)]
            cache = {}; accum = np.zeros(3)
            for r in test:
                key=(r['N'],r['G'])
                if key not in cache:
                    local = [t for t in train if (t['N'],t['G']) == key]
                    pool = local if local else train
                    cache[key]=(distribution(pool,kind,True),distribution(pool,kind,False),len(pool))
                jp,ip,_ = cache[key]
                for y in observed_gaps(r,kind):
                    weight=r['weight'];v=np.array([crps(jp,y),crps(ip,y),1])*weight
                    accum+=v;totals+=v;scored_pairs+=1
                scored_households.add(r['_private_id'])
            folds.append({'fold':f,'train_households':len(train),'test_households':len(test),
                          'joint_CRPS_years':float(accum[0]/accum[2]),
                          'factorized_CRPS_years':float(accum[1]/accum[2])})
        results.append({'pair_type':kind,'scored_source_households':len(scored_households),'scored_pairs':scored_pairs,
                        'joint_CRPS_years':float(totals[0]/totals[2]),'factorized_CRPS_years':float(totals[1]/totals[2]),
                        'delta_joint_minus_factorized':float((totals[0]-totals[1])/totals[2]),'folds':folds})
    result={'evaluation':'5fold_whole_source_household_pair_age_gap_proxy','fold_salt':'EB_JOINT_MOTIF_GAP_OUTER_FOLDS_20261004_V1',
            'data_scope':'CHFS2021_actual_visit2021_city_sampling_address_complete_ego_relation_sex_birth_coresidence_proxy',
            'outcome':'absolute_partner_or_signed_parent_child_birthyear_difference_proxy; age_birthdays_not_observed',
            'source_QC':qc,'results':results,'survey_design_SE_available':False,
            'full_household_joint_or_China_census_population_validated':False,
            'same_NG_train_stratum_and_same_5year_coarsening_for_both_models':True,
            'no_test_households_used_in_training':True,'selection_status':'development_benchmark; not_final_blind_release_test'}
    (OUT/'JOINT_AGE_GAP_HOLDOUT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'results':[{k:v for k,v in r.items() if k!='folds'} for r in results]},ensure_ascii=False,indent=2))


if __name__ == '__main__': main()
