"""Place traceable reference worktop/device kernels in the same checked world.

Partial inventoried experimental ports are not complete real household assets.
Idle washing, label-average refrigeration and declared standby tank scenarios
are explicit, rather than inferred daily routines or device peak load truth.
"""
import collections,copy,math,re
from common import *
from shapely.geometry import box,Point
from shapely.ops import unary_union
from verify_sleep import idf_doors
from assemble_worlds import obj

WORKTOP_SOURCE='https://www.ikea.com/at/en/p/lilltraesk-worktop-white-laminate-00479874/'
SIZES={'worktop':(1.23,.635,0.),'washer':(.596,.637,1.055-.637),'refrigerator':(.640,.682,0.),'water_heater':(.833,.443,0.)}
def parse(p):return [[v.strip() for v in q.split(',')] for q in re.sub(r'!.*','',Path(p).read_text()).split(';') if q.strip()]
def reach(room,door,obstacles,site,c=.6):
 radius=c/2;boundary=box(*room['usable_rect_m']);free=boundary.buffer(-radius,join_style=2).difference(unary_union([box(*b).buffer(radius,join_style=2) for b in obstacles]));parts=[free] if free.geom_type=='Polygon' else [g for g in getattr(free,'geoms',[]) if g.geom_type=='Polygon'];x0,y0,x1,y1=room['usable_rect_m']
 xs=[v[0] for v in door];ys=[v[1] for v in door]
 if max(xs)-min(xs)>.1:
  lo=max(min(xs)+radius,x0+radius);hi=min(max(xs)-radius,x1-radius);north=abs(ys[0]-y1)<abs(ys[0]-y0);yy=y1-radius-1e-7 if north else y0+radius+1e-7;entries=[Point(lo+(hi-lo)*t,yy) for t in [0,.25,.5,.75,1]] if lo<=hi else []
 else:
  lo=max(min(ys)+radius,y0+radius);hi=min(max(ys)-radius,y1-radius);east=abs(xs[0]-x1)<abs(xs[0]-x0);xx=x1-radius-1e-7 if east else x0+radius+1e-7;entries=[Point(xx,lo+(hi-lo)*t) for t in [0,.25,.5,.75,1]] if lo<=hi else []
 return any(g.buffer(1e-7).covers(Point(*site)) and any(g.buffer(1e-6).covers(p) for p in entries) for g in parts)
def place(room,door,kind,occupied,protected_sites=()):
 W,D,extra=SIZES[kind];x0,y0,x1,y1=room['usable_rect_m'];wallgap=.10 if kind=='refrigerator' else .025;c=.6;radius=c/2
 for orientation in ['north','south','east','west']:
  dx,dy=(W,D) if orientation in ['north','south'] else (D,W)
  for ax,ay in [(0,0),(1,0),(0,1),(1,1),(.5,0),(.5,1),(0,.5),(1,.5)]:
   x=x0+wallgap+ax*(x1-x0-dx-2*wallgap);y=y0+wallgap+ay*(y1-y0-dy-2*wallgap);body=[x,y,x+dx,y+dy]
   if not box(x0,y0,x1,y1).buffer(1e-8).covers(box(*body)):continue
   envelope=body[:]
   if orientation=='north':envelope[3]+=extra;site=[(x+x+dx)/2,envelope[3]+radius+1e-5]
   elif orientation=='south':envelope[1]-=extra;site=[x+dx/2,envelope[1]-radius-1e-5]
   elif orientation=='east':envelope[2]+=extra;site=[envelope[2]+radius+1e-5,y+dy/2]
   else:envelope[0]-=extra;site=[envelope[0]-radius-1e-5,y+dy/2]
   if not box(x0,y0,x1,y1).buffer(1e-8).covers(box(*envelope)):continue
   if any(box(*envelope).intersection(box(*o)).area>1e-8 for o in occupied):continue
   if reach(room,door,occupied+[envelope],site) and all(reach(room,door,occupied+[envelope],oldsite) for oldsite in protected_sites):return {'kind':kind,'room_id':room['room_id'],'body_rect_m':body,'operation_envelope_rect_m':envelope,
     'front_orientation':orientation,'reachable_operator_center_m':site,'clearance_design_m':c,'wall_gap_reference_m':wallgap,
     'reference_dimension_source':WORKTOP_SOURCE if kind=='worktop' else 'DEVICE_MODEL_CATALOG.json in sealedV9',
     'fridge_door_swing_and_heater_wall_structural_mount_not_validated':kind in ['refrigerator','water_heater']}
 return None
