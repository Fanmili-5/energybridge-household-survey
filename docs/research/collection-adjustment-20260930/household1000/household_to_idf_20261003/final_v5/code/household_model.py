#!/usr/bin/env python3
"""Explicit household-to-building contract and closed rectangular research layout."""
import hashlib
import json
import math
import re
from pathlib import Path

HERE=Path(__file__).resolve().parent
REPO=next(p for p in HERE.parents if p.name=='energybridge-household-survey')
BATCH='HOUSEHOLD_TO_IDF_20261003_V1'

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')

def decision(trace,key,value,evidence,inputs,rule,limits=None):
    trace.append({'decision_id':key,'value':value,'evidence_status':evidence,'input_paths':inputs,
                  'rule':rule,'limitations':limits or []})

def input_errors(item):
    errors=[]
    def real(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
    def require(ok,name):
        if not ok:errors.append(name)
    require(isinstance(item.get('case_id'),str) and bool(re.fullmatch(r'[A-Za-z0-9_-]{1,100}',item.get('case_id',''))),'case_id_missing_or_unsafe')
    for key in ['family','housing','model_policy','site']:
        if not isinstance(item.get(key),dict):return ['input_section_missing_or_not_object:'+key]
    members=item.get('family',{}).get('resident_member_ids')
    require(isinstance(members,list) and len(members)>0,'resident_roster_missing')
    members_valid=isinstance(members,list) and all(isinstance(x,str) and x for x in members)
    if members_valid:
        require(len(members)==len(set(members)),'resident_ids_not_unique')
        require(all(isinstance(x,str) and x for x in members),'resident_id_invalid')
        require(type(item['family'].get('resident_count')) is int and item['family']['resident_count']==len(members),'resident_count_roster_mismatch')
    family=item.get('family',{})
    require(family.get('population_scope')=='city_family_household','city_family_scope_not_declared')
    require(family.get('residence_evidence') in ['matched_chfs_proxy','declared_synthetic_role','actor_supplied'],'residence_evidence_missing')
    h=item.get('housing',{});p=item.get('model_policy',{})
    require(h.get('H5_status')=='ordinary_declared_or_matched','H5_not_ordinary_or_unresolved')
    require(isinstance(h.get('H5_evidence'),str) and bool(h['H5_evidence'].strip()),'H5_evidence_missing')
    require(h.get('occupancy_scope')=='whole_household_private','shared_scope_not_resolved')
    require(type(h.get('household_storeys')) is int and h['household_storeys']==1,'household_multistorey_unsupported')
    require(h.get('dwelling_type')=='apartment','dwelling_type_unsupported')
    area=h.get('H6_building_area_m2')
    require(real(area) and area>0,'H6_missing_or_invalid')
    require(h.get('H6_evidence') in ['matched_area_proxy','source_reported','declared_design'],'H6_evidence_missing')
    rooms=h.get('H7_natural_rooms_exact')
    require(isinstance(rooms,int) and not isinstance(rooms,bool) and 1<=rooms<=20,'H7_exact_missing_or_invalid')
    require(h.get('H7_evidence') in ['matched_census_conditional','source_proxy','declared_design','actor_supplied'],'H7_evidence_missing')
    require(h.get('H7_definition')=='natural_rooms_excluding_kitchen_toilet_corridor_hall','H7_definition_mismatch')
    groups=h.get('sleep_groups')
    require(isinstance(groups,list) and isinstance(rooms,int) and len(groups)==rooms,'sleep_groups_H7_mismatch')
    if isinstance(groups,list) and all(isinstance(g,list) and all(isinstance(m,str) and m for m in g) for g in groups) and members_valid:
        assigned=[m for g in groups for m in g]
        require(sorted(assigned)==sorted(members),'sleep_assignment_not_exact_resident_partition')
    else:require(False,'sleep_group_format_invalid')
    ratio=p.get('gross_to_zone_floor_ratio')
    require(real(ratio) and 0<ratio<=1,'net_ratio_missing_or_invalid')
    require(p.get('net_ratio_evidence')=='declared_geometry_bridge','net_ratio_evidence_missing')
    require(p.get('floor_position') in ['middle','top','ground'],'floor_position_missing')
    require(p.get('floor_position')!='ground' or (p.get('ground_temperature_method')=='explicit_research_boundary' and
            isinstance(p.get('ground_monthly_temperatures_C'),list) and len(p['ground_monthly_temperatures_C'])==12 and all(real(v) for v in p['ground_monthly_temperatures_C'])),'ground_boundary_unresolved')
    require(p.get('wall_boundaries') in [{'west':'Adiabatic','east':'Adiabatic','south':'Outdoors','north':'Outdoors'},
            {'west':'Outdoors','east':'Outdoors','south':'Outdoors','north':'Outdoors'}],'wall_boundary_policy_missing_or_unsupported')
    require(real(p.get('north_axis_deg')) and 0<=p['north_axis_deg']<360,'orientation_missing_or_invalid')
    require(real(p.get('air_exchange_ach')) and 0<=p['air_exchange_ach']<=10,'air_exchange_missing_or_invalid')
    require(isinstance(p.get('prototype_key'),str) and bool(p.get('prototype_key')),'thermal_prototype_missing')
    require(item.get('operation_mode')=='building_shell_validation','operation_mode_not_supported')
    return sorted(set(errors))

def make_layout(item,trace):
    h=item['housing'];p=item['model_policy'];area=h['H6_building_area_m2']
    net=area*p['gross_to_zone_floor_ratio'];groups=h['sleep_groups'];rooms=h['H7_natural_rooms_exact']
    # Explicit prototype capacity assumptions, not building-code minima.
    minimum_widths=[max(1.5,.9*len(g)+.6) for g in groups]
    width_min=max(4.5,sum(minimum_widths))
    width=max(width_min,math.sqrt(net*1.25))
    width=min(width,net/5.6)
    if width<width_min-1e-8:
        return None,['template_capacity_failure_no_area_or_H7_repair']
    depth=net/width;natural_depth=depth-3.0
    spare=width-sum(minimum_widths)
    weights=[max(1,len(g)) for g in groups]
    widths=[minimum_widths[i]+spare*weights[i]/sum(weights) for i in range(rooms)]
    spaces=[];windows=[];doors=[];cursor=0
    for i,(g,w) in enumerate(zip(groups,widths),1):
        end=width if i==rooms else cursor+w
        name=f'natural_{i}';rect=[cursor,3.0,end,depth]
        beds=[{'member_id':member,'rect_m':[cursor+.3+j*.9,depth-2,cursor+.3+(j+1)*.9,depth]} for j,member in enumerate(g)]
        spaces.append({'name':name,'kind':'natural_room','rect_m':rect,'member_ids_sleeping':g,
                       'bed_footprints':beds,'function_design':'sleep_and_flexible_activity' if g else 'multipurpose'})
        # Each window stays on one complete host edge; no grid-fragment splitting.
        center=cursor+w/2
        windows.append({'space':name,'edge':'y='+str(depth),'span_m':[center-.4,center+.4],'height_m':1.2,'sill_m':.9})
        doors.append({'from':'corridor','to':name,'edge':'y=3.0','span_m':[center-.4,center+.4]})
        cursor=end
    kitchen_width=max(1.5,width*.22);bath_width=max(1.2,width*.18);hall_start=kitchen_width+bath_width
    # Three service partitions use the full rectangle, with no unaccounted cells.
    spaces += [
        {'name':'kitchen','kind':'kitchen','rect_m':[0,0,kitchen_width,2]},
        {'name':'bathroom','kind':'bath_toilet','rect_m':[kitchen_width,0,hall_start,2]},
        {'name':'living_hall','kind':'hall_not_H7','rect_m':[hall_start,0,width,2]},
        {'name':'corridor','kind':'circulation','rect_m':[0,2,width,3]}
    ]
    for s in spaces[-4:-1]:
        x0,_,x1,_=s['rect_m'];center=(x0+x1)/2
        doors.append({'from':s['name'],'to':'corridor','edge':'y=2.0','span_m':[center-.4,center+.4]})
    for s in [spaces[-4],spaces[-2]]:
        x0,_,x1,_=s['rect_m'];center=(x0+x1)/2
        windows.append({'space':s['name'],'edge':'y=0','span_m':[center-.4,center+.4],'height_m':1.2,'sill_m':.9})
    doors.append({'from':'entry','to':'corridor','edge':'x=0','span_m':[2.1,2.9],
                  'thermal_status':('explicit_exterior_door' if p['wall_boundaries']['west']=='Outdoors' else
                    'adjacent_conditioned_common_corridor_proxy_not_explicit_external_aperture')})
    layout={'schema':'eb.closed_rectangular_layout.v1','gross_H6_m2':area,'net_proxy_m2':net,
        'gross_minus_zone_floor_area_m2':area-net,'gross_residual_identity':'unmodeled wall/common-area bridge, not observed decomposition',
        'envelope_rect_m':[0,0,width,depth],'spaces':spaces,'windows':windows,'doors':doors,
        'H7_materialized_natural_rooms':rooms,'sleep_assignment_evidence':'declared_input_groups; individual0.9x2m berths are capacity design',
        'corridor_width_m':1.0,'capacity_rule':'natural_depth>=2.6m; group berths0.9x2m +0.6m width margin; service widths are experimental',
        'building_code_certified':False,'layout_observed':False,'entry_and_egress_code_validated':False}
    decision(trace,'zone_floor_area',net,'derived_design',['housing.H6_building_area_m2','model_policy.gross_to_zone_floor_ratio'],
        'zone area = H6 x explicitly declared net ratio',['inverse1.33 is not an official forward gross-to-usable measurement'])
    decision(trace,'H7_and_service_zones',{'natural':rooms,'service':4},'designed',['housing.H7_natural_rooms_exact'],
        'H7 only natural rooms; kitchen/bath/hall/corridor are separate model zones',['thermal zone count is H7+4, never H7 itself'])
    decision(trace,'rectangular_layout',{'width_m':width,'depth_m':depth},'designed',
        ['housing.sleep_groups','zone_floor_area'],'closed rectangle with resident berths and corridor; retain area and H7 on failure',
        ['not observed dwelling shape','furniture/daylight/egress/code validation remains separate'])
    return layout,[]

def layout_checks(item,layout):
    errors=[];spaces=layout['spaces'];net=layout['net_proxy_m2']
    area=0;bed_members=[]
    for s in spaces:
        x0,y0,x1,y1=s['rect_m'];area+=(x1-x0)*(y1-y0)
        if min(x1-x0,y1-y0)<.01:errors.append('sub1cm_space')
        for bed in s.get('bed_footprints',[]):
            bed_members.append(bed['member_id'])
            a,b,c,d=bed['rect_m']
            if not(x0-1e-6<=a<c<=x1+1e-6 and y0-1e-6<=b<d<=y1+1e-6):errors.append('bed_outside_room')
        beds=s.get('bed_footprints',[])
        if sorted(b['member_id'] for b in beds)!=sorted(s.get('member_ids_sleeping',[])):errors.append('room_bed_members_mismatch')
        for i,a in enumerate(beds):
            for b in beds[i+1:]:
                ra,rb=a['rect_m'],b['rect_m']
                if min(ra[2],rb[2])-max(ra[0],rb[0])>1e-7 and min(ra[3],rb[3])-max(ra[1],rb[1])>1e-7:errors.append('overlapping_beds')
    for i,a in enumerate(spaces):
        for b in spaces[i+1:]:
            ra,rb=a['rect_m'],b['rect_m']
            overlap=max(0,min(ra[2],rb[2])-max(ra[0],rb[0]))*max(0,min(ra[3],rb[3])-max(ra[1],rb[1]))
            if overlap>1e-7:errors.append('overlapping_spaces')
    if abs(area-net)>1e-6:errors.append('zone_area_not_closed')
    if sum(s['kind']=='natural_room' for s in spaces)!=item['housing']['H7_natural_rooms_exact']:errors.append('H7_changed')
    if sorted(bed_members)!=sorted(item['family']['resident_member_ids']):errors.append('bed_members_not_exact_resident_partition')
    graph={s['name']:set() for s in spaces};graph['entry']=set()
    for d in layout['doors']:
        if d['from'] not in graph or d['to'] not in graph:errors.append('door_connects_unknown_space');continue
        graph[d['from']].add(d['to']);graph[d['to']].add(d['from'])
    reached=set();todo=['entry']
    while todo:
        name=todo.pop()
        if name not in reached:reached.add(name);todo.extend(graph[name]-reached)
    if reached!=set(graph):errors.append('space_not_connected_to_entry')
    return sorted(set(errors))
