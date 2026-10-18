"""Read-only AC84 import. All paths are arguments; original stages never run."""
import collections
import datetime as dt
import hashlib
import json
import lzma
from pathlib import Path
from .common import bound, digest, read, save, seal, sha
from .generate import binding
from .model import plan_commands
from .resources import authority, legacy_program_constraints


def channel(trace, name, key):
    names = [k for k in trace['channels'] if k.lower() == (name + '|' + key).lower()]
    if len(names) != 1:
        raise ValueError('MISSING_OR_AMBIGUOUS_A_CHANNEL:' + name + '|' + key)
    return dict(trace['channels'][names[0]])


def intervals(minutes):
    result = []
    for t in sorted(set(minutes)):
        if result and result[-1][1] == t:
            result[-1][1] += 10
        else:
            result.append([t, t + 10])
    return result


def extract(pack, pair, physics, trace, source):
    start = dt.date.fromisoformat(pair['date'])
    windows, occupancy, reservations = collections.defaultdict(list), collections.defaultdict(list), []
    lo = min([pair['decision_min']] + [x['start_min'] for x in pair['A']['operations']]) - 1440
    hi = max([1920] + [x['end_min'] for rows in plan_commands(pair['A']).values() for x in rows]) + 1440
    for date, day in pack['days'].items():
        off = (dt.date.fromisoformat(date) - start).days * 1440
        if off + 1440 <= lo or off >= hi:
            continue
        for mid, spans in day['operator_windows'].items():
            windows[mid].extend([[off + a, off + b] for a, b in spans])
        calendars = {**day['calendars'], **day['shared']['member_calendars']}
        for cal in calendars.values():
            for item in cal:
                if item.get('location') == 'home' and item.get('room_id'):
                    occupancy[item['room_id']].extend(range(off + item['start_min'], off + item['end_min'], 10))
        reservations.extend({**r, 'start_min': off + r['start_min'], 'end_min': off + r['end_min']} for r in day['shared']['facility_reservations'])
        bath = pack['world']['activity_contract']['room_map']['bath']
        reservations.extend({'room_id': bath, 'start_min': off + t, 'end_min': off + t + 10} for t in day['family']['bath_times_min'].values())
    # Draw only on frozen pre-existing assignment metadata, never final B success.
    if pair['opportunity_generation'].get('preserved_failure'):
        mode = 'preserved_failure_replay'
    elif not pair['classification']['actual_actions']['any_command_change']:
        mode = 'identical_control'
    else:
        mode = 'fresh_candidates'
    context = {'schema': 'eb.ab_generation.context.v2', 'case_id': pair['case_id'],
               'household_id': pair['household_id'], 'date': pair['date'],
               'decision_min': pair['decision_min'], 'horizon_min': [480, 1920],
               'A': plan_commands(pair['A']), 'needs': legacy_program_constraints(pair['needs_A']),
               'devices': pack['world']['parameter_pack']['devices'],
               'operator_windows': dict(windows), 'occupancy': {k: intervals(v) for k, v in occupancy.items()},
               'reservations': reservations, 'events': pair['VPP_events'],
               'event_meter_scope': 'modeled_controlled_equipment',
               'tariff': [], 'assignment': {'mode': mode, 'source': 'frozen_legacy_assignment;not_reclassified_by_new_outcomes'},
               'source': source}
    context['authority'] = authority(pack, windows)
    if mode == 'preserved_failure_replay':
        context['retained_B_request'] = plan_commands(pair['B'])
    thermal = {}
    for device in context['devices']:
        aid = device['asset_id']
        if not set(device['types']) & {'ac', 'water_heater'}:
            continue
        if 'ac' in device['types']:
            name = physics['HVAC_equipment_mapping'][aid]
            energy = channel(trace, 'Zone Packaged Terminal Heat Pump Electricity Energy', name)
            fans = channel(trace, 'Fan Electricity Energy', name.replace('_UNIT', '_FAN'))
            temps = channel(trace, 'Zone Mean Air Temperature', device['room_id'])
            # This is the supplied electrical reference rating, not cooling W.
            cap = device.get('max_electric_kw', device['parameters']['max_electric_W'] / 1000) * 1000
        else:
            name = physics['tank_name']
            energy = channel(trace, 'Water Heater Electricity Energy', name)
            temps = channel(trace, 'Water Heater Tank Temperature', name)
            fans = {}
            cap = device['parameters']['heater_capacity_W'] / device['parameters']['efficiency']
        thermal[aid] = [{'minute': t, 'electric_kWh': max(0, energy[t] - fans.get(t, 0)) / 3600000,
                         'headroom_kWh': max(0, cap / 6000 - energy[t] / 3600000),
                         'temperature_C': temps[t - 10]}
                        for t in range(480, 1920, 10) if t in energy and t - 10 in temps]
    context['reference'] = {'binding': binding(context), 'thermal': thermal,
                            'ev_charging_steps': pair['EV_continuous_reference'].get('A', {}).get('charging_steps', []),
                            'provenance': 'current_A_only_simulation;legacy_B_trace_not_read'}
    return context


