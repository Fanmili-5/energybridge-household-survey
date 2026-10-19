"""Final fixed-plan sampling and static acceptance. No simulation entry point."""
import argparse
import copy
from collections import Counter
from pathlib import Path
from .common import bound, code_hash, digest, read, save, seal, sha, verify
from .generate import DEFAULT_RULES, generate
from .model import apply, control_issues
from .power import site_capacity
from .sampling import catalogue, command_hash, describe, interactions, require, sample_catalogue

HERE = Path(__file__).parent
ROOT = HERE / 'validation/gap_supplement'
PLAN = HERE / 'examples/gap_supplement/tail_plan.json'


def inputs():
    verify(ROOT / 'final_inputs')
    suite = read(ROOT / 'final_inputs/REFERENCES.json')
    require(suite['tail_plan_sha256'] == sha(PLAN), 'STATIC_PLAN_CHANGED')
    require(suite['scenario_plan_sha256'] == sha(HERE / 'examples/gap_supplement/scenarios.json'), 'STATIC_SCENARIOS_CHANGED')
    contexts = {}
    for ref in suite['records']:
        path = bound(ROOT, ref['context'])
        require(sha(path) == ref['context_file_sha256'], 'STATIC_CONTEXT_CHANGED')
        contexts[ref['reference_id']] = read(path)
    require(len(contexts) == len(suite['records']) == 3, 'STATIC_SCENARIOS_MISSING_OR_DUPLICATE')
    require(set(contexts) == {r['id'] for r in read(HERE / 'examples/gap_supplement/scenarios.json')['cases']},
            'STATIC_SCENARIO_IDS_CHANGED')
    return suite, contexts


def compact(row):
    keys = ('sample_id', 'case_id', 'household_id', 'context_sha256', 'B_commands_sha256',
            'features', 'static_issues', 'reference_id', 'physical_baseline_status')
    return {**{k: copy.deepcopy(row[k]) for k in keys}, 'alias_count': len(row['aliases'])}


def audit_selected(rows, requests, contexts):
    """Materialize complete A/B and use the unindexed reference checker."""
    by_id = {r['sample_id']: r for r in requests}
    audits = []
    require(len(by_id) == len(requests) == len(rows), 'SELECTED_REQUESTS_MISSING_OR_DUPLICATE')
    for sample in rows:
        request = by_id[sample['sample_id']]
        c = contexts[sample['reference_id']]
        B = apply(c['A'], request['patches'])
        b_hash = command_hash(B)
        features, issues = describe(c, B, request['children'], list(request['generation_static_issues']),
            unchanged=b_hash == command_hash(c['A']), stress_admissions=[])
        extra = sorted(set(control_issues(c, B) + site_capacity(c, B)['issues']) - set(issues))
        checked = b_hash == sample['B_commands_sha256'] and features == sample['features'] and issues == sample['static_issues'] and not extra
        audits.append({'sample_id': sample['sample_id'], 'stratum': sample['stratum'],
            'reference_id': sample['reference_id'], 'checked': checked, 'static_valid': not issues,
            'static_issues': issues, 'unreported_issues': extra,
            'full_A_used': True, 'physical_baseline_status': sample['physical_baseline_status'],
            'B_executed': False, 'human_acceptance': None})
    return audits


