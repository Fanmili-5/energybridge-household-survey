#!/usr/bin/env python3
"""Generate anonymous modeled family/housing candidates, not actor answers.

Source household/person identifiers exist only in private process memory.
Coarsened conditional references generate NEW values; no donor is assigned.
Population slots are immutable. Housing/layout feasibility never resamples family.
"""
import argparse
import collections
import copy
import hashlib
import json
import math
import random
import shutil
import sys
from pathlib import Path

import numpy as np
import scipy
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BRIDGE = ROOT / 'chfs_census_bridge_20261003'
sys.path.insert(0, str(BRIDGE))
import run_bridge as rb
from bridge_rules import LEVEL, integer

VERSION = 'FAMILY_HOUSING_GENERATOR_20261003_V1'
REFERENCE_DATE = '2020-11-01'
AREA_EDGES = [1, 20, 40, 60, 80, 100, 120, 160, 200, 250, 350, 500, 750, 1000, 1500, 2000]
AGE_MAX = 105


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def stage_rng(seed, purpose):
    return random.Random(int(hashlib.sha256(f'{seed}|{purpose}'.encode()).hexdigest(), 16))


def weighted_choice(rng, values, weights):
    total = sum(weights)
    if not values or not math.isfinite(total) or total <= 0:
        raise ValueError('empty_or_invalid_aggregate_reference')
    u = rng.random() * total
    for v, w in zip(values, weights):
        u -= w
        if u <= 0:
            return v
    return values[-1]


def round_counts(total, weights, rng):
    """Fixed-total largest remainders, seeded ties. Each cell floor/ceil."""
    if not total:
        return [0] * len(weights)
    norm = sum(weights)
    if norm <= 0:
        raise ValueError('invalid_integer_target')
    expected = [total * v / norm for v in weights]
    result = [math.floor(x) for x in expected]
    order = sorted(range(len(weights)), key=lambda i: (-(expected[i] - result[i]), rng.random()))
    for i in order[:total - sum(result)]:
        result[i] += 1
    return result


def reference_summary(records, route):
    ws = [float(r['weight']) for r in records]
    total = sum(ws)
    return {'route': route, 'source_records': len(records),
            'kish_effective_sample_size': total * total / sum(w * w for w in ws) if ws else 0,
            'maximum_weight_share': max(ws) / total if ws else 0,
            'source_visit_years': sorted({int(r['visit_year']) for r in records}),
            'no_donor_selected': True}


