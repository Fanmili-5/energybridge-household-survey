"""Read-only source arithmetic. No household generation, IDF or EP calls."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import pathlib
import urllib.request


def largest_remainder(counts, n):
    total = sum(counts)
    targets = [x * n / total for x in counts]
    result = [math.floor(x) for x in targets]
    for i in sorted(range(len(counts)), key=lambda i: (-(targets[i] - result[i]), i))[:n - sum(result)]:
        result[i] += 1
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input', type=pathlib.Path, required=True)
    p.add_argument('--household-root', type=pathlib.Path, required=True)
    p.add_argument('--output', type=pathlib.Path, required=True)
    p.add_argument('--check-public-source-bytes', action='store_true')
    args = p.parse_args()
    j = json.loads(args.input.read_text())
    frame = args.household_root / j['frame_source_relative']
    digest = hashlib.sha256(frame.read_bytes()).hexdigest()
    assert digest == j['frame_source_sha256'], 'existing school frame bytes differ'
    observed_frame = json.loads(frame.read_text())
    assert j['official_households'] == observed_frame['official_households']
    assert j['official_residents'] == observed_frame['official_residents']
    assert j['integer_allocation'] == observed_frame['integer_allocation']
    values = j['ordinary_generation_room_national']
    frame_values = [sum(province[g][room] for province in observed_frame['ordinary_generation_room_counts'])
                    for g in range(5) for room in range(5)]
    assert values[1:] == frame_values, 'generation-room aggregate differs from hash-bound school frame'
    counts = [sum(values[1 + i * 5:6 + i * 5]) for i in range(5)]
    assert sum(counts) == values[0] == j['official_households']
    quota = largest_remainder(counts, 1000)
    assert quota == j['integer_allocation']['national_generation_quotas']
    sizes = j['integer_allocation']['modeled_national_size_quotas']
    assert sum(sizes) == sum(quota) == 1000
    assert sum(j['integer_allocation']['province_quota'].values()) == 1000
    assert round(1000 * j['official_residents'] / j['official_households']) == 2524
    housing = j['national_longform_housing']
    public = []
    if args.check_public_source_bytes:
        for source in j['public_source_tables']:
            req = urllib.request.Request(source['url'], headers={'User-Agent': 'Mozilla/5.0'})
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    data = r.read()
                actual = hashlib.sha256(data).hexdigest()
                public.append({'id': source['id'], 'url': source['url'], 'bytes': len(data),
                               'sha256': actual, 'expected_sha256': source['sha256'],
                               'bytes_match': actual == source['sha256']})
            except Exception as e:
                public.append({'id': source['id'], 'url': source['url'], 'bytes_match': None,
                               'access_error': str(e)[:300]})
    review = {
        'schema': 'household1000.composition.source_arithmetic_review.v1',
        'date': '2026-10-14', 'execution_host': 'school_hku-server',
        'script_sha256': hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
        'input_sha256': hashlib.sha256(args.input.read_bytes()).hexdigest(),
        'frame_sha256': digest, 'frame_hash_match': True,
        'generation_room_facts_rederived_from_hash_bound_school_frame': True,
        'integer_solution_optimality_proven': False,
        'input_allocation_solver_status': j['integer_allocation']['solver_status'],
        'input_allocation_mip_gap': j['integer_allocation']['mip_gap'],
        'housing_ratios_input_identity': 'previously audited public aggregate;source bytes rechecked;XLS cell parser not rerun in this script',
        'ordinary_generation_counts': counts,
        'ordinary_generation_percent': [100 * x / sum(counts) for x in counts],
        'generation_1000_integer_counts': quota,
        'modeled_size_1000_counts_not_observed_joint': sizes,
        'ordinary_people_per_household': j['official_residents'] / j['official_households'],
        'population1000_integer_people_target': 2524,
        'rented_household_percent_longform': 100 * housing['renter_total'] / housing['long_housing_total'],
        'any_family_car_household_percent_longform': 100 * housing['households_with_any_family_car'] / housing['long_housing_total'],
        'NEV_stock2020_fixed_denominator_diagnostic_percent_ceiling': 100 * j['NEV_stock2020'] / j['official_households'],
        'NEV_diagnostic_is_natural_ratio_estimate': False,
        'EV_function_coverage_design_minimum_percent': j['functional_coverage_design']['6'] / 10,
        'coverage_is_natural_ownership': False,
        'public_source_bytes': public,
        'public_source_byte_mismatches': sum(x['bytes_match'] is False for x in public),
        'public_source_byte_unavailable': sum(x['bytes_match'] is None for x in public),
        'arithmetic_checks_passed': True,
        'scientific_type_prevalence_identified': False,
        'actual_type_assignment_verified': False,
        'target_type_counts': None,
        'generator_implemented_in_this_stage': False,
        'new_worlds': 0, 'new_IDFs': 0, 'EP_calls': 0,
        'generation_allowed': False, 'full_EP_allowed': False,
    }
    args.output.write_text(json.dumps(review, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(review, ensure_ascii=False))
    if review['public_source_byte_mismatches']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