def coverage_result(rows, selection, audits):
    tables = interactions(rows, selection['records'], read(PLAN)['coverage_axes'])
    missing = [r for r in tables if r['selected_unique'] == 0]
    return {'schema': 'eb.ab_final_static_coverage.v1',
        'integrity_passed': all(a['checked'] for a in audits) and len(audits) == len(selection['records']),
        'required_strata_passed': selection['selection_coverage_passed'],
        'coverage': selection['coverage'], 'required_deficits': [r['stratum'] for r in selection['coverage'] if r['required'] and r['deficit']],
        'catalogue_unique': len(rows), 'raw_aliases': sum(r['alias_count'] for r in rows),
        'selected': len(selection['records']), 'unassigned_unique': selection['unassigned_unique'],
        'catalogue_admissions': dict(Counter(r['features']['admission'] for r in rows)),
        'selected_admissions': dict(Counter(r['features']['admission'] for r in selection['records'])),
        'physical_baselines_in_selected': dict(Counter(r['physical_baseline_status'] for r in selection['records'])),
        'interaction_coverage': tables, 'missing_interactions': missing,
        'interaction_levels': len(tables), 'covered_interaction_levels': len(tables) - len(missing),
        'selection_is_complete_covering_array': not missing,
        'no_outcome_reselection': True, 'new_engine_runs': 0, 'B_executed': False,
        'actual_response_or_service_outcomes': 'deferred_unverified', 'representative_population_claim': False}


