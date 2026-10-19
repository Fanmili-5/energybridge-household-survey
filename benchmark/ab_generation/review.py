"""Predeclared strategy comparison and boundary probes; no outcome reselection."""
from pathlib import Path
from .common import read, save, seal, sha, verify
from .evaluate import summarize
from .generate import DEFAULT_RULES, disruption
from .life import require
from .life_pipeline import build_life
from .life_physics import assemble_life, bind_life_worlds, export_life, reference_life


def reproduce_strategies(input_path, world_contracts, shell_config, experiments, energyplus_dir, out, plan_path=None):
    from .__main__ import build_batch
    from benchmark.housing_simulation.pipeline import build_shell, compile_pairs, run_pairs
    from benchmark.housing_simulation.validation import audit
    input_path, world_contracts, shell_config, experiments, energyplus_dir, out = map(Path,
        (input_path, world_contracts, shell_config, experiments, energyplus_dir, out))
    plan = read(plan_path) if plan_path else {'schema': 'eb.ab_strategy_review.v1',
        'policies': DEFAULT_RULES['selection_policies'], 'comparison_case_ids': [r['case_id'] for r in read(experiments)['records']],
        'probe_case_ids': [], 'probe_families': [], 'departure_target_failure_probe': False}
    require(plan['schema'] == 'eb.ab_strategy_review.v1' and set(plan['policies']) <= set(DEFAULT_RULES['selection_policies']), 'UNKNOWN_REVIEW_PLAN')
    out.mkdir(parents=True, exist_ok=False)
    save(out / 'REVIEW_PLAN.json', plan); save(out / 'EXPERIMENTS.json', read(experiments))
    ep = energyplus_dir.resolve(); engine = ep / 'energyplus'
    weather = ep / 'WeatherData/USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw'
    stages, assessments = [], []
    shell = build_shell(shell_config.resolve(), out / 'shells')
    require(all(r['status'] == 'shell_compiled' for r in shell['records']), 'SHELL_BUILD_FAILED')
    bind_life_worlds(world_contracts, out / 'shells', out / 'world_binding')
    life = build_life(input_path, out / 'life'); require(life['all_A_constructed'], 'LIFE_REQUIREMENTS_UNSERVED')
    require(read(out / 'life/WORLD_INPUT.json') == read(out / 'world_binding/resource_worlds.json'), 'DECLARED_WORLD_RESOURCE_NOT_REPRODUCED')
    assembled = assemble_life(out / 'life', world_contracts, out / 'shells', weather, experiments, out / 'assembled')
    require(all(r['status'] == 'assembled' for r in assembled['records']), 'LIFE_PHYSICS_ASSEMBLY_FAILED')
    def execute(label, folder, expected_target_failure=False):
        compiled, runs, audits = (out / (label + suffix) for suffix in ('_compiled', '_runs', '_audit'))
        cc = compile_pairs((folder / 'physics_job.json').resolve(), compiled)
        require(all(r['status'] == 'compiled' for r in cc['records']), 'COMPILATION_FAILED:' + label)
        rr = run_pairs(compiled, runs, engine, sha(engine), 300)
        require(all(r['status'] == 'completed' for r in rr['records']), 'ENGINE_RUN_FAILED:' + label)
        aa = audit(compiled, runs, audits)
        stages.append({'stage': label, 'engine_arms': len(rr['records']), 'audit_passed': aa['passed'],
                       'predeclared_target_failure': expected_target_failure})
        if label == 'baseline':
            require(aa['passed'], 'BASELINE_AUDIT_FAILED')
            return
        report = out / (label + '_report')
        summarize(folder / 'physics_job.json', compiled, runs, audits, report,
                  imported=out / 'contexts', reference_runs=out / 'baseline_runs')
        data = read(report / 'REPORT.json')
        binding_passed = all(r['readback_status'] == 'complete' and r['A_reference_comparison']['passed'] for r in data['records'])
        if expected_target_failure:
            valid = (len(aa['records']) == 1 and {k for k, v in aa['records'][0]['checks'].items() if not v} == {'B_EV_departure_target'}
                     and aa['records'][0]['checks'].get('B_EV_balance') is True
                     and binding_passed)
        else:
            from .sampling import SERVICE_FAILURES
            failures = {k for r in aa['records'] for k, v in r['checks'].items() if not v}
            valid = not failures - SERVICE_FAILURES and binding_passed
        assessments.append({'stage': label, 'passed_expected_checks': valid, 'cases': len(data['records']),
                            'report_sha256': sha(report / 'REPORT.json'), 'records': data['records']})
    execute('baseline', out / 'assembled')
    reference_life(out / 'assembled', out / 'baseline_compiled', out / 'baseline_runs', out / 'contexts', out / 'baseline_audit')
    build_batch(out / 'contexts/BATCH.json', out / 'candidates')
    batch = read(out / 'contexts/BATCH.json'); generation = verify(out / 'candidates')
    contexts = {r['case_id']: read(out / 'contexts' / r['context']) for r in batch['records']}
    results = {r['case_id']: read(out / 'candidates' / r['path']) for r in generation['records']}
    comparison = []
    for policy in plan['policies']:
        label = 'selected_B' if policy == 'known_profile_vpp' else policy
        export_life(out / 'assembled', out / 'contexts', out / 'candidates', policy, out / label, plan['comparison_case_ids'])
        execute(label, out / label)
    for case_id in plan['comparison_case_ids']:
        selections = results[case_id]['selections']
        comparison.append({'case_id': case_id, 'distinct_B_commands': len({selections[p]['B_commands_sha256'] for p in plan['policies']}),
                           'policies': {p: {k: v for k, v in selections[p].items() if k != 'plan_B'} for p in plan['policies']}})
    # Probe selection sees only A, declared rules and static candidate properties.
    for family in plan['probe_families']:
        available = [(case_id, c) for case_id in plan['probe_case_ids'] for c in results[case_id]['candidates']
                     if c['family'] == family and not c['static_issues']
                     and (family not in plan.get('probe_axes', {}) or c['factors'].get('thermal_axis') == plan['probe_axes'][family])
                     and (family not in plan.get('probe_directions', {}) or c['factors'].get('direction') == plan['probe_directions'][family])]
        require(available, 'REQUIRED_DEVICE_PROBE_UNAVAILABLE:' + family)
        def dose(item):
            case_id, c = item; f = c['factors']
            return (f['setpoint_delta_C'], f.get('available_duration_min', 0),
                    abs(f['program_shift_min']), disruption(c), case_id, c['id'])
        case_id, probe = min(available, key=dose); label = 'probe_' + family
        override = {case_id: {'candidate_id': probe['id']}}
        save(out / (label + '_selection.json'), {'case_id': case_id, 'candidate_id': probe['id'], 'factors': probe['factors'],
                                               'criterion': 'minimum_predeclared_dose_then_stable_id;no_B_outcomes'})
        export_life(out / 'assembled', out / 'contexts', out / 'candidates', 'known_profile_vpp', out / label, [case_id], override)
        execute(label, out / label)
    if plan.get('joint_probe'):
        choices = [(case_id, c) for case_id in plan['probe_case_ids'] for c in results[case_id]['joint_candidates'] if not c['static_issues']]
        require(choices, 'REQUIRED_JOINT_PROBE_UNAVAILABLE')
        case_id, joint = min(choices, key=lambda x: (x[0], x[1]['id']))
        label = 'probe_joint'
        save(out / (label + '_selection.json'), {'case_id': case_id, 'joint_id': joint['id'],
                                               'criterion': 'first_declared_case_and_stable_joint_id;no_B_results'})
        export_life(out / 'assembled', out / 'contexts', out / 'candidates', 'known_profile_vpp', out / label, [case_id],
                    {case_id: {'joint_id': joint['id']}})
        execute(label, out / label)
    if plan['departure_target_failure_probe']:
        options = []
        for case_id in plan['comparison_case_ids']:
            context = contexts[case_id]
            for d in context['devices']:
                if 'ev' not in d['types']:
                    continue
                controls = [c for c in context['A']['controls'] if c['asset_id'] == d['asset_id'] and c['kind'] == 'ev_charge_window']
                for nid in {c['need_id'] for c in controls}:
                    steps = [s for s in context['reference']['ev_charging_steps'] if s['need_id'] == nid and context['decision_min'] <= s['start_min'] < context['horizon_min'][1]]
                    if steps and sum(s['grid_kWh'] for s in steps) > d['parameters']['charger_kw'] / 6 + 1e-8:
                        end = max(c['end_min'] for c in controls if c['need_id'] == nid)
                        delay = end - 10 - min(s['start_min'] for s in steps)
                        if delay > 0:
                            options.append((case_id, nid, delay))
        require(options, 'FAILURE_PROBE_HAS_NO_REAL_REMAINING_CHARGE')
        case_id, nid, delay = min(options)
        rules = {**DEFAULT_RULES, 'ev_delays_min': [delay]}; save(out / 'failure_rules.json', rules)
        build_batch(out / 'contexts/BATCH.json', out / 'failure_candidates', out / 'failure_rules.json')
        fm = verify(out / 'failure_candidates'); record = next(r for r in fm['records'] if r['case_id'] == case_id)
        candidates = read(out / 'failure_candidates' / record['path'])['candidates']
        probe = next(c for c in candidates if c['family'] == 'ev' and c['factors']['need_id'] == nid)
        label = 'probe_departure_target_failure'
        override = {case_id: {'candidate_id': probe['id'], 'expected_static_issues': ['CHARGE_EXCEEDS_ORIGINAL_CONNECTION']}}
        save(out / (label + '_selection.json'), {'case_id': case_id, 'candidate_id': probe['id'], 'factors': probe['factors'],
                                               'criterion': 'leave_one_original_10min_charge_slot;failure_expected_before_execution'})
        export_life(out / 'assembled', out / 'contexts', out / 'failure_candidates', 'known_profile_vpp', out / label, [case_id], override)
        execute(label, out / label, True)
    passed = bool(assessments) and all(r['passed_expected_checks'] for r in assessments)
    result = {'schema': 'eb.ab_strategy_review.public_reproduction.v1', 'passed': passed, 'stages': stages,
              'comparisons': comparison, 'assessments': assessments, 'households': life['households'],
              'engine_arms': sum(s['engine_arms'] for s in stages), 'engine_sha256': sha(engine), 'weather_sha256': sha(weather),
              'historical_households_required': False, 'API_used': False, 'empirical_calibration_claimed': False,
              'human_acceptance_inferred': False, 'master1000_simulation_started': False}
    save(out / 'RESULT.json', result)
    seal(out, {'schema': result['schema'], 'passed': passed, 'engine_arms': result['engine_arms']})
    require(passed, 'STRATEGY_REVIEW_FAILED;inspect_RESULT_and_preserved_reports')
    return {k: v for k, v in result.items() if k not in ('comparisons', 'assessments')}