def model_rows(instance,hid):
 kind=instance['kind'];rid=instance['room_id'];name=instance['instance_reference_ID'];sname=name+'_schedule'
 if kind=='washer':
  return [['Schedule:Constant',sname,'',0.],obj('ElectricEquipment',{'name':name,'zone_or_zonelist_or_space_or_spacelist_name':rid,'schedule_name':sname,'design_level_calculation_method':'EquipmentLevel',
   'design_level':.72*1000/(159/60),'fraction_latent':0.,'fraction_radiant':0.,'fraction_lost':.8,'end_use_subcategory':'ReferenceWashOnly'}),
   ['Output:Variable',name,'Electric Equipment Electricity Energy','Hourly']]
 if kind=='refrigerator':
  return [['Schedule:Constant',sname,'',1.],obj('ElectricEquipment',{'name':name,'zone_or_zonelist_or_space_or_spacelist_name':rid,'schedule_name':sname,'design_level_calculation_method':'EquipmentLevel',
   'design_level':.65*1000/24,'fraction_latent':0.,'fraction_radiant':.2,'fraction_lost':0.,'end_use_subcategory':'ReferenceFridgeLabelMean'}),
   ['Output:Variable',name,'Electric Equipment Electricity Energy','Hourly']]
 if kind=='water_heater':
  return [['Schedule:Constant',sname,'',55.],['Schedule:Constant',name+'_cold','',15.],
   obj('WaterHeater:Mixed',{'name':name,'tank_volume':.060,'setpoint_temperature_schedule_name':sname,'deadband_temperature_difference':2.,'maximum_temperature_limit':75.,
    'heater_control_type':'Cycle','heater_maximum_capacity':3300.,'heater_fuel_type':'Electricity','heater_thermal_efficiency':1.,
    'off_cycle_parasitic_fuel_consumption_rate':0.,'on_cycle_parasitic_fuel_consumption_rate':0.,'ambient_temperature_indicator':'Zone','ambient_temperature_zone_name':rid,
    'off_cycle_loss_coefficient_to_ambient_temperature':1.5,'off_cycle_loss_fraction_to_zone':1.,'on_cycle_loss_coefficient_to_ambient_temperature':1.5,'on_cycle_loss_fraction_to_zone':1.,
    'peak_use_flow_rate':0.,'cold_water_supply_temperature_schedule_name':name+'_cold','end_use_subcategory':'ReferenceTankStandby'}),
   ['Output:Variable',name,'Water Heater Electricity Energy','Hourly'],['Output:Variable',name,'Water Heater Tank Temperature','Hourly']]
 return []
