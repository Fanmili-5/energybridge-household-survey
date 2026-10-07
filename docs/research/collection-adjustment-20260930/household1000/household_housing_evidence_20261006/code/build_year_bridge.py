"""Actual source admission, conditional year holdout and1000-slot support.
Only coarse aggregates/support and generated slot IDs are exported. Derived
source records remain in private_research and are not released as role facts.
"""
import collections,hashlib,json,math,sys
from pathlib import Path
import numpy as np
from year_rules import derive_year,epoch

OUT=Path(__file__).resolve().parent.parent;BASE=OUT.parent;REPO=OUT.parents[4]
PRIVATE=REPO/'artifacts/private_research/household_housing_evidence_20261006'
sys.path.insert(0,str(BASE/'chfs_census_bridge_20261003'));import run_bridge as rb

def save(name,d):(OUT/name).write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def fold(h):return int(hashlib.sha256(('EB_EFFECTIVE_HOUSING_YEAR20261006|'+str(h)).encode()).hexdigest(),16)%5
def area_bin(pc):return int(np.searchsorted([8,12,16,19,29,39,49,59,69],pc,side='left'))
def kish(rows):
    w=np.array([r['weight'] for r in rows]);return float(w.sum()**2/(w@w)) if len(w) else 0.

def distributions(records):
    global_joint=np.full((10,10,4),.1);local=collections.defaultdict(lambda:np.zeros((10,10,4)))
    mean=np.mean([d['weight'] for d in records])
    for d in records:
        w=d['weight']/mean;idx=(d['R']-1,d['B'],d['Y']);global_joint[idx]+=w;local[(d['N'],d['G'])][idx]+=w
    return global_joint/global_joint.sum(),local

def joint(g,l,N,G):
    counts=l[(N,G)];return (counts+10*g)/(counts.sum()+10)

def evaluate(records):
    folds=[]
    for f in range(5):
        train=[d for d in records if d['fold']!=f];test=[d for d in records if d['fold']==f]
        g,l=distributions(train);scores=np.zeros(3)
        for d in test:
            p=joint(g,l,d['N'],d['G']);py=p[d['R']-1,d['B']];py=py/py.sum();factor=p.sum((0,1))
            scores+=np.array([-math.log(py[d['Y']]),-math.log(factor[d['Y']]),1])*d['weight']
        folds.append({'fold':f,'train_households':len(train),'test_households':len(test),
          'joint_conditional_year_NLL_nats':float(scores[0]/scores[2]),'factorized_year_NLL_nats':float(scores[1]/scores[2]),'test_weight_mass':float(scores[2])})
    total=sum(d['test_weight_mass'] for d in folds)
    a=sum(d['joint_conditional_year_NLL_nats']*d['test_weight_mass'] for d in folds)/total
    b=sum(d['factorized_year_NLL_nats']*d['test_weight_mass'] for d in folds)/total
    report={'source_households':len(records),'folds':folds,'joint_conditional_year_NLL_nats':a,
      'factorized_year_NLL_nats':b,'delta_joint_minus_factorized':a-b,
      'primary_score':'effective_building_year_epoch conditional onfixedN/G/R/area_bin; joint versus its year marginal',
      'same_joint_marginals_and_hyperparameters':True,'training_only_weight_normalization':True,
      'global_cell_pseudocount':.1,'local_equivalent_household_shrinkage':10,'survey_weights_used_for_scoring':True,
      'source_owned_direct_area_proxy_subframe_only':True,'PSU_sampling_standard_error_available':False,
      'development_holdout_not_final_blind_validation':True,'national_stock_or_energy_validation':False}
    save('YEAR_JOINT_HOLDOUT.json',report);return report

