"""Join published design days to frozen reference weather at printed precision."""
from decimal import Decimal, ROUND_HALF_UP
import re

from .common import ROOT, require
from .idf import parse, objects
from .source_adapter import source_file


def same_printed_coordinate(a, b):
    first, second = Decimal(a), Decimal(b)
    quantum = Decimal(1).scaleb(max(first.as_tuple().exponent, second.as_tuple().exponent))
    return first.quantize(quantum, rounding=ROUND_HALF_UP) == second.quantize(quantum, rounding=ROUND_HALF_UP)


def design_pair(ddy_ref, weather_ref, fields, *, root=ROOT):
    text = source_file(ddy_ref, root).read_text()
    with source_file(weather_ref, root).open() as stream:
        header = stream.readline().strip().split(',')
    require(header[0] == 'LOCATION' and re.search(r'\bWMO=' + re.escape(header[5]) + r'\b', text), 'DESIGN_WMO_CONFLICT')
    rows = parse(text); locations = objects(rows, 'Site:Location')
    require(len(locations) == 1, 'DESIGN_LOCATION_CARDINALITY'); location = locations[0]
    require(all(same_printed_coordinate(a, b) for a, b in zip(location[2:6], header[6:10])),
            'DESIGN_LOCATION_PRINTED_PRECISION_CONFLICT')
    rules = {'heating_99_6': 'Ann Htg 99.6% Condns DB', 'cooling_DB_0_4': 'Ann Clg .4% Condns DB=>MWB',
             'cooling_WB_0_4': 'Ann Clg .4% Condns WB=>MDB'}
    selected = {}
    for role, suffix in rules.items():
        found = [r for r in objects(rows, 'SizingPeriod:DesignDay') if r[1].endswith(suffix)]
        require(len(found) == 1, 'DESIGN_CONDITION_NOT_UNIQUE', [role, len(found)])
        row = found[0]
        require(not any(fields.get(row, key) for key in ('dry_bulb_temperature_range_modifier_day_schedule_name',
            'humidity_condition_day_schedule_name', 'beam_solar_day_schedule_name', 'diffuse_solar_day_schedule_name')),
            'DESIGN_EXTERNAL_SCHEDULE_REQUIRED')
        require(fields.get(row, 'day_type') == ('WinterDesignDay' if role.startswith('heating') else 'SummerDesignDay'), 'DESIGN_DAY_TYPE_CONFLICT')
        selected[role] = row
    return location, selected, {'ddy': ddy_ref, 'annual_weather_identity_only': weather_ref, 'wmo': header[5],
        'selected_names': {k: r[1] for k, r in selected.items()},
        'geography_compared_at_common_published_decimal_precision': True,
        'design_vintage_independent_from_annual_TMY_vintage': True, 'annual_weather_used_for_design_simulation': False,
        'formal_admitted': False}
