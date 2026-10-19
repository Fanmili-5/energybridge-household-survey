"""Finite, predeclared parameter perturbations; never replace a failed outcome."""
import argparse
import copy
import itertools
from collections import Counter, defaultdict
from pathlib import Path

from .common import code_hash, digest, read, save, seal, sha, verify
from .life import generate_household, require
from .energy import task_power

HERE = Path(__file__).parent
DEFAULT_PLAN = HERE / 'examples/sensitivity/plan.json'


def variants(plan):
    factors = plan['factors']
    base = {k: v['base'] for k, v in factors.items()}
    rows = [{'id': 'base', 'design': 'center', 'values': base}]
    for key, levels in factors.items():
        for level in ('low', 'high'):
            rows.append({'id': key + '_' + level, 'design': 'one_at_a_time',
                         'values': {**base, key: levels[level]}})
    for i, signs in enumerate(itertools.product(('low', 'high'), repeat=len(factors))):
        rows.append({'id': 'corner_%02d' % i, 'design': 'full_factorial',
                     'signs': {k: -1 if s == 'low' else 1 for k, s in zip(factors, signs)},
                     'values': {k: factors[k][s] for k, s in zip(factors, signs)}})
    for row in plan['supplementary']:
        rows.append({**row, 'values': {**base, **row['values']}})
    require(len({r['id'] for r in rows}) == len(rows), 'DUPLICATE_SENSITIVITY_VARIANT')
    return rows


def perturb(spec, world, values):
    """Change habits and hardware explicitly; move real return and calendar together."""
    spec, world = copy.deepcopy(spec), copy.deepcopy(world)
    for p in spec['program_policies']:
        if p['kind'] == 'washer':
            p['daily_quantity_kg'] = values['textile_kg']
            p['duration_min'] = values['washer_duration_min']
            p['daily_service'] = values.get('daily_service', True)
    for p in spec['thermostat_policies']:
        p['cooling_setpoint_C'] = values['cooling_C']
    for member in world['members']:
        member['hot_water_liters'] *= values['hot_water_scale']
    for d in world.get('devices', []):
        if d['kind'] == 'water_heater':
            d['parameters']['deadband_C'] = values.get('tank_deadband_C', 2)
    mobility = spec['mobility']; operator = spec['member_calendars'][mobility['operator_id']]
    journeys = mobility['journey_templates']
    for kind, trips in [(k, journeys[k]) for k in ('weekday', 'weekend')] + list(journeys.get('date_overrides', {}).items()):
        cal = operator.get('date_overrides', {})[kind] if kind not in ('weekday', 'weekend') else operator[kind]
        for trip in trips:
            old = trip['arrival_min']; new = old + values['ev_arrival_delta_min']
            away = next(e for e in cal if e['location'] == 'away' and e['end_min'] == old)
            home = next(e for e in cal if e['location'] == 'home' and e['start_min'] == old)
            require(away['start_min'] < new < home['end_min'], 'PERTURBED_RETURN_CROSSES_FIXED_ACTIVITY')
            away['end_min'], home['start_min'], trip['arrival_min'] = new, new, new
            if values.get('missing_ev_handler', False):
                home['available_for_operation'] = False
    return spec, world


