"""Literal change dimensions and timing relative to the fixed VPP boundary.

Time bands are explicit experimental reporting cells, never comfort/acceptance
levels. A minute of retiming is not a minute of additional human work.
"""
import copy
import math
from pathlib import Path
from ..common import digest, read

VERSION = 'eb.separate_action_axes.v1'
PROGRAMS = ('washer', 'dryer', 'dishwasher')
RULES = read(Path(__file__).with_name('ACTION_AXIS_RULES.json'))


def time_band(minutes, boundaries=None):
    if minutes is None:
        return 'unknown'
    if type(minutes) not in (int, float) or not math.isfinite(minutes):
        raise ValueError('INVALID_ACTION_MINUTES')
    cuts = RULES['time_boundaries_min'] if boundaries is None else boundaries
    if not cuts or list(cuts) != sorted(set(cuts)) or any(x <= 0 for x in cuts):
        raise ValueError('INVALID_ACTION_REPORTING_BOUNDARIES')
    x = abs(minutes)
    if x == 0:
        return 'unchanged'
    previous = 0
    for cut in cuts:
        if x <= cut:
            return f'up_to_{cut:g}_min' if not previous else f'over_{previous:g}_to_{cut:g}_min'
        previous = cut
    return f'over_{previous:g}_min'


def minutes_text(value):
    if value is None:
        return '未知'
    if value >= 60 and value == int(value):
        hours, minutes = divmod(int(value), 60)
        return f'{hours}小时' + (f'{minutes}分钟' if minutes else '') + f'（{value:g}分钟）'
    return f'{value:g}分钟'


def intersect(a, z, b, y):
    return max(0, min(z, y) - max(a, b))


def union_minutes(intervals, left, right):
    clipped = sorted((max(a, left), min(z, right)) for a, z in intervals if max(a, left) < min(z, right))
    total = 0
    end = left
    for a, z in clipped:
        total += max(0, z - max(a, end))
        end = max(end, z)
    return total


def thermal_timing(context, component, event):
    """Count actual changed request intervals, not a local relaxation anchor.

    Original construction uses lead minutes relative to the second phase. That
    phase may begin inside VPP; such preparation is never counted as pre-VPP.
    No inference about temperature, compressor state or realized response.
    """
    m = component['magnitude']
    patches = [p for p in component['patches'] if p['type'] == 'control_interval']
    lo, hi = event['start_min'], event['end_min']
    axis = m.get('axis', 'tank')
    field = 'value_C' if component['family'] == 'water_heater' else axis + '_setpoint_C'
    changed = []
    for p in patches:
        if field not in p.get('values', {}):
            continue
        for a in context['A']['controls']:
            if a['asset_id'] != component['asset_id'] or a['kind'] != p['kind']:
                continue
            left, right = max(p['start_min'], a['start_min']), min(p['end_min'], a['end_min'])
            if left < right and a.get(field) != p['values'][field]:
                changed.append((left, right))
    lead = m.get('construction_lead_min', m.get('precondition_min', 0))
    construction = component.get('construction_operator', component['mechanism'])
    is_two_phase = construction == 'precondition_and_relax' and lead > 0 and bool(patches)
    split = max((p['end_min'] for p in patches), default=lo) - m.get('duration_min', 0)
    prep_start = split - lead
    prep = [(max(a, prep_start), min(z, split)) for a, z in changed if max(a, prep_start) < min(z, split)] if is_two_phase else []
    before = union_minutes(prep, min([lo] + [a for a, z in prep]), lo)
    inside = union_minutes(prep, lo, hi)
    after = union_minutes(prep, hi, max([hi] + [z for a, z in prep]))
    phase = ('crosses_event_start_preparation' if before and inside else
             'pre_event_preparation' if before else 'in_event_preparation' if inside else
             'outside_event_preparation' if after else 'no_changed_preparation')
    direction = m.get('direction')
    kind = ('cooling_request' if axis == 'cooling' else 'heating_request') if direction == 'aligned' else 'opposing_threshold_request'
    return dict(event_start_min=lo, event_end_min=hi,
        construction_lead_min=lead, preparation_interval_min=[prep_start, split] if is_two_phase else None,
        pre_event_preparation_min=before, in_event_preparation_min=inside,
        after_event_preparation_min=after, event_changed_request_min=union_minutes(changed, lo, hi),
        phase=phase, preparation_kind=kind if prep else None,
        before_event_cooling_request=bool(before and axis == 'cooling' and direction == 'aligned'),
        before_event_heating_request=bool(before and axis != 'cooling' and direction == 'aligned'),
        actual_response_known=False)


