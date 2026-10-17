"""Apply the common weighted-area rule to the already assigned research cohort.
No individual exception table, resampling, or changed room/sharing assignments.
The full generator calls the same rule when reproduced from source.
"""
import json,sys
import numpy as np
from joint_housing import OUT,BASE,LO,HI,balance_weighted_area,save
from reference_world import minimum_area,sized_world

def main():
    body=json.loads((OUT/'HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json').read_text());pp=body['profiles']
    # The first attempted L1-only rule concentrated650m2 in one home and was
    # rejected. Always repair from the saved pre-correction reference vector.
    saved=OUT/'UNWEIGHTED_AREA_ASSIGNMENT_BEFORE_CORRECTION.json'
    if saved.exists():
        before={r['household_id']:r['area_design_m2'] for r in json.loads(saved.read_text())['household_areas']}
    else:
        before={r['household_id']:r['H6'] for r in json.loads((OUT/'IDF_REFERENCE_BINDINGS1000.json').read_text())['bindings']}
    old=np.array([before[p['slot_id']] for p in pp])
    lower=[];upper=[]
    for p in pp:
        h=p['housing'];N=p['family']['resident_count'];b=h['percap_area_bin_index'];R=h['H7_independent_natural_rooms_design'];q=h['shared_household_count_design']
        lower.append(max(np.ceil(LO[b]*N),np.ceil(minimum_area(R,q)-1e-8)))
        upper.append(HI[b]*N if np.isfinite(HI[b]) else 92170)
    new,correction=balance_weighted_area(old,np.array(lower),np.array(upper),pp)
    save('WEIGHTED_AREA_MOMENT_CORRECTION.json',correction)
    sys.path.insert(0,str(BASE/'benchmark_foundation_20261004/code'));from census_projection import project
    for p,A in zip(pp,new):
        h=p['housing'];w=sized_world(h['H7_independent_natural_rooms_design'],h['shared_household_count_design'],int(A),p['slot_id'])
        h['H6_census_building_area_design_m2']=int(A)
        h['gross_to_net_area_ratio_for_this_world']=w['usable_total_area_m2']/w['whole_unit_building_area_m2']
        save(h['world_path'],{'world':w,'census_projection':project(w)})
    anchor=json.loads((BASE/'production_route_v6_20261004/HOUSEHOLDS1000_JOINT_CANDIDATE.json').read_text())['profiles']
    body['result']['housing_assignment_changes']['H6_changed']=sum(p['housing']['H6_census_building_area_design_m2']!=a['housing']['H6_census_building_area_design_m2'] for p,a in zip(pp,anchor))
    # Retain the pre-weighted-projection metric with its original scope rather
    # than claiming the new mean is computed from unavailable initial draws.
    if 'projection_mean_absolute_area_change_m2' in body['result']:
        body['result']['projection_mean_absolute_area_change_m2_before_weighted_correction']=body['result'].pop('projection_mean_absolute_area_change_m2')
    body['result']['weighted_area_mean_m2']=correction['after_weighted_mean_m2'];body['result']['weighted_area_correction']=correction
    save('HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json',body);save('JOINT_HOUSING_RESULT.json',body['result'])
    print(json.dumps(correction,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
