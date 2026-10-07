#!/usr/bin/env python3
"""Complete interrupted comparison attempts in new immutable directories."""
import argparse
import json
from pathlib import Path
import generate_empirical_support_candidates as gen
import verify_empirical_support_candidates as verifier

HERE = Path(__file__).resolve().parent

def main():
    original = gen.load_references
    cache = []
    def cached():
        if not cache:
            cache.append(original())
        return cache[0]
    gen.load_references = cached
    batches = {
        'empirical_support_tilt_tau100_completed': {'shrinkage_tau':100.0},
        'empirical_support_tilt_replicate': {'seed':20261004},
        'empirical_support_tilt_iid': {'area_draw_design':'iid'},
    }
    for name, overrides in batches.items():
        args = argparse.Namespace(output=str(HERE/name),seed=20261003,h5_mode='independence',
            h7_mode='source_association',max_household_tail=16,max_room_tail=20,
            shrinkage_tau=20.0,age_bin_width=5,h7_prior_mass=.25,tail_prior_mass=.25,
            area_mode='tilt',area_bin_edges='1,20,40,60,80,100,120,160,200,250,350,500,750,1000,1500,2000',
            max_building_storeys=50,birthyear_upper_probability=.5,area_draw_design='stratified',
            minimum_source_area_per_room_m2=1.0)
        for key, value in overrides.items():
            setattr(args,key,value)
        gen.generate(args)
        qc = verifier.verify(HERE/name)
        (HERE/name/'PROFILES_QC.json').write_text(json.dumps(qc,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
        print(json.dumps({'batch':name,'pass':qc['pass'],'checks':qc['check_count'],
            'expected_mean_residual':qc['maximum_H6_expected_official_mean_residual_m2'],
            'maximum_area_source_share':qc['maximum_area_posterior_source_weight_share']},ensure_ascii=False),flush=True)
        if not qc['pass']:
            raise ValueError('QC_failed:'+name)

if __name__ == '__main__':
    main()
