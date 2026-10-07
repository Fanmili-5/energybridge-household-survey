"""Preserve census H6; stress unidentified building-common versus unit split.
Gamma is stipulated, not a national estimate, fixed net/gross conversion or
observed cadastral ratio. Finite grammar failures remain explicitly recorded.
Only geometric sleep capacity is evaluated here, not device/engine validity.
"""
import copy,collections
from common import *
from geometry import sized,SHAPES,STUDIOS
from mixed_sleep import choose
import compile_reference_idfs as compiler
def main():
 guard();profiles={p['slot_id']:p for p in read(V7/'HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json')['profiles']};all_results=[];original=compiler.assemblies
 try:
  for gamma in [.1,.2]:
   results=[]
   for r in read(OUT/'JOINT_WORLD_BINDINGS.json')['records']:
    hid=r['household_id'];p=copy.deepcopy(profiles[hid]);c=read(OUT/r['world_path']);w=c['world'];a=read(c['source_bundle_path']);H6=c['fixed_H6_m2'];inside=H6*(1-gamma);outside=H6*gamma
    p['housing']['H6_census_building_area_design_m2']=inside;compiler.assemblies=lambda a=a:a;shapes=STUDIOS if c['fixed_H7']==1 and w['shared_household_count_design']==1 else SHAPES
    order=[r['shape_index']]+[j for j in range(len(shapes)) if j!=r['shape_index']];attempts=[];success=None
    for j in order:
     try:
      candidate=sized(p,w['stock_reference_features'],a,shapes[j]);rows,meta=compiler.model(candidate);sleep=choose(p,candidate,rows,.6,False)
      if not sleep['found']:sleep=choose(p,candidate,rows,.6,True)
      attempts.append({'shape_index':j,'sleep_found':sleep['found']})
      if sleep['found']:
       assert abs(candidate['target_H6_unrounded_m2']+outside-H6)<1e-6
       parents={z[1]:z[4] for z in rows if z[0]=='BuildingSurface:Detailed'}
       doors={parents[z[4]]:[list(map(float,z[k:k+3])) for k in range(10,len(z),3)] for z in rows if z[0]=='FenestrationSurface:Detailed' and z[2]=='Door' and not z[1].endswith('_peer') and z[1]!='entry_door'}
       success={'shape_index':j,'target_unit_gross_allocation_m2':candidate['target_H6_unrounded_m2'],'sleep':sleep,'usable_total_m2':candidate['usable_total_area_m2'],
        'reference_world_geometry':candidate,'compiled_reference_portal_vertices_by_room':doors};break
     except ValueError as e:attempts.append({'shape_index':j,'reason':str(e)})
    results.append({'household_id':hid,'fixed_census_H6_m2':H6,'building_common_allocation_m2':outside,'reference_unit_allocation_target_m2':inside,
     'found':success is not None,'witness':success,'attempts':attempts,'no_profile_source_resampling':True})
    if len(results)%100==0:print({'gamma':gamma,'processed':len(results),'found':sum(x['found'] for x in results)},flush=True)
   all_results.append({'gamma':gamma,'witnesses':sum(x['found'] for x in results),'no_witness':sum(not x['found'] for x in results),
    'failed_household_IDs':[x['household_id'] for x in results if not x['found']],'records':results})
 finally:compiler.assemblies=original
 save(OUT/'AREA_ALLOCATION_SENSITIVITY.json',{'baseline_gamma':0.,'baseline_gamma_is_declared_not_observed':True,'stress_scenarios':all_results,
  'gamma_is_not_estimated_stock_rate':True,'fixed_H6_N_G_H7_q_and_source_parameters_preserved':True,
  'whole_reference_H6_identity':'unit-target allocation plus outside-building-common allocation equals fixed census H6;aux context areas separately conserved',
  'baseline_worlds_and_IDFs_not_changed':True,'appliance_footprints_engine_and_building_common_geometry_not_evaluated_in_stress':True,
  'finite_search_failure_not_proof_impossible_real_dwelling':True,'H6_to_inside_geometry_point_identification_not_established':True})
 print({'summary':[{k:s[k] for k in ['gamma','witnesses','no_witness']} for s in all_results]})
if __name__=='__main__':main()
