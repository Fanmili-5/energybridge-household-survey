"""Derive impact summaries from sealed V61 traces; never execute/reschedule physics.

Stdlib only. Run on the machine holding the sealed V61 raw results:
    python -B code/regenerate.py --workers 8
"""
import argparse
import copy
import gzip
import hashlib
import json
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT.parent / 'unified_physics50_v61_20261017'
SCHEMA = 'eb.impact_summary50.v62'
STEP = 10
PRIMARY = (480, 1920)
THRESHOLDS = (0.2, 0.5, 1.0, 2.0)
EPS = 1e-7
AIR_BINS = [(None,10),(10,16),(16,20),(20,24),(24,28),(28,32),(32,None)]
SOURCE_PINS = json.loads((ROOT / 'SOURCE_PHYSICS.json').read_bytes())
SOURCE_SEAL = SOURCE_PINS['seal_sha256']
SOURCE_BINDINGS = SOURCE_PINS['bindings_sha256']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    data = Path(path).read_bytes()
    return json.loads(gzip.decompress(data) if str(path).endswith('.gz') else data)


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()
    if str(path).endswith('.gz'):
        data = gzip.compress(data, mtime=0)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_bytes(data)
    temporary.replace(path)


def wall(date, minute):
    return (datetime.fromisoformat(date) + timedelta(minutes=minute)).isoformat(timespec='minutes')


def limits(values):
    return [min(values), max(values)] if values else None


def periods(minutes, date):
    """Merge adjacent reported intervals, preserving gaps and midnight rollover."""
    spans = []
    for minute in minutes:
        if spans and spans[-1][1] == minute:
            spans[-1][1] = minute + STEP
        else:
            spans.append([minute, minute + STEP])
    return [{'start_min': a, 'end_min': b, 'start': wall(date, a), 'end': wall(date, b),
             'duration_minutes': b - a} for a, b in spans]


def duration(minutes, date):
    spans = periods(minutes, date)
    return {'total_minutes': len(minutes) * STEP,
            'longest_continuous_minutes': max((s['duration_minutes'] for s in spans), default=0),
            'periods': spans}


