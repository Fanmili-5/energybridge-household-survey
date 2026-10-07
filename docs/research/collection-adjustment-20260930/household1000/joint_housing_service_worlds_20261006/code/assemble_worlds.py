"""Compile joint facility/area/geometry/exposure worlds; keep failures explicit.
Source routing is deterministic experimental reference, not stock weighting.
"""
import collections,copy,math,sys
from common import *
from geometry import make,sized,SHAPES,STUDIOS
import compile_reference_idfs as compiler
from mixed_sleep import choose
SCHEMA=read('/Applications/EnergyPlus-24-1-0/Energy+.schema.epJSON')
def obj(kind,values):
 fields=SCHEMA['properties'][kind]['legacy_idd']['fields'];last=max(fields.index(k) for k in values)
 return [kind]+[values.get(f,'') for f in fields[:last+1]]
def exposure(rows,world,facet,a,side_exposed=False,soil_factor=1.,initial=20.):
 rr=copy.deepcopy(rows);one=facet['building_storeys']=='one_storey';surfaces=[r for r in rr if r[0]=='BuildingSurface:Detailed']
 for r in surfaces:
  if r[2]=='Wall' and r[6]=='Adiabatic' and side_exposed:r[6:10]=['Outdoors','','SunExposed','WindExposed']
 for r in surfaces:
  if one and r[2]=='Ceiling':r[2]='Roof';r[3]=a['names']['roof'];r[6:10]=['Outdoors','','SunExposed','WindExposed']
  if one and r[2]=='Floor':
   name=r[1]+'_foundation';r[3]=a['names']['ground'];r[6:10]=['Foundation',name,'NoSun','NoWind']
   perimeter=0
   for wall in surfaces:
    if wall[4]==r[4] and wall[2]=='Wall' and wall[6]=='Outdoors':perimeter+=math.dist(list(map(float,wall[12:14])),list(map(float,wall[15:17])))
   rr += [obj('Foundation:Kiva',{'name':name,'initial_indoor_air_temperature':initial,'wall_height_above_grade':.2,'wall_depth_below_slab':0.,'footing_wall_construction_name':a['names']['exterior']}),
    obj('SurfaceProperty:ExposedFoundationPerimeter',{'surface_name':r[1],'exposed_perimeter_calculation_method':'TotalExposedPerimeter','total_exposed_perimeter':perimeter})]
 if one:rr.append(obj('Foundation:Kiva:Settings',{'soil_conductivity':1.73*soil_factor,'soil_density':1842.,'soil_specific_heat':419.,
  'ground_solar_absorptivity':.9,'ground_thermal_absorptivity':.9,'ground_surface_roughness':.03,'far_field_width':40.,
  'deep_ground_boundary_condition':'ZeroFlux','deep_ground_depth':20.,'minimum_cell_dimension':.02,'maximum_cell_growth_coefficient':1.5,'simulation_timestep':'Hourly'}))
 # Thermal air/area calculations use the declared centerline enclosure.
 # Usable furniture/activity area stays separate in the metric world, never
 # overwritten by EnergyPlus's effective centerline floor area.
 for row in rr:
  if row[0]=='Zone':row[9:11]=['Autocalculate','Autocalculate']
 used={r[3] for r in rr if r[0] in ['BuildingSurface:Detailed','FenestrationSurface:Detailed']}
 used.update(r[15] for r in rr if r[0]=='Foundation:Kiva' and len(r)>15 and r[15])
 cons=[r for r in rr if r[0]=='Construction' and r[1] in used];materials={m for r in cons for m in r[2:]}
 rr=[r for r in rr if (r[0]!='Construction' or r[1] in used) and (r[0] not in ['Material','Material:NoMass','WindowMaterial:SimpleGlazingSystem'] or r[1] in materials)]
 return rr,{'one_storey_roof_ground_executed':one,'side_party_walls_or_side_exposure':'all_outer_sides_exposed' if side_exposed else 'declared_side_party_walls_except_entry',
  'non_one_storey_actual_floor_unknown_midfloor_is_reference':not one,'Kiva_soil_conductivity_W_mK':1.73*soil_factor if one else None,
  'Kiva_soil_density_kg_m3':1842 if one else None,'Kiva_soil_specific_heat_J_kgK':419 if one else None,
  'Kiva_initial_indoor_C_design':initial if one else None,'Kiva_default_soil_is_not_Chinese_measured_soil':True,
  'Kiva_deep_boundary':'ZeroFlux_at20m_declared_reference_not_observed_water_table' if one else None,
  'thermal_Zone_area_and_air_volume':'autocalculated_from_reference_centerline_enclosure;human_usable_area_separately_retained',
  'roof_ground_native_parameters_not_asbuilt':True,'native_middle_floor_KIND5_namespace_checked':True}
