"""Technical compatibility of accepted native commands with the pinned EP writer.

This does not grade plans, comfort, savings or user acceptance, and never changes
an EB action. Check the actual application ledger, not requested LLM actions or
the abstract appliance model's power report. A clean result means only that none
of the known incompatibilities checked here was found.
"""
from copy import deepcopy
import math

VERSION='eb.native_execution_diagnostics.v1'
SOURCE={
    'upstream_commit':'2b17ae63e613da776c93e900f5dace50d63a88a8',
    'application':'experiments/benchmark/family_runner.py::_adaptive_v3_apply_appliance_actions',
    'writer':'experiments/benchmark/family_runner.py::_write_appliance_actuators',
    'appliance_model':'energybridge/simulation/appliance_sim.py::WaterHeater.step',
    'evidence_basis':'accepted execution.applications[].applied_actions; not requested_actions or inferred power',
}


def diagnose_native_execution(trace, *, branch='proposal'):
    """Inspect a completed ``simulate_live`` trace before admitting human rating.

    Returns JSON-safe execution_compatible/issues/source. Missing or malformed
    ledgers cannot establish compatibility and fail closed with a trace issue.
    A rejected or disabled heater request is not diagnosed as an active command.
    """
    issues=[]
    execution=trace.get('execution') if isinstance(trace,dict) else None
    applications=execution.get('applications') if isinstance(execution,dict) else None
    if not isinstance(applications,list):
        issues.append({'code':'native_application_ledger_missing','branch':branch,
                       'detail':'A native application ledger is required to check accepted commands.'})
        applications=[]
    checked=0
    for index,application in enumerate(applications):
        base={'branch':branch,'application_index':index}
        if not isinstance(application,dict) or not isinstance(application.get('applied_actions'),dict):
            issues.append({**base,'code':'native_application_record_invalid',
                           'detail':'The native application record lacks an applied_actions object.'})
            continue
        actions=application['applied_actions']
        if actions.get('water_heater_preheat') is not True:
            continue
        checked+=1
        context={**base,'sim_h':application.get('sim_h'),'application_kind':application.get('kind'),
                 'service':'water_heater','applied_actions':deepcopy(actions)}
        start=actions.get('water_heater_preheat_start_h');end=actions.get('water_heater_preheat_end_h')
        if any(type(value) not in (float,int) or not math.isfinite(value) for value in (start,end)):
            issues.append({**context,'code':'native_applied_water_window_invalid',
                           'detail':'An accepted enabled water-heater command lacks finite numeric start/end hours.'})
            continue
        if start==0:
            issues.append({**context,'code':'native_water_midnight_start_fallback',
                           'detail':'The pinned EP writer uses start or default and substitutes midnight zero; accepted command and EP setpoint execution are not faithful.'})
        if end<=start:
            issues.append({**context,'code':'native_water_nonincreasing_window',
                           'detail':'The pinned heater step and EP writer use start <= hour < end; this accepted cross-midnight/nonincreasing interval is not executed as the commanded heating window.'})
    return {'schema_version':VERSION,'execution_compatible':not issues,'branch':branch,
            'checked_application_count':len(applications),'checked_enabled_water_commands':checked,
            'issues':issues,'source':deepcopy(SOURCE),
            'scope':'Known native technical command/execution compatibility only; not plan quality, comfort, energy savings or human evaluation.'}
