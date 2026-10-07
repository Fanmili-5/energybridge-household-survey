"""Keep explainable B constraint conflicts; reject corrupted worlds/bindings."""
import sys
from pathlib import Path
SRC=Path(__file__).resolve().parents[2]/'joint_static_production_20261007_v16'
sys.path.insert(0,str(SRC/'code'))
from validate import validate

# These do not corrupt an EnergyPlus program or thermal control input.
EXPLAINABLE={'B:RELEASE_OR_DEADLINE','B:AC_REFERENCE_LIMIT'}

def assess(pair):
    errors=validate(pair)
    hard=[e for e in errors if e not in EXPLAINABLE]
    flags=[e for e in errors if e in EXPLAINABLE]
    family=pair.get('proposal',{}).get('family')
    if family=='ev_short_charge_window':
        flags.append('B:AVAILABLE_CHARGE_ENERGY_BELOW_GIVEN_TRIP_ENERGY')
    if family=='hotwater_low_heat_target':
        flags.append('B:HEATING_TARGET_BELOW_GIVEN_MIXED_WATER_TARGET')
    return {'integrity_errors':hard,'constraint_or_service_risk_flags':sorted(set(flags)),
            'role_response':None,'constraint_flags_are_not_rejection_labels':True}
