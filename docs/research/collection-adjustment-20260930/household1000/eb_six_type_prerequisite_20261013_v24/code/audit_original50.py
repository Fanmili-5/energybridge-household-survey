#!/usr/bin/env python3
"""Structural EB-six-type trial capacity on the unchanged original50; no EP."""
import argparse
import json
from pathlib import Path
import sys
from preflight import STAGE, TYPES, read, save, sha, quota, eligibility, capacity_match


def main():
    if sys.platform != 'linux':
        raise RuntimeError('Run primary checks on school Linux')
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-stage', type=Path, required=True)
    p.add_argument('--output', type=Path, default=STAGE / 'ORIGINAL50_FEASIBILITY_REVIEW.json')
    args = p.parse_args()
    source = args.source_stage.resolve()
    selected = source / 'SELECTION50.json'
    records = read(selected)['records']
    if len(records) != 50 or len({r['household_id'] for r in records}) != 50:
        raise RuntimeError('Original50 count/uniqueness mismatch')
    worlds = []
    for r in records:
        world_path = (source / r['world_path']).resolve()
        if source not in world_path.parents or sha(world_path) != r['world_sha256']:
            raise RuntimeError('Original50 world path/hash mismatch')
        w = read(world_path)
        if w['household_id'] != r['household_id'] or len(w['members']) != w['N']:
            raise RuntimeError('Original50 identity/roster mismatch')
        worlds.append(w)
    ref = read(STAGE / 'EB_REFERENCE.json')
    targets = quota({k: ref['types'][k]['published_assigned_role_n'] for k in TYPES}, 50)
    rows = [eligibility(w) for w in worlds]
    result = {'schema': 'eb.original50_EB6_structural_feasibility.v24',
              'households': 50, 'original50_identity_preserved': True,
              'selection_sha256': sha(selected),
              'reference_sha256': sha(STAGE / 'EB_REFERENCE.json'),
              'audit_code_sha256': sha(__file__), 'preflight_code_sha256': sha(STAGE / 'code/preflight.py'),
              'target_counts_for_trial': targets,
              'structural_candidates': {k: sum(r[k] for r in rows) for k in TYPES},
              'joint_quota_feasibility': capacity_match(rows, targets),
              'critical_policy_blueprints_available': sum('eb6_blueprint' in w for w in worlds),
              'prototype_or_cluster_recovery_passed': False,
              'generation_allowed': False, 'EP_started': False,
              'scope': 'capacity diagnostic for unchanged original50;not actual role assignment or new physical acceptance'}
    save(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2


if __name__ == '__main__':
    sys.exit(main())
