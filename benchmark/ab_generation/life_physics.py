"""Cohort-free life -> housing execution -> current-A reference -> B bridge."""
import copy
import datetime as dt
import shutil
from pathlib import Path
from .common import bound, digest, read, save, seal, sha, verify
from .generate import binding
from .life import normalize_world, require
from .model import plan_commands, plan_hash


def bind_life_worlds(world_contracts, shells, out):
    from benchmark.housing_simulation.assembly import bind_world
    world_contracts, shells, out = map(Path, (world_contracts, shells, out))
    verify(shells)
    source = read(world_contracts)
    normalized = []
    for spec in source['households']:
        world = bind_world(copy.deepcopy(spec), read(shells / spec['household_id'] / 'layout.json'))
        normalized.append(normalize_world(world))
    out.mkdir(parents=True, exist_ok=False)
    save(out / 'resource_worlds.json', {'schema': 'eb.life_resource_worlds.v1',
                                      'source_world_contract_sha256': sha(world_contracts), 'households': normalized})
    seal(out, {'schema': 'eb.life_resource_world_binding.v1', 'households': len(normalized),
               'shell_manifest_sha256': sha(shells / 'MANIFEST.json')})
    return {'households': len(normalized)}


def make_pack(life, world, static, shell, weather_sha):
    from benchmark.housing_simulation.components import heat_pump
    from benchmark.housing_simulation.kernel.core_tools import parse_idf
    from benchmark.housing_simulation.pipeline import HERE
    fields = read(HERE / 'resources/schema_fields.json')
    target = life['household_id']
    members = {m['member_id']: m for m in world['members']}
    pack = {'household_id': target, 'anchor': life['anchor'], 'end_exclusive': life['end_exclusive'],
            'world': world, 'days': {}, 'tasks': life['A']['tasks'], 'operations': life['A']['operations'],
            'HVAC': [heat_pump(d, fields) for d in world['parameter_pack']['devices'] if d['kind'] == 'ac'],
            'journeys': life['EV']['journeys'], 'EV_battery_energy_events': life['EV']['charge_events'],
            'EV_physical_connections': life['EV']['connections'],
            'weather': 'inputs/weather.epw', 'weather_sha256': weather_sha,
            'shell_rows': parse_idf(shell.read_text()), 'source_shell_sha256': sha(shell),
            'hot_water_model': 'standalone_hot_outlet', 'background': static['background'],
            'service_needs': [n for n in life['requirements'] if n['kind'] in ('washer', 'dryer', 'dishwasher')],
            'life_generation': {'version': life['schema'], 'input_sha256': life['input_sha256'],
                                'world_sha256': life['world_sha256'], 'physical_calibration_claimed': False}}
    for date, d in life['days'].items():
        base = d['base_min']
        controls = [{**c, 'start_min': max(base, c['start_min']), 'end_min': min(base + 1440, c['end_min'])}
                    for c in life['A']['controls'] if max(base, c['start_min']) < min(base + 1440, c['end_min'])]
        calendars = copy.deepcopy(d['calendars'])
        pack['days'][date] = {'controls': controls,
            'calendars': {mid: cal for mid, cal in calendars.items() if members[mid]['household_id'] == target},
            'operator_windows': {mid: [[a - base, z - base] for a, z in spans] for mid, spans in d['operator_windows'].items()},
            'family': {'bath_times_min': {mid: e['start_min'] for mid, cal in calendars.items() for e in cal if e['activity'] == 'bath'},
                       'member_dinners_min': {mid: e['start_min'] for mid, cal in calendars.items() for e in cal if e['activity'] == 'dinner'}},
            'water_needs': copy.deepcopy(d['water_needs']),
            'shared': {'member_calendars': {mid: cal for mid, cal in calendars.items() if members[mid]['household_id'] != target},
                       'facility_reservations': copy.deepcopy(d['reservations'])}}
    return pack