def actual_exposure(arm, indices, date):
    """Actual presence, including periods when the other arm's room is empty."""
    minutes=[i*STEP for i in indices]
    spans=periods(minutes,date)
    for span in spans:
        subset=range(span['start_min']//STEP,span['end_min']//STEP)
        span['air_temperature_range_C']=limits([arm['air_C'][i]for i in subset])
        span['radiant_temperature_range_C']=limits([arm['radiant_C'][i]for i in subset])
        span['RH_range_percent']=limits([arm['RH_percent'][i]for i in subset])
        span['person_hours']=sum(arm['occupants'][i]for i in subset)*STEP/60
    bins=[]
    for lower,upper in AIR_BINS:
        hit=[i*STEP for i in indices if (lower is None or arm['air_C'][i]>=lower)and(upper is None or arm['air_C'][i]<upper)]
        bins.append({'lower_inclusive_C':lower,'upper_exclusive_C':upper,**duration(hit,date)})
    return {'occupied_minutes':len(minutes)*STEP,'occupied_periods':spans,
            'air_temperature_bins':bins,'bins_are':'descriptive temperature ranges,not comfort limits'}


def channel(trace, name, room):
    key = name + '|' + room
    result = trace['channels'][key]
    assert all(t == i * STEP for i, (t, _) in enumerate(result)), ('TRACE_TIME_AXIS', key)
    return [float(v) for _, v in result]


def room_arrays(a, b):
    rooms = {}
    assert a['interval_min'] == b['interval_min']
    for key in a['channels']:
        if not key.startswith('Zone Mean Air Temperature|'):
            continue
        room = key.split('|', 1)[1]
        names = {'air_C': 'Zone Mean Air Temperature', 'radiant_C': 'Zone Mean Radiant Temperature',
                 'RH_percent': 'Zone Air Relative Humidity', 'occupants': 'Zone People Occupant Count'}
        rooms[room] = {side: {short: channel(trace, name, room) for short, name in names.items()}
                       for side, trace in [('A', a), ('B', b)]}
    assert rooms
    return rooms


def room_metrics(data, window, date):
    lo, hi = window
    indices = range(lo // STEP, hi // STEP)
    common = [i for i in indices if data['A']['occupants'][i] > 0 and data['B']['occupants'][i] > 0]
    out = {'window_min': [lo, hi], 'common_room_occupied_minutes': len(common) * STEP,
           'common_occupancy_definition': 'room occupied in both arms;not a matched-person comfort estimate'}
    for side in ('A', 'B'):
        x = data[side]
        occupied = [i for i in indices if x['occupants'][i] > 0]
        out[side] = {'occupied_minutes': len(occupied) * STEP,
                     'occupied_person_hours': sum(x['occupants'][i] for i in indices) * STEP / 60,
                     'occupied_air_temperature_range_C': limits([x['air_C'][i] for i in occupied]),
                     'occupied_radiant_temperature_range_C': limits([x['radiant_C'][i] for i in occupied]),
                     'occupied_RH_range_percent': limits([x['RH_percent'][i] for i in occupied]),
                     'occupied_RH_at_least95_minutes': STEP * sum(x['RH_percent'][i] >= 95 for i in occupied)}
        other='B'if side=='A'else'A'
        only=[i for i in occupied if data[other]['occupants'][i]<=0]
        out[side]['actual_occupied_exposure']=actual_exposure(x,occupied,date)
        out[side]['other_arm_empty_exposure']=actual_exposure(x,only,date)
        differences={i:data['B']['air_C'][i]-data['A']['air_C'][i]for i in occupied}
        out[side]['own_occupied_same_clock_air_B_minus_A_range_C']=limits(list(differences.values()))
        out[side]['own_occupied_same_clock_air_delta_durations']={str(threshold):{
            'B_warmer':duration([i*STEP for i,v in differences.items()if v>threshold+EPS],date),
            'B_cooler':duration([i*STEP for i,v in differences.items()if v<-threshold-EPS],date)}for threshold in THRESHOLDS}
    deltas = {i: data['B']['air_C'][i] - data['A']['air_C'][i] for i in common}
    out['common_occupied_air_B_minus_A_range_C'] = limits(list(deltas.values()))
    out['common_occupied_radiant_B_minus_A_range_C'] = limits([
        data['B']['radiant_C'][i] - data['A']['radiant_C'][i] for i in common])
    out['common_occupied_RH_B_minus_A_range_percentage_points'] = limits([
        data['B']['RH_percent'][i] - data['A']['RH_percent'][i] for i in common])
    out['common_occupied_absolute_air_delta_room_degree_hours'] = sum(abs(v) for v in deltas.values()) * STEP / 60
    # The minimum headcount is an explicit weight, not evidence of matched people.
    out['min_headcount_weighted_absolute_air_delta_person_degree_hours'] = sum(
        min(data['A']['occupants'][i], data['B']['occupants'][i]) * abs(v) for i, v in deltas.items()) * STEP / 60
    out['air_delta_durations'] = {}
    for threshold in THRESHOLDS:
        out['air_delta_durations'][str(threshold)] = {
            'B_warmer': duration([i * STEP for i, v in deltas.items() if v > threshold + EPS], date),
            'B_cooler': duration([i * STEP for i, v in deltas.items() if v < -threshold - EPS], date)}
    out['subjective_comfort_or_acceptance'] = None
    return out


def task_status(side):
    services = side['service_outcomes']
    ev_short = [t for t in side['EV_trips'] if t['target_shortfall_kWh'] > EPS or t['unserved_traction_kWh'] > EPS]
    water_short = [w for w in side['water_delivery']
                   if w.get('rollout_below_target_volume_L', w['below_target_volume_L']) > EPS]
    return {'programmes_and_retrieval_completed': services['all_known_program_services_completed'],
            'unexecuted_batches': len(services['unexecuted_batches']),
            'future_unexecuted_batches': len(services['future_unexecuted_batches']),
            'failed_retrieval_batches': len(services['failed_retrieval_batches']),
            'retrieval_pending_after_horizon': len(services['retrieval_pending_after_horizon']),
            'EV_departures_with_target_or_traction_shortfall': len(ev_short),
            'EV_shortfall_details': ev_short,
            'reported_hot_water_target_met': not water_short,
            'hot_water_shortfall_details': water_short,
            'given_electrical_supply_limits_met': side['given_electrical_supply_feasible_at_10min_resolution'],
            'no_assumed_rescue_boundary': services['no_recovery_boundary']}


def energy_summary(source, date):
    a, b = source['A'], source['B']
    tasks = {s: task_status(source[s]) for s in ('A', 'B')}
    deficit = any(not t['programmes_and_retrieval_completed'] or t['EV_departures_with_target_or_traction_shortfall']
                  or not t['reported_hot_water_target_met'] for t in tasks.values())
    recovered = source['recovery']['status'] in ('no_executable_request_difference', 'within_declared_tolerances_to_horizon')
    observed = source['delta_rollout_kWh']['facility']
    primary = source['delta_primary_kWh']['facility']
    qualifiers = ['conditional_reference_model_observation']
    if deficit:
        qualifiers.append('unmet_task_or_delivery_present;lower_consumption_includes_service_difference')
    if not recovered:
        qualifiers.append('states_not_restored_within_finite_observation')
    if source['source_B_constraint_flags']:
        qualifiers.append('source_B_constraint_conflicts_retained')
    if any(not t['given_electrical_supply_limits_met'] for t in tasks.values()):
        qualifiers.append('open_loop_electrical_limit_exceeded')
    if abs(observed) <= 1e-6 and primary < -1e-6:
        qualifiers.append('primary_reduction_offset_in_followup_observation')
    qualifiers.append('temperature_and_humidity_impacts_require_separate_reading')
    result = {'sign': 'B minus A;negative means lower observed electricity,not equivalent comfort or task delivery',
              'qualifiers': qualifiers, 'subjective_comfort_equivalence_verified': False,
              'energy_saving_or_human_acceptance_inferred': False,
              'task_delivery': tasks, 'state_recovery_status': source['recovery']['status'],
              'known_task_delivery_deficit_present': deficit}
    for label, prefix, hi in [('primary', 'primary', PRIMARY[1]), ('observation', 'rollout', source['recovery']['end_min'])]:
        result[label] = {'start': wall(date, PRIMARY[0]), 'end': wall(date, hi), 'window_min': [PRIMARY[0], hi],
                         'facility_A_kWh': a[prefix + '_energy_kWh']['facility'],
                         'facility_B_kWh': b[prefix + '_energy_kWh']['facility'],
                         'facility_B_minus_A_kWh': source['delta_' + prefix + '_kWh']['facility'],
                         'controlled_portfolio_B_minus_A_kWh': source['delta_' + prefix + '_kWh']['controlled_portfolio'],
                         'components_B_minus_A_kWh': source['delta_' + prefix + '_kWh']}
    return result


def verified(path, manifest):
    relative = str(path.relative_to(SOURCE))
    digest = sha(path)
    assert manifest[relative] == digest, ('SEALED_SOURCE_MISMATCH', relative)
    return digest


def load_pair(label, record, manifest, reference_schedule):
    folder = SOURCE / 'results' / label / record['household_id'] / record['date']
    data, evidence = {}, {}
    for side in ('A', 'B'):
        result_path = folder / side / 'RESULT.json'
        trace_path = folder / side / 'TRACE.json.gz'
        result_sha = verified(result_path, manifest)
        trace_sha = verified(trace_path, manifest)
        result = read(result_path)
        assert result['engine_completed'] and not result['errors']
        assert result['trace_sha256'] == trace_sha
        assert result['source_pair_sha256'] == record['source_pair_sha256']
        assert result['source_schedule_hash'] == reference_schedule[side]
        data[side] = read(trace_path)
        evidence[side] = {'trace_path': str(trace_path.relative_to(SOURCE)), 'trace_sha256': trace_sha,
                          'result_path': str(result_path.relative_to(SOURCE)), 'result_sha256': result_sha}
    return data, evidence


def energy_delta(data):
    def total(trace):
        matches = [rows for key, rows in trace['channels'].items() if key.split('|')[0] == 'Electricity:Facility']
        assert len(matches) == 1
        rows = matches[0]
        return sum(v for t, v in rows if PRIMARY[0] <= t < PRIMARY[1]) / 3600000
    return total(data['B']) - total(data['A'])


def assess_case(args):
    record, manifest, diagnostic_records = args
    cid, date = record['case_id'], record['date']
    source_path = SOURCE / record['path']
    assert verified(source_path, manifest) == record['sha256']
    source = read(source_path)
    schedules = {s: source[s]['source_schedule_hash'] for s in ('A', 'B')}
    raw, evidence = load_pair('pilot50', record, manifest, schedules)
    nominal = room_arrays(raw['A'], raw['B'])
    assert abs(energy_delta(raw) - source['delta_primary_kWh']['facility']) < 1e-7
    scenarios = {'reference': nominal}
    scenario_evidence = {'reference': evidence}
    energies = {'reference': source['delta_primary_kWh']['facility']}
    labels=sorted(r['alternative']for r in diagnostic_records)
    for label in labels:
        alt, proofs = load_pair(label, record, manifest, schedules)
        rooms = room_arrays(alt['A'], alt['B'])
        assert rooms.keys() == nominal.keys()
        for room in rooms:
            for side in ('A', 'B'):
                assert rooms[room][side]['occupants'] == nominal[room][side]['occupants'], 'SENSITIVITY_OCCUPANCY_CHANGED'
        scenarios[label] = rooms
        scenario_evidence[label] = proofs
        energies[label] = energy_delta(alt)
    for r in diagnostic_records:
        expected = r['contrast_sensitivity']['primary_facility_B_minus_A_kWh']
        assert abs(expected['reference'] - energies['reference']) < 1e-7
        assert abs(expected[r['alternative']] - energies[r['alternative']]) < 1e-7
    timeline = {'schema': SCHEMA, 'case_id': cid, 'window_min': list(PRIMARY),
                'interval_start_min': list(range(*PRIMARY, STEP)), 'step_minutes': STEP,
                'values_are': 'reported 10-minute states/counts assigned to their reporting interval;durations approximate',
                'scenario_labels': list(scenarios), 'rooms': {}}
    impacts = []
    max_sensitivity = {label: 0.0 for label in labels}
    max_actual_sensitivity={label:0.0 for label in labels}
    max_absolute_sensitivity={label:0.0 for label in labels}
    for room, values in nominal.items():
        primary = room_metrics(values, PRIMARY, date)
        rollout = room_metrics(values, (PRIMARY[0], source['recovery']['end_min']), date)
        alternatives = {label: room_metrics(rooms[room], PRIMARY, date) for label, rooms in scenarios.items()}
        points = {}
        for label, rooms in scenarios.items():
            values_here = rooms[room]
            points[label] = {side: {name: seq[48:192] for name, seq in values_here[side].items()} for side in ('A', 'B')}
            points[label]['air_B_minus_A_C'] = [values_here['B']['air_C'][i] - values_here['A']['air_C'][i] for i in range(48, 192)]
            if label != 'reference':
                max_sensitivity[label] = max(max_sensitivity[label], max((
                    abs(points[label]['air_B_minus_A_C'][i] - points['reference']['air_B_minus_A_C'][i])
                    for i in range(144) if values['A']['occupants'][i + 48] > 0 and values['B']['occupants'][i + 48] > 0), default=0))
                actual_indices=[i for i in range(144)if values['A']['occupants'][i+48]>0 or values['B']['occupants'][i+48]>0]
                max_actual_sensitivity[label]=max(max_actual_sensitivity[label],max((
                    abs(points[label]['air_B_minus_A_C'][i]-points['reference']['air_B_minus_A_C'][i])for i in actual_indices),default=0))
                for side in ('A','B'):
                    max_absolute_sensitivity[label]=max(max_absolute_sensitivity[label],max((
                        abs(points[label][side]['air_C'][i]-points['reference'][side]['air_C'][i])
                        for i in range(144)if values[side]['occupants'][i+48]>0),default=0))
        band = None
        if labels:
            band = {'scenario_labels': list(scenarios),
                    'air_B_minus_A_C_min': [min(p['air_B_minus_A_C'][i] for p in points.values()) for i in range(144)],
                    'air_B_minus_A_C_max': [max(p['air_B_minus_A_C'][i] for p in points.values()) for i in range(144)]}
            for side in ('A', 'B'):
                band[side + '_air_C_min'] = [min(p[side]['air_C'][i] for p in points.values()) for i in range(144)]
                band[side + '_air_C_max'] = [max(p[side]['air_C'][i] for p in points.values()) for i in range(144)]
        timeline['rooms'][room] = {'scenarios': points, 'tested_single_factor_range': band}
        nonempty = [m['common_occupied_air_B_minus_A_range_C'] for m in alternatives.values()
                    if m['common_occupied_air_B_minus_A_range_C'] is not None]
        envelope = None
        if labels:
            envelope = {'common_occupied_air_B_minus_A_range_C': [min(v[0] for v in nonempty), max(v[1] for v in nonempty)] if nonempty else None,
                        'duration_ranges_minutes': {str(t): {direction: {
                            key: limits([m['air_delta_durations'][str(t)][direction][key] for m in alternatives.values()])
                            for key in ('total_minutes', 'longest_continuous_minutes')}
                            for direction in ('B_warmer', 'B_cooler')} for t in THRESHOLDS}}
            envelope['own_occupied_temperature_bin_duration_ranges']={side:[{
                'lower_inclusive_C':lower,'upper_exclusive_C':upper,
                'total_minutes':limits([m[side]['actual_occupied_exposure']['air_temperature_bins'][ix]['total_minutes']for m in alternatives.values()]),
                'longest_continuous_minutes':limits([m[side]['actual_occupied_exposure']['air_temperature_bins'][ix]['longest_continuous_minutes']for m in alternatives.values()])}
                for ix,(lower,upper)in enumerate(AIR_BINS)]for side in ('A','B')}
            envelope['own_occupied_scenario_ranges']={side:{name:limits([
                endpoint for m in alternatives.values()if m[side][name]is not None for endpoint in m[side][name]])
                for name in ('occupied_air_temperature_range_C','occupied_radiant_temperature_range_C','occupied_RH_range_percent')}
                for side in ('A','B')}
            envelope['own_occupied_air_delta_duration_ranges']={side:{str(t):{direction:{
                key:limits([m[side]['own_occupied_same_clock_air_delta_durations'][str(t)][direction][key]for m in alternatives.values()])
                for key in ('total_minutes','longest_continuous_minutes')}for direction in ('B_warmer','B_cooler')}
                for t in THRESHOLDS}for side in ('A','B')}
        impacts.append({'room': room, 'primary': primary, 'observation': rollout,
                        'tested_primary_scenarios': alternatives if labels else None,
                        'tested_single_factor_range': envelope})
    for label in labels:
        report = next(r['contrast_sensitivity']for r in diagnostic_records if r['alternative']==label)
        assert abs(max_sensitivity[label] - report['occupied_air_temperature_contrast_sensitivity_C']) < 1e-6, ('TEMPERATURE_READBACK', cid, label)
        assert abs(max_actual_sensitivity[label]-report['actual_occupied_union_air_temperature_contrast_sensitivity_C'])<1e-6
        assert abs(max_absolute_sensitivity[label]-report['own_occupied_absolute_air_temperature_sensitivity_C'])<1e-6
    timeline_path = ROOT / 'results' / record['household_id'] / date / 'TEMPERATURE_TIMELINE.json.gz'
    save(timeline_path, timeline)
    summary = copy.deepcopy(source)
    for obsolete in ('electricity_comparison', 'temperature_exposure', 'simulation_uncertainty'):
        summary.pop(obsolete, None)
    summary['physical_readback_passed'] = summary.pop('passed')
    summary['schema'] = SCHEMA
    summary['source_physics'] = {'stage': SOURCE.name, 'summary_path': record['path'], 'summary_sha256': record['sha256'],
                                 'seal_sha256': SOURCE_SEAL, 'trace_evidence': scenario_evidence}
    summary['energy_changes'] = energy_summary(source, date)
    summary['thermal_impacts'] = {
        'sign': 'positive B warmer;negative B cooler;neither automatically means comfortable/uncomfortable',
        'air_temperature_is_not_subjective_comfort': True,
        'duration_resolution_minutes': STEP,
        'duration_thresholds_C': list(THRESHOLDS),
        'thresholds_are': 'descriptive physical differences;not human comfort,perception or acceptance thresholds',
        'occupancy_scope': 'each arm complete actual occupied exposure and other-arm-empty periods;common-occupancy deltas retained separately',
        'rooms': impacts, 'timeline_path': str(timeline_path.relative_to(ROOT)), 'timeline_sha256': sha(timeline_path)}
    summary['sensitivity_coverage'] = {
        'history_effectively_different':any(x in labels for x in ('history224','history7')),
        'diagnostic_records':diagnostic_records,
        'portal_flow_scales_tested': [0.5, 2.0] if 'portal_low'in labels else [],
        'background_leakage_ACH_tested':[.175,.7]if'leakage_low'in labels else [],
        'individually_assessed_with_distinct_scenarios': bool(labels),
        'status': 'tested_single_factor_scenarios_only' if labels else 'not_individually_assessed_with_distinct_scenarios',
        'primary_facility_B_minus_A_kWh_by_scenario': energies,
        'primary_facility_B_minus_A_tested_range_kWh': limits(list(energies.values())) if labels else None,
        'occupied_air_delta_max_pointwise_sensitivity_C': max_sensitivity or None,
        'actual_occupied_union_air_delta_max_pointwise_sensitivity_C':max_actual_sensitivity or None,
        'own_occupied_absolute_air_max_pointwise_sensitivity_C':max_absolute_sensitivity or None,
        'range_is_confidence_interval_or_guaranteed_bound': False,
        'joint_history_and_airflow_perturbations_tested': False,
        'full_observation_thermal_sensitivity_validated': False,
        'sensitivity_scope': 'primary08:00 to next08:00;new winter/spring/summer/autumn/extreme single-factor diagnostics under repaired V61 model',
        'human_acceptance_inferred': False}
    summary['display'] = display(summary)
    summary['summary_generation_passed'] = True
    out_path = timeline_path.parent / 'IMPACT_SUMMARY.json'
    save(out_path, summary)
    binding = {k: v for k, v in record.items() if k not in (
        'equal_service_energy_comparison_eligible', 'energy_interpretation', 'path', 'sha256')}
    binding.update({'path': str(out_path.relative_to(ROOT)), 'sha256': sha(out_path),
                    'source_physical_summary_path': record['path'], 'source_physical_summary_sha256': record['sha256'],
                    'temperature_timeline_path': str(timeline_path.relative_to(ROOT)), 'temperature_timeline_sha256': sha(timeline_path),
                    'distinct_sensitivity_scenarios_available': bool(labels),
                    'known_task_delivery_deficit_present': summary['energy_changes']['known_task_delivery_deficit_present'],
                    'delta_primary_facility_kWh': source['delta_primary_kWh']['facility'],
                    'delta_observation_facility_kWh': source['delta_rollout_kWh']['facility'],
                    'human_acceptance': None})
    return binding


def display(summary):
    """Neutral structured cards usable by a future questionnaire, no preference labels."""
    energy = summary['energy_changes']
    temperature_rows = []
    for room in summary['thermal_impacts']['rooms']:
        primary = room['primary']
        if not primary['A']['occupied_minutes'] and not primary['B']['occupied_minutes']:
            continue
        temperature_rows.append({'room': room['room'],
                                 'A_occupied_air_C': primary['A']['occupied_air_temperature_range_C'],
                                 'B_occupied_air_C': primary['B']['occupied_air_temperature_range_C'],
                                 'A_occupied_radiant_C': primary['A']['occupied_radiant_temperature_range_C'],
                                 'B_occupied_radiant_C': primary['B']['occupied_radiant_temperature_range_C'],
                                 'A_occupied_RH_percent': primary['A']['occupied_RH_range_percent'],
                                 'B_occupied_RH_percent': primary['B']['occupied_RH_range_percent'],
                                 'A_actual_occupied_exposure':primary['A']['actual_occupied_exposure'],
                                 'B_actual_occupied_exposure':primary['B']['actual_occupied_exposure'],
                                 'A_other_arm_empty_exposure':primary['A']['other_arm_empty_exposure'],
                                 'B_other_arm_empty_exposure':primary['B']['other_arm_empty_exposure'],
                                 'A_own_occupied_air_delta_durations':primary['A']['own_occupied_same_clock_air_delta_durations'],
                                 'B_own_occupied_air_delta_durations':primary['B']['own_occupied_same_clock_air_delta_durations'],
                                 'common_occupied_air_B_minus_A_C': primary['common_occupied_air_B_minus_A_range_C'],
                                 'durations': primary['air_delta_durations'],
                                 'tested_scenario_range': room['tested_single_factor_range']})
    coverage = summary['sensitivity_coverage']
    observation_rows=[{'room':r['room'],
        'A_occupied_air_C':r['observation']['A']['occupied_air_temperature_range_C'],
        'B_occupied_air_C':r['observation']['B']['occupied_air_temperature_range_C'],
        'A_actual_occupied_exposure':r['observation']['A']['actual_occupied_exposure'],
        'B_actual_occupied_exposure':r['observation']['B']['actual_occupied_exposure'],
        'A_other_arm_empty_exposure':r['observation']['A']['other_arm_empty_exposure'],
        'B_other_arm_empty_exposure':r['observation']['B']['other_arm_empty_exposure']}
        for r in summary['thermal_impacts']['rooms']if r['observation']['A']['occupied_minutes']or r['observation']['B']['occupied_minutes']]
    return {'energy_card': {'title': '电量变化（B−A）', 'primary_kWh': energy['primary']['facility_B_minus_A_kWh'],
                            'observation_kWh': energy['observation']['facility_B_minus_A_kWh'],
                            'primary_period': [energy['primary']['start'], energy['primary']['end']],
                            'observation_period': [energy['observation']['start'], energy['observation']['end']],
                            'task_delivery_deficit_present': energy['known_task_delivery_deficit_present'],
                            'meaning': '负值表示观测耗电较少；需同时查看任务完成情况和温度影响'},
            'temperature_card': {'title': '温度、湿度与持续时间', 'period': '当日08:00至次日08:00', 'rows': temperature_rows,
                                 'observation_period':[energy['observation']['start'],energy['observation']['end']],
                                 'observation_exposure_rows':observation_rows,
                                 'sensitivity_ranges_cover_primary_only':True,
                                 'resolution_minutes': STEP, 'subjective_comfort_rating': None,
                                 'duration_thresholds_meaning': '只描述物理温差，不是个人舒适或接受阈值'},
            'task_delivery_card': {'title': '任务完成与失败后果', 'A': energy['task_delivery']['A'], 'B': energy['task_delivery']['B'],
                                   'source_B_constraint_flags': summary['source_B_constraint_flags'],
                                   'state_recovery_status': energy['state_recovery_status']},
            'sensitivity_card': {'title': '敏感性验证覆盖范围',
                                 'this_case_status': coverage['status'],
                                 'tested_primary_energy_range_kWh': coverage['primary_facility_B_minus_A_tested_range_kWh'],
                                 'history_effectively_different': coverage['history_effectively_different'],
                                 'portal_flow_scales_tested': coverage['portal_flow_scales_tested'],
                                 'background_leakage_ACH_tested':coverage['background_leakage_ACH_tested'],
                                 'actual_occupied_union_air_delta_sensitivity_C':coverage['actual_occupied_union_air_delta_max_pointwise_sensitivity_C'],
                                 'own_occupied_absolute_air_sensitivity_C':coverage['own_occupied_absolute_air_max_pointwise_sensitivity_C'],
                                 'batch_distinct_cases_tested': 200, 'batch_cases_not_individually_assessed': 300,
                                 'scope': '原50户既有日期中预选冬春夏秋及极端案例200组；剩余300组未逐例验证。逐项列出实际完成的实验；单因素范围不是置信区间。'},
            'human_acceptance': None}


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()
    assert sha(SOURCE / 'FINAL_SEAL50.json') == SOURCE_SEAL
    assert sha(SOURCE / 'PHYSICAL_BINDINGS50.json') == SOURCE_BINDINGS
    seal = read(SOURCE / 'FINAL_SEAL50.json')
    assert sha(SOURCE / 'FILE_MANIFEST50.json.gz') == seal['manifest_sha256']
    manifest = {r['path']: r['sha256'] for r in read(SOURCE / 'FILE_MANIFEST50.json.gz')['files']}
    for name in ('PHYSICAL_BINDINGS50.json', 'SENSITIVITY_REVIEW.json', 'SENSITIVITY_SELECTION.json'):
        verified(SOURCE / name, manifest)
    bindings = read(SOURCE / 'PHYSICAL_BINDINGS50.json')
    assert bindings['households'] == 50 and bindings['pairs'] == len(bindings['records']) == 500
    assert bindings['type_counts'] == {'A': 5, 'B': 15, 'C': 16, 'D': 5, 'E': 4, 'F': 5}
    diagnostics=read(SOURCE/'SENSITIVITY_REVIEW.json');selection=read(SOURCE/'SENSITIVITY_SELECTION.json')
    diagnostic_cases={}
    for r in diagnostics['records']:diagnostic_cases.setdefault(r['case_id'],[]).append(r)
    assert len(diagnostic_cases)==200 and len(diagnostics['records'])==632
    assert set(diagnostic_cases)=={r['case_id']for r in selection['records']}
    work = [(r,manifest,diagnostic_cases.get(r['case_id'],[]))for r in bindings['records']]
    with ProcessPoolExecutor(max_workers=max(1, min(8, args.workers))) as pool:
        records = []
        for r in pool.map(assess_case, work, chunksize=4):
            records.append(r)
            if len(records) % 50 == 0:
                print(json.dumps({'regenerated': len(records), 'total': 500}), flush=True)
    distinct = {r['case_id'] for r in records if r['distinct_sensitivity_scenarios_available']}
    assert len(distinct) == 200
    output = {k: v for k, v in bindings.items() if k not in ('schema', 'records')}
    output.update({'schema': SCHEMA, 'records': records, 'source_physics_stage': SOURCE.name,
                   'source_physics_seal_sha256': SOURCE_SEAL, 'source_physics_bindings_sha256': SOURCE_BINDINGS,
                   'new_energyplus_runs_in_summary_generation':0,'physical_trajectories_modified_by_summary_generator':False,'source_physics_replayed_under_repaired_model':True,
                   'summary_logic_sha256': sha(Path(__file__)), 'policy_sha256': sha(ROOT / 'SUMMARY_POLICY.json')})
    save(ROOT / 'SUMMARY_BINDINGS50.json', output)
    coverage = {'schema': SCHEMA, 'total_households': 50, 'total_cases': 500,
                'primary_temperature_summaries': 500, 'observation_temperature_summaries': 500,
                'primary_temperature_timelines': 500,
                'different_effective_history_cases':200,'history224_cases':179,'history7_cases':21,'portal_flow_cases':200,'portal_flow_comparisons':400,
                'background_leakage_cases':16,'background_leakage_comparisons':32,
                'distinct_cases_with_effective_sensitivity_scenarios':200,
                'cases_not_individually_assessed_with_distinct_scenarios':300,
                'diagnostic_comparisons':632,'sensitive_case_ids':diagnostics['sensitive_case_ids'],
                'sensitive_comparisons':diagnostics['sensitive_comparisons'],
                'absolute_occupied_temperature_sensitive_case_ids':diagnostics['absolute_occupied_temperature_sensitive_case_ids'],
                'distinct_sensitivity_case_ids':sorted(distinct),'season_reason_counts':diagnostics['season_reason_counts'],
                'missing_household_season_dates':selection['missing_household_season_dates'],
                'selection':selection['selection_rule'],
                'sensitivity_scope':'primary interval only;one factor at a time;actual A/B occupied union;not joint perturbations,all500 robustness or field calibration',
                'subjective_comfort_or_preference_sensitivity_measured': False,
                'known_task_delivery_deficit_cases': sum(r['known_task_delivery_deficit_present'] for r in records),
                'new_energyplus_runs_in_summary_generation':0,'schedules_modified':False, 'human_labels_created': 0,
                'full1000_deferred_by_user': True}
    save(ROOT / 'COVERAGE50.json', coverage)
    assert sha(SOURCE / 'FINAL_SEAL50.json') == SOURCE_SEAL
    assert sha(SOURCE / 'PHYSICAL_BINDINGS50.json') == SOURCE_BINDINGS
    print(json.dumps({'completed':len(records),'effective_sensitivity_cases':len(distinct),'new_energyplus_runs_in_summary_generation':0}),flush=True)


if __name__ == '__main__':
    main()
