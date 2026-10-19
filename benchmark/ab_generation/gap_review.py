"""Diagnose fixed-frame gaps; build a separate, preregistered A-only supplement."""
import argparse
import copy
import itertools
from collections import Counter
from pathlib import Path

from .common import bound, code_hash, digest, read, save, seal, sha, verify
from .generate import DEFAULT_RULES, program_candidates, program_domain_coverage, thermal_candidates
from .joint import build_joint, unit_key
from .joint_review import runtime_identity
from .life import require

HERE = Path(__file__).parent


def program_projection(context, radius=120):
    """Keep every row that can meet a moved chain; this is an audit view only.

    The full context remains the final checker and the identity used in receipts.
    No projection is exported to simulation or used as a replacement A.
    """
    c = copy.deepcopy(context)
    lo, hi = c['decision_min'] - radius, c['horizon_min'][1] + radius + 1440
    for key in ('tasks', 'operations', 'controls'):
        c['A'][key] = [r for r in c['A'][key] if r['end_min'] > lo and r['start_min'] < hi]
    c['needs'] = [n for n in c['needs'] if n['deadline_min'] > lo and n['release_min'] < hi]
    return c


def program_audit(context, shifts):
    """Finite domain enumeration, without policy winners or B outcomes."""
    c = program_projection(context, max(map(abs, shifts)))
    rules = {**DEFAULT_RULES, 'program_shifts_min': shifts}
    rows = [r for d in c['devices'] if 'washer' in d['types']
            for r in program_candidates(c, d, rules)[0]]
    pairs = [build_joint(c, [a, b]) for a, b in itertools.combinations(rows, 2)
             if unit_key(a) != unit_key(b)]
    valid = [r for r in rows if not r['static_issues']]
    valid_pairs = [r for r in pairs if not r['static_issues']]
    # Constructive witnesses are rechecked against the complete original A.
    by_id = {r['id']: r for r in rows}
    for children in [[r] for r in valid] + [[by_id[i] for i in r['candidate_ids']] for r in valid_pairs]:
        require(not build_joint(context, children)['static_issues'], 'AUDIT_PROJECTION_FALSE_WITNESS')
    positive = [r for r in rows if r['prediction']['delta_cost'] is not None and r['prediction']['delta_cost'] > 1e-9]
    def counts(rr):
        return dict(Counter(i for r in rr for i in r['static_issues']))
    return {'shifts_min': shifts, 'single_count': len(rows), 'positive_cost_count': len(positive),
            'valid_single_count': len(valid), 'valid_positive_cost_count': sum(r in positive for r in valid),
            'positive_cost_rejection_issues': counts(positive), 'two_job_product_count': len(pairs),
            'valid_two_job_count': len(valid_pairs), 'two_job_rejection_issues': counts(pairs),
            'valid_singles': [{k: r[k] for k in ('id', 'factors', 'prediction')} for r in valid],
            'valid_two_job_witnesses': valid_pairs,
            'full_context_witness_recheck': True, 'B_outcomes_read': False}


def diagnose(out):
    """Only public frozen A + frozen catalogue metadata are inputs."""
    root = HERE / 'validation/joint_tail/frozen_inputs'
    refs = read(root / 'REFERENCES.json') if (root / 'REFERENCES.json').exists() else read(HERE / 'examples/joint_tail/references.json')
    catalogue = read(HERE / 'validation/joint_tail/CATALOGUE_INDEX.json')
    if isinstance(catalogue, dict):
        catalogue = catalogue['records']
    results = []
    for ref in refs['records']:
        folder = bound(root, ref['path']) / 'contexts'
        verify(folder); batch = read(folder / 'BATCH.json')
        for row in batch['records']:
            c = read(bound(folder, row['context']))
            heating = [r.get('axis_electric_kWh', {}).get('heating', 0)
                       for state in c['reference']['thermal'].values() for r in state
                       if any(e['start_min'] <= r['minute'] < e['end_min'] for e in c['events'])]
            item = {'reference_id': ref['id'], 'context_sha256': digest(c), 'date': c['date'],
                    'heating_event_native_kWh': sum(heating),
                    'coarse': program_audit(c, DEFAULT_RULES['program_shifts_min'])}
            if ref['id'] in ('family_base', 'family_multibatch', 'studio_wide'):
                item['fine'] = program_audit(c, [v for v in range(-120, 121, 10) if v])
            results.append(item)
            print('gap diagnosis ' + ref['id'], flush=True)
    out = Path(out); out.mkdir(parents=True, exist_ok=False)
    save(out / 'RESULT.json', {'schema': 'eb.ab_gap_diagnosis.v1', 'records': results,
        'source_commit': '9c29521252c18e310a7894e1dcd42be27b9167ec', 'catalogue_rows': len(catalogue),
        'old_result_sha256': sha(HERE / 'validation/joint_tail/RESULT.json'),
        'old_selection_sha256': sha(HERE / 'validation/joint_tail/frozen_sample/SELECTION.json'),
        'scope': 'finite declared shifts and rigid handling modes;not continuous/global infeasibility',
        'B_outcomes_read': False})
    seal(out, {'schema': 'eb.ab_gap_diagnosis.v1'})


