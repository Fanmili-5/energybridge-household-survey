"""Historical design comparisons, not a census-stock eligibility or legal test.

Primary authored GB50096-2011 committee explanation, January2012, PDF pages
17(scope),25(gross/usable relation),28-31(selected area and width criteria).
No bedroom type is inferred merely from occupied berths: compare separate
single/double design thresholds for each reference private bedroom.
"""
import collections
from common import *
def main():
 guard();records=[];counts=collections.Counter();hhsets=collections.defaultdict(set)
 for rec in read(OUT/'JOINT_WORLD_BINDINGS.json')['records']:
  case=read(OUT/rec['world_path']);w=case['world'];hid=rec['household_id'];rooms=w['rooms'];studio=any(r['room_id']=='combined_bed_living' for r in rooms);checks=[]
  def add(label,value,limit,room=None):
   ok=value+1e-7>=limit;checks.append({'criterion':label,'reference_room_id':room,'value':value,'threshold':limit,'below_selected_historical_design_threshold':not ok});counts[label+'_comparisons']+=1
   if not ok:counts[label+'_below']+=1;hhsets[label].add(hid)
  for r in rooms:
   a=r['usable_area_m2'];rid=r['room_id'];rect=r['usable_rect_m']
   if rid=='combined_bed_living':add('combined_bed_living12m2',a,12.,rid)
   elif r['census_room_class']=='bedroom' and hid in r['using_household_ids']:
    add('private_bedroom_single_design5m2',a,5.,rid);add('private_bedroom_double_design9m2',a,9.,rid)
   elif r['census_room_class']=='hall':add('living_hall10m2',a,10.,rid)
   if r['current_function'] in ['exclusive_cooking_room','shared_cooking_room']:
    add('kitchen_studio3_5_other4m2',a,3.5 if studio else 4.,rid)
    add('kitchen_single_row_reference_width1_5m',min(rect[2]-rect[0],rect[3]-rect[1]),1.5,rid)
  # Whole reference-unit usable area is a unit measure, not per-household
  # allocated H6 and not per-resident space. Shared contexts remain distinct.
  add('whole_reference_unit_studio22_other30m2',w['usable_total_area_m2'],22. if studio else 30.)
  records.append({'household_id':hid,'checks':checks,'historical_standard_applicable_to_source_home':None,'actual_home_legal_compliance':None,
   'private_room_single_or_double_design_intention_observed':False,'does_not_exclude_census_stock_profile':True,
   'complete_kitchen_sink_hob_hood_water_and_full_sanitary_fixtures_checked':False})
 save(OUT/'HISTORICAL_DESIGN_SCREEN.json',{'primary_source':'raw/GB50096_2011_committee_explanation.pdf','source_pages_1based':[17,25,28,29,30,31],
  'scope':'historical urban/town new/alteration/extension architectural design,not all2020 city occupied stock eligibility or current2026 certification',
  'target_population_city_only_unchanged':True,'selected_comparisons_only_not_full_code_review':True,'counts':dict(counts),
  'households_below_by_criterion':{k:len(v) for k,v in hhsets.items()},'records':records,
  'single_or_double_bedroom_design_is_not_reconstructed_from_berth_count':True,'baseline_area_code_compliance_admitted':False})
 print(dict(counts));print({k:len(v) for k,v in hhsets.items()})
if __name__=='__main__':main()