def life_measurements(spec, world, result):
    needs = {n['need_id']: n for n in result['requirements']}
    tasks = result['A']['tasks']; ops = result['A']['operations']
    durations = {p['asset_id']: p['duration_min'] for p in spec['program_policies']}
    days = len(result['days']); checks = {}
    checks['complete_programs'] = all(t['end_min'] - t['start_min'] == durations[t['asset_id']] for t in tasks)
    checks['unique_tasks_and_operations'] = (len({t['task_id'] for t in tasks}) == len(tasks)
        and len({o['operation_id'] for o in ops}) == len(ops))
    resources = defaultdict(list)
    checks['operators_available'] = True
    for o in ops:
        resources['person:' + o['operator_id']].append((o['start_min'], o['end_min']))
        if o['kind'] not in ('EV_plug', 'EV_unplug'):
            resources['room:' + o['room_id']].append((o['start_min'], o['end_min']))
        checks['operators_available'] &= any(a <= o['start_min'] and o['end_min'] <= z
            for day in result['days'].values() for a, z in day['operator_windows'].get(o['operator_id'], []))
    checks['no_operator_or_manual_room_overlap'] = all(
        all(x[1] <= y[0] for x, y in zip(sorted(spans), sorted(spans)[1:])) for spans in resources.values())
    by_need = defaultdict(dict)
    for o in ops:
        by_need[o['need_id']][o['kind']] = o
    checks['release_deadline_waits_and_dependencies'] = True
    for t in tasks:
        n = needs[t['need_id']]; o = by_need[t['need_id']]; load, unload = o['load'], o['unload']
        valid = (n['release_min'] <= load['start_min'] and load['end_min'] <= t['start_min']
            and t['end_min'] <= unload['start_min'] and unload['end_min'] <= n['deadline_min']
            and t['start_min'] - load['end_min'] <= n['maximum_preload_wait_min']
            and unload['start_min'] - t['end_min'] <= n['maximum_retrieval_wait_min'])
        if t.get('depends_on_need_id'):
            valid &= by_need[t['depends_on_need_id']]['unload']['end_min'] <= load['start_min']
        checks['release_deadline_waits_and_dependencies'] &= valid
    laundry = next(p for p in spec['program_policies'] if p['kind'] == 'washer')
    served_kg = sum(needs[t['need_id']]['quantity'] for t in tasks if t['kind'] == 'washer')
    residual = result['remaining_unallocated_textile_kg'][laundry['service_id']]
    checks['textile_mass_balance'] = abs(served_kg + residual - laundry['initial_inventory_kg'] - days * laundry['daily_quantity_kg']) < 1e-7
    checks['batch_capacity'] = all(0 < needs[t['need_id']]['quantity'] <= laundry['capacity_kg'] + 1e-9 for t in tasks if t['kind'] == 'washer')
    checks['A_has_no_B_information'] = result['B_events_prices_or_answers_used'] is False
    eff = next(d['parameters']['efficiency'] for d in world['devices'] if d['kind'] == 'ev')
    return {'status': result['status'], 'days': days, 'checks': checks,
            'unserved_reasons': dict(Counter(r['reason'] for r in result['unserved'])),
            'cycles': dict(Counter(t['kind'] for t in tasks)), 'served_textile_kg': served_kg,
            'remaining_textile_kg': residual,
            'program_kWh': sum(task_power(t, next(d['parameters'] for d in world['devices'] if d['asset_id'] == t['asset_id'])) * (t['end_min'] - t['start_min']) / 60 for t in tasks),
            'washer_kWh': sum(task_power(t, next(d['parameters'] for d in world['devices'] if d['asset_id'] == t['asset_id'])) * (t['end_min'] - t['start_min']) / 60 for t in tasks if t['kind'] == 'washer'),
            'hot_outlet_liters': sum(n['quantity'] for n in result['requirements'] if n['kind'] == 'water_heater'),
            'manual_minutes': sum(o['end_min'] - o['start_min'] for o in ops),
            'ev_grid_kWh': sum(e['battery_kWh'] / eff for e in result['EV']['charge_events']),
            'ev_connection_minutes': sum(e['end_min'] - e['start_min'] for e in result['EV']['connections'])}


def screen(plan_path, out):
    out = Path(out); out.mkdir(parents=True, exist_ok=False)
    plan = read(plan_path); design = variants(plan)
    batch = read(HERE / 'examples/strategy_review/life_batch.json')
    worlds = read(HERE / 'examples/strategy_review/resource_worlds.json')
    rows = []
    save(out / 'FROZEN_PLAN.json', plan)
    for variant in design:
        for original in batch['households']:
            hid = original['household_id']
            world = next(w for w in worlds['households'] if w['household_id'] == hid)
            spec, changed = perturb(original, world, variant['values'])
            result = generate_household(spec, changed)
            path = 'raw/' + variant['id'] + '/' + hid + '.json.gz'
            save(out / path, {'spec': spec, 'world': changed, 'result': result})
            rows.append({'variant': variant['id'], 'design': variant['design'], 'household_id': hid,
                         'values': variant['values'], 'raw': path, 'raw_sha256': sha(out / path),
                         **life_measurements(spec, changed, result)})
        print('screen ' + variant['id'], flush=True)
    metrics = ('washer_kWh', 'program_kWh', 'manual_minutes', 'ev_grid_kWh', 'ev_connection_minutes', 'remaining_textile_kg')
    effects = []
    corners = {v['id']: v for v in design if v['design'] == 'full_factorial'}
    for hid in sorted({r['household_id'] for r in rows}):
        rr = [r for r in rows if r['household_id'] == hid and r['variant'] in corners]
        for size in (1, 2):
            for keys in itertools.combinations(plan['factors'], size):
                plus = [r for r in rr if product(corners[r['variant']]['signs'][k] for k in keys) == 1]
                minus = [r for r in rr if r not in plus]
                effects.append({'household_id': hid, 'factors': list(keys), 'contrast': 'mean(sign_product=+1)-mean(sign_product=-1)',
                    'effects': {m: sum(r[m] for r in plus) / len(plus) - sum(r[m] for r in minus) / len(minus) for m in metrics},
                    'unserved_cases_included': sum(r['status'] != 'A_constructed' for r in rr)})
    result = {'schema': 'eb.ab_parameter_sensitivity.screen.v1', 'plan_sha256': sha(plan_path), 'code_sha256': code_hash(),
        'variants': len(design), 'generation_cases': len(rows), 'unique_households': len(batch['households']),
        'invariants_passed': all(all(r['checks'].values()) for r in rows),
        'all_A_feasible': all(r['status'] == 'A_constructed' for r in rows), 'records': rows, 'factorial_contrasts': effects,
        'empirical_ranges_or_global_sensitivity_claimed': False, 'outcome_reselection': False}
    save(out / 'SCREEN.json', result); seal(out, {'schema': result['schema'], 'plan_sha256': sha(plan_path)})
    return result


