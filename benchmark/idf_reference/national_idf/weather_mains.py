"""Freeze the existing EB/EnergyPlus inlet model to a pinned weather file.

These are modelled supply temperatures, not measurements of a city's network.
Only the dry-bulb series is used; solar QC has its own admission decision.
"""
import calendar
import datetime as dt
import math

from .common import ROOT, read, require
from .source_adapter import source_file
from .weather import audit


def derive(epw_ref, *, root=ROOT):
    report = audit(source_file(epw_ref, root))
    # The inlet model requires the full, regular dry-bulb year. It does not
    # assert that the other fields or a dwelling/weather pairing are approved.
    require(report['hours'] in (8760, 8784)
            and not any(key in report['errors'] for key in ('hour_count', 'time_axis', 'unparseable_row', 'dry_bulb_C')),
            'MAINS_WEATHER_DRY_BULB_NOT_COMPLETE')
    means = report['daily_mean_dry_C']
    year = 2000 if report['leap'] else 2001
    require(len(means) == 365 + int(report['leap']), 'MAINS_WEATHER_DAILY_COVERAGE')
    monthly = []
    for month in range(1, 13):
        monthly.append(sum(means[f'{month:02}-{day:02}'] for day in range(1, calendar.monthrange(year, month)[1]+1))
                       / calendar.monthrange(year, month)[1])
    annual = sum(means.values()) / len(means)
    spread = max(monthly)-min(monthly)
    return {'schema': 'national_idf.weather_derived_mains.v1', 'weather': epw_ref,
        'identity': report['identity'], 'annual_mean_dry_bulb_C': annual,
        'max_difference_monthly_mean_dry_bulb_C': spread, 'monthly_mean_dry_bulb_C': monthly,
        'idf_object': ['Site:WaterMainsTemperature', 'Correlation', '', format(annual, '.17g'),
                       format(spread, '.17g'), '1', '0'],
        'model': 'Unmodified EnergyPlus25.2 Christensen/Burch correlation already used by EB',
        'modelled_not_measured': True, 'local_distribution_calibration': None,
        'empirical_adjustment_fitted': False, 'whole_weather_QC_or_housing_admission_granted': False,
        'dry_bulb_only_input_checked': True, 'formal_admitted': False}


def daily_temperature(annual_C, monthly_spread_C, latitude, day):
    """Independent expression of the pinned official 25.2 source equation."""
    require(1 <= day <= 366 and monthly_spread_C >= 0, 'MAINS_CORRELATION_INPUT')
    average_F, spread_F = annual_C * 1.8 + 32, monthly_spread_C * 1.8
    ratio, lag = .4 + .01 * (average_F-44), 35 - (average_F-44)
    value_F = average_F + 6 + ratio * spread_F / 2 * (1 if latitude >= 0 else -1) * math.sin(
        math.radians(.986 * (day - 15 - lag) - 90))
    return (max(value_F, 32)-32) * 5 / 9


def apply(rows, ref, *, root=ROOT):
    import copy
    value = read(source_file(ref, root))
    calculated = derive(value['weather'], root=root)
    require(all(value[key] == calculated[key] for key in calculated), 'MAINS_BOUNDARY_DERIVATION_CHANGED')
    result = copy.deepcopy(rows)
    old = [r for r in result if r[0] == 'Site:WaterMainsTemperature']
    require(len(old) <= 1, 'MULTIPLE_WATER_MAINS_MODELS')
    if old:
        index = result.index(old[0]); before = old[0][:]; result[index] = value['idf_object'][:]
    else:
        before = None; result.append(value['idf_object'][:])
    return result, {'boundary': ref, 'before': before, 'after': value['idf_object'],
        'basis': 'Weather-derived inputs to unchanged existing EB/EnergyPlus inlet algorithm',
        'modelled_not_measured': True, 'formal_admitted': False}
