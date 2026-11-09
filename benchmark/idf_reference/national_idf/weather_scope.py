"""Derive component operating temperatures from frozen run windows.

A full EPW remains intact for soil initialization and the published inlet
correlation. It is not silently reduced to the component's allowed dates.
Only explicitly reviewed window configurations can use this alternative to
annual equipment coverage; all other configurations retain the annual gate.
"""
import csv
import datetime as dt

from .common import ROOT,locked,read,require


def window_ranges(epw,windows):
    with epw.open(newline='') as stream:rows=list(csv.reader(stream))[8:]
    by_day={}
    for r in rows:by_day.setdefault((int(r[1]),int(r[2])),[]).append(float(r[6]))
    result=[]
    for window in windows:
        begin,end=(dt.date.fromisoformat(window[k]) for k in ('start_date','end_date'))
        require(begin<=end and (end-begin).days==6,'WEATHER_SCOPE_EXPECTED_VALIDATED_WEEK')
        # Include the preceding interpolation hour conservatively, and the
        # complete 14-day recovery experiment, not just the approved 7 days.
        days=[begin+dt.timedelta(days=i) for i in range(-1,14)]
        values=[v for day in days for v in by_day.get((day.month,day.day),[])]
        require(len(values)==15*24,'WEATHER_SCOPE_EPWHOURS_MISSING')
        result.append({'start_date':begin.isoformat(),'end_date':end.isoformat(),
            'audited_start':days[0].isoformat(),'audited_end':days[-1].isoformat(),
            'min_C':min(values),'max_C':max(values)})
    require(result,'WEATHER_SCOPE_NO_WINDOWS')
    return result


def assess(record,*,root=ROOT):
    ref=record['weather'].get('operating_scope')
    require(ref is not None,'WEATHER_SCOPE_MISSING')
    scope=read(locked(ref,root));domain=read(locked(record['runtime_support_domain'],root))
    require(scope['schema']=='national_idf.reviewed_weather_window_scope.v1'
        and scope['configuration_id']==record['id']
        and scope['weather']==record['weather']['epw']
        and scope['runtime_support_domain']==record['runtime_support_domain'],'WEATHER_SCOPE_NOT_BOUND')
    init=domain.get('initialization',{})
    require(init.get('mode')=='reviewed_run_windows' and init.get('state_restore_supported') is False,
            'WEATHER_SCOPE_REQUIRES_FIXED_INITIALIZATION')
    windows=[{k:w[k] for k in ('start_date','end_date')} for w in init['approved_run_windows']]
    require(windows==scope['windows'],'WEATHER_SCOPE_WINDOW_SUBSTITUTION')
    require(scope['annual_design_service_claimed'] is False
        and scope['annual_EPWHVAC_operation_claimed'] is False,'WEATHER_SCOPE_CANNOT_APPROVE_ANNUAL_SERVICE')
    source=locked(scope['weather_manager_source'],root).read_text()
    receipt=read(locked(scope['weather_manager_receipt'],root))
    require('/v25.2.0/' in receipt['url'] and receipt['sha256']==scope['weather_manager_source']['sha256']
        and 'ReadWeatherForDay(state, 1, state.dataWeather->Envrn, false); // Read first day' in source
        and 'if ((!state.dataGlobal->WarmupFlag)' in source,'WEATHER_SCOPE_WARMUP_METHOD_NOT_PINNED')
    actual=window_ranges(locked(record['weather']['epw'],root),windows)
    require(actual==scope['derived_temperature_ranges'],'WEATHER_SCOPE_TEMPERATURES_CHANGED')
    basis=read(locked(scope['physical_review'],root))
    require(basis['accepted_seasons']==scope['accepted_seasons'] and not basis['unaccounted_objects'],
            'WEATHER_SCOPE_PHYSICAL_REVIEW_NOT_MATCHED')
    numerical=read(locked(scope['numerical_result'],root))
    require(numerical['protocol']['sha256']==record['numerical_protocol_sha256'],'WEATHER_SCOPE_NUMERICAL_PROTOCOL_CHANGED')
    plan=read(locked(numerical['source_plan'],root))
    evidence_windows=[]
    for season in scope['accepted_seasons']:
        require(all(v['passed'] for v in numerical['comparisons'][season].values()),'WEATHER_SCOPE_NUMERICS_FAILED')
        fixture=read(locked(plan['sources'][season]['fixture'],root))
        require(fixture['weather']==record['weather']['epw'],'WEATHER_SCOPE_VALIDATION_SITE_CHANGED')
        source_domain=read(locked(fixture['input_domain'],root))
        evidence_windows.append(source_domain['run_period'])
    require(evidence_windows==windows,'WEATHER_SCOPE_WINDOWS_NOT_ACTUALLY_VALIDATED')
    limits=record['equipment']['air_conditioner']['dry_bulb_domain_C']
    require(all(limits[0]<=r['min_C']<=r['max_C']<=limits[1] for r in actual),'WEATHER_SCOPE_OUTSIDE_AC_DOMAIN')
    return {'ranges':actual,'full_EPW_unmodified':True,'annual_service_approved':False,
        'source_algorithm_warmup_weather':'first environment day is repeated; preceding interpolation day and 14-day verification envelope also checked'}
