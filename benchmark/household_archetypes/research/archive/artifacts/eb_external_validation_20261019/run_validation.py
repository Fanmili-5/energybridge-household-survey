"""Independent research only; never imports or writes the production generator."""
from __future__ import annotations
import hashlib
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from scipy.special import logsumexp
from sklearn.metrics import adjusted_rand_score
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parent
RAW = Path(os.environ.get('EB_COARSE_RAW_DIR', '/tmp/eb_external_followup_20261019'))
SEED = 20261019
SPEC = importlib.util.spec_from_file_location('iflex_lca', ROOT.parent / 'eb_source_selection_20261019' / 'cluster_iflex.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
aligned, encode = MODULE.aligned, MODULE.encode


class LCA(MODULE.LCA):
    def fit(self, x, row_weights=None, starts=24):
        super().fit(x, row_weights, starts)
        self.refinement = None
        if self.converged:
            return self
        # Continue the best initialization if the shared solver's 1200-step
        # budget was exhausted. Preserve the objective, tolerance and floor.
        u, counts, _ = MODULE.compress(x, row_weights)
        keep = counts > 0
        z, counts = encode(u[keep], self.categories), counts[keep]
        pi, theta = self.pi.copy(), self.theta.copy()
        initial_ll, previous = self.ll, -np.inf
        converged = False
        for it in range(20000):
            lp = z @ np.log(theta).T + np.log(pi)
            den = logsumexp(lp, axis=1)
            ll = float(counts @ den)
            if np.isfinite(previous) and abs(ll - previous) / self.n < 1e-8:
                converged = True
                break
            resp = np.exp(lp - den[:, None]) * counts[:, None]
            pi = np.maximum(resp.sum(0) / self.n, 1e-6)
            pi /= pi.sum()
            theta = resp.T @ z
            for s in self.slices:
                v = theta[:, s] + 1e-6
                v /= v.sum(axis=1, keepdims=True)
                v = np.maximum(v, 1e-6)
                theta[:, s] = v / v.sum(axis=1, keepdims=True)
            previous = ll
        self.pi, self.theta = pi, theta
        self.ll = float(counts @ logsumexp(z @ np.log(theta).T + np.log(pi), axis=1))
        self.converged = converged
        self.iterations += it + 1
        self.bic = -2 * self.ll + self.parameters * np.log(self.n)
        self.refinement = {'initial_ll': initial_ll, 'final_ll': self.ll,
                           'additional_iterations': it + 1, 'converged': converged}
        return self

    def summary(self, x):
        return {**super().summary(x), 'best_start_continuation': self.refinement}


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def numeric(d):
    codes, names = [], {}
    for c in d.columns:
        values = sorted(d[c].unique().tolist(), key=str)
        names[c] = values
        codes.append(pd.Categorical(d[c], categories=values).codes)
    return np.array(codes).T, [list(range(len(v))) for v in names.values()], names


def profile(d, r, background):
    result = []
    for k in range(r.shape[1]):
        w = r[:, k]
        row = {'class': k + 1, 'share': float(w.mean()), 'hard_n': int((r.argmax(1) == k).sum()), 'responses': {}}
        for c in d:
            row['responses'][c] = {str(v): float(w @ d[c].eq(v).to_numpy() / w.sum()) for v in sorted(d[c].unique(), key=str)}
        row['background_not_used_in_fit'] = {}
        for c in background:
            known = background[c].notna().to_numpy()
            total = w[known].sum()
            row['background_not_used_in_fit'][c] = {
                'known_soft_n': float(total),
                'distribution': {str(v): float(w @ background[c].eq(v).to_numpy() / total) for v in sorted(background.loc[known, c].unique(), key=str)} if total else {}}
        result.append(row)
    return result


def fit_source(name, d, background, input_paths, groups=None):
    out = ROOT / name
    out.mkdir(exist_ok=True)
    assert not d.isna().any().any()
    x, categories, names = numeric(d)
    report = {'source': name, 'n': len(d), 'features': names,
              'input_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in input_paths},
              'model_selection': [], 'models': {}, 'production_changes': False}
    fitted = {}
    for k in range(1, 9):
        m = LCA(k, categories, SEED + k).fit(x, starts=24)
        fitted[k] = m
        s = m.summary(x)
        report['model_selection'].append(s)
        print(json.dumps({'source': name, 'stage': 'selection', 'k': k, 'bic': m.bic, 'converged': m.converged}), flush=True)
        save(out / 'RESULTS.partial.json', report)
    selected = min(fitted, key=lambda k: fitted[k].bic)
    report['selected_k'] = selected
    # A one-class multinomial has a closed-form likelihood.
    direct_ll = 0.0
    for c in d:
        counts = d[c].value_counts().to_numpy()
        direct_ll += float(counts @ np.log(counts / len(d)))
    report['independent_one_class_likelihood_error'] = float(abs(direct_ll - fitted[1].ll))
    assert report['independent_one_class_likelihood_error'] < 1e-3
    rng = np.random.default_rng(SEED + 100)
    for k in sorted({selected, 6}):
        m = fitted[k]
        ref = m.posterior(x)
        assert np.allclose(ref.sum(1), 1)
        assert np.isclose(m.pi.sum(), 1)
        entry = {'summary': m.summary(x), 'profiles': profile(d, ref, background),
                 'parameters': {'pi': m.pi.tolist(), 'theta': m.theta.tolist(), 'categories': categories}, 'bootstrap': []}
        for b in range(20):
            if groups is None:
                idx = rng.integers(0, len(d), len(d))
            else:
                idx = np.concatenate([rng.choice(np.flatnonzero(groups == g), size=int((groups == g).sum()), replace=True) for g in sorted(set(groups))])
            weights = np.bincount(idx, minlength=len(d))
            bm = LCA(k, categories, SEED + 1000 * k + b).fit(x, weights, starts=10)
            post, _ = aligned(ref, bm.posterior(x))
            entry['bootstrap'].append({'iteration': b, 'ari': float(adjusted_rand_score(ref.argmax(1), post.argmax(1))),
                                       'share': np.average(post, weights=weights, axis=0).tolist(), 'converged': bm.converged})
        entry['bootstrap_summary'] = {'median_ari': float(np.median([v['ari'] for v in entry['bootstrap']])),
                                      'min_ari': float(min(v['ari'] for v in entry['bootstrap'])),
                                      'share_interval_2p5_97p5': np.quantile([v['share'] for v in entry['bootstrap']], [.025, .975], axis=0).T.tolist()}
        report['models'][str(k)] = entry
        print(json.dumps({'source': name, 'stage': 'bootstrap', 'k': k, **entry['bootstrap_summary']}), flush=True)
        save(out / 'RESULTS.partial.json', report)
    report['held_out'] = []
    for split in range(3):
        order = np.random.default_rng(SEED + 3000 + split).permutation(len(d))
        train, test = order[:int(len(d) * .8)], order[int(len(d) * .8):]
        row = {'split': split, 'train_n': len(train), 'test_n': len(test), 'mean_test_loglik': {}}
        for k in sorted({selected, 6}):
            m = LCA(k, categories, SEED + 4000 + 10 * split + k).fit(x[train], starts=12)
            ll = logsumexp(encode(x[test], categories) @ np.log(m.theta).T + np.log(m.pi), axis=1)
            row['mean_test_loglik'][str(k)] = float(ll.mean())
        report['held_out'].append(row)
    save(out / 'RESULTS.json', report)
    pd.DataFrame([{c: row[c] for c in ['k', 'n', 'll', 'parameters', 'bic', 'aic', 'mean_max_posterior', 'best_start_converged']} for row in report['model_selection']]).to_csv(out / 'MODEL_SELECTION.csv', index=False)
    (out / 'RESULTS.partial.json').unlink()
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', choices=['both', 'iflex2020', 'dutch2025'], default='both')
    args = parser.parse_args()
    plan = json.loads((ROOT / 'ANALYSIS_PLAN.json').read_text())
    # No changes to production. Only the independently collected survey is read.
    a = pd.read_csv(RAW / 'survey1_answers.csv')
    b = pd.read_csv(RAW / 'survey2_answers.csv')
    assert a.ID.is_unique and b.ID.is_unique
    joined = b.merge(a, on='ID', suffixes=('', '_baseline'), validate='one_to_one')
    assert len(joined) == len(b) == 800
    columns = plan['sources']['iflex2020']['features']
    d = joined[columns].copy()
    for c in ['Aq3_1', 'Aq3_2', 'Aq3_4', 'Aq3_7']:
        assert d[c].notna().all()
        d[c] = d[c].ne('-').astype(int)
    bg = pd.DataFrame({'daytime_home': joined.q23, 'EV_ownership': joined.q16_bil_b,
                       'under6_present': (joined['q20.1'] + joined['q20.2'] > 0).astype(int),
                       'heating_control': joined.q13})
    if args.source in ['both', 'iflex2020']:
        fit_source('iflex2020', d, bg, [RAW / f'survey{w}_{kind}.csv' for w in [1, 2] for kind in ['answers', 'questions']])
    if args.source == 'iflex2020':
        return
    sys.path.insert(0, str(RAW / 'pydeps'))
    import pyreadstat
    raw, meta = pyreadstat.read_sav(RAW / 'dutch.sav')
    parts, exclusion = [], {}
    active = np.zeros(len(raw), dtype=int)
    for group, cols in plan['sources']['dutch2025']['branch_columns'].items():
        valid = raw[cols].notna().all(axis=1)
        active += valid.to_numpy()
        p = raw.loc[valid, cols].copy()
        p.columns = plan['sources']['dutch2025']['features']
        p['branch'] = group
        p['row'] = p.index
        parts.append(p)
        exclusion[group] = {'valid_four_core': len(p)}
    assert active.max() == 1, 'Do not count multiple branches of one respondent as independent people.'
    combined = pd.concat(parts).sort_values('row').reset_index(drop=True)
    idx = combined.row.to_numpy()
    background = pd.DataFrame({'appliance_branch': combined.branch, 'EV_ownership_code': raw.loc[idx, 'Q18'].to_numpy(),
                               'HEMS_ownership_code': raw.loc[idx, 'Q15'].to_numpy(),
                               'children_reported': raw.loc[idx, ['Q8_2', 'Q8_3']].eq(1).any(axis=1).astype(int).to_numpy()})
    exclusion.update({'all_rows': len(raw), 'included': len(combined), 'excluded_missing_core': len(raw) - len(combined),
                      'columns': plan['sources']['dutch2025']['branch_columns'], 'license': 'CC BY-SA 4.0'})
    save(ROOT / 'DUTCH_SAMPLE_AUDIT.json', exclusion)
    fit_source('dutch2025', combined[plan['sources']['dutch2025']['features']], background,
               [RAW / 'dutch.sav', RAW / 'dutch_dictionary.docx'], combined.branch.to_numpy())


if __name__ == '__main__':
    with threadpool_limits(limits=1):
        main()
