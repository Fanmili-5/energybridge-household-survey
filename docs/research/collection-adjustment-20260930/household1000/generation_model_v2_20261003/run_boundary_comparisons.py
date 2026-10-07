#!/usr/bin/env python3
"""Predeclared H5 and area-domain alternatives; no downstream outcomes used."""
import argparse
import json
from pathlib import Path
import generate_candidates as gen
import verify_candidates as verifier

HERE=Path(__file__).resolve().parent
BATCHES={
    'H5_lower_ordinary':{'h5_mode':'lower_ordinary'},
    'H5_upper_ordinary':{'h5_mode':'upper_ordinary'},
    'area_domain_cap1000':{'area_bin_edges':'1,20,40,60,80,100,120,160,200,250,350,500,750,1000'},
}


def main():
    original=gen.load_references
    private_cache=[]
    def cached_references():
        if not private_cache:private_cache.append(original())
        return private_cache[0]
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
            'ordinary':result['ordinary'],'expected_area_residual':result['maximum_H6_expected_official_mean_residual_m2'],
            'realized_area_residual':result['maximum_H6_realized_official_mean_residual_m2']},ensure_ascii=False),flush=True)
        if not result['pass']:raise RuntimeError('independent_verifier_failed:'+name)


if __name__=='__main__':main()
