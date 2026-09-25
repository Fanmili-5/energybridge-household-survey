"""Per-room EnergyPlus setpoint schedules for one DeST household."""
from __future__ import annotations


def append_controls(rows: list[list[str]], zones: list[str], *,
                    default_cooling_c: float = 28.0,
                    pair_treatment_c: float | None = None) -> dict:
    if not 18 <= default_cooling_c <= 40:
        raise ValueError("cooling setpoint outside engineering range")
    if pair_treatment_c is not None and not 18 <= pair_treatment_c <= 40:
        raise ValueError("paired setpoint outside engineering range")
    if len(zones) != len(set(zones)):
        raise ValueError("duplicate household zone")
    originals = {r[1]: r for r in rows if r[0].lower() == "thermostatsetpoint:dualsetpoint"}
    thermostat = {r[2]: r for r in rows if r[0].lower() == "zonecontrol:thermostat"}
    modified = []
    schedules = []
    for index, zone in enumerate(zones, 1):
        control = thermostat.get(zone)
        if control is None or control[5] not in originals:
            raise ValueError(f"zone thermostat/dual setpoint missing: {zone}")
        old = originals[control[5]]
        schedule = f"EB_Cooling_{index}"
        dual_name = f"EB_Dual_{index}"
        if pair_treatment_c is None:
            row = ["Schedule:Compact", schedule, "Any Number", "Through: 12/31",
                   "For: AllDays", "Until: 24:00", f"{default_cooling_c:g}"]
        else:
            row = ["Schedule:Compact", schedule, "Any Number",
                   "Through: 7/14", "For: AllDays", "Until: 24:00", f"{default_cooling_c:g}",
                   "Through: 7/15", "For: AllDays", "Until: 18:00", f"{default_cooling_c:g}",
                   "Until: 20:00", f"{pair_treatment_c:g}",
                   "Until: 24:00", f"{default_cooling_c:g}",
                   "Through: 12/31", "For: AllDays", "Until: 24:00", f"{default_cooling_c:g}"]
        rows.append(row)
        rows.append(["ThermostatSetpoint:DualSetpoint", dual_name, old[2], schedule])
        control[5] = dual_name
        rows.append(["Output:Variable", zone, "Zone Thermostat Cooling Setpoint Temperature", "Hourly"])
        modified.append(zone)
        schedules.append({"zone": zone, "cooling_schedule": schedule,
                          "energyplus_api_actuator": ["Schedule:Compact", "Schedule Value", schedule]})
    if pair_treatment_c is not None:
        periods = [r for r in rows if r[0].lower() == "runperiod"]
        if len(periods) != 1:
            raise ValueError("one source RunPeriod required")
        periods[0][2:7] = ["7", "14", "", "7", "15"]
    if not any(r[0].lower() == "timestep" for r in rows):
        rows.append(["Timestep", "6"])
    return {"selected_zone_count": len(modified), "selected_zones": modified,
            "zone_control_schedules": schedules, "default_cooling_setpoint_c": default_cooling_c,
            "pair_treatment_setpoint_c": pair_treatment_c,
            "evidence_identity": "experimental_control_interface"}