def main():
 guard();records=read(OUT/'JOINT_WORLD_BINDINGS.json')['records'];specs={x['household_id']:x for x in read(V9/'PRODUCTION_REFERENCE1000.json')['households']};results=[];counts=collections.Counter()
 (OUT/'service_worlds').mkdir(exist_ok=True);(OUT/'service_idfs').mkdir(exist_ok=True)
 for rec in records:
  if not rec['assembled']:continue
  case=read(OUT/rec['world_path']);w=case['world'];hid=rec['household_id'];f=w['stock_reference_features'];rows=parse(OUT/rec['IDF_path']);doors=idf_doors(OUT/rec['IDF_path']);rooms={r['room_id']:r for r in w['rooms']};occupied=collections.defaultdict(list)
  for fr in w['sleep_reference']['frames']:occupied[fr['room_id']].append(fr['outer_rect_m'])
  fixtures=[];ports=[];held=[]
  for room in w['rooms']:
   if room['current_function'] in ['exclusive_cooking_room','shared_cooking_room']:
    fixture=place(room,doors[room['room_id']],'worktop',occupied[room['room_id']])
    if fixture:fixtures.append(fixture);occupied[room['room_id']].append(fixture['operation_envelope_rect_m']);counts['kitchen_worktop_witness']+=1
    else:held.append({'class':'kitchen_worktop','reason':'finite_no_geometric_witness'});counts['kitchen_worktop_no_witness']+=1
  candidates=collections.defaultdict(list)
  for report in specs[hid]['device_reports']:
   for port in report['reference_model_candidates']:candidates[port['port']].append(report['report_reference_id'])
  # Only one experimental covered port of each kind is instantiated. Positive
  # source reports and unresolved extra hardware remain in the original ledger.
  for portname,report_ids in candidates.items():
   if portname.startswith('Haier_KFR'):
    held.append({'port':portname,'report_refs':report_ids,'reason':'rated_point_not_full_HVAC_electric_model;noIdealLoads_substitution'});counts['AC_rated_only_held']+=1;continue
   kind='washer' if portname.startswith('Miele') else 'water_heater' if portname.startswith('Haier_ES') else 'refrigerator'
   if kind in ['washer','water_heater'] and f['piped_water']=='absent':held.append({'port':portname,'reason':'supply_pressure_and_alternative_supply_not_instantiated'});counts['no_piped_water_held']+=1;continue
   if kind=='water_heater' and f['bathing_hot_water']!='self_installed_heater':held.append({'port':portname,'reason':'official_reference_bath_service_not_personal_heater'});counts['bath_service_conflict_held']+=1;continue
   room_choices=[r for r in w['rooms'] if r['room_id'] in ['utility_niche','dry_service_niche','kitchen','washroom'] and hid in r['using_household_ids']]
   if kind=='water_heater':room_choices.sort(key=lambda r:(r['room_id']!='washroom',r['room_id']))
   else:room_choices.sort(key=lambda r:(r['room_id'] not in ['utility_niche','dry_service_niche'],r['room_id']))
   fitted=None
   for room in room_choices:
    fitted=place(room,doors[room['room_id']],kind,occupied[room['room_id']],
      [x['reachable_operator_center_m'] for x in fixtures+ports if x['room_id']==room['room_id']])
    if fitted:break
   if fitted is None:held.append({'port':portname,'reason':'finite_no_nonoverlap_door_access_footprint_witness'});counts[kind+'_footprint_held']+=1;continue
   instance={**fitted,'instance_reference_ID':hid+'_'+kind+'_covered_reference','source_report_reference_IDs':report_ids,'parameter_port':portname,
    'physical_device_identity_at_source_observed':False,'reference_installation_is_declared_design':True,
    'full_household_device_count_remains_unknown':True,'owner_and_meter_context':hid,'private_meter_not_derived_from_area_or_q':True,
    'manual_permission_and_presence_observed':None,'baseline_state':'idle_no_inferred_wash_job' if kind=='washer' else 'label_mean_constant' if kind=='refrigerator' else 'standby55C_UA1_5_no_inferred_draw',
    'source_full_performance_and_actual_duty_calibrated':False,'experimental_kernel_not_same_source_hardware_or_pop_frequency':True}
   if kind=='water_heater':instance['mounted_height_design_m']=2.;instance['outer_height_m']=.453;instance['structural_support_verified']=False
   ports.append(instance);occupied[instance['room_id']].append(instance['operation_envelope_rect_m']);rows+=model_rows(instance,hid);counts[kind+'_reference_ports']+=1
  # Recheck front access of every fixture against all later added obstacles.
  invalid=[]
  for device in fixtures+ports:
   if not reach(rooms[device['room_id']],doors[device['room_id']],occupied[device['room_id']],device['reachable_operator_center_m']):invalid.append(device.get('instance_reference_ID',device['kind']))
  if invalid:raise RuntimeError('later_device_blocks_existing_front_access:'+hid+':'+str(invalid))
  if ports:rows.append(['Output:Meter','Electricity:Facility','Hourly'])
  if any(x['kind'] in ['washer','refrigerator'] for x in ports):rows.append(['Output:Meter','InteriorEquipment:Electricity','Hourly'])
  if any(x['kind']=='water_heater' for x in ports):rows.append(['Output:Meter','WaterSystems:Electricity','Hourly'])
  body={**case,'service_model':{'kitchen_worktop_references':fixtures,'instantiated_reference_ports':ports,'held_candidates':held,
   'covered_inventory_is_partial':True,'unmodelled_auxiliary_and_household_devices_not_assumed_zero':True,
   'facility_meter_measures_only_modelled_reference_ports_not_full_household':True,
   'no_hot_water_daily_draw_or_wash_clock_inferred_from_historical_bins':True,'People_HVAC_lighting_cooking_infiltration_and_care_not_complete':True}}
  path=OUT/'service_idfs'/(hid+'.idf');path.write_text('! Joint housing plus explicitly partial reference service kernels.\n'+'\n'.join(',\n  '.join(str(v) for v in row)+';' for row in rows)+'\n');wp=OUT/'service_worlds'/(hid+'.json');save(wp,body)
  results.append({**rec,'service_world_path':str(wp.relative_to(OUT)),'service_world_sha256':sha(wp),'service_IDF_path':str(path.relative_to(OUT)),
    'service_IDF_sha256':sha(path),'reference_ports':len(ports),'kitchen_worktop_found':f['kitchen']=='none' or bool(fixtures),'all_declared_front_access_rechecked':True,
    'unresolved_whole_home_inventory_or_daily_operating_context':True,'complete_household_IDF':False})
  counts['households_with_reference_ports']+=bool(ports)
 save(OUT/'SERVICE_PORT_BINDINGS.json',{'records':results,'summary':dict(counts),'reference_worktop_dimensions_m':[1.23,.635],'worktop_source':WORKTOP_SOURCE,
  'service_subset_not_complete_household_model':True,'complete_household_IDFs':0})
 print(json.dumps(dict(counts),ensure_ascii=False))
if __name__=='__main__':main()
