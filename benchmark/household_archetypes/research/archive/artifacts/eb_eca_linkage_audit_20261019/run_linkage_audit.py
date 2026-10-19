"""Existing-data construct linkage, not EB classification or quota generation."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent.parent
sys.path.insert(0, str(ROOT.parent / 'eb_eca_context_six_20261019'))
from run_context_six import prepare, col, posterior_from_params
from run_validation import numeric


def save(name, value):
    (ROOT/name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--raw', type=Path, default=Path('/tmp/eb_external_followup_20261019/eca2026.xlsx'))
    rawpath = parser.parse_args().raw
    digest = hashlib.sha256(rawpath.read_bytes()).hexdigest()
    assert digest == json.loads((ROOT/'ANALYSIS_PLAN.json').read_text())['raw_sha256']
    d = pd.read_excel(rawpath, sheet_name='RAW data (Labelled)')
    f, bg, w, _ = prepare(d)
    n = len(d)
    assert n == 4507 and len(d.columns) == 369
    def eq(prefix, value):
        return d[col(d, prefix)].eq(value).astype('boolean')
    def isin(prefix, values):
        s = d[col(d, prefix)]
        return s.isin(values).astype('boolean').where(s.notna())
    def tri(s):
        return pd.Series(s, index=d.index, dtype='boolean')
    def describe(s, weights=w):
        s = tri(s)
        known = s.notna().to_numpy()
        positive = s.fillna(False).to_numpy(dtype=bool)
        return {'n_true': int(positive.sum()), 'n_false': int((known & ~positive).sum()), 'n_unobserved': int((~known).sum()),
            'n_observed': int(known.sum()), 'reference_weight_sum': float(weights.sum()),
            'known_weight_fraction': float(weights[known].sum()/weights.sum()),
            'weighted_positive_fraction_observed_only': float(weights[positive].sum()/weights.sum()),
            'weighted_positive_fraction_among_observed': float(weights[positive].sum()/weights[known].sum()) if known.any() else None}
    employed = isin('Q6b.', ['Working full time','Working part time','Working casually'])
    commute_cols = [c for c in d if c.startswith('A8a.') and '- I never commute' not in c and '.Other' not in c]
    any_commute = d[commute_cols].eq('Yes').any(axis=1)
    never_col = col(d, 'A8a. When you do have to commute to a place of work outside of your home, which of the following types of transport do you use? - I never commute')
    assert not (d[never_col].eq('Yes') & any_commute).any()
    commute = tri(any_commute & employed.fillna(False))
    drive_col = col(d, 'A8a. When you do have to commute to a place of work outside of your home, which of the following types of transport do you use? - Drive a vehicle myself')
    self_drive = tri(d[drive_col].eq('Yes') & employed.fillna(False))
    self_home = tri(d[[c for c in d if c.startswith('A3.') and any(day in c for day in ['Monday','Tuesday','Wednesday','Thursday','Friday']) and '- You are' in c]].eq('Yes').all(axis=1))
    home = tri(f.weekday_home_pattern.eq('home_all5'))
    high_cost = isin('Q11. The cost of electricity', ['Extremely concerned','Quite concerned'])
    active = eq('Q16.', 'ACTIVE RELATIONSHIP (BASIC +)')
    interested = isin('Q58.', ['Very interested','Somewhat interested','Already a member of a virtual power plant'])
    uninterested = isin('Q58.', ['Not very interested','Not at all interested'])
    member = eq('Q58.', 'Already a member of a virtual power plant')
    automation = isin('Q51a. A home automation system', ['You already have this','You’re currently researching options for buying this technology','You’re considering buying this technology but are not actively researching it'])
    solar = eq('Q51a. Rooftop solar', 'You already have this')
    battery = eq('Q51a. A home battery', 'You already have this')
    q59cols = [c for c in d if c.startswith('Q59.') and c != 'Q59.Other']
    q59expected = battery & ~member
    q59known = d[q59cols].notna().all(axis=1)
    assert np.array_equal(q59expected.to_numpy(dtype=bool), q59known.to_numpy())
    assert d[q59cols].notna().sum(axis=1).isin([0,len(q59cols)]).all()
    distrust = isin('Q59. Which of the following, if any, are reasons why you haven’t joined a virtual power plant? - You don’t trust', ['Yes'])
    control = isin('Q59. Which of the following, if any, are reasons why you haven’t joined a virtual power plant? - You are concerned about losing control', ['Yes'])
    cautious = distrust | control
    q79cols = [c for c in d if c.startswith('Q79a.')]
    q79expected = isin('Q75. What type', ['Time-of-use tariff (different rates for different times of day)', 'Demand tariff (charges are based on the highest amount of energy you use during a single hour in the entire month)']) | solar
    q79known = d[q79cols].notna().all(axis=1)
    assert np.array_equal(q79expected.to_numpy(dtype=bool), q79known.to_numpy())
    assert d[q79cols].notna().sum(axis=1).isin([0,len(q79cols)]).all()
    relevant = d[q79cols].isin(['Regularly','Sometimes','Rarely','Never']).any(axis=1)
    shift = tri(d[q79cols].isin(['Regularly','Sometimes']).any(axis=1)).where(q79known & relevant)
    health = eq('Z7. I or someone I live with has a health condition', 'Yes')
    child = tri(f.dependent_children.eq('under18_present'))
    # Exact labels exclude non-plugin hybrids; never use substring "plugin".
    actual_main_ev_labels = ['A fully electric vehicle', 'Plugin hybrid vehicle (PHEV - that can be plugged in to an external power source for charging)']
    assert set(actual_main_ev_labels).issubset(set(d[col(d,'Q208.')].dropna()))
    main_ev = isin('Q208.', actual_main_ev_labels).fillna(False)
    home_charge = isin('Q210. Home', ['Daily','A few times a week','About once a week','Less often'])
    q213 = d[col(d,'Q213.')]
    assert np.array_equal((main_ev & home_charge.fillna(False)).to_numpy(dtype=bool), q213.notna().to_numpy())
    optimized_labels = ['Charge it at specific times to minimise the cost', 'Use smart home energy system to automatically manage charging',
        'Use in-car settings or companion app to schedule charging (e.g. Tesla app)', 'Allow a third party (such as retailer or network operator) to manage charging in exchange for bill savings']
    optimized = tri(q213.isin(optimized_labels)).where(q213.notna())
    patterns = {'A_related_observed_combination': high_cost & commute & shift,
        'B_related_observed_combination': self_home & ~eq('Q35. Avoided heating or cooling', 'Yes') & uninterested,
        'C_control_caution_only_not_complete_role': cautious,
        'D_related_observed_combination': active & interested & automation,
        'E_related_observed_combination': (child | health) & home & uninterested,
        'F_related_observed_combination': main_ev & self_drive & optimized}
    audit = {'n': n, 'raw_sha256': digest, 'scope': 'construct linkage only; no role labels or quotas',
        'newly_examined_fields': {'Q16': col(d,'Q16.'), 'Q59': q59cols, 'Q79':q79cols, 'Q213': col(d,'Q213.')},
        'routing': {'Q59_battery_nonmember': int(q59known.sum()), 'Q79_tou_demand_or_solar': int(q79known.sum()), 'Q213_actual_main_EV_home_chargers': int(q213.notna().sum())},
        'direct_dimensions': {k: describe(s) for k,s in {'cost_concern':high_cost,'employment_commute_any_mode':commute,'active_energy_relationship':active,
            'VPP_interested_or_member': interested,'home_automation_own_or_intent':automation,'actual_cost_shift_any_appliance':shift,
            'battery_management_distrust':distrust,'battery_control_loss_concern':control,'either_battery_control_concern':cautious,
            'main_EV_or_PHEV_driver':main_ev,'main_EV_and_work_drive':main_ev & self_drive,'actual_cost_or_scheduled_home_charging':optimized}.items()},
        'patterns_not_role_prevalences': {k: describe(s) for k,s in patterns.items()},
        'conditional_tables': {}, 'pairwise_pattern_overlap_raw_n': {}, 'all_previous_ECA_clusters': [],
        'production_changes': False, 'EP_runs':0}
    for name,s in [('under18',child),('health_energy_need',health),('home_all5',home)]:
        table = {}
        for v in [False,True]:
            ix = s.fillna(False).eq(v).to_numpy()
            table[str(v)] = {'n':int(ix.sum()), 'VPP_interest_weighted_fraction':float(w[ix] @ interested.to_numpy(dtype=float)[ix]/w[ix].sum())}
        audit['conditional_tables'][name] = table
    for a in patterns:
        for b in patterns:
            if a < b:
                audit['pairwise_pattern_overlap_raw_n'][a+' & '+b] = int((patterns[a].fillna(False) & patterns[b].fillna(False)).sum())
    prior = json.loads((ROOT.parent/'eb_eca_context_six_20261019/RESULTS.json').read_text())
    x,cats,_ = numeric(f)
    post = posterior_from_params(x,cats,np.array(prior['parameters']['pi']),np.array(prior['parameters']['theta']))
    for label,k in enumerate(prior['class_order_descending_weighted_share']):
        ww = w*post[:,k]
        audit['all_previous_ECA_clusters'].append({'class':f'H{label+1}','share':float(ww.sum()/w.sum()),
            'related_patterns':{name:{kk:vv for kk,vv in describe(s,ww).items() if not kk.startswith('n_')} for name,s in patterns.items()}})
    save('RESULTS.json',audit)
    save('FIELD_INVENTORY.json', {'columns':list(d.columns),'patterns_and_native_categories':{c:{str(k):int(v) for k,v in d[c].value_counts(dropna=False).items()} for c in [col(d,'Q16.'),col(d,'Q58.'),*q59cols,*q79cols,col(d,'Q208.'),col(d,'Q213.')]}})
    print(json.dumps({'routing':audit['routing'],'direct_dimensions':audit['direct_dimensions'],'patterns':audit['patterns_not_role_prevalences'], 'overlap':{k:v for k,v in audit['pairwise_pattern_overlap_raw_n'].items() if v}},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
