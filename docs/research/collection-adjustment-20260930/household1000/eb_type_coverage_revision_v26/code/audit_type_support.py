#!/usr/bin/env python3
"""Read-only source support for type-aware design on school original50.

Candidate support is not a type label, preference inference, coherent world
generation, downstream physical validation or approval. No quotas are drawn
from EB actors. Only a one-per-type screening minimum is examined.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

STAGE = Path(__file__).resolve().parents[1]
TYPES = ('A', 'B', 'C', 'D', 'E', 'F')


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_support(world):
    members = world['members']
    adults = [m for m in members if m['age_years'] >= 18]
    # Reuse actual long-work scenario eligibility of the existing foundation.
    # Unknown/no-current-work is never converted into observed commuting work.
    work = [m for m in adults if m['employment_status'] == 'has_work'
            and m['reference_activity_role'] in
            ('commuter_reference', 'home_work_reference', 'flexible_work_reference')]
    actual_commuter = [m for m in work if m['reference_activity_role'] == 'commuter_reference']
    ev = any('ev' in device['types'] for device in world['parameter_pack']['devices'])
    protected_pair = any(
        adult['member_id'] != other['member_id']
        and (other['age_years'] < 6 or other['age_years'] >= 65)
        for adult in adults for other in members
    )
    care = world.get('care_contract', {})
    named_childcare = bool(care.get('home_care_child_ids'))
    existing_resident_childcare = (named_childcare and care.get('caregiver_is_resident', False)
                                  and care.get('caregiver_id') in {m['member_id'] for m in adults})
    candidates = {'A': bool(work), 'B': bool(adults), 'C': bool(adults),
                  'D': bool(work), 'E': protected_pair, 'F': bool(work) and ev}
    return {
        'candidate_under_declared_adaptation': candidates,
        'adult_responsible_person_supported': bool(adults),
        'long_work_scenario_supported': bool(work),
        'existing_commuter_scenario_present': bool(actual_commuter),
        'EV_function_present': ev,
        'protected_pair_structural_support': protected_pair,
        'existing_named_home_childcare': named_childcare,
        'existing_named_resident_childcare': existing_resident_childcare,
    }


def audit(source):
    if sys.platform != 'linux':
        raise RuntimeError('Run original50 source support checks on school Linux')
    selected = source / 'SELECTION50.json'
    records = read(selected)['records']
    if len(records) != 50 or len({r['household_id'] for r in records}) != 50:
        raise RuntimeError('original50 count/uniqueness mismatch')
    rows, inputs = [], []
    for record in records:
        path = (source / record['world_path']).resolve()
        if not path.is_relative_to(source) or sha(path) != record['world_sha256']:
            raise RuntimeError('source world path/hash mismatch')
        world = read(path)
        if world['household_id'] != record['household_id'] or len(world['members']) != world['N']:
            raise RuntimeError('world identity/roster mismatch')
        rows.append(source_support(world))
        inputs.append(record['world_sha256'])
    # Reuse the independently checked V24 integer max-flow helper only. Its
    # old quotas/age eligibility are NOT used by this current support audit.
    legacy = STAGE.parent / 'eb_six_type_prerequisite_20261013_v24' / 'code'
    sys.path.insert(0, str(legacy))
    from preflight import capacity_match
    candidate_rows = [row['candidate_under_declared_adaptation'] for row in rows]
    screening = capacity_match(candidate_rows, {k: 1 for k in TYPES})
    return {
        'schema': 'eb.type_generation_source_support50.v26',
        'date': '2026-10-14', 'execution_host': 'hku-server',
        'objective': 'type_coverage_consistent_with_EB',
        'checked_households': len(rows), 'world_hash_checks_passed': True,
        'selection_sha256': sha(selected),
        'input_world_hashes_digest': hashlib.sha256(json.dumps(inputs).encode()).hexdigest(),
        'audit_code_sha256': sha(Path(__file__)),
        'flow_helper_sha256': sha(legacy / 'preflight.py'),
        'candidate_support_counts': {k: sum(row[k] for row in candidate_rows) for k in TYPES},
        'support_summary': {key: sum(row[key] for row in rows)
                            for key in rows[0] if key != 'candidate_under_declared_adaptation'},
        'one_per_type_screening': screening,
        'screening_minimum_is_not_formal_sample_size_or_quota': True,
        'eligibility_interpretation': {
            'A_D_F': 'existing long-work reference eligibility with source has_work; reconfiguration and actual date/service feasibility still needed',
            'B_C': 'adult policy holder; home/irregular activity is a new declared scenario, not observed occupation or calendar',
            'E': 'adult plus another young/older member; structural support only, not observed care or vulnerability; concrete protected service and care calendar still required',
            'EV': 'existing task-world functional coverage,not national vehicle ownership or verified home charging',
        },
        'open_items': [
            'nonadult-only household policy holder/guardian and source-frame reconciliation',
            'actual given policy and coherent ten-date calendars/services',
            'freeze joint allocation of formal coverage counts before1000',
            'replace uniform A temperature/unknown-role text by shared policy reads',
            'actual A/B/IDF/material coupling and independent feature extraction/coverage tests',
        ],
        'actual_EB_type_assignment_performed': False,
        'new_worlds_generated': 0, 'new_IDFs_compiled': 0, 'EP_started': False,
        'actual_cluster_coverage_verified': False, 'generation_allowed': False,
        'scope': 'candidate source adaptation support only;not generated-world or scientific production acceptance',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-stage', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.source_stage.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
