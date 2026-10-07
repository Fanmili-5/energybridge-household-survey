"""Joint reference construction. Survey values are preserved in an evidence layer."""
import collections, concurrent.futures, copy, math
from common import *
from joint_geometry import candidates
DEFAULTS=read(OUT/'inputs/eb_equipment_defaults.json')
AC=read(OUT/'inputs/AC_CATALOG.json')['reference_units']
def support(b):
    w=read(OLD/b['world_path']);rows=parse(V12/'background_idfs'/f"{w['household_id']}.idf")
    cs,fs=candidates(w,rows)
    return w,b,cs,fs
def operator_context(w):
    adult=next((m for m in w['members'] if m['age_years']>=18),None)
    if adult:
        windows={}
        for day in adult['weekly_calendar']:
            # Availability for manual tasks is stricter than mere physical occupancy.
            windows[str(day['weekday'])]=[[int(x['start_h']*60),int(x['end_h']*60)] for x in day['intervals']
                if x['location']=='home' and x['activity'] not in ['sleep_rest','home_work','dinner']]
        return {'operator_id':adult['member_id'],'resident':True,'weekly_windows_min':windows,
                'evidence':'reference household activity grammar;permission for hypothetical execution is designed,not human adoption'}
    return {'operator_id':w['household_id']+':external_guardian','resident':False,
        'weekly_windows_min':{str(d):[[420,450],[1110,1350]] for d in range(7)},
        'evidence':'explicit nonresident guardian assistance scenario for the retained child-only roster;not observed or an extra resident',
        'roleplay_representative':'adult guardian answers on behalf of this reference household',
        'care_scope':'given daytime school/care and reachable guardian;not a model of unsupported independent child living'}
def routine(w, prior):
    hid=w['household_id'];report=next((x for x in prior['auxiliary_reported_assets'] if x['class'] in ['washer','washer_dryer_combo_report']),None)
    code=report.get('frequency_bin') if report else None
    # Coarsened historical bins are transported only as use priors. Within-bin counts
    # and exact day offsets are explicit reference imputations, never diary observations.
    count={1:7,2:7,3:7,4:4+rank(hid,'wash-count')%3,5:1+rank(hid,'wash-count')%3,6:.5,7:0}.get(code,3)
    if count==.5:
        wash_days=[rank(hid,'wash-weekday')%7];alternate_week=rank(hid,'wash-week-phase')%2
        batches=1
    else:
        n=int(count);batches=max(1,math.ceil(n/7));wash_days=sorted(range(7),key=lambda d:rank(hid,'wash-weekday',d))[:min(n,7)];alternate_week=None
    return {'wash_days':sorted(wash_days),'wash_batches_each_active_day':batches if count else 0,
        'wash_alternate_week_phase':alternate_week,'historical_frequency_bin':code,
        'historical_report_id':report.get('report_reference_id') if report else None,
        'wash_count_reference_per_week':count,'match_route':prior['match_route'],
        'source_year':2012 if report else None,
        'frequency_rule':'CRECS c3_1e bins4to7 with explicit realization;daily bins1to3 use one benchmark cycle/day because duration and physical hardware are resynthesized;3/week fallback',
        'high_frequency_transport_normalized':code in [1,2],
        'high_frequency_rule_is_design_not_same_source_rate':code in [1,2],
        'duration_rule':'EB benchmark washer120min,dryer90min;historical duration bin is retained separately and not used as device-specific program duration',
        'historical_duration_bin':report.get('duration_bin') if report else None,
        'laundry_batch_kg':min(4.5,1.+w['N']*.5),
        'batch_mass_is_reference_design':True,
        'wash_preferred_min':1110+10*(rank(hid,'wash-clock')%7),
        'dish_preferred_min':1200+10*(rank(hid,'dish-clock')%4),
        'tank_heat_window_min':[960+10*(rank(hid,'tank-clock')%7),1260],
        'tank_setpoint_C':60.,'bath_start_min':1230,'mixed_water_L_per_resident':30.,
        'mixed_target_C':40.5555555555556,'bath_duration_min_per_resident':10,
        'exact_activity_and_service_clocks':'designed stable routine;not joint measured household diary',
        'EV_trip_days':[0,1,2,3,4],'EV_departure_min':450,'EV_arrival_min':1110,
        'EV_daily_trip_kWh':25.,'EV_target_soc':.85,'EV_input_lane':'ApplianceSuite defaults,not appliance_controller.py alternate parameters'}