def main():
    from evidence_guard import ensure_unsealed
    ensure_unsealed(OUT)
    meta=json.loads((BASE/'chfs_admission_20261003/private_metadata/chfs2021_hh_pub_v0_20260131_metadata.json').read_text())['variable_labels']
    cols=['hhid','c1000ak']+[k for k in meta if any(k.startswith(p) for p in ['c2012a_','c2006_','c2008ab_','c2000x_']) and '_ex' not in k]
    raw=rb.read('hh',cols).set_index('hhid').to_dict('index');frame=rb.load_bridge_pool()
    status=collections.Counter();auxstatus=collections.Counter();types=collections.Counter();yearrecords=[];nonowned=[];weightedstatus=collections.defaultdict(float)
    all_owner_years=[];existing=0
    for d in frame.to_dict('records'):
        if d['visit_year']!=2021:continue
        weight=rb.number(d['weight']);n,g=[rb.number(d[k]) for k in ['co_resident_count','generation_count_proxy']]
        if weight is None or weight<=0 or not d['residence_complete'] or not d['reported_roster_consistent_or_unasked'] or d['active_member_conflict'] or n is None or n<1 or g is None:continue
        sr=derive_year(raw[d['_local_hhid']],d,2021);status[sr['status']]+=1;weightedstatus[sr['status']]+=weight
        base={'N':int(n),'G':int(g),'province':d['province'],'weight':weight,'fold':fold(d['_local_hhid'])}
        if sr['status']=='nonowned_reported_age_interval':nonowned.append({**base,'age_interval':sr['age_interval_years']})
        if sr['status']=='reported_effective_year_reference_compatible':all_owner_years.append({**base,'Y':epoch(sr['exact_reported_year'])})
        R,A=[rb.number(d[k]) for k in ['room_count_h7_proxy','area_candidate_m2']]
        if not d['area_scope_supported'] or d['area_origin']!='c2003_source_building_area' or R is None or not 1<=R<=99 or A is None or not 1<=A<=2000:continue
        existing+=1;auxstatus[sr['status']]+=1
        if sr['status']=='reported_effective_year_reference_compatible':
            yy=epoch(sr['exact_reported_year']);types[yy]+=1
            yearrecords.append({**base,'R':min(int(R),10),'B':area_bin(A/n),'Y':yy,
              'reported_effective_year':sr['exact_reported_year'],'source_exact_area_private_m2':A,
              'year_is_exact_source_building_compliance_or_original_construction':False})
    assert existing==1779,'exact_existing_source_filters_preserved'
    PRIVATE.mkdir(parents=True,exist_ok=True)
    for name,data in [('OWNED_JOINT_YEAR_SOURCE_PRIVATE.json',yearrecords),('NONOWNED_AGE_INTERVAL_SOURCE_PRIVATE.json',nonowned),('OWNED_YEAR_SOURCE_PRIVATE.json',all_owner_years)]:
        (PRIVATE/name).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    report={'city_source_codes':[111,112],'visit_year':2021,'housing_reference_year':2020,'selected_samevisit_source_household_status':dict(status),
      'selected_samevisit_source_original_weight_mass':dict(weightedstatus),'existing_owned_direct_room_area_subframe':existing,
      'owned_auxiliary_year_status':dict(auxstatus),'admitted_owned_joint_year_proxy_households':len(yearrecords),
      'owned_effective_year_epoch_counts':dict(types),'owned_joint_year_Kish_ESS':kish(yearrecords),
      'current_nonowned_age_interval_records':len(nonowned),'missing_and_unasked_not_random_missing_assumption':True,
      'completion_vs_major_renovation_year_not_separately_identified':True,'energy_code_compliance_not_observed':True,
      'source_household_ids_or_microdata_exported_in_docs':False,'source_years_reclassified_as_generated_household_observations':False}
    save('YEAR_SOURCE_ADMISSION.json',report);holdout=evaluate(yearrecords)
    body=json.loads((BASE/'idf_joint_production_20261005/HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json').read_text())['profiles']
    rows=[];sameprov=0;samenational=0;owned_whole=0
    for p in body:
        N=p['family']['resident_count'];G=p['family']['generation_count'];R=min(p['housing']['H7_independent_natural_rooms_design'],10);B=p['housing']['percap_area_bin_index']
        nat=[r for r in yearrecords if (r['N'],r['G'],r['R'],r['B'])==(N,G,R,B)]
        local=[r for r in nat if r['province']==p['province']];own=p['family']['tenure_source_prior_code']==1 and p['housing']['shared_household_count_design']==1
        sameprov+=bool(local);samenational+=bool(nat);owned_whole+=own
        age=[r for r in nonowned if r['province']==p['province'] and (r['N'],r['G'])==(N,G)]
        rows.append({'household_id':p['slot_id'],'province':p['province'],'N':N,'G':G,'R_proxy_bucket':R,'B':B,
          'same_province_NG_RB_source_year_count':len(local),'same_province_source_Kish_ESS':kish(local),
          'national_NG_RB_source_year_count':len(nat),'national_source_Kish_ESS':kish(nat),
          'owned_whole_auxiliary_frame_matches_role_design':own,'owned_prior_transport_to_other_tenure_or_sharing_required':not own,
          'same_province_NG_nonowned_age_interval_source_count':len(age),'source_year_observed_for_this_generated_role':None,
          'household_year_assigned_this_phase':False,'support_exists_is_not_transport_validation':True})
    save('YEAR_SUPPORT1000.json',{'households':rows,'same_province_NG_RB_year_supported_slots':sameprov,'national_NG_RB_year_supported_slots':samenational,
      'roles_with_source_owner_prior_and_exclusive_reference_world':owned_whole,
      '1000_household_years_or_national_joint_distribution_identified':False,'new_complete_actor_packages':0})
    print(json.dumps({'source_admission':report,'year_holdout':{k:v for k,v in holdout.items() if k!='folds'},'same_province_supported_slots':sameprov,'national_supported_slots':samenational},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
