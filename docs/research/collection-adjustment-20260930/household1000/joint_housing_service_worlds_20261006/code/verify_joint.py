"""Independent checks on exported world geometry, IDF boundaries and fixtures.
Does not import assembler/geometry/furniture/fixture placement generators.
"""
import collections,copy,math,re
from common import *
from shapely.geometry import box,Point
from shapely.ops import unary_union
from verify_sleep import check_case,idf_doors
def parse(p):return [[v.strip() for v in q.split(',')] for q in re.sub(r'!.*','',Path(p).read_text()).split(';') if q.strip()]
def front_access(room,door,obstacles,point,clearance):
 radius=clearance/2;boundary=box(*room['usable_rect_m']);free=boundary.buffer(-radius,join_style=2).difference(unary_union([box(*r).buffer(radius,join_style=2) for r in obstacles]));pieces=[free] if free.geom_type=='Polygon' else [g for g in getattr(free,'geoms',[]) if g.geom_type=='Polygon']
 x0,y0,x1,y1=room['usable_rect_m'];horizontal=max(v[0] for v in door)-min(v[0] for v in door)>.1
 if horizontal:
  lo=max(min(v[0] for v in door)+radius,x0+radius);hi=min(max(v[0] for v in door)-radius,x1-radius);y=sum(v[1] for v in door)/len(door);yy=y1-radius-1e-7 if abs(y-y1)<abs(y-y0) else y0+radius+1e-7
  entries=[Point(lo+(hi-lo)*t,yy) for t in [0,.25,.5,.75,1]] if lo<=hi else []
 else:
  lo=max(min(v[1] for v in door)+radius,y0+radius);hi=min(max(v[1] for v in door)-radius,y1-radius);x=sum(v[0] for v in door)/len(door);xx=x1-radius-1e-7 if abs(x-x1)<abs(x-x0) else x0+radius+1e-7
  entries=[Point(xx,lo+(hi-lo)*t) for t in [0,.25,.5,.75,1]] if lo<=hi else []
 return any(g.buffer(1e-6).covers(Point(*point)) and any(g.buffer(1e-6).covers(p) for p in entries) for g in pieces)