def product(values):
    out = 1
    for value in values:
        out *= value
    return out


def choose_joint(result, panel):
    """Frozen A-only selector. Missing specified families is a result, not a fallback."""
    candidates = {c['id']: c for c in result['candidates']}
    eligible = []
    for joint in result['joint_candidates']:
        children = [candidates[i] for i in joint['candidate_ids']]
        if joint['static_issues'] or sorted(c['family'] for c in children) != sorted(panel['families']):
            continue
        if any((c['family'] in ('washer', 'dishwasher') and c['factors']['handling_mode'] != 'shift_chain')
               or (c['family'] in ('ac', 'water_heater') and c['factors']['direction'] != 'aligned')
               or (c['family'] == 'ac' and c['factors']['thermal_axis'] != 'cooling') for c in children):
            continue
        score = 0
        for c in children:
            f = c['factors']; family = c['family']
            if family in ('washer', 'dishwasher'):
                score += abs(f['program_shift_min'] - panel['program_shift_min'])
            elif family == 'ev':
                score += abs(f['ev_delay_min'] - panel['ev_delay_min'])
            else:
                score += 100 * abs(f['setpoint_delta_C'] - panel['thermal_delta_C'])
                score += abs(f['available_duration_min'] - panel['thermal_duration_min'])
        supported = sum(c['opportunity']['status'] == 'supported' for c in children)
        eligible.append((-supported, score, joint['id'], joint, children))
    if not eligible:
        return None
    _, score, _, joint, children = min(eligible, key=lambda r: r[:3])
    return {'joint_id': joint['id'], 'dose_distance': score,
            'children': [{k: c[k] for k in ('id', 'family', 'asset_id', 'factors', 'opportunity')} for c in children],
            'criterion': 'static-valid specified families;most A-supported children;nearest declared dose;stable id;no B results'}


