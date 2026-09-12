"""Load pinned EB modules and equipment inputs; no legacy execution code."""
from functools import lru_cache
import json
import os
import sys
from common import UPSTREAM

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