def errors(case,rows,profile,doors):
 w=case['world'];hid=case['household_id'];issues=[];rr=w['rooms'];index={r['room_id']:r for r in rr};f=w['stock_reference_features'];target=case['fixed_H6_m2'];s=case.get('service_model',{});fixtures=s.get('kitchen_worktop_references',[])+s.get('instantiated_reference_ports',[])
 gross=[box(*r['gross_rect_m']) for r in rr]
 if abs(sum(g.area for g in gross)-unary_union(gross).area)>1e-6:issues.append('physical_room_overlap')
 outer=box(*w['metric_outer_rect_m'])
 if outer.symmetric_difference(unary_union(gross)).area>1e-6:issues.append('physical_whole_footprint_not_partitioned')
 areas=collections.defaultdict(float)
 for r in rr:
  if min(r['area_allocation_fractions'].values())<0 or abs(sum(r['area_allocation_fractions'].values())-1)>1e-8:issues.append('room_area_share_not_partitioned')
  if r['energy_meter_allocation_fractions'] is not None:issues.append('area_share_used_as_energy_meter')
  for h,v in r['area_allocation_fractions'].items():areas[h]+=box(*r['gross_rect_m']).area*v
 if abs(areas[hid]-target)>1e-6 or abs(sum(areas.values())-outer.area)>1e-6:issues.append('H6_area_identity')
 if sum(r['census_room_class']=='bedroom' and r['using_household_ids']==[hid] for r in rr)!=case['fixed_H7']:issues.append('H7_target_room_count')
 cooking=[r for r in rr if 'cooking_room' in r['current_function']]
 if f['kitchen']=='none' and cooking:issues.append('none_kitchen_has_cooking_room')
 if f['kitchen']=='exclusive' and (len(cooking)!=1 or cooking[0]['using_household_ids']!=[hid] or cooking[0]['area_allocation_fractions']!={hid:1.}):issues.append('exclusive_kitchen_rights')
 if f['kitchen']=='shared' and (len(cooking)!=1 or len(cooking[0]['using_household_ids'])<2):issues.append('shared_kitchen_not_shared')
 if f['toilet']=='none' and any(r['census_toilet_facility_reference_present'] for r in rr):issues.append('none_toilet_has_declared_facility')
 if any(r['physical_toilet_fixture_geometry_instantiated'] for r in rr):issues.append('unsupported_full_toilet_fixture_claim')
 one=f['building_storeys']=='one_storey';surfaces=[r for r in rows if r[0]=='BuildingSurface:Detailed'];floor=[r for r in surfaces if r[2]=='Floor'];roof=[r for r in surfaces if r[2] in ['Ceiling','Roof']]
 if one and (any(r[6]!='Foundation' for r in floor) or any(r[6]!='Outdoors' or r[2]!='Roof' for r in roof)):issues.append('one_storey_false_midfloor_boundaries')
 if not one and any(r[6]!='Adiabatic' for r in floor+roof):issues.append('baseline_multistorey_boundary_not_declared_midfloor')
 perimeters={r[1]:float(r[3]) for r in rows if r[0]=='SurfaceProperty:ExposedFoundationPerimeter'};foundations={r[1]:r for r in rows if r[0]=='Foundation:Kiva'}
 if one:
  for floorrow in floor:
   perimeter=sum(math.hypot(float(z[15])-float(z[12]),float(z[16])-float(z[13])) for z in surfaces if z[4]==floorrow[4] and z[2]=='Wall' and z[6]=='Outdoors')
   if floorrow[7] not in foundations or abs(perimeters.get(floorrow[1],-1)-perimeter)>1e-6:issues.append('foundation_exposed_perimeter_or_object_mismatch')
  settings=next((r for r in rows if r[0]=='Foundation:Kiva:Settings'),None)
  if not settings or settings[8]!='ZeroFlux' or float(settings[9])!=20.:issues.append('uncontrolled_ground_water_or_deep_boundary')
 if any(r[0]=='Zone' and r[9:11]!=['Autocalculate','Autocalculate'] for r in rows):issues.append('thermal_enclosure_and_zone_area_mismatch')
 if case['compiler_meta']['surfaces']!=[{'name':z[1],'type':z[2],'construction':z[3],'zone':z[4],'bc':z[6],'peer':z[7],'vertices':[list(map(float,z[k:k+3])) for k in range(12,len(z),3)]} for z in surfaces]:issues.append('stale_compiler_boundary_metadata')
 sl=w['sleep_reference'];issues+=check_case(profile,w,doors,sl['frames'],sl['berths'],.6)
 if case['N']!=profile['family']['resident_count'] or case['G']!=profile['family']['generation_count']:issues.append('changed_N_or_G')
 occupied=collections.defaultdict(list)
 for frame in sl['frames']:occupied[frame['room_id']].append(frame['outer_rect_m'])
 for fixture in fixtures:occupied[fixture['room_id']].append(fixture['operation_envelope_rect_m'])
 for fixture in fixtures:
  room=index[fixture['room_id']];env=box(*fixture['operation_envelope_rect_m']);body=box(*fixture['body_rect_m'])
  if not box(*room['usable_rect_m']).buffer(1e-7).covers(env) or not env.buffer(1e-7).covers(body):issues.append('fixture_envelope_outside_room')
  dims=sorted([body.bounds[2]-body.bounds[0],body.bounds[3]-body.bounds[1]]);desired=sorted({'worktop':(1.23,.635),'washer':(.596,.637),'refrigerator':(.640,.682),'water_heater':(.833,.443)}[fixture['kind']])
  if max(abs(a-b) for a,b in zip(dims,desired))>1e-7:issues.append('fixture_manufacturer_footprint_mismatch')
  if not front_access(room,doors[fixture['room_id']],occupied[fixture['room_id']],fixture['reachable_operator_center_m'],fixture['clearance_design_m']):issues.append('fixture_front_access_blocked')
 for name,rects in occupied.items():
  for i,a in enumerate(rects):
   if any(box(*a).intersection(box(*b)).area>1e-8 for b in rects[:i]):issues.append('furniture_or_device_overlap')
 ports=s.get('instantiated_reference_ports',[]);models={r[1]:r for r in rows if r[0] in ['ElectricEquipment','WaterHeater:Mixed']}
 for port in ports:
  if port['owner_and_meter_context']!=hid or port['manual_permission_and_presence_observed'] is not None:issues.append('invented_observed_ownership_or_permission')
  if port['instance_reference_ID'] not in models:issues.append('device_port_not_in_IDF')
  if port['kind']=='water_heater' and (f['bathing_hot_water']!='self_installed_heater' or f['piped_water']!='present'):issues.append('tank_facility_conflict')
 if any(r[0]=='ZoneHVAC:IdealLoadsAirSystem' for r in rows):issues.append('IdealLoads_substituted_for_AC_electricity')
 if not ports and any(r[0]=='Output:Meter' and r[1]=='Electricity:Facility' for r in rows):issues.append('unmodelled_inventory_as_zero_household_meter')
 if w['operator_context']['default_manual_action_enabled']:issues.append('unconfirmed_manual_permission_enabled')
 return sorted(set(issues))