def import_current(stage, out, limit=None, tariff_path=None, tariff_sha256=None):
    stage, out = Path(stage), Path(out)
    if limit is not None and limit <= 0:
        raise ValueError('LIMIT_MUST_BE_POSITIVE')
    manifest = read(stage / 'INPUT_MANIFEST.json')
    tariff = None
    if tariff_path:
        if not tariff_sha256 or sha(tariff_path) != tariff_sha256:
            raise ValueError('TARIFF_HASH_MISMATCH')
        tariff = read(tariff_path)
    out.mkdir(parents=True, exist_ok=False)
    records, counts = [], collections.Counter()
    for home in manifest['records']:
        path = bound(stage, home['path'])
        if sha(path) != home['sha256']:
            raise ValueError('HOUSEHOLD_HASH_CHANGED')
        pack = read(path)
        for case in home['cases']:
            if limit is not None and len(records) >= limit:
                break
            path = bound(stage, case['path'])
            if sha(path) != case['sha256']:
                raise ValueError('PAIR_HASH_CHANGED')
            pair = read(path)
            if digest({k: pair['A'][k] for k in ('tasks', 'operations', 'controls')}) != pair['schedule_hashes']['A']:
                raise ValueError('A_COMMAND_HASH_MISMATCH')
            folder = stage / 'results/pilot50' / home['household_id'] / case['date'] / 'A'
            physics, result = read(folder / 'INPUT.json.gz'), read(folder / 'RESULT.json')
            if not result['engine_completed'] or physics['source_schedule_hash'] != pair['schedule_hashes']['A'] or result['source_schedule_hash'] != pair['schedule_hashes']['A']:
                raise ValueError('CURRENT_A_RUN_NOT_BOUND')
            if sha(folder / 'INPUT.json.gz') != result['input_sha256'] or physics['weather_sha256'] != pack['weather_sha256']:
                raise ValueError('CURRENT_A_INPUT_CHANGED')
            archive = read(folder / 'TRACE_ARCHIVE.json')
            if archive['original_gzip_sha256'] != result['trace_sha256']:
                raise ValueError('A_TRACE_NOT_BOUND_TO_RESULT')
            if sha(folder / 'TRACE.json.xz') != archive['archive_sha256']:
                raise ValueError('A_TRACE_ARCHIVE_CHANGED')
            raw = lzma.decompress((folder / 'TRACE.json.xz').read_bytes())
            if hashlib.sha256(raw).hexdigest() != archive['json_sha256']:
                raise ValueError('A_TRACE_JSON_CHANGED')
            source = {'household_sha256': home['sha256'], 'pair_sha256': case['sha256'],
                      'legacy_A_schedule_hash': pair['schedule_hashes']['A'],
                      'A_input_sha256': result['input_sha256'], 'A_result_sha256': sha(folder / 'RESULT.json'),
                      'A_trace_json_sha256': archive['json_sha256'], 'A_idf_sha256': physics['idf_sha256'],
                      'engine_sha256': result['engine_sha256'], 'weather_sha256': pack['weather_sha256'],
                      'initialization': {'history_days': physics['history_days'], 'run_interval_min': physics['run_interval_min']}}
            context = extract(pack, pair, physics, json.loads(raw), source)
            if tariff is not None:
                limits = [x for rows in plan_commands(pair['A']).values() for x in rows]
                lo = min(x['start_min'] for x in limits) - 1440
                hi = max(x['end_min'] for x in limits) + 1440
                context['tariff'] = [{'start_min': day * 1440 + p['start_min'],
                                      'end_min': day * 1440 + p['end_min'],
                                      'price_per_kWh': p['CNY_per_kWh']}
                                     for day in range(lo // 1440, hi // 1440 + 1)
                                     for p in tariff['daily_periods']]
                context['tariff_provenance'] = {'sha256': tariff_sha256, 'id': tariff['id'],
                                                'currency': tariff['currency'], 'experimental_scenario': True}
                context['reference']['binding'] = binding(context)
            name = 'contexts/' + digest(pair['case_id'])[:24] + '.json.gz'
            save(out / name, context)
            # Preserve the old request verbatim as a separate comparator, never
            # consult its physical effects, price advantage or human answers.
            old = {'case_id': pair['case_id'], 'A': pair['A'], 'B': pair['B'],
                   'assignment': context['assignment'], 'source_pair_sha256': case['sha256'],
                   'mode': 'fixed_intervention_replay_comparator', 'actual_outcomes': None}
            baseline = 'legacy/' + digest(pair['case_id'])[:24] + '.json.gz'
            save(out / baseline, old)
            records.append({'case_id': pair['case_id'], 'context': name, 'legacy_comparator': baseline,
                            'household_id': home['household_id'], 'date': case['date'], 'source_pair': case['path']})
            counts[context['assignment']['mode']] += 1
        if limit is not None and len(records) >= limit:
            break
    save(out / 'BATCH.json', {'schema': 'eb.ab_generation.batch.v1', 'records': records})
    seal(out, {'schema': 'eb.ab_generation.import.v1', 'source_manifest_sha256': sha(stage / 'INPUT_MANIFEST.json'),
               'cases': len(records), 'households': len({r['household_id'] for r in records}),
               'assignments': dict(counts), 'tariff_status': 'explicit_frozen_experimental_tariff' if tariff else 'not_imported;cost_ranking_explicitly_unavailable',
               'tariff_sha256': tariff_sha256,
               'old_B_physical_outcomes_read': False, 'source_files_modified': False})
    return read(out / 'MANIFEST.json')
