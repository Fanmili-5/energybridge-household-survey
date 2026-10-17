#!/usr/bin/env python3
"""Audit native source selection and model identification before production.

Imports the existing source semantic bridge, never a generator or IDF writer.
Private source identifiers are used only for combining overlapping pool mass.
Outputs are aggregate diagnostics and generated-slot reference checks.
"""
import argparse
import collections
import copy
import hashlib
import json
import math
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
H1000=HERE.parent.parent
sys.path.insert(0,str(H1000/'chfs_census_bridge_20261003'))
import run_bridge as bridge

def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        while b:=f.read(1024*1024):h.update(b)
    return h.hexdigest()

def write(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def count(xs,key):return dict(collections.Counter(str(x.get(key)) for x in xs))
def ess(xs):
    ws=[float(x['weight']) for x in xs]
    return sum(ws)**2/sum(w*w for w in ws) if ws else 0.0

def source_mixture(records,province,size,generation,room,tau,quality_floor):
    eligible=[r for r in records if r['area_scope_supported'] and r['room_proxy_category']==room
        and isinstance(r['area_candidate_m2'],(int,float)) and math.isfinite(r['area_candidate_m2'])
        and r['room_count_h7_proxy'] and r['area_candidate_m2']/r['room_count_h7_proxy']>=quality_floor]
    def preferred(pred):
        xs=[r for r in eligible if pred(r)]
        aligned=[r for r in xs if r['member_housing_same_reference_time']]
        return aligned or xs
    local=preferred(lambda r:r['province']==province and r['size_category']==size and r['generation_category']==generation)
    national=preferred(lambda r:r['size_category']==size and r['generation_category']==generation)
    broad=preferred(lambda r:r['generation_category']==generation)
    city=preferred(lambda r:True)
    if not broad:broad=city
    masses=[]
    remaining=1.0
    for xs in [local,national,broad]:
        e=ess(xs);lam=e/(e+tau) if e else 0.0
        masses.append(remaining*lam);remaining*=1-lam
    masses.append(remaining)
    merged={}
    for xs,mass in zip([local,national,broad,city],masses):
        total=sum(float(r['weight']) for r in xs)
        if mass<=0:continue
        if not total:raise ValueError('empty_positive_mass_pool')
        for r in xs:
            key=r['_local_hhid']
            if key not in merged:merged[key]=dict(r,weight=0.0)
            merged[key]['weight']+=mass*float(r['weight'])/total
    return list(merged.values())

def actual_bins(pool,edges):
    bins=collections.defaultdict(list);omitted=0.0
    for r in pool:
        a=r['area_candidate_m2']
        index=next((i for i,(lo,hi) in enumerate(zip(edges,edges[1:])) if lo<=a<=hi),None)
        if index is None:omitted+=r['weight']
        else:bins[index].append(r)
    total=sum(r['weight'] for xs in bins.values() for r in xs)
    return {i:{'lower_m2':min(r['area_candidate_m2'] for r in xs),
        'upper_m2':max(r['area_candidate_m2'] for r in xs),
        'probability':sum(r['weight'] for r in xs)/total,
        'source_records':len(xs),
        'source_weight_square_sum':sum((r['weight']/total)**2 for r in xs),
        'maximum_source_weight':max(r['weight']/total for r in xs)} for i,xs in bins.items()},omitted

def support_errors(h,expected,edges):
    errors=[]
    # Raw whole-dwelling reference and derived shared allocation are different
    # statistical units. Validate the former against native endpoints, then
    # validate the explicit design transform without calling it observation.
    raw=h['area_reference']['predictive_area_bins']
    if len(raw)!=len(expected):errors.append('bin_count')
    for b in raw:
        index=next((i for i in range(len(edges)-1) if b['source_coarsening_bin_m2']==edges[i:i+2]),None)
        e=expected.get(index)
        if e is None:errors.append('unsupported_source_bin');continue
        for key,value in e.items():
            if abs(b[key]-value)>1e-8*max(1,abs(value)):errors.append('native_reference_mismatch:'+key)
        if b['source_H7_bin']!=h['H7_census_bin']:errors.append('room_condition_mismatch')
    ratio=h['sharing_model']['whole_to_exclusive_design_ratio']
    if h['occupancy_scope']=='whole_household_private' and ratio!=1:
        errors.append('private_whole_scope_transformed')
    mapped=h['H6_predictive_support_bins']
    if len(raw)!=len(mapped):errors.append('transformed_bin_count')
    for sourcebin,modelbin in zip(raw,mapped):
        for field in ['lower_m2','upper_m2']:
            if abs(modelbin[field]-sourcebin[field]*ratio)>1e-8:
                errors.append('explicit_allocation_transform_mismatch:'+field)
    if not any(e['lower_m2']*ratio-.005001<=h['H6_building_area_m2']<=e['upper_m2']*ratio+.005001 for e in expected.values()):
        errors.append('generated_area_outside_declared_source_or_design_transformed_support')
    return errors

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--profiles',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    if args.output.exists():raise ValueError('new_immutable_audit_directory_required')
    args.output.mkdir(parents=True)
    source=args.profiles.resolve();body=json.loads(source.read_text());settings=body['generation_model']
    lock_path=source.parent/'GENERATOR_LOCK.json';lock=json.loads(lock_path.read_text())
    binding_errors=[]
    if lock['output_sha256']!=sha(source):binding_errors.append('profile_lock')
    if lock['settings']!=settings:binding_errors.append('model_settings_lock')
    for r in lock['source_files']:
        if sha(r['path'])!=r['sha256']:binding_errors.append('source_bytes_changed:'+Path(r['path']).name)
    frame=bridge.load_bridge_pool()
    allcity=frame.to_dict('records')
    records=frame[frame.eligible_for_generation_matching & frame.weight.notna() & (frame.weight>0)].to_dict('records')
    selected=[r for r in records if r['selected']]
    area=[r for r in records if r['area_scope_supported']]
    pairs=[r for r in area if r['room_count_h7_proxy'] is not None and math.isfinite(float(r['room_count_h7_proxy'])) and r['room_count_h7_proxy']>0]
    floor=settings['minimum_source_area_per_room_m2_design']
    accepted=[r for r in pairs if r['area_candidate_m2']/r['room_count_h7_proxy']>=floor]
    quarantined=[r for r in pairs if r not in accepted]
    source_report={'schema':'eb.foundation.source_frame_audit.v1','profile_sha256':sha(source),
        'bridge_sha256':sha(H1000/'chfs_census_bridge_20261003/run_bridge.py'),
        'bridge_rules_sha256':sha(H1000/'chfs_census_bridge_20261003/bridge_rules.py'),
        'stages':[{ 'stage':name,'records':len(xs),'Kish_ESS':ess([r for r in xs if r['weight'] is not None and r['weight']>0]),
            'tenure_codes':count(xs,'tenure_code'),'sharing_scope':count(xs,'sharing_scope'),
            'area_origin':count(xs,'area_origin'),'visit_years':count(xs,'visit_year')}
            for name,xs in [('city_coded_raw',allcity),('member_eligible_positive_weight',records),
                ('current_dwelling_selected',selected),('whole_scope_area_proxy',area),
                ('paired_area_H7_proxy_before_quality_quarantine',pairs),('paired_area_H7_proxy_after_quality_quarantine',accepted)]],
        'financial_complete_cases_in_member_pool':sum(r['finance_derived_totals_present'] for r in records),
        'financial_complete_case_required_by_member_eligibility':False,
        'paired_rented_room_references':sum(r['tenure_code']==2 for r in accepted),
        'paired_owned_room_references':sum(r['tenure_code']==1 for r in accepted),
        'CHFS_H5_equivalence_verified':False,'CHFS_room_proxy_equals_census_H7_verified':False,
        'source_city_sampling_address_equals_current_residence_verified':False,
        'quality_quarantine':{'threshold_m2_per_proxy_room':floor,'official_minimum':False,
            'source_housing_pairs_withheld':len(quarantined),'area_origin_counts':count(quarantined,'area_origin'),
            'original_rows_changed':0,'member_references_removed':0,'population_slots_removed':0,
            'resolution_required':'source field unit/branch verification; retain raw values; never assume multiplying by100 corrects a typo'},
        'limits':['source-frame selection is diagnostic, not calibration of target selection probabilities',
            'exact source weight validity for the selected housing branch remains unverified',
            'cross-year transportation and room-proxy definition need independent validation'],
        'raw_source_ids_or_rows_exported':False,'source_microdata_read':True}
    write(args.output/'SOURCE_FRAME_AUDIT.json',source_report)
    cache={};errors=[];slotrows=[];room_count=0
    edges=settings['area_bin_edges_m2']
    for p in body['profiles']:
        h=p['housing']
        if not h['H5_is_ordinary_model_assigned']:continue
        key=(p['province'],p['size_category'],p['generation_category'],h['H7_census_bin'])
        if key not in cache:
            pool=source_mixture(records,*key,settings['shrinkage_tau'],floor)
            cache[key]=actual_bins(pool,edges)
        bins,omitted=cache[key];problem=support_errors(h,bins,edges)
        if problem:errors.append({'slot_id':p['slot_id'],'errors':problem})
        room_count+=1
        slotrows.append({'slot_id':p['slot_id'],'province':p['province'],
            'N':p['size_category'],'G':p['generation_category'],'H7_bin':h['H7_census_bin'],
            'native_endpoint_and_weight_check':'fail' if problem else 'pass',
            'model_posterior_maximum_source_share':h['area_policy']['posterior_maximum_source_weight'],
            'model_posterior_source_ESS':h['area_policy']['posterior_source_ESS'],
            'same_H7_reference_scope':'current_whole_owned_branch; rented_H7_not_measured',
            'generated_area_unit':'whole_household_gross_proxy' if h['occupancy_scope']=='whole_household_private' else 'shared_exclusive_plus_common_design_allocation',
            'shared_area_allocation_empirically_verified':False,
            'weighted_mass_outside_declared_area_domain':omitted})
    first=next(p for p in body['profiles'] if p['housing']['H5_is_ordinary_model_assigned'])
    h=first['housing'];key=(first['province'],first['size_category'],first['generation_category'],h['H7_census_bin'])
    expected=cache[key][0]
    probe=copy.deepcopy(h);probe['area_reference']['predictive_area_bins'][0]['lower_m2']-=.1
    negative_detected=bool(support_errors(probe,expected,edges))
    native_report={'schema':'eb.foundation.native_area_support_check.v1','generator_imported':False,
        'profile_sha256':sha(source),
        'scope':'recomputes source filtering, nested overlap-combined weights and endpoints using existing semantic bridge; does not independently validate that bridge or population transport',
        'profiles_checked':room_count,'distinct_reference_keys':len(cache),'errors':errors,
        'negative_control_expanded_source_endpoint_detected':negative_detected,
        'pass':not errors and negative_detected,'rows':slotrows}
    write(args.output/'NATIVE_AREA_SUPPORT_CHECK.json',native_report)
    targets=json.loads((source.parent/'CALIBRATION_TARGETS.json').read_text())['ordinary_H6_province_vintage_means']
    populated=[r for r in targets if r['profiles']]
    dominated=[r for r in slotrows if r['model_posterior_maximum_source_share']>.5]
    gates=[
        {'id':'target_field_contract','status':'documented','evidence':'FOUNDATION_CONTRACT.json'},
        {'id':'source_bytes_and_reference_reconstruction','status':'pass' if not binding_errors and native_report['pass'] else 'fail',
            'errors':binding_errors+errors},
        {'id':'H5_H7_and_housing_branch_to_target_bridge','status':'unresolved',
            'reason':'paired-room source restricted to owned branch; H5/H7 equivalence and rented/shared transport not validated'},
        {'id':'calibration_influence_and_joint_distribution','status':'unresolved',
            'reason':'exact aggregate expected means coexist with strong source domination; no target joint distribution validation'},
        {'id':'functional_home_and_actor_contract','status':'unresolved',
            'reason':'actual form/interior storeys/topology, full kinship and task operations not validated'},
        {'id':'observed_human_benchmark','status':'unresolved','reason':'no observed human answers or comprehension pilot'}]
    decision={'schema':'eb.foundation.preflight_decision.v1','profile_path':str(source),'profile_sha256':sha(source),
        'contract_sha256':sha(HERE/'FOUNDATION_CONTRACT.json'),'audit_code_sha256':sha(__file__),
        'generator_lock_path':str(lock_path),'generator_lock_sha256':sha(lock_path),
        'source_frame_sha256':sha(args.output/'SOURCE_FRAME_AUDIT.json'),
        'native_support_sha256':sha(args.output/'NATIVE_AREA_SUPPORT_CHECK.json'),
        'audit_integrity_pass':not binding_errors and native_report['pass'],'gates':gates,
        'profiles':len(body['profiles']),'ordinary_profiles':room_count,
        'source_dominates_more_than_half_of_posterior_mass_profiles':len(dominated),
        'majority_diagnostic_is_not_a_validated_scientific_release_threshold':True,
        'maximum_area_posterior_source_weight_share':max(r['model_posterior_maximum_source_share'] for r in slotrows),
        'minimum_area_posterior_source_ESS':min(r['model_posterior_source_ESS'] for r in slotrows),
        'populated_official_area_mean_groups':len(populated),
        'maximum_expected_mean_residual_m2':max(abs(r['expected_mean_residual_m2']) for r in populated),
        'current_population_generation_status':'research_candidate_only_foundational_identification_unresolved',
        'formal_1000_production_release':False,'collection_release':False,'training_release':False,
        'compile_rate_or_energy_outcomes_used_for_preflight':False,
        'next_work':['resolve H5/H7 and housing-branch selection/transport before choosing a universal conditional housing model',
            'compare reference vs mean-tilted model by source concentration and jointly supported validation, not expected mean residual alone',
            'complete task-relevant functional role contract before actor collection']}
    write(args.output/'PREFLIGHT_DECISION.json',decision)
    print(json.dumps({k:decision[k] for k in ['audit_integrity_pass','profiles','ordinary_profiles',
        'source_dominates_more_than_half_of_posterior_mass_profiles','maximum_area_posterior_source_weight_share',
        'formal_1000_production_release']},ensure_ascii=False))
    raise SystemExit(0 if decision['audit_integrity_pass'] else 1)

if __name__=='__main__':main()
