#!/usr/bin/env python3
"""Anonymous policy admission controls; synthetic source fixtures are labelled."""
import argparse
import collections
import copy
import hashlib
import json
import tempfile
from pathlib import Path
import generate_candidates as gen
import verify_candidates as verifier

HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text())
def save(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def pick(body,predicate):return next(p for p in body['profiles'] if predicate(p))


def policy_positive():
    # Fictional references test policy, never estimate an empirical frequency.
    source={'weight':1.0,'visit_year':2021,'generation_count_proxy':1,
        '_joint_age_pattern':((0,),(2,),(((3,3),(11,11)),)),
        '_age_sex_counts':collections.Counter({(0,3,2):1,(0,11,2):1}),
        '_source_relation_counts':collections.Counter({1:1,10:1})}
    old=gen.select_pool
    gen.select_pool=lambda *a,**k:([source],'synthetic_source_policy_fixture')
    gen.MODEL.update(age_bin_width=5,birthyear_upper_probability=.5)
    gen.FAMILY_REFERENCE_CACHE.clear()
    slot={'slot_id':'fixture-0001','province':'fixture','size_category':'2','generation_category':'1','exact_member_count':2}
    f=gen.generated_family(slot,[],gen.stage_rng(123,'synthetic_policy_fixture'),16)
    gen.FAMILY_REFERENCE_CACHE.clear()
    singleton={**slot,'size_category':'1','exact_member_count':1}
    one=gen.generated_family(singleton,[],gen.stage_rng(456,'synthetic_singleton_condition'),16)
    gen.select_pool=old
    ages=[m['age_years'] for m in f['members']]
    return {'fixture_is_synthetic_not_CHFS':True,'G1_multimember_under20_allowed':min(ages)<20,
        'same_generation_gap_above6_allowed':max(ages)-min(ages)>6,
        'same_sex_members_not_forced_to_opposite_sexes':len({m['sex_design'] for m in f['members']})==1,
        'no_spouse_or_parent_claim_generated':all(r['kind'] in ['shared_generation_design','cross_generation_co_residence_design'] for r in f['relation_design']),
        'singleton_under20_exclusion_preserved':one['members'][0]['age_years']>=20}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--batch',default='strong_shrinkage_tau100');args=ap.parse_args()
    baseline=HERE/args.batch;body=read(baseline/'FAMILY_HOUSING_CANDIDATES.json');targets=read(baseline/'CALIBRATION_TARGETS.json');lock=read(baseline/'GENERATOR_LOCK.json')
    def old_age_rule(b,t):b['profiles'][0]['family']['age_kinship_policy']['same_generation_age_gap_limit']=6
    def inferred_parent(b,t):
        f=pick(b,lambda p:p['family']['resident_count']>1)['family'];f['relation_design'].append({'kind':'parent_child_design','member_ids':f['resident_member_ids'][:2]})
    def invented_form(b,t):b['profiles'][0]['housing']['dwelling_type']='apartment'
    def underage_single(b,t):
        m=pick(b,lambda p:p['family']['resident_count']==1)['family']['members'][0];m['age_years']=19;m['age_reference_bin_years']=[15,19]
    def bad_mix(b,t):
        comps=b['profiles'][0]['family']['member_generation_reference']['reference_mixture']['components']
        for i,c in enumerate(comps):c['mass']=float(i==0)
    def fake_area(b,t):
        h=pick(b,lambda p:p['housing']['H5_is_ordinary_model_assigned'])['housing'];h['H6_building_area_m2']=max(x['upper_m2'] for x in h['H6_predictive_support_bins'])+100
    def fake_mean(tbody,t):
        row=next(x for x in t['ordinary_H6_province_vintage_means'] if x['profiles']);row['realized_mean_residual_m2']=0;row['actual_mean_H6_m2']=row['reference_mean_H6_m2']
    def fake_hull(b,t):next(x for x in t['ordinary_H6_province_vintage_means'] if x['profiles'])['reference_support_convex_hull_mean_m2'][0]-=10
    def fake_nonordinary(b,t):pick(b,lambda p:not p['housing']['H5_is_ordinary_model_assigned'])['housing']['H6_building_area_m2']=100
    def bad_rooms(b,t):pick(b,lambda p:p['housing']['H7_census_bin']=='5+')['housing']['H7_natural_rooms_exact']=4
    def duplicate_sleep(b,t):
        p=b['profiles'][0];p['housing']['sleep_groups'][0].append(p['family']['resident_member_ids'][0])
    def bad_population(b,t):b['profiles'][0]['province']='天津' if b['profiles'][0]['province']!='天津' else '北京'
    cases=[('old_same_generation_age_rule',old_age_rule,'unsupported_age_kinship_rule_reintroduced'),
        ('parent_edge_inferred_from_levels',inferred_parent,'kinship_inferred_from_generation'),
        ('dwelling_form_inferred_from_H8',invented_form,'dwelling_form_inferred_from_building_storeys'),
        ('under20_singleton',underage_single,'age_invalid_or_singleton_under20'),
        ('small_pool_full_weight',bad_mix,'ESS_continuous_mixture_policy_conflict'),
        ('area_outside_frozen_predictive_support',fake_area,'H6_area_outside_original_support'),
        ('fabricated_realized_official_mean_match',fake_mean,'H6_realized_residual_reported_'),
        ('support_expanded_to_fit_mean',fake_hull,'H6_original_support_hull_'),
        ('nonordinary_census_area',fake_nonordinary,'nonordinary_census_fields_fabricated'),
        ('H7_topcode_bin_changed',bad_rooms,'H7_bin_or_semantic_conflict'),
        ('duplicate_sleep',duplicate_sleep,'sleep_assignment_conflict'),
        ('population_province_changed',bad_population,'changed_population_target')]
    results=[]
    for name,mutation,expected in cases:
        b,t=copy.deepcopy(body),copy.deepcopy(targets);mutation(b,t)
        with tempfile.TemporaryDirectory(prefix='anonymous_policy_',dir=HERE) as d:
            out=Path(d);save(out/'FAMILY_HOUSING_CANDIDATES.json',b);save(out/'CALIBRATION_TARGETS.json',t)
            copylock=copy.deepcopy(lock);copylock['output_sha256']=sha(out/'FAMILY_HOUSING_CANDIDATES.json');save(out/'GENERATOR_LOCK.json',copylock)
            qc=verifier.verify(out)
        failed=qc['failed'];labels=[x['check'] for x in failed];faults={}
        for x in failed:
            if x['check'] in ['profile_semantic_checks','H6_profile_support_and_influence']:faults.update(x['detail'])
        detected=expected in faults or any(label.startswith(expected) for label in labels)
        results.append({'case':name,'expected':expected,'candidate_rejected':not qc['pass'],'expected_semantic_failure_detected':detected,
                        'self_consistent_byte_hash_pass':next(x['pass'] for x in qc['checks'] if x['check']=='candidate_bytes_equal_locked_sha')})
    positive=policy_positive();passed=all(positive.values()) and all(x['candidate_rejected'] and x['expected_semantic_failure_detected'] and x['self_consistent_byte_hash_pass'] for x in results)
    report={'schema':'eb.generation_v2_policy_controls.v1','baseline':args.batch,'baseline_sha256':sha(baseline/'FAMILY_HOUSING_CANDIDATES.json'),
        'positive_controls':positive,'negative_controls':results,'pass':passed,'source_microdata_read':False,'mutants_retained':False,'test_code_sha256':sha(__file__)}
    save(HERE/'POLICY_CONTROL_RESULTS.json',report);print(json.dumps({'pass':passed,'negative_controls':len(results),'positive_controls':positive}))
    if not passed:raise SystemExit(1)


if __name__=='__main__':main()
