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

VERSION = 'FAMILY_HOUSING_GENERATOR_20261003_V3_EMPIRICAL_SUPPORT'
REFERENCE_DATE = '2020-11-01'
AREA_EDGES = [1, 20, 40, 60, 80, 100, 120, 160, 200, 250, 350, 500, 750, 1000, 1500, 2000]
MODEL = {}
FAMILY_REFERENCE_CACHE = {}
AREA_REFERENCE_CACHE = {}


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
            'no_donor_selected': True,
            'reference_mixture': records[0].get('_mixture_report') if records else None}


def load_references():
    """Read authorized local files; no original identifiers/values are saved."""
    frame = rb.load_bridge_pool()
    # Financial complete cases are not necessary for family/housing references.
    records = frame[frame.eligible_for_generation_matching & frame.weight.notna() & (frame.weight > 0)].to_dict('records')
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
        width = MODEL['age_bin_width']
        agebins = {lev: [] for lev in occupied}
        sexcounts = collections.Counter()
        for p, lev in zip(co, levels):
            age = int(r['visit_year']) - integer(p['a2005'])
            normalized = lev - low
            lowerbin=max(0,(age-1)//width);upperbin=max(0,age//width)
            agebins[normalized].append((lowerbin,upperbin))
            sex = integer(p['a2003'])
            if sex in [1, 2]:
                probability=MODEL['birthyear_upper_probability']
                sexcounts[(occupied.index(normalized), lowerbin, sex)] += 1-probability
                sexcounts[(occupied.index(normalized), upperbin, sex)] += probability
        r['_joint_age_pattern'] = (tuple(occupied), tuple(counts[z] for z in occupied),
                                   tuple(tuple(sorted(agebins[z])) for z in occupied))
        r['_age_sex_counts'] = sexcounts
        r['_male_count'] = sum(integer(p['a2003']) == 1 for p in co)
        r['_sex_known_count'] = sum(integer(p['a2003']) in [1, 2] for p in co)
        r['_has_couple_reference'] = {1, 2} <= {integer(p['a2001']) for p in co}
        r['_source_relation_counts']=collections.Counter(integer(p['a2001']) for p in co)
        r['_birthyear_under20_certain_count']=sum(int(r['visit_year'])-integer(p['a2005'])<20 for p in co)
        r['_birthyear_boundary19_20_count']=sum(int(r['visit_year'])-integer(p['a2005'])==20 for p in co)
    return records


def select_pool(records, province, size, generation, need='member', room=None):
    def admitted(r):
        if need == 'member':
            return True
        if MODEL.get('minimum_source_area_per_room_m2',0)>0:
            rr=integer(r.get('room_count_h7_proxy'));a=r.get('area_candidate_m2')
            if rr is not None and rr>0 and isinstance(a,(int,float)) and math.isfinite(a) and a/rr<MODEL['minimum_source_area_per_room_m2']:
                return False
        if need == 'joint':
            return bool(r['area_scope_supported']) and integer(r['room_count_h7_proxy']) is not None
        return bool(r['area_scope_supported']) and isinstance(r['area_candidate_m2'], (int, float)) and math.isfinite(r['area_candidate_m2'])
    eligible = [r for r in records if admitted(r)]
    if room is not None and need in ['area','joint']:
        eligible=[r for r in eligible if r['room_proxy_category']==room]
    def preferred(test):
        pool = [r for r in eligible if test(r)]
        room_relaxed = False
        if room is not None:
            narrowed = [r for r in pool if r['room_proxy_category'] == room]
            if narrowed: pool = narrowed
            else: room_relaxed = True
        aligned = [r for r in pool if r['member_housing_same_reference_time']]
        return (aligned or pool), room_relaxed, bool(aligned)
    local, lr, la = preferred(lambda r: r['province'] == province and r['size_category'] == size and r['generation_category'] == generation)
    national, nr, na = preferred(lambda r: r['size_category'] == size and r['generation_category'] == generation)
    broad, br, ba = preferred(lambda r: r['generation_category'] == generation)
    if not broad: broad, br, ba = preferred(lambda r: True)
    if not broad: return [], 'no_admitted_reference'
    def ess(pool):
        ws = [float(r['weight']) for r in pool]
        return sum(ws) ** 2 / sum(w*w for w in ws) if ws else 0
    tau = MODEL['shrinkage_tau']
    le, ne = ess(local), ess(national)
    ll = le / (le + tau) if le else 0
    nl = ne / (ne + tau) if ne else 0
    pools=[local,national,broad];labels=['same_province_N_G','national_N_G','national_G_or_city']
    relaxed=[lr,nr,br];aligned=[la,na,ba]
    masses = [ll, (1-ll)*nl, (1-ll)*(1-nl)]
    if need in ['area','joint']:
        city,cr,ca=preferred(lambda r:True)
        be=ess(broad);bl=be/(be+tau) if be else 0
        remaining=masses[-1]
        masses[-1]=remaining*bl;masses.append(remaining*(1-bl))
        pools.append(city);labels.append('national_city_housing_prior');relaxed.append(cr);aligned.append(ca)
    components = []
    blended = {}
    for label, pool, mass, relaxed, aligned in zip(labels,pools,masses,relaxed,aligned):
        total = sum(float(r['weight']) for r in pool)
        components.append({'layer':label,'mass':mass,'source_records':len(pool),'kish_ESS':ess(pool),
                           'room_condition_relaxed':relaxed,'time_aligned_preferred':aligned,
                           'source_years':sorted({int(r['visit_year']) for r in pool})})
        if mass <= 0: continue
        for r in pool:
            identity = r['_local_hhid']
            if identity not in blended: blended[identity] = {**r, 'weight':0.0}
            blended[identity]['weight'] += mass * float(r['weight']) / total
    report = {'design_tau':tau,'formula':'lambda=KishESS/(KishESS+tau); nested_local_national_broad',
              'components':components,'overlap_combined_before_influence_diagnostics':True,
              'housing_city_prior_fixed_before_any_census_mean_fit':need in ['area','joint'],
              'geographic_and_time_transport_is_a_model':True,
              'same_H7_bin_required_for_housing_reference':room is not None and need in ['area','joint'],
              'minimum_source_area_per_room_m2_design':MODEL.get('minimum_source_area_per_room_m2',0)}
    result = list(blended.values())
    for r in result: r['_mixture_report'] = report
    return result, 'ESS_continuous_local_national_NG_national_G_hierarchical_mixture'


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
            prior = MODEL['h7_prior_mass']
            q = census if mode == 'independent_size' else [(1-prior) * v + prior * u for v, u in zip(source_prob, census)]
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
    ws = [float(r['weight']) for r in records if integer(r.get(field)) is not None and minimum <= integer(r[field]) <= maximum]
    ess = sum(ws)**2 / sum(w*w for w in ws) if ws else 0
    fraction = (1-MODEL['tail_prior_mass']) * ess / (ess + MODEL['shrinkage_tau']) if ess else 0
    probs = [fraction * a + (1-fraction) * b for a, b in zip(source, geometric)]
    selected = weighted_choice(rng, values, probs)
    alltail = [r for r in records if integer(r.get(field)) is not None and integer(r[field]) >= minimum]
    totalw = sum(float(r['weight']) for r in alltail)
    omitted = sum(float(r['weight']) for r in alltail if integer(r[field]) > maximum)
    return selected, {'model': 'weighted_exact_count_histogram_ESS_shrunk_to_geometric_design_prior',
                      'support': [minimum, maximum], 'source_tail_records': len(alltail),
                      'design_prior_mass':MODEL['tail_prior_mass'],'source_ESS':ess,'effective_source_mass':fraction,
                      'source_weighted_mass_above_design_cap': omitted / totalw if totalw else None,
                      'population_tail_frequency_identified': False}


def generated_family(slot, records, rng, max_tail):
    province, size, gg = slot['province'], slot['size_category'], slot['generation_category']
    n = slot['exact_member_count']
    tail = None
    if n is None:
        n, tail = sample_tail(records, 'co_resident_count', 10, max_tail, rng)
    g = 5 if gg == '5+' else int(gg)
    key=(province,size,gg)
    if key not in FAMILY_REFERENCE_CACHE:
        pool, route = select_pool(records, province, size, gg)
        patterns=collections.Counter();sexmass=collections.Counter();relationmass=collections.Counter();presence=collections.Counter()
        for record in pool:
            if record['generation_count_proxy'] == g:
                patterns[record['_joint_age_pattern']] += float(record['weight'])
                for sexkey,count in record['_age_sex_counts'].items():
                    sexmass[sexkey] += float(record['weight'])*count
                for code,count in record['_source_relation_counts'].items():
                    relationmass[code]+=float(record['weight'])*count
                    if count:presence[code]+=float(record['weight'])
        relationship_reference={'source_question':'A2001 relationship_to_respondent; 2 partner_or_spouse; 10 siblings; 7777 other',
            'weighted_expected_resident_count_by_source_relation_code':dict(relationmass),
            'weighted_presence_probability_by_source_relation_code':dict(presence),
            'scope':'ESS_mixed_source_reference_diagnostic_only_not_generated_kinship_graph',
            'pairwise_parent_partner_edges_observed_for_synthetic_family':False}
        FAMILY_REFERENCE_CACHE[key]=(patterns,sexmass,reference_summary(pool,route),relationship_reference)
    patterns,sexmass,reference,relationship_reference=FAMILY_REFERENCE_CACHE[key]
    if n==1:
        probability=MODEL['birthyear_upper_probability'];width=MODEL['age_bin_width']
        patterns={pattern:weight for pattern,weight in patterns.items() if any(
            ((low+1)*width-1>=20 and probability<1) or ((high+1)*width-1>=20 and probability>0)
            for levelbins in pattern[2] for low,high in levelbins)}
    if not patterns:
        raise ValueError('no_coarsened_generation_age_reference')
    occupied, oldcounts, agebins = weighted_choice(rng, list(patterns), list(patterns.values()))
    adapted = sum(oldcounts) != n
    counts = list(oldcounts)
    if adapted:
        counts = [1] * g
        for _ in range(n-g):
            index = weighted_choice(rng, list(range(g)), oldcounts)
            counts[index] += 1
    width = MODEL['age_bin_width']
    members, bylevel = [], {}
    for ordinal, (lev, count, bins) in enumerate(zip(occupied, counts, agebins)):
        bylevel[lev] = []
        eligible_bins=list(bins)
        if n==1:
            probability=MODEL['birthyear_upper_probability']
            eligible_bins=[b for b in eligible_bins if ((b[0]+1)*width-1>=20 and probability<1) or ((b[1]+1)*width-1>=20 and probability>0)]
        if not eligible_bins:raise ValueError('no_age_bin_after_singleton_eligibility_condition')
        if count<=len(eligible_bins):selected_bins=rng.sample(eligible_bins,count)
        else:
            selected_bins=eligible_bins+[weighted_choice(rng,eligible_bins,[1]*len(eligible_bins)) for _ in range(count-len(eligible_bins))]
            rng.shuffle(selected_bins)
        for lowerbin,upperbin in selected_bins:
            ab=upperbin if rng.random()<MODEL['birthyear_upper_probability'] else lowerbin
            if n==1 and (ab+1)*width-1<20:ab=upperbin
            low, high = ab*width, ab*width+width-1
            if n == 1:
                low = max(20, low)
                if high < low: raise ValueError('singleton_age_reference_under20')
            age = rng.randint(low, high)
            male = sexmass[(ordinal,ab,1)]
            known = male+sexmass[(ordinal,ab,2)]
            pmale = male/known if known else .5
            mid = f"member-v3-{slot['slot_id'][-4:]}-{len(members)+1:02d}"
            members.append({'member_id':mid,'age_years':age,'sex_design':'male' if rng.random()<pmale else 'female',
                'generation_level':lev,'residence_status':'modeled_usual_resident_at_reference_date',
                'age_evidence':'new_within_bin_draw_from_ESS_mixed_coarsened_age_generation_count_reference',
                'age_reference_bin_years':[low,high],
                'birthyear_interval_evidence':'birth_year_only_age_d_minus1_to_d; coarse_boundary_mixture_is_design_not_birthday_observation',
                'sex_evidence':'new_draw_from_ESS_mixed_generation_age_bin_sex_marginal_no_pair_constraint'})
            bylevel[lev].append(mid)
    relations = []
    for lev, ids in bylevel.items():
        for mid in ids[1:]:
            relations.append({'kind':'shared_generation_design','member_ids':[ids[0],mid],
                'evidence':'occupied_generation_membership_only; kinship_and_partnership_unknown'})
    for first, second in zip(occupied, occupied[1:]):
        relations.append({'kind':'cross_generation_co_residence_design',
            'member_ids':[bylevel[first][0],bylevel[second][0]],'generation_difference':second-first,
            'evidence':'co_resident_occupied_generations_only; not_parent_child_inference'})
    return {'population_scope':'city_family_household','reference_date':REFERENCE_DATE,
        'family_id':'family-v3-'+slot['slot_id'][-4:],'profile_version':VERSION,
        'resident_member_ids':[m['member_id'] for m in members],'resident_count':n,'members':members,
        'generation_levels':list(occupied),'generation_count_design':g,'relation_design':relations,
        'residence_evidence':'declared_synthetic_role','member_generation_reference':reference,
        'composition_evidence':'new_draw_from_weighted_coarsened_age_generation_count_pattern_with_ESS_mixture',
        'composition_count_adaptation':{'used':adapted,'method':'one_per_occupied_level_plus_multinomial_reference_proportions' if adapted else 'exact_N_reference_coarse_pattern'},
        'age_kinship_policy':{'only_singleton_under20_excluded':True,'same_generation_age_gap_limit':None,
            'mandatory_parent_age_gap':None,'mandatory_spouse_opposite_sex':False,
            'detailed_parent_spouse_edges':'unknown_not_generated_from_generation_levels'},
        'complete_original_source_family_copied':False,'exact_size_tail':tail,
        'source_relationship_reference':relationship_reference,
        'actor_fact_completeness':{'resident_roster':'generated','detailed_kinship_graph':'pending_ego_relation_generation_with_age_consistency',
            'unidentified_edges_not_frozen_as_facts':True},
        'economic_scope':{'status':'pending_separate_generated_economic_scope','source_economic_family_not_equal_resident_roster':True}}

def sample_area(records, slot, room, rng):
    key=(slot['province'],slot['size_category'],slot['generation_category'],room)
    if key in AREA_REFERENCE_CACHE:
        reference=AREA_REFERENCE_CACHE[key]
        bins=reference['predictive_area_bins']
        chosen=weighted_choice(rng,bins,[x['probability'] for x in bins])
        return rng.uniform(chosen['lower_m2'],chosen['upper_m2']),reference
    pool, route = select_pool(records, slot['province'], slot['size_category'], slot['generation_category'], 'area', room)
    histogram = collections.Counter()
    squares=collections.Counter();maxweights=collections.Counter();bin_counts=collections.Counter()
    empirical_values=collections.defaultdict(list)
    omitted = 0.0
    for r in pool:
        value = float(r['area_candidate_m2'])
        index = next((i for i in range(len(AREA_EDGES)-1) if AREA_EDGES[i] <= value <= AREA_EDGES[i+1]),None)
        if index is None:
            omitted += float(r['weight'])
        else:
            histogram[index] += float(r['weight'])
            squares[index]+=float(r['weight'])**2
            maxweights[index]=max(maxweights[index],float(r['weight']))
            bin_counts[index]+=1
            empirical_values[index].append(value)
    if not histogram: raise ValueError('no_area_mass_inside_declared_bins')
    total = sum(histogram.values())
    bins = [{'lower_m2':min(empirical_values[i]),'upper_m2':max(empirical_values[i]),'probability':weight/total,
             'source_coarsening_bin_m2':[AREA_EDGES[i],AREA_EDGES[i+1]],
             'distribution':'point_mass' if min(empirical_values[i])==max(empirical_values[i]) else 'uniform_within_empirical_conditional_endpoint_interval',
             'source_H7_bin':room,'source_support_endpoints_used_without_expansion':True,
             'source_weight_square_sum':squares[i]/total**2,'maximum_source_weight':maxweights[i]/total,'source_records':bin_counts[i]}
            for i,weight in sorted(histogram.items())]
    index = weighted_choice(rng,list(range(len(bins))),[x['probability'] for x in bins])
    chosen = bins[index]
    area = rng.uniform(chosen['lower_m2'],chosen['upper_m2'])
    reference={**reference_summary(pool,route),
        'source_area_proxy':'same_current_dwelling_H6_proxy_building_or1_33_conversion',
        'area_value_evidence':'new_within_coarse_bin_draw_from_ESS_shrunk_weighted_area_reference',
        'predictive_area_bins':bins,'weighted_mass_outside_design_area_bins':omitted,
        'area_bin_edges_m2':AREA_EDGES,'CHFS_H5_observed':False,
        'source_support_policy':'strict_same_H7_bin_when_ordinary; actual_source_bin_endpoint_interval_or_point_mass; no_missing_H7_relaxation',
        'source_scope_policy':'whole-owned_or_whole-rented_supported_current_dwelling; shared_exclusive_allocation_remains_design',
        'minimum_source_area_per_room_m2_design':MODEL.get('minimum_source_area_per_room_m2',0)}
    AREA_REFERENCE_CACHE[key]=reference
    return area,reference


def tilted_distribution(bins, theta):
    logm, means = [], []
    for b in bins:
        low, high = b['lower_m2'], b['upper_m2']
        width = high-low
        if width==0:
            logm.append(math.log(b['probability'])+theta*low);means.append(low)
            continue
        x = theta*width
        if abs(x) < 1e-6:
            logz = theta*(low+high)/2 + x*x/24
            mean = (low+high)/2 + theta*width*width/12
        elif theta > 0:
            logz = theta*low + (x+math.log1p(-math.exp(-x)) if x>50 else math.log(math.expm1(x))) - math.log(x)
            mean = low + width/(-math.expm1(-x)) - 1/theta
        else:
            logz = theta*low + math.log(-math.expm1(x)) - math.log(-x)
            k = -theta
            mean = low + 1/k - (width/math.expm1(-x) if -x<700 else 0)
        logm.append(math.log(b['probability'])+logz)
        means.append(mean)
    maximum = max(logm)
    masses = [math.exp(x-maximum) for x in logm]
    norm = sum(masses)
    probs = [x/norm for x in masses]
    return probs, sum(p*x for p,x in zip(probs,means))


def tilted_area_draw(bins, theta, rng, quantile=None):
    probs, expected = tilted_distribution(bins,theta)
    u=rng.random() if quantile is None else quantile
    cumulative=0.0
    index=len(bins)-1
    for i,p in enumerate(probs):
        if u<cumulative+p:
            index=i;break
        cumulative+=p
    u=min(1-1e-15,max(0.0,(u-cumulative)/probs[index]))
    b = bins[index];low,high=b['lower_m2'],b['upper_m2']
    if high==low:
        area=low
    elif abs(theta*(high-low)) < 1e-6:
        area = low+(high-low)*u
    elif theta > 0:
        area = high + math.log(max(1e-300,u+(1-u)*math.exp(-theta*(high-low))))/theta
    else:
        area = low + math.log1p(u*math.expm1(theta*(high-low)))/theta
    post_squares=sum(b['source_weight_square_sum']*(p/b['probability'])**2 for b,p in zip(bins,probs))
    post_max=max(b['maximum_source_weight']*p/b['probability'] for b,p in zip(bins,probs))
    return area, expected, 1/sum(p*p for p in probs), max(probs), 1/post_squares, post_max

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
    grouped = collections.defaultdict(list)
    for p in profiles:
        if p['housing']['H5_is_ordinary_model_assigned']: grouped[p['province']].append(p)
    years=[(1850,1948),(1949,1959),(1960,1969),(1970,1979),(1980,1989),(1990,1999),(2000,2009),(2010,2014),(2015,2020)]
    targets=[]
    for province, ps in grouped.items():
        ref=authority['long_form_housing_summary'][province]
        vc=round_counts(len(ps),ref['vintage_counts'],rng);sc=round_counts(len(ps),ref['building_storeys_counts'],rng)
        vi=[i for i,n in enumerate(vc) for _ in range(n)];rng.shuffle(vi)
        si=[i for i,n in enumerate(sc) for _ in range(n)];rng.shuffle(si)
        for p,v,ss in zip(ps,vi,si):
            h=p['housing'];h['vintage_category_index']=v;h['building_year_design']=rng.randint(*years[v])
            h['building_year_evidence']='new_year_draw_within_census_longform_vintage_bin; eligible_transport_independent_of_size_generation'
            h['building_storeys_category_index']=ss
            h['H8_building_storeys_bin']=['flat_one_natural_storey','2_to7','8_to33','34plus'][ss]
            h['building_total_storeys_design']=rng.randint(*[(1,1),(2,7),(8,33),(34,MODEL['max_building_storeys'])][ss])
            h['building_storeys_evidence']='new_count_within_census_H8_building_natural_storeys_bin; not_household_internal_floors_or_dwelling_form'
        for v,n in enumerate(vc):
            selected=[p for p in ps if p['housing']['vintage_category_index']==v]
            target=ref['vintage_whole_area_means_m2'][v]
            if not selected:
                targets.append({'province':province,'vintage_category_index':v,'profiles':0,'reference_mean_H6_m2':target,'mean_constraint_realized':False})
                continue
            allbins=[]
            for p in selected:
                h=p['housing'];ratio=h['sharing_model']['whole_to_exclusive_design_ratio']
                bins=[{**b,'lower_m2':b['lower_m2']*ratio,'upper_m2':b['upper_m2']*ratio}
                      for b in h['area_reference']['predictive_area_bins']]
                allbins.append(bins)
                h['H6_predictive_support_bins']=bins
            lower=sum(min(b['lower_m2'] for b in bins) for bins in allbins)/n
            upper=sum(max(b['upper_m2'] for b in bins) for bins in allbins)/n
            feasible=lower<target<upper
            theta=0.0;reason='source_reference_track_no_mean_fitting'
            if MODEL['area_mode']=='tilt':
                if feasible:
                    def expected(t):return sum(tilted_distribution(bins,t)[1] for bins in allbins)/n
                    lo,hi=-1.0,1.0
                    for _ in range(40):
                        if expected(lo)<=target<=expected(hi):break
                        lo*=2;hi*=2
                    for _ in range(90):
                        mid=(lo+hi)/2
                        if expected(mid)<target:lo=mid
                        else:hi=mid
                    theta=(lo+hi)/2;reason='expected_mean_tilt_within_predeclared_reference_bin_support'
                else:reason='official_mean_outside_reference_support_convex_hull; retained_reference_track'
            esss=[];shares=[];means=[]
            strata=list(range(n));strata_rng=stage_rng(MODEL['seed'],'area_strata_'+province+'_'+str(v));strata_rng.shuffle(strata)
            for position,(p,bins) in enumerate(zip(selected,allbins)):
                h=p['housing'];prior=h['H6_building_area_m2']
                arng=stage_rng(MODEL['seed'],'area_final_'+p['slot_id'])
                quantile=(strata[position]+arng.random())/n if MODEL['area_draw_design']=='stratified' else None
                area,expected,ess,share,source_ess,source_share=tilted_area_draw(bins,theta,arng,quantile)
                h['area_before_policy_draw_m2']=prior
                h['H6_building_area_m2']=round(area,2)
                h['H6_evidence']=('modeled_empirical_endpoint_bounded_exponential_tilt_of_strict_H7_CHFS_area_reference_to_census_expected_group_mean'
                    if theta else 'modeled_strict_H7_CHFS_area_reference_with_empirical_endpoint_support_and_ESS_shrinkage')
                h['area_policy']={'mode':MODEL['area_mode'],'theta_per_m2':theta,'status':reason,
                    'expected_area_m2':expected,'bin_probability_ESS':ess,'maximum_bin_probability':share,
                    'posterior_source_ESS':source_ess,'posterior_maximum_source_weight':source_share,
                    'draw_design':MODEL['area_draw_design'],'group_size':n,'draw_dependence_group':province+'_vintage_'+str(v),
                    'support_never_expanded_for_mean_or_simulation':True,'calibrated_household_observation':False}
                esss.append(ess);shares.append(share);means.append(expected)
            actual=sum(p['housing']['H6_building_area_m2'] for p in selected)/n
            targets.append({'province':province,'vintage_category_index':v,'profiles':n,'reference_mean_H6_m2':target,
                'actual_mean_H6_m2':actual,'realized_mean_residual_m2':actual-target,'expected_model_mean_H6_m2':sum(means)/n,
                'expected_mean_residual_m2':sum(means)/n-target,'mean_constraint_realized':False,
                'area_mode':MODEL['area_mode'],'policy_status':reason,'theta_per_m2':theta,
                'reference_support_convex_hull_mean_m2':[lower,upper],'official_mean_strictly_inside_support_hull':feasible,
                'minimum_bin_probability_ESS':min(esss),'maximum_bin_probability':max(shares),
                'area_multiplicative_scaling_used':False,'new_support_added_to_fit_mean':False})
    return targets

def generate(args):
    global AREA_EDGES
    AREA_EDGES = list(map(float,args.area_bin_edges.split(',')))
    MODEL.update(seed=args.seed,shrinkage_tau=args.shrinkage_tau,age_bin_width=args.age_bin_width,
                 h7_prior_mass=args.h7_prior_mass,tail_prior_mass=args.tail_prior_mass,
                 max_building_storeys=args.max_building_storeys,area_mode=args.area_mode,
                 birthyear_upper_probability=args.birthyear_upper_probability,area_draw_design=args.area_draw_design,
                 minimum_source_area_per_room_m2=args.minimum_source_area_per_room_m2)
    FAMILY_REFERENCE_CACHE.clear();AREA_REFERENCE_CACHE.clear()
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
    area_pair_audit=[]
    for threshold in [.5,1.0,2.0]:
        known=[r for r in records if r['area_scope_supported'] and integer(r.get('room_count_h7_proxy')) is not None and integer(r['room_count_h7_proxy'])>0]
        suspect=[r for r in known if float(r['area_candidate_m2'])/integer(r['room_count_h7_proxy'])<threshold]
        area_pair_audit.append({'minimum_m2_per_proxy_room':threshold,'known_whole_scope_area_room_source_records':len(known),
            'quarantined_housing_reference_records':len(suspect),
            'quarantined_area_origin_counts':dict(collections.Counter(r['area_origin'] for r in suspect)),
            'quarantined_sharing_scope_counts':dict(collections.Counter(r['sharing_scope'] for r in suspect)),
            'quarantined_room_bin_counts':dict(collections.Counter(str(r['room_proxy_category']) for r in suspect)),
            'member_reference_records_removed':0,'population_slots_removed':0,'threshold_is_research_QC_design_not_official_floor':True})
    save(out/'AREA_PAIR_QC_REFERENCE_AUDIT.json',{'source_records':len(records),'design_policy':
        'withhold_severely_low_area_per_room_pairs_from_housing_references_pending_source_unit_scope_verification; not_a_population_exclusion',
        'active_minimum_source_area_per_room_m2':args.minimum_source_area_per_room_m2,'threshold_comparisons':area_pair_audit,
        'no_source_IDs_or_source_rows_exported':True,'original_source_files_modified':False})
    g1multi=[r for r in records if r['generation_count_proxy']==1 and r['co_resident_count']>1]
    save(out/'SOURCE_REFERENCE_AUDIT.json',{'source_records':len(records),
        'one_generation_multimember_source_households':len(g1multi),
        'one_generation_multimember_certain_under20_residents_birthyear_upper_proxy':sum(r['_birthyear_under20_certain_count'] for r in g1multi),
        'one_generation_multimember_boundary19_to20_residents':sum(r['_birthyear_boundary19_20_count'] for r in g1multi),
        'source_relation10':'siblings_not_other; source7777_is_other',
        'age_reference':'birth_year_only_age_interval_at_actual_visit_then_coarse_transport_to_role_reference_date',
        'original_IDs_or_source_rows_exported':False,'financial_complete_case_gate_used':False})
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
                   'H7_evidence': 'modeled_census_ordinary_conditional_integer_calibration_with_ESS_shrunk_CHFS_association_' + args.h7_mode if ordinary else 'not_applicable_to_nonordinary_census_frame',
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
                   'sleep_evidence': 'declared_individual_least_loaded_natural_room_assignment; sleeping_space_is_design_not_observed_bedroom_mapping',
                   'dwelling_type': None,
                   'household_storeys': None,
                   'dwelling_form_evidence':'unknown_not_identified_by_census_building_total_natural_storeys',
                   'household_internal_storeys_evidence':'unknown_attics_and_internal_levels_not_inferred_from_H8',
                   'engineering_geometry_options':['single_storey_apartment_context','single_storey_house_context','maisonette_context'],
                   'engineering_geometry_options_are_population_frequencies':False,
                   'geometry_or_template_feasibility_used_to_choose_household': False,
                   'physical_binding_status': 'pending_city_prototype_layout_and_supported_regime_validation'}
        profiles.append({'slot_id': slot['slot_id'], 'profile_version':VERSION,'generation_model_sha256':sha(__file__),
                         'field_provenance':{'family.members':'ESS_mixed_coarsened_CHFS_age_generation_count_reference_new_draw',
                            'family.relation_design':'occupied_generation_co_residence_only; detailed_kinship_unknown',
                            'housing.H5':'bounded_census_ordinary_binary_model',
                            'housing.H6':'source_reference_or_support_bounded_expected_mean_tilt_model; not_observed',
                            'housing.H7':'ordinary_conditional_census_integer_margins_with_modeled_N_association',
                            'housing.building_year_and_total_storeys':'transported_census_longform_bin_model',
                            'housing.dwelling_type_and_household_storeys':'unknown',
                            'housing.sleep_groups':'declared_individual_least_loaded_room_design; no_spouse_mapping',
                            'site.city':'unknown','economics_devices_activities_answers':'pending'},
                         'province': slot['province'], 'size_category': slot['size_category'],
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
                'age_cap': None, 'parent_generation_min_age_gap': None,
                'age_bin_width':args.age_bin_width,'shrinkage_tau':args.shrinkage_tau,'area_mode':args.area_mode,
                'birthyear_age_upper_probability':args.birthyear_upper_probability,
                'area_draw_design':args.area_draw_design,
                'area_support_policy':'strict_same_H7_bin_when_ordinary; per_bin_empirical_endpoints; degenerate_point_mass_retained',
                'minimum_source_area_per_room_m2_design':args.minimum_source_area_per_room_m2,
                'source_quality_floor_is_official':False,
                'max_building_storeys':args.max_building_storeys,
                'random_streams': 'sha256(seed|stage_or_slot); family stream independent of every housing factor',
                'room_reference_smoothing_census_mass': args.h7_prior_mass, 'tail_geometric_prior_mass': args.tail_prior_mass,
                'member_financial_complete_case_gate':False,
                'same_generation_age_gap_limit':None,'mandatory_spouse_opposite_sex':False,
                'dwelling_form_population_assignment':False,
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
                                           'H7_by_size_association': args.h7_mode,
                                           'H6_population_mean_exactly_matched':False,
                                           'H6_area_mode':args.area_mode})
    save(out / 'SOURCE_INFLUENCE.json', influence)
    (out / 'code').mkdir()
    for name in ['generate_empirical_support_candidates.py', 'verify_empirical_support_candidates.py']:
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
    parser.add_argument('--shrinkage-tau',type=float,default=20.0)
    parser.add_argument('--age-bin-width',type=int,choices=[5,10],default=5)
    parser.add_argument('--h7-prior-mass',type=float,default=.25)
    parser.add_argument('--tail-prior-mass',type=float,default=.25)
    parser.add_argument('--area-mode',choices=['reference','tilt'],default='reference')
    parser.add_argument('--area-bin-edges',default='1,20,40,60,80,100,120,160,200,250,350,500,750,1000,1500,2000')
    parser.add_argument('--max-building-storeys',type=int,default=50)
    parser.add_argument('--birthyear-upper-probability',type=float,default=.5)
    parser.add_argument('--area-draw-design',choices=['stratified','iid'],default='stratified')
    parser.add_argument('--minimum-source-area-per-room-m2',type=float,default=1.0)
    args = parser.parse_args()
    if args.max_household_tail < 10 or args.max_room_tail < 5:
        parser.error('tail maximum below topcode threshold')
    if not math.isfinite(args.shrinkage_tau) or args.shrinkage_tau<=0 or not 0<=args.h7_prior_mass<=1 or not 0<=args.tail_prior_mass<=1 or not 0<=args.birthyear_upper_probability<=1 or args.max_building_storeys<34 or not math.isfinite(args.minimum_source_area_per_room_m2) or args.minimum_source_area_per_room_m2<0:
        parser.error('invalid_declared_design_parameter')
    edges=list(map(float,args.area_bin_edges.split(',')))
    if len(edges)<2 or not all(math.isfinite(x) and x>0 for x in edges) or any(a>=b for a,b in zip(edges,edges[1:])):
        parser.error('area_bin_edges_must_be_positive_finite_and_increasing')
    generate(args)
