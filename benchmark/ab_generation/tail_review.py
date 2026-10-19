"""Execute a sealed tail sample once, retaining adverse and incomplete outcomes."""
from pathlib import Path
from .common import bound, code_hash, digest, read, save, seal, sha, verify
from .evaluate import summarize
from .life_physics import export_life
from .sampling import command_hash, coverage_report, require, sample_tail


def reproduce_tail(reference_root, plan_path, energyplus_dir, out):
    from benchmark.housing_simulation.pipeline import compile_pairs, run_pairs
    from benchmark.housing_simulation.validation import audit
    reference_root, out, energyplus_dir = map(Path, (reference_root, out, energyplus_dir))
    # Existing A is reusable, including older generator versions: the exact input,
    # audit and native trace are bound. No old B is a sampling input.
    for name in ('assembled', 'contexts', 'baseline_compiled', 'baseline_runs', 'baseline_audit'):
        verify(reference_root / name)
    engine = energyplus_dir.resolve() / 'energyplus'
    baseline_runs = read(reference_root / 'baseline_runs/MANIFEST.json')
    require(all(read(reference_root / 'baseline_runs' / r['id'] / r['side'] / 'RESULT.json')['engine_sha256'] == sha(engine)
                for r in baseline_runs['records']), 'TAIL_REFERENCE_ENGINE_CHANGED')
    out.mkdir(parents=True, exist_ok=False)
    sample_tail(reference_root / 'contexts', plan_path, out / 'sample')
    selection = read(out / 'sample/SELECTION.json')
    observations, arms = [], 0
    # Selection, all quotas and aliases are sealed before the first B run.
    for sample in selection['records']:
        if sample['features']['admission'] == 'static_diagnostic':
            continue
        alias = sorted(sample['aliases'], key=lambda r: (r['variant'], digest(r)))[0]
        generated = out / 'sample/variants' / digest(alias['variant'])[:24]
        label = sample['sample_id'][:24]
        folder, compiled, runs, audits, report = (out / 'executions' / label / name for name in ('export', 'compiled', 'runs', 'audit', 'report'))
        export_life(reference_root / 'assembled', reference_root / 'contexts', generated, 'known_profile_vpp', folder,
                    [sample['case_id']], {sample['case_id']: alias['override']})
        job = read(folder / 'physics_job.json')
        pair = read(bound(folder, job['pairs'][0]['pair']['path']))
        exported = command_hash(pair['B'])
        require(exported == sample['B_commands_sha256'], 'TAIL_EXPORT_CHANGED_SELECTED_B')
        try:
            cc = compile_pairs((folder / 'physics_job.json').resolve(), compiled)
            require(all(r['status'] == 'compiled' for r in cc['records']), 'TAIL_COMPILE_FAILED;selection_preserved')
            rr = run_pairs(compiled, runs, engine, sha(engine), 300)
            arms += len(rr['records'])
            audit(compiled, runs, audits)
            summarize(folder / 'physics_job.json', compiled, runs, audits, report,
                      imported=reference_root / 'contexts', reference_runs=reference_root / 'baseline_runs')
            verify(report)
            data = read(report / 'REPORT.json')
            require(len(data['records']) == 1, 'TAIL_REPORT_CASE_COUNT')
            record = data['records'][0]
            receipt = sha(report / 'MANIFEST.json')
        except (ValueError, FileNotFoundError, KeyError) as error:
            # Preserve unknown/model failures and finish the frozen sample; never
            # substitute another B. The final acceptance still fails.
            record = {'case_id': sample['case_id'], 'readback_status': 'incomplete',
                      'error_type': type(error).__name__, 'error': str(error),
                      'human_acceptance': None, 'actual_results_used_for_reselection': False}
            receipt = None
        observations.append({'sample_id': sample['sample_id'], 'exported_B_commands_sha256': exported,
                             'export_manifest_sha256': sha(folder / 'MANIFEST.json'),
                             'report_manifest_sha256': receipt, 'report': record})
        save(out / 'OBSERVATIONS.json', observations)
    result = coverage_report(out / 'sample', observations)
    result.update({'code_sha256': code_hash(), 'engine_arms': arms, 'engine_sha256': sha(engine),
                   'reused_A_contexts_manifest_sha256': sha(reference_root / 'contexts/MANIFEST.json'),
                   'reused_baseline_runs_manifest_sha256': sha(reference_root / 'baseline_runs/MANIFEST.json'),
                   'baseline_reuse_not_new_A_calibration': True,
                   'master1000_simulation_started': False, 'production_inputs_modified': False})
    save(out / 'RESULT.json', result)
    lines = ['# Tail coverage verification', '', '| Stratum | Frame | Selected | Verified | Deficit | Pass |',
             '| --- | ---: | ---: | ---: | ---: | --- |']
    for r in result['coverage']:
        lines.append('| {stratum} | {assigned_unique} | {selected} | {verified} | {verification_deficit} | {passed} |'.format(**r))
    lines += ['', 'Diagnostic rows verify static rejection only. All other rows require bound native readback.',
              'Benefits, event success and human acceptance are not selection or ordinary admission conditions.',
              'Marginal/pairwise coverage is measured over this finite catalogue; no complete covering-array or population claim.', '']
    response = result['response_coverage']
    lines += ['## Per-target response coverage', '',
              'Patterns: ' + str(response['patterns']),
              'Changed device kinds: ' + str(response['actual_changed_kind_counts']),
              'Missing required kinds: ' + str(response['missing_changed_kinds']),
              'Screen-supported targets without observed response: ' + str(response['supported_no_response_fraction']),
              'All samples, including ineffective and failed requests, remain in RESULT.json. No replacement.', '']
    (out / 'COVERAGE.md').write_text('\n'.join(lines))
    seal(out, {'schema': result['schema'], 'code_sha256': code_hash(), 'passed': result['passed'],
               'engine_arms': arms, 'selection_manifest_sha256': sha(out / 'sample/MANIFEST.json')})
    require(result['passed'], 'TAIL_COVERAGE_FAILED;inspect_all_preserved_results;do_not_reselect')
    return {k: result[k] for k in ('passed', 'engine_arms', 'outcome_counts', 'master1000_simulation_started')}