def main():
 guard();pp={r['slot_id']:r for r in read(V7/'HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json')['profiles']};records=read(OUT/'SERVICE_PORT_BINDINGS.json')['records'];counts=collections.Counter();fail=[];examples=[]
 for r in records:
  assert sha(OUT/r['service_world_path'])==r['service_world_sha256'] and sha(OUT/r['service_IDF_path'])==r['service_IDF_sha256']
  c=read(OUT/r['service_world_path']);rs=parse(OUT/r['service_IDF_path']);dd=idf_doors(OUT/r['service_IDF_path']);issues=errors(c,rs,pp[r['household_id']],dd)
  if issues:fail.append({'household_id':r['household_id'],'issues':issues})
  counts['joint_worlds_checked']+=1;counts['area_allocation_identity_checked']+=1;counts['sleep_berths_checked']+=len(c['world']['sleep_reference']['berths']);counts['reference_fixtures_and_ports_checked']+=len(c['service_model']['kitchen_worktop_references'])+len(c['service_model']['instantiated_reference_ports']);counts['one_storey_roof_ground_checked']+=r['one_storey_roof_ground'];counts['no_adult_default_disabled_checked']+=r['no_adult_operator']
  if r['one_storey_roof_ground'] or c['service_model']['instantiated_reference_ports']:examples.append((c,rs,pp[r['household_id']],dd))
 negative=[]
 c,rs,p,dd=next(x for x in examples if x[0]['world']['stock_reference_features']['building_storeys']=='one_storey');qq=copy.deepcopy(rs);next(r for r in qq if r[0]=='BuildingSurface:Detailed' and r[2]=='Floor')[6]='Adiabatic';negative.append({'injection':'one_storey_floor_adiabatic','detected':'one_storey_false_midfloor_boundaries' in errors(c,qq,p,dd)})
 q=copy.deepcopy(c);next(iter(q['world']['rooms']))['area_allocation_fractions'][q['household_id']]=.5;negative.append({'injection':'room_allocation_not_conserved','detected':'room_area_share_not_partitioned' in errors(q,rs,p,dd)})
 c,rs,p,dd=next(x for x in examples if x[0]['service_model']['instantiated_reference_ports']);q=copy.deepcopy(c);q['service_model']['instantiated_reference_ports'][0]['body_rect_m'][0]-=100;negative.append({'injection':'device_outside_reference_room','detected':'fixture_envelope_outside_room' in errors(q,rs,p,dd)})
 q=copy.deepcopy(c);q['service_model']['instantiated_reference_ports'][0]['owner_and_meter_context']='other';negative.append({'injection':'wrong_household_meter_owner','detected':'invented_observed_ownership_or_permission' in errors(q,rs,p,dd)})
 q=copy.deepcopy(c);q['world']['operator_context']['default_manual_action_enabled']=True;negative.append({'injection':'manual_permission_without_context','detected':'unconfirmed_manual_permission_enabled' in errors(q,rs,p,dd)})
 result={'counts':dict(counts),'failures':fail,'negative_controls':negative,'independent_exported_coordinates_IDF_and_semantics':True,
   'does_not_import_geometry_or_appliance_placement_generators':True,'body_load_care_privacy_wall_mount_and_real_stock_not_validated':True}
 save(OUT/'INDEPENDENT_JOINT_VERIFICATION.json',result);print(json.dumps({k:v for k,v in result.items() if k!='failures'},ensure_ascii=False));print('failures',fail[:5]);assert not fail and all(x['detected'] for x in negative) and len(records)==1000
if __name__=='__main__':main()
