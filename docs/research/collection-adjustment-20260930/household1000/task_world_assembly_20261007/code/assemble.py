"""Compile source anchors and explicit EB-domain design into concrete worlds.

No persona attitudes, latent scores or generated human answers are imported.
Historical source reports remain distinct from this reference installation.
"""
import collections, copy, datetime as dt
from common import *
from geometry import doors,fitted,reach
NAMES={'ac':'空调','washer':'洗衣机','dishwasher':'洗碗机','dryer':'烘干机','water_heater':'电热水器','ev':'家庭EV充电'}
DEFAULTS_PATH=UP/'energybridge/roleplay/personas/all_appliances_full.json'
DEFAULTS=read(DEFAULTS_PATH)['appliances']
START=dt.date(2025,7,1)

def activities(member,hid):
    """Finite weekday/weekend activity grammar; frequencies are design, not NBS probabilities."""
    age=member['age_years'];proxy=member['current_work_source_proxy'];seed=rank(hid,member['member_id'])
    if age<6: role='preschool_with_given_daycare'
    elif age<18: role='school'
    elif proxy==1: role='home_worker' if seed%4==0 else 'commuter'
    elif proxy in [2,3]: role='home_activity'
    else: role=['commuter','home_worker','home_activity'][seed%3]
    days=[]
    for weekday in range(7):
        away=role in ['school','commuter','preschool_with_given_daycare'] and weekday<5
        a,b=(7.5,18.5) if role=='commuter' else (8.,16.5)
        intervals=[{'start_h':0.,'end_h':6.5,'activity':'sleep_rest','location':'home'},
                   {'start_h':6.5,'end_h':a if away else 8.,'activity':'personal_and_breakfast','location':'home'}]
        if away:
            intervals.extend([{'start_h':a,'end_h':a+.5,'activity':'travel','location':'outside'},
                              {'start_h':a+.5,'end_h':12.,'activity':'school' if role!='commuter' else 'work','location':'outside'},
                              {'start_h':12.,'end_h':13.,'activity':'meal_and_rest','location':'outside'},
                              {'start_h':13.,'end_h':b-.5,'activity':'school' if role!='commuter' else 'work','location':'outside'},
                              {'start_h':b-.5,'end_h':b,'activity':'travel','location':'outside'},
                              {'start_h':b,'end_h':19.,'activity':'home_activity','location':'home'}])
        else:
            intervals.extend([{'start_h':8.,'end_h':12.,'activity':'home_work' if role=='home_worker' and weekday<5 else 'home_activity','location':'home'},
                              {'start_h':12.,'end_h':13.,'activity':'meal_and_rest','location':'home'},
                              {'start_h':13.,'end_h':17.,'activity':'home_work' if role=='home_worker' and weekday<5 else 'home_activity','location':'home'},
                              {'start_h':17.,'end_h':19.,'activity':'household_activity','location':'home'}])
        intervals.extend([{'start_h':19.,'end_h':19.5,'activity':'dinner','location':'home'},
                          {'start_h':19.5,'end_h':22.5,'activity':'household_services_and_free_time','location':'home'},
                          {'start_h':22.5,'end_h':24.,'activity':'sleep_rest','location':'home'}])
        assert intervals[0]['start_h']==0 and intervals[-1]['end_h']==24
        assert all(x['end_h']==y['start_h'] for x,y in zip(intervals,intervals[1:]))
        days.append({'weekday':weekday,'intervals':intervals})
    return {'reference_activity_role':role,'employment_proxy':proxy,'employment_proxy_is_observed_for_synthetic_role':False,
            'activity_role_assignment':'age eligibility + source employment proxy where available + explicitly designed fallback',
            'weekly_calendar':days,'exact_times_are_design_not_individual_diary':True,
            'preschool_care':'given external daycare service;not additional resident' if age<6 else 'not_applicable'}

def fit_rect(room,w=.6,d=.6,obstacles=()):
    """Deterministic in-room nonoverlap witness; operator reach is checked separately."""
    from shapely.geometry import box
    x0,y0,x1,y1=room['usable_rect_m'];gap=.03
    for ax,ay in [(0,0),(1,0),(0,1),(1,1),(.5,0),(.5,1),(0,.5),(1,.5)]:
        x=x0+gap+ax*(x1-x0-w-2*gap);y=y0+gap+ay*(y1-y0-d-2*gap);rect=[x,y,x+w,y+d]
        if not box(x0,y0,x1,y1).covers(box(*rect)):continue
        if any(box(*rect).intersection(box(*r)).area>1e-8 for r in obstacles):continue
        return rect
    return None

