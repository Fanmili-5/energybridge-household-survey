"""Explicit compilation of the original EB heater permission window.

The zero setpoint is an internal OFF encoding supported by the pinned binding,
not a new Agent action or a requested water temperature. The native EP tank
continues storage, losses and draws; electrical energy is never fabricated.
"""
from .common import require
MODE="paper_v1_native_permission_window.v1"

def validate(case,domain=None):
    c=case['controls'];windows=c.get('water_heater_windows_by_date')
    if windows is None:
        require('water_heater_window_encoding' not in c,'WH_WINDOW_MODE_WITHOUT_WINDOWS')
        return
    require(c.get('water_heater_window_encoding')==MODE,'WH_WINDOW_ENCODING_NOT_DECLARED')
    grid=domain['command_grid_min'] if domain else 1
    for date,rows in windows.items():
        require(len(rows)<=1,'WH_ONLY_SINGLE_DAILY_NATIVE_WINDOW')
        for row in rows:
            a,z=row['start_min'],row['end_min']
            require(0<=a<z<=1440 and z-a<=240,'WH_WINDOW_OUTSIDE_ORIGINAL_NATIVE_SUBSET')
            require(a%grid==z%grid==0,'WH_WINDOW_OUTSIDE_COMMAND_GRID')

def available(case,date,minute):
    windows=case['controls'].get('water_heater_windows_by_date')
    if windows is None or date not in windows:return True
    return any(r['start_min']<=minute<r['end_min'] for r in windows[date])

def effective_setpoint(control):
    return control['tank_target_C'] if control.get('water_heater_window_open',True) else 0.0
