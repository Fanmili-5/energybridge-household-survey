"""Research-only eCAPE fixed-six; never imports a production generator."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from sklearn.metrics import adjusted_rand_score
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
sys.path.insert(0, str(REPO / 'artifacts/eb_external_validation_20261019'))
from run_validation import LCA, aligned

SEED = 20261019
AGREE = ['Meget enig', 'Delvist enig']
DISAGREE = ['Meget uenig', 'Delvist uenig']
REGULAR = ['I meget høj grad', 'I høj grad']
REGULAR_VALID = REGULAR + ['I nogen grad', 'Hverken eller', 'I lav grad', 'I meget lav grad']


def save(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')


def prepare(raw):
    d = raw.loc[raw.int_resultat.str.strip().eq('1. Svar')].reset_index(drop=True)
    assert len(d) == 1022 and d.resp_id1.is_unique
    native = lambda col: d[col].astype('str').str.strip()
    f = pd.DataFrame(index=d.index)
    a, b = native('q16_morgen'), native('q16_aften')
    both_known = a.isin(REGULAR_VALID) & b.isin(REGULAR_VALID)
    n_high = a.isin(REGULAR).astype(int) + b.isin(REGULAR).astype(int)
    f['weekday_regularity'] = n_high.map({0: 'neither_high', 1: 'one_high', 2: 'both_high'}).where(both_known)
    for name, col in [('job_related_routine_changes', 'q17_job'), ('routine_interruptions', 'q20_forstyr'), ('external_fixed_schedule', 'q20_tid')]:
        f[name] = native(col).map({**{v: 'agree' for v in AGREE}, **{v: 'disagree' for v in DISAGREE}, 'Hverken eller': 'neutral'})
    hours = pd.to_numeric(d.q14, errors='coerce').where(lambda x: x.between(0, 24))
    f['weekday_awake_home_hours'] = pd.cut(hours, [-np.inf, 8, 12, np.inf], right=False, labels=['below8', '8toBelow12', '12plus']).astype(object)
    care1, care2 = native('q22_care'), native('q26_care')
    assert care1.isin(['Ja', 'Nej']).all() and care2.isin(['Ja', 'Nej']).all()
    f['care_activity_two_days'] = (care1.eq('Ja').astype(int) + care2.eq('Ja').astype(int)).map({0: 'neither_day', 1: 'one_day', 2: 'both_days'})
    heat1, heat2 = native('q6_termo'), native('q6_varme')
    active_labels = ['Ja, og de bliver brugt', 'Ja, og det bliver brugt']
    allowed = active_labels + ['Ja, men de bliver ikke brugt', 'Ja, men det bliver ikke brugt', 'Nej']
    assert heat1.isin(allowed).all() and heat2.isin(allowed).all()
    active = heat1.isin(active_labels) | heat2.isin(active_labels)
    owned = heat1.ne('Nej') | heat2.ne('Nej')
    f['smart_heat_use'] = np.select([active, owned], ['active', 'owned_unused_only'], default='none')
    assert native('q3_6').isin(['Ingen', '1']).all()
    f['EV_ownership'] = native('q3_6').map({'Ingen': 'none', '1': 'EV_owned'})
    bg = pd.DataFrame(index=d.index)
    bg['morning_high_regularity'] = a.isin(REGULAR).where(a.isin(REGULAR_VALID))
    bg['evening_high_regularity'] = b.isin(REGULAR).where(b.isin(REGULAR_VALID))
    for field in ['q17_livsstil', 'q17_husstand']:
        bg[field + '_agree'] = native(field).isin(AGREE).where(native(field).isin(AGREE+DISAGREE+['Hverken eller']))
    for field in ['q13', 'aldergrp4', 'hjemb0012', 'hjemb1319', 'q21a', 'q5_vask_aarsag']:
        bg[field] = d[field].astype('str').str.strip().replace({'nan': np.nan, 'Ved ikke': np.nan, 'Ønsker ikke at svare': np.nan})
    bg['weekday_awake_home_hours_raw'] = hours
    return d, f, bg


def encode_frame(f):
    names, parts, categories = {}, [], []
    for col in f:
        values = sorted(f[col].dropna().unique().tolist(), key=str)
        names[col] = values
        parts.append(pd.Categorical(f[col], categories=values).codes)
        categories.append(list(range(len(values))))
    return np.array(parts).T, categories, names


def profiles(f, bg, post, order):
    rows = []
    for label, k in enumerate(order):
        w = post[:, k]
        row = {'class': 'H'+str(label+1), 'share': float(w.mean()), 'soft_n': float(w.sum()),
               'hard_n': int((post.argmax(1) == k).sum()), 'inputs': {}, 'posthoc': {}}
        for frame, target in [(f, row['inputs']), (bg, row['posthoc'])]:
            for col in frame:
                known = frame[col].notna().to_numpy()
                denom = float(w[known].sum())
                if col == 'weekday_awake_home_hours_raw':
                    target[col] = {'known_soft_n': denom, 'mean': float(w[known] @ frame.loc[known,col].to_numpy()/denom)}
                else:
                    target[col] = {'known_soft_n': denom, 'known_fraction': denom/float(w.sum()),
                                   'distribution': {str(v): float(w @ frame[col].eq(v).fillna(False).to_numpy(dtype=float)/denom)
                                                    for v in sorted(frame[col].dropna().unique(), key=str)} if denom else {}}
        rows.append(row)
    return rows


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--raw', type=Path, required=True)
    p.add_argument('--output', type=Path, default=ROOT)
    args = p.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    plan = json.loads((ROOT/'ANALYSIS_PLAN.json').read_text())
    assert hashlib.sha256(args.raw.read_bytes()).hexdigest() == plan['raw_sha256']
    seal = json.loads((REPO/'artifacts/eb_eca_linkage_audit_20261019/RESEARCH_MANIFEST.json').read_text())
    solver_paths = ['artifacts/eb_external_validation_20261019/run_validation.py','artifacts/eb_source_selection_20261019/cluster_iflex.py']
    for rel in solver_paths:
        assert hashlib.sha256((REPO/rel).read_bytes()).hexdigest() == seal['files_sha256'][rel]
    raw = pd.read_csv(args.raw, sep=';', encoding='cp1252', low_memory=False)
    d, f, bg = prepare(raw)
    assert list(f) == plan['features']
    x, categories, names = encode_frame(f)
    save(args.output/'FIELD_AUDIT.json', {'n':len(d), 'input_distributions':{col:{str(k):int(v) for k,v in f[col].value_counts(dropna=False).items()} for col in f},
                                       'missing_items':{col:int(f[col].isna().sum()) for col in f}, 'input_categories':names,
                                       'weighting':'unit weights; supplied public file contains no survey weights', 'production_changes':False})
    model = LCA(6, categories, SEED).fit(x, starts=48)
    post = model.posterior(x)
    assert np.allclose(post.sum(1),1) and np.isclose(model.pi.sum(),1)
    order = np.argsort(-post.mean(0))
    report = {'schema':'eb.ecape.fixed_six.results.v1','n':len(d),'fixed_k':6,'plan':plan,'category_names':names,
              'fit':model.summary(x),'parameters':{'pi':model.pi.tolist(),'theta':model.theta.tolist(),'categories':categories},
              'model_columns_by_reported_class':order.tolist(),'profiles':profiles(f,bg,post,order),
              'bootstrap':[],'sensitivities':[],'production_changes':False,'EP_runs':0,'new_benchmark_labels':0}
    save(args.output/'RESULTS.partial.json',report)
    print(json.dumps({'stage':'primary','converged':model.converged,'near_best_starts':report['fit']['starts_within_1_loglik'],
                      'shares':[row['share'] for row in report['profiles']]}),flush=True)
    direct = 0.0
    for col in f:
        counts = f[col].value_counts().to_numpy()
        direct += float(counts @ np.log(counts/counts.sum()))
    one = LCA(1,categories,SEED+1).fit(x,starts=1)
    report['one_class_missing_likelihood_error'] = abs(direct-one.ll)
    assert report['one_class_missing_likelihood_error']<1e-3
    rng = np.random.default_rng(SEED+2)
    for b in range(20):
        counts = np.bincount(rng.integers(0,len(x),len(x)),minlength=len(x))
        m = LCA(6,categories,SEED+100+b).fit(x,row_weights=counts,starts=12)
        bp,_ = aligned(post,m.posterior(x))
        entry = {'replicate':b,'ARI':float(adjusted_rand_score(post.argmax(1),bp.argmax(1))),
                 'aligned_share':np.average(bp,weights=counts,axis=0)[order].tolist(),'converged':m.converged}
        report['bootstrap'].append(entry)
        print(json.dumps({'stage':'bootstrap',**{k:entry[k] for k in ['replicate','ARI','converged']}}),flush=True)
        save(args.output/'RESULTS.partial.json',report)
    report['bootstrap_summary'] = {'median_ARI':float(np.median([v['ARI'] for v in report['bootstrap']])),
                                   'min_ARI':float(min(v['ARI'] for v in report['bootstrap'])),
                                   'share_resample_interval2p5_97p5_not_population_CI':np.quantile([v['aligned_share'] for v in report['bootstrap']],[.025,.975],axis=0).T.tolist()}
    alt = f.copy()
    alt['weekday_awake_home_hours'] = pd.cut(bg.weekday_awake_home_hours_raw,[-np.inf,10,14,np.inf],right=False,labels=['below10','10toBelow14','14plus']).astype(object)
    variants = [('without_EV',f.drop(columns='EV_ownership')),('routines_only',f.iloc[:,:4]),('home_hours_edges10_14',alt)]
    for i,(name,ff) in enumerate(variants):
        xx,cc,_ = encode_frame(ff)
        m = LCA(6,cc,SEED+200+i).fit(xx,starts=32)
        ap,_ = aligned(post,m.posterior(xx))
        entry = {'name':name,'features':list(ff),'ARI':float(adjusted_rand_score(post.argmax(1),ap.argmax(1))),
                 'aligned_share':ap.mean(0)[order].tolist(),'converged':m.converged,'fit':m.summary(xx)}
        report['sensitivities'].append(entry)
        print(json.dumps({'stage':'sensitivity','name':name,'ARI':entry['ARI'],'converged':m.converged}),flush=True)
    report['source_solver_sha256'] = {rel:hashlib.sha256((REPO/rel).read_bytes()).hexdigest() for rel in solver_paths}
    save(args.output/'RESULTS.json',report)
    (args.output/'RESULTS.partial.json').unlink()
    print(json.dumps({'stage':'complete','bootstrap':report['bootstrap_summary'],'production_changes':False,'EP_runs':0}),flush=True)


if __name__ == '__main__':
    with threadpool_limits(limits=1):
        main()
