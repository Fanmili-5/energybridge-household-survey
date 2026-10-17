"""Functional space checks independent of the shape-selection objective."""
from collections import Counter
from shapely.geometry import box,Point
from shapely.ops import unary_union


def space_issues(w):
    occupants=Counter(m['reference_home_room_id']for m in w['members']);bad=[]
    for r in w['layout']['rooms']:
        if w['household_id']not in r['using_household_ids']:continue
        rid=r['room_id'];a=r['usable_area_m2'];x0,y0,x1,y1=r['usable_rect_m'];width=min(x1-x0,y1-y0);kind=r['census_room_class']
        minimum=12 if rid=='combined_bed_living'else (9 if occupants[rid]>1 else 5)if kind=='bedroom'and occupants[rid]else 10 if kind=='hall'else 4 if kind=='kitchen'else 0
        if a+1e-6<minimum:bad.append(rid+':area')
        if kind=='corridor'and width<1.-1e-6:bad.append(rid+':route_width')
        if kind=='kitchen'and width<1.5-1e-6:bad.append(rid+':working_width')
    return bad


def review(w,rows):
    hid=w['household_id'];layout=w['layout'];rooms={r['room_id']:r for r in layout['rooms']};bad=space_issues(w)
    rects=[box(*r['gross_rect_m'])for r in rooms.values()]
    if abs(sum(p.area for p in rects)-unary_union(rects).area)>1e-6:bad.append('ROOM_OVERLAP')
    if abs(sum(p.area for p in rects)-layout['whole_unit_building_area_m2'])>1e-6:bad.append('WHOLE_AREA')
    if abs(sum(r['gross_area_m2']*r['area_allocation_fractions'].get(hid,0)for r in rooms.values())-w['H6'])>1e-6:bad.append('TARGET_AREA')
    if sum(r['census_room_class']=='bedroom'and r['using_household_ids']==[hid]for r in rooms.values())!=w['H7']:bad.append('TARGET_ROOM_COUNT')
    for r in rooms.values():
        if abs(sum(r['area_allocation_fractions'].values())-1)>1e-8:bad.append('AREA_SHARES')
    people={m['member_id']for m in w['members']};berths=w['layout']['sleep_reference']['berths']
    if {b['member_id']for b in berths}!=people or len(berths)!=w['N']:bad.append('TARGET_BERTHS')
    ds=w['parameter_pack']['devices'];classes={k for d in ds for k in d['types']}
    if not 4<=len(classes)<=6 or'ac'not in classes:bad.append('DEVICE_COVERAGE')
    if 'dryer'in classes and'washer'not in classes:bad.append('DRYER_CHAIN')
    for d in ds:
        if 'ev'in d['types']:
            if d['room_id']!='external_dedicated_EV_bay'or not w.get('given_transport_contract'):bad.append('EV_SUPPORT')
        elif d['room_id']not in rooms or hid not in rooms[d['room_id']]['using_household_ids']:bad.append('DEVICE_ROOM')
        if set(d['types'])&{'washer','dishwasher','water_heater'}and w['layout']['stock_reference_features']['piped_water']!='present':bad.append('WATER_SUPPORT')
        if not d.get('installation'):bad.append('MISSING_INSTALLATION')
    # Own and neighbor bed footprints must lie in their private rooms.
    sleeps=[layout['sleep_reference']]+[r['sleep_reference']for r in w.get('shared_context',{}).get('households',[])]
    for sleep in sleeps:
        for f in sleep['frames']:
            r=rooms[f['room_id']]
            if not box(*r['usable_rect_m']).buffer(1e-6).covers(box(*f['outer_rect_m'])):bad.append('BED_OUTSIDE')
    # Rows and JSON must describe the same enclosure and openings.
    if {r[1]for r in rows if r[0]=='Zone'}!=set(rooms):bad.append('IDF_ZONE_BINDING')
    modeled_area=sum((max(float(r[i])for i in range(12,len(r),3))-min(float(r[i])for i in range(12,len(r),3)))*
                     (max(float(r[i])for i in range(13,len(r),3))-min(float(r[i])for i in range(13,len(r),3)))
                     for r in rows if r[0]=='BuildingSurface:Detailed'and r[2]=='Floor')
    if abs(modeled_area-layout['thermal_reference_floor_area_m2'])>1e-5:bad.append('IDF_THERMAL_FLOOR_AREA')
    return {'household_id':hid,'passed':not bad,'errors':sorted(set(bad)),
            'classes':sorted(classes),'N':w['N'],'area_m2':w['H6'],'rooms':w['H7'],
            'scope':'constructed metric housing and equipment support;not asbuilt/code/physical-outcome validation'}
