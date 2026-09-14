"""Offline precision probe against the current native EB -> EnergyPlus entry.

Only test-local option copies and generated reporting requests are widened.
This script does not change questionnaire files, planner code or deployed settings.
It exercises the current production execution adapter.
Network connections are prohibited; no real LLM response is tested.
"""
from contextlib import redirect_stdout, contextmanager, nullcontext
from copy import deepcopy
import argparse
import json
import os
import math
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'realtime_pilot'))
os.environ['PYTHON_DOTENV_DISABLED'] = '1'
os.environ.setdefault('EPLUS_ROOT', '/Applications/EnergyPlus-24-1-0')
# Non-secret test values permit constructing the client; its method is stubbed
# and the process-wide socket guard prevents any external request.
os.environ['LLM_API_KEY'] = 'offline-precision-fixture'
os.environ['LLM_BASE_URL'] = 'http://127.0.0.1:1/v1'
os.environ['USE_LLM'] = '1'


def prohibit_network(event, args):
    if event == 'socket.connect':
        raise RuntimeError('Precision audit prohibits network connections')


sys.addaudithook(prohibit_network)
from common import normalize_answers, write_json, file_hash, UPSTREAM
from paired_contract import QUESTIONS, LOOKUP, prepare, sanitize_profile
from household_config import ensure_household_config
from native_support import upstream
from native_runner import run_native
from native_assets import read_series
import native_assets
import native_runner
from verify_paired_physics import answers
from survey_time import LEGACY_STARTS


@contextmanager
def zone_synchronized_probe():
    """Compatibility flag: the verified clock now lives in native_runner."""
    from native_clock import VERSION
    assert VERSION == 'eb.appliance_zone_clock.v1'
    yield