def scenario(item):
    """Apply declared upstream factors before life generation; A sees no prices/events."""
    batch = read(HERE / 'examples/strategy_review/life_batch.json')
    worlds = read(HERE / 'examples/life/world_contracts.json')
    experiments = read(HERE / 'examples/strategy_review/experiments.json')
    spec = next(s for s in batch['households'] if s['household_id'] == item['household_id'])
    experiment = next(c for c in experiments['records'] if c['case_id'] == item['base_experiment_case_id'])
    spec.update(anchor=item['anchor'], end_exclusive=item['end_exclusive'])
    for policy in spec['program_policies']:
        if policy['kind'] == 'washer':
            policy['daily_quantity_kg'] = item['textile_kg']
        if policy['kind'] in ('washer', 'dryer'):
            policy['preferred_start_min']['weekend'] = item['weekend_preferred_start_min'][policy['kind']]
    experiment.update(case_id=item['id'], date=item['date'])
    experiment['events'] = item['events']
    experiment['tariff'] = item['tariff']
    experiment['tariff_provenance'] = {'currency': 'CNY', 'experimental_scenario': True,
        'id': item['id'] + ':declared_tariff', 'origin': 'project-designed fixed experimental contrast;not live or household tariff'}
    batch['households'] = [spec]; experiments['records'] = [experiment]
    return batch, worlds, experiments


def reference(plan_path, energyplus_dir, out):
    from .life_pipeline import build_life
    from .life_physics import assemble_life, bind_life_worlds, reference_life
    from benchmark.housing_simulation.pipeline import build_shell, compile_pairs, run_pairs
    from benchmark.housing_simulation.validation import audit
    plan, out = read(plan_path), Path(out)
    require(plan['schema'] == 'eb.ab_gap_supplement.plan.v1', 'UNKNOWN_GAP_PLAN')
    out.mkdir(parents=True, exist_ok=False)
    engine = Path(energyplus_dir) / 'energyplus'
    weather = Path(energyplus_dir) / 'WeatherData/USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw'
    source = {'plan_sha256': sha(plan_path), 'code_sha256': code_hash(), 'runtime_sha256': runtime_identity(),
              'engine_sha256': sha(engine), 'weather_sha256': sha(weather)}
    save(out / 'PLAN.json', plan); save(out / 'SOURCE.json', source)
    build_shell(HERE.parent / 'housing_simulation/examples/shell_batch.json', out / 'shells')
    records = []
    for item in plan['cases']:
        require(runtime_identity() == source['runtime_sha256'], 'GAP_REFERENCE_RUNTIME_CHANGED')
        folder = out / item['id']; folder.mkdir()
        batch, worlds, experiments = scenario(item)
        save(folder / 'world_contracts.json', worlds)
        bind_life_worlds(folder / 'world_contracts.json', out / 'shells', folder / 'world_binding')
        batch['worlds'] = {'path': 'world_binding/resource_worlds.json', 'sha256': sha(folder / 'world_binding/resource_worlds.json')}
        save(folder / 'life_batch.json', batch); save(folder / 'experiments.json', experiments)
        ll = build_life(folder / 'life_batch.json', folder / 'life')
        record = {'id': item['id'], 'life_status': ll['records'][0]['status'], 'engine_arms': 0}
        if not ll['all_A_constructed']:
            record['status'] = 'unserved_A_retained'
        else:
            assembled = assemble_life(folder / 'life', folder / 'world_contracts.json', out / 'shells', weather, folder / 'experiments.json', folder / 'assembled')
            require(all(r['status'] == 'assembled' for r in assembled['records']), 'GAP_ASSEMBLY_FAILED')
            compiled = compile_pairs((folder / 'assembled/physics_job.json').resolve(), folder / 'baseline_compiled')
            require(all(r['status'] == 'compiled' for r in compiled['records']), 'GAP_COMPILATION_FAILED')
            ran = run_pairs(folder / 'baseline_compiled', folder / 'baseline_runs', engine, source['engine_sha256'], 300)
            record['engine_arms'] = len(ran['records'])
            aa = audit(folder / 'baseline_compiled', folder / 'baseline_runs', folder / 'baseline_audit')
            record['baseline_audit'] = aa
            if aa['passed']:
                reference_life(folder / 'assembled', folder / 'baseline_compiled', folder / 'baseline_runs', folder / 'contexts', folder / 'baseline_audit')
                record['status'] = 'A_reference_ready'
            else:
                record['status'] = 'baseline_failure_retained'
        records.append(record); save(out / 'PROGRESS.json', records)
        print(item['id'] + ': ' + record['status'], flush=True)
    save(out / 'RESULT.json', {'schema': plan['schema'], 'records': records, **source,
        'B_executed': False, 'outcome_reselection': False, 'online_questionnaire_changed': False, 'master1000_simulation_started': False})
    seal(out, {'schema': plan['schema'], **source})


