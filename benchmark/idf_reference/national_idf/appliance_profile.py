"""Read source-bound appliance samples on their declared nominal clock.

This supplies EB power commands and a separate resource ledger. It does not
identify room gains, service completion, standby, or behaviour at a new site.
"""
import csv
import math

from .common import ROOT, read, require
from .source_adapter import source_file


def load_profile(ref, *, device, root=ROOT):
    value = read(source_file(ref, root))
    require(value.get('schema') == 'national_idf.nominal_resource_profile.v1'
            and value.get('device') == device, 'RESOURCE_PROFILE_IDENTITY')
    require(value.get('clock') == {'kind': 'nominal_sample_index', 'sample_seconds': 1,
                                 'timestamps_reconstructed': False}, 'RESOURCE_PROFILE_CLOCK')
    require(type(value.get('water_measured')) is bool, 'RESOURCE_PROFILE_WATER_DECLARATION')
    water_unit = 'mL/s' if value['water_measured'] else None
    require(value.get('units') == {'power': 'W', 'water_inlet': water_unit, 'water_outlet': water_unit},
            'RESOURCE_PROFILE_UNITS')
    require(value.get('formal_admitted') is False and value.get('physical_service_success') is None
            and value.get('outside_cycle_power_W') is None, 'RESOURCE_PROFILE_SCOPE')
    require(value.get('evidence'), 'RESOURCE_PROFILE_EVIDENCE_MISSING')
    for evidence in value['evidence']:
        source_file(evidence, root)
    with source_file(value['samples'], root).open() as stream:
        rows = list(csv.DictReader(stream))
    require(bool(rows) and len(rows) == value['active_cycle_duration_s'], 'RESOURCE_PROFILE_DURATION')
    channels = ['power'] + (['water_inlet', 'water_outlet'] if value['water_measured'] else [])
    for row in rows:
        for channel in channels:
            try:
                number = float(row[channel])
            except (KeyError, TypeError, ValueError):
                require(False, 'RESOURCE_SAMPLE_MISSING', channel)
            require(math.isfinite(number) and number >= 0, 'RESOURCE_SAMPLE_INVALID', channel)
    return value, rows


def resource_window(profile, rows, start_s, duration_s):
    """Average known samples; never pad an EP timestep with unknown standby.

    Integral seconds follow the source's nominal 1 Hz protocol. They are not
    a reconstruction of irregular sensor timestamps or a new appliance model.
    """
    require(type(start_s) is int and type(duration_s) is int and duration_s > 0,
            'RESOURCE_WINDOW_CLOCK')
    require(0 <= start_s < start_s + duration_s <= len(rows),
            'RESOURCE_WINDOW_OUTSIDE_OBSERVED_CYCLE')
    section = rows[start_s:start_s + duration_s]
    power = math.fsum(float(r['power']) for r in section)
    water = profile['water_measured']
    return {'elapsed_s': start_s, 'duration_s': duration_s,
            'power_kw': power / duration_s / 1000,
            'electricity_kwh': power / 3_600_000,
            'inlet_L': math.fsum(float(r['water_inlet']) for r in section) / 1000 if water else None,
            'drain_L': math.fsum(float(r['water_outlet']) for r in section) / 1000 if water else None,
            'room_sensible_heat_W': None, 'room_moisture_kg_s': None,
            'physical_service_success': None}


def resource_bins(profile, rows, step_s):
    require(type(step_s) is int and step_s > 0, 'RESOURCE_BIN_CLOCK')
    return [resource_window(profile, rows, i, min(step_s, len(rows)-i))
            for i in range(0, len(rows), step_s)]