def world(profile,prior,source,record):
    hid=profile['slot_id'];f=profile['family'];layout=copy.deepcopy(source['world']);facets=layout['stock_reference_features'];rooms=layout['rooms']
    target=[r for r in rooms if hid in r['using_household_ids']];sleep={b['member_id']:b['room_id'] for b in layout['sleep_reference']['berths']}
    members=[]
    for m in f['members']:
        members.append({**copy.deepcopy(m),'local_id':'m'+str(len(members)+1).zfill(2),'reference_home_room_id':sleep[m['member_id']],**activities(m,hid)})
    adults=[m for m in members if m['age_years']>=18];operator=adults[0]['member_id'] if adults else None
    historical=prior['auxiliary_reported_assets'];classes={a['class'] for a in historical}
    water=facets['piped_water']=='present';bath=facets['bathing_hot_water']=='self_installed_heater'
    kitchens=[r for r in target if r['census_room_class']=='kitchen'];services=[r for r in target if r['census_room_class'] in ['non_H7_service','kitchen'] or 'niche' in r['room_id']]
    beds=collections.defaultdict(list)
    for b in layout['sleep_reference']['frames']:beds[b['room_id']].append(b['outer_rect_m'])
    installed=[];placements={};sites={};dd=doors(V10/record['service_IDF_path']);factor=rank(hid,'modern_hardware_factor')%8
    desired={'washer':bool({'washer','washer_dryer_combo_report'}&classes),
             'ac':bool({'split_AC','household_central_AC','building_central_AC'}&classes),
             'water_heater':any(a['class']=='water_heater' and a['fuel_code']==1 for a in historical),
             'dryer':bool({'dryer','washer_dryer_combo_report'}&classes) or bool(factor&1),
             'dishwasher':bool(factor&2),'ev':bool(factor&4)}
    assets={}
    for kind in NAMES:
        cfg=copy.deepcopy(DEFAULTS[kind]);ok=desired[kind] and bool(adults);reason='configured_reference' if ok else 'reference_variant_unconfigured_or_no_adult_operator'
        room=None;rect=None;fit=None
        if kind in ['washer','dishwasher','water_heater'] and not water:ok=False;reason='reference_piped_water_absent;external_service'
        if kind=='water_heater' and not bath:ok=False;reason='central_or_external_hot_water_service'
        if kind=='dishwasher' and not kitchens:ok=False;reason='no_in_unit_kitchen'
        if kind=='dryer' and not assets.get('washer',{}).get('present'):ok=False;reason='no_reference_wash_load_for_dryer'
        if kind in ['washer','dishwasher'] and ok:
            options=kitchens if kind=='dishwasher' else services
            for r in options:
                if r['room_id'] not in dd:continue
                fit=fitted(r,dd[r['room_id']],kind,beds[r['room_id']]+placements.get(r['room_id'],[]),sites.get(r['room_id'],[]))
                if fit:rect=fit['body_rect_m'] if 'body_rect_m' in fit else fit['footprint_rect_m'];room=r['room_id'];break
            if not rect:ok=False;reason='no_geometry_witness;external_service'
            else:
                placements.setdefault(room,[]).append(fit['operation_envelope_rect_m']);sites.setdefault(room,[]).append(fit['reachable_operator_center_m'])
        elif kind=='dryer' and ok:
            room=assets['washer']['room_id'];rect=assets['washer']['installation']['footprint_m'];reason='reference_stacked_dryer_with_shared_floor_footprint'
        elif kind=='water_heater' and ok:
            room=next((r['room_id'] for r in services if 'wash' in r['room_id']),services[0]['room_id'] if services else None)
            if room is None:ok=False;reason='no_service_room;external_hot_water'
        elif kind=='ac' and ok:room=sleep[operator]
        elif kind=='ev' and ok:
            driver=next((m for m in adults if m['reference_activity_role']=='commuter' and 18<=m['age_years']<=70),None)
            if not driver:ok=False;reason='no_assigned_reference_commuting_driver'
            else:operator_ev=driver['member_id'];room='external_dedicated_reference_charging_bay'
        cfg['present']=bool(ok)
        if kind in ['washer','dishwasher','dryer']:
            cfg.update({'earliest_h':18.5 if kind=='washer' else 19.5 if kind=='dishwasher' else 20.5,
                        'preferred_h':18.5 if kind=='washer' else 20. if kind=='dishwasher' else 20.5,
                        'latest_h':23.5 if kind!='dryer' else 24.,'shiftable':True,'dr_adjustable':True})
        if kind=='water_heater':cfg.update({'bath_required_h':20.5,'pre_heat_window_start_h':17.,'pre_heat_window_end_h':21.,'reference_allowed_preheat_start_h':15.})
        if kind=='ev':cfg.update({'initial_soc':cfg['target_soc'],'efficiency':.92})
        install={'installation_scope':'declared_reference_design_not_source_observation','footprint_m':rect,'height_design_m':.84 if kind in ['washer','dishwasher'] else 1.68 if kind=='dryer' else 2.0 if kind=='water_heater' else None,
                 'stacking_and_wall_support_are_reference_assumptions_not_asbuilt_certification':kind in ['dryer','water_heater']}
        if fit:install['door_access_witness']=fit
        asset={'id':hid+':'+kind+':1','kind':kind,'label':NAMES[kind],'present':bool(ok),'reference_choice_reason':reason,
               'room_id':room if ok else None,'config':cfg,'operator_member_id':(operator_ev if kind=='ev' and ok else operator) if ok else None,
               'permission':'proposal_requires_actor_judgment;hypothetical_execution_allowed_for_physics' if ok else 'not_applicable',
               'preprogrammed_start_available_reference':bool(ok),'meter_bucket':'target_household_reference' if ok else 'not_applicable',
               'installation':install,'source_equipment_defaults_sha256':sha(DEFAULTS_PATH),
               'historical_report_reference_ids':[a['report_reference_id'] for a in historical if (a['class']==kind or kind=='ac' and 'AC' in a['class'] or kind=='washer' and a['class']=='washer_dryer_combo_report')],
               'physical_model_source':'pinned EB program;AC DX andWH thermal bindings added by compiler',
               'future_human_response':None}
        assets[kind]=asset
    weekly_tasks=[]
    for weekday in range(7):
        jobs=[]
        wash_day=weekday in [0,2,5]
        for kind in ['washer','dishwasher','dryer']:
            a=assets[kind]
            if not a['present'] or kind in ['washer','dryer'] and not wash_day:continue
            c=a['config'];jobs.append({'id':kind+'_weekday'+str(weekday),'device_id':a['id'],'kind':kind,'release_h':c['earliest_h'],
                'deadline_h':c['latest_h'],'duration_h':c['duration_h'],'baseline_start_h':c['preferred_h'],
                'operator_member_id':a['operator_member_id'],'start_mode':'preprogrammed_reference',
                'depends_on':['washer_weekday'+str(weekday)] if kind=='dryer' else [],'program_source':'exact pinned EB ShiftableAppliance constant-power duration program'})
        if assets['water_heater']['present']:jobs.append({'id':'hotwater_weekday'+str(weekday),'kind':'water_heater','device_id':assets['water_heater']['id'],'required_h':20.5,'nominal_draw_litres':30.*f['resident_count'],'draw_duration_minutes':10*f['resident_count'],'minimum_timestep_average_outlet_C':40.,'baseline_heating_window_h':[17.,21.],'allowed_preheat_window_h':[15.,21.]})
        if assets['ev']['present']:jobs.append({'id':'ev_weekday'+str(weekday),'kind':'ev','device_id':assets['ev']['id'],'arrival_h':18.5 if weekday<5 else 0.,'departure_h':7.5 if weekday<5 else 24.,'daily_drive_kWh':25. if weekday<5 else 0.,'target_SOC':assets['ev']['config']['target_soc'],'minimum_SOC':assets['ev']['config']['min_soc']})
        weekly_tasks.append({'weekday':weekday,'jobs':jobs})
    # Declared external services close needs without inventing controllable in-home hardware.
    external={'washing':'in_home_reference' if assets['washer']['present'] else 'given external laundry service;not controlled or household-metered',
              'dishwashing':'in_home_reference' if assets['dishwasher']['present'] else 'given manual or external dishwashing;outside six-device electrical task scope',
              'drying':'reference_dryer' if assets['dryer']['present'] else 'given passive or external drying service',
              'hot_water':'reference_electric_tank' if assets['water_heater']['present'] else 'given noncontrollable local/central/external hot-water service consistent with housing facet',
              'vehicle':'reference_home_EV' if assets['ev']['present'] else 'no home-EV task in this declared world',
              'no_adult':'manual task execution disabled;assistance inquiry has no unspecified additional resident' if not adults else 'not_applicable'}
    result={'schema':'eb.six_device_world.v1','household_id':hid,'province':profile['province'],'population_weight':profile['relative_population_weight'],
            'population_frame':'2020 city ordinary residential family household reference;towns/rural excluded',
            'N':f['resident_count'],'G':f['generation_count'],'H6':source['fixed_H6_m2'],'H7':source['fixed_H7'],
            'members':members,'ego_relationships':f['ego_relationships'],'layout':layout,'assets':assets,'weekly_tasks':weekly_tasks,'external_services':external,
            'reference_initial_states':{'EV_SOC':assets['ev']['config']['initial_soc'],'water_inlet_C':15.,'tank_reference_volume_m3':.06,'tank_UA_W_K':1.5,'tank_setpoint_C':55.,'thermal_history':'EnergyPlus warmup atcommonJul1 start thenidentical prescribedhistory;not measured'},
            'background_scope':{'lighting':'Ding/Zhou2020 reference density','other_fixed_electricity':'distinct prespecified50% ofpublished aggregateplug reference;not incremental appliance inventory estimate','six_device_double_count':'published inclusive aggregate replaced;fixed background explicitly redefined','auxiliary_people':'fixed declared absent during benchmark reference world;not observed absence','shared_meter':'separate shared_unallocated reference bucket;no area to bill inference'},
            'hardware_design_factor':{'factor':factor,'dishwasher_dryer_EV_levels':'experimentalcoverage factors conditionaloneligibility;not observed China prevalence'},
            'tariff_reference':{'flat_CNY_per_kWh':.6,'observed_local_tariff':False},'reference_calendar_start':START.isoformat(),'reference_calendar_end':'2026-06-30',
            'source_links':{'profile_path':str((V7/'HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json').relative_to(BASE)),
                            'geometry_world':str((V10/record['service_world_path']).relative_to(BASE)),
                            'geometry_world_sha256':sha(V10/record['service_world_path']),
                            'historic_devices':str((V9/'DEVICE_PRIOR_ROUTES1000.json').relative_to(BASE)),
                            'EB_equipment_defaults':str(DEFAULTS_PATH),'EB_equipment_defaults_sha256':sha(DEFAULTS_PATH)},
            'source_missing_values_remain_in_evidence_layer':True,'actor_preferences_and_answers':None}
    result['world_content_sha256']=digest(result)
    return result

