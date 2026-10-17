"""Read written annual/case files and check daily services and real resources."""
import collections
import copy
from common import *
from power import known_power_errors


def errors(w,year):
    bad=[];assets={d['asset_id']:d for d in w['parameter_pack']['devices']};classes={k for d in assets.values()for k in d['types']}
    if year['source_world_content_sha256']!=w['world_content_sha256']:bad.append('WORLD_BINDING')
    if year['parameter_pack_sha256']!=w['parameter_pack_sha256']:bad.append('HARDWARE_BINDING')
    if year['B_price_event_answers_consulted']:bad.append('A_CONSULTED_B_OR_OUTCOME')
    days=year['days'];needs={n['need_id']:n for day in days.values()for n in day['needs']};tasks=year['tasks'];ops=year['operations']
    coverage=collections.defaultdict(set)
    def cover(kind,asset,a,b):
        for i in range((a-480)//1440,(b-1-480)//1440+1):coverage[str(ANCHOR+dt.timedelta(days=i))].add((kind,asset))
    for task in tasks:cover(task['kind'],task['asset_id'],task['start_min'],task['end_min'])
    for day in days.values():
        for control in day['controls']:
            if control['kind']=='ac_setpoint':
                cover('ac',control['asset_id'],control['start_min'],control['end_min'])
                if control['fan_operating_mode']==1:cover('ac_fan',control['asset_id'],control['start_min'],control['end_min'])
            if control['kind']=='ev_charge_window':cover('ev',control['asset_id'],control['start_min'],control['actual_charge_end_min'])
        for need in day['needs']:
            if need['kind']=='water_heater':cover('water_heater',need['asset_id'],need['release_min'],need['deadline_min'])
    taskmap=collections.defaultdict(list);opmap=collections.defaultdict(list);slots=set();rooms=set();blocks=set()
    for key,day in days.items():
        date=dt.date.fromisoformat(key);base=origin(date);activity=day['activity']
        if activity['date']!=key or day['shared']['target_activity_day_sha256']!=activity['activity_day_sha256']:bad.append('DATED_CONTEXT_BINDING')
        for minute in activity['family_context']['bath_times_min'].values():blocks.add((w['activity_contract']['room_map']['bath'],base+minute))
        for r in day['shared']['facility_reservations']:
            for minute in range(base+r['start_min'],base+r['end_min'],10):blocks.add((r['room_id'],minute))
        t=day['textiles']
        if abs(t['before_kg']+t['generated_kg']-t['washed_kg']-t['after_kg'])>3e-6 or t['after_kg']<0:bad.append('TEXTILE_MASS_BALANCE')
        if date>ANCHOR and abs(t['before_kg']-days[str(date-dt.timedelta(days=1))]['textiles']['after_kg'])>2e-6:bad.append('MIDNIGHT_INVENTORY_RESET')
        if date.year==2025:
            if any((kind,aid)not in coverage[key]for aid,d in assets.items()for kind in d['types']):bad.append('DEVICE_NOT_USED_IN_08_TO_NEXT08')
            count=collections.Counter(n['kind']for n in day['needs'])
            if count['dishwasher']!=int('dishwasher'in classes):bad.append('DAILY_DISH_SERVICE_DROPPED')
            if 'washer'in classes and count['washer']<1:bad.append('DAILY_LAUNDRY_DROPPED')
            if 'dryer'in classes and count['dryer']!=count['washer']:bad.append('DAILY_DRYER_DROPPED')
            if count['ev']!=int('ev'in classes)or('ev'in classes and activity['transport']is None):bad.append('DAILY_EV_TASK_DROPPED')
            ac_ids={d['asset_id']for d in assets.values()if'ac'in d['types']}
            if {n['asset_id']for n in day['needs']if n['kind']=='ac'}!=ac_ids:bad.append('DAILY_AC_UNIT_DROPPED')
            if any(('ac_fan',aid)not in coverage[key]for aid in ac_ids):bad.append('DAILY_AC_REAL_FAN_TASK_DROPPED')
            if count['water_heater']!=(w['N']if 'water_heater'in classes else 0):bad.append('DAILY_HOTWATER_DROPPED')
            if t['oldest_days']>7 and 'washer'in classes:bad.append('DIRTY_INVENTORY_UNSERVED')
            if any(n['kind']=='dishwasher'and n['release_min']<base+max(activity['family_context']['member_dinners_min'].values())+30 for n in day['needs']):bad.append('DISHES_BEFORE_MEAL')
    for task in tasks:
        taskmap[task['need_id']].append(task)
        if task['asset_id']not in assets or task['kind']not in assets[task['asset_id']]['types']:bad.append('ABSENT_DEVICE')
        required=120 if task['kind']=='washer'else 90
        if task['end_min']-task['start_min']!=required:bad.append('EB_PROGRAM_DURATION')
    asset_use=collections.defaultdict(list)
    for op in ops:
        opmap[op['need_id']].append(op);t=op['start_min'];date=ANCHOR+dt.timedelta(days=t//1440);day=days.get(str(date))
        if op['kind']not in('load','unload','EV_plug','EV_unplug')or op.get('given_baseline_booking'):bad.append('FAKE_HANDLING_OR_HELPER')
        if op['end_min']-t!=10:bad.append('HANDLING_DURATION')
        oid=op['operator_id'];local=t%1440
        if day is None or not any(a<=local and local+10<=b for a,b in day['activity']['operator_windows_min'].get(oid,[])):bad.append('OPERATOR_UNAVAILABLE')
        if (oid,t)in slots:bad.append('OPERATOR_DOUBLE_BOOKED')
        if (op['room_id'],t)in rooms or(op['room_id'],t)in blocks:bad.append('FACILITY_ACCESS_COLLISION')
        slots.add((oid,t));rooms.add((op['room_id'],t))
        if op['need_id']not in needs:bad.append('OPERATION_WITHOUT_SERVICE')
    for nid,n in needs.items():
        if n['kind']not in('washer','dishwasher'):continue
        group=taskmap[nid];handling={o['kind']:o for o in opmap[nid]}
        if len(group)!=1 or set(handling)!=set(('load','unload')):bad.append('BATCH_CHAIN_MISSING');continue
        task=group[0];end=task['end_min'];dry=taskmap.get(nid+':dry',[])
        if n['kind']=='washer':
            if n['quantity']>4.5+1e-6:bad.append('WASH_MASS_OVER_CAPACITY')
            if 'dryer'in classes:
                if len(dry)!=1 or dry[0]['start_min']!=end or dry[0]['asset_id']!=task['asset_id']:bad.append('WASH_DRY_DEPENDENCY')
                else:end=dry[0]['end_min']
        load=handling['load'];unload=handling['unload']
        if not n['release_min']<=load['start_min']or load['end_min']>task['start_min']or task['start_min']-load['end_min']>720:bad.append('LOAD_RELEASE_OR_TIMER')
        if unload['start_min']<end or unload['end_min']>n['deadline_min']or unload['start_min']-end>n['maximum_retrieval_wait_min']:bad.append('RETRIEVAL_OR_DEADLINE')
        asset_use[task['asset_id']].append((load['start_min'],unload['end_min']))
    for intervals in asset_use.values():
        seq=sorted(intervals)
        if any(a[1]>b[0]for a,b in zip(seq,seq[1:])):bad.append('ASSET_OCCUPIED_BY_PRIOR_BATCH')
    journeys=year['journeys'];departures={j['absolute_departure_min']:j for j in journeys}
    ac_windows=collections.defaultdict(list)
    for day in days.values():
        for c in day['controls']:
            if c['kind']=='ac_setpoint':
                if c['mode']not in('dual_thermostat',)or c['cooling_setpoint_C']-c['heating_setpoint_C']<2:bad.append('HVAC_MODE_OR_DEADBAND')
                ac_windows[c['asset_id']].append((c['start_min'],c['end_min']))
            if c['kind']!='ev_charge_window':continue
            n=needs.get(c.get('need_id'));handling={o['kind']:o for o in opmap[c.get('need_id')]}
            if n is None or n.get('departure_min')not in departures or not n.get('next_access_is_actual_trip'):bad.append('INVENTED_EV_ACCESS');continue
            if set(handling)!=set(('EV_plug','EV_unplug')):bad.append('EV_CONNECTION_CHAIN');continue
            if c['battery_energy_kWh']<=0 or c['actual_charge_end_min']>handling['EV_unplug']['start_min']:bad.append('EMPTY_OR_INFEASIBLE_CHARGE')
            if not n['release_min']<=handling['EV_plug']['start_min']or handling['EV_plug']['end_min']>c['start_min']or handling['EV_unplug']['end_min']>n['departure_min']:bad.append('EV_RETURN_DEPARTURE_ORDER')
    for windows in ac_windows.values():
        windows=sorted(windows)
        if any(a[1]>b[0]for a,b in zip(windows,windows[1:])):bad.append('OVERLAPPING_HVAC_MODES')
    ev=next((d for d in assets.values()if 'ev'in d['types']),None)
    if ev:
        capacity=ev['parameters']['capacity_kwh'];initial=year['initial_states']['EV_SOC']*capacity;events=year['EV_battery_energy_events']
        deltas=collections.defaultdict(float);instant=collections.defaultdict(float)
        for event in events:
            a,b=event['start_min'],event['end_min']
            if a==b:instant[a]+=event['battery_kWh']
            else:
                rate=event['battery_kWh']/(b-a);deltas[a]+=rate;deltas[b]-=rate
        energy=initial;rate=0.;previous=0
        for point in sorted(set(deltas)|set(instant)):
            energy+=rate*(point-previous)+instant[point];rate+=deltas[point];previous=point
            if energy<capacity*ev['parameters']['min_soc']-1e-6 or energy>capacity+1e-6:bad.append('EV_CONTINUOUS_SOC')
    bad+=known_power_errors(w,year)
    return sorted(set(bad))


def case_errors(w,case):
    bad=[];expected_ids={d['asset_id']for d in w['parameter_pack']['devices']if'ac'in d['types']}
    if set(case['HVAC_signals'])!=expected_ids:return ['HVAC_SIGNALS_MISSING']
    for aid,signals in case['HVAC_signals'].items():
        if {len(v)for v in signals.values()}!={576}:bad.append('HVAC_SIGNAL_LENGTH');continue
        controls=[c for c in case['A']['controls']if c['asset_id']==aid and c['kind']=='ac_setpoint']
        for ix in range(576):
            minute=-1440+ix*10;control=next((c for c in controls if c['start_min']<=minute<c['end_min']),None)
            expected={'available':int(control is not None),'fan_mode':control['fan_operating_mode']if control else 0,
                'heat_sp':control['heating_setpoint_C']if control else 5.,'cool_sp':control['cooling_setpoint_C']if control else 50.}
            if any(signals[k][ix]!=v for k,v in expected.items()):bad.append('HVAC_SIGNAL_NOT_PLAN')
            if signals['cool_sp'][ix]-signals['heat_sp'][ix]<2:bad.append('HVAC_SIGNAL_DEADBAND')
    return sorted(set(bad))


def negative_controls(w,year):
    tests=[]
    def test(name,change,expected):
        candidate=copy.deepcopy(year);change(candidate);bad=errors(w,candidate)
        tests.append({'control':name,'rejected':expected in bad,'actual':bad})
    def skip_daily(y):
        day=next(d for d in y['days'].values()if d['date'].startswith('2025')and any(n['kind']=='dishwasher'for n in d['needs']))
        day['needs']=[n for n in day['needs']if n['kind']!='dishwasher']
    if any('dishwasher'in d['types']for d in w['parameter_pack']['devices']):test('drop_daily_dishwasher_for_diversity',skip_daily,'DAILY_DISH_SERVICE_DROPPED')
    def skip_laundry(y):
        y['days']['2025-06-10']['needs']=[n for n in y['days']['2025-06-10']['needs']if n['kind']!='washer']
    test('drop_daily_laundry_for_diversity',skip_laundry,'DAILY_LAUNDRY_DROPPED')
    test('reset_midnight_inventory',lambda y:y['days']['2025-06-10']['textiles'].update(before_kg=999.),'TEXTILE_MASS_BALANCE')
    test('operator_during_sleep',lambda y:y['operations'][0].update(start_min=origin(dt.date(2025,6,10))+120,end_min=origin(dt.date(2025,6,10))+130),'OPERATOR_UNAVAILABLE')
    test('invent_filler_operation',lambda y:y['operations'].append({**y['operations'][0],'kind':'additional_EV_handling_request','need_id':'made_up'}),'FAKE_HANDLING_OR_HELPER')
    test('reverse_dryer_chain',lambda y:next(t for t in y['tasks']if t['kind']=='dryer').update(start_min=0),'WASH_DRY_DEPENDENCY')
    return tests


def main():
    verify_inputs();bindings=read(OUT/'A_BINDINGS10000.json');signature=rules_id()
    if bindings['rules_sha256']!=signature:raise ValueError('RULES_CHANGED_AFTER_BUILD')
    failed=[];variation=collections.Counter();cases=0;negative=[];deferred=0;maxwait=0;daily=collections.Counter()
    for index,row in enumerate(bindings['records']):
        world_path=MASTER/row['master_world_path'];yp=OUT/row['annual_A_path']
        if sha(world_path)!=row['master_world_sha256']or sha(yp)!=row['annual_A_sha256']:raise ValueError('INPUT_OUTPUT_BYTES_CHANGED')
        if sha(OUT/row['A_world_path'])!=row['A_world_sha256']or sha(OUT/row['HVAC_components_path'])!=row['HVAC_components_sha256']:raise ValueError('A_WORLD_OR_HVAC_BYTES_CHANGED')
        original=read(world_path);w=read(OUT/row['A_world_path']);year=read(yp);bad=errors(w,year)
        if any(w[k]!=original[k]for k in('household_id','N','G','H6','H7','province','role_policy','random10_date_selection','layout')):bad.append('FAMILY_HOUSING_OR_DATES_CHANGED')
        roster=lambda world:[{k:m[k]for k in('member_id','age_years','sex','ego_relation_code','employment_status','reference_home_room_id')}for m in world['members']]
        if roster(w)!=roster(original):bad.append('FAMILY_ROSTER_CHANGED')
        for package in read(OUT/row['HVAC_components_path']):
            kinds=collections.Counter(r[0]for r in package['rows'])
            if any(kinds[k]!=1 for k in('Coil:Cooling:DX:SingleSpeed','Coil:Heating:DX:SingleSpeed','Coil:Heating:Electric','Fan:OnOff','ZoneHVAC:PackagedTerminalHeatPump'))or package['ideal_heating_allowed_in_this_AC_room']:bad.append('HEATING_COMPONENTS_MISSING_OR_UNMETERED')
        if bad:failed.append({'household_id':row['household_id'],'errors':bad})
        original_dates={d['date']for d in w['random10_date_selection']['dates']}
        if {c['date']for c in row['cases']}!=original_dates or len(row['cases'])!=10:failed.append({'household_id':row['household_id'],'errors':['TEN_DATES_CHANGED']})
        for c in row['cases']:
            cp=OUT/c['path']
            if sha(cp)!=c['sha256']:raise ValueError('CASE_BYTES_CHANGED')
            case=read(cp);cases+=1
            if case['year_A_sha256']!=row['annual_A_sha256']or case['source_world_content_sha256']!=w['world_content_sha256']or case['B_generated']:failed.append({'case_id':c['case_id'],'errors':['CASE_LINEAGE']})
            signal_errors=case_errors(w,case)
            if signal_errors:failed.append({'case_id':c['case_id'],'errors':signal_errors})
            for d in case['days']:
                base=origin(dt.date.fromisoformat(c['date']))
                for name in('activity','shared','weather','textiles'):
                    if d[name]!=year['days'][d['date']][name]:failed.append({'case_id':c['case_id'],'errors':['CASE_CONTEXT_MIXED']})
            daily.update(n['kind']for n in year['days'][c['date']]['needs'])
        variation[row['unique_substantive_days']]+=1;deferred+=row['deferred_laundry_count'];maxwait=max(maxwait,row['max_dirty_wait_days'])
        if not negative and all(any(k in d['types']for d in w['parameter_pack']['devices'])for k in('dishwasher','dryer')):negative=negative_controls(w,year)
        if(index+1)%100==0:print({'households_read_back':index+1,'failures':len(failed)},flush=True)
    master_ids={r['household_id']for r in read(MASTER/'SUBSET50.json')['records']};subset=read(OUT/'SUBSET50.json')
    lookup={r['household_id']:r for r in bindings['records']}
    subset_ok=master_ids=={r['household_id']for r in subset['records']}and all(r==lookup[r['household_id']]for r in subset['records'])
    if not subset_ok:failed.append({'errors':['SUBSET_NOT_SAME_MASTER']})
    passed=not failed and cases==10000 and len(bindings['records'])==1000 and all(t['rejected']for t in negative)
    report={'schema':'eb.normal_A_acceptance.v46','accepted':passed,'households_checked':len(bindings['records']),'cases_checked':cases,
            'failures':failed,'rules_sha256':signature,'bindings_sha256':sha(OUT/'A_BINDINGS10000.json'),
            'daily_service_counts_in10000_dates':dict(daily),'household_unique_substantive_days':dict(variation),
            'variation_excludes_ID_date_and_minute_jitter':True,'daily_services_retained':True,'every_device_used_in08_to_next08_checked':True,'subset50_same_master':subset_ok,
            'subset50_type_counts':subset['type_counts'],'negative_controls':negative,'deferred_laundry_attempts_retained':deferred,
            'maximum_dirty_wait_days_including_tail':maxwait,'EP_started':0,'new_B_generated':False,'thermal_delivery_validated':False,'live_questionnaire_replaced':False}
    save(OUT/'ACCEPTANCE.json',report);print(canonical(report))
    if not passed:raise SystemExit(2)

if __name__=='__main__':main()
