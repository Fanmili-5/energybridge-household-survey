"""Joint geometric grammar with separate area allocation and facility rights.

Shape/minimum choices are declared design, not inferred dwelling floorplans or
stock proportions. Every reference area share is explicit and conserves the
whole physical footprint. Other household residents remain unknown.
"""
import math
from scipy.optimize import brentq
from shapely.geometry import box
from shapely.ops import unary_union
from common import *

SHAPES=[(2.2,2.5,1.2,4.,.5),(2.6,2.5,1.0,3.6,.5),(2.8,2.8,1.0,3.5,.5),
 (3.,2.3,1.0,3.5,.5),(2.4,3.2,1.0,3.4,.5),(3.2,3.,.9,3.4,.5),
 (2.6,2.5,1.0,3.6,.6),(2.8,2.8,1.0,3.5,.6),(3.,3.2,.9,3.2,.5)]
STUDIOS=[(4.,3.,1.2,2.,.5),(4.5,3.2,1.0,1.9,.5),(5.,3.,1.,1.8,.55),
 (3.5,4.,1.,2.,.5),(4.8,3.6,.9,1.8,.5),(5.5,3.,.9,1.8,.55)]

def make(profile,facet,assembly,s,shape,check=True):
 hid=profile['slot_id'];r=profile['housing']['H7_independent_natural_rooms_design'];q=profile['housing']['shared_household_count_design'];te,ti=assembly['exterior_thickness_m'],assembly['interior_thickness_m']
 hhs=[hid]+[hid+f'-aux-{i:02}' for i in range(1,q)];external=hid+'-external-kitchen-user';rooms=[]
 studio=r==1 and q==1
 if studio:
  width,depth,corr,service,kfrac=shape;W=width*s+2*te;D=(depth+corr+service)*s+2*ti+2*te
  y1=te+depth*s+ti/2;y2=y1+corr*s+ti;xk=te+width*s*kfrac+ti/2
  declarations=[('combined_bed_living','bedroom',[0,0,W,y1],[hid]),('corridor','corridor',[0,y1,W,y2],hhs),
   ('kitchen','kitchen',[0,y2,xk,D],hhs),('toilet','toilet',[xk,y2,W,D],hhs)]
 else:
  bay,depth,corr,service,kfrac=shape;count=r*q;cols=math.ceil(count/2);private_width=cols*bay*s+(cols-1)*ti
  W=private_width+service*s+ti+2*te;D=(depth*2+corr)*s+2*ti+2*te;xp=te+private_width+ti/2;y1=te+depth*s+ti/2;y2=y1+corr*s+ti
  declarations=[];index=0
  for num,y0,y3 in [(math.ceil(count/2),0,y1),(count//2,y2,D)]:
   width=(private_width-(num-1)*ti)/num;breaks=[0]+[te+j*width+(j-.5)*ti for j in range(1,num)]+[xp]
   for j in range(num):
    owner=hhs[index//r];index+=1;declarations.append((f'private_{index:02}','bedroom',[breaks[j],y0,breaks[j+1],y3],[owner]))
  xk=xp+ti/2+service*s*kfrac
  declarations += [('corridor','corridor',[0,y1,W,y2],hhs),('living_hall','hall',[xp,0,W,y1],hhs),
   ('kitchen','kitchen',[xp,y2,xk,D],hhs),('toilet','toilet',[xk,y2,W,D],hhs)]
 for old_name,kind,rect,users in declarations:
  name=old_name;users=list(users);shares={h:1/len(users) for h in users};function=kind
  if old_name=='kitchen':
   if facet['kitchen']=='exclusive':users=[hid];shares={hid:1.};function='exclusive_cooking_room'
   elif facet['kitchen']=='shared':
    users=hhs[:] if q>1 else [hid,external];shares={h:1/len(users) for h in users};function='shared_cooking_room'
   else:name='utility_niche';kind='non_H7_service';function='non_cooking_utility_niche'
  if old_name=='toilet':
   name='washroom' if facet['toilet']!='none' or facet['bathing_hot_water']!='none' else 'dry_service_niche';kind='non_H7_service';function='sanitary_service_space' if name=='washroom' else 'non_sanitary_service_niche'
  x0,y0,x1,y3=rect
  net=[x0+(te if abs(x0)<1e-8 else ti/2),y0+(te if abs(y0)<1e-8 else ti/2),x1-(te if abs(x1-W)<1e-8 else ti/2),y3-(te if abs(y3-D)<1e-8 else ti/2)]
  thermal=[x0+(te/2 if abs(x0)<1e-8 else 0),y0+(te/2 if abs(y0)<1e-8 else 0),x1-(te/2 if abs(x1-W)<1e-8 else 0),y3-(te/2 if abs(y3-D)<1e-8 else 0)]
  if net[2]<=net[0] or net[3]<=net[1]:raise ValueError('nonpositive_usable_extent')
  area=(x1-x0)*(y3-y0);usable=(net[2]-net[0])*(net[3]-net[1]);mina=12 if name=='combined_bed_living' else 5 if kind=='bedroom' else 4 if old_name=='kitchen' and facet['kitchen']!='none' else 2.5 if old_name=='toilet' and function=='sanitary_service_space' else 10 if old_name=='living_hall' else 0
  rooms.append({'room_id':name,'legacy_room_id':old_name,'census_room_class':kind,'using_household_ids':users,
   'area_allocation_fractions':shares,'energy_meter_allocation_fractions':None,'gross_rect_m':rect,'usable_rect_m':net,'thermal_centerline_rect_m':thermal,
   'gross_area_m2':area,'usable_area_m2':usable,'thermal_reference_area_m2':(thermal[2]-thermal[0])*(thermal[3]-thermal[1]),
   'legacy_min_area_diagnostic_m2':mina,'legacy_min_area_diagnostic_met':usable+1e-7>=mina,
   'legacy_area_threshold_is_not_physical_or_census_admission':True,'current_function':function,'classification_evidence':'declared_reference_architecture_and_facility_rights_not_observed_home',
   'census_toilet_facility_reference_present':old_name=='toilet' and facet['toilet']!='none','physical_toilet_fixture_geometry_instantiated':False,'toilet_facility_reference_class':facet['toilet'] if old_name=='toilet' else None,
   'bathing_service_type':facet['bathing_hot_water'] if old_name=='toilet' else None})
 polygons=[box(*rr['gross_rect_m']) for rr in rooms];union=unary_union(polygons);assert abs(sum(p.area for p in polygons)-union.area)<1e-7 and abs(union.area-W*D)<1e-7
 allocated={h:sum(rr['gross_area_m2']*rr['area_allocation_fractions'].get(h,0) for rr in rooms) for h in set(h for rr in rooms for h in rr['area_allocation_fractions'])}
 assert abs(sum(allocated.values())-W*D)<1e-7
 corridor=next(rr for rr in rooms if rr['room_id']=='corridor');access=[]
 for rr in rooms:
  if rr['room_id']=='corridor':continue
  segment=box(*rr['gross_rect_m']).boundary.intersection(box(*corridor['gross_rect_m']).boundary)
  if segment.length<.9:raise ValueError('no_reference_portal')
  access.append({'from':rr['room_id'],'to':'corridor','width_design_m':.8,'height_design_m':2.,'common_edge':list(segment.coords),'evidence':'declared_new_portal'})
 return {'target_household_id':hid,'target_H7':r,'target_H6_unrounded_m2':allocated[hid],'whole_unit_building_area_m2':W*D,
  'rooms':rooms,'households':[{'household_id':h,'is_population_target':h==hid,'resident_count_observed':None if h!=hid else 'join_fixed_reference_roster','allocated_building_area_m2':a} for h,a in allocated.items()],
  'metric_outer_rect_m':[0,0,W,D],'shared_household_count_design':q,'household_level_q_is_not_kitchen_sharing_count':True,
  'nonresident_external_kitchen_user_context':external if external in allocated else None,'all_area_allocations_are_declared_reference_not_registered_property_shares':True,
  'usable_total_area_m2':sum(rr['usable_area_m2'] for rr in rooms),'thermal_reference_floor_area_m2':sum(rr['thermal_reference_area_m2'] for rr in rooms),
  'wall_footprint_area_m2':W*D-sum(rr['usable_area_m2'] for rr in rooms),'allocated_gross_area_by_context_household_m2':allocated,
  'access':access,'layout_shape_parameters':list(shape),'uniform_room_scale':s,'source_native_floorplan_preserved':False,
  'census_H7_counting_rule':'target natural-bedroom design count;shared halls/corridor/wet/utility niches excluded by declared original architecture',
  'common_private_area_shares_not_energy_meter_or_control_rights':True,'complete_household_energy_world':False,'actor_ready':False}

def sized(profile,facet,assembly,shape):
 target=profile['housing']['H6_census_building_area_design_m2'];lo=.1
 while lo<2:
  try:a=make(profile,facet,assembly,lo,shape,False)['target_H6_unrounded_m2'];break
  except ValueError:lo+=.025
 else:raise ValueError('shape_domain_empty')
 if a>target+1e-7:raise ValueError('fixed_H6_below_geometry_domain')
 hi=max(2,lo*2)
 while make(profile,facet,assembly,hi,shape,False)['target_H6_unrounded_m2']<target:hi*=2
 s=brentq(lambda z:make(profile,facet,assembly,z,shape,False)['target_H6_unrounded_m2']-target,lo,hi,xtol=1e-12)
 w=make(profile,facet,assembly,s,shape,True);assert abs(w['target_H6_unrounded_m2']-target)<1e-6
 return w
