"""Research-only fixed-six ECA model with coarse life/health/EV context."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from scipy.special import logsumexp
from sklearn.metrics import adjusted_rand_score
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parent
PREVIOUS = ROOT.parent / 'eb_external_validation_20261019'
sys.path.insert(0, str(PREVIOUS))
from run_validation import LCA, aligned, encode, numeric

SEED = 20261019
ATTITUDES = {
    'electricity_cost_concern': 'Q11. The cost of electricity',
    'avoided_HVAC_for_cost': 'Q35. Avoided heating or cooling',
    'low_energy_discomfort': 'Q33a. Experience discomfort',
    'VPP_interest': 'Q58.',
    'automation_adoption_or_intent': 'Q51a. A home automation system',
    'health_impacts_energy_use': 'Z7. I or someone I live with has a health condition',
}


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def col(d, prefix):
    matches = [c for c in d if str(c).startswith(prefix)]
    assert len(matches) == 1, (prefix, matches)
    return matches[0]


def prepare(raw):
    f = pd.DataFrame({name: raw[col(raw, prefix)] for name, prefix in ATTITUDES.items()})
    sources = {name: [col(raw, prefix)] for name, prefix in ATTITUDES.items()}
    home, occupancy_cols = [], []
    for day in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']:
        candidates = [c for c in raw if c.startswith('A3. ' + day)]
        self_col = next(c for c in candidates if '- You are' in c)
        other_col = next(c for c in candidates if '- Someone else' in c)
        away_col = next(c for c in candidates if '- No one' in c)
        occupancy_cols += [self_col, other_col, away_col]
        assert raw[[self_col, other_col, away_col]].isin(['Yes', 'No']).all().all()
        at_home = raw[self_col].eq('Yes') | raw[other_col].eq('Yes')
        away = raw[away_col].eq('Yes')
        assert (at_home ^ away).all(), 'A3 contradiction or missing response'
        home.append(at_home.to_numpy(dtype=int))
    n_home = np.array(home).sum(0)
    f['weekday_home_pattern'] = np.select([n_home == 5, n_home == 0], ['home_all5', 'away_all5'], default='home_some1to4')
    sources['weekday_home_pattern'] = occupancy_cols
    f['work_status'] = raw[col(raw, 'Q6b.')]
    sources['work_status'] = [col(raw, 'Q6b.')]
    child_cols = [col(raw, 'A2a1.'), col(raw, 'A2a2.')]
    assert raw[child_cols].notna().all().all()
    f['dependent_children'] = np.where(raw[child_cols].sum(axis=1) > 0, 'under18_present', 'no_under18')
    sources['dependent_children'] = child_cols
    ev_cols = [col(raw, 'Q201. A fully electric'), col(raw, 'Q201. Plugin hybrid')]
    yes = 'Yes / you or family member in household own'
    assert raw[ev_cols].stack().dropna().isin([yes, 'No']).all()
    has_ev = raw[ev_cols].eq(yes).any(axis=1)
    no_car = raw[col(raw, 'Q200.')].eq(0)
    assert raw.loc[~no_car, ev_cols].notna().all().all()
    charger_col = col(raw, 'Q212. You have a dedicated')
    assert raw.loc[has_ev, charger_col].isin(['Yes', 'No']).all()
    assert raw.loc[~has_ev, charger_col].isna().all()
    f['EV_home_charger'] = np.select([~has_ev, raw[charger_col].eq('Yes')], ['no_EV_or_PHEV', 'EV_with_dedicated_home_charger'], default='EV_without_dedicated_home_charger')
    sources['EV_home_charger'] = ev_cols + [col(raw, 'Q200.'), charger_col]
    w = raw[col(raw, 'Weight - Age')].to_numpy(dtype=float, copy=True)
    assert np.isfinite(w).all() and (w > 0).all()
    w /= w.mean()
    work = raw[col(raw, 'Q6b.')]
    employed = work.isin(['Working full time', 'Working part time', 'Working casually'])
    location = raw[col(raw, 'A7aa.')]
    assert location[employed].notna().all() and location[~employed].isna().all()
    location_mapping = {
        'You are employed in a job where you are unable to work from home': 'on_site_only',
        'You are employed in a job where you can work from home some of the time': 'hybrid_possible',
        'You are employed in a job where you can work from home all of the time': 'home_based_possible',
        'You run your own business where you work primarily from home': 'home_based_possible',
    }
    work_location = location.map(location_mapping).where(employed, 'not_employed')
    assert work_location.notna().all()
    commute_col = col(raw, 'A8a. When you do have to commute to a place of work outside of your home, which of the following types of transport do you use? - Drive a vehicle myself')
    assert raw.loc[employed, commute_col].isin(['Yes', 'No']).all()
    bg = pd.DataFrame({'work_location': work_location,
        'EV_and_driving_commute': has_ev & raw[commute_col].eq('Yes'),
        'drive_commute_asked': employed,
        'drive_commute_yes': raw[commute_col].map({'Yes': True, 'No': False}),
        'household_type': raw[col(raw, 'A1. Which one')],
        'home_charging_frequency': raw[col(raw, 'Q210. Home')],
        'weekday_charging_time': raw[col(raw, 'Q211. Weekday at home')],
        'charging_method': raw[col(raw, 'Q213.')],
        'life_support_registration': raw[col(raw, 'Z7. I am registered as a life-support')],
        'weekdays_home_count': n_home})
    audit = {'n': len(raw), 'feature_sources': sources, 'field_counts': {c: f[c].value_counts(dropna=False).to_dict() for c in f},
        'has_EV_n': int(has_ev.sum()), 'EV_driving_commute_n': int(bg.EV_and_driving_commute.sum()),
        'conditional_posthoc_valid_n': {c: int(bg[c].notna().sum()) for c in ['work_location', 'home_charging_frequency', 'weekday_charging_time', 'charging_method']},
        'weight_effective_n_kish': float(w.sum()**2 / (w @ w)), 'core_missing_n': int(f.isna().any(axis=1).sum())}
    assert len(f) == 4507 and not f.isna().any().any()
    return f, bg, w, audit


def profiles(f, bg, post, weights, order):
    result = []
    for label, k in enumerate(order):
        ww = post[:, k] * weights
        total = ww.sum()
        row = {'class': f'H{label+1}', 'model_column': int(k), 'share_weighted_soft': float(total / weights.sum()),
            'share_unweighted_soft': float(post[:, k].mean()), 'hard_n': int((post.argmax(1) == k).sum()),
            'share_weighted_hard': float(weights[post.argmax(1) == k].sum() / weights.sum()), 'inputs': {}, 'posthoc': {}}
        for c in f:
            row['inputs'][c] = {str(v): float(ww @ f[c].eq(v).to_numpy() / total) for v in sorted(f[c].unique(), key=str)}
        for c in bg:
            valid = bg[c].notna().to_numpy()
            denominator = ww[valid].sum()
            row['posthoc'][c] = {'known_soft_n': float(denominator),
                'known_fraction_in_class': float(denominator / total),
                'distribution': {str(v): float(ww @ bg[c].eq(v).to_numpy() / denominator) for v in sorted(bg.loc[valid, c].unique(), key=str)} if denominator else {}}
        result.append(row)
    return result


def posterior_from_params(x, categories, pi, theta):
    lp = encode(x, categories) @ np.log(theta).T + np.log(pi)
    return np.exp(lp - logsumexp(lp, axis=1)[:, None])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--raw', type=Path, default=Path('/tmp/eb_external_followup_20261019/eca2026.xlsx'))
    parser.add_argument('--output', type=Path, default=ROOT)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    plan = json.loads((ROOT / 'ANALYSIS_PLAN.json').read_text())
    raw_hash = hashlib.sha256(args.raw.read_bytes()).hexdigest()
    assert raw_hash == plan['raw_sha256']
    raw = pd.read_excel(args.raw, sheet_name='RAW data (Labelled)')
    f, bg, weights, audit = prepare(raw)
    assert list(f) == plan['features']
    save(args.output / 'FIELD_AUDIT.json', audit)
    x, categories, names = numeric(f)
    m = LCA(6, categories, SEED + 610).fit(x, row_weights=weights, starts=48)
    post = m.posterior(x)
    assert np.allclose(post.sum(1), 1)
    order = np.argsort(-np.average(post, weights=weights, axis=0))
    r = {'schema': 'eb.eca.context_six.results.v1', 'n': len(f), 'k_prespecified': 6,
        'input_sha256': raw_hash, 'features': names, 'weighting': 'official survey weights, mean one',
        'fit': m.summary(x), 'parameters': {'pi': m.pi.tolist(), 'theta': m.theta.tolist(), 'categories': categories},
        'class_order_descending_weighted_share': order.tolist(), 'profiles': profiles(f, bg, post, weights, order),
        'bootstrap': [], 'sensitivity': [], 'holdout': [], 'production_changes': False, 'EP_runs': 0}
    save(args.output / 'RESULTS.partial.json', r)
    print(json.dumps({'stage': 'primary_six', 'll': m.ll, 'converged': m.converged, 'profiles': [{'class': c['class'], 'share': c['share_weighted_soft']} for c in r['profiles']]}), flush=True)
    # Independent single-class likelihood check, with frequency weights.
    closed = 0.0
    for c in f:
        cnt = np.array([weights[f[c].eq(v)].sum() for v in sorted(f[c].unique(), key=str)])
        closed += float(cnt @ np.log(cnt/cnt.sum()))
    one = LCA(1, categories, SEED + 611).fit(x, weights, starts=1)
    r['one_class_closed_form_likelihood_error'] = abs(closed - one.ll)
    assert r['one_class_closed_form_likelihood_error'] < 1e-3
    rng = np.random.default_rng(SEED + 612)
    for b in range(20):
        counts = np.bincount(rng.integers(0, len(x), len(x)), minlength=len(x))
        bw = counts * weights
        bw *= len(x)/bw.sum()
        bm = LCA(6, categories, SEED + 620 + b).fit(x, bw, starts=16)
        bp, _ = aligned(post, bm.posterior(x))
        r['bootstrap'].append({'iteration': b, 'ari': float(adjusted_rand_score(post.argmax(1), bp.argmax(1))),
            'aligned_share': np.average(bp, weights=bw, axis=0)[order].tolist(), 'converged': bm.converged})
        print(json.dumps({'stage': 'bootstrap', 'iteration': b, 'ari': r['bootstrap'][-1]['ari'], 'converged': bm.converged}), flush=True)
    r['bootstrap_summary'] = {'median_ari': float(np.median([v['ari'] for v in r['bootstrap']])),
        'min_ari': float(min(v['ari'] for v in r['bootstrap'])),
        'share_interval_2p5_97p5': np.quantile([v['aligned_share'] for v in r['bootstrap']], [.025, .975], axis=0).T.tolist()}
    save(args.output / 'RESULTS.partial.json', r)
    variants = [('unweighted', f, None, 48), ('without_EV', f.drop(columns='EV_home_charger'), weights, 24),
        ('work_location_instead_of_status', f.drop(columns='work_status').assign(work_location=bg.work_location), weights, 24),
        ('background_only', f[['health_impacts_energy_use', 'weekday_home_pattern', 'work_status', 'dependent_children', 'EV_home_charger']], weights, 24)]
    for i, (name, ff, ww, starts) in enumerate(variants):
        xx, cc, _ = numeric(ff)
        mm = LCA(6, cc, SEED + 700 + i).fit(xx, ww, starts=starts)
        pp, alignment = aligned(post, mm.posterior(xx))
        entry = {'name': name, 'features': list(ff), 'fit': mm.summary(xx),
            'ARI_with_primary': float(adjusted_rand_score(post.argmax(1), pp.argmax(1))),
            'aligned_share_using_official_weights': np.average(pp, weights=weights, axis=0)[order].tolist()}
        r['sensitivity'].append(entry)
        print(json.dumps({'stage': 'sensitivity', 'name': name, 'ari': entry['ARI_with_primary'], 'converged': mm.converged}), flush=True)
        save(args.output / 'RESULTS.partial.json', r)
    previous = json.loads((PREVIOUS / 'eca2026' / 'RESULTS.json').read_text())
    oldf = f[list(ATTITUDES)]
    oldx, oldc, _ = numeric(oldf)
    oldparams = previous['models']['6']['parameters']
    oldpost = posterior_from_params(oldx, oldc, np.array(oldparams['pi']), np.array(oldparams['theta']))
    r['ARI_with_previous_attitude_only_six'] = float(adjusted_rand_score(post.argmax(1), oldpost.argmax(1)))
    r['previous_model_overlap_weighted'] = (post[:, order].T @ (oldpost * weights[:, None]) / weights.sum()).tolist()
    for split in range(3):
        perm = np.random.default_rng(SEED + 800 + split).permutation(len(x))
        train, test = perm[:int(len(x)*.8)], perm[int(len(x)*.8):]
        entry = {'split': split, 'train_n': len(train), 'test_n': len(test), 'mean_test_loglik': {}}
        for weighted in [True, False]:
            ww = weights[train]/weights[train].mean() if weighted else None
            mm = LCA(6, categories, SEED + 810 + 2*split + int(weighted)).fit(x[train], ww, starts=12)
            ll = logsumexp(encode(x[test], categories) @ np.log(mm.theta).T + np.log(mm.pi), axis=1)
            entry['mean_test_loglik']['weighted_fit' if weighted else 'unweighted_fit'] = float(np.average(ll, weights=weights[test]))
        r['holdout'].append(entry)
    save(args.output / 'RESULTS.json', r)
    (args.output / 'RESULTS.partial.json').unlink()
    print(json.dumps({'stage': 'finished', 'bootstrap_summary': r['bootstrap_summary'], 'production_changes': False}), flush=True)


if __name__ == '__main__':
    with threadpool_limits(limits=1):
        main()
