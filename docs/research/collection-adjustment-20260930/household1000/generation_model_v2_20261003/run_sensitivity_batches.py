#!/usr/bin/env python3
"""Run fixed policy comparisons; source records stay in process memory only."""
import argparse
import json
from pathlib import Path
import generate_candidates as gen
import verify_candidates as verifier

HERE=Path(__file__).resolve().parent
BATCHES={
 'final_tilt_tau20':{},
 'reference_tau20':{'area_mode':'reference'},
 'strong_shrinkage_tau100':{'shrinkage_tau':100.0},
 'weak_shrinkage_tau5':{'shrinkage_tau':5.0},
 'H7_independent':{'h7_mode':'independent_size'},
 'H7_prior_0p1':{'h7_prior_mass':.1},
 'tail_prior_0p5_caps20_30':{'tail_prior_mass':.5,'max_household_tail':20,'max_room_tail':30},
 'age_bins10_upper0p25':{'age_bin_width':10,'birthyear_upper_probability':.25},
 'area_iid':{'area_draw_design':'iid'},
 'replicate_seed20261004':{'seed':20261004},
}


def main():
    original=gen.load_references
    private_cache={}
    def cached_references():
        key=(gen.MODEL['age_bin_width'],gen.MODEL['birthyear_upper_probability'])
        if key not in private_cache:private_cache[key]=original()
        return private_cache[key]
    gen.load_references=cached_references
    for name,overrides in BATCHES.items():
        args=argparse.Namespace(output=str(HERE/name),seed=20261003,h5_mode='independence',h7_mode='source_association',
            max_household_tail=16,max_room_tail=20,shrinkage_tau=20.0,age_bin_width=5,h7_prior_mass=.25,tail_prior_mass=.25,
            area_mode='tilt',area_bin_edges='1,20,40,60,80,100,120,160,200,250,350,500,750,1000,1500,2000',
            max_building_storeys=50,birthyear_upper_probability=.5,area_draw_design='stratified')
        for key,value in overrides.items():setattr(args,key,value)
        gen.generate(args)
        result=verifier.verify(HERE/name)
        (HERE/name/'PROFILES_QC.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
        print(json.dumps({'batch':name,'pass':result['pass'],'checks':result['check_count'],
            'expected_area_residual':result['maximum_H6_expected_official_mean_residual_m2'],
            'realized_area_residual':result['maximum_H6_realized_official_mean_residual_m2']},ensure_ascii=False),flush=True)
        if not result['pass']:raise RuntimeError('independent_verifier_failed:'+name)


if __name__=='__main__':main()
