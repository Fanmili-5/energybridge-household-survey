#!/usr/bin/env python3
"""Read-only audit consistency check; no simulation, microdata or training.

This checks byte bindings and report consistency, not scientific validity.
Run: python3 verify_audit.py --report /private/tmp/reviewer_audit_check.json
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote

AUDIT = Path(__file__).resolve().parent
STAGE = AUDIT.parent


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    failures, checks = [], []

    def check(name, passed, **details):
        checks.append({'name': name, 'pass': bool(passed), **details})
        if not passed:
            failures.append(name)

    def bindings(items, base):
        mismatches = []
        for name, expected in items.items():
            path = (base / name).resolve()
            if not path.is_file() or sha(path) != expected:
                mismatches.append(str(path))
        return mismatches

    manifest = read(AUDIT / 'REVIEW_MANIFEST.json')
    baseline = read(AUDIT / 'AUDIT_BASELINE.json')
    prior = read(STAGE / 'PACKAGE_MANIFEST.json')
    mismatch = bindings(prior['files'], STAGE)
    check('frozen_package_bytes', not mismatch,
          files_checked=len(prior['files']), mismatches=mismatch)
    check('prior_package_manifest_anchor',
          sha(STAGE / 'PACKAGE_MANIFEST.json') == baseline['prior_package_manifest_sha256'])
    check('prior_summary_anchor',
          sha(STAGE / 'final_v5/SUMMARY.json') == baseline['prior_SUMMARY_sha256'])
    mismatch = bindings(manifest['files'], AUDIT)
    check('new_audit_manifest_bytes', not mismatch,
          files_checked=len(manifest['files']), mismatches=mismatch)
    excluded = set(manifest['excluded_generated_files'])
    actual = {p.name for p in AUDIT.iterdir() if p.is_file()}
    check('audit_root_inventory', actual - excluded == set(manifest['files']),
          unexpected=sorted(actual - excluded - set(manifest['files'])),
          missing=sorted(set(manifest['files']) - actual))

    ledger = read(STAGE / 'SOURCE_LEDGER.json')
    refs = [f for s in ledger['sources'] for f in s.get('local_files', [])]
    mismatch = [f['path'] for f in refs
                if not Path(f['path']).is_file() or sha(f['path']) != f['sha256']]
    check('prior_source_ledger_bytes', not mismatch,
          references_checked=len(refs), mismatches=mismatch)

    population = read(AUDIT / 'POPULATION_CHECKS.json')
    standards = read(AUDIT / 'STANDARDS_SOURCES.json')
    for name, evidence, field in [
        ('population_evidence_bytes', population['evidence_index'], 'sha256'),
        ('standards_local_evidence_bytes', standards['local_evidence'], 'sha256_at_review')
    ]:
        mismatch = [key for key, item in evidence.items()
                    if not Path(item['path']).is_file()
                    or sha(item['path']) != item[field]]
        check(name, not mismatch, references_checked=len(evidence), mismatches=mismatch)
    check('standards_report_binding',
          sha(standards['review_outputs']['report_path'])
          == standards['review_outputs']['report_sha256'])
    check('population_check_results',
          population['computed_checks_all_pass']
          and all(c['pass'] for c in population['computed_checks']),
          checks_recorded=len(population['computed_checks']),
          interpretation='readback of reported aggregate checks, not rerun of survey microdata')

    probes = read(AUDIT / 'REVIEW_PROBES.json')
    check('probe_script_binding',
          sha(AUDIT / 'verify_review_probes.py') == probes['review_probe_script_sha256'])
    check('probe_baseline_binding',
          sha(probes['reviewed_baseline_idf_path']) == probes['reviewed_baseline_idf_sha256'])
    legacy = STAGE.parents[2] / 'UX_LOGIC_REVIEW_20260926/PHYSICAL_GATE_V1/V5_DOWNSTREAM/C_IDF/build_v5_idfs.py'
    mismatch = []
    for name, expected in probes['code_hashes'].items():
        path = legacy if name == 'build_v5_idfs.py' else STAGE / name
        if not path.is_file() or sha(path) != expected:
            mismatch.append(str(path))
    check('probed_implementation_bytes', not mismatch, mismatches=mismatch)
    observed = {p['id']: p for p in probes['probes']}
    huge = observed['huge_integer_refusal_path']
    shell = observed['parallel_wall_shift_open_shell']
    check('recorded_numeric_failure_consistency',
          huge['direct_input_gate']['raised'] == 'OverflowError'
          and huge['file_loop']['raised'] == 'OverflowError'
          and not any(huge[k] for k in ['ADMISSION_FAILURE_exists', 'case_STATUS_exists', 'SUMMARY_exists']),
          defect_remains_open=True)
    check('recorded_geometry_failure_consistency',
          shell['writer_static_check']['errors'] == []
          and shell['independent_geometry']['status'] == 'fail'
          and any('zone_shell_not_closed_or_opposite_edges:corridor' in r['issues']
                  for r in shell['independent_geometry']['results']),
          defect_remains_open=True)

    requirements = read(AUDIT / 'AUDIT_REQUIREMENTS.json')
    ids = [r['id'] for r in requirements['requirements']]
    absent = [(r['id'], p) for r in requirements['requirements']
              for p in r.get('current_evidence', []) if not (AUDIT / p).is_file()]
    check('requirement_ids_and_evidence', len(ids) == len(set(ids)) == 13 and not absent,
          requirements=len(ids), missing_evidence=absent)
    check('consistent_claim_boundary',
          requirements['benchmark_ready'] is False
          and manifest['benchmark_ready'] is False
          and population['release_claims']['1000_complete_synthetic_actor_role_benchmark_ready'] is False
          and baseline['distinct_population_slots_assigned'] == 0
          and baseline['new_complete1000_roles'] == 0)

    broken, count = [], 0
    for report in AUDIT.glob('*.md'):
        for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)', report.read_text()):
            target = unquote(target.strip().strip('<>'))
            if target.startswith(('https://', 'http://', 'app://', 'codex://', '#')):
                continue
            target = re.sub(r':\d+(?:-\d+)?$', '', target)
            target = target.split('#', 1)[0]
            path = Path(target) if target.startswith('/') else report.parent / target
            count += 1
            if not path.exists():
                broken.append({'report': report.name, 'target': target})
    check('local_markdown_targets', not broken, links_checked=count, broken=broken)
    parsed, invalid = 0, []
    for path in AUDIT.glob('*.json'):
        if path.name in excluded:
            continue
        try:
            read(path)
            parsed += 1
        except (ValueError, OSError) as exc:
            invalid.append({'path': path.name, 'error': str(exc)})
    check('new_json_syntax', not invalid, files_parsed=parsed, invalid=invalid)

    result = {
        'schema': 'eb.reviewer_audit.verification.v1',
        'review_date_HKT': '2026-10-03',
        'reviewed_experiment_id': baseline['reviewed_experiment_id'],
        'review_manifest_sha256': sha(AUDIT / 'REVIEW_MANIFEST.json'),
        'audit_artifact_consistency': 'pass' if not failures else 'fail',
        'checks': checks, 'failed_checks': failures,
        'benchmark_ready': False,
        'open_reproducible_defects': ['R12_STRICT_GEOMETRY_GATE', 'R13_INPUT_DOMAIN_REFUSAL'],
        'simulation_or_training_rerun': False,
        'claim': 'This verifies the audit package bindings and report consistency only. It does not close the defects or validate the complete benchmark.'
    }
    body = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.report:
        args.report.write_text(body)
        print(json.dumps({'report': str(args.report), 'status': result['audit_artifact_consistency'],
                          'failed_checks': failures}, ensure_ascii=False))
    else:
        print(body)
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