def baseline_pair(life, pack, case):
    date = dt.date.fromisoformat(case['date'])
    base = (date - dt.date.fromisoformat(life['anchor'])).days * 1440
    require(case['decision_min'] == 480 and case['horizon_min'] == [480, 1920], 'CURRENT_PHYSICS_PROFILE_REQUIRES_0800_NOTICE_AND_24H_PRIMARY')
    a = {key: [{**r, 'start_min': r['start_min'] - base, 'end_min': r['end_min'] - base}
               for r in life['A'][key]] for key in ('tasks', 'operations', 'controls')}
    needs = [{**n, 'release_min': n['release_min'] - base, 'deadline_min': n['deadline_min'] - base,
              **({'preferred_start_min': n['preferred_start_min'] - base} if 'preferred_start_min' in n else {})}
             for n in life['requirements']]
    pair = {'case_id': case['case_id'], 'household_id': life['household_id'], 'date': case['date'],
            'decision_min': 480, 'A': a, 'B': copy.deepcopy(a), 'needs_A': needs,
            'needs_B': copy.deepcopy(needs), 'VPP_events': copy.deepcopy(case['events']),
            'schedule_hashes': {s: digest(a) for s in ('A', 'B')},
            'EV_continuous_reference': {'status': 'not_installed'},
            'life_input_sha256': life['input_sha256'], 'role_policy_used_as_acceptance_label': False}
    device = next((d for d in pack['world']['parameter_pack']['devices'] if d['kind'] == 'ev'), None)
    if device:
        p = device['parameters']
        initial = dict(life['EV']['states'])[base + 480]
        pair['EV_continuous_reference'] = {'status': 'installed', 'initial_energy_kWh': initial,
            'efficiency': p['efficiency'], 'target_SOC': p['target_soc'], 'capacity_kWh': p['capacity_kwh'],
            'minimum_SOC': p['minimum_soc'], 'charger_kW': p['charger_kw']}
    pair['source_pair_sha256'] = digest(pair)
    return pair


def assemble_life(life_dir, world_contracts, shells, weather, experiments, out):
    from benchmark.housing_simulation.assembly import bind_world
    from benchmark.housing_simulation.pipeline import HERE, portable_gzip
    from benchmark.housing_simulation.validation import check_baseline
    from benchmark.housing_simulation.weather import inspect_weather
    life_dir, world_contracts, shells, weather, experiments, out = map(Path, (life_dir, world_contracts, shells, weather, experiments, out))
    lm, sm = verify(life_dir), verify(shells)
    static, ex = read(world_contracts), read(experiments)
    require(ex['schema'] == 'eb.life_A_experiments.v1', 'UNKNOWN_EXPERIMENT_SCHEMA')
    weather_report = inspect_weather(weather, ex['weather_source'])
    norm = read(life_dir / 'WORLD_INPUT.json')
    require(norm['source_world_contract_sha256'] == sha(world_contracts), 'SPATIAL_WORLD_CONTRACT_CHANGED')
    raw = {s['household_id']: s for s in static['households']}
    expected = {w['household_id']: w for w in norm['households']}
    cases = ex['records']; ids = [c['case_id'] for c in cases]
    require(ids and len(ids) == len(set(ids)), 'EMPTY_OR_DUPLICATE_EXPERIMENT_CASE')
    require(set(c['household_id'] for c in cases) <= {r['household_id'] for r in lm['records']}, 'EXPERIMENT_HOUSEHOLD_NOT_GENERATED')
    shell_status = {r['household_id']: r['status'] for r in sm['records']}
    out.mkdir(parents=True, exist_ok=False)
    (out / 'inputs').mkdir()
    save(out / 'inputs/weather_identity.json', weather_report)
    (out / 'inputs/schema_fields.json.gz').write_bytes(portable_gzip((HERE / 'resources/schema_fields.json').read_bytes()))
    shutil.copyfile(weather, out / 'inputs/weather.epw')
    shutil.copyfile(HERE / 'reference_environment.json', out / 'THERMAL_ENVIRONMENT_POLICY.json')
    gains = [['Lights', 'reference_light', '', '', 'Watts/Area', '', 1]]
    for kind, name in [('washer', 'clotheswasher1'), ('dryer', 'electric_dryer1'), ('dishwasher', 'dishwasher1'),
                       ('misc', 'IECC_Adj1'), ('refrigerator', 'refrigerator1'), ('cooking', 'electric_range1')]:
        fractions = static['thermal_fractions'][kind]
        require(len(fractions) == 3 and all(0 <= x <= 1 for x in fractions) and sum(fractions) <= 1, 'INVALID_HEAT_FRACTIONS')
        gains.append(['ElectricEquipment', name, '', '', 'EquipmentLevel', 1, 1, '', *fractions])
    save(out / 'inputs/native_rows.json.gz', {'gains': gains, 'tank': [], 'provenance': 'declared_project_reference_heat_fractions'})
    records, pairs, index = [], [], []
    for row in lm['records']:
        hid = row['household_id']; life = read(bound(life_dir, row['path']))
        try:
            require(life['status'] == 'A_constructed', 'UNSERVED_A_REQUIREMENTS_RETAINED')
            require(shell_status.get(hid) == 'shell_compiled', 'SHELL_NOT_ADMITTED')
            world = bind_world(copy.deepcopy(raw[hid]), read(shells / hid / 'layout.json'))
            require(normalize_world(world) == expected[hid], 'NORMALIZED_SPATIAL_WORLD_MISMATCH')
            require(digest(expected[hid]) == life['world_sha256'], 'LIFE_WORLD_BINDING_MISMATCH')
            pack = make_pack(life, world, raw[hid], shells / hid / 'shell.idf', sha(weather))
            selected = [c for c in cases if c['household_id'] == hid]
            pp = [baseline_pair(life, pack, c) for c in selected]
            check_baseline(pack, pp, ex['settings'])
            hpath = 'households/' + digest(hid)[:24] + '.json.gz'
            save(out / hpath, pack)
            for case, pair in zip(selected, pp):
                ppath = 'pairs/' + digest(pair['case_id'])[:24] + '.json.gz'
                save(out / ppath, pair)
                item = {'id': digest(pair['case_id'])[:24], 'case_id': pair['case_id'],
                        'household': {'path': hpath, 'sha256': sha(out / hpath)},
                        'pair': {'path': ppath, 'sha256': sha(out / ppath)}}
                pairs.append(item); index.append({**item, 'experiment': case})
            records.append({'household_id': hid, 'status': 'assembled', 'cases': len(pp), 'baseline_execution_checked': True})
        except (ValueError, KeyError, TypeError) as error:
            records.append({'household_id': hid, 'status': 'rejected', 'reason': str(error), 'life_plan': row['path']})
    resources = {name: sha(out / name) for name in ('inputs/schema_fields.json.gz', 'inputs/native_rows.json.gz', 'THERMAL_ENVIRONMENT_POLICY.json')}
    save(out / 'physics_job.json', {'schema': 'eb.housing_physics.input.v1', 'resource_root': '.',
                                  'resources': resources, 'settings': ex['settings'], 'pairs': pairs})
    save(out / 'CASE_INDEX.json', {'records': index})
    verify(life_dir); verify(shells)
    seal(out, {'schema': 'eb.life_A_physics.assembly.v1', 'life_manifest_sha256': sha(life_dir / 'MANIFEST.json'),
               'shell_manifest_sha256': sha(shells / 'MANIFEST.json'), 'world_contracts_sha256': sha(world_contracts),
               'experiments_sha256': sha(experiments), 'weather_sha256': sha(weather),
               'weather_registration_verified': True, 'records': records,
               'case_count': len(pairs), 'historical_cohort_required': False})
    return {'records': records, 'case_count': len(pairs)}


