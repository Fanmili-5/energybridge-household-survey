#!/usr/bin/env python3
"""Read-only EB-six-type admission audit, run on school Linux.

This program does not label existing unknown preferences, generate households,
change demographics, run EnergyPlus, or manufacture human responses.
"""
import argparse
from collections import Counter, deque
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import sys

STAGE = Path(__file__).resolve().parents[1]
TYPES = tuple('ABCDEF')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True,
                               indent=2, allow_nan=False) + '\n')
    temp.replace(path)


def quota(counts, n):
    """Largest remainder, with stable A..F tie order and exact arithmetic."""
    if tuple(counts) != TYPES or any(type(v) is not int or v <= 0 for v in counts.values()):
        raise ValueError('Six positive integer EB counts required')
    if type(n) is not int or n <= 0:
        raise ValueError('Positive integer cohort size required')
    total = sum(counts.values())
    raw = {k: Fraction(n * counts[k], total) for k in TYPES}
    out = {k: raw[k].numerator // raw[k].denominator for k in TYPES}
    order = sorted(TYPES, key=lambda k: (-raw[k] + out[k], k))
    for k in order[:n - sum(out.values())]:
        out[k] += 1
    return out


def eligibility(world):
    """Proposed strict household-policy-holder adaptation, not observed types.

    Each type needs an adult resident to hold the given energy policy. Commute
    eligibility preserves unknown employment and prohibits filling a no-work
    source with an invented current job. Age cutoffs are declared admission
    choices, not empirical retirement or preference thresholds.
    """
    members = world['members']
    adults = [m for m in members if m['age_years'] >= 18]
    commuters = [m for m in members if 18 <= m['age_years'] < 65
                 and m['employment_status'] in ('has_work', 'unknown')]
    irregular = [m for m in members if 18 <= m['age_years'] < 75]
    carers = [m for m in members if 18 <= m['age_years'] < 75
              and any(t['member_id'] != m['member_id']
                      and (t['age_years'] < 6 or t['age_years'] >= 65)
                      for t in members)]
    has_ev = any('ev' in a['types'] for a in world['parameter_pack']['devices'])
    return {'A': bool(commuters), 'B': bool(adults), 'C': bool(irregular),
            'D': bool(commuters), 'E': bool(carers), 'F': bool(commuters) and has_ev}


def capacity_match(rows, targets):
    """Integral max flow: all six quotas must be jointly feasible.

    A capacity-only proof cannot identify preferences or authorize production.
    """
    graph = {}
    residual = {}
    original_edges = []

    def edge(a, b, capacity):
        graph.setdefault(a, []).append(b)
        graph.setdefault(b, []).append(a)
        residual[a, b] = capacity
        residual[b, a] = 0
        original_edges.append((a, b, capacity))

    source, sink = 'source', 'sink'
    for k in TYPES:
        edge(source, 'type:' + k, targets[k])
    for i, row in enumerate(rows):
        node = 'household:' + str(i)
        edge(node, sink, 1)
        for k in TYPES:
            if row[k]:
                edge('type:' + k, node, 1)
    flow = 0
    while True:
        prev = {source: None}
        todo = deque([source])
        while todo and sink not in prev:
            a = todo.popleft()
            for b in graph[a]:
                if b not in prev and residual[a, b] > 0:
                    prev[b] = a
                    todo.append(b)
        if sink not in prev:
            break
        b = sink
        while prev[b] is not None:
            a = prev[b]
            residual[a, b] -= 1
            residual[b, a] += 1
            b = a
        flow += 1
    realized = {k: targets[k] - residual[source, 'type:' + k] for k in TYPES}
    # Residual reachability is a reproducible cut certificate of any deficit.
    reachable = {source}
    todo = deque([source])
    while todo:
        a = todo.popleft()
        for b in graph[a]:
            if b not in reachable and residual[a, b] > 0:
                reachable.add(b)
                todo.append(b)
    cut = sum(c for a, b, c in original_edges if a in reachable and b not in reachable)
    return {'maximum_assignable': flow, 'target_count': sum(targets.values()),
            'jointly_feasible': flow == sum(targets.values()),
            'one_possible_partial_allocation': realized,
            'allocation_is_observed_type': False,
            'partial_allocation_and_unfilled_type_depend_on_traversal_order': True,
            'cut_certificate_flow': cut,
            'unfilled_quotas': {k: targets[k] - realized[k] for k in TYPES}}


def audit(source_stage, output):
    if sys.platform != 'linux':
        raise RuntimeError('Run primary checks on school Linux')
    source_stage = source_stage.resolve()
    requirement = read(STAGE / 'REQUIREMENT.json')
    reference = read(STAGE / 'EB_REFERENCE.json')
    counts = {k: reference['types'][k]['published_assigned_role_n'] for k in TYPES}
    targets = quota(counts, requirement['households'])
    if targets != requirement['target_counts']:
        raise RuntimeError('Declared quotas do not match the pinned EB counts')
    selected = source_stage / 'SELECTION1000.json'
    selection = read(selected)
    records = selection['records']
    ids = [r['household_id'] for r in records]
    if len(ids) != requirement['households'] or len(set(ids)) != len(ids):
        raise RuntimeError('Cohort count or uniqueness failure')
    rows, missing, unsupported, inputs = [], Counter(), [], {}
    detail = []
    for r in records:
        path = (source_stage / r['world_path']).resolve()
        if source_stage not in path.parents:
            raise RuntimeError('World path escapes registered stage')
        checksum = sha(path)
        if checksum != r['world_sha256']:
            raise RuntimeError('Actual world hash mismatch: ' + r['household_id'])
        inputs[r['world_path']] = checksum
        w = read(path)
        if w['household_id'] != r['household_id'] or len(w['members']) != w['N']:
            raise RuntimeError('Household identity or resident-count mismatch')
        eligible = eligibility(w)
        rows.append(eligible)
        prefs = w['service_semantics']['unknown_subjective_tradeoffs']
        for key in ['price_sensitivity', 'temperature_tolerance', 'willingness_to_change_habit']:
            missing[key] += prefs.get(key) is None
        missing['explicit_eb6_blueprint'] += 'eb6_blueprint' not in w
        no_adult = not any(m['age_years'] >= 18 for m in w['members'])
        if no_adult:
            unsupported.append({'household_id': w['household_id'], 'N': w['N'],
                                'age_bins': [m['age_bin_reference'] for m in w['members']],
                                'ages': [m['age_years'] for m in w['members']]})
        detail.append({'household_id': w['household_id'], 'source_world_sha256': checksum,
                       'strict_structural_candidates': [k for k in TYPES if eligible[k]],
                       'assigned_eb_type': None, 'preferences_inferred': False})
    study = capacity_match(rows, targets)
    signature = hashlib.sha256(json.dumps(inputs, sort_keys=True,
                                         separators=(',', ':')).encode()).hexdigest()
    report = {'schema': 'eb.six_type_pre_generation_audit.v24',
              'source_stage': source_stage.name, 'checked_households': len(records),
              'target_counts': targets, 'quota_origin': requirement['quota_origin'],
              'reference_commit': reference['author_repo_commit'],
              'structural_candidates': {k: sum(row[k] for row in rows) for k in TYPES},
              'strict_admission_is_a_declared_adaptation': True,
              'joint_quota_feasibility': study,
              'missing_required_semantics': dict(missing),
              'households_without_adult_resident': len(unsupported),
              'minor_singleton_bin_counts': dict(Counter(
                  str(row['age_bins'][0]) for row in unsupported if row['N'] == 1)),
              'actual_world_input_signature': signature,
              'selection_sha256': sha(selected),
              'requirement_sha256': sha(STAGE / 'REQUIREMENT.json'),
              'reference_sha256': sha(STAGE / 'EB_REFERENCE.json'),
              'audit_code_sha256': sha(__file__),
              'passed_for_new_requirement': False,
              'generation_allowed': False, 'EP_allowed': False,
              'blind_cluster_recovery': 'not tested: required preference blueprints absent',
              'human_answers': 0, 'worlds_modified': 0, 'EP_started': False,
              'blockers': ['strict cohort eligibility and source-frame reconciliation',
                           'source-aware EB policy blueprints and causal routine/service propagation',
                           'frozen extraction/clustering implementation and original50 verification'],
              'scope': 'negative eligibility/missingness audit;not new-world production or human evidence'}
    output.mkdir(parents=True, exist_ok=True)
    save(output / 'COHORT_FEASIBILITY_REVIEW.json', report)
    save(output / 'COHORT_FEASIBILITY_PRIVATE.json', {'records': detail, 'unsupported': unsupported,
         'warning': 'Structural candidates are design eligibility, never recovered/observed EB labels'})
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-stage', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=STAGE / 'school_review')
    args = parser.parse_args()
    return audit(args.source_stage, args.output)


if __name__ == '__main__':
    sys.exit(main())
