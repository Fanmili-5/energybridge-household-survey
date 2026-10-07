#!/usr/bin/env python3
"""Uniform housing policy revision; member RNG never reads downstream results."""
import argparse
import json
from pathlib import Path
import generate_empirical_support_candidates as gen
import verify_empirical_support_candidates as verifier

HERE=Path(__file__).resolve().parent
BATCHES={
    'empirical_support_reference_qc1':{'area_mode':'reference'},
    'empirical_support_tilt_qc0':{'minimum_source_area_per_room_m2':0.0},
    'empirical_support_tilt_qc0p5':{'minimum_source_area_per_room_m2':.5},
    'empirical_support_tilt_qc2':{'minimum_source_area_per_room_m2':2.0},
    'empirical_support_tilt_tau100':{'shrinkage_tau':100.0},
    'empirical_support_tilt_replicate':{'seed':20261004},
    'empirical_support_tilt_iid':{'area_draw_design':'iid'},
}
def main():
    source=gen.load_references;private_cache=[]
    def cached():
        if not private_cache:private_cache.append(source())
        return private_cache[0]
    gen.load_references=cached
    for name,overrides in BATCHES.items():
        args=argparse.Namespace(output=str(HERE/name),seed=20261003,h5_mode='independence',h7_mode='source_association',
            max_household_tail=16,max_room_tail=20,shrinkage_tau=20.0,age_bin_width=5,h7_prior_mass=.25,tail_prior_mass=.25,
            area_mode='tilt',area_bin_edges='1,20,40,60,80,100,120,160,200,250,350,500,750,1000,1500,2000',
            max_building_storeys=50,birthyear_upper_probability=.5,area_draw_design='stratified',minimum_source_area_per_room_m2=1.0)
        for key,value in overrides.items():setattr(args,key,value)
        gen.generate(args);qc=verifier.verify(HERE/name)
        (HERE/name/'PROFILES_QC.json').write_text(json.dumps(qc,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
        print(json.dumps({'batch':name,'pass':qc['pass'],'checks':qc['check_count'],
            'expected_mean_residual':qc['maximum_H6_expected_official_mean_residual_m2'],
            'realized_mean_residual':qc['maximum_H6_realized_official_mean_residual_m2']},ensure_ascii=False),flush=True)
        if not qc['pass']:raise ValueError('QC_failed:'+name)
if __name__=='__main__':main()
