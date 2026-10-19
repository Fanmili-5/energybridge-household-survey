"""Offline checks of this method release, not a claim of archetype validity."""
import hashlib
import json
from pathlib import Path

from allocate import largest_remainder, proposed

ROOT = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text())


def check():
    manifest = read(ROOT / 'PACKAGE_MANIFEST.json')
    for rel, digest in manifest['files_sha256'].items():
        path = ROOT / rel
        if not path.resolve().is_relative_to(ROOT) or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('Method package hash mismatch: ' + rel)
    policy = read(ROOT / 'POLICY.json')
    source = policy['EB_source']
    assert sum(source['assigned_role_counts'].values()) == source['participants_total'] == 584
    assert set(policy['archetypes']) == set('ABCDEF')
    assert policy['current_data_migration'] is False and policy['EP_runs'] == 0
    frozen = read(ROOT / 'PROPOSED_ALLOCATION.json')
    assert frozen == proposed()
    assert frozen['master']['quotas'] == dict(zip('ABCDEF', [166, 198, 125, 151, 156, 204]))
    assert frozen['same_master_subset']['quotas'] == dict(zip('ABCDEF', [8, 10, 6, 8, 8, 10]))
    assert frozen['applied_to_existing_data'] is False
    # The two properties that matter for transparent quota calculation: exact source
    # recovery and deterministic treatment of tied fractional remainders.
    assert largest_remainder(source['assigned_role_counts'], 584)['quotas'] == source['assigned_role_counts']
    assert largest_remainder(dict.fromkeys('ABCDEF', 1), 8)['quotas'] == dict(zip('ABCDEF', [2, 2, 1, 1, 1, 1]))
    summary = read(ROOT / 'evidence/SUMMARY.json')
    archive = ROOT / 'research/archive'
    eca = read(archive / 'artifacts/eb_eca_linkage_audit_20261019/RESULTS.json')
    ext = read(archive / 'artifacts/eb_eca_linkage_audit_20261019/EXTERNAL_CONSTRUCTS.json')
    ecape = read(archive / 'docs/research/ecape-fixed-six_20261019/RESULTS.json')
    assert summary['ECA']['n'] == eca['n'] == 4507
    assert summary['ECA']['routing'] == eca['routing']
    assert summary['ECA']['patterns_not_role_prevalences'] == eca['patterns_not_role_prevalences']
    assert summary['iFlex'] == ext['iFlex2020'] and summary['Dutch']['construct_linkage'] == ext['dutch']
    assert summary['eCAPE']['n'] == ecape['n'] == 1022
    assert summary['eCAPE']['bootstrap_summary'] == ecape['bootstrap_summary']
    assert summary['eCAPE']['class_shares'] == {v['class']: v['share'] for v in ecape['profiles']}
    assert len(ecape['bootstrap']) == 20 and len(ecape['sensitivities']) == 3
    assert abs(sum(summary['eCAPE']['class_shares'].values()) - 1) < 1e-10
    return {'passed': True, 'method_version': policy['method_version'],
            'method_files_verified': len(manifest['files_sha256']),
            'proposed_quotas_match': True, 'aggregate_evidence_matches': True,
            'archetype_validity_claim': False, 'population_prevalence_claim': False,
            'existing_data_migrated': False, 'EP_started': False}


if __name__ == '__main__':
    print(json.dumps(check(), ensure_ascii=False))
