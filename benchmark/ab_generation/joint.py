"""Finite interaction covering: same-family jobs and unrestricted joint size.

Small spaces are exhaustive. Larger spaces cover exact two-unit dose tuples and
declared presence compositions, with explicit budget gaps. No B outcome is read.
"""
import itertools
import math
from collections import Counter
from .common import digest
from .model import apply, control_issues, program_issues, request_issues
from .opportunity import joint_evidence
from .power import site_capacity


def unit_key(row):
    f = row['factors']
    if row['family'] in ('washer', 'dishwasher', 'ev'):
        return (row['family'], row['asset_id'], f['need_id'])
    return (row['family'], row['asset_id'], f['event_id'], f['thermal_axis'])


def build_joint(context, children):
    children = sorted(children, key=lambda r: r['id'])
    patches = [p for c in children for p in c['patches']]
    plan = apply(context['A'], patches)
    issues = set(request_issues(context, plan)) | set(control_issues(context, plan))
    for c in children:
        if c['family'] in ('washer', 'dishwasher'):
            issues.update(program_issues(context, plan, c['factors']['need_id']))
        elif c['family'] == 'ev':
            issues.update(c['static_issues'])
            # Site bounds must be recomputed jointly, not inherited from a single.
            issues.difference_update(('SITE_KNOWN_PROFILE_EXCEEDS_SUPPLY', 'SITE_CAPACITY_NOT_CERTIFIED'))
    power = site_capacity(context, plan); issues.update(power['issues'])
    result = {'candidate_ids': [c['id'] for c in children], 'patches': patches,
        'id': digest({'binding': context['reference']['binding'], 'children': [c['id'] for c in children]})[:24],
        'static_issues': sorted(issues), 'actual_outcomes': None,
        'opportunity': joint_evidence(children), 'request_units': [list(unit_key(c)) for c in children],
        'family_composition': sorted(c['family'] for c in children),
        'status': 'joint_request_failure_retained' if issues else 'joint_static_check_passed'}
    if context.get('electrical'):
        result['power_certificate'] = power
    return result


