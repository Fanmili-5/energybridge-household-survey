"""Sharp two-event Frechet bounds conditional on fixed province margins.

These are mathematical identification regions, not confidence intervals,
sampling uncertainty, causal bounds, or sharp bounds on all model outputs.
Two-by-two endpoint witnesses preserve both margins without independence.
"""
import collections,json
from pathlib import Path
OUT=Path(__file__).resolve().parent.parent;BASE=OUT.parent
PAIRS=[
 ('older_and_tall',('effective_building_epoch',['pre1949','1949_1959','1960_1969','1970_1979','1980_1989','1990_1999']),('building_storeys',['8_to33','34plus'])),
 ('rent_and_shared_kitchen',('housing_source',['rent_social','rent_other']),('kitchen',['shared'])),
 ('one_storey_and_elevator',('building_storeys',['one_storey']),('elevator',['present'])),
 ('no_piped_water_and_self_heater',('piped_water',['absent']),('bathing_hot_water',['self_installed_heater'])),
 ('tallest_and_steel_RC',('building_storeys',['34plus']),('load_bearing_structure',['steel_RC'])),
 ('no_kitchen_and_main_gas',('kitchen',['none']),('main_cooking_fuel',['gas']))]
def save(name,d):(OUT/name).write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def endpoint(a,b,n,x):return {'both':x,'A_only':a-x,'B_only':b-x,'neither':n-a-b+x}
def main():
 if (OUT/'PACKAGE_MANIFEST.json').exists():raise SystemExit('sealed')
 controls=json.loads((OUT/'STOCK_CONTROLS.json').read_text())['controls'];index={(r['province'],r['feature']):r for r in controls}
 pp=json.loads((BASE/'idf_joint_production_20261005/HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json').read_text())['profiles'];by=collections.defaultdict(list)
 for p in pp:by[p['province']].append(p)
 scenarios=json.loads((OUT/'STOCK_SCENARIOS1000.json').read_text())['scenarios'];mapping={s['scenario_id']:{r['household_id']:r['official_marginal_calibrated_reference_assignments'] for r in s['households']} for s in scenarios};results=[]
 for name,(fa,la),(fb,lb) in PAIRS:
  rows=[];weighted=[0.,0.];integer=[0,0];observed={s:0 for s in mapping};total_weight=sum(p['relative_population_weight'] for p in pp)
  for prov,pool in sorted(by.items()):
   ra,rb=index[prov,fa],index[prov,fb];a=sum(ra['source_proportions'][v] for v in la);b=sum(rb['source_proportions'][v] for v in lb);lo=max(0.,a+b-1);hi=min(a,b)
   n=len(pool);ia=sum(ra['integer_reference_counts'][v] for v in la);ib=sum(rb['integer_reference_counts'][v] for v in lb);ilo=max(0,ia+ib-n);ihi=min(ia,ib)
   w=sum(p['relative_population_weight'] for p in pool)/total_weight;weighted[0]+=w*lo;weighted[1]+=w*hi;integer[0]+=ilo;integer[1]+=ihi
   for sid,assign in mapping.items():
    v=sum(assign[p['slot_id']][fa] in la and assign[p['slot_id']][fb] in lb for p in pool);assert ilo<=v<=ihi;observed[sid]+=v
   rows.append({'province':prov,'official_A_proportion':a,'official_B_proportion':b,'sharp_proportion_bounds':[lo,hi],
    'reference_N':n,'integer_A_count':ia,'integer_B_count':ib,'sharp_integer_both_bounds':[ilo,ihi],
    'lower_endpoint_2x2_witness':endpoint(ia,ib,n,ilo),'upper_endpoint_2x2_witness':endpoint(ia,ib,n,ihi)})
  results.append({'pair':name,'event_A':{'feature':fa,'categories':la},'event_B':{'feature':fb,'categories':lb},
    'province_poststratified_proportion_bounds':weighted,'sharp_reference1000_count_bounds':integer,
    'scenario_counts':observed,'provinces':rows,'bounds_condition_on_margins_without_structural_zero_constraints':True})
 save('PARTIAL_IDENTIFICATION.json',{'method':'province-conditional two-event Frechet bounds with endpoint witnesses',
  'pairs':results,'sampling_error_and_long_to_short_frame_transport_not_included':True,
  'not_bounds_on_full_multivariate_joint_or_energy_or_behavior':True,
  'scenario_extremes_are_not_claimed_sharp_bounds':True,'unknown_associations_not_identified_by_more_marginal_controls':True})
 print(json.dumps({r['pair']:r['sharp_reference1000_count_bounds'] for r in results},ensure_ascii=False))
if __name__=='__main__':main()