def main():
    guard();profiles=read(V7/'HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json')['profiles'];priors={r['household_id']:r for r in read(V9/'DEVICE_PRIOR_ROUTES1000.json')['routes']};bindings={r['household_id']:r for r in read(V10/'SERVICE_PORT_BINDINGS.json')['records']}
    records=[];counts=collections.Counter();reasons=collections.Counter()
    for p in profiles:
        hid=p['slot_id'];b=bindings[hid];w=world(p,priors[hid],read(V10/b['service_world_path']),b);path=OUT/'worlds'/f'{hid}.json';save(path,w)
        assert w['N']==p['exact_member_count'] and w['G']==p['family']['generation_count'] and w['H6']==p['housing']['H6_census_building_area_design_m2'] and w['H7']==p['housing']['H7_independent_natural_rooms_design']
        for kind,a in w['assets'].items():counts[kind]+=a['present'];reasons[kind+'/'+a['reference_choice_reason']]+=1
        records.append({'household_id':hid,'world_path':str(path.relative_to(OUT)),'world_sha256':sha(path),'world_content_sha256':w['world_content_sha256'],'weather':b['weather'],'source_geometry':b['service_IDF_path']})
    save(OUT/'WORLD_BINDINGS1000.json',{'records':records,'households':len(records),'residents':sum(p['exact_member_count'] for p in profiles),'configured_device_counts':dict(counts),'configuration_reasons':dict(reasons),'device_counts_are_reference_design_not_population_estimates':True,'formal_human_answers':0})
    print({'worlds':len(records),'residents':2524,'devices':dict(counts)},flush=True)
if __name__=='__main__':main()