def trace_values(trace, variable, name):
    matches = [v['values'] for k, v in trace.items() if k.lower() == (variable + '|' + name).lower()]
    require(len(matches) == 1, 'MISSING_OR_AMBIGUOUS_CURRENT_A_CHANNEL:' + variable + '|' + name)
    return dict(matches[0])


def context_from_A(pair, pack, meta, trace, experiment, source):
    base = (dt.date.fromisoformat(pair['date']) - dt.date.fromisoformat(pack['anchor'])).days * 1440
    windows, occupancy, reservations = collections_for_context(pack, pair['date'])
    devices = copy.deepcopy(pack['world']['parameter_pack']['devices'])
    context = {'schema': 'eb.ab_generation.context.v1', 'case_id': pair['case_id'], 'household_id': pair['household_id'],
               'date': pair['date'], 'decision_min': 480, 'horizon_min': [480, 1920],
               'A': plan_commands(pair['A']), 'needs': pair['needs_A'], 'devices': devices,
               'operator_windows': windows, 'occupancy': occupancy, 'reservations': reservations,
               'events': experiment['events'], 'tariff': experiment['tariff'],
               'assignment': experiment['assignment'], 'source': source}
    thermal = {}
    for device in devices:
        aid, kind = device['asset_id'], device['kind']
        if kind not in ('ac', 'water_heater'):
            continue
        if kind == 'ac':
            package = next(h for h in pack['HVAC'] if h['asset_id'] == aid)
            name = meta['HVAC_equipment_mapping'][aid]
            fan = next(r[1] for r in package['rows'] if r[0].startswith('Fan:'))
            energy = trace_values(trace, 'Zone Packaged Terminal Heat Pump Electricity Energy', name)
            fan_energy = trace_values(trace, 'Fan Electricity Energy', fan)
            temperature = trace_values(trace, 'Zone Mean Air Temperature', device['room_id'])
            capacity = device['parameters']['nameplate_W']
        else:
            energy = trace_values(trace, 'Water Heater Electricity Energy', meta['tank_name'])
            fan_energy = {}
            temperature = trace_values(trace, 'Water Heater Tank Temperature', meta['tank_name'])
            capacity = device['parameters']['heater_capacity_W'] / device['parameters']['efficiency']
        thermal[aid] = [{'minute': t, 'temperature_C': temperature[t - 10],
                         'electric_kWh': max(0, energy[t] - fan_energy.get(t, 0)) / 3600000,
                         'headroom_kWh': max(0, capacity / 6000 - energy[t] / 3600000)}
                        for t in range(480, 1920, 10)]
    ev_steps = []
    for t, grid in meta['EV_grid_steps']:
        if grid > 0:
            c = next((c for c in pair['A']['controls'] if c['kind'] == 'ev_charge_window' and c['start_min'] <= t < c['end_min']), None)
            if c:
                ev_steps.append({'need_id': c['need_id'], 'start_min': t, 'end_min': t + 10, 'grid_kWh': grid})
    context['reference'] = {'binding': binding(context), 'thermal': thermal, 'ev_charging_steps': ev_steps,
                            'provenance': 'newly_generated_life_A;content_bound_current_A_execution;no_legacy_forecast'}
    return context