def describe(context, component, event):
    m = component['magnitude']
    family = component['family']
    operations = {o['operation_id']: o for o in context['A']['operations']}
    shifts = []
    for p in component['patches']:
        if p.get('collection') != 'operations':
            continue
        for o in p['rows']:
            a = operations.get(o['operation_id'])
            if a is None:
                raise ValueError('UNKNOWN_OPERATION_IN_ACTION_AXES')
            shifts.append(dict(operation_id=o['operation_id'], kind=o['kind'],
                signed_start_shift_min=o['start_min'] - a['start_min'],
                active_duration_delta_min=(o['end_min'] - o['start_min']) - (a['end_min'] - a['start_min'])))
    manual_max = max((abs(o['signed_start_shift_min']) for o in shifts), default=0)
    machine = m.get('signed_machine_shift_min') if family in PROGRAMS else None
    result = dict(schema=VERSION,
        machine=dict(signed_start_shift_min=machine, absolute_start_shift_min=None if machine is None else abs(machine),
                     time_band=time_band(machine)),
        handling=dict(operations=shifts, maximum_absolute_retime_min=manual_max,
            sum_absolute_retime_min=sum(abs(o['signed_start_shift_min']) for o in shifts),
            time_band=time_band(manual_max), additional_operation_count=0,
            active_duration_delta_min=sum(o['active_duration_delta_min'] for o in shifts),
            retiming_is_not_extra_work_minutes=True, experienced_burden=None),
        whole_proposal_intensity=None)
    if family == 'ev':
        pause = m.get('permission_pause_interval_min')
        if pause is None:
            patch = next((p for p in component['patches'] if p['type'] == 'control_pause'), None)
            pause = [patch['start_min'], patch['end_min']] if patch else None
        length = pause[1] - pause[0] if pause else m.get('pause_min')
        result['charging_permission'] = dict(pause_interval_min=pause, pause_duration_min=length,
            time_band=time_band(length), not_actual_charger_runtime=True)
    if family in ('ac', 'water_heater'):
        timing = thermal_timing(context, component, event)
        ac = m.get('ac_intervention', {})
        delta = (ac.get('max_comparable_setpoint_delta_C') if m.get('axis') == 'cooling' else
                 m.get('actual_max_command_delta_C', m.get('service_delta_C')))
        # The stop-cooling fallback has no comparable comfort-temperature delta.
        stop = ac.get('cooling_stop_requested_min', 0)
        if stop and m.get('axis') == 'cooling':
            delta = None
        result['thermal'] = dict(axis=m.get('axis', 'tank'), comparable_setpoint_delta_C=delta,
            cooling_stop_request_min=stop, control_state_request=ac.get('state_change', 'not_applicable'),
            additional_temperature_control_enabled_min=ac.get('additional_thermostat_enabled_min', 0),
            availability_off_proved=False, timing=timing)
    return result


def labels(axes):
    """Factors used in both conditional coverage and selection; no mixed dose."""
    if axes.get('schema') != VERSION:
        raise ValueError('UNKNOWN_ACTION_AXES_SCHEMA')
    out = {}
    if axes['machine']['signed_start_shift_min'] is not None:
        out['machine_shift'] = time_band(axes['machine']['signed_start_shift_min'])
        out['handling_retime'] = time_band(axes['handling']['maximum_absolute_retime_min'])
    if 'charging_permission' in axes:
        out['permission_pause'] = time_band(axes['charging_permission']['pause_duration_min'])
    if 'thermal' in axes:
        t = axes['thermal']; timing = t['timing']; delta = t['comparable_setpoint_delta_C']
        out.update(temperature_delta='not_comparable_state_change' if delta is None else f'{delta:g}_C',
            event_control_duration=time_band(timing['event_changed_request_min']),
            pre_event_preparation=time_band(timing['pre_event_preparation_min']),
            in_event_preparation=time_band(timing['in_event_preparation_min']),
            phase=timing['phase'], cooling_stop_duration=time_band(t['cooling_stop_request_min']))
        if t['control_state_request'] != 'not_applicable':
            out['control_state'] = t['control_state_request']
            out['additional_enable_duration'] = time_band(t['additional_temperature_control_enabled_min'])
    return out