def physics(plan_path, engine_dir, out):
    from .__main__ import build_batch
    from .evaluate import summarize
    from .life_pipeline import build_life
    from .life_physics import assemble_life, bind_life_worlds, export_life, reference_life
    from benchmark.housing_simulation.pipeline import build_shell, compile_pairs, run_pairs
    from benchmark.housing_simulation.validation import audit
    out = Path(out); out.mkdir(parents=True, exist_ok=False)
    plan = read(plan_path); design = {r['id']: r for r in variants(plan)}
    engine_dir = Path(engine_dir); engine = engine_dir / 'energyplus'
    weather = engine_dir / 'WeatherData/USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw'
    save(out / 'FROZEN_PLAN.json', plan)
    source = {'code_sha256': code_hash(), 'plan_sha256': sha(plan_path), 'engine_sha256': sha(engine), 'weather_sha256': sha(weather)}
    save(out / 'SOURCE.json', source)
    build_shell((HERE.parent / 'housing_simulation/examples/shell_batch.json').resolve(), out / 'shells')
    original_batch = read(HERE / 'examples/strategy_review/life_batch.json')
    original_worlds = read(HERE / 'examples/life/world_contracts.json')
    original_experiments = read(HERE / 'examples/strategy_review/experiments.json')
    records = []
    def execute(folder, label, request):
        cc = compile_pairs((request / 'physics_job.json').resolve(), folder / (label + '_compiled'))
        require(all(r['status'] == 'compiled' for r in cc['records']), 'SENSITIVITY_COMPILATION_FAILED')
        rr = run_pairs(folder / (label + '_compiled'), folder / (label + '_runs'), engine, source['engine_sha256'], 300)
        require(all(r['status'] == 'completed' for r in rr['records']), 'SENSITIVITY_ENGINE_FAILED')
        return audit(folder / (label + '_compiled'), folder / (label + '_runs'), folder / (label + '_audit')), len(rr['records'])
    for item in plan['physical_cases']:
        require(code_hash() == source['code_sha256'], 'SENSITIVITY_CODE_CHANGED_DURING_RUN')
        label, hid, variant = item['id'], item['household_id'], design[item['variant']]
        folder = out / label; folder.mkdir()
        batch, worlds = copy.deepcopy(original_batch), copy.deepcopy(original_worlds)
        spec = next(h for h in batch['households'] if h['household_id'] == hid)
        raw = next(w for w in worlds['households'] if w['household_id'] == hid)
        spec, raw = perturb(spec, raw, variant['values'])
        batch['households'] = [spec]
        worlds['households'] = [raw if w['household_id'] == hid else w for w in worlds['households']]
        save(folder / 'world_contracts.json', worlds)
        bind_life_worlds(folder / 'world_contracts.json', out / 'shells', folder / 'world_binding')
        batch['worlds'] = {'path': 'world_binding/resource_worlds.json', 'sha256': sha(folder / 'world_binding/resource_worlds.json')}
        save(folder / 'life_batch.json', batch)
        ll = build_life(folder / 'life_batch.json', folder / 'life')
        row = {**item, 'values': variant['values'], 'engine_arms': 0, 'life_status': ll['records'][0]['status']}
        if not ll['all_A_constructed']:
            row['status'] = 'unserved_A_retained'; row['unserved'] = read(folder / 'life' / ll['records'][0]['path'])['unserved']
        else:
            ex = copy.deepcopy(original_experiments)
            case = next(c for c in ex['records'] if c['case_id'] == item['experiment_case_id'])
            ex['records'] = [case]; save(folder / 'experiments.json', ex)
            assembled = assemble_life(folder / 'life', folder / 'world_contracts.json', out / 'shells', weather, folder / 'experiments.json', folder / 'assembled')
            require(all(r['status'] == 'assembled' for r in assembled['records']), 'SENSITIVITY_ASSEMBLY_FAILED')
            aa, arms = execute(folder, 'baseline', folder / 'assembled'); row['engine_arms'] += arms
            row['baseline_audit'] = aa
            if not aa['passed']:
                row['status'] = 'baseline_service_or_model_failure_retained'
            else:
                reference_life(folder / 'assembled', folder / 'baseline_compiled', folder / 'baseline_runs', folder / 'contexts', folder / 'baseline_audit')
                build_batch(folder / 'contexts/BATCH.json', folder / 'candidates')
                manifest = verify(folder / 'candidates')
                result = read(folder / 'candidates' / manifest['records'][0]['path'])
                row['device_opportunity_inventory'] = result['device_opportunity_inventory']
                row['candidate_counts'] = {'single': len(result['candidates']), 'single_static_conflict': sum(bool(c['static_issues']) for c in result['candidates']),
                    'joint': len(result['joint_candidates']), 'joint_static_conflict': sum(bool(c['static_issues']) for c in result['joint_candidates']),
                    'unavailable': len(result['unavailable'])}
                chosen = choose_joint(result, plan['panels'][item['panel']]); row['selection'] = chosen
                save(folder / 'FROZEN_B_SELECTION.json', {'selection': chosen, 'no_B_outcomes_read': True, 'candidate_manifest_sha256': sha(folder / 'candidates/MANIFEST.json')})
                if chosen is None:
                    row['status'] = 'specified_joint_opportunity_unavailable_retained'
                else:
                    cid = case['case_id']
                    export_life(folder / 'assembled', folder / 'contexts', folder / 'candidates', 'known_profile_vpp', folder / 'B', [cid], {cid: {'joint_id': chosen['joint_id']}})
                    ba, arms = execute(folder, 'B', folder / 'B'); row['engine_arms'] += arms
                    summarize(folder / 'B/physics_job.json', folder / 'B_compiled', folder / 'B_runs', folder / 'B_audit', folder / 'report', imported=folder / 'contexts', reference_runs=folder / 'baseline_runs')
                    row['B_audit'] = ba; row['physical_records'] = read(folder / 'report/REPORT.json')['records']
                    row['status'] = 'paired_B_completed' if ba['passed'] else 'B_service_failure_retained'
        records.append(row)
        save(out / 'PROGRESS.json', {'records': records, 'planned': len(plan['physical_cases'])})
        print('physical ' + label + ': ' + row['status'] + ' arms=' + str(row['engine_arms']), flush=True)
    result = {'schema': 'eb.ab_parameter_sensitivity.physics.v1', **source, 'records': records,
        'planned_cases': len(plan['physical_cases']), 'accounted_cases': len(records), 'engine_arms': sum(r['engine_arms'] for r in records),
        'outcome_reselection': False, 'fresh_A_for_every_parameter_case': True, 'master1000_simulation_started': False}
    save(out / 'PHYSICAL.json', result); seal(out, {'schema': result['schema'], **source})
    return result


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('mode', choices=('screen', 'physics'))
    parser.add_argument('--plan', type=Path, default=DEFAULT_PLAN)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--energyplus-dir', type=Path)
    args = parser.parse_args()
    result = screen(args.plan, args.out) if args.mode == 'screen' else physics(args.plan, args.energyplus_dir, args.out)
    print({k: v for k, v in result.items() if k not in ('records', 'factorial_contrasts')})


if __name__ == '__main__':
    main()