def collections_for_context(pack, date):
    from .life import merge
    base = (dt.date.fromisoformat(date) - dt.date.fromisoformat(pack['anchor'])).days * 1440
    windows, occupancy, reservations = {}, {}, []
    for key, day in pack['days'].items():
        off = (dt.date.fromisoformat(key) - dt.date.fromisoformat(date)).days * 1440
        for mid, spans in day['operator_windows'].items():
            windows.setdefault(mid, []).extend([[off + a, off + z] for a, z in spans])
        for cal in {**day['calendars'], **day['shared']['member_calendars']}.values():
            for e in cal:
                if e['location'] == 'home':
                    occupancy.setdefault(e['room_id'], []).append([off + e['start_min'], off + e['end_min']])
        reservations += [{**r, 'start_min': off + r['start_min'], 'end_min': off + r['end_min']} for r in day['shared']['facility_reservations']]
    return windows, {room: merge(spans) for room, spans in occupancy.items()}, reservations


def reference_life(assembled, compiled, runs, out):
    assembled, compiled, runs, out = map(Path, (assembled, compiled, runs, out))
    verify(assembled); cm, rm = verify(compiled), verify(runs)
    require(rm['compiled_manifest_sha256'] == sha(compiled / 'MANIFEST.json'), 'REFERENCE_RUN_COMPILER_MISMATCH')
    require(cm['input_sha256'] == sha(assembled / 'physics_job.json'), 'REFERENCE_COMPILER_REQUEST_MISMATCH')
    out.mkdir(parents=True, exist_ok=False)
    records = []
    for item in read(assembled / 'CASE_INDEX.json')['records']:
        rid = item['id']; pair = read(bound(assembled, item['pair']['path'])); pack = read(bound(assembled, item['household']['path']))
        meta = read(compiled / rid / 'A/INPUT.json.gz'); result = read(runs / rid / 'A/RESULT.json')
        require(result['status'] == 'completed' and result['idf_sha256'] == meta['idf_sha256'], 'CURRENT_A_EXECUTION_NOT_BOUND')
        require(meta['source_schedule_hash'] == pair['schedule_hashes']['A'], 'CURRENT_A_COMMANDS_CHANGED')
        trace = read(runs / rid / 'A/TRACE.json.gz')
        require(sha(runs / rid / 'A/TRACE.json.gz') == result['trace_sha256'], 'CURRENT_A_TRACE_CHANGED')
        source = {'life_input_sha256': pair['life_input_sha256'], 'world_sha256': digest(normalize_world(pack['world'])),
                  'household_sha256': item['household']['sha256'], 'pair_sha256': item['pair']['sha256'],
                  'A_input_sha256': sha(compiled / rid / 'A/INPUT.json.gz'), 'A_trace_sha256': result['trace_sha256'],
                  'A_idf_sha256': meta['idf_sha256'], 'weather_sha256': pack['weather_sha256'],
                  'initialization': {'history_days': meta['history_days'], 'run_interval_min': meta['run_interval_min']}}
        context = context_from_A(pair, pack, meta, trace, item['experiment'], source)
        name = 'contexts/' + rid + '.json.gz'; save(out / name, context)
        records.append({'case_id': pair['case_id'], 'context': name, 'id': rid})
    save(out / 'BATCH.json', {'schema': 'eb.ab_generation.batch.v1', 'records': records})
    seal(out, {'schema': 'eb.life_current_A_reference.v1', 'assembled_manifest_sha256': sha(assembled / 'MANIFEST.json'),
               'compiled_manifest_sha256': sha(compiled / 'MANIFEST.json'), 'runs_manifest_sha256': sha(runs / 'MANIFEST.json'),
               'cases': len(records), 'B_result_or_answer_read': False})
    return {'cases': len(records), 'current_A_reference_bound': True}


