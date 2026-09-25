"""Transparent COP conversion of DeST IdealLoads into metered AC electricity.

The meter is an experimental energy accounting proxy, not an equipment model.
It follows the thermal control response from the same selected zones and does
not imply a sourced appliance COP or installed AC capacity.
"""
from __future__ import annotations


def append_ac_proxy(rows: list[list[str]], zones: list[str], cop: float = 3.0) -> dict:
    if not 1.5 <= cop <= 5.0:
        raise ValueError("COP outside explicit sensitivity range [1.5, 5]")
    if len(zones) != len(set(zones)):
        raise ValueError("selected AC zones must be unique")
    systems = {r[1] for r in rows if r[0].lower() == "zonehvac:idealloadsairsystem"}
    if any(z + " Ideal Loads" not in systems for z in zones):
        raise ValueError("selected zone lacks converted IdealLoads system")
    rows.append(["EnergyManagementSystem:ProgramCallingManager", "EB_AC_Proxy_Calling",
                 "EndOfSystemTimestepAfterHVACReporting", "EB_AC_Proxy_Program"])
    instructions = ["SET EB_AC_Total_J = 0"]
    for index, zone in enumerate(zones, 1):
        sensor = f"EB_AC_Cool_{index}"
        energy = f"EB_AC_Elec_{index}"
        rows.append(["EnergyManagementSystem:Sensor", sensor,
                     zone + " Ideal Loads", "Zone Ideal Loads Supply Air Total Cooling Energy"])
        instructions.append(f"SET {energy} = {sensor} / {cop:.9f}")
        instructions.append(f"SET EB_AC_Total_J = EB_AC_Total_J + {energy}")
        rows.append(["EnergyManagementSystem:MeteredOutputVariable",
                     f"EB Selected Zone {index} AC Proxy Electricity Energy", energy,
                     "SystemTimestep", "EB_AC_Proxy_Program", "Electricity", "HVAC",
                     "Cooling", "Experimental IdealLoads COP Proxy", "J"])
        rows.append(["Output:Variable", "*",
                     f"EB Selected Zone {index} AC Proxy Electricity Energy", "Hourly"])
    rows.append(["EnergyManagementSystem:Program", "EB_AC_Proxy_Program", *instructions])
    if not zones:
        rows.append(["EnergyManagementSystem:MeteredOutputVariable",
                     "EB Household Zero AC Proxy Electricity Energy", "EB_AC_Total_J",
                     "SystemTimestep", "EB_AC_Proxy_Program", "Electricity", "HVAC",
                     "Cooling", "Experimental IdealLoads COP Proxy", "J"])
    rows.append(["EnergyManagementSystem:OutputVariable", "EB Selected Household AC Proxy Electricity Energy",
                 "EB_AC_Total_J", "Summed", "SystemTimestep", "EB_AC_Proxy_Program", "J"])
    rows.append(["Output:Variable", "*", "EB Selected Household AC Proxy Electricity Energy", "Hourly"])
    rows.append(["Output:Meter", "Cooling:Electricity", "Hourly"])
    return {"method": "EnergyPlus_EMS_each_zone_IdealLoads_total_cooling_J_divided_by_fixed_experimental_COP",
            "cop": cop, "selected_zones": zones,
            "meter_name": "Cooling:Electricity",
            "measured_equipment_electricity": False,
            "evidence_identity": "derived_experimental",
            "sensitivity_cop_range": [1.5, 5.0]}