def materialize(w,b,c,prior):
    w=copy.deepcopy(w);hid=w['household_id'];types=c['types'];layout=w['layout']
    anchor={k:w[k] for k in ['household_id','province','population_frame','population_weight','N','G','H6','H7','members','ego_relationships']}
    w['anchor_sha256']=digest(anchor);w['source_world_file_sha256']=sha(OLD/b['world_path'])
    w['source_world_stage']=OLD.name;w['source_world_path']=b['world_path']
    old_facets=copy.deepcopy(layout['stock_reference_features']);changes=[]
    w['evidence_layer']={'original_housing_facets':old_facets,'historical_device_prior':prior,
        'original_source_links':copy.deepcopy(w['source_links']),
        'reference_values_are_not_same_household_observations':True}
    # Earlier geometry packages carry their own incomplete-inventory/disabled-action
    # flags. Namespace those source snapshots instead of exposing contradictory
    # current statuses in the new complete reference input.
    w['evidence_layer']['upstream_assembly_status']={k:layout.pop(k) for k in ['complete_household_energy_world','actor_ready','operator_context'] if k in layout}
    if 'complete_actor_world' in layout['sleep_reference']:
        w['evidence_layer']['upstream_assembly_status']['sleep_complete_actor_world']=layout['sleep_reference'].pop('complete_actor_world')
    layout['reference_task_geometry_complete']=True
    layout['door_motion_reference']='non-swing reference portals;sliding mechanism/mounting are design boundaries,not asbuilt or building-code certification'
    if old_facets['piped_water']!='present':
        layout['stock_reference_features']['piped_water']='present'
        changes.append({'field':'reference_piped_water','old':old_facets['piped_water'],'new':'present',
            'reason':'4to6-equipment benchmark conditions on an explicitly connected supply and drainage installation;source marginal remains in evidence layer',
            'evidence_kind':'benchmark service design,not census observation'})
    if 'water_heater' in types and old_facets['bathing_hot_water']!='self_installed_heater':
        layout['stock_reference_features']['bathing_hot_water']='self_installed_heater'
        changes.append({'field':'controlled_hot_water_service','old':old_facets['bathing_hot_water'],
            'new':'dedicated local electric tank for target draw;central/external source disconnected from this target stream',
            'evidence_kind':'reference service resynthesis,not retrofit prevalence'})
    op=operator_context(w);w['operating_context']={'operators':[op],
        'reference_manual_action_enabled':True,
        'control_rights':'installed target assets hypothetically controlled after the event notice;human adoption remains null',
        'shared_rooms':'same room access and reserved appliance times for both arms;other using households have no use of target assets during these reservations',
        'target_meter':'target device electricity plus explicit allocated background;shared room area shares do not imply device ownership',
        'service_installation':{'water_supply':'piped water15C reference inlet','drainage':'explicit connected drain','pressure_and_asbuilt_certification':False}}
    if not op['resident']:changes.append({'field':'nonresident_assistance','new':op,'resident_count_changed':False,'evidence_kind':'explicit reference scenario'})
    places={p['kind']:p for p in c['placements']}
    for room in layout['rooms']:
        if room.get('census_toilet_facility_reference_present'):
            room['physical_toilet_fixture_geometry_instantiated']=any(p['kind']=='toilet' and p['room_id']==room['room_id'] for p in c['placements'])
    for p in c['placements']:
        room=next(r for r in layout['rooms'] if r['room_id']==p['room_id'])
        if p['kind'] in ['laundry','tank'] and room['census_room_class']=='hall':
            changes.append({'field':'hall_service_alcove','room_id':p['room_id'],'device':p['kind'],
                'reason':'reference cabinet and pipe extension inside existing hall;walls,beds,H6,H7 retained;shared-use reservation explicit',
                'evidence_kind':'joint reference installation design;not observed Chinese housing stock'})
    devices=[];assets={};served=set(m['reference_home_room_id'] for m in w['members']);recipe=routine(w,prior)
    rooms={r['room_id']:r for r in layout['rooms']}
    for kind in KINDS:
        cfg=copy.deepcopy(DEFAULTS[kind]);cfg['present']=kind in types
        if kind in ['washer','dryer','dishwasher']:
            cfg.update(earliest_h=19.5 if kind=='dishwasher' else 6.5,latest_h=24.)
            cfg['preferred_h']=(recipe['dish_preferred_min'] if kind=='dishwasher' else recipe['wash_preferred_min']+(120 if kind=='dryer' else 0))/60
        if kind=='ev':cfg.update(initial_soc=.85,efficiency=.92)
        if kind=='water_heater':cfg.update(bath_required_h=recipe['bath_start_min']/60,
            pre_heat_window_start_h=recipe['tank_heat_window_min'][0]/60,pre_heat_window_end_h=recipe['tank_heat_window_min'][1]/60)
        assets[kind]={'kind':kind,'present':kind in types,'config':cfg,'asset_ids':[]}
        if kind not in types:continue
        if kind=='ac':
            for rid in sorted(served):
                room=rooms[rid];area=room['thermal_reference_area_m2'];unit=AC[0] if area<=15 else AC[1]
                n=max(1,math.ceil(area/unit['area_range_m2'][1]));x0,y0,x1,y1=room['usable_rect_m']
                wall=max(x1-x0,y1-y0);slots=math.floor(wall/(unit['width_m']+.1))
                if n>slots:raise RuntimeError(f'AC_WALL_LENGTH:{hid}:{rid}')
                for j in range(n):
                    aid=f'{hid}:ac:{rid}:{j+1}'
                    devices.append({'asset_id':aid,'types':['ac'],'room_id':rid,'served_rooms':[rid],
                        'model_family':'zone DX reference with EB curves and OEM rated point',
                        'parameters':copy.deepcopy(unit),'max_electric_kw':unit['max_electric_W']/1000,
                        'circuit':'AC','reference_upper_setpoint_C':27.,'operator_id':op['operator_id'],
                        'meter_scope':'target','rated_area_below_nominal':area/n<unit['area_range_m2'][0],
                        'installation':{'mode':'wall reference at2m;design mount,not structural certification',
                            'wall_length_available_m':wall,'reserved_width_each_m':unit['width_m']+.1,'units_on_wall':n},
                        'parameter_source':unit['url'],'source_offdesign_curve_transfer_is_uncalibrated':True})
                    assets[kind]['asset_ids'].append(aid)
        else:
            aid=f'{hid}:laundry:1' if kind in ['washer','dryer'] else f'{hid}:{kind}:1'
            if kind=='dryer':
                d=next(d for d in devices if d['asset_id']==aid);d['types'].append('dryer');d['max_electric_kw']=max(d['max_electric_kw'],cfg['power_kw'])
                d['parameters']['dryer']=cfg;assets[kind]['asset_ids']=[aid];continue
            p=places.get('laundry' if kind=='washer' else 'tank' if kind=='water_heater' else kind)
            params={kind:cfg} if kind=='washer' else cfg
            rid=p['room_id'] if p else 'external_dedicated_EV_bay'
            if kind=='water_heater':
                params={'volume_m3':.12,'height_m':1.05,'shape':'VerticalCylinder','heater_capacity_W':3000.,'heater2_capacity_W':0.,
                    'efficiency':1.,'maximum_C':65.,'deadband_C':4.,'skin_U_W_m2K':1.2,'number_of_nodes':1,
                    'inlet_C':15.,'target_mixed_C':40.5555555555556,'mixed_shower_peak_m3_s':.000141975}
                cfg['rated_kw']=3.;assets[kind]['config']=cfg
            devices.append({'asset_id':aid,'types':[kind],'room_id':rid,'served_rooms':[rid] if p else [],
                'model_family':'EB ShiftableAppliance functional reference on combo geometry' if kind=='washer' else 'EB native Stratified' if kind=='water_heater' else 'EB ApplianceSuite '+kind,
                'parameters':params,'max_electric_kw':cfg.get('power_kw',3. if kind=='water_heater' else cfg.get('charger_kw',0)),
                'circuit':'EV_bay' if kind=='ev' else 'hot_water' if kind=='water_heater' else 'wet_appliances',
                'tank_max_C':65. if kind=='water_heater' else None,'operator_id':op['operator_id'],'meter_scope':'target',
                'installation':p or {'mode':'outside dwelling;exclusive reserved bay and dedicated electric supply','bay_dimensions_m':[2.5,5.0],
                    'bay_in_H6_or_H7':False,'plug_operation_required':True,'driver':'reference licensed nonresident transport operator;resident eligibility does not imply a license',
                    'trip_source':'explicit weekday transport service,not inferred observed commuting'},
                'parameter_source':'pinned EB source IDF' if kind=='water_heater' else 'pinned EB appliance defaults;geometry source tracked separately'})
            assets[kind]['asset_ids']=[aid]
    home_peak=sum(d['max_electric_kw'] for d in devices if d['circuit']!='EV_bay')
    background_kw=sum(r['thermal_reference_area_m2']*((1.8 if r['census_room_class']=='corridor' else 4.2)+.5*(5 if r['census_room_class']=='kitchen' else 2))/len(r['using_household_ids'])/1000 for r in layout['rooms'] if hid in r['using_household_ids'])+.01
    home_rating=next((a for a in [40,60,80,100,125,160] if .220*a>=home_peak+background_kw),None)
    if home_rating is None:raise RuntimeError('ELECTRIC_SERVICE_SUPPORT:'+hid)
    circuits={'wet_appliances':4.4,'hot_water':4.4,'AC':max(4.4,.220*math.ceil(sum(d['max_electric_kw'] for d in devices if d['circuit']=='AC')/.220/20)*20), 'EV_bay':8.8}
    pack={'devices':devices,'control_defaults':{k:a['config'] for k,a in assets.items()},'circuit_limit_kw':circuits,'home_service_limit_kw':home_rating*.220,'background_reserved_kw':background_kw,
        'electric_design':'finite reference branch and inlet sizes at220V;selected from40/60/80/100/125/160A to support declared installed specs plus the compiled lighting/background nameplate reservation;not observed service capacity',
        'power_check_scope':'published/device-program input envelope;EP offdesign electrical outcomes require later meter validation',
        'EB_defaults_sha256':sha(OUT/'inputs/eb_equipment_defaults.json'),
        'EB_native_IDF_sha256':sha(UP/'experiments/models/family_home/family_simple_3day.idf'),
        'EB_appliance_kernel_sha256':sha(UP/'energybridge/simulation/appliance_sim.py'),
        'AC_catalog_sha256':sha(OUT/'inputs/AC_CATALOG.json')}
    w['assets']=assets;w['parameter_pack']=pack;w['parameter_pack_sha256']=digest(pack)
    w['routine']=recipe;w['reference_change_ledger']=changes
    external={'washing':'configured EB reference program' if 'washer' in types else 'given external laundry service on the frozen routine;not target-meter electricity',
        'drying':'automatic same-combo dry program' if 'dryer' in types else 'given passive/external drying after fixed morning unload;same service context in A/B',
        'dishwashing':'configured EB dishwasher program' if 'dishwasher' in types else 'given manual/external dishwashing after the same reference meals',
        'hot_water':'dedicated native electric tank for target mixed draws' if 'water_heater' in types else 'given noncontrolled hot-water service;outside controlled electrical meter',
        'transport':'explicit fixed EV trip/bay service' if 'ev' in types else 'given non-EV transport;no invented home charger',
        'cooking':'given meal preparation/provision at the stable meal clocks;outside six-device controls',
        'sanitation':'instantiated reference toilet fixture' if any(p['kind']=='toilet' for p in c['placements']) else 'given shared/external sanitary facility,outside target controls',
        'other_electricity':'separate fixed aggregate background,not inferred item-by-item ownership',
        'boundaries':'outside services are designed exogenous conditions,not measured availability;B cannot modify them'}
    w['given_external_services']=external
    w['joint_matching']={'types':types,'type_count':len(types),'spatial_witnesses':c['placements'],
        'sleep_metric_access_witnesses':c['sleep_metric_access_witnesses'],
        'fixed_walls_beds_and_portals_preserved':True,'class_frequency_is_benchmark_design':True,
        'space_proof':'rectangles and600mm reference front-access connectivity;not national code or asbuilt certification',
        'source_housing_facility_marginal_preserved_as_evidence_not_configured_benchmark_marginal':True}
    w['reference_initial_states']={'EV_SOC':.85,'tank_inlet_C':15.,'tank_initial_C':60.,
        'history':'seven common A calendar days plus EP warmup;independent sampled episodes;14day sensitivity prescribed',
        'measured_state':False}
    w['schema']='eb.joint_static_reference_world.v1'
    w['protocol_sha256']=sha(OUT/'PROTOCOL.json')
    for k in ['world_content_sha256','weekly_tasks','external_services','random10_task_families','task_selection_design','hardware_design_factor']:w.pop(k,None)
    w['actor_preferences_and_answers']=None
    w['world_content_sha256']=digest(w)
    return w