def export_life(assembled, contexts, generated, policy, out):
    assembled, contexts, generated, out = map(Path, (assembled, contexts, generated, out))
    verify(assembled); con = verify(contexts); gen = verify(generated)
    require(con['assembled_manifest_sha256'] == sha(assembled / 'MANIFEST.json'), 'CONTEXT_ASSEMBLY_MISMATCH')
    require(gen['input_batch_sha256'] == digest(read(contexts / 'BATCH.json')), 'GENERATION_BATCH_MISMATCH')
    by_id = {r['case_id']: r for r in gen['records']}
    context_rows = {r['case_id']: r for r in read(contexts / 'BATCH.json')['records']}
    out.mkdir(parents=True, exist_ok=False)
    # This is a newly created output: copying explicit inputs is safe and bound.
    shutil.copytree(assembled / 'inputs', out / 'inputs')
    shutil.copytree(assembled / 'households', out / 'households')
    shutil.copyfile(assembled / 'THERMAL_ENVIRONMENT_POLICY.json', out / 'THERMAL_ENVIRONMENT_POLICY.json')
    job = read(assembled / 'physics_job.json'); pairs = []
    for item in read(assembled / 'CASE_INDEX.json')['records']:
        case_id = item['case_id']; result = read(bound(generated, by_id[case_id]['path']))
        context = read(bound(contexts, context_rows[case_id]['context']))
        require(result['context_sha256'] == digest(context), 'CURRENT_A_CONTEXT_CHANGED')
        selected = result['selections'][policy]
        require(selected['status'] != 'no_comparable_opportunity', 'NO_B_OPPORTUNITY:' + case_id)
        pair = read(bound(assembled, item['pair']['path']))
        require(plan_hash(pair['A']) == result['A_commands_sha256'], 'FROZEN_A_CHANGED')
        pair['B'] = selected['plan_B']
        pair['schedule_hashes'] = {s: digest(pair[s]) for s in ('A', 'B')}
        pair['AB_generation'] = {'policy': policy, 'candidate_ids': selected['candidate_ids'], 'rules_sha256': result['rules_sha256'],
                                 'reference_sha256': result['reference_sha256'], 'status': selected['status']}
        pair.pop('source_pair_sha256', None); pair['source_pair_sha256'] = digest(pair)
        name = item['pair']['path']; save(out / name, pair)
        pairs.append({**item, 'pair': {'path': name, 'sha256': sha(out / name)}})
    job['pairs'] = pairs; job['resource_root'] = '.'
    save(out / 'physics_job.json', job)
    save(out / 'CASE_INDEX.json', {'records': pairs})
    seal(out, {'schema': 'eb.life_AB_export.v1', 'policy': policy, 'cases': len(pairs),
               'generation_manifest_sha256': sha(generated / 'MANIFEST.json'), 'A_and_events_frozen': True})
    return {'cases': len(pairs), 'policy': policy}


