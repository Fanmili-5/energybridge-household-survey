"""Print proposed experimental quotas; never writes household or answer data."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from fractions import Fraction
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ROLES = tuple('ABCDEF')
PERSONAS = dict(zip(
    ('Price-sensitive', 'Comfort-sensitive', 'Irregular routine',
     'Cooperative regular', 'Caregiver', 'EV commuter'), ROLES))


def largest_remainder(counts, total):
    if not isinstance(total, int) or isinstance(total, bool) or total < 0:
        raise ValueError('Total must be a nonnegative integer')
    if set(counts) != set(ROLES) or any(type(v) is not int or v < 0 for v in counts.values()):
        raise ValueError('Expected six nonnegative integer source counts A-F')
    denominator = sum(counts.values())
    if denominator <= 0:
        raise ValueError('Source counts must have a positive total')
    exact = {k: Fraction(total * counts[k], denominator) for k in ROLES}
    floors = {k: exact[k].numerator // exact[k].denominator for k in ROLES}
    order = sorted(ROLES, key=lambda k: (-(exact[k] - floors[k]), k))
    awarded = order[:total - sum(floors.values())]
    quotas = {k: floors[k] + int(k in awarded) for k in ROLES}
    return {
        'source_counts': {k: counts[k] for k in ROLES}, 'target_total': total,
        'exact_quota_fraction': {k: str(exact[k]) for k in ROLES},
        'initial_floor': floors,
        'fractional_remainder': {k: str(exact[k] - floors[k]) for k in ROLES},
        'remainder_order': order, 'extra_slot_roles': awarded, 'quotas': quotas,
    }


def verify_participants(path, source):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != source['participants_sha256']:
        raise ValueError('EB participant source SHA256 differs from the pinned file')
    with path.open(encoding='utf-8', newline='') as stream:
        rows = list(csv.DictReader(stream))
    ids = [row['participant_id'] for row in rows]
    if len(rows) != source['participants_total'] or len(set(ids)) != len(ids) or not all(ids):
        raise ValueError('EB participant IDs are not unique and complete at the pinned count')
    observed = Counter(PERSONAS[row['persona']] for row in rows)
    if dict(observed) != source['assigned_role_counts']:
        raise ValueError('EB assigned-role counts differ from the frozen source')


def proposed(households=1000, subset=50):
    if households <= 0 or not 0 <= subset <= households:
        raise ValueError('Require households > 0 and 0 <= subset <= households')
    policy = json.loads((ROOT / 'POLICY.json').read_text())
    master = largest_remainder(policy['EB_source']['assigned_role_counts'], households)
    child = largest_remainder(master['quotas'], subset)
    return {
        'schema': 'eb.household_archetypes.proposed_allocation.v1',
        'method_version': policy['method_version'],
        'status': 'proposed_not_applied_to_existing_households',
        'source_interpretation': 'EB assigned-role experimental composition, not population prevalence',
        'EB_source_commit': policy['EB_source']['commit'],
        'master': master, 'same_master_subset': child,
        'applied_to_existing_data': False, 'generated_households': 0,
        'generated_acceptance_labels': 0, 'EP_runs': 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--households', type=int, default=1000)
    parser.add_argument('--subset', type=int, default=50)
    parser.add_argument('--participants', type=Path)
    args = parser.parse_args()
    if args.participants:
        policy = json.loads((ROOT / 'POLICY.json').read_text())
        verify_participants(args.participants, policy['EB_source'])
    print(json.dumps(proposed(args.households, args.subset), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
