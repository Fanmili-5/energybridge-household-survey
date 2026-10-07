#!/usr/bin/env python3
"""Calibrated city long-form source/facility reference and candidate assignments.

Only source x both-facilities is observed jointly. Other cells use a declared
maximum-entropy completion; analytic identification bounds are also exported.
No kitchen/water service report becomes ownership, permission or physical power.
"""
import collections
import hashlib
import json
import math
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROUTE = HERE.parent
H = ROUTE.parent
SRC = H / 'evidence_contract_20261001/CITY_AUTHORITY_CONSTRAINTS_V2.json'
LABELS = ['public_rental', 'other_rental', 'new_commercial_purchase',
          'secondhand_purchase', 'former_public_purchase', 'affordable_purchase',
          'self_built', 'inherited_or_gift', 'other_source']
STATES = ['both_kitchen_toilet', 'kitchen_only', 'toilet_only', 'neither']
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
from generate_population import fit_transport


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def rng(s):
    return random.Random(int(hashlib.sha256(('EB_FACILITIES_V4_20261003|' + s).encode()).hexdigest(), 16))


def counts(n, probs):
    x = [n * p for p in probs]
    out = [math.floor(z) for z in x]
    for i in sorted(range(len(x)), key=lambda i: (-(x[i] - out[i]), i))[:n - sum(out)]:
        out[i] += 1
    return out


