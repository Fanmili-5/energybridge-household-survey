#!/usr/bin/env python3
"""Inventory current generation artifacts without modifying frozen batches."""
import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
BATCHES = ['final_v2', 'reproduce_seed20261003', 'sensitivity_H5_lower', 'sensitivity_H5_upper',
           'sensitivity_H7_independent', 'sensitivity_minimum_tails', 'replicate_seed20261004', 'replicate_seed20261005']


def read(path):
    return json.loads(path.read_text())


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run():
    baseline = HERE / 'final_v2'
    lock = read(baseline / 'GENERATOR_LOCK.json')
    qc = read(baseline / 'PROFILES_QC.json')
    sensitivity = read(HERE / 'SENSITIVITY_RESULTS.json')
    negatives = read(HERE / 'NEGATIVE_CONTROL_RESULTS.json')
    assert sha(baseline / 'FAMILY_HOUSING_CANDIDATES.json') == lock['output_sha256'] == qc['candidate_sha256']
    assert sha(HERE / 'generate_candidates.py') == lock['code_sha256'] == sha(baseline / 'code/generate_candidates.py')
    assert sha(HERE / 'verify_candidates.py') == qc['independent_verifier_sha256'] == sha(baseline / 'code/verify_candidates.py')
    assert qc['pass'] and sensitivity['exact_reproduction_pass'] and sensitivity['all_independent_batches_pass'] and negatives['pass']
    links = []
    for name in ['README.md', 'MODEL_CARD.md']:
        for link in re.findall(r'\]\(([^)]+)\)', (HERE / name).read_text()):
            if link.startswith(('https://', 'http://')):
                continue
            target = (HERE / link.split('#')[0]).resolve()
            links.append({'document': name, 'target': link, 'exists': target.exists()})
    assert all(x['exists'] for x in links)
    save(HERE / 'SOURCE_INFLUENCE_SUMMARY.json', {
        'schema': 'eb.family_housing_source_influence_summary.v1', 'candidate_sha256': lock['output_sha256'],
        'detailed_reference_path': 'final_v2/SOURCE_INFLUENCE.json',
        'detailed_reference_sha256': sha(baseline / 'SOURCE_INFLUENCE.json'),
        'source_records_admitted': read(baseline / 'SOURCE_INFLUENCE.json')['source_records_admitted'],
        'diagnostics': sensitivity['reference_influence_and_calibration_diagnostics'],
        'donor_assignment_count': 0, 'source_ids_exported': 0, 'raw_source_households_exported': 0,
        'source_influence_independence_proven': False,
        'dependency_aware_benchmark_split': 'required_before_human_benchmark_release; detailed source influence graph is not yet a released artifact',
    })
    save(HERE / 'CURRENT.json', {
        'schema': 'eb.family_housing_generation_current.v1', 'batch': 'final_v2',
        'candidate_file': str(baseline / 'FAMILY_HOUSING_CANDIDATES.json'),
        'candidate_sha256': lock['output_sha256'],
        'QC_file': str(baseline / 'PROFILES_QC.json'), 'QC_pass': qc['pass'], 'QC_checks': qc['check_count'],
        'profiles': qc['profiles'], 'resident_members': qc['members'],
        'ordinary': qc['ordinary'], 'nonordinary': qc['nonordinary'], 'ordinary_shared': qc['ordinary_shared'],
        'dwelling_type_counts': qc['dwelling_type_counts'],
        'exact_reproduction_pass': sensitivity['exact_reproduction_pass'],
        'sensitivity_batch_count_including_baseline_and_reproduction': len(BATCHES),
        'semantic_negative_control_count': negatives['case_count'], 'semantic_negative_controls_pass': negatives['pass'],
        'role_evidence_status': 'modeled_anonymous_family_housing_candidate',
        'complete_actor_cards': 0, 'observed_source_families': 0, 'measured_phase2_households': 0,
        'city_distribution_bound': False, 'devices_bound': False, 'economics_bound': False, 'activities_bound': False,
        'physical_model_admission_outside_this_generation_package': True,
        'collection_release': False, 'training_release': False, 'detailed_national_joint_representativeness_claimed': False,
        'historical_not_current': ['baseline_v1', 'trial_v2_family_stream_isolated'],
    })
    roots = ['README.md', 'MODEL_CARD.md', 'CURRENT.json', 'SENSITIVITY_RESULTS.json', 'SOURCE_INFLUENCE_SUMMARY.json',
             'NEGATIVE_CONTROL_RESULTS.json', 'generate_candidates.py', 'verify_candidates.py', 'analyze_sensitivity.py',
             'test_negative_controls.py', 'seal_generation_package.py']
    files = [HERE / name for name in roots]
    for batch in BATCHES:
        files.extend(p for p in (HERE / batch).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    save(HERE / 'PACKAGE_MANIFEST.json', {
        'schema': 'eb.family_housing_generation_manifest.v1',
        'scope': 'generation only; sealed original inputs and downstream physical/context packages are excluded',
        'current_candidate_sha256': lock['output_sha256'], 'inventory_count': len(files),
        'files': [{'path': str(p.relative_to(HERE)), 'bytes': p.stat().st_size, 'sha256': sha(p)} for p in sorted(set(files))],
        'markdown_local_links': links, 'all_markdown_local_links_exist': True,
        'manifest_self_hash_excluded': True,
    })
    print(json.dumps({'candidate_sha256': lock['output_sha256'], 'inventory_files': len(files),
                      'all_markdown_local_links_exist': True, 'manifest_sha256': sha(HERE / 'PACKAGE_MANIFEST.json')}))


if __name__ == '__main__':
    run()