def load_references():
    """Read authorized local files; no original identifiers/values are saved."""
    frame = rb.load_bridge_pool()
    records = frame[frame.member_finance_pool].to_dict('records')
    persons = rb.read('ind', ['hhid', 'a2000c', 'a2001', 'a2003', 'a2005'])
    members = {h: g.drop(columns=['hhid']).to_dict('records') for h, g in persons.groupby('hhid')}
    for r in records:
        co = [p for p in members[r['_local_hhid']] if integer(p['a2000c']) in [1, 2]]
        levels = [LEVEL[integer(p['a2001'])] for p in co]
        low = min(levels)
        counts = collections.Counter(z - low for z in levels)
        occupied = sorted(counts)
        # Only generation occupancy/count pattern and coarse eldest age enter.
        r['_pattern'] = (tuple(occupied), tuple(counts[z] for z in occupied))
        oldest = max(int(r['visit_year']) - integer(p['a2005']) for p in co)
        r['_oldest_age_bin'] = min(AGE_MAX // 5, max(0, oldest // 5))
        r['_male_count'] = sum(integer(p['a2003']) == 1 for p in co)
        r['_sex_known_count'] = sum(integer(p['a2003']) in [1, 2] for p in co)
        r['_has_couple_reference'] = {1, 2} <= {integer(p['a2001']) for p in co}
    return records


def select_pool(records, province, size, generation, need='member', room=None):
    def admitted(r):
        if need == 'member':
            return True
        if need == 'joint':
            return bool(r['area_scope_supported']) and integer(r['room_count_h7_proxy']) is not None
        return bool(r['area_scope_supported']) and isinstance(r['area_candidate_m2'], (int, float)) and math.isfinite(r['area_candidate_m2'])
    pools = [
        ('same_province_size_generation_time_aligned', lambda r: r['province'] == province and r['size_category'] == size and r['generation_category'] == generation and r['member_housing_same_reference_time']),
        ('same_province_size_generation_mixed_time', lambda r: r['province'] == province and r['size_category'] == size and r['generation_category'] == generation),
        ('nationwide_size_generation_time_aligned_transport', lambda r: r['size_category'] == size and r['generation_category'] == generation and r['member_housing_same_reference_time']),
        ('nationwide_size_generation_mixed_time_transport', lambda r: r['size_category'] == size and r['generation_category'] == generation),
        ('nationwide_generation_transport', lambda r: r['generation_category'] == generation),
        ('nationwide_city_transport', lambda r: True)]
    if room is not None:
        for route, test in pools:
            pool = [r for r in records if admitted(r) and test(r) and r['room_proxy_category'] == room]
            if pool:
                return pool, route + '_same_room_proxy_bin'
    for route, test in pools:
        pool = [r for r in records if admitted(r) and test(r)]
        if pool:
            return pool, route + ('_room_condition_relaxed_declared' if room is not None else '')
    return [], 'explicit_design_no_admitted_source'


def h5_assign(slots, authority, mode, rng):
    dp = authority['modeled_population_completion']
    ordinary = {r['province']: r for r in authority['complete_province_generation_room_counts']}
    groups = collections.defaultdict(list)
    for i, s in enumerate(slots):
        groups[(s['province'], s['generation_category'])].append(i)
    expected = {}
    probs = {}
    for key, ids in groups.items():
        p, gg = key
        g = 4 if gg == '5+' else int(gg) - 1
        pi = dp['province_order'].index(p)
        A = authority['tables']['A0109a']['rows'][p]['counts_or_aggregates'][1 + 2 * g]
        O = ordinary[p]['generation_totals'][g]
        E = dp['eligible_province_generation_counts'][pi][g]
        lower, upper = (max(0, O - (A - E)) / E, min(O, E) / E) if g == 0 else (O / A, O / A)
        prob = lower if mode == 'lower_ordinary' else upper if mode == 'upper_ordinary' else O / A
        probs[key] = {'p_ordinary': prob, 'feasible_probability_bounds': [lower, upper]}
        expected[key] = len(ids) * prob
    ordinary_total = int(math.floor(sum(expected.values()) + .5))
    counts = {key: math.floor(v) for key, v in expected.items()}
    order = sorted(groups, key=lambda k: (-(expected[k] - counts[k]), rng.random()))
    for key in order[:ordinary_total - sum(counts.values())]:
        counts[key] += 1
    assigned = {}
    targets = []
    for key, ids in groups.items():
        shuffled = list(ids)
        rng.shuffle(shuffled)
        yes = set(shuffled[:counts[key]])
        for i in ids:
            assigned[i] = i in yes
        targets.append({'province': key[0], 'generation_category': key[1], 'slots': len(ids),
                        **probs[key], 'ordinary_expected': expected[key], 'ordinary_assigned': counts[key],
                        'integer_residual': counts[key] - expected[key]})
    return assigned, targets


def fit_transport(row_totals, col_totals, probabilities):
    """IPF + absolute-deviation MILP preserves fixed size and H7 margins."""
    q = np.array(probabilities, float)
    q[:, np.array(col_totals) == 0] = 0
    x = q * np.array(row_totals)[:, None]
    rt, ct = np.array(row_totals), np.array(col_totals)
    for _ in range(10000):
        sums = x.sum(1)
        x *= np.divide(rt, sums, out=np.zeros_like(sums), where=sums > 0)[:, None]
        sums = x.sum(0)
        x *= np.divide(ct, sums, out=np.zeros_like(sums), where=sums > 0)[None, :]
        if max(abs(x.sum(0) - ct).max(), abs(x.sum(1) - rt).max()) < 1e-8:
            break
    if max(abs(x.sum(0) - ct).max(), abs(x.sum(1) - rt).max()) >= 1e-6:
        raise ValueError('H7_IPF_nonconvergence')
    rows, cols = x.shape
    n = x.size
    a = lil_matrix((rows + cols + 2 * n, 2 * n))
    lo = np.full(a.shape[0], -np.inf)
    hi = np.full(a.shape[0], np.inf)
    ids = np.arange(n).reshape(x.shape)
    z = 0
    for i in range(rows):
        a[z, ids[i]] = 1; lo[z] = hi[z] = rt[i]; z += 1
    for j in range(cols):
        a[z, ids[:, j]] = 1; lo[z] = hi[z] = ct[j]; z += 1
    for i, e in enumerate(x.ravel()):
        a[z, i] = 1; a[z, n + i] = -1; hi[z] = e; z += 1
        a[z, i] = -1; a[z, n + i] = -1; hi[z] = -e; z += 1
    upper = np.where(q.ravel() > 0, max(sum(row_totals), 1), 0)
    result = milp(np.r_[np.arange(n) * 1e-10, np.ones(n)],
                  integrality=np.r_[np.ones(n), np.zeros(n)],
                  bounds=Bounds(np.zeros(2 * n), np.r_[upper, np.full(n, np.inf)]),
                  constraints=LinearConstraint(a.tocsc(), lo, hi),
                  options={'time_limit': 30, 'mip_rel_gap': 0})
    if not result.success:
        raise ValueError('H7_integer_transport_failed')
    answer = np.rint(result.x[:n]).astype(int).reshape(x.shape)
    if not np.array_equal(answer.sum(0), ct) or not np.array_equal(answer.sum(1), rt):
        raise ValueError('H7_integer_margins_changed')
    return answer.tolist(), float(abs(answer - x).sum())


def h7_assign(slots, h5, authority, records, mode, rng):
    roomrows = {r['province']: r for r in authority['complete_province_generation_room_counts']}
    groups = collections.defaultdict(list)
    for i, s in enumerate(slots):
        if h5[i]:
            groups[(s['province'], s['generation_category'])].append(i)
    result, targets = {}, []
    for (p, g), ids in groups.items():
        gi = 4 if g == '5+' else int(g) - 1
        freq = roomrows[p]['generation_room_counts'][gi]
        census = [v / sum(freq) for v in freq]
        columns = round_counts(len(ids), census, rng)
        sized = collections.defaultdict(list)
        for i in ids:
            sized[slots[i]['size_category']].append(i)
        sizes = sorted(sized, key=lambda s: 10 if s == '10+' else int(s))
        qs, refs = [], []
        for size in sizes:
            pool, route = select_pool(records, p, size, g, 'joint')
            mass = [sum(float(r['weight']) for r in pool if r['room_proxy_category'] == rr) for rr in ['1', '2', '3', '4', '5+']]
            source_prob = [z / sum(mass) for z in mass] if sum(mass) else census
            q = census if mode == 'independent_size' else [.75 * v + .25 * u for v, u in zip(source_prob, census)]
            qs.append(q)
            refs.append({'size_category': size, **reference_summary(pool, route)})
        matrix, residual = fit_transport([len(sized[z]) for z in sizes], columns, qs)
        for size, counts in zip(sizes, matrix):
            shuffled = list(sized[size]); rng.shuffle(shuffled)
            cats = [rr for rr, n in zip(['1', '2', '3', '4', '5+'], counts) for _ in range(n)]
            for i, cat in zip(shuffled, cats):
                result[i] = cat
        targets.append({'province': p, 'generation_category': g, 'ordinary_profiles': len(ids),
                        'census_probability': census, 'integer_room_bin_target': columns,
                        'size_categories': sizes, 'size_room_bin_matrix': matrix,
                        'source_reference_by_size': refs, 'MILP_L1_vs_IPF': residual,
                        'eligible_one_generation_H7_transport': 'retain ordinary H7 proportions despite unidentified under20-singleton association'})
    return result, targets


def sample_tail(records, field, minimum, maximum, rng):
    freq = collections.Counter()
    for r in records:
        value = integer(r.get(field))
        if value is not None and minimum <= value <= maximum:
            freq[value] += float(r['weight'])
    values = list(range(minimum, maximum + 1))
    source = [freq[v] / sum(freq.values()) if freq else 0 for v in values]
    geometric = [(.5 ** (v - minimum)) for v in values]
    geometric = [v / sum(geometric) for v in geometric]
    probs = [.75 * a + .25 * b for a, b in zip(source, geometric)] if freq else geometric
    selected = weighted_choice(rng, values, probs)
    alltail = [r for r in records if integer(r.get(field)) is not None and integer(r[field]) >= minimum]
    totalw = sum(float(r['weight']) for r in alltail)
    omitted = sum(float(r['weight']) for r in alltail if integer(r[field]) > maximum)
    return selected, {'model': 'pooled_weighted_exact_count_histogram_plus25pct_geometric_design_prior',
                      'support': [minimum, maximum], 'source_tail_records': len(alltail),
                      'source_weighted_mass_above_design_cap': omitted / totalw if totalw else None,
                      'population_tail_frequency_identified': False}


def generated_family(slot, records, rng, max_tail):
    p, size, gg = slot['province'], slot['size_category'], slot['generation_category']
    n = slot['exact_member_count']
    tail = None
    if n is None:
        n, tail = sample_tail(records, 'co_resident_count', 10, max_tail, rng)
    g = 5 if gg == '5+' else int(gg)
    pool, route = select_pool(records, p, size, gg)
    exact = [r for r in pool if r['co_resident_count'] == n and r['generation_count_proxy'] == g]
    if not exact:
        exact = [r for r in records if r['co_resident_count'] == n and r['generation_count_proxy'] == g]
        if exact:
            route = 'nationwide_exact_size_generation_pattern_transport'
    patternmass = collections.Counter()
    for r in exact:
        patternmass[r['_pattern']] += float(r['weight'])
    if patternmass:
        occupied, counts = weighted_choice(rng, list(patternmass), list(patternmass.values()))
        pattern_status = 'modeled_from_weighted_coarse_occupied_generation_count_pattern'
    else:
        occupied = tuple(range(g))
        counts = [1] * g
        for _ in range(n - g):
            counts[rng.randrange(g)] += 1
        counts = tuple(counts)
        pattern_status = 'explicit_design_composition_no_exact_size_generation_reference'
    agepool = exact or [r for r in records if r['generation_count_proxy'] == g]
    min_oldest = max(20 if g == 1 else 0, 18 * max(occupied))
    agefreq = collections.Counter()
    for r in agepool:
        lo = r['_oldest_age_bin'] * 5
        if min(AGE_MAX, lo + 4) >= min_oldest:
            agefreq[r['_oldest_age_bin']] += float(r['weight'])
    if agefreq:
        ab = weighted_choice(rng, list(agefreq), list(agefreq.values()))
        oldest = rng.randint(max(min_oldest, ab * 5), min(AGE_MAX, ab * 5 + 4))
    else:
        oldest = rng.randint(min_oldest, min(AGE_MAX, max(min_oldest, 85)))
    maxlevel = max(occupied)
    gap_budget = oldest
    gaps = []
    for k in range(maxlevel):
        remaining = maxlevel - k - 1
        gap = rng.randint(18, min(32, gap_budget - 18 * remaining))
        gaps.append(gap); gap_budget -= gap
    anchors = {lev: oldest - sum(gaps[lev:]) for lev in occupied}
    male_w = sum(float(r['weight']) * r['_male_count'] for r in agepool)
    sex_w = sum(float(r['weight']) * r['_sex_known_count'] for r in agepool)
    pmale = male_w / sex_w if sex_w else .5
    members, levels = [], {}
    for lev, count in zip(occupied, counts):
        levels[lev] = []
        for j in range(count):
            mid = f"member-{slot['slot_id'][-4:]}-{len(members) + 1:02d}"
            age = anchors[lev] if j == 0 else max(20 if g == 1 else 0, anchors[lev] - rng.randint(0, 6))
            members.append({'member_id': mid, 'age_years': age, 'sex_design': 'male' if rng.random() < pmale else 'female',
                            'generation_level': lev, 'residence_status': 'modeled_usual_resident_at_reference_date',
                            'age_evidence': 'new_integer_draw_from_coarse_source_age_reference_with_design_kinship_constraints',
                            'sex_evidence': 'new_draw_from_weighted_co_resident_sex_marginal_not_individual_observation'})
            levels[lev].append(mid)
    relations = []
    coupleprob = (sum(float(r['weight']) for r in agepool if r['_has_couple_reference']) /
                  sum(float(r['weight']) for r in agepool)) if agepool else .5
    for lev in occupied:
        ids = levels[lev]
        if len(ids) >= 2 and rng.random() < coupleprob:
            # Couple is designed, not reconstructed. Force adult eligibility.
            a, b = [next(m for m in members if m['member_id'] == z) for z in ids[:2]]
            if min(a['age_years'], b['age_years']) >= 20:
                b['sex_design'] = 'female' if a['sex_design'] == 'male' else 'male'
                relations.append({'kind': 'spouse_design', 'member_ids': ids[:2], 'evidence': 'declared_relationship_design'})
        for mid in ids[1:]:
            relations.append({'kind': 'same_generation_kin_or_cohabitants_design', 'member_ids': [ids[0], mid], 'evidence': 'declared_relationship_design'})
    for young, older in zip(occupied, occupied[1:]):
        delta = older - young
        for child in levels[young]:
            relations.append({'kind': 'parent_child_design' if delta == 1 else 'ancestor_descendant_design',
                              'older_member_id': levels[older][0], 'younger_member_id': child,
                              'generation_gap': delta, 'evidence': 'declared_relationship_design_not_observed_parent_graph'})
    family = {'population_scope': 'city_family_household', 'reference_date': REFERENCE_DATE,
              'family_id': 'family-' + slot['slot_id'][-4:], 'resident_member_ids': [m['member_id'] for m in members],
              'resident_count': n, 'members': members, 'generation_levels': sorted(occupied),
              'generation_count_design': len(occupied), 'relation_design': relations,
              'residence_evidence': 'declared_synthetic_role', 'member_generation_reference': reference_summary(exact or pool, route),
              'composition_evidence': pattern_status, 'complete_original_source_family_copied': False,
              'exact_size_tail': tail, 'economic_scope': {'status': 'pending_separate_generated_economic_scope',
                                                        'source_economic_family_not_equal_resident_roster': True}}
    return family


def sample_area(records, slot, room, rng):
    pool, route = select_pool(records, slot['province'], slot['size_category'], slot['generation_category'], 'area', room)
    histogram = collections.Counter()
    clipped = 0
    for r in pool:
        value = float(r['area_candidate_m2'])
        if value > AREA_EDGES[-1]:
            value = AREA_EDGES[-1] - 1e-6; clipped += 1
        for i in range(len(AREA_EDGES) - 1):
            if AREA_EDGES[i] <= value < AREA_EDGES[i + 1]:
                histogram[i] += float(r['weight']); break
    if histogram:
        index = weighted_choice(rng, list(histogram), list(histogram.values()))
        area = rng.uniform(AREA_EDGES[index], AREA_EDGES[index + 1])
    else:
        area = rng.uniform(20, 140)
    return area, {**reference_summary(pool, route), 'source_area_proxy': 'same_current_dwelling_H6_proxy_building_or1_33_conversion',
                  'area_value_evidence': 'new_continuous_draw_inside_coarse_weighted_area_bin; no_source_value_copied',
                  'source_records_above2000_design_winsor_cap': clipped,
                  'area_bin_edges_m2': AREA_EDGES, 'CHFS_H5_observed': False}


def sleep_groups(family, room_count):
    """Explicit designed assignment; generation count does not set rooms."""
    units, assigned = [], set()
    for rel in family['relation_design']:
        if rel['kind'] == 'spouse_design' and not assigned.intersection(rel['member_ids']):
            units.append(list(rel['member_ids'])); assigned.update(rel['member_ids'])
    units += [[m] for m in family['resident_member_ids'] if m not in assigned]
    groups = [[] for _ in range(room_count)]
    for unit in sorted(units, key=lambda u: -len(u)):
        groups[min(range(room_count), key=lambda i: (len(groups[i]), i))].extend(unit)
    return groups


def assign_longform(profiles, authority, rng):
    """Ordinary-only transported vintage/storeys margins, area group means."""
    grouped = collections.defaultdict(list)
    for p in profiles:
        if p['housing']['H5_is_ordinary_model_assigned']:
            grouped[p['province']].append(p)
    years = [(1850, 1948), (1949, 1959), (1960, 1969), (1970, 1979), (1980, 1989), (1990, 1999), (2000, 2009), (2010, 2014), (2015, 2020)]
    targets = []
    for province, ps in grouped.items():
        ref = authority['long_form_housing_summary'][province]
        vc = round_counts(len(ps), ref['vintage_counts'], rng)
        sc = round_counts(len(ps), ref['building_storeys_counts'], rng)
        vi = [i for i, n in enumerate(vc) for _ in range(n)]; rng.shuffle(vi)
        si = [i for i, n in enumerate(sc) for _ in range(n)]; rng.shuffle(si)
        for p, v, s in zip(ps, vi, si):
            h = p['housing']; h['vintage_category_index'] = v
            h['building_year_design'] = rng.randint(*years[v])
            h['building_year_evidence'] = 'new_year_draw_within_census_longform_vintage_bin; eligible_transport_independent_of_size_generation'
            h['building_storeys_category_index'] = s
            ranges = [(1, 1), (2, 7), (8, 33), (34, 50)]
            h['building_total_storeys_design'] = rng.randint(*ranges[s])
            h['dwelling_type'] = 'single_storey_ordinary_house_design' if s == 0 else 'apartment'
            h['dwelling_type_evidence'] = 'declared_geometry_regime_from_transported_building_storeys_bin; not_observed_house_type'
            h['household_storeys'] = 2 if s > 0 and rng.random() < .05 else 1
            if h['household_storeys'] == 2:
                h['dwelling_type'] = 'maisonette_design'
            h['household_storeys_evidence'] = 'explicit5pct_multi_level_design_prior_for_nonflat_buildings_not_census_joint'
        for v, n in enumerate(vc):
            selected = [p for p in ps if p['housing']['vintage_category_index'] == v]
            mean = ref['vintage_whole_area_means_m2'][v]
            if not selected:
                targets.append({'province': province, 'vintage_category_index': v, 'profiles': 0,
                                'reference_mean_H6_m2': mean, 'mean_constraint_realized': False})
                continue
            initial = sum(p['housing']['H6_building_area_m2'] for p in selected)
            scale = mean * n / initial
            for p in selected:
                p['housing']['area_before_mean_calibration_m2'] = p['housing']['H6_building_area_m2']
                p['housing']['area_calibration_scale'] = scale
                p['housing']['H6_building_area_m2'] = round(p['housing']['H6_building_area_m2'] * scale, 2)
                p['housing']['H6_evidence'] = 'modeled_binned_CHFS_area_proxy_then_census_longform_group_mean_calibration'
            actual = sum(p['housing']['H6_building_area_m2'] for p in selected) / n
            targets.append({'province': province, 'vintage_category_index': v, 'profiles': n,
                            'reference_mean_H6_m2': mean, 'actual_mean_H6_m2': actual,
                            'rounding_mean_residual_m2': actual - mean, 'multiplicative_calibration_scale': scale,
                            'mean_constraint_realized': True})
    return targets


def generate(args):
    out = Path(args.output).resolve()
    if out.exists():
        raise ValueError('output_must_be_new_immutable_directory')
    out.mkdir(parents=True)
    rng = stage_rng(args.seed, 'H5_integer_bridge')
    allocation_path = ROOT / 'evidence_contract_20261001/POPULATION_ALLOCATION_CANDIDATE_V2.json'
    authority_path = ROOT / 'evidence_contract_20261001/CITY_AUTHORITY_CONSTRAINTS_V2.json'
    allocation = json.loads(allocation_path.read_text()); authority = json.loads(authority_path.read_text())
    slots = allocation['slots']
    records = load_references()
    h5, h5targets = h5_assign(slots, authority, args.h5_mode, rng)
    h7, h7targets = h7_assign(slots, h5, authority, records, args.h7_mode, stage_rng(args.seed, 'H7_conditional_transport'))
    profiles = []
    for i, slot in enumerate(slots):
        family = generated_family(slot, records, stage_rng(args.seed, 'family_' + slot['slot_id']), args.max_household_tail)
        rng = stage_rng(args.seed, 'housing_' + slot['slot_id'])
        ordinary = h5[i]
        rbin = h7.get(i)
        tail = None
        if ordinary:
            if rbin == '5+':
                rr, tail = sample_tail(records, 'room_count_h7_proxy', 5, args.max_room_tail, stage_rng(args.seed, 'H7_tail_' + slot['slot_id']))
            else:
                rr = int(rbin)
        else:
            rr = max(1, min(6, math.ceil(family['resident_count'] / 2)))
        area, aref = sample_area(records, slot, rbin if ordinary else None, stage_rng(args.seed, 'area_' + slot['slot_id']))
        rng = stage_rng(args.seed, 'sharing_' + slot['slot_id'])
        pool, route = select_pool(records, slot['province'], slot['size_category'], slot['generation_category'])
        known = [r for r in pool if r['sharing_scope'] in ['whole_current_owned_dwelling', 'whole_rented_dwelling', 'partial_occupancy_requires_allocation', 'shared_area_allocation_unknown']]
        if known:
            sw = sum(float(r['weight']) for r in known if r['sharing_scope'] in ['partial_occupancy_requires_allocation', 'shared_area_allocation_unknown'])
            sharedprob = sw / sum(float(r['weight']) for r in known)
        else:
            sharedprob = .1
        shared = rng.random() < sharedprob if ordinary else True
        allocation_ratio = rng.uniform(.4, .85) if shared else 1.0
        # This scales generated reference area, not a source whole home record.
        area *= allocation_ratio
        housing = {'H5_is_ordinary_model_assigned': ordinary,
                   'H5_status': 'ordinary_declared_or_matched' if ordinary else 'nonordinary_model_assigned',
                   'H5_evidence': 'modeled_census_province_generation_bounded_binary_bridge_' + args.h5_mode,
                   'H5_detailed_subtype_code': 1 if ordinary else None,
                   'H5_detailed_nonordinary_subtype_status': 'not_identified; declared_accommodation_scenario_is_not_census_subtype',
                   'census_H6_H7_applicable': ordinary,
                   'H6_building_area_m2': round(area, 2) if ordinary else None,
                   'H6_evidence': 'modeled_from_coarse_CHFS_same_dwelling_area_proxy_not_observed' if ordinary else 'not_applicable_to_nonordinary_census_frame',
                   'H7_natural_rooms_exact': rr if ordinary else None,
                   'H7_census_bin': rbin,
                   'H7_evidence': 'modeled_census_ordinary_conditional_integer_calibration_with_CHFS_association_' + args.h7_mode if ordinary else 'not_applicable_to_nonordinary_census_frame',
                   'H7_definition': 'natural_rooms_excluding_kitchen_toilet_corridor_hall' if ordinary else None,
                   'exact_room_tail_model': tail,
                   'design_floor_area_m2': None if ordinary else round(area, 2),
                   'design_natural_rooms_exact': None if ordinary else rr,
                   'nonordinary_model_scenario': None if ordinary else 'declared_shared_accommodation_stress_scenario_not_identified_H5_subtype',
                   'occupancy_scope': 'shared_exclusive_model_assigned' if shared else 'whole_household_private',
                   'sharing_model': {'weighted_reference_probability': sharedprob, 'whole_to_exclusive_design_ratio': allocation_ratio,
                                     'range': [.4, .85], 'scope': 'new_generated_exclusive_plus_prorated_common_area; not_source_observed_allocation',
                                     'reference': reference_summary(known, route), 'nonordinary_forced_shared': not ordinary},
                   'area_reference': aref, 'sleep_groups': sleep_groups(family, rr),
                   'sleep_evidence': 'declared_least_loaded_room_assignment_with_designed_couple_units; no_observed_bedroom_mapping',
                   'dwelling_type': None if ordinary else 'nonordinary_shared_accommodation_design',
                   'household_storeys': 1,
                   'geometry_or_template_feasibility_used_to_choose_household': False,
                   'physical_binding_status': 'pending_city_prototype_layout_and_supported_regime_validation'}
        profiles.append({'slot_id': slot['slot_id'], 'province': slot['province'], 'size_category': slot['size_category'],
                         'generation_category': slot['generation_category'], 'exact_member_count': family['resident_count'],
                         'family': family, 'housing': housing, 'site': {'province': slot['province'], 'city': None,
                                                                     'coordinate_evidence': None, 'urban_placement_status': 'pending_target_city_distribution_and111_112_design'},
                         'model_policy': {'prototype_key': None, 'gross_to_zone_floor_ratio': None,
                                          'geometry_status': 'not_bound_no_layout_feasibility_resampling'},
                         'devices': {'status': 'pending'}, 'activities': {'status': 'pending'},
                         'human_answers': None, 'complete_actor_card': False,
                         'evidence_status': 'modeled_anonymous_family_housing_candidate_not_observed_household'})
    areatargets = assign_longform(profiles, authority, stage_rng(args.seed, 'ordinary_longform_assignment'))
    # Source references are aggregated diagnostics; never expose original ids.
    influence = {'schema': 'eb.synthetic_reference_influence.v1', 'source_records_admitted': len(records),
                 'pool_reference_by_profile': [{'slot_id': p['slot_id'], 'member_reference': p['family']['member_generation_reference'],
                                               'area_reference': {k: v for k, v in p['housing']['area_reference'].items() if k in ['route', 'source_records', 'kish_effective_sample_size', 'maximum_weight_share', 'source_visit_years']}}
                                              for p in profiles],
                 'donor_assignments': 0, 'raw_source_households_exported': 0, 'source_ids_exported': 0,
                 'definition': 'each conditional model references a weighted aggregate pool; this is influence exposure, not donor selection or source-cluster sampling variance'}
    settings = {'version': VERSION, 'seed': args.seed, 'h5_mode': args.h5_mode, 'h7_mode': args.h7_mode,
                'reference_date': REFERENCE_DATE, 'max_household_tail': args.max_household_tail,
                'max_room_tail': args.max_room_tail, 'area_bin_edges_m2': AREA_EDGES,
                'age_cap': AGE_MAX, 'parent_generation_min_age_gap': 18,
                'random_streams': 'sha256(seed|stage_or_slot); family stream independent of every housing factor',
                'room_reference_smoothing_census_mass': .25, 'tail_geometric_prior_mass': .25,
                'declared_nonordinary_scenario': 'shared_accommodation; not a subtype frequency estimate',
                'financial_values_generated': False, 'template_feasibility_in_generation': False,
                'cross_year_transport': 'field-specific references; no requirement to pretend2020/2021/2022 are same-time observations'}
    body = {'schema': 'eb.anonymous_family_housing_candidates.v1', 'generation_model': settings,
            'target_allocation_sha256': sha(allocation_path), 'profiles': profiles,
            'complete_actor_cards': 0, 'human_answers': 0, 'collection_release': False, 'training_release': False}
    save(out / 'FAMILY_HOUSING_CANDIDATES.json', body)
    save(out / 'CALIBRATION_TARGETS.json', {'H5_province_generation': h5targets, 'ordinary_H7_province_generation': h7targets,
                                           'ordinary_H6_province_vintage_means': areatargets,
                                           'longform_transport': 'ordinary longform sample margins applied to eligible synthetic ordinary cohort; not observed eligible joint',
                                           'H7_by_size_association': args.h7_mode})
    save(out / 'SOURCE_INFLUENCE.json', influence)
    (out / 'code').mkdir()
    for name in ['generate_candidates.py', 'verify_candidates.py']:
        shutil.copy2(HERE / name, out / 'code' / name)
    source_files = [allocation_path, authority_path, BRIDGE / 'run_bridge.py', BRIDGE / 'bridge_rules.py',
                    *sorted(rb.PACKAGE.glob('chfs2021_*_pub_*.dta'))]
    save(out / 'GENERATOR_LOCK.json', {'settings': settings, 'python': sys.version, 'numpy_version': np.__version__,
                                     'scipy_version': scipy.__version__, 'pandas_version': pd.__version__,
                                     'source_files': [{'path': str(p), 'sha256': sha(p)} for p in source_files],
                                     'code_sha256': sha(__file__), 'output_sha256': sha(out / 'FAMILY_HOUSING_CANDIDATES.json'),
                                     'original_source_rows_output': False, 'original_source_ids_output': False})
    print(json.dumps({'output': str(out), 'family_housing_candidates': len(profiles),
                      'ordinary': sum(p['housing']['H5_is_ordinary_model_assigned'] for p in profiles),
                      'nonordinary': sum(not p['housing']['H5_is_ordinary_model_assigned'] for p in profiles),
                      'source_records_admitted': len(records), 'actor_ready_claim': False}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--seed', type=int, default=20261003)
    parser.add_argument('--h5-mode', choices=['independence', 'lower_ordinary', 'upper_ordinary'], default='independence')
    parser.add_argument('--h7-mode', choices=['source_association', 'independent_size'], default='source_association')
    parser.add_argument('--max-household-tail', type=int, default=16)
    parser.add_argument('--max-room-tail', type=int, default=20)
    args = parser.parse_args()
    if args.max_household_tail < 10 or args.max_room_tail < 5:
        parser.error('tail maximum below topcode threshold')
    generate(args)
