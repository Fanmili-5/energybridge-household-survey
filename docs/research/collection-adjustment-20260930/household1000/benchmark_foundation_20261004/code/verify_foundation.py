"""Integrity and completed-work audit; never promotes a review to validation."""
import hashlib
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent
BASE = OUT.parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def main():
    checks = []
    def check(value, label):
        if not value:
            raise AssertionError(label)
        checks.append(label)
    old_files = 0
    for folder in ['production_route_v5_20261004', 'idf_unit_evidence_20261004',
                   'end_to_end_plan_20261004', 'production_route_v4_20261003', 'construction_chain_20261003']:
        root = BASE / folder
        for rel, expected in read(root / 'PACKAGE_MANIFEST.json')['files'].items():
            check(sha(root / rel) == expected, 'sealed_source_unchanged:' + folder + '/' + rel)
            old_files += 1
    for entry in read(OUT / 'INPUT_LOCK.json'):
        check(sha(Path(entry['path'])) == entry['sha256'], 'audit_input_lock:' + entry['path'])
    cohort = read(OUT / 'COHORT_AUDIT1000.json')
    policy = read(OUT / 'PRODUCTION_POLICY.json')
    oracle = read(OUT / 'ETNA_EXTERNAL_ORACLE.json')
    devices = read(OUT / 'MODERN_ASSET_GROUP_ADMISSION.json')
    semantics = read(OUT / 'SEMANTIC_WITNESSES.json')
    adversary = read(OUT / 'MATCHER_ADVERSARIAL_WITNESS.json')
    summary = cohort['summary']
    check(len(cohort['slots']) == 1000 and len({r['slot_id'] for r in cohort['slots']}) == 1000, 'all1000_unique_slots_audited')
    check(summary['whole_private_roles_definitely_outside_native_H7_support'] == 181, 'H7_support_deficit_recomputed')
    check(policy['counts'] == summary, 'policy_counts_equal_audit')
    check(not policy['benchmark_scientific_validity_established'], 'no_scientific_admission_from_report')
    check(not policy['target_contract_frozen'] and not policy['current_candidate_changed'], 'no_silent_population_switch')
    check(not policy['old_V5_binding_gate_may_approve_production'], 'presence_gate_no_longer_approval_authority_in_new_policy')
    check(adversary['old_gate_accepted_adversarial_placeholder'] and not adversary['real_world_approved'], 'adversarial_case_not_misrepresented_as_real_binding')
    check(semantics['checks_passed'] and all(x['rejected'] for x in semantics['invalid_cases']), 'semantic_normal_and_negative_witnesses_completed')
    check(not semantics['shared_natural_room_not_forced_into_exclusive_H7']['physical_binding_approved'], 'semantic_projection_not_full_physical_gate')
    check(devices['positive_weight_eligible_source_households'] == 9145, 'modern_asset_source_denominator')
    check(devices['all_choice_flags_source_QC']['all_flags_unselected_not_an_explicit_none'] == 194, 'all_unchecked_not_explicit_absence')
    check(sum(x['source_households'] for x in devices['primary_same_visit2021_group_prior']) == devices['primary_same_visit2021_answered_households'] == 6089, 'modern_primary_answered_aligned_source_6089')
    check(sum(x['source_households'] for x in devices['visit_year_sensitivity']) == 9145, 'asset_year_partitions_conserve_source_rows')
    check(not devices['2020_national_frequency_validated'], 'modern_group_QC_not_2020_national_installation_validation')
    check(sha(Path(oracle['source_archive_path'])) == oracle['source_archive_sha256'], 'ETNA_primary_archive_lock')
    check(oracle['reference_cases_recomputed'] == 4 and len(oracle['published_comparisons_recomputed']) == 8, 'ETNA_reference_and_published_comparisons_recomputed')
    for r in oracle['reference_cases']:
        check(r['steady_state_hours'] == (18 if r['case'].startswith('ET110') else 55), 'case_specific_normative_time_window:' + r['case'])
    check(all(r['negative_control_heater_plus_fan_wrong_meter_rejected'] for r in oracle['published_comparisons_recomputed']), 'wrong_meter_negative_control_detected')
    check(not oracle['local_energyplus24_1_empirical_validation_completed'] and oracle['new_energyplus_runs'] == 0, 'reference_comparisons_not_our_generated_IDF_validation')
    check(not policy['collection_release'] and not policy['training_release'], 'only_foundation_scope')
    register = read(OUT / 'EVIDENCE_REGISTER.json')
    check(len({s['id'] for s in register['sources']}) == len(register['sources']), 'unique_source_register_ids')
    for source in register['sources']:
        if 'sha256' in source and 'local_path' in source:
            p = Path(source['local_path'])
            if not p.is_absolute(): p = OUT / p
            check(sha(p) == source['sha256'], 'primary_local_source_lock:' + source['id'])
        if 'private_local_path' in source and 'sha256' in source:
            check(sha(Path(source['private_local_path'])) == source['sha256'], 'private_primary_source_lock:' + source['id'])
    result = {'integrity_and_executed_work_verified': True, 'checks': len(checks),
              'sealed_existing_files_unchanged': old_files, 'all1000_foundation_slots_audited': 1000,
              'semantic_operator_witnesses_completed': True,
              'modern_group_source_audit_completed': True, 'ETNA_external_reference_evaluator_verified': True,
              'full_generator_validation_completed': False, 'new_1000_IDFs_generated': 0,
              'our_compiler_empirical_validation_completed': False,
              'scientific_benchmark_admitted': False, 'review_decision': policy['review_decision'],
              'meaning': 'source_integrity_and_completed_diagnostics; not_scientific_or_population_or_physical_approval'}
    save(OUT / 'VERIFICATION.json', result)
    files = {str(p.relative_to(OUT)): sha(p) for p in sorted(OUT.rglob('*'))
             if p.is_file() and p.name != 'PACKAGE_MANIFEST.json' and '__pycache__' not in p.parts}
    save(OUT / 'PACKAGE_MANIFEST.json', {'files': files, 'file_count': len(files),
                                         'scope': result['meaning'], 'scientific_benchmark_admitted': False,
                                         'collection_release': False, 'training_release': False})
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
