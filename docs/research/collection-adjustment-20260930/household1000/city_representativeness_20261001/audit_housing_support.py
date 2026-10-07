#!/usr/bin/env python3
"""Read-only support diagnosis; no new household, IDF, A/B, or engine run.

The 12 deterministic cases are a mechanism probe, not a population sample.
CHNS frequencies remain local unweighted frequencies, not city census weights.
Only aggregate CHNS statistics and synthetic role IDs are written.
"""
from collections import Counter, defaultdict
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def read(p):
    return json.loads(Path(p).read_text())


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def module(name, p):
    spec = importlib.util.spec_from_file_location(name, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def group(n):
    return str(n) if n < 5 else '5+'


def cell(p):
    return f"{p['family_size']}x{p['generation_category']}"


def stats(pool):
    # tuple: usable area, weak rooms, source residents, frequency, gross area.
    mass = sum(x[3] for x in pool)
    if not mass:
        return {'source_row_mass': 0, 'unique_tuples': 0, 'mean_gross_m2': None}
    return {'source_row_mass': mass, 'unique_tuples': len(pool),
            'mean_gross_m2': round(sum(x[3]*x[4] for x in pool)/mass, 3),
            'gross_le40_fraction': round(sum(x[3] for x in pool if x[4] <= 40)/mass, 6),
            'gross_gt500_fraction': round(sum(x[3] for x in pool if x[4] > 500)/mass, 6),
            'source_exact999_fraction': round(sum(x[3] for x in pool if x[0] == 999)/mass, 6)}


def main():
    started = time.monotonic()
    lock = read(ROOT/'INPUT_LOCK.json')['files']
    labels = ['CHNS_probe_code', 'CHNS_asset', 'CHNS_roster', 'geometry_code',
              'layout_config', 'province_reference', 'city_reference']
    for label in labels:
        assert sha(lock[label]['path']) == lock[label]['sha256'], label
    probe = module('support_chns', lock['CHNS_probe_code']['path'])
    geom = module('support_geometry', lock['geometry_code']['path'])
    conf = read(lock['layout_config']['path'])
    import pandas as pd
    usable, source_audit = probe.prepare(pd.read_sas(lock['CHNS_asset']['path']),
                                         pd.read_sas(lock['CHNS_roster']['path']))
    pools = defaultdict(Counter)
    for r in usable.itertuples(index=False):
        pools[group(int(r.resident_count))][(float(r.L16), int(r.L17), int(r.resident_count))] += 1
    roles = []
    role_files = {}
    for path in sorted((ROOT/'candidate_v2/roles').glob('*.json')):
        if int(path.stem.split('-')[1]) > 300:
            roles.append(read(path))
            role_files[path.name] = sha(path)
    assert len(roles) == 700
    target = read(HERE/'CITY_TARGET_AUDIT.json')
    target_by_cell = {r['size_generation']: r['joint_target_1000'] for r in target['joint_size_generation']}
    changed = [r for r in roles if r['profile']['dwelling_interface']['requested_H7_before_capacity_check'] !=
               r['profile']['dwelling_interface']['room_count_design_minimum']]
    changed_topology = []
    for r in changed:
        p = r['profile']; h = p['dwelling_interface']['requested_H7_before_capacity_check']
        # Existence only: huge area removes area limits, not structural group rules.
        exists = next(geom.all_sleep_topologies(p, h), None) is not None
        changed_topology.append({'role_id': r['role_id'], 'cell': cell(p), 'requested_H7': h,
                                 'selected_H7': p['dwelling_interface']['room_count_design_minimum'],
                                 'any_sleep_partition_at_fixed_H7_under_current_template': exists})
    selected = []
    for k in sorted(target_by_cell, key=lambda k: (-target_by_cell[k], k))[:8]:
        matches = [r for r in roles if cell(r['profile']) == k]
        if matches:
            selected.append(matches[0])
    for r in changed:
        if r not in selected:
            selected.append(r)
        if len(selected) == 12:
            break
    cases = []
    for row in selected:
        p = row['profile']; n = p['family_size']
        h = p['dwelling_interface']['requested_H7_before_capacity_check']
        full = [(a, l, sn, f, math.floor(a/sn*n*1.33+.5)) for (a,l,sn), f in pools[group(n)].items()]
        weak = [x for x in full if x[1] >= h]
        accepted = []; rejection = Counter(); cache = {}
        for x in weak:
            gross = x[4]
            if gross not in cache:
                try:
                    layout, error = geom.plan(p, gross, h, conf, {'x+':1, 'x-':1, 'y+':1, 'y-':1})
                    errors = geom.full_layout_errors(p, layout) if layout else [error]
                except Exception as exc:
                    errors = [type(exc).__name__]
                cache[gross] = errors
            if not cache[gross]:
                accepted.append(x)
            else:
                for error in set(cache[gross]):
                    rejection[error] += x[3]
        cases.append({'role_id': row['role_id'], 'cell': cell(p), 'province':p['province'],
            'requested_H7_fixed': h, 'prior_selected_H7': p['dwelling_interface']['room_count_design_minimum'],
            'row_frequency_unfiltered': stats(full), 'row_frequency_weak_room_only': stats(weak),
            'deduplicated_weak_room_only': stats([(*x[:3],1,x[4]) for x in weak]),
            'row_frequency_fixed_H7_geometry': stats(accepted),
            'deduplicated_fixed_H7_geometry': stats([(*x[:3],1,x[4]) for x in accepted]),
            'row_frequency_fixed_H7_geometry_exclude999_sensitivity': stats([x for x in accepted if x[0]!=999]),
            'rejection_reason_source_row_mass': dict(rejection),
            'geometry_checks_unique_gross_values': len(cache),
            'all_layouts_unbound_prospective_four_exterior_faces': True})
    citydoc = read(lock['city_reference']['path'])
    cities = defaultdict(set)
    for a in citydoc['assignments']:
        cities[a['province']].add(a['administrative_city_code'])
    provinces = []
    for p in target['province_quotas']:
        name = p['province']; rows = [r for r in roles if r['profile']['province']==name]
        provinces.append({'province': name, 'target_1000':p['quota_1000'], 'retained_300':p['old300'],
            'needed_from_joint1000_minus_old300':p['quota_1000']-p['old300'],
            'cached_city_count': len(cities[name]), 'new_candidate_count':len(rows),
            'new_room_national_fallback_count': sum(r['profile']['dwelling_interface']['room_reference']==
                'national_generation_room_conditional_fallback' for r in rows),
            'new_actual_IDF_bindings':sum(r['profile']['dwelling_interface']['source_specific_exterior_and_IDF'] is not None for r in rows)})
    total = target['total_city_households']; eligible = target['eligible_city_households']
    removed = total-eligible
    ordinary = sum(p['ordinary_dwelling_family_households_1_12a'] for p in target['province_quotas'])
    # Inclusion-exclusion, with E and O both subsets of the same city household set.
    overlap_lo, overlap_hi = max(0, ordinary-removed), min(ordinary, eligible)
    bounds = {'all_city_family_households': total, 'eligible_city_family_households': eligible,
              'ordinary_dwelling_city_family_households': ordinary,
              'ordinary_and_eligible_overlap_count_bounds': [overlap_lo,overlap_hi],
              'nonordinary_expected_mass_per1000_bounds': [round(1000*(eligible-overlap_hi)/eligible,3),
                                                         round(1000*(eligible-overlap_lo)/eligible,3)],
              'assumption': 'ordinary and eligibility are subsets of the same 2020 city family household frame',
              'not_equivalent': 'nonordinary is not identical to unsimulatable; ordinary is not proof of model coverage'}
    report = {'batch_id':'CITY_HOUSING_SUPPORT_20261001_V1',
        'scope':'city family household targets only; town/rural excluded',
        'population_sample':False, 'bounded_case_selection':'first role in 8 largest target size-generation cells, then first changed-H7 roles until 12',
        'source_audit':source_audit, 'new_candidate_metadata_audited':700,
        'H7_changed_count':len(changed), 'H7_changed_without_any_current_template_sleep_partition':
            sum(not r['any_sleep_partition_at_fixed_H7_under_current_template'] for r in changed_topology),
        'changed_H7_topology_audit':changed_topology, 'cases':cases,
        'source_frequency_usable_means_by_size':[{'size_group':k, 'source_rows':sum(pool.values()),
            'unique_tuples':len(pool), 'row_frequency_mean_usable_m2':round(sum(a*f for (a,l,n),f in pool.items())/sum(pool.values()),3),
            'deduplicated_mean_usable_m2':round(sum(a for a,l,n in pool)/len(pool),3)} for k,pool in sorted(pools.items())],
        'province_support':provinces, 'denominator_overlap_bounds':bounds,
        'outputs_are':'support probabilities and aggregate diagnostics; no assignments or new profiles',
        'limitations':['CHNS urban local sample is not census city household frame',
            'L17 is weak room compatibility, not H7 equivalence', '1.33 area conversion is a design assumption',
            'geometry feasible is not observed livability or bound IDF', 'raw L16=999 unresolved; removal is sensitivity only',
            'national fallback counts diagnose truncated cache not absence of official provincial data'],
        'sources':{k:lock[k] for k in labels}, 'target_audit_sha256':sha(HERE/'CITY_TARGET_AUDIT.json'),
        'candidate_role_hashes_sha256':hashlib.sha256(json.dumps(role_files,sort_keys=True).encode()).hexdigest(),
        'code_sha256':sha(__file__), 'generated_profiles':0, 'engine_calls':0,
        'collection_release':False, 'elapsed_s':round(time.monotonic()-started,3)}
    out = HERE/'HOUSING_SUPPORT_AUDIT.json'
    with out.open('x') as f:
        json.dump(report,f,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False); f.write('\n')
    print(json.dumps({k:report[k] for k in ['batch_id','H7_changed_count',
        'H7_changed_without_any_current_template_sleep_partition','denominator_overlap_bounds','elapsed_s']},ensure_ascii=False))


if __name__ == '__main__':
    main()
