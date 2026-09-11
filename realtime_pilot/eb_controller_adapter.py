"""Pinned run_family_agent control bounds/fallback, without household grading.

The upstream fallback is a closure, not an importable helper. Keep its formulas
here and verify them against the pinned function body in tests. Do not infer
numeric questionnaire preferences or import hidden persona/scoring data.
"""
from eb_execution import upstream
from copy import deepcopy
from survey_time import ac_available


def daily_plan_due(loop, sim_h, previous_sim_h, dt, sim_days):
    """Native daily trigger (family_runner:13733), after the shared P0 prefix."""
    runner,_=upstream()
    grace=max(0.25,2.0*float(dt or 0.25))
    for day in range(sim_days):
        plan_h=day*24.0+runner.DEFAULT_PLANNING_HOUR
        if day in loop.daily_plans_done:continue
        if previous_sim_h<plan_h<=sim_h or plan_h<=sim_h<=plan_h+grace:
            loop.daily_plans_done.add(day)
            return True
    return False


def apply_hvac(loop, ex, state, *, original, sim_h, agent_active):
    """Ordinary P0 prefix, then native agent occupancy/availability semantics."""
    runner,_=upstream();ac=original['devices'].get('ac',{})
    if agent_active:
        available=bool(ac.get('active')) and loop.current_occupied
        cooling=loop.sp
    else:
        available=ac_available(ac,sim_h)
        cooling=loop.sp if available else runner.AC_OFF_FALLBACK_COOLING_SETPOINT
    applied=runner._set_hvac_availability(ex,state,loop,available)
    if not applied and not available:cooling=runner.AC_OFF_FALLBACK_COOLING_SETPOINT
    ex.set_actuator_value(state,loop.h_cool,cooling)
    return available,cooling


def planning_evidence(loop, *, sim_h, observed, event, appliances, tariff):
    """Same native evidence producers; no evaluation labels or future EP data."""
    runner,_=upstream()
    from energybridge.harness.energy_tools_v3 import build_hourly_tariff_snapshot
    prices=build_hourly_tariff_snapshot([tariff['cny_per_kwh']]*24,unit='CNY/kWh')
    rollout=runner._adaptive_v3_hvac_rollout_snapshot(loop,sim_h=sim_h,hod=sim_h%24,
        temp=observed['temperature_c'],out_t=observed['outdoor_c'],facility_w=observed['facility_w'],
        vpp_event=event,appliance_config=appliances)
    demand={}
    if event is not None:
        vid=event['id']
        # Native capacity acquisition at event start, followed by the native
        # demand builder. Before that, its unquantified fallback is explicit.
        if sim_h>=event['trigger_h'] and vid not in loop.vpp_capacity_by_id:
            from energybridge.quantification import assess_suite_vpp_request
            try:
                capacity=assess_suite_vpp_request(loop.appliance_suite,sim_h,target_kw=2.0,
                    duration_minutes=(event['end_h']-event['trigger_h'])*60,
                    hvac_context=runner._capacity_hvac_context(loop,temp=observed['temperature_c'],
                        out_t=observed['outdoor_c'],facility_w=observed['facility_w']))
            except Exception as exc:
                capacity={'status':'unavailable','error_type':type(exc).__name__}
            loop.vpp_capacity_by_id[vid]=capacity
            loop.current_vpp_capacity=capacity
            loop.vpp_demand_by_id[vid]=runner._call_vpp_demand_agent(vid,
                loop.total_quantification_by_id.get(vid),household_capacity=capacity,
                observed_baseline_kw=observed['facility_w']/1000,
                duration_h=event['end_h']-event['trigger_h'])
        demand=deepcopy(loop.vpp_demand_by_id.get(vid) or runner._call_vpp_demand_agent(
            vid,loop.total_quantification_by_id.get(vid)))
    return {'tariff_snapshot':prices,'hvac_rollout':rollout,'demand_context':demand}


def control_context(loop):
    runner, _ = upstream()
    low, high, tolerance = runner._agent_observable_ac_bounds(loop)
    household=getattr(loop,"household_config",{})
    return {"usual_setpoint_c": household.get("ordinary_plan",{}).get("setpoint"),
            "reported_comfort_range": None,
            "minimum_c": max(runner.SP_MIN, low-tolerance),
            "maximum_c": min(runner.SP_MAX, high+2.0),
            "default_c": round((low+high)/2, 1),
            "protective": runner._agent_memory_is_protective(loop),
            "source": "family_runner.run_family_agent observable bounds; native defaults where onboarding range is absent"}


def native_fallback(loop, sim_h, temperature_c, event):
    # family_runner.py:11478-11489, with the observable adaptive harness context.
    context = control_context(loop)
    if event["trigger_h"] <= sim_h < event["end_h"]:
        sp = min(context["maximum_c"], context["default_c"] if context["protective"] else 26.5)
    else:
        sp = min(context["maximum_c"], max(context["minimum_c"], min(26.0, round(temperature_c-0.5, 1))))
    return {"setpoint": sp, "next_check_hour": None, "appliances": {}}
