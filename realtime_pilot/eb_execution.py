"""Replay frozen questionnaire plans through the pinned EB appliance executor.

This is a paired-experiment adapter, not the full continuously replanning runner.
No household scorer, acceptance gate, or synthetic rating is invoked.
"""
from contextlib import redirect_stdout
from copy import deepcopy
from functools import lru_cache
from io import StringIO
import json
import math
import os
import sys
from types import SimpleNamespace
from common import UPSTREAM, file_hash

MODEL = UPSTREAM / 'energybridge/roleplay/personas/all_appliances_full.json'

@lru_cache(maxsize=1)
def upstream():
    # Original runner/config imports may discover parent .env files.
    # Credentials are supplied only through explicit runtime configuration.
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    if str(UPSTREAM) not in sys.path:
        sys.path.insert(0, str(UPSTREAM))
    from experiments.benchmark import family_runner
    from energybridge.simulation.appliance_sim import ApplianceSuite
    return family_runner, ApplianceSuite

def physical_defaults():
    # Read only equipment model values. Never import the persona's attitudes,
    # scoring weights, refusal probability, routines, or authorizations.
    return json.loads(MODEL.read_text())['appliances']

def ordinary(config):
    runner, _ = upstream()
    plan = runner._manual_no_vpp_user_plan(
        persona_config=None, appliance_config=config,
        current_setpoint=config['ac'].get('setpoint_preferred_max_c'))
    return {'setpoint': plan['setpoint'], 'appliances': plan['appliance_actions']}

def validate_shape(original, plan, scenario):
    runner, _ = upstream()
    errors = runner._adaptive_v3_plan_control_errors(
        plan, sim_h=72 + scenario['decision_h'], total_sim_hours=96,
        setpoint_min_c=runner.SP_MIN, setpoint_max_c=runner.SP_MAX)
    if errors:
        raise ValueError('; '.join(errors))
    # Only JSON scalar execution inputs here; policy/runtimes are handled by EB.
    for key, val in plan['appliances'].items():
        if isinstance(val, float) and not math.isfinite(val):
            raise ValueError('Non-finite appliance action: '+key)
    return deepcopy(plan)

def replay(original, plan, scenario, *, proposal=True, stop_at_notification=False, sim_days=4):
    """Keep P0 state to notification, then let EB accept/normalize/reject P1.

    Actuator values come directly from EB's writer. They are translated into EP
    schedules by paired_ep; rejected commands remain visible in the application
    record and are never replaced by an independently chosen pilot strategy.
    """
    runner, Suite = upstream()
    config = original['eb_appliance_config']
    p0 = original['eb_ordinary_plan']
    cutoff = 72 + scenario['decision_h']
    event = scenario['event']
    events = [{'trigger_h':72+event['trigger_h'], 'end_h':72+event['end_h']}]
    suite = Suite(config, sim_days=sim_days, vpp_events=events if proposal else [], explicit_only=True)
    handles = {'washer':'h_washer', 'dishwasher':'h_dishwasher', 'dryer':'h_dryer',
               'ev':'h_ev', 'water_heater':'h_ewh_sp', 'refrigerator':'h_refrigerator'}
    loop = SimpleNamespace(appliance_suite=suite)
    for device, attr in handles.items():
        setattr(loop, attr, device if config.get(device, {}).get('present', False) else -1)
    values = {}
    class Exchange:
        def set_actuator_value(self, state, handle, value): values[handle] = value
    exchange = Exchange()
    rows, applications = [], []
    logs = StringIO()
    with redirect_stdout(logs):
        for i in range(sim_days*144):
            sim_h = i / 6
            if i % 144 == 0:
                application = runner._adaptive_v3_apply_appliance_actions(suite, p0['appliances'], sim_h)
                applications.append({'sim_h':sim_h, 'kind':'ordinary', **application})
            if stop_at_notification and abs(sim_h-cutoff) < 1e-8:
                return loop
            if proposal and abs(sim_h-cutoff) < 1e-8:
                application = runner._adaptive_v3_apply_appliance_actions(suite, plan['appliances'], sim_h)
                applications.append({'sim_h':sim_h, 'kind':'proposal', **application})
            powers = suite.step(sim_h, 1/6)
            runner._write_appliance_actuators(exchange, None, loop, powers, sim_h)
            rows.append({'sim_h':sim_h, 'actuators':dict(values), 'model_power_kw':dict(powers)})
    return {'rows':rows, 'applications':applications, 'services':suite.all_results(),
            'log':logs.getvalue(), 'source':source_manifest()}

def source_manifest():
    return {'commit':'2b17ae63e613da776c93e900f5dace50d63a88a8',
            'ordinary_function':'family_runner._manual_no_vpp_user_plan',
            'application_function':'family_runner._adaptive_v3_apply_appliance_actions',
            'power_function':'appliance_sim.ApplianceSuite.step',
            'actuator_function':'family_runner._write_appliance_actuators',
            'runner_sha256':file_hash(UPSTREAM/'experiments/benchmark/family_runner.py'),
            'appliance_sim_sha256':file_hash(UPSTREAM/'energybridge/simulation/appliance_sim.py'),
            'equipment_defaults_sha256':file_hash(MODEL),
            'native_context_sha256':{name:file_hash(UPSTREAM/name) for name in (
                'energybridge/harness/profile_v3.py','energybridge/harness/operations_knowledge_v3.py',
                'energybridge/harness/energy_tools_v3.py','energybridge/harness/memory_v3.py')},
            'household_scorer_called':False,
            'scope':'frozen proposal replay; not the complete online benchmark controller'}
