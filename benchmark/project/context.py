"""Join a newly generated family, its bound housing and unexecuted life A."""
import copy
import datetime as dt
from benchmark.ab_generation.common import digest
from benchmark.ab_generation.generate import binding
from benchmark.ab_generation.information import information_set
from benchmark.ab_generation.life import merge
from benchmark.ab_generation.model import plan_commands
from benchmark.ab_generation.resources import authority


def plan_context(life, normalized_world, experiment, family_sha256):
    base = (dt.date.fromisoformat(experiment['date']) - dt.date.fromisoformat(life['anchor'])).days * 1440
    A = {key: [{**r, 'start_min': r['start_min'] - base, 'end_min': r['end_min'] - base}
               for r in life['A'][key]] for key in ('tasks', 'operations', 'controls')}
    needs = [{**n, 'release_min': n['release_min'] - base, 'deadline_min': n['deadline_min'] - base,
              **({'preferred_start_min': n['preferred_start_min'] - base} if 'preferred_start_min' in n else {})}
             for n in life['requirements']]
    windows, occupancy, reservations, days = {}, {}, [], {}
    target = life['household_id']; member_ids = {m['member_id']: m['household_id'] for m in normalized_world['members']}
    for date, day in life['days'].items():
        off = day['base_min'] - base
        for mid, spans in day['operator_windows'].items():
            windows.setdefault(mid, []).extend([[a - base, z - base] for a, z in spans])
        for calendar in day['calendars'].values():
            for e in calendar:
                if e['location'] == 'home':
                    occupancy.setdefault(e['room_id'], []).append([off + e['start_min'], off + e['end_min']])
        reservations.extend({**r, 'start_min': off + r['start_min'], 'end_min': off + r['end_min']} for r in day['reservations'])
        days[date] = {'shared': {'member_calendars': {mid: cal for mid, cal in day['calendars'].items() if member_ids[mid] != target}}}
    devices = copy.deepcopy(normalized_world['devices'])
    authority_pack = {'household_id': target, 'world': {'members': normalized_world['members'],
        'parameter_pack': {'devices': devices}}, 'days': days}
    c = {'schema': 'eb.ab_generation.context.v3', 'case_id': experiment['case_id'], 'household_id': target,
        'date': experiment['date'], 'decision_min': 480, 'horizon_min': [480, 1920],
        'A': plan_commands(A), 'needs': needs, 'devices': devices,
        'operator_windows': windows, 'occupancy': {k: merge(v) for k, v in occupancy.items()},
        'reservations': reservations, 'events': copy.deepcopy(experiment['events']),
        'tariff': copy.deepcopy(experiment['tariff']), 'tariff_provenance': {'currency': 'CNY',
            'origin': 'fixed project experimental tariff;not household measured or live tariff', 'experimental_scenario': True},
        'event_meter_scope': 'whole_physical_dwelling', 'authority': authority(authority_pack, windows),
        'assignment': {'mode': 'fresh_candidates'}, 'source': {'family_sha256': family_sha256,
            'life_input_sha256': life['input_sha256'], 'world_sha256': life['world_sha256'],
            'basis': 'same_generated_family_and_full_life_plan;no_physical_A_trace_or_human_answers'}}
    if normalized_world.get('electrical'):
        c['electrical'] = {'schema': 'eb.ab_site_capacity.v1',
            **{k: normalized_world['electrical'][k] for k in ('supply_W', 'background_upper_W', 'capacity_mode')},
            'scope': 'whole_physical_dwelling_including_shared_context'}
    ev = next((d for d in devices if d['kind'] == 'ev'), None)
    steps = []
    if ev:
        for e in life['EV']['charge_events']:
            if e['kind'] == 'charge' and e['battery_kWh'] > 0:
                steps.append({'need_id': e['need_id'], 'start_min': e['start_min'] - base,
                    'end_min': e['end_min'] - base, 'grid_kWh': e['battery_kWh'] / ev['parameters']['efficiency']})
    spans = [r for rows in A.values() for r in rows]
    span = [min(r['start_min'] for r in spans), max(r['end_min'] for r in spans)]
    c['reference'] = {'binding': binding(c), 'thermal': {}, 'ev_charging_steps': steps,
        'information_set': information_set('offline_unexecuted_A_plan', 480, span),
        'provenance': 'unexecuted_same_household_A;EV_grid_is_analytic_plan;no_thermal_state_or_native_measurement',
        'baseline_admission': {'status': 'not_physically_executed', 'physical_or_human_validity_inferred': False}}
    return c
