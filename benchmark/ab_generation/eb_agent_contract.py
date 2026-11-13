"""Paper-v1 primitive mapping and explicit benchmark construction rules.

Benchmark choices (continuous EV, required daily services and no non-EV
overnight) are explicit subsets, not claims that EB has no other operations.
"""
from copy import deepcopy
from types import SimpleNamespace
from collections import defaultdict
import math

from .paper_v1_clock import replay_clock, NS as PAPER_CONSTANTS

VERSION = "eb.paper_v1.operational_domain.v2"
KINDS = {"AC":"ac", "WM":"washer", "DR":"dryer", "DW":"dishwasher", "WH":"water_heater", "EV":"ev"}
AC_KEYS = {"cooling_setpoint_C"}
TASK_NAMES = {"washer", "dryer", "dishwasher"}

def household_bounds(household):
    # Household comfort is a soft questionnaire attribute, not admission bounds.
    return {"min_c":22.0,"max_c":28.0,"temperature_decimals":1,
            "heating_fixed_c":20.0,"projection":"paper_v1_global_operational_domain",
            "source_commit":"c58a2a7a3189482f57b93ddd0637f2c58ce5b5d0",
            "preferred_cooling_c":household["comfort"]["preferred_cooling_c"],
            "preference_conflicts_are_admitted":True}

def _finite(value):
    return not isinstance(value,bool) and isinstance(value,(int,float)) and math.isfinite(value)

def _by_kind(plan):
    groups = defaultdict(list)
    for row in plan.get("controls",[]):
        groups[(row.get("asset_id"),row.get("kind"))].append(row)
    return groups

def ac_calls(context,plan):
    """Compile same-day cooling thresholds into scalar Agent checkpoints."""
    calls = []
    decision = context["decision_min"]
    for (asset,kind),rows in _by_kind(plan).items():
        if kind != "ac_setpoint":
            continue
        rows = sorted(rows,key=lambda row:row["start_min"])
        current = next((r for r in rows if r["start_min"]<=decision<r["end_min"]),None)
        if current is None:
            continue
        calls.append({"asset_id":asset,"minute":decision,"setpoint":current["cooling_setpoint_C"]})
        previous = current["cooling_setpoint_C"]
        for row in rows:
            if decision < row["start_min"] <= 1440 and row["cooling_setpoint_C"] != previous:
                calls.append({"asset_id":asset,"minute":row["start_min"],"setpoint":row["cooling_setpoint_C"]})
                previous = row["cooling_setpoint_C"]
    return sorted(calls,key=lambda row:(row["asset_id"],row["minute"]))