def annotate(context, component, event):
    """Only metadata is changed; literal patches and service declarations stay."""
    axes = describe(context, component, event)
    if 'change_axes' not in component:
        component['legacy_axis_metadata'] = {k: component.get(k) for k in ('relative_level', 'absolute_level')}
    component['change_axes'] = axes
    component['relative_level'] = dict(small_relative='domain_lower_third', medium_relative='domain_middle_third',
        large_relative='domain_upper_third').get(component.get('relative_level'), component.get('relative_level'))
    component['absolute_level'] = 'separate_axes_no_overall_level'
    m = copy.deepcopy(component['magnitude'])
    if 'thermal' in axes:
        timing = axes['thermal']['timing']
        construction = component.get('construction_operator', component['mechanism'])
        if construction == 'precondition_and_relax':
            component['construction_operator'] = construction
            component['mechanism'] = {
                'pre_event_preparation': 'pre_event_prepare_and_relax',
                'in_event_preparation': 'in_event_prepare_and_relax',
                'crosses_event_start_preparation': 'cross_event_prepare_and_relax',
                'outside_event_preparation': 'outside_event_prepare_and_relax',
                'no_changed_preparation': 'two_phase_without_changed_preparation'}[timing['phase']]
        m['construction_lead_min'] = timing['construction_lead_min']
        m['precondition_min'] = timing['pre_event_preparation_min']
        m['precondition_min_semantics'] = 'changed_preparation_request_minutes_before_fixed_VPP_start'
        m['pre_event_preparation_min'] = timing['pre_event_preparation_min']
        m['in_event_preparation_min'] = timing['in_event_preparation_min']
        if 'ac_intervention' in m:
            ac = m['ac_intervention']
            ac.update(schema='eb.ac_intervention.v2', preconditioning_min=timing['pre_event_preparation_min'],
                in_event_preparation_min=timing['in_event_preparation_min'],
                timing=timing, amplitude_axes={**labels(axes),
                    'temperature_offset': labels(axes)['temperature_delta'],
                    'preconditioning': time_band(timing['pre_event_preparation_min']),
                    'event_duration': time_band(timing['event_changed_request_min'])}, whole_intervention_intensity=None)
    component['magnitude'] = m
    return component


def presentation(component):
    a = component['change_axes']; parts = []
    shift = a['machine']['signed_start_shift_min']
    if shift is not None:
        parts.append('机器' + ('不改时' if not shift else ('提前' if shift < 0 else '推迟') + minutes_text(abs(shift))))
        names = {'load': '装入', 'unload': '取出'}
        for o in a['handling']['operations']:
            x = o['signed_start_shift_min']
            parts.append(names.get(o['kind'], o['kind']) + ('不改时' if not x else ('提前' if x < 0 else '推迟') + minutes_text(abs(x))))
        parts.append('未增加操作次数；移时分钟不等于额外劳动分钟')
    if 'charging_permission' in a:
        parts.append('暂停充电许可' + minutes_text(a['charging_permission']['pause_duration_min']) + '，不等于实际少充这些分钟')
    if 'thermal' in a:
        t = a['thermal']; timing = t['timing']
        if timing['pre_event_preparation_min']:
            name = ('VPP前预冷请求' if timing['before_event_cooling_request'] else
                    'VPP前预热请求' if timing['before_event_heating_request'] else 'VPP前反向设定调节请求')
            parts.append(name + minutes_text(timing['pre_event_preparation_min']))
        if timing['in_event_preparation_min']:
            parts.append('VPP内首阶段调节' + minutes_text(timing['in_event_preparation_min']))
        if t['cooling_stop_request_min']:
            parts.append('请求停冷' + minutes_text(t['cooling_stop_request_min']) + '，未证明整机关闭')
        if t['additional_temperature_control_enabled_min']:
            parts.append('新增温控许可' + minutes_text(t['additional_temperature_control_enabled_min']) + '，不是实际运行时长')
        if t['comparable_setpoint_delta_C'] is not None:
            parts.append(f"可比设定变化{t['comparable_setpoint_delta_C']:g}℃")
        parts.append('实际运行与服务后果未计算')
    return '；'.join(parts)


def refresh_row_features(row):
    row['change_axes_version'] = VERSION
    axes = sorted({c['family'] + '.' + k + '=' + v for c in row['components'] for k, v in labels(c['change_axes']).items()})
    row['features'].update(amplitude_axes=axes, amplitude_profile=';'.join(axes),
        mechanisms=sorted({c['mechanism'] for c in row['components']}) or ['control'],
        intensity='separate_dimensions;no_overall_small_medium_large')


def annotate_frozen_row(context, original, event):
    """Independent annotation overlay; keep case IDs, literal patches and tails."""
    row = copy.deepcopy(original)
    for component in row['components']:
        annotate(context, component, event)
    refresh_row_features(row)
    judgments = {j['component_id']: j for j in row.get('judgment_context', []) if 'component_id' in j}
    for component in row['components']:
        judgment = judgments.get(component['id'])
        if judgment is None:
            continue
        reasons = [r for r in judgment['confirmation_reasons'] if r != 'PRECONDITIONING_EXECUTION_CONSENT_NOT_OBTAINED']
        m = component['magnitude']
        if m.get('pre_event_preparation_min'):
            reasons.append('PRE_EVENT_PREPARATION_REQUIRES_CONFIRMATION')
        if m.get('in_event_preparation_min'):
            reasons.append('IN_EVENT_PREPARATION_REQUIRES_CONFIRMATION')
        judgment['confirmation_reasons'] = sorted(set(reasons))
    row['annotation_provenance'] = dict(version=VERSION, source_row_sha256=digest(original),
        literal_case_id_preserved=True, original_selection_not_changed=True)
    return row
