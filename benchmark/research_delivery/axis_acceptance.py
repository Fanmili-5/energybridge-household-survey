"""Independent checks of new annotations against preserved literal plans."""
from collections import Counter

from benchmark.ab_generation.common import digest
from benchmark.ab_generation.model import apply


RETAINED = ('id', 'household_id', 'date', 'patches', 'component_ids', 'independent_units',
    'issues', 'consent_status', 'known_event_reduction_kWh', 'unknown_thermal_response',
    'A_commands_sha256', 'working_B_sha256', 'portrait_sha256',
    'human_acceptance', 'human_score', 'human_reason', 'actual_outcomes')


def band(minutes):
    if minutes is None:
        return 'unknown'
    x = abs(minutes)
    return ('unchanged' if x == 0 else 'up_to_30_min' if x <= 30 else
            'over_30_to_60_min' if x <= 60 else 'over_60_to_120_min' if x <= 120 else 'over_120_min')


def check(context, original, annotated):
    """No calls to the new annotation mapper, bander, or timing classifier."""
    from .change_axes_review import independent_preparation
    errors = []
    if any(original.get(k) != annotated.get(k) for k in RETAINED):
        errors.append('SOURCE_ACTION_OR_JUDGMENT_CHANGED')
    if any(annotated.get(k) is not None for k in ('actual_outcomes', 'human_acceptance', 'human_score', 'human_reason')):
        errors.append('DOWNSTREAM_VALUE_PRESENT')
    if len(original['components']) != len(annotated['components']):
        return errors + ['COMPONENT_COUNT_CHANGED']
    tasks = {t['task_id']: t for t in context['A']['tasks']}
    ops = {o['operation_id']: o for o in context['A']['operations']}
    for source, child in zip(original['components'], annotated['components']):
        if any(source.get(k) != child.get(k) for k in ('id', 'unit', 'asset_id', 'family', 'service_need_id', 'patches', 'event_relevance')):
            errors.append('COMPONENT_ACTION_OR_REASON_CHANGED')
        a = child['change_axes']
        expected_ops = []
        task_shifts = []
        for p in source['patches']:
            if p.get('collection') == 'tasks':
                task_shifts.extend(t['start_min'] - tasks[t['task_id']]['start_min'] for t in p['rows'])
            elif p.get('collection') == 'operations':
                for o in p['rows']:
                    old = ops[o['operation_id']]
                    expected_ops.append(dict(operation_id=o['operation_id'], kind=o['kind'],
                        signed_start_shift_min=o['start_min'] - old['start_min'],
                        active_duration_delta_min=o['end_min'] - o['start_min'] - old['end_min'] + old['start_min']))
        actual_ops = a['handling']['operations']
        if sorted(expected_ops, key=lambda x:x['operation_id']) != sorted(actual_ops, key=lambda x:x['operation_id']):
            errors.append('HANDLING_LITERAL_MISMATCH')
        maximum = max((abs(o['signed_start_shift_min']) for o in expected_ops), default=0)
        if (a['handling']['maximum_absolute_retime_min'] != maximum or
                a['handling']['sum_absolute_retime_min'] != sum(abs(o['signed_start_shift_min']) for o in expected_ops) or
                a['handling']['time_band'] != band(maximum) or
                a['handling']['active_duration_delta_min'] != sum(o['active_duration_delta_min'] for o in expected_ops) or
                a['handling']['additional_operation_count'] != 0 or a['handling']['experienced_burden'] is not None):
            errors.append('HANDLING_AXIS_OR_EXTRA_WORK_MISMATCH')
        if source['family'] in ('washer', 'dryer', 'dishwasher'):
            shift = a['machine']['signed_start_shift_min']
            if not task_shifts or set(task_shifts) != {shift} or a['machine']['time_band'] != band(shift):
                errors.append('MACHINE_LITERAL_OR_BAND_MISMATCH')
        if a['whole_proposal_intensity'] is not None:
            errors.append('UNSUPPORTED_WHOLE_PROPOSAL_INTENSITY')
        if 'charging_permission' in a:
            pause = next((p for p in source['patches'] if p['type'] == 'control_pause'), None)
            if pause:
                value = a['charging_permission']
                if (value['pause_interval_min'] != [pause['start_min'], pause['end_min']] or
                        value['pause_duration_min'] != pause['end_min'] - pause['start_min'] or
                        value['time_band'] != band(pause['end_min'] - pause['start_min']) or
                        value['not_actual_charger_runtime'] is not True):
                    errors.append('EV_PERMISSION_NOT_LITERAL_OR_CALLED_RUNTIME')
        if 'thermal' in a:
            t = a['thermal']['timing']
            expected = independent_preparation(context, source)
            if expected != (t['pre_event_preparation_min'], t['in_event_preparation_min']):
                errors.append('THERMAL_BOUNDARY_MINUTES_MISMATCH')
            if t['event_start_min'] != 1080 or t['event_end_min'] != 1140:
                errors.append('EVENT_BOUNDARY_CHANGED')
            if child['magnitude']['precondition_min'] != expected[0]:
                errors.append('LOCAL_LEAD_WRONGLY_CALLED_PRE_VPP')
            B = apply(context['A'], source['patches'])
            field = 'value_C' if source['family'] == 'water_heater' else source['magnitude']['axis'] + '_setpoint_C'
            count = 0
            for minute in range(1080,1140,10):
                old = next((r.get(field) for r in context['A']['controls'] if r['asset_id']==source['asset_id'] and r['start_min']<=minute<r['end_min']), None)
                new = next((r.get(field) for r in B['controls'] if r['asset_id']==source['asset_id'] and r['start_min']<=minute<r['end_min']), None)
                if old is not None and new is not None and old != new:
                    count += 10
            if t['event_changed_request_min'] != count:
                errors.append('EVENT_REQUEST_DURATION_MISMATCH')
            stop = source['magnitude'].get('ac_intervention',{}).get('cooling_stop_requested_min',0)
            if stop and a['thermal']['comparable_setpoint_delta_C'] is not None:
                errors.append('FALLBACK40_USED_AS_TEMPERATURE_AMPLITUDE')
            if a['thermal']['availability_off_proved'] is not False:
                errors.append('UNOBSERVED_HARD_OFF_CLAIM')
    if digest(original['patches']) != digest(annotated['patches']):
        errors.append('LITERAL_PLAN_PATCH_CHANGED')
    return sorted(set(errors))


def dimensions(rows):
    result = Counter()
    for row in rows:
        for c in row['components']:
            a = c['change_axes']
            if c['family'] in ('washer', 'dryer', 'dishwasher'):
                result['machine.' + band(a['machine']['signed_start_shift_min'])] += 1
                result['handling.' + band(a['handling']['maximum_absolute_retime_min'])] += 1
            if 'charging_permission' in a:
                result['permission_pause.' + band(a['charging_permission']['pause_duration_min'])] += 1
            if 'thermal' in a:
                result['thermal.phase.' + a['thermal']['timing']['phase']] += 1
    return dict(result)
