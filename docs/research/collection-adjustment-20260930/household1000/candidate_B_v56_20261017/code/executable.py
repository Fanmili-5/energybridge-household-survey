"""Executable commands only; representation, service IDs and projections are not actions.

Half-open intervals retain real gaps. Adjacent identical control states merge;
manual operations and appliance programs remain separate executable requests.
No physics or human response is used in this comparison.
"""
import collections
from common import canonical

SCHEMA = 'eb.executable_commands.v48'

def number(value):
    value = float(value)
    return 0.0 if value == 0 else value

def commands(plan, end=None):
    result = {'schema': SCHEMA, 'tasks': [], 'operations': [], 'controls': []}
    for kind, keys in [('tasks', ('kind','asset_id')),
                       ('operations', ('kind','asset_id','operator_id','room_id'))]:
        for item in plan[kind]:
            a, b = item['start_min'], item['end_min']
            if end is not None:
                if a >= end: continue
                b = min(b, end)
            result[kind].append({**{key:item[key] for key in keys}, 'start_min':a, 'end_min':b})
        result[kind].sort(key=canonical)
    groups = collections.defaultdict(list)
    for item in plan['controls']:
        kind = item['kind']
        if kind == 'ac_setpoint':
            values = {'heating_setpoint_C':number(item['heating_setpoint_C']),
                      'cooling_setpoint_C':number(item['cooling_setpoint_C']),
                      'fan_operating_mode':int(item['fan_operating_mode'])}
        elif kind == 'tank_setpoint':
            values = {'value_C':number(item['value_C'])}
        elif kind == 'ev_charge_window':
            values = {'stop_at_target_soc':number(item['stop_at_target_soc'])}
        else:
            raise ValueError('UNREGISTERED_EXECUTABLE_CONTROL:'+kind)
        a, b = item['start_min'], item['end_min']
        if end is not None:
            if a >= end: continue
            b = min(b, end)
        state = canonical({'kind':kind, 'asset_id':item['asset_id'], **values})
        groups[state].append((a,b))
    import json
    for state, intervals in sorted(groups.items()):
        merged = []
        for a, b in sorted(intervals):
            if merged and a <= merged[-1][1]: merged[-1][1] = max(b, merged[-1][1])
            else: merged.append([a,b])
        result['controls'].extend({**json.loads(state), 'start_min':a, 'end_min':b} for a,b in merged)
    result['controls'].sort(key=canonical)
    return result
