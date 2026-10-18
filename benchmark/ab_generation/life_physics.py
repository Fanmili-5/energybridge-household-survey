"""Cohort-free life -> housing execution -> current-A reference -> B bridge."""
import copy
import datetime as dt
import shutil
from pathlib import Path
from .common import bound, digest, read, save, seal, sha, verify
from .generate import binding
from .life import normalize_world, require
from .model import apply, plan_commands, plan_hash, request_issues
from .resources import authority


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
    context = {'schema': 'eb.ab_generation.context.v2', 'case_id': pair['case_id'], 'household_id': pair['household_id'],
               'date': pair['date'], 'decision_min': 480, 'horizon_min': [480, 1920],
               'A': plan_commands(pair['A']), 'needs': pair['needs_A'], 'devices': devices,
               'operator_windows': windows, 'occupancy': occupancy, 'reservations': reservations,
               'events': experiment['events'], 'tariff': experiment['tariff'],
               'event_meter_scope': experiment.get('event_meter_scope', 'whole_physical_dwelling'),
               'authority': authority(pack, windows),
               'tariff_provenance': experiment.get('tariff_provenance'),
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
            components = meta['HVAC_component_mapping'][aid]
            modes = {axis: [trace_values(trace, axis.title() + ' Coil Electricity Energy', n)
                            for n in components[axis]] for axis in ('heating', 'cooling')}
            temperature = trace_values(trace, 'Zone Mean Air Temperature', device['room_id'])
            capacity = device['parameters']['nameplate_W']
        else:
            energy = trace_values(trace, 'Water Heater Electricity Energy', meta['tank_name'])
            fan_energy = {}
            temperature = trace_values(trace, 'Water Heater Tank Temperature', meta['tank_name'])
            capacity = device['parameters']['heater_capacity_W'] / device['parameters']['efficiency']
        thermal[aid] = [{'minute': t, 'temperature_C': temperature[t - 10],
                         'electric_kWh': max(0, energy[t] - fan_energy.get(t, 0)) / 3600000,
                         **({'axis_electric_kWh': {axis: sum(c[t] for c in channels) / 3600000
                                                  for axis, channels in modes.items()},
                             'operating_axis_source': 'native_coil_electricity;not_distance_to_setpoint'} if kind == 'ac' else {}),
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


def export_life(assembled, contexts, generated, policy, out, case_ids=None, request_overrides=None):
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
    requested = set(case_ids) if case_ids is not None else {i['case_id'] for i in read(assembled / 'CASE_INDEX.json')['records']}
    require(requested and requested <= by_id.keys(), 'UNKNOWN_OR_EMPTY_EXPORT_CASES')
    for item in read(assembled / 'CASE_INDEX.json')['records']:
        case_id = item['case_id']
        if case_id not in requested:
            continue
        result = read(bound(generated, by_id[case_id]['path']))
        context = read(bound(contexts, context_rows[case_id]['context']))
        require(result['context_sha256'] == digest(context), 'CURRENT_A_CONTEXT_CHANGED')
        selected = result['selections'][policy]
        override = (request_overrides or {}).get(case_id)
        if override:
            require(result['assignment']['mode'] == 'fresh_candidates', 'CANNOT_OVERRIDE_FROZEN_CONTROL_OR_FAILURE')
            probe = (next(c for c in result['joint_candidates'] if c['id'] == override['joint_id']) if 'joint_id' in override
                     else next(c for c in result['candidates'] if c['id'] == override['candidate_id']))
            allowed = override.get('expected_static_issues', [])
            require(probe['static_issues'] == allowed, 'PROBE_STATIC_ISSUES_NOT_PREDECLARED')
            baseline = plan_commands(context['A'])
            for c in baseline['controls']:
                c['_ab_control_id'] = digest(c)
            plan = apply(baseline, probe['patches'])
            for c in plan['controls']:
                c.pop('_ab_control_id', None)
            selected = {'status': 'predeclared_failure_probe' if allowed else 'explicit_predeclared_candidate_probe',
                        'candidate_ids': probe.get('candidate_ids', [probe['id']]), 'plan_B': plan}
        require(selected['status'] != 'no_comparable_opportunity', 'NO_B_OPPORTUNITY:' + case_id)
        pair = read(bound(assembled, item['pair']['path']))
        require(plan_hash(pair['A']) == result['A_commands_sha256'], 'FROZEN_A_CHANGED')
        pair['B'] = selected['plan_B']
        require(not request_issues(context, pair['B']), 'REQUEST_CHANGED_FROZEN_IDENTITIES_OR_PAST')
        require(selected.get('B_commands_sha256', plan_hash(pair['B'])) == plan_hash(pair['B']), 'SELECTED_B_HASH_CHANGED')
        pair['schedule_hashes'] = {s: digest(pair[s]) for s in ('A', 'B')}
        pair['AB_generation'] = {'policy': ('failure_probe' if override and override.get('expected_static_issues') else 'explicit_candidate_probe') if override else policy, 'candidate_ids': selected['candidate_ids'], 'rules_sha256': result['rules_sha256'],
                                 'event_meter_scope': context['event_meter_scope'],
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
    """Default public comparison executes all declared selection policies."""
    from .review import reproduce_strategies
    return reproduce_strategies(input_path, world_contracts, shell_config, experiments, energyplus_dir, out)
