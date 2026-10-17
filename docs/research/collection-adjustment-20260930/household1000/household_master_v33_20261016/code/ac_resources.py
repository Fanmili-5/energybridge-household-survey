"""All-household AC as an explicit benchmark resource; actual room DX assets.

Retain the pinned EB DX/fan bundle. Capacity and airflow scale together using
the same admitted 2610/3500W reference families; no fitted comfort or ownership.
"""
import copy, hashlib, json, math
def digest(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def install(world,templates):
    w=copy.deepcopy(world);hid=w['household_id'];devices=w['parameter_pack']['devices']
    old=[d for d in devices if 'ac'in d['types']];others=[d for d in devices if 'ac'not in d['types']]
    target={m['reference_home_room_id']for m in w['members']}
    # Include the household's daytime living room, not an unused whole apartment.
    target|={r['room_id']for r in w['layout']['rooms']if hid in r['using_household_ids']and r['census_room_class']=='hall'}
    rooms={r['room_id']:r for r in w['layout']['rooms']};units=[]
    for rid in sorted(target):
        r=rooms[rid];area=r['thermal_reference_area_m2'];capacity=2610 if area<=15 else 3500
        template=min(templates,key=lambda d:abs(d['parameters']['cooling_W']-capacity))
        q=template['parameters'];count=max(1,math.ceil(area/q['area_range_m2'][1]));x0,y0,x1,y1=r['usable_rect_m'];wall=max(x1-x0,y1-y0)
        if count*(q['width_m']+.1)>wall+1e-8:raise ValueError('AC_WALL_SUPPORT:'+hid+':'+rid)
        for j in range(count):
            d=copy.deepcopy(template);aid=f'{hid}:ac:{rid}:{j+1}'
            d.update(asset_id=aid,room_id=rid,served_rooms=[rid],operator_id=w['role_policy']['holder']['person_id'],
                reference_upper_setpoint_C=w['role_policy']['thermal']['absolute_upper_control_C'],
                installation={'mode':'given wall-mounted reference at2m;not structural certification','wall_length_available_m':wall,
                    'reserved_width_each_m':q['width_m']+.1,'units_on_wall':count},rated_area_below_nominal=area/count<q['area_range_m2'][0])
            units.append(d)
    w['parameter_pack']['devices']=units+others
    classes={t for d in w['parameter_pack']['devices']for t in d['types']}
    if not 4<=len(classes)<=6 or 'ac'not in classes:raise ValueError('FUNCTIONAL_RESOURCE_COUNT')
    asset=w['assets']['ac'];asset['present']=True;asset['asset_ids']=[d['asset_id']for d in units]
    if 'config'in asset:asset['config']['present']=True
    if 'control_defaults'in w['parameter_pack']:
        w['parameter_pack']['control_defaults']['ac']=copy.deepcopy(asset['config'])
    circuits=w['parameter_pack']['circuit_limit_kw'];ac_kw=sum(d['max_electric_kw']for d in units)
    circuits['AC']=max(4.4,.220*20*math.ceil(ac_kw/(.220*20)))
    peak=sum(d['max_electric_kw']for d in w['parameter_pack']['devices']if d['circuit']!='EV_bay')
    reserve=w['parameter_pack']['background_reserved_kw'];amps=next((a for a in [40,60,80,100,125,160]if .220*a>=peak+reserve),None)
    if amps is None:raise ValueError('HOME_ELECTRIC_REFERENCE_LIMIT:'+hid)
    w['parameter_pack']['home_service_limit_kw']=.220*amps
    w['joint_matching']['types']=sorted(classes);w['joint_matching']['type_count']=len(classes)
    w['AC_resource_contract']={'coverage':'all households by explicit user instruction2026-10-15','observed_ownership':None,
        'reference_rooms':sorted(target),'native_parameters_fitted_to_outcomes':False,
        'sleep_and_living_services_require_room_assets':True,'previous_AC_asset_count':len(old),'current_AC_asset_count':len(units),
        'actual_control_and_IDF_required_before_acceptance':True,'constant_all_day_cooling_assumed':False,
        'shared_living_control_rights':'explicit benchmark permission for this household reference AC;other users occupancy and agreement are unknown',
        'sizing_scope':'EB area-range reference sizing;not validated room load or Chinese installed-unit prevalence'}
    w['parameter_pack_sha256']=digest(w['parameter_pack'])
    return w