def reproduce_life(input_path, world_contracts, shell_config, experiments, energyplus_dir, out):
    """Independent public construction and numerical validation, with no cohort."""
    from benchmark.housing_simulation.pipeline import build_shell, compile_pairs, run_pairs
    from benchmark.housing_simulation.validation import audit
    from .life_pipeline import build_life
    from .__main__ import build_batch
    input_path, world_contracts, shell_config, experiments, energyplus_dir, out = map(Path,
        (input_path, world_contracts, shell_config, experiments, energyplus_dir, out))
    out.mkdir(parents=True, exist_ok=False)
    ep = energyplus_dir.resolve(); weather = ep / 'WeatherData/USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw'
    require(weather.is_file(), 'PUBLIC_REFERENCE_WEATHER_NOT_FOUND')
    stages = []
    shell_result = build_shell(shell_config.resolve(), out / 'shells')
    require(all(r['status'] == 'shell_compiled' for r in shell_result['records']), 'SHELL_BUILD_FAILED')
    stages.append({'stage': 'shells', 'households': len(shell_result['records'])})
    bind_life_worlds(world_contracts, out / 'shells', out / 'world_binding')
    life_result = build_life(input_path, out / 'life')
    require(life_result['all_A_constructed'], 'LIFE_REQUIREMENTS_UNSERVED;inspect_life_output')
    require(read(out / 'life/WORLD_INPUT.json') == read(out / 'world_binding/resource_worlds.json'), 'DECLARED_WORLD_RESOURCE_NOT_REPRODUCED')
    stages.append({'stage': 'life', 'households': life_result['households']})
    assembled = assemble_life(out / 'life', world_contracts, out / 'shells', weather, experiments, out / 'assembled')
    require(all(r['status'] == 'assembled' for r in assembled['records']), 'LIFE_PHYSICS_ASSEMBLY_FAILED')
    stages.append({'stage': 'assembled', 'cases': assembled['case_count']})
    for label, folder in [('baseline', out / 'assembled'), ('selected_B', out / 'selected_B')]:
        if label == 'selected_B':
            reference_life(out / 'assembled', out / 'baseline_compiled', out / 'baseline_runs', out / 'contexts')
            build_batch(out / 'contexts/BATCH.json', out / 'candidates')
            export_life(out / 'assembled', out / 'contexts', out / 'candidates', 'known_profile_vpp', out / 'selected_B')
        compiled, runs, audits = out / (label + '_compiled'), out / (label + '_runs'), out / (label + '_audit')
        compilation = compile_pairs((folder / 'physics_job.json').resolve(), compiled)
        require(all(r['status'] == 'compiled' for r in compilation['records']), 'PHYSICAL_COMPILATION_FAILED:' + label)
        execution = run_pairs(compiled, runs, ep / 'energyplus', sha(ep / 'energyplus'), 300)
        require(all(r['status'] == 'completed' for r in execution['records']), 'ENGINE_RUN_FAILED:' + label)
        assessment = audit(compiled, runs, audits)
        require(assessment['passed'], 'PHYSICAL_AUDIT_FAILED:' + label)
        stages.append({'stage': label, 'engine_arms': len(execution['records']), 'audit_passed': True})
    # Evaluate independent comfort requirements without calling setpoints preferences.
    comfort = []
    life_records = verify(out / 'life')['records']
    plans = {r['household_id']: read(out / 'life' / r['path']) for r in life_records}
    for item in read(out / 'assembled/CASE_INDEX.json')['records']:
        experiment = item['experiment']; life = plans[experiment['household_id']]
        offset = (dt.date.fromisoformat(experiment['date']) - dt.date.fromisoformat(life['anchor'])).days * 1440
        trace = read(out / 'baseline_runs' / item['id'] / 'A/TRACE.json.gz')
        for n in life['requirements']:
            if n['kind'] != 'comfort' or not max(n['release_min'] - offset, 480) < min(n['deadline_min'] - offset, 1920):
                continue
            band = n['temperature_band_C']; temps = trace_values(trace, 'Zone Mean Air Temperature', n['room_id'])
            times = range(max(480, n['release_min'] - offset), min(1920, n['deadline_min'] - offset), 10)
            violations = None if band is None else sum(10 for t in times if not band[0] <= temps[t] <= band[1])
            comfort.append({'case_id': experiment['case_id'], 'room_id': n['room_id'],
                            'declared_band_C': band, 'outside_declared_band_min': violations,
                            'unknown_preference_preserved': band is None})
    result = {'schema': 'eb.life_AB.public_reproduction.v1', 'passed': True, 'stages': stages,
              'historical_households_required': False, 'API_used': False, 'engine_sha256': sha(ep / 'energyplus'),
              'weather_sha256': sha(weather), 'life_input_sha256': sha(input_path), 'comfort_readback': comfort,
              'empirical_calibration_claimed': False, 'human_acceptance_inferred': False,
              'master1000_simulation_started': False}
    save(out / 'RESULT.json', result)
    seal(out, {'schema': result['schema'], 'passed': True, 'engine_arms': sum(s.get('engine_arms', 0) for s in stages)})
    return result