def main():
    school_guard();bindings=read(OLD/'WORLD_BINDINGS1000.json')['records']
    priors={r['household_id']:r for r in read(OUT/'inputs/DEVICE_PRIOR_ROUTES1000.json')['routes']}
    with concurrent.futures.ProcessPoolExecutor(max_workers=12) as pool: support_rows=list(pool.map(support,bindings))
    supported=[];failed=[]
    for w,b,cs,fs in support_rows:
        if not cs:failed.append({'household_id':w['household_id'],'failures':fs})
        else:supported.append((w,b,cs,fs))
    save(OUT/'GEOMETRIC_SUPPORT.json',{'households':len(bindings),'supported':len(supported),'failed':failed,
        'K_support':dict(collections.Counter(k for _,_,cs,_ in supported for k in set(len(c['types']) for c in cs)))})
    if failed:raise RuntimeError('Retain infeasible anchors and repair common construction before production:'+str(len(failed)))
    quota={4:333,5:333,6:334};counts=collections.Counter();type_counts=collections.Counter();combo_counts=collections.Counter();records=[]
    # More constrained worlds are assigned first. Quotas are design, not prevalence.
    supported.sort(key=lambda row:(len(row[2]),rank(row[0]['household_id'],'assignment-v16')))
    for w,b,cs,fs in supported:
        cs=[c for c in cs if counts[len(c['types'])]<quota[len(c['types'])]]
        if not cs:raise RuntimeError('QUOTA_SUPPORT:'+w['household_id'])
        c=min(cs,key=lambda c:(counts[len(c['types'])]/quota[len(c['types'])],combo_counts[tuple(c['types'])],sum(type_counts[k] for k in c['types']),rank(w['household_id'],c['types'])))
        nw=materialize(w,b,c,priors[w['household_id']]);hid=w['household_id'];p=OUT/'worlds'/f'{hid}.json';save(p,nw)
        counts[len(c['types'])]+=1;combo_counts[tuple(c['types'])]+=1;type_counts.update(c['types'])
        records.append({'household_id':hid,'world_path':str(p.relative_to(OUT)),'world_sha256':sha(p),
            'world_content_sha256':nw['world_content_sha256'],'parameter_pack_sha256':nw['parameter_pack_sha256'],
            'source_world_file_sha256':nw['source_world_file_sha256'],'weather':b['weather'],
            'feasible_patterns':len(cs),'excluded_patterns':fs})
    records.sort(key=lambda r:r['household_id'])
    save(OUT/'WORLD_BINDINGS1000.json',{'records':records,'households':len(records),'K_counts':dict(counts),'device_class_counts':dict(type_counts),
        'pattern_counts':{'|'.join(k):v for k,v in combo_counts.items()},'source_population_weights_are_not_device_prevalence_weights':True})
    print({'worlds':len(records),'K_counts':dict(counts),'patterns':len(combo_counts)},flush=True)
if __name__=='__main__':main()