def search(context, candidates, rules):
    groups = {}
    for c in candidates:
        groups.setdefault(unit_key(c), []).append(c)
    keys = sorted(groups)
    domains = {k: sorted(v, key=lambda c: (bool(c['static_issues']), c['opportunity']['status'] != 'supported', c['id']))
               for k, v in groups.items()}
    n = len(keys); budget = rules['joint_candidate_budget']; rows, seen = [], set()
    total = math.prod(len(v) + 1 for v in domains.values()) - 1 - sum(map(len, domains.values()))
    cache = {}
    pairs_required = sum(len(domains[a]) * len(domains[b]) for a, b in itertools.combinations(keys, 2))
    covered_pairs = set(); compositions = set(); sizes = set(); feasible_compositions = set()
    def add(children):
        ident = tuple(sorted(c['id'] for c in children))
        if ident in seen or len(rows) >= budget:
            return cache.get(ident)
        seen.add(ident); row = build_joint(context, children); rows.append(row)
        cache[ident] = row
        comp = tuple(sorted({c['family'] for c in children})); compositions.add(comp); sizes.add(len(children))
        if not row['static_issues']:
            feasible_compositions.add(comp)
        covered_pairs.update(tuple(sorted((a['id'], b['id']))) for a, b in itertools.combinations(children, 2))
        return row
    exhaustive = total <= min(budget, rules['joint_exact_product_limit'])
    if exhaustive:
        for values in itertools.product(*[[None] + domains[k] for k in keys]):
            children = [v for v in values if v is not None]
            if len(children) >= 2:
                add(children)
    else:
        # All cardinalities get a turn before the potentially large pair product.
        # Each same-family dated job is independent; different variants of one
        # job are alternatives, never two patches to the same task identities.
        if n <= 12:
            subsets = [s for size in range(3, n + 1) for s in itertools.combinations(keys, size)]
        else:
            families = sorted({k[0] for k in keys})
            reps = {f: [k for k in keys if k[0] == f] for f in families}
            subsets = [tuple(reps[f][0] for f in fs) for size in range(3, len(families) + 1)
                       for fs in itertools.combinations(families, size)]
            subsets += [tuple(keys[:size]) for size in range(3, n + 1)]
            subsets += [tuple(ks) for ks in reps.values() if len(ks) >= 3]
        # Presence witnesses are fixed before any feasibility or physics result.
        for subset in sorted(set(subsets), key=lambda s: (-len(s), s)):
            add([domains[k][0] for k in subset])
        pair_iterators = [iter(itertools.product(domains[a], domains[b])) for a, b in itertools.combinations(keys, 2)]
        live = list(pair_iterators)
        reserve = min(budget // 4, len(subsets) * max(0, rules['joint_trials_per_subset'] - 1))
        while live and len(rows) < budget - reserve:
            more = []
            for iterator in live:
                children = next(iterator, None)
                if children is not None:
                    add(children); more.append(iterator)
                if len(rows) >= budget - reserve:
                    break
            live = more
        for trial in range(1, rules['joint_trials_per_subset']):
            for subset in sorted(set(subsets), key=lambda s: (-len(s), s)):
                add([domains[k][(trial + i * (trial // len(domains[k])) ) % len(domains[k])]
                     for i, k in enumerate(subset)])
        # Finish any outstanding two-way tuples if witness dedup left room.
        for iterator in pair_iterators:
            for children in iterator:
                if len(rows) >= budget:
                    break
                add(children)
            if len(rows) >= budget:
                break
    families = sorted({k[0] for k in keys})
    required_compositions = {tuple(fs) for size in range(2, len(families) + 1) for fs in itertools.combinations(families, size)}
    # Bounded CSP beam completion supplements the fixed covering design when a
    # composition has no static-valid witness yet. Score uses constraints only;
    # every evaluated complete request (including invalid prefixes >=2 units)
    # remains in the catalogue. This never reads native B or acceptance.
    if not exhaustive:
        for composition in sorted(required_compositions - feasible_compositions, key=lambda c: (-len(c), c)):
            subset = [min((k for k in keys if k[0] == f), key=lambda k: (bool(domains[k][0]['static_issues']), k)) for f in composition]
            beam = [[]]
            for k in subset:
                expanded = []
                for prefix in beam:
                    for c in domains[k]:
                        children = prefix + [c]
                        row = add(children) if len(children) >= 2 else c
                        if row is not None:
                            expanded.append((len(row['static_issues']), tuple(r['id'] for r in children), children))
                beam = [r[2] for r in sorted(expanded, key=lambda r: r[:2])[:rules['joint_beam_width']]]
                if not beam or len(rows) >= budget:
                    break
    actual_families = {c['id']: c['family'] for c in candidates}
    same_family_required = sum(len(domains[a]) * len(domains[b]) for a, b in itertools.combinations(keys, 2) if a[0] == b[0])
    same_family_covered = sum(actual_families[a] == actual_families[b] for a, b in covered_pairs)
    return rows, {'schema': 'eb.joint_search_coverage.v1', 'method': 'exhaustive' if exhaustive else 'two_unit_dose_cover_plus_presence_compositions',
        'units': [list(k) for k in keys], 'unit_count': n, 'finite_space_size': total,
        'candidate_budget': budget, 'generated': len(rows), 'pair_dose_required': pairs_required,
        'pair_dose_covered': len(covered_pairs), 'pair_dose_complete': len(covered_pairs) == pairs_required,
        'same_family_pair_dose_required': same_family_required, 'same_family_pair_dose_covered': same_family_covered,
        'request_cardinalities_required': list(range(2, n + 1)), 'request_cardinalities_observed': sorted(sizes),
        'family_compositions_required': [list(c) for c in sorted(required_compositions)],
        'family_compositions_observed': [list(c) for c in sorted(compositions)],
        'family_compositions_with_static_valid_witness': [list(c) for c in sorted(feasible_compositions)],
        'missing_family_compositions': [list(c) for c in sorted(required_compositions - compositions)],
        'static_failure_counts': dict(Counter(i for r in rows for i in r['static_issues'])),
        'all_generated_invalid_requests_retained': True, 'B_results_used': False,
        'all_higher_order_dose_combinations_exhausted': exhaustive,
        'coverage_passed': len(covered_pairs) == pairs_required and not required_compositions - compositions and sizes == set(range(2, n + 1)),
        'scope': 'finite_declared_atomic_doses;coverage_is_not_global_feasibility_or_population_frequency'}
