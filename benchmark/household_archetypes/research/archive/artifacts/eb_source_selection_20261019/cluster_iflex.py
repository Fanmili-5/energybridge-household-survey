"""Research-only categorical clustering of the open iFlex household survey.

Run with the studytest Python environment; see ANALYSIS_PLAN.json for scope.
Raw records and individual assignments are deliberately not exported.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from scipy.special import logsumexp
from sklearn.metrics import adjusted_rand_score
from threadpoolctl import threadpool_limits

SEED = 20261019
MOTIVES = [f"Q13_{i}" for i in range(1, 9)]
FEATURES = MOTIVES + ["Q16"]
RANGES = [[0, 1]] * 8 + [list(range(1, 10))]
LABELS = ["费用", "易手动", "省心自动", "不损舒适", "技术尝试", "环境", "电网与网费", "共同参与"]


def encode(x, categories):
    return np.concatenate([(x[:, j, None] == np.array(c)).astype(float)
                           for j, c in enumerate(categories)], axis=1)


def compress(x, row_weights=None):
    u, inv = np.unique(x, axis=0, return_inverse=True)
    return u, np.bincount(inv, weights=row_weights), inv


class LCA:
    def __init__(self, k, categories, seed=SEED):
        self.k, self.categories, self.seed = k, categories, seed
        self.slices = []
        offset = 0
        for c in categories:
            self.slices.append(slice(offset, offset + len(c)))
            offset += len(c)

    def fit(self, x, row_weights=None, starts=16):
        u, counts, _ = compress(x, row_weights)
        keep = counts > 0
        u, counts = u[keep], counts[keep]
        z = encode(u, self.categories)
        n = float(counts.sum())
        rng = np.random.default_rng(self.seed)
        best = None
        self.start_results = []
        for _ in range(starts):
            centers = z[rng.choice(len(u), self.k, replace=len(u) < self.k,
                                   p=counts / n)]
            marginal = counts @ z / n
            theta = .65 * centers + .35 * marginal[None, :]
            theta = np.maximum(theta + rng.uniform(0, .03, theta.shape), 1e-6)
            for s in self.slices:
                theta[:, s] /= theta[:, s].sum(axis=1, keepdims=True)
            pi = np.full(self.k, 1 / self.k)
            previous = -np.inf
            converged = False
            for it in range(1200):
                lp = z @ np.log(theta).T + np.log(pi)
                den = logsumexp(lp, axis=1)
                ll = float(counts @ den)
                if np.isfinite(previous) and abs(ll - previous) / n < 1e-8:
                    converged = True
                    break
                resp = np.exp(lp - den[:, None]) * counts[:, None]
                nk = resp.sum(axis=0)
                pi = np.maximum(nk / n, 1e-6)
                pi /= pi.sum()
                theta = resp.T @ z
                for s in self.slices:
                    v = theta[:, s] + 1e-6
                    v /= v.sum(axis=1, keepdims=True)
                    v = np.maximum(v, 1e-6)
                    theta[:, s] = v / v.sum(axis=1, keepdims=True)
                previous = ll
            # Recompute the objective at the stored final parameters.
            ll = float(counts @ logsumexp(z @ np.log(theta).T + np.log(pi), axis=1))
            self.start_results.append({"ll": ll, "iterations": it + 1,
                                       "converged": converged})
            if best is None or ll > best[0]:
                best = ll, pi.copy(), theta.copy(), it + 1, converged
        self.ll, self.pi, self.theta, self.iterations, self.converged = best
        self.n = n
        self.parameters = self.k - 1 + self.k * sum(len(c) - 1 for c in self.categories)
        self.bic = -2 * self.ll + self.parameters * np.log(n)
        return self

    def posterior(self, x):
        lp = encode(x, self.categories) @ np.log(self.theta).T + np.log(self.pi)
        return np.exp(lp - logsumexp(lp, axis=1)[:, None])

    def summary(self, x):
        r = self.posterior(x)
        return {"k": self.k, "n": len(x), "ll": self.ll,
                "parameters": self.parameters, "bic": self.bic,
                "aic": -2 * self.ll + 2 * self.parameters,
                "soft_share": r.mean(axis=0).tolist(),
                "hard_n": np.bincount(r.argmax(axis=1), minlength=self.k).tolist(),
                "mean_max_posterior": float(r.max(axis=1).mean()),
                "normalized_entropy": None if self.k == 1 else float(
                    1 + (r * np.log(np.maximum(r, 1e-15))).sum() / (len(x) * np.log(self.k))),
                "best_start_converged": self.converged,
                "best_start_iterations": self.iterations,
                "starts_within_1_loglik": sum(v["ll"] >= self.ll - 1 for v in self.start_results),
                "starts": self.start_results}


def aligned(reference, alternative):
    rows, cols = linear_sum_assignment(-(reference.T @ alternative))
    cols = cols[np.argsort(rows)]
    return alternative[:, cols], cols


def profiles(d, posterior):
    result = []
    for c in range(posterior.shape[1]):
        w = posterior[:, c]
        total = w.sum()
        def rate(col, test, valid_codes=None):
            vals = pd.to_numeric(d[col], errors="coerce").to_numpy()
            valid = np.isfinite(vals)
            if valid_codes is not None:
                valid &= np.isin(vals, valid_codes)
            return {"rate": float(w[valid] @ test(vals[valid]) / w[valid].sum())
                    if w[valid].sum() else None,
                    "known_soft_n": float(w[valid].sum())}
        entry = {"cluster": c + 1, "soft_n": float(total),
                 "soft_share": float(total / len(d)),
                 "hard_n": int((posterior.argmax(axis=1) == c).sum()),
                 "motivation_probabilities": {name: float(w @ d[col].to_numpy() / total)
                                               for name, col in zip(LABELS, MOTIVES)},
                 "mean_number_selected": float(w @ d[MOTIVES].sum(axis=1).to_numpy() / total),
                 "Q16_investment_savings_response": {
                     str(v): float(w @ d.Q16.eq(v).to_numpy() / total) for v in range(1, 10)},
                 "daytime_5_of_5": rate("Q19", lambda a: a == 6, valid_codes=[1, 2, 3, 4, 5, 6]),
                 "home_charged_ev": rate("Q29", lambda a: a == 1),
                 "automatic_ev_control_among_answered": rate("Q31", lambda a: np.isin(a, [3, 4])),
                 "Q7_self_reported_response_codes": {
                     str(v): float(w @ d.Q7.eq(v).to_numpy() / total)
                     for v in sorted(d.Q7.dropna().unique())}}
        result.append(entry)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    raw_path = args.raw_dir / "iflex2022_answers.csv"
    household_path = args.raw_dir / "iflex2022_households.csv"
    d = pd.read_csv(raw_path)
    h = pd.read_csv(household_path)
    assert d.ID.is_unique and h.ID.is_unique
    assert set(d.ID) == set(h.ID)
    for col, allowed in zip(FEATURES, RANGES):
        assert d[col].isin(allowed).all(), (col, d[col].unique())
    joined = d.merge(h, on="ID", validate="one_to_one")
    selected = d[MOTIVES].sum(axis=1) > 0
    main_d = joined.loc[selected].reset_index(drop=True)
    x = main_d[FEATURES].to_numpy(dtype=int)
    report = {"schema": "eb.source_clustering.research.v1",
              "source": "https://zenodo.org/records/8423312",
              "seed": SEED, "n_all": len(d), "n_preference_sample": len(main_d),
              "not_classified_as_preferences": {
                  "n": int((~selected).sum()),
                  "explicit_none_or_cannot": int(d.Q13_10.sum()),
                  "dont_know": int(d.Q13_11.sum()),
                  "other_or_no_named_reason": int(((~selected) & d.Q13_10.eq(0) & d.Q13_11.eq(0)).sum())},
              "production_changed": False, "survey_weights": "not supplied; no population estimates",
              "features": FEATURES,
              "input_hashes": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in [raw_path, household_path, args.raw_dir / "iflex2022_survey.csv"]},
              "environment": {"python": platform.python_version(), **{
                  name: importlib.metadata.version(name) for name in ["numpy", "pandas", "scipy", "scikit-learn"]}}}
    models = {}
    selection = []
    for k in range(1, 9):
        model = LCA(k, RANGES, SEED + k).fit(x)
        models[k] = model
        s = model.summary(x)
        selection.append(s)
        print(json.dumps({"stage": "fit", **{key: s[key] for key in ["k", "bic", "mean_max_posterior", "starts_within_1_loglik", "best_start_converged"]}}), flush=True)
    report["model_selection"] = selection
    report["bic_best_k"] = min(selection, key=lambda a: a["bic"])["k"]
    six = models[6]
    ref = six.posterior(x)
    report["six_class_profiles"] = profiles(main_d, ref)
    report["six_class_parameters"] = {"pi": six.pi.tolist(), "theta": six.theta.tolist(), "categories": RANGES}
    rng = np.random.default_rng(SEED)
    boot = []
    for i in range(20):
        weights = np.bincount(rng.integers(0, len(x), len(x)), minlength=len(x))
        m = LCA(6, RANGES, SEED + 1000 + i).fit(x, weights, starts=6)
        resp, _ = aligned(ref, m.posterior(x))
        b = {"iteration": i, "ari": float(adjusted_rand_score(ref.argmax(1), resp.argmax(1))),
             "share": np.average(resp, weights=weights, axis=0).tolist(),
             "converged": m.converged}
        boot.append(b)
        print(json.dumps({"stage": "bootstrap", "iteration": i, "ari": b["ari"]}), flush=True)
    report["bootstrap"] = boot
    shares = np.array([b["share"] for b in boot])
    report["bootstrap_summary"] = {"median_ari": float(np.median([b["ari"] for b in boot])),
                                   "min_ari": float(min(b["ari"] for b in boot)),
                                   "share_intervals_2p5_97p5": np.quantile(shares, [.025, .975], axis=0).T.tolist()}
    loo = []
    for region in sorted(main_d.Region.unique()):
        train = main_d.Region.ne(region).to_numpy()
        m = LCA(6, RANGES, SEED + 2000 + len(loo)).fit(x[train], starts=8)
        resp, _ = aligned(ref, m.posterior(x))
        loo.append({"region_left_out": region, "train_n": int(train.sum()),
                    "ari_on_all": float(adjusted_rand_score(ref.argmax(1), resp.argmax(1))),
                    "share_on_all": resp.mean(0).tolist(), "converged": m.converged})
        print(json.dumps({"stage": "leave_region_out", **loo[-1]}), flush=True)
    report["leave_region_out"] = loo
    scenarios = []
    for name, indices in [("no_investment_question", list(range(8))),
                           ("four_core_motives_and_investment", [0, 1, 2, 3, 8])]:
        m = LCA(6, [RANGES[j] for j in indices], SEED + 3000 + len(scenarios)).fit(x[:, indices])
        resp, _ = aligned(ref, m.posterior(x[:, indices]))
        scenarios.append({"name": name, "ari": float(adjusted_rand_score(ref.argmax(1), resp.argmax(1))),
                          "share": resp.mean(0).tolist(), "converged": m.converged})
    all_x = joined[FEATURES].to_numpy(dtype=int)
    all_m = LCA(6, RANGES, SEED + 4000).fit(all_x)
    all_resp = all_m.posterior(all_x)
    a_resp, order = aligned(ref, all_resp[selected.to_numpy()])
    scenarios.append({"name": "include_all_4446", "ari_on_named_motivation_sample": float(
        adjusted_rand_score(ref.argmax(1), a_resp.argmax(1))),
        "share_on_all": all_resp[:, order].mean(0).tolist(), "converged": all_m.converged})
    report["sensitivity"] = scenarios
    regional = {str(region): ref[main_d.Region.eq(region)].mean(0).tolist()
                for region in sorted(main_d.Region.unique())}
    report["region_profiles_fixed_model"] = regional
    report["equal_region_scenario_share_not_population_weight"] = np.mean(list(regional.values()), axis=0).tolist()
    report["max_regional_equalization_change_percentage_points"] = float(100 * np.max(np.abs(
        np.mean(list(regional.values()), axis=0) - ref.mean(0))))
    pd.DataFrame([{key: a[key] for key in ["k", "n", "ll", "parameters", "bic", "aic", "mean_max_posterior", "normalized_entropy", "best_start_converged", "best_start_iterations", "starts_within_1_loglik"]}
                  for a in selection]).to_csv(args.output / "MODEL_SELECTION.csv", index=False)
    (args.output / "CLUSTER_RESULTS.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({"stage": "complete", "bic_best_k": report["bic_best_k"],
                      "bootstrap": report["bootstrap_summary"], "output": str(args.output)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    with threadpool_limits(limits=1):
        main()
