#!/usr/bin/env python3
"""C-owned pure IDF adapter for D's assigned household AC zones."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from build_buildings import parse_idf, render
from ac_proxy import append_ac_proxy


def operational_body(building: dict, assignment: dict) -> str:
    """Return an IDF with only assigned AC zones metered and all others off.

    Source background zones remain present for thermal boundaries. Facility
    electricity is not a household observation. D should use the EB meter.
    """
    if building['role_id'] != assignment['role_id'] or building['idf_sha256'] != assignment['building_idf_sha256']:
        raise ValueError('role or C IDF hash mismatch')
    idf = Path(building['idf_path'])
    if sha256(idf.read_bytes()).hexdigest() != building['idf_sha256']:
        raise ValueError('base C IDF changed')
    selected = assignment['assigned_zone_names']
    candidates = building['ac_controllable_zones']
    if len(selected) != len(set(selected)) or not set(selected) <= set(candidates):
        raise ValueError('AC assignment is not unique and household-owned')
    rows = parse_idf(idf.read_text())
    original_ems = [r for r in rows if r[0].lower().startswith('energymanagementsystem:')]
    if not original_ems or any(not (r[1].startswith('EB_AC_') or r[1].startswith('EB Selected ') or
                                r[1] == 'EB Selected Household AC Proxy Electricity Energy') for r in original_ems):
        raise ValueError('unexpected EMS object; refuse to remove unrelated device logic')
    rows = [r for r in rows if not r[0].lower().startswith('energymanagementsystem:')]
    rows = [r for r in rows if not (r[0].lower() == 'output:meter' and r[1] == 'Cooling:Electricity')]
    rows = [r for r in rows if not (r[0].lower() == 'output:variable' and
            (r[2].startswith('EB Selected Zone ') or r[2] == 'EB Selected Household AC Proxy Electricity Energy'))]
    schedule_by_name = {r[1]: r for r in rows if r[0].lower() == 'schedule:compact'}
    ideal_by_name = {r[1]: r for r in rows if r[0].lower() == 'zonehvac:idealloadsairsystem'}
    if len(selected) < len(candidates):
        if 'EB_AC_Off' in schedule_by_name:
            raise ValueError('reserved C off-schedule already exists')
        rows.append(['Schedule:Compact', 'EB_AC_Off', 'Any Number',
                     'Through: 12/31', 'For: AllDays', 'Until: 24:00', '0'])
    for index, zone in enumerate(candidates, 1):
        name = f'EB_Cooling_{index}'
        if name not in schedule_by_name:
            raise ValueError('missing C cooling schedule: ' + zone)
        setpoint = 28 if zone in selected else 40
        schedule_by_name[name][:] = ['Schedule:Compact', name, 'Any Number',
                                     'Through: 12/31', 'For: AllDays', 'Until: 24:00', str(setpoint)]
        if zone not in selected:
            ideal_by_name[zone + ' Ideal Loads'][2] = 'EB_AC_Off'
    append_ac_proxy(rows, selected)
    return render(rows, (f'! Experimental operational AC variant {building["role_id"]}; '
                         f'{len(selected)} D assigned zones; source C SHA-256 {building["idf_sha256"]}.'))