def request_for(name, start, duration, temperature, earliest, latest, heater, ev):
    raw = answers()
    updates = {'H_ac_temp': f'{temperature:g}', 'H_ac': 'all_day',
               'H_electric_water_heater': str(heater[0]), 'D_electric_water_heater': str(heater[1]),
               'H_home_ev': str(ev[0]), 'D_home_ev': str(ev[1])}
    for device in ('washer', 'dishwasher', 'dryer'):
        updates.update({f'H_{device}': str(start), f'T_{device}': str(duration),
                        f'E_{device}': str(earliest), f'D_{device}': str(latest)})
    # Canonical string aliases are not a precision limitation (18 -> evening).
    for key, value in list(updates.items()):
        try:
            numeric = float(value)
        except ValueError:
            continue
        for option in LOOKUP[key]['options']:
            try:
                candidate = float(LEGACY_STARTS.get(option['value'], option['value']))
            except (ValueError, TypeError):
                continue
            if abs(candidate-numeric) < 1e-12:
                updates[key] = option['value']
                break
    rejected = []
    for key, value in updates.items():
        try:
            normalize_answers({key: value}, [key], LOOKUP)
        except ValueError:
            rejected.append(key)
    # Simulate admitting the values at intake without touching production schema.
    snapshot = deepcopy(QUESTIONS)
    for q in snapshot:
        if q['id'] in updates and updates[q['id']] not in [o['value'] for o in q['options']]:
            q['options'].append({'value': updates[q['id']], 'label': updates[q['id']]})
    raw.update(updates)
    lookup = {q['id']: q for q in snapshot}
    profile = sanitize_profile(normalize_answers(raw, list(lookup), lookup))
    original, scenario = prepare(profile, 'precision-' + name)
    request = {'profile': profile, 'original_plan': original, 'scenario': scenario,
               'questionnaire_snapshot': snapshot, 'household_id': 'synthetic-precision-' + name}
    house = ensure_household_config(request)
    return request, {'current_intake_rejected_fields': rejected, 'test_answers': updates,
                     'appliance_config': house['appliances'], 'ordinary_plan': house['ordinary_plan'],
                     'calendar_constraints': house['calendar']['days'][0]['constraints']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--zone-synchronized', action='store_true', help='Assert the installed zone-clock adapter regression checks')
    parser.add_argument('--ten-minute-matrix', action='store_true')
    parser.add_argument('--agent-duration-minutes',type=int,default=72)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    runner, _ = upstream()
    from energybridge.llm.client import LLMClient
    original_reporting = native_assets.reporting_assets

    def reporting(path):
        result = original_reporting(path)
        with Path(path).open('a') as target:
            target.write('\nOutput:Variable,*,Electric Equipment Electricity Energy,Timestep;\n'
                         'Output:Variable,*,Water Heater Electricity Energy,Timestep;\n'
                         'Output:Variable,*,Zone Thermostat Cooling Setpoint Temperature,Timestep;\n')
        return result

    cases = [
        ('aligned', 18., 1., 26., 8., 23., (16., 17.), (20., 22.)),
        ('decimal_hours', 18.2, 1.2, 26.3, 8.2, 23.4, (16.2, 17.4), (20.2, 22.4)),
        ('minute_input', 18 + 7/60, 73/60, 26.7, 8 + 7/60, 23 + 17/60,
         (16 + 7/60, 17 + 19/60), (20 + 7/60, 22 + 19/60)),
    ]
    report = {'api_calls': 0, 'network_prohibited': True, 'production_changed': False,
              'test_zone_synchronization': args.zone_synchronized,
              'method': 'native no_dr, no model calls; test-only input schema extension',
              'runner_sha256': file_hash(UPSTREAM/'experiments/benchmark/family_runner.py'),
              'cases': {}}
    for case in cases:
        name = case[0]
        req, info = request_for(*case)
        actions = info['ordinary_plan']['appliances']
        info['native_action_errors'] = runner._adaptive_v3_appliance_action_contract_errors(actions, info['appliance_config'])
        info['native_window_errors'] = runner._shiftable_service_window_errors(actions, info['appliance_config'])
        print('Running native EnergyPlus:', name, flush=True)
        with (args.output/(name+'.console.txt')).open('w') as log, redirect_stdout(log), \
             patch.object(LLMClient, 'chat_with_metrics', side_effect=AssertionError('Paid API forbidden')), \
             patch.object(native_assets, 'reporting_assets', reporting), \
             (zone_synchronized_probe() if args.zone_synchronized else nullcontext()):
            result = run_native(args.output/name, req, method='no_dr')
        write_json(args.output/(name+'.request.json'), req)
        traces = read_series(args.output/name, horizon=24, start_date=req['scenario']['simulation_start_date'])
        meters = {}
        for key, rows in traces.items():
            if 'Electric Equipment Electricity Energy' in key or 'Water Heater Electricity Energy' in key:
                nonzero = [r for r in rows if r['value'] > 1e-6]
                meters[key] = {'kwh': sum(r['value'] for r in rows)/3.6e6,
                               'active_intervals': nonzero}
            elif 'Zone Thermostat Cooling Setpoint Temperature' in key:
                meters[key] = {'values': sorted(set(round(r['value'],8) for r in rows))}
        info.update(seconds=result['seconds'], llm_call_count=result['native']['llm_call_count'],
                    ep_intervals=len(result['electricity']), meters=meters,
                    native_services=result['execution']['services'],
                    actual_no_dr_routine_actions=result['native']['no_dr_routine_actions'], controls={})
        for device in ('washer','dishwasher','dryer','ev','water_heater'):
            on = [r for r in result['controls'] if r['native_device_power_kw'].get(device,0)>1e-8]
            info['controls'][device] = {
                'active_rows': [{'start_h':r['start_h'],'end_h':r['end_h'],
                                 'kw':r['native_device_power_kw'][device],
                                 'actuator':r['actuators'].get(device)} for r in on],
                'integrated_trace_kwh':sum(r['native_device_power_kw'][device]*(r['end_h']-r['start_h']) for r in on)}
        info['cooling_setpoints_written'] = sorted(set(r['cooling_setpoint'] for r in result['controls']))
        info['heater_setpoint_transitions'] = []
        previous = None
        for row in result['controls']:
            value = row['actuators'].get('water_heater')
            if value != previous:
                info['heater_setpoint_transitions'].append({'hour':row['start_h'],'setpoint':value})
                previous = value
        report['cases'][name] = info
        write_json(args.output/'report.json', report)
        print(name, 'complete:', round(result['seconds'],2), 'seconds', flush=True)
    assert all(c['llm_call_count']==0 for c in report['cases'].values())
    # Pass a known fractional plan through the real native agent lifecycle.
    # Only the external model is replaced. Native validation/fallback/execution remain.
    duration=args.agent_duration_minutes/60
    req, _ = request_for('agent_fractional', 18.2, duration, 26.3, 8.2, 23.4,
                         (16.2,17.4), (20.2,22.4))
    raw = {k:v['value'] for k,v in req['profile'].items()}
    raw['B05'] = ['ac','washer']
    lookup = {q['id']:q for q in req['questionnaire_snapshot']}
    profile = sanitize_profile(normalize_answers(raw,list(lookup),lookup))
    original, scenario = prepare(profile,'fixed-agent-precision')
    scenario['event'].update(trigger_h=20.,end_h=21.)
    req = {'profile':profile,'original_plan':original,'scenario':scenario,
           'questionnaire_snapshot':req['questionnaire_snapshot'],
           'household_id':'synthetic-agent-precision'}
    calls = []
    def fixed_model(client, system, user, **kwargs):
        if len(calls)>30:raise RuntimeError('Fixture call limit exceeded')
        calls.append({'planning':'[PLANNING PAYLOAD]' in user})
        if '[PLANNING PAYLOAD]' in user:
            payload=json.JSONDecoder().raw_decode(user.split('[PLANNING PAYLOAD]',1)[1].lstrip())[0]
            calls[-1]['payload']=payload
        # Same schedule at subsequent checkpoints; native completed-service
        # handling decides whether the action is still applicable.
        plan={'setpoint':26.3,'appliances':{'washer_start_h':planned_start,'washer_skip':False},
              'next_check_hour':23.9}
        response={'candidate_plans':[{'id':'precision_fixture','plan':plan}],
                  'selected_candidate_id':'precision_fixture','selection_reason':'Offline numerical precision test.'}
        return {'text':json.dumps(response),'metrics':{'fixture':True}}
    report['agent_probes']={}
    probes=[('agent_aligned',18.),('agent_fractional',18.2),('agent_minute',18+7/60)]
    if args.ten_minute_matrix:
        probes += [(f'agent_grid_{m:02d}',18+m/60) for m in (10,20,30,40,50)]
    for name,planned_start in probes:
        calls.clear()
        print('Running native EnergyPlus:',name,'(offline model fixture)',flush=True)
        with (args.output/(name+'.console.txt')).open('w') as log, redirect_stdout(log), \
             patch.object(LLMClient,'chat_with_metrics',new=fixed_model), \
             patch.object(native_assets,'reporting_assets',reporting), \
             (zone_synchronized_probe() if args.zone_synchronized else nullcontext()):
            result=run_native(args.output/name,deepcopy(req),method='agent')
        write_json(args.output/(name+'.request.json'),req)
        write_json(args.output/(name+'.fixture_calls.json'),calls)
        traces=read_series(args.output/name,horizon=24,start_date=req['scenario']['simulation_start_date'])
        meter=traces['Electric Equipment Electricity Energy|CLOTHESWASHER_APPLIANCE']
        active=[r for r in result['controls'] if r['native_device_power_kw'].get('washer',0)>0]
        decisions=[{k:row[k] for k in ('h','sp','requested_actions','actions','actuator_application') if k in row}
                   for day in result['native']['all_day_decisions'] for row in day]
        report['agent_probes'][name]={'stub_calls':len(calls),'paid_api_calls':0,
            'requested_start_h':planned_start,'requested_duration_h':duration,'requested_setpoint_c':26.3,
            'native_services':result['execution']['services'], 'decisions':decisions,
            'active_controls':active,
            'command_integral_kwh':sum(r['native_device_power_kw']['washer']*(r['end_h']-r['start_h']) for r in active),
            'expected_fixed_power_kwh':req['original_plan']['eb_appliance_config']['washer']['power_kw']*duration,
            'metered_kwh':sum(r['value'] for r in meter)/3.6e6,
            'metered_active_intervals':[r for r in meter if r['value']>1e-6],
            'cooling_setpoints_written':sorted(set(r['cooling_setpoint'] for r in result['controls']))}
        write_json(args.output/'report.json',report)
        assert calls, 'Native model fixture was not reached'
        assert abs(result['execution']['services']['washer'][0]['scheduled_abs_h']-planned_start)<1e-8, 'Fixed plan did not reach scheduler'
    if args.zone_synchronized:
        checks=[]
        for name,case in report['agent_probes'].items():
            expected_start=math.ceil(case['requested_start_h']*6-1e-8)/6
            checks.append({'case':name,'expected_grid_start_h':expected_start,
                           'start_passed':abs(case['active_controls'][0]['start_h']-expected_start)<1e-7,
                           'energy_passed':all(abs(case[key]-case['expected_fixed_power_kwh'])<1e-6
                                               for key in ('command_integral_kwh','metered_kwh'))})
        for name,case in report['cases'].items():
            for device,key in [('washer','CLOTHESWASHER_APPLIANCE'),('dishwasher','DISHWASHER_APPLIANCE'),('dryer','CLOTHESDRYER_APPLIANCE')]:
                config=case['appliance_config'][device]
                expected=config['power_kw']*config['duration_h']
                measured=case['meters']['Electric Equipment Electricity Energy|'+key]['kwh']
                commanded=case['controls'][device]['integrated_trace_kwh']
                checks.append({'case':name,'device':device,'energy_passed':abs(measured-expected)<1e-6 and abs(commanded-expected)<1e-6})
        report['candidate_checks']=checks
        write_json(args.output/'report.json',report)
        assert all(c['energy_passed'] and c.get('start_passed',True) for c in checks), 'Candidate precision regression'
    print('Report:', args.output/'report.json', flush=True)


if __name__ == '__main__':
    main()