def save(p, x):
    p.write_text(json.dumps(x, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def main():
    output = ROUTE / 'facilities1000_v2'
    if output.exists():
        raise ValueError('new_output_required')
    output.mkdir()
    a = json.loads(SRC.read_text())['tables']
    references = {}
    for prov in a['B0903a']['rows']:
        f = a['B0903a']['rows'][prov]['counts_or_aggregates']
        s = a['B0904a']['rows'][prov]['counts_or_aggregates']
        b = a['B0906a']['rows'][prov]['counts_or_aggregates']
        n = f[0]
        assert n == s[0] and sum(s[1:]) == n and sum(b[1:]) == b[0]
        # Explicit zero-based indices of counts_or_aggregates, checked against
        # the published multi-row XLS headers in the locked source artifact.
        kitchen = f[10] + f[11]
        toilet = sum(f[13:17])
        both = b[0]
        state_total = [both, kitchen - both, toilet - both, n - kitchen - toilet + both]
        assert min(state_total) >= 0 and sum(state_total) == n
        remaining = n - both
        residual_share = [z / remaining for z in state_total[1:]]
        cells = []
        for label, ns, nb in zip(LABELS, s[1:], b[1:]):
            assert 0 <= nb <= ns
            r = ns - nb
            # With only margins, every feasible completion has these exact
            # source-specific kitchen/toilet bounds. No normal CI is implied.
            def bound(global_count):
                low = max(0, global_count - (remaining - r))
                high = min(r, global_count)
                return [(nb + low) / ns, (nb + high) / ns] if ns else None
            cells.append({'housing_source': label, 'source_count': ns, 'both_count': nb,
                          'maximum_entropy_cell_counts': [nb, *[r * p for p in residual_share]],
                          'kitchen_presence_probability_identification_bounds': bound(state_total[1]),
                          'toilet_presence_probability_identification_bounds': bound(state_total[2]),
                          'completion_is_observed_joint': False})
        references[prov] = {'ordinary_city_longform_households': n,
                            'kitchen_toilet_state_counts': dict(zip(STATES, state_total)),
                            'source_by_facility_state': cells,
                            'self_installed_water_heater_probability': f[19] / n,
                            'bathing_facility_counts': dict(zip(['central_hot_water', 'self_installed_water_heater', 'other', 'none'], f[18:22])),
                            'cooking_fuel_counts': dict(zip(['gas', 'electricity', 'coal', 'biomass', 'other'], f[3:8])),
                            'water_pipe_counts': dict(zip(['present', 'absent'], f[8:10])),
                            'kitchen_use_counts': dict(zip(['private', 'shared', 'none'], f[10:13])),
                            'toilet_type_counts': dict(zip(['flush_sanitary', 'flush_other', 'dry_sanitary', 'dry_other', 'none'], f[13:18]))}
    base = ROUTE / 'population1000/FAMILY_HOUSING_CANDIDATES.json'
    body = json.loads(base.read_text())
    groups = collections.defaultdict(list)
    for p in body['profiles']:
        if p['housing']['H5_is_ordinary_model_assigned']:
            groups[p['province']].append(p)
        else:
            p['housing']['facilities'] = {'status': 'unknown_not_in_ordinary_longform_frame',
                                          'service_context': 'requires_separate_shared_or_external_service_model'}
    # Joint integer transport avoids bias from rounding many tiny source cells
    # separately (which previously erased rare missing-facility states).
    provinces = list(groups)
    state_probs = [[references[p]['kitchen_toilet_state_counts'][s] / references[p]['ordinary_city_longform_households'] for s in STATES] for p in provinces]
    row_totals = [len(groups[p]) for p in provinces]
    overall_expected = [sum(n * q[j] for n, q in zip(row_totals, state_probs)) for j in range(4)]
    national_target = counts(sum(row_totals), [x / sum(row_totals) for x in overall_expected])
    province_states, _ = fit_transport(row_totals, national_target, state_probs)
    audits = []
    for prov, state_target in zip(provinces, province_states):
        ps = groups[prov]
        ref = references[prov]
        cells = ref['source_by_facility_state']
        src_prob = [x['source_count'] / ref['ordinary_city_longform_households'] for x in cells]
        ns = counts(len(ps), src_prob)
        conditional = [[x / c['source_count'] for x in c['maximum_entropy_cell_counts']] if c['source_count'] else [1, 0, 0, 0] for c in cells]
        joint, _ = fit_transport(ns, state_target, conditional)
        rr = rng(prov)
        rr.shuffle(ps)
        cursor = 0
        expected = collections.Counter()
        realized = collections.Counter()
        for c, nc, psrc, joint_row in zip(cells, ns, src_prob, joint):
            probabilities = [x / c['source_count'] for x in c['maximum_entropy_cell_counts']] if c['source_count'] else [1, 0, 0, 0]
            states = [st for st, count in zip(STATES, joint_row) for _ in range(count)]
            rr.shuffle(states)
            for st, profile in zip(states, ps[cursor:cursor + nc]):
                k = st in ['both_kitchen_toilet', 'kitchen_only']
                t = st in ['both_kitchen_toilet', 'toilet_only']
                facilities = {'status': 'census_constrained_synthetic_not_observed',
                    'housing_source': c['housing_source'], 'kitchen_present_any': k,
                    'toilet_present_any': t, 'kitchen_toilet_state': st,
                    'both_given_source_is_observed_reference': True,
                    'other_dependency_model': 'maximum_entropy_conditional_on_not_both; unidentified_see_bounds',
                    'kitchen_private_or_shared': None, 'water_heater_asset_class': None,
                    'operator_permission': None, 'calibrated_electric_power': None,
                    'bathing_and_fuel': 'source_population_constraints_available_assignment_pending',
                    'engineering_rule': 'do_not_create_private_kitchen_toilet_when_absent; shared/external_service_needs_explicit_context'}
                profile['housing']['facilities'] = facilities
                realized[(c['housing_source'], st)] += 1
            cursor += nc
            for st, prob in zip(STATES, probabilities):
                expected[(c['housing_source'], st)] = len(ps) * psrc * prob
        audits.append({'province': prov, 'ordinary_candidates': len(ps),
                       'cells': [{'housing_source': key[0], 'state': key[1],
                                  'expected_count': val, 'realized_count': realized[key],
                                  'integer_residual': realized[key] - val} for key, val in expected.items()],
                       'transport_note': 'city ordinary longform margins transported to eligible ordinary roles; under20-singleton associations unidentified'})
    body['schema'] = 'eb.population_housing_facilities_candidate.v4'
    body['evidence_scope'] = '1000 census-constrained candidates; full joint representativeness, detailed kinship and actor readiness pending'
    body['family_housing_input_sha256'] = sha(base)
    save(output / 'FAMILY_HOUSING_FACILITIES1000.json', body)
    save(output / 'OFFICIAL_FACILITIES_REFERENCE.json', {'schema': 'eb.census_city_facilities_reference.v1', 'source_sha256': sha(SRC),
        'tables': {k: {'url': a[k]['url'], 'sha256': a[k]['sha256'], 'header_rows': a[k]['header_rows']} for k in ['B0903a', 'B0904a', 'B0906a']},
        'references': references, 'bounded_dependencies_not_confidence_intervals': True})
    save(output / 'ASSIGNMENT_AUDIT.json', {'source_reference_sha256': sha(output / 'OFFICIAL_FACILITIES_REFERENCE.json'),
        'scope': 'observed marginal/joint aggregate constraints plus explicitly modeled completion',
        'ordinary_candidates': sum(len(x) for x in groups.values()), 'audits': audits,
        'national_state_expected': dict(zip(STATES, overall_expected)),
        'national_state_integer_target': dict(zip(STATES, national_target)),
        'integerization': 'joint province-state transport then source-state transport; no independent tiny-cell rounding',
        'devices_owned_assigned': 0, 'actor_ready': 0, 'collection_release': False, 'training_release': False})
    print(json.dumps({'candidates': len(body['profiles']), 'ordinary': sum(len(x) for x in groups.values()), 'output': str(output)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
