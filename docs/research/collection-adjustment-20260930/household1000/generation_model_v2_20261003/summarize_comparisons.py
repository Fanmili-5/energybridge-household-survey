#!/usr/bin/env python3
"""Readback comparison, source influence, population preservation and lineage."""
import collections
import hashlib
import json
import math
from pathlib import Path

HERE=Path(__file__).resolve().parent
NAMES=['final_tilt_tau20','reference_tau20','strong_shrinkage_tau100','weak_shrinkage_tau5',
    'H7_independent','H7_prior_0p1','tail_prior_0p5_caps20_30','age_bins10_upper0p25','area_iid',
    'replicate_seed20261004','H5_lower_ordinary','H5_upper_ordinary','area_domain_cap1000']
def read(path):return json.loads(Path(path).read_text())
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path,body):Path(path).write_text(json.dumps(body,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def digest(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def quantiles(values):
    vs=sorted(values)
    return {str(p):vs[round((len(vs)-1)*p)] for p in [0,.05,.25,.5,.75,.95,1]}
def family_semantics(p):
    f=p['family']
    return {'resident_count':f['resident_count'],'generation_levels':f['generation_levels'],
        'members':[(m['member_id'],m['age_years'],m['sex_design'],m['generation_level']) for m in f['members']],
        'relation_design':f['relation_design']}
def population_counter(ps):return collections.Counter((p['province'],p['size_category'],p['generation_category']) for p in ps)
def H7_counter(ps):return collections.Counter((p['province'],p['generation_category'],p['housing']['H7_census_bin']) for p in ps if p['housing']['H5_is_ordinary_model_assigned'])
def summary(name,baseline,allocation):
    batch=HERE/name;body=read(batch/'FAMILY_HOUSING_CANDIDATES.json');ps=body['profiles'];qc=read(batch/'PROFILES_QC.json');targets=read(batch/'CALIBRATION_TARGETS.json')
    rows=[r for r in targets['ordinary_H6_province_vintage_means'] if r['profiles']]
    n=sum(r['profiles'] for r in rows)
    expected_rmse=math.sqrt(sum(r['profiles']*r['expected_mean_residual_m2']**2 for r in rows)/n)
    realized_rmse=math.sqrt(sum(r['profiles']*r['realized_mean_residual_m2']**2 for r in rows)/n)
    ordinary=[p for p in ps if p['housing']['H5_is_ordinary_model_assigned']]
    area_ess=[p['housing']['area_policy']['posterior_source_ESS'] for p in ordinary]
    area_max=[p['housing']['area_policy']['posterior_maximum_source_weight'] for p in ordinary]
    base={p['slot_id']:p for p in baseline}
    result={k:v for k,v in qc.items() if k not in ['checks','failed']}
    result.update(batch=name,profile_path=str(batch/'FAMILY_HOUSING_CANDIDATES.json'),settings=body['generation_model'],
        population_slots_equal_original=population_counter(ps)==population_counter(allocation),
        original_slot_fields_equal=all((p['province'],p['size_category'],p['generation_category'])==(base[p['slot_id']]['province'],base[p['slot_id']]['size_category'],base[p['slot_id']]['generation_category']) for p in ps),
        family_semantic_same_slots_vs_tau20=sum(digest(family_semantics(p))==digest(family_semantics(base[p['slot_id']])) for p in ps),
        full_family_field_same_slots_vs_tau20=sum(digest(p['family'])==digest(base[p['slot_id']]['family']) for p in ps),
        H7_ordinary_margin_equal_tau20=H7_counter(ps)==H7_counter(baseline),
        H6_nonempty_group_count=len(rows),H6_expected_feasible_group_count=sum(r['official_mean_strictly_inside_support_hull'] for r in rows),
        H6_infeasible_groups=[{k:r[k] for k in ['province','vintage_category_index','profiles','reference_mean_H6_m2','reference_support_convex_hull_mean_m2','expected_mean_residual_m2','policy_status']} for r in rows if not r['official_mean_strictly_inside_support_hull']],
        H6_expected_group_weighted_RMSE_m2=expected_rmse,H6_realized_group_weighted_RMSE_m2=realized_rmse,
        H6_official_group_weighted_target_mean_m2=sum(r['profiles']*r['reference_mean_H6_m2'] for r in rows)/n,
        H6_expected_cohort_mean_m2=sum(r['profiles']*r['expected_model_mean_H6_m2'] for r in rows)/n,
        H6_realized_cohort_mean_m2=sum(r['profiles']*r['actual_mean_H6_m2'] for r in rows)/n,
        H6_posterior_source_ESS_quantiles=quantiles(area_ess),H6_posterior_source_maximum_share_quantiles=quantiles(area_max),
        diagnostic_thresholds_are_design_not_official=True,
        H6_source_ESS_below2_profiles=sum(x<2 for x in area_ess),H6_source_ESS_below5_profiles=sum(x<5 for x in area_ess),
        H6_source_maximum_share_above25percent_profiles=sum(x>.25 for x in area_max),H6_source_maximum_share_above50percent_profiles=sum(x>.5 for x in area_max),
        H6_source_weighted_mass_omitted_by_area_domain_max=max(p['housing']['area_reference']['weighted_mass_outside_design_area_bins'] for p in ps),
        H6_realized_group_counts_by_population={str(k):sum(r['profiles']==k for r in rows) for k in sorted({r['profiles'] for r in rows})},
        worst_realized_group_residuals=[{k:r[k] for k in ['province','vintage_category_index','profiles','realized_mean_residual_m2','expected_mean_residual_m2']} for r in sorted(rows,key=lambda r:-abs(r['realized_mean_residual_m2']))[:10]],
        input_and_code_lock_path=str(batch/'GENERATOR_LOCK.json'),input_and_code_lock_sha256=sha(batch/'GENERATOR_LOCK.json'))
    return result


def main():
    recommended=read(HERE/'final_tilt_tau20/FAMILY_HOUSING_CANDIDATES.json');baseline=recommended['profiles']
    allocation=read(HERE.parent/'evidence_contract_20261001/POPULATION_ALLOCATION_CANDIDATE_V2.json')['slots']
    results=[summary(n,baseline,allocation) for n in NAMES]
    old_path=HERE.parent/'generation_model_20261003/final_v2/FAMILY_HOUSING_CANDIDATES.json';old=read(old_path)['profiles']
    scales=[p['housing']['area_calibration_scale'] for p in old if p['housing']['H5_is_ordinary_model_assigned']]
    old_comparison={'frozen_profile_path':str(old_path),'frozen_profile_sha256':sha(old_path),
        'population_counter_preserved':population_counter(old)==population_counter(baseline),
        'H5_by_province_generation_preserved':collections.Counter((p['province'],p['generation_category'],p['housing']['H5_is_ordinary_model_assigned']) for p in old)==collections.Counter((p['province'],p['generation_category'],p['housing']['H5_is_ordinary_model_assigned']) for p in baseline),
        'H7_by_province_generation_preserved':H7_counter(old)==H7_counter(baseline),
        'old_area_multiplicative_scale_range':[min(scales),max(scales)],
        'new_multiplicative_area_scaling':False,
        'old_inferred_known_dwelling_form_profiles':sum(p['housing']['dwelling_type'] is not None for p in old),
        'new_known_actual_dwelling_form_profiles':sum(p['housing']['dwelling_type'] is not None for p in baseline),
        'old_same_generation_age_gap_above6_profiles':sum(any(max(m['age_years'] for m in p['family']['members'] if m['generation_level']==l)-min(m['age_years'] for m in p['family']['members'] if m['generation_level']==l)>6 for l in p['family']['generation_levels']) for p in old),
        'complete_actor_cards':0,'human_answers':0,'frozen_old_files_modified':False}
    reproduction=HERE/'reproduce_recommended/FAMILY_HOUSING_CANDIDATES.json'
    save(HERE/'SENSITIVITY_RESULTS.json',{'schema':'eb.generation_policy_comparison.v1','recommended_batch':'final_tilt_tau20',
        'recommendation_status':'design_default_not_empirical_optimum','selection_used_IDF_runtime_or_answers':False,
        'old_frozen_baseline_comparison':old_comparison,'batches':results,
        'fresh_process_reproduction':{'profile_path':str(reproduction),'sha256':sha(reproduction),'byte_identical_recommended':sha(reproduction)==sha(HERE/'final_tilt_tau20/FAMILY_HOUSING_CANDIDATES.json'),
            'QC_pass':read(reproduction.parent/'PROFILES_QC.json')['pass']},'comparison_code_sha256':sha(__file__)})
    ordinary=[p for p in baseline if p['housing']['H5_is_ordinary_model_assigned']]
    weakest=sorted(ordinary,key=lambda p:-p['housing']['area_policy']['posterior_maximum_source_weight'])[:20]
    grouped=collections.defaultdict(list)
    for p in baseline:grouped[(p['province'],p['size_category'],p['generation_category'])].append(p)
    relationships=[]
    for (province,size,generation),ps in sorted(grouped.items()):
        ref=ps[0]['family']['source_relationship_reference'];member=ps[0]['family']['member_generation_reference']
        relationships.append({'province':province,'size_category':size,'generation_category':generation,'target_slots':len(ps),
            'member_reference_source_count':member['source_records'],'member_reference_ESS':member['kish_effective_sample_size'],
            'weighted_expected_resident_count_by_A2001':ref['weighted_expected_resident_count_by_source_relation_code'],
            'weighted_presence_probability_by_A2001':ref['weighted_presence_probability_by_source_relation_code'],
            'reference_only_not_population_relationship_frequency':True})
    save(HERE/'SOURCE_INFLUENCE_SUMMARY.json',{'schema':'eb.generation_source_influence_summary.v1','recommended_profile_sha256':sha(HERE/'final_tilt_tau20/FAMILY_HOUSING_CANDIDATES.json'),
        'source_audit':read(HERE/'final_tilt_tau20/SOURCE_REFERENCE_AUDIT.json'),
        'member_reference_ESS_quantiles':quantiles([p['family']['member_generation_reference']['kish_effective_sample_size'] for p in baseline]),
        'member_reference_max_share_quantiles':quantiles([p['family']['member_generation_reference']['maximum_weight_share'] for p in baseline]),
        'local_member_mixture_mass_quantiles':quantiles([p['family']['member_generation_reference']['reference_mixture']['components'][0]['mass'] for p in baseline]),
        'area_posterior_source_ESS_quantiles':quantiles([p['housing']['area_policy']['posterior_source_ESS'] for p in ordinary]),
        'area_posterior_source_max_share_quantiles':quantiles([p['housing']['area_policy']['posterior_maximum_source_weight'] for p in ordinary]),
        'most_concentrated_twenty_ordinary_synthetic_slots':[{'slot_id':p['slot_id'],'province':p['province'],'size_category':p['size_category'],'generation_category':p['generation_category'],
            'vintage_category_index':p['housing']['vintage_category_index'],'posterior_source_ESS':p['housing']['area_policy']['posterior_source_ESS'],
            'posterior_source_maximum_weight':p['housing']['area_policy']['posterior_maximum_source_weight']} for p in weakest],
        'A2001_reference_by_target_population_cell':relationships,
        'source_IDs_exported':False,'original_family_vector_comparison_attempted':False,'differential_privacy_claimed':False,
        'dependency_limit':'overlapping conditional references share source households; unique synthetic IDs do not establish independent unseen-source benchmark units',
        'kinship_gap':'actual generated pairwise kinship graph remains pending; A2001 reference diagnostics are not edges of the synthetic resident roster'})
    print(json.dumps({'batches':len(results),'all_QC_pass':all(r['pass'] for r in results),'all_population_preserved':all(r['population_slots_equal_original'] for r in results),
        'reproduction_equal':sha(reproduction)==sha(HERE/'final_tilt_tau20/FAMILY_HOUSING_CANDIDATES.json')}))


if __name__=='__main__':main()