def main():
 guard();pp=read(V7/'HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json')['profiles'];specs={p['household_id']:p for p in read(V9/'PRODUCTION_REFERENCE1000.json')['households']}
 (OUT/'worlds').mkdir(exist_ok=True);(OUT/'idfs').mkdir(exist_ok=True);records=[];original=compiler.assemblies
 limit=int(sys.argv[1]) if len(sys.argv)>1 else len(pp)
 try:
  for i,p in enumerate(pp[:limit]):
   hid=p['slot_id'];spec=specs[hid];f=spec['three_stock_reference_assignments']['hash_reference'];candidates=spec['reference_world_and_IDF']['regional_candidates']
   selected=min(candidates,key=lambda c:hashlib.sha256(('EB_JOINT_NATIVE_REF20261006|'+hid+'|'+c['model_key']).encode()).hexdigest())
   a=read(OUT/'assemblies'/(selected['model_key']+'.json'));assert sha(OUT/'assemblies'/(selected['model_key']+'.json'))==next(x['bundle_sha256'] for x in read(OUT/'HORIZONTAL_SOURCE_ADMISSION.json')['models'] if x['model_key']==selected['model_key'])
   compiler.assemblies=lambda a=a:a;attempts=[];found=None;shapes=STUDIOS if p['housing']['H7_independent_natural_rooms_design']==1 and p['housing']['shared_household_count_design']==1 else SHAPES
   for j,shape in enumerate(shapes):
    try:
     world=sized(p,f,a,shape);rows,meta=compiler.model(world);sleep=choose(p,world,rows,.6,False)
     if not sleep['found']:sleep=choose(p,world,rows,.6,True)
     attempts.append({'shape_index':j,'geometry_compiled':True,'sleep_witness':sleep['found']})
     if not sleep['found']:continue
     rows,boundary=exposure(rows,world,f,a);found=(world,rows,meta,sleep,boundary,j);break
    except ValueError as e:attempts.append({'shape_index':j,'reason':str(e)})
   if found is None:
    records.append({'household_id':hid,'assembled':False,'attempts':attempts,'fixed_profile_not_resampled':True,'source_reference_not_swapped_after_failure':True});continue
   world,rows,meta,sleep,boundary,j=found
   adults=[m['member_id'] for m in p['family']['members'] if m['age_years']>=18]
   world['stock_reference_features']=f;world['source_parameter_reference']=selected;world['sleep_reference']=sleep;world['boundary_reference']=boundary
   world['operator_context']={'adult_reference_candidates':adults,'observed_permission':None,'observed_presence':None,'default_manual_action_enabled':False,
    'no_adult_requires_explicit_nonresident_assistance_context':not bool(adults),'nonresident_assistance_not_silently_created':True}
   world['housing_source_is_assigned_marginal_not_source_family_tenure_observation']=True
   meta['old_floor_and_side_neighbor_policy_superseded_by']=boundary;meta['source_original_thermal_absorptance_preserved']=False
   meta['old_zone_net_area_and_volume_policy_superseded_by']='thermal_enclosure_autocalculate;usable_world_area_for_people_furniture_separate'
   meta['surfaces']=[{'name':z[1],'type':z[2],'construction':z[3],'zone':z[4],'bc':z[6],'peer':z[7],
      'vertices':[list(map(float,z[k:k+3])) for k in range(12,len(z),3)]} for z in rows if z[0]=='BuildingSurface:Detailed']
   meta['floor_policy_scope']='native KIND3 roof and KIND4 ground for one-storey;explicit RC reference only on adiabatic midfloor slabs'
   meta['absorption_roughness_are_reference_parameters_not_native_measurements']=True
   case={'household_id':hid,'province':p['province'],'N':p['family']['resident_count'],'G':p['family']['generation_count'],
    'fixed_H6_m2':p['housing']['H6_census_building_area_design_m2'],'fixed_H7':p['housing']['H7_independent_natural_rooms_design'],
    'source_profile_sha256':sha(V7/'HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json'),'world':world,'source_bundle_path':str(OUT/'assemblies'/(selected['model_key']+'.json')),
    'source_bundle_sha256':sha(OUT/'assemblies'/(selected['model_key']+'.json')),'assembly_attempts':attempts,'successful_shape_index':j,
    'stock_control_individual_assignments_are_reference_not_observed_home':True,'native_code_epoch_not_observed_house_build_year':True,
    'catalogue_count_not_used_as_population_weight':True,'source_routing_hash_is_experimental_selection_not_empirical_city_probability':True,
    'compiler_meta':meta,'whole_home_devices_people_and_services_complete':False,'actor_ready':False}
   path=OUT/'idfs'/(hid+'.idf');path.write_text('! Joint reference housing/facilities/exposure;not as-built or complete occupied home.\n'+compiler.dump(rows));save(OUT/'worlds'/(hid+'.json'),case)
   records.append({'household_id':hid,'assembled':True,'world_path':'worlds/'+hid+'.json','world_sha256':sha(OUT/'worlds'/(hid+'.json')),
    'IDF_path':str(path.relative_to(OUT)),'IDF_sha256':sha(path),'source_model_key':selected['model_key'],'weather':selected['weather'][0],
    'shape_index':j,'sleep0_6m_found':True,'temporary_hall_sleepers':sleep['temporary_hall_sleepers'],
    'one_storey_roof_ground':boundary['one_storey_roof_ground_executed'],'no_adult_operator':not bool(adults),
    'whole_home_IDF_complete':False,'population_weight':p['relative_population_weight']})
   if (i+1)%100==0:print(json.dumps({'profiles_processed':i+1,'assembled':sum(x['assembled'] for x in records)},ensure_ascii=False),flush=True)
 finally:compiler.assemblies=original
 save(OUT/'JOINT_WORLD_BINDINGS.json',{'records':records,'profiles_processed':len(records),'assembled':sum(r['assembled'] for r in records),
  'failures_retained':sum(not r['assembled'] for r in records),'geometry_shape_reference_not_population_frequency':True,'old_profile_N_G_H6_H7_unchanged':True,
  'complete_household_IDFs':0,'scientific_population_stock_or_human_benchmark_admitted':False})
 print(json.dumps({'processed':len(records),'assembled':sum(r['assembled'] for r in records),'failed':sum(not r['assembled'] for r in records)},ensure_ascii=False))
if __name__=='__main__':main()