def prepare(root, out):
    """Account every planned A; failed A is retained and earns no B credit."""
    from .life_physics import context_from_A
    root, out = Path(root), Path(out)
    verify(root); result = read(root / 'RESULT.json'); plan = read(root / 'PLAN.json')
    tail = read(HERE / 'examples/gap_supplement/tail_plan.json')
    require(all(program_domain_coverage({**DEFAULT_RULES, **v['overrides']})['complete_within_radius']
                for v in tail['variants']), 'SUPPLEMENT_PROGRAM_GRID_INCOMPLETE')
    out.mkdir(parents=True, exist_ok=False)
    admitted, failed, diagnostics, comparisons = [], [], [], []
    for row in result['records']:
        if row['status'] == 'A_reference_ready':
            admitted.append({'id': row['id'], 'path': row['id']})
            original = {'summer_base_grid': 'family_base', 'summer_multibatch_grid': 'family_multibatch'}.get(row['id'])
            if original:
                def ctx(folder):
                    batch = read(folder / 'BATCH.json')
                    return read(bound(folder, batch['records'][0]['context']))
                old = ctx(HERE / 'validation/joint_tail/frozen_inputs' / original / 'contexts')
                new = ctx(root / row['id'] / 'contexts')
                from .sampling import command_hash
                comparison = {'reference_id': row['id'], 'original_reference_id': original,
                    'life_input_identical': old['source']['life_input_sha256'] == new['source']['life_input_sha256'],
                    'A_commands_identical': command_hash(old['A']) == command_hash(new['A'])}
                require(all(comparison[k] for k in ('life_input_identical', 'A_commands_identical')), 'SUMMER_A_CHANGED')
                comparisons.append(comparison)
        else:
            failed.append(row)
            folder = root / row['id']
            if not (folder / 'assembled/CASE_INDEX.json').exists():
                continue
            for item in read(folder / 'assembled/CASE_INDEX.json')['records']:
                rid = item['id']; pair = read(bound(folder / 'assembled', item['pair']['path']))
                pack = read(bound(folder / 'assembled', item['household']['path']))
                meta = read(folder / 'baseline_compiled' / rid / 'A/INPUT.json.gz')
                trace = read(folder / 'baseline_runs' / rid / 'A/TRACE.json.gz')
                # For diagnosis only. Never install an admitted-context receipt.
                c = context_from_A(pair, pack, meta, trace, item['experiment'],
                    {'initialization': {'history_days': meta['history_days'], 'run_interval_min': meta['run_interval_min']}})
                thermal = [r for d in c['devices'] if 'ac' in d['types']
                           for r in thermal_candidates(c, d, DEFAULT_RULES)[0]]
                heating = [r for r in thermal if r['factors']['thermal_axis'] == 'heating']
                diagnostics.append({'reference_id': row['id'], 'A_admitted': False, 'B_executed': False,
                    'heating_candidates': len(heating),
                    'heating_supported': sum(r['opportunity']['status'] == 'supported' for r in heating),
                    'heating_static_valid': sum(not r['static_issues'] for r in heating),
                    'event_heating_kWh': sum(r.get('axis_electric_kWh', {}).get('heating', 0)
                        for state in c['reference']['thermal'].values() for r in state
                        if any(e['start_min'] <= r['minute'] < e['end_min'] for e in c['events'])),
                    'coverage_credit': False})
    save(out / 'REFERENCES.json', {'schema': 'eb.ab_joint_tail.references.v1', 'records': admitted,
        'information': 'A-admission gate only;all planned cases separately accounted;no B outcomes read'})
    save(out / 'A_STATUS.json', {'planned': len(plan['cases']), 'admitted': len(admitted),
        'failed_retained': failed, 'summer_A_comparisons': comparisons, 'unadmitted_diagnostics': diagnostics,
        'all_planned_accounted': len(admitted) + len(failed) == len(plan['cases']),
        'all_planned_A_admitted': not failed, 'reference_manifest_sha256': sha(root / 'MANIFEST.json'),
        'B_outcomes_read': False, 'replacement_scenarios_added': False})
    seal(out, {'schema': 'eb.ab_gap_A_admission.v1'})


if __name__ == '__main__':
    p = argparse.ArgumentParser(__doc__); p.add_argument('mode', choices=('diagnose', 'reference', 'prepare'))
    p.add_argument('--plan', type=Path, default=HERE / 'examples/gap_supplement/scenarios.json')
    p.add_argument('--energyplus-dir', type=Path); p.add_argument('--reference-root', type=Path)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    if a.mode == 'diagnose': diagnose(a.out)
    elif a.mode == 'reference': reference(a.plan, a.energyplus_dir, a.out)
    else: prepare(a.reference_root, a.out)
