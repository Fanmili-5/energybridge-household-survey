"""Read-only native RH bounds over the exact compiled RunPeriod.

EnergyPlus 24.1 checks initial-day RH as Severe, but later out-of-range
values only increment a counter. Check the source throughout the supplied
history/main/recovery instead. This is not empirical weather validation.
"""
import csv
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from benchmark.ab_generation.common import sha
from benchmark.housing_simulation.kernel.core_tools import parse_idf


@lru_cache(maxsize=64)
def _invalid_rh(path, expected_hash):
    path=Path(path)
    if sha(path)!=expected_hash:raise ValueError('WEATHER_INPUT_HASH_MISMATCH')
    bad=[]
    for line,row in enumerate(csv.reader(path.read_text().splitlines()[8:]),9):
        if not row:continue
        value=float(row[8])
        # Match native WeatherManager.cc 24.1: >110 is out of range;
        # >=999 denotes missing, which the engine handles separately.
        if value<0 or 110<value<999:
            bad.append((int(row[1]),int(row[2]),int(row[3]),line,value))
    return tuple(bad)


def native_weather_review(weather, expected_hash, idf):
    periods=[r for r in parse_idf(idf)if r[0].lower()=='runperiod']
    if len(periods)!=1:raise ValueError('EXACT_SINGLE_COMPILED_RUNPERIOD_REQUIRED')
    r=periods[0]
    start=date(int(r[4]),int(r[2]),int(r[3]));end=date(int(r[7]),int(r[5]),int(r[6]))
    if not 0<=(end-start).days<=400:raise ValueError('UNSUPPORTED_WEATHER_REVIEW_SPAN')
    days=set();day=start
    while day<=end:
        days.add((day.month,day.day));day+=timedelta(days=1)
    bad=[{'month':m,'day':d,'hour_end':h,'source_line':line,'RH_percent':value}
         for m,d,h,line,value in _invalid_rh(str(Path(weather).resolve()),expected_hash)if(m,d)in days]
    return {'passed':not bad,'weather_sha256':expected_hash,'run_start':start.isoformat(),
            'run_end':end.isoformat(),'failures':['native_RH_input_out_of_range']if bad else[],
            'invalid_RH_records':bad,'source_modified':False,
            'scope':'native_RH_bounds_all_supplied_history_primary_recovery;not_full_weather_quality_or_empirical_validation',
            'threshold':'RH<0 or110<RH<999;native_24.1_tolerance_and_missing_sentinel'}
