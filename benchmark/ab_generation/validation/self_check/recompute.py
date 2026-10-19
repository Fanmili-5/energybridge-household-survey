"""Recheck frozen coverage receipts without generating or executing any new B."""
import argparse
from pathlib import Path
from benchmark.ab_generation.common import canonical, code_hash, read, save, sha
from benchmark.ab_generation.sampling import response_coverage


def recompute(out):
    package = Path(__file__).resolve().parents[2]
    rules = package / 'validation/rules'
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    summaries = []
    for label, folder, result_name, selection_name, manifest_name in [
            ('summer', rules, 'PHYSICAL_RESULT.json', 'PHYSICAL_SAMPLE_SELECTION.json', 'PHYSICAL_SAMPLE_MANIFEST.json'),
            ('winter', rules / 'winter', 'RESULT.json', 'SAMPLE_SELECTION.json', 'SAMPLE_MANIFEST.json')]:
        result, selection = read(folder / result_name), read(folder / selection_name)
        manifest = read(folder / manifest_name)
        if (result['selection_manifest_sha256'] != sha(folder / manifest_name)
                or manifest['files']['SELECTION.json'] != sha(folder / selection_name)
                or {r['sample_id'] for r in result['records']} != {r['sample_id'] for r in selection['records']}
                or len(result['records']) != len(selection['records'])
                or len(result['records']) != len({r['sample_id'] for r in result['records']})):
            raise ValueError('FROZEN_SELECTION_RECEIPT_MISMATCH')
        reviewed = response_coverage(result['records'], selection.get('response_checks'))
        previous = result['response_coverage']
        unchanged = all(reviewed[k] == previous[k] for k in
                        ('patterns', 'actual_changed_kind_counts', 'distinct_case_and_native_B_trajectories', 'records'))
        if not unchanged:
            raise ValueError('SELF_CHECK_CHANGED_PHYSICAL_RESULTS_OR_DROPPED_RECORDS')
        review = {'source_result_sha256': sha(folder / result_name),
                  'source_selection_sha256': sha(folder / selection_name),
                  'code_sha256': code_hash(), 'verifier_sha256': sha(__file__),
                  'previous_supported_target_count': previous['supported_target_count'],
                  'physical_results_unchanged': unchanged,
                  'selected_record_count': len(result['records']), 'all_selected_records_retained': True,
                  'original_other_validation_passed': result['passed'],
                  'reviewed_response_coverage': reviewed,
                  'new_B_selected_or_executed': False,
                  'passed': result['passed'] and reviewed['passed']}
        save(out / (label.upper() + '.json'), review)
        summaries.append({'scope': label, 'previous_supported_targets': previous['supported_target_count'],
                          'reviewed_supported_targets': reviewed['supported_target_count'],
                          'no_response': reviewed['supported_no_response_count'], 'passed': review['passed']})
    summary = {'scopes': summaries, 'passed': all(r['passed'] for r in summaries),
               'new_physics_runs': 0, 'new_B_selection': False, 'production_modified': False}
    save(out / 'SUMMARY.json', summary)
    if not summary['passed']:
        raise ValueError('REVIEWED_COVERAGE_FAILED;retain_original_sample;do_not_reselect')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    print(canonical(recompute(parser.parse_args().out)))