def build(out, generated_index=None):
    suite, contexts = inputs()
    plan = read(PLAN)
    out = Path(out); out.mkdir(parents=True, exist_ok=False)
    runtime = code_hash()
    save(out / 'PLAN.json', plan)
    save(out / 'INPUTS.json', suite)
    save(out / 'PRE_SELECTION.json', {'schema': 'eb.ab_static_preselection.v1', 'plan_sha256': sha(PLAN),
        'inputs_sha256': digest(suite), 'implementation_sha256': runtime, 'selection_created': False,
        'prior_B_outcomes_read': False, 'seed': plan['seed'], 'physics_required': False})
    cached = read(generated_index) if generated_index else {}
    unique, generation, sources = {}, [], []
    originals = {}
    for ref in suite['records']:
        rid = ref['reference_id']; c = contexts[rid]
        for variant in plan['variants']:
            key = rid + '/' + variant['id']
            result = read(cached[key]) if key in cached else generate(c, variant['overrides'])
            require(result['rules_sha256'] == digest({**DEFAULT_RULES, **variant['overrides']}), 'STATIC_CACHED_RULES_MISMATCH')
            require(result['context_sha256'] == digest(c), 'STATIC_CACHED_CONTEXT_MISMATCH')
            originals[(rid, variant['id'])] = result
            generated_rows = catalogue({c['case_id']: c}, {variant['id']: {c['case_id']: result}}, stress_admissions=[])
            for row in generated_rows:
                row['reference_id'] = rid
                row['physical_baseline_status'] = ref['physical_baseline_status']
                for alias in row['aliases']:
                    alias['reference_id'] = rid
                if row['sample_id'] in unique:
                    prior = unique[row['sample_id']]
                    require(prior['features'] == row['features'] and prior['static_issues'] == row['static_issues'], 'STATIC_ALIAS_CONFLICT')
                    prior['aliases'].extend(row['aliases'])
                else:
                    unique[row['sample_id']] = row
            sources.append({'reference_id': rid, 'variant': variant['id'], 'context_sha256': digest(c),
                'generated_payload_sha256': digest(result), 'singles': len(result['candidates']),
                'joints': len(result['joint_candidates']), 'physical_baseline_status': ref['physical_baseline_status']})
            generation.append({'reference_id': rid, 'variant': variant['id'],
                'program_shift_domain': result['program_shift_domain'], 'joint_search_coverage': result['joint_search_coverage']})
            print('static catalogue complete ' + rid + ': ' + str(len(generated_rows)), flush=True)
    require(code_hash() == runtime, 'STATIC_IMPLEMENTATION_CHANGED_DURING_BUILD')
    rows = sorted(unique.values(), key=lambda r: r['sample_id'])
    # This is the one draw: fixed input, plan, first-match ownership and hash
    # priorities. Deficits never trigger retries or changes to the catalogue.
    selection = sample_catalogue(rows, plan)
    selection.update(schema='eb.ab_final_static_selection.v1', plan_sha256=sha(PLAN),
        implementation_sha256=runtime, static_scope=True, B_executed=False,
        physical_acceptance_inferred=False, final_B_outcomes_available=False)
    requests = []
    for sample in selection['records']:
        alias = min(sample['aliases'], key=lambda a: (a['reference_id'], a['variant'], digest(a)))
        result = originals[(alias['reference_id'], alias['variant'])]
        singles = {r['id']: r for r in result['candidates']}
        override = alias['override']
        if 'candidate_id' in override:
            request = singles[override['candidate_id']]; children = [request]
        elif 'joint_id' in override:
            request = next(r for r in result['joint_candidates'] if r['id'] == override['joint_id'])
            children = [singles[i] for i in request['candidate_ids']]
        else:
            require(override.get('baseline_control') is True, 'UNKNOWN_STATIC_OVERRIDE')
            request, children = {'patches': [], 'static_issues': []}, []
        requests.append({'sample_id': sample['sample_id'], 'reference_id': alias['reference_id'],
            'patches': request['patches'], 'children': children, 'generation_static_issues': request['static_issues']})
    audits = audit_selected(selection['records'], requests, contexts)
    index = [compact(r) for r in rows]
    result = coverage_result(index, selection, audits)
    result['generation_coverage_passed'] = all(r['joint_search_coverage']['coverage_passed'] and r['program_shift_domain']['complete_within_radius'] for r in generation)
    result['passed'] = result['integrity_passed'] and result['required_strata_passed'] and result['generation_coverage_passed']
    for name, payload in [('CATALOGUE_INDEX.json', index), ('SELECTION.json', selection),
                          ('SELECTED_REQUESTS.json', requests), ('SELECTED_AUDIT.json', audits),
                          ('GENERATION_SOURCES.json', sources), ('GENERATION_COVERAGE.json', generation), ('RESULT.json', result)]:
        save(out / name, payload)
    lines = ['# Final static stratified sampling', '',
        '| Stratum | Matched unique | Assigned unique | Requested | Selected | Deficit |',
        '|---|---:|---:|---:|---:|---:|']
    for r in result['coverage']:
        lines.append('| {stratum} | {matched_unique} | {assigned_unique} | {requested} | {selected} | {deficit} |'.format(**r))
    lines += ['', 'Static contract passed: ' + str(result['passed']),
        'Missing one/two-axis level combinations: ' + str(len(result['missing_interactions'])),
        'All deficits and all invalid catalogue entries are retained. No B execution; no outcome-based replacement.', '']
    (out / 'COVERAGE.md').write_text('\n'.join(lines))
    # Retention references are written only after the draw; historical B
    # outcomes never enter candidate features, ownership or priorities.
    retained = {'schema': 'eb.ab_static_retained_history.v1', 'not_selection_inputs': True,
        'files': {name: sha(ROOT / name) for name in ('A_STATUS.json', '../joint_tail/RESULT.json',
                                                   '../joint_tail/frozen_sample/SELECTION.json')},
        'meaning': 'all original failures,no-response and invalid samples remain in their original version;winter A failure remains separately labelled'}
    save(out / 'RETAINED_HISTORY.json', retained)
    seal(out, {'schema': 'eb.ab_final_static_sample.v1', 'implementation_sha256': runtime,
        'selection_sha256': sha(out / 'SELECTION.json'), 'plan_sha256': sha(PLAN), 'new_engine_runs': 0})
    return {k: result[k] for k in ('passed', 'catalogue_unique', 'selected', 'required_deficits', 'covered_interaction_levels', 'interaction_levels')}


