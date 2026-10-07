"""Independent exported stress-area identities and sleep witness checks."""
import collections,copy
from common import *
from shapely.geometry import box
from shapely.ops import unary_union
from verify_sleep import check_case
def errors(r,p):
 if not r['found']:return []
 q=r['witness'];w=q['reference_world_geometry'];sl=q['sleep'];issues=check_case(p,w,q['compiled_reference_portal_vertices_by_room'],sl['frames'],sl['berths'],.6)
 rectangles=[box(*z['gross_rect_m']) for z in w['rooms']];union=unary_union(rectangles);areas=collections.defaultdict(float)
 if abs(sum(z.area for z in rectangles)-union.area)>1e-6:issues.append('gross_room_overlap')
 if union.symmetric_difference(box(*w['metric_outer_rect_m'])).area>1e-6:issues.append('gross_partition')
 for room in w['rooms']:
  if abs(sum(room['area_allocation_fractions'].values())-1)>1e-8:issues.append('room_shares')
  for hid,f in room['area_allocation_fractions'].items():areas[hid]+=box(*room['gross_rect_m']).area*f
 if abs(sum(areas.values())-union.area)>1e-6:issues.append('whole_area_identity')
 if abs(areas[r['household_id']]+r['building_common_allocation_m2']-r['fixed_census_H6_m2'])>1e-6:issues.append('fixed_H6_identity')
 if r['fixed_census_H6_m2']!=p['housing']['H6_census_building_area_design_m2']:issues.append('H6_changed')
 if sum(z['census_room_class']=='bedroom' and z['using_household_ids']==[r['household_id']] for z in w['rooms'])!=p['housing']['H7_independent_natural_rooms_design']:issues.append('H7_changed')
 return issues
def main():
 guard();p={x['slot_id']:x for x in read(V7/'HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json')['profiles']};d=read(OUT/'AREA_ALLOCATION_SENSITIVITY.json');fail=[];counts=[];example=None
 for scenario in d['stress_scenarios']:
  n=0
  for r in scenario['records']:
   assert len(scenario['records'])==1000
   if not r['found']:continue
   n+=1;issues=errors(r,p[r['household_id']])
   if issues:fail.append({'gamma':scenario['gamma'],'household_id':r['household_id'],'issues':issues})
   if example is None:example=r
  counts.append({'gamma':scenario['gamma'],'verified_witnesses':n,'retained_finite_search_failures':1000-n})
 q=copy.deepcopy(example);q['building_common_allocation_m2']+=1
 negative={'injection':'external_common_area_not_conserved','detected':'fixed_H6_identity' in errors(q,p[q['household_id']])}
 assert not fail and negative['detected']
 save(OUT/'INDEPENDENT_AREA_SENSITIVITY_VERIFICATION.json',{'scenarios':counts,'failures':fail,'negative_control':negative,
  'independent_from_geometry_and_search_generator':True,'compiled_reference_portal_coordinates_not_actual_home_doors':True,'fixture_and_thermal_validity_not_evaluated_here':True})
 print({'scenarios':counts,'failures':len(fail),'negative':negative})
if __name__=='__main__':main()