def plan_errors(context,plan):
    if context.get("source",{}).get("appliance_command_protocol") != "eb.primary_appliance_calls.v1":
        return []
    errors = []
    a = context["A"]
    contract = context.get("native_execution_contract",{})
    limits = contract.get("agent_action_bounds")
    if not limits:
        return ["ORIGINAL_AGENT_ACTION_BOUNDS_NOT_BOUND"]
    if plan.get("operations"):
        errors.append("NON_EB_MANUAL_OPERATION")
    originals = {row["task_id"]:row for row in a["tasks"]}
    tasks = {row["task_id"]:row for row in plan["tasks"]}
    if set(originals) != set(tasks) or len(tasks) != len(plan["tasks"]):
        errors.append("AGENT_PROGRAMME_SERVICE_SET_CHANGED")
    for task_id,row in tasks.items():
        before = originals.get(task_id)
        if not _finite(row["start_min"]) or not _finite(row["end_min"]):
            errors.append("AGENT_PROGRAMME_INVALID_TIME_SCALAR")
        if before is None:
            continue
        if row != before and not context["authority"]["assets"].get(row["asset_id"],{}).get("target_control_authorized",False):
            errors.append("TARGET_CONTROL_NOT_AUTHORIZED")
        if row != before and min(row["start_min"],before["start_min"]) < context["decision_min"]:
            errors.append("AGENT_CANNOT_REWRITE_PAST_PROGRAMME")
        if row.get("kind") not in TASK_NAMES:
            errors.append("UNSUPPORTED_AGENT_PROGRAMME_KIND")
        if {k:v for k,v in row.items() if k not in {"start_min","end_min"}} != {k:v for k,v in before.items() if k not in {"start_min","end_min"}}:
            errors.append("AGENT_CANNOT_CHANGE_PROGRAMME_ID_POWER_OR_HARDWARE")
        if row["end_min"]-row["start_min"] != before["end_min"]-before["start_min"]:
            errors.append("AGENT_CANNOT_CHANGE_PROGRAMME_DURATION")
        if not 0<=row["start_min"]<row["end_min"]<=1440:
            errors.append("NON_EV_PROGRAMME_OVERNIGHT_FORBIDDEN")
    before_groups = _by_kind(a)
    after_groups = _by_kind(plan)
    if set(before_groups) != set(after_groups):
        errors.append("AGENT_CONTROL_SERVICE_SET_CHANGED")
    for key,rows in after_groups.items():
        originals = before_groups.get(key,[])
        asset,kind = key
        if not originals:
            continue
        authority = context["authority"]["assets"].get(asset,{})
        if not authority.get("target_control_authorized",False) and rows != originals:
            errors.append("TARGET_CONTROL_NOT_AUTHORIZED")
        if kind not in {"ac_setpoint","tank_setpoint","ev_charge_window"}:
            errors.append("UNSUPPORTED_AGENT_CONTROL_KIND")
            continue
        if kind == "ac_setpoint":
            ordered = sorted(rows,key=lambda row:row["start_min"])
            if not ordered or ordered[0]["start_min"] != originals[0]["start_min"] or ordered[-1]["end_min"] != originals[-1]["end_min"] or any(x["end_min"]!=y["start_min"] for x,y in zip(ordered,ordered[1:])):
                errors.append("AGENT_AC_CONTROL_TIMELINE_GAP_OR_OVERLAP")
            for row in ordered:
                before = next((r for r in originals if r["start_min"]<=row["start_min"]<r["end_min"]),None)
                if before is None:
                    errors.append("AGENT_AC_EXTRA_DATE")
                    continue
                variable = {"start_min","end_min","cooling_setpoint_C"}
                if {k:v for k,v in row.items() if k not in variable} != {k:v for k,v in before.items() if k not in variable}:
                    errors.append("AGENT_AC_ONLY_COOLING_SETPOINT_IS_MUTABLE")
                value = row.get("cooling_setpoint_C")
                if not _finite(value):
                    errors.append("AGENT_AC_INVALID_SCALAR")
                    continue
                if not limits["min_c"]<=value<=limits["max_c"]:
                    errors.append("OUTSIDE_ORIGINAL_AGENT_COOLING_RANGE")
                if abs(round(value,1)-value)>1e-8:
                    errors.append("AGENT_AC_TEMPERATURE_WOULD_BE_ROUNDED")
                if row.get("heating_setpoint_C") != 20.0:
                    errors.append("AGENT_HEATING_SETPOINT_MUST_REMAIN_20C")
                if row["start_min"] < context["decision_min"] and value != before["cooling_setpoint_C"]:
                    errors.append("AGENT_CANNOT_REWRITE_PAST_AC")
        else:
            if len(rows) != len(originals):
                errors.append("AGENT_REQUIRES_SINGLE_CONTIGUOUS_SERVICE_WINDOW")
                continue
            for row,before in zip(sorted(rows,key=lambda x:x["start_min"]),sorted(originals,key=lambda x:x["start_min"])):
                variable = {"start_min","end_min"} | ({"value_C"} if kind=="tank_setpoint" else set())
                if {k:v for k,v in row.items() if k not in variable} != {k:v for k,v in before.items() if k not in variable}:
                    errors.append("AGENT_CANNOT_CHANGE_SERVICE_TARGET_OR_HARDWARE")
                if kind == "tank_setpoint":
                    start,end = row["start_min"],row["end_min"]
                    config = contract["primary_water_heater_configuration"]
                    duration = config["pre_heat_window_end_h"]-config["pre_heat_window_start_h"]
                    if duration<=0:duration+=24
                    if end-start>60*min(8.0,duration+1.0)+1e-7:
                        errors.append("AGENT_WH_WINDOW_WOULD_BE_BOUNDED")
                    if start//1440 != (end-1)//1440:
                        errors.append("NON_EV_WATER_HEATER_OVERNIGHT_FORBIDDEN")
                    if not _finite(row.get("value_C")) or not 45<=row["value_C"]<=75:
                        errors.append("PAPER_V1_WH_TEMPERATURE_WOULD_BE_CLIPPED")
    for (asset,kind),rows in after_groups.items():
        if kind != "ac_setpoint":
            continue
        ordered=sorted(rows,key=lambda x:x["start_min"])
        clock=replay_clock(ordered,{**context,"events":context.get("events",[])})
        if clock["mismatches"]:
            errors.append("PAPER_V1_CHECKPOINT_CLOCK_CANNOT_REPRODUCE_LITERAL_PLAN")
    return sorted(set(errors))

def complete_appliance_payload(plan):
    """An accepted whole-plan payload; future-day EV is applied by dated queue."""
    actions={}
    for row in plan["tasks"]:
        actions[row["kind"]+"_start_h"]=row["start_min"]/60
        actions[row["kind"]+"_skip"]=False
    rows=[r for r in plan["controls"] if r["kind"]=="tank_setpoint" and 0<=r["start_min"]<1440]
    if rows:
        row=rows[0]
        actions.update(water_heater_preheat=True,water_heater_preheat_start_h=row["start_min"]/60,water_heater_preheat_end_h=row["end_min"]/60,water_heater_preheat_temp_c=row["value_C"])
    ev=next((r for r in plan["controls"] if r["kind"]=="ev_charge_window"),None)
    if ev:
        actions.update(ev_charge_start_h=(ev["start_min"]%1440)/60,ev_charge_end_h=24.0 if ev["end_min"]%1440==0 else (ev["end_min"]%1440)/60)
    return actions