def recheck(folder, out, require_coverage=False):
    """Replay only the frozen draw and independently check selected full plans."""
    folder = Path(folder); manifest = verify(folder)
    suite, contexts = inputs()
    require(read(folder / 'INPUTS.json') == suite, 'FINAL_STATIC_INPUTS_CHANGED')
    plan = read(folder / 'PLAN.json')
    require(plan == read(PLAN) and sha(folder / 'PLAN.json') == manifest['plan_sha256'], 'FINAL_STATIC_PLAN_CHANGED')
    freeze = read(folder / 'PRE_SELECTION.json')
    require(freeze['plan_sha256'] == manifest['plan_sha256'] and freeze['inputs_sha256'] == digest(suite)
            and freeze['seed'] == plan['seed'] and freeze['selection_created'] is False
            and freeze['prior_B_outcomes_read'] is False, 'FINAL_STATIC_FREEZE_CHANGED')
    require(sha(folder / 'SELECTION.json') == manifest['selection_sha256'], 'FINAL_STATIC_SELECTION_CHANGED')
    rows, selected = read(folder / 'CATALOGUE_INDEX.json'), read(folder / 'SELECTION.json')
    require(selected['implementation_sha256'] == freeze['implementation_sha256'] == manifest['implementation_sha256'],
            'FINAL_STATIC_IMPLEMENTATION_RECEIPT_CHANGED')
    retained = read(folder / 'RETAINED_HISTORY.json')
    require(all(sha(bound(ROOT.parent, 'gap_supplement/' + name)) == expected
                for name, expected in retained['files'].items()), 'RETAINED_HISTORY_CHANGED')
    replay = sample_catalogue(rows, plan)
    keys = lambda x: [(r['sample_id'], r['stratum']) for r in x['records']]
    require(keys(replay) == keys(selected) and replay['coverage'] == selected['coverage'], 'FINAL_STATIC_DRAW_MISMATCH')
    audits = audit_selected(selected['records'], read(folder / 'SELECTED_REQUESTS.json'), contexts)
    require(audits == read(folder / 'SELECTED_AUDIT.json'), 'FINAL_STATIC_AUDIT_CHANGED')
    actual = coverage_result(rows, replay, audits)
    expected = read(folder / 'RESULT.json')
    require(all(actual[k] == expected[k] for k in actual), 'FINAL_STATIC_COVERAGE_CHANGED')
    generation = read(folder / 'GENERATION_COVERAGE.json')
    sources = read(folder / 'GENERATION_SOURCES.json')
    generation_passed = all(r['joint_search_coverage']['coverage_passed']
                            and r['program_shift_domain']['complete_within_radius'] for r in generation)
    require(len(generation) == len(sources) == len(suite['records']) * len(plan['variants'])
            and sum(r['alias_count'] for r in rows) == sum(r['singles'] + r['joints'] + 1 for r in sources)
            and all(r['context_sha256'] == digest(contexts[r['reference_id']]) for r in sources),
            'FINAL_STATIC_SOURCE_ACCOUNTING_CHANGED')
    require(expected['generation_coverage_passed'] == generation_passed
            and expected['passed'] == (actual['integrity_passed'] and actual['required_strata_passed'] and generation_passed),
            'FINAL_STATIC_ACCEPTANCE_CHANGED')
    result = {'schema': 'eb.ab_final_static_recheck.v1', 'passed': actual['integrity_passed'],
        'required_coverage_passed': expected['passed'], 'required_deficits': actual['required_deficits'],
        'selection_identical': True, 'selected_full_plans_rechecked': len(audits), 'new_engine_runs': 0,
        'new_catalogue_or_outcome_reselection': False}
    save(Path(out) / 'CHECKS.json', result)
    require(result['passed'] and (not require_coverage or result['required_coverage_passed']), 'FINAL_STATIC_CHECK_FAILED;retain_deficits;do_not_reselect')
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(__doc__); p.add_argument('mode', choices=('build', 'recheck'))
    p.add_argument('--generated-index', type=Path); p.add_argument('--sample', type=Path, default=ROOT / 'final_sample')
    p.add_argument('--out', type=Path, required=True); p.add_argument('--require-coverage', action='store_true')
    a = p.parse_args()
    print(build(a.out, a.generated_index) if a.mode == 'build' else recheck(a.sample, a.out, a.require_coverage))
