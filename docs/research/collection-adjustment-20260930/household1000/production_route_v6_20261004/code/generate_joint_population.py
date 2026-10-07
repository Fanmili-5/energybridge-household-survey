"""Generate a new1000 ordinary-city candidate from joint household motifs.

Statistical counts are census-calibrated. Source joint traits are auxiliary
CHFS proxies. Missing source facts and designed role-world facts are separate.
This is NOT a complete actor/IDF release.
"""
import collections
import copy
import hashlib
import json
import math
import random
from functools import lru_cache
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp, brentq
from scipy.sparse import lil_matrix
from joint_motifs import load_source, weighted_choice, LEVEL, coarse_age_pmf
from build_census_frame import apportion

OUT = Path(__file__).resolve().parent.parent
SEED = 20261004
PC_LO = np.array([1,9,13,17,20,30,40,50,60,70],float)
PC_HI = np.array([8,12,16,19,29,39,49,59,69,np.inf],float)


def save(name,d):
    (OUT/name).write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def digest(x):
    return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def atom_age_order_supported(record):
    """Admission for this conventional age-ordered ROLE design, not a claim
    that step/adoptive or anomalous source relations are impossible in China.
    Unsupported prior mass is audited, never interpreted as population absence.
    """
    root=next(a for a in record['atom'] if a[0]==1)
    lo,hi=root[2]*5,root[3]*5+4
    for a in record['atom']:
        if a[0] in [3,5]: hi=min(hi,a[3]*5+3)
        if a[0] in [6,8]: lo=max(lo,a[2]*5+1)
    return lo<=hi


@lru_cache(maxsize=None)
def singleton_reference(province):
    df = pd.read_excel(OUT/'raw/A0502a.xls',header=None).fillna('')
    row = next(r for r in df.values.tolist() if ''.join(str(r[0]).split()) == province and isinstance(r[1],(int,float)))
    ranges = [(0,14),(15,19),(20,24),(25,29),(30,34),(35,39),(40,44),(45,49),(50,54),(55,59),(60,64),(65,99)]
    values,weights = [],[]
    assert len(row[4:]) == len(ranges)*3
    for i,bounds in enumerate(ranges):
        total,male,female = row[4+i*3:7+i*3]
        assert total == male+female
        for sex,w in [(1,male),(2,female)]:
            if w: values.append((sex,*bounds));weights.append(float(w))
    return values,weights


def draw_family(slot,records,rng):
    n,g = slot['exact_member_count'], int(slot['generation_category'].replace('+',''))
    singleton = None
    if n == 1:
        values,weights = singleton_reference(slot['province'])
        sex,lo,hi = weighted_choice(rng,values,weights)
        # The census identifies65+, not a uniform65--99 density. Use a
        # same-visit, same-sex singleton coarse-age prior within that open bin.
        if lo == 65:
            tail = collections.defaultdict(float)
            for r in records:
                if r['N'] == 1 and r['visit_year'] == 2021 and r['atom'][0][1] == sex:
                    for a,w in coarse_age_pmf(r['atom'][0]).items():
                        if a >= 65: tail[a//5] += r['weight']*w
            if not tail: raise ValueError('singleton65plus_prior_unidentified; no_uniform_tail_substitution')
            bin_id = weighted_choice(rng,list(tail),list(tail.values()))
            age = rng.randint(bin_id*5,bin_id*5+4)
            hi = None
        else:
            age = rng.randint(lo,hi)
        singleton = sex,age,lo,hi
    candidates = [r for r in records if r['N'] == n and r['G'] == g and r['visit_year'] == 2021]
    if singleton:
        sex,age,_,_ = singleton
        candidates = [r for r in candidates if r['atom'][0][1] == sex and r['atom'][0][2] <= age//5 <= r['atom'][0][3]]
    route = 'samevisit2021_exact_NG_joint_motif_national'
    if not candidates and n > 1:
        candidates = [r for r in records if r['N'] == n and r['G'] == g]
        route = 'exact_NG_joint_motif_visit_year_fallback'
    graft = False
    if not candidates and n > 1:
        compatible = [r for r in records if r['G'] == g and r['N'] <= n]
        if not compatible: raise ValueError('no_supported_G_motif; target_slot_must_not_be_replaced')
        closest = max(r['N'] for r in compatible)
        candidates = [r for r in compatible if r['N'] == closest]
        route = 'same_G_nearest_lower_N_joint_motif_graft_design'
        graft = True
    # Aggregate identical coarsened atoms BEFORE drawing. No raw donor selected.
    aggregates = {}
    for r in candidates:
        key = (r['atom'],r['economic_member_count'],r['income_bin'],r['asset_groups'],r['tenure_code'],r['visit_year'])
        if key not in aggregates: aggregates[key] = {'weight':0.,'source_count':0}
        aggregates[key]['weight'] += r['weight'];aggregates[key]['source_count'] += 1
    if aggregates:
        key = weighted_choice(rng,list(aggregates),[v['weight'] for v in aggregates.values()])
    else:
        assert singleton is not None
        sex,age,_,_ = singleton
        key = (((1,sex,age//5,age//5,None),),None,None,(None,None,None),None,None)
        aggregates[key] = {'weight':0.,'source_count':0}
        route = 'census_singleton_demographics; same_age_sex_source_attributes_unidentified'
    atom,economic_n,income,assets,tenure,visit = key
    atom = list(atom)
    if graft:
        # Extrapolation for sparse tails; never duplicate a spouse or parent.
        # Sibling of ego (G0) is used only if no observed child block exists.
        blocks = [a for a in atom if a[0] == 6]
        if not blocks:
            root = next(a for a in atom if a[0] == 1)
            blocks = [(10,root[1],root[2],root[3],root[4])]
        while len(atom) < n: atom.append(weighted_choice(rng,blocks,[1]*len(blocks)))
    assert len(atom) == n and len({LEVEL[a[0]] for a in atom}) == g
    atom.sort(key=lambda a:(a[0],a[2],a[3],a[1],-1 if a[4] is None else a[4]))
    if n == 1:
        # Census singleton age/sex has direct city-only evidence. Its ordinary
        # conditioning remains modeled; within-bin exact ages are role designs.
        sex,age,lo,hi = singleton
        members = [{'member_id':slot['slot_id']+'-m01','ego_relation_code':1,'sex': 'male' if sex == 1 else 'female',
                    'age_years':age,'generation_level':0,
                    'age_evidence':'new_draw_from_allcity_singleton_age_sex; ordinary_conditioning_is_model',
                    'age_bin_reference':[lo,hi],'current_work_source_proxy':None}]
        members[0]['age_tail_density_evidence'] = ('samevisit2021_singleton_same_sex_coarsened_CHFS_auxiliary_prior'
                                                   if lo == 65 else 'uniform_within_finite_census_bin_role_design')
        # Other traits of an adult source singleton cannot silently become a
        # observed income/job/asset package for a census-designed minor singleton.
        if age < 20:
            income,assets = None,(None,None,None)
            route += '; minor_singleton_source_finance_assets_unidentified'
    else:
        for attempt in range(1000):
            members = []
            for i,a in enumerate(atom):
                b = a[2] if rng.random() < .5 else a[3]
                members.append({'member_id':slot['slot_id']+f'-m{i+1:02}','ego_relation_code':a[0],
                                'sex':'male' if a[1] == 1 else 'female','age_years':rng.randint(b*5,b*5+4),
                                'generation_level':LEVEL[a[0]],'age_bin_reference':[b*5,b*5+4],
                                'age_evidence':'new_within_bin_role_age_from_joint_relation_sex_age_motif',
                                'current_work_source_proxy':a[4]})
            root = next(m for m in members if m['ego_relation_code'] == 1)
            elder_ok = all(m['age_years'] > root['age_years'] for m in members if m['ego_relation_code'] in [3,5])
            child_ok = all(m['age_years'] < root['age_years'] for m in members if m['ego_relation_code'] in [6,8])
            if elder_ok and child_ok: break
        else:
            raise ValueError('joint_atom_age_order_infeasible; preserve_target_and_report_not_replace')
    root = next(m for m in members if m['ego_relation_code'] == 1)
    labels = {2:'partner_or_spouse_of',3:'parent_of',4:'parent_of_partner_of',5:'grandparent_of',
              6:'child_of',7:'child_partner_of',8:'grandchild_of',9:'grandchild_partner_of',10:'sibling_of'}
    relations = [{'subject':m['member_id'],'object':root['member_id'],'type':labels[m['ego_relation_code']],
                  'evidence':'new_role_relation_from_joint_coarsened_source_pattern; not_a_real_source_family'}
                 for m in members if m['ego_relation_code'] != 1]
    weights = np.array([v['weight'] for v in aggregates.values()])
    return {'population_reference_year':2020,'role_age_reference_year':2020,
            'source_joint_attribute_visit_year':visit,'one_year_age_transport_is_model':visit != 2020,
            'resident_member_ids':[m['member_id'] for m in members],'resident_count':n,
            'reference_member_id':root['member_id'],'reference_member_is_observed_source_household_head':False,
            'generation_count':g,'members':members,'ego_relationships':relations,
            'ego_relative_family_roles_complete':True,'full_biological_pairwise_parentage_identified':False,
            'unidentified_parentage_completion_policy':'retain_ego_relation; extra_branch_choice_requires_explicit_world_scenario',
            'nonfamily_resident_source_coverage':'CHFS_omits_helpers_and_boarders; rate_unidentified_no_absence_claim',
            'co_residence_prior_is_census_observation':False,
            'economic_family_reference_count':economic_n,
            'economic_count_equals_generated_resident_count':economic_n == n and not graft,
            'income_reference_bin':income,'income_scope':'source_economic_family_total; never_divided_by_resident_count_as_income_percap',
            'income_calendar_reference_year':None,
            'income_period_evidence':'derived_master_total; exact_calendar_period_not_assumed_from_interview_year; not_generated2020_role_income',
            'modern_asset_group_2_5_19':list(assets) if visit == 2021 else [None,None,None],
            'modern_group_evidence':'same_coarsened_source_atom_when2021_and_answer_known; installation_and_counts_unknown',
            'tenure_source_prior_code':tenure,'reference_route':route,'motif_graft_extrapolation':graft,
            'motif_group_hash':digest(key),'source_matching_households':len(candidates),
            'selected_coarse_atom_source_count':aggregates[key]['source_count'],
            'aggregate_atom_effective_pattern_count':float(weights.sum()**2/(weights@weights)) if weights.sum() > 0 else 0.,
            'source_pool_Kish_ESS':float(sum(r['weight'] for r in candidates)**2/sum(r['weight']**2 for r in candidates)) if candidates else 0.,
            'real_household_record_exported':False,
            'exact_private_birthyears_areas_incomes_exported':False,
            'categorical_joint_source_pattern_used_as_prior':True}


def assign_census_housing(profiles, frame, records, rng):
    provinces = frame['provinces']; pindex={p:i for i,p in enumerate(provinces)}
    room_counts=np.array(frame['ordinary_room10_counts'],float)
    gen_room=np.array(frame['ordinary_generation_room_counts'],float)
    room_target=apportion(1000,room_counts.sum(0))
    # Joint GxH7-bin controls; detailed5+ tail completion inferred within province.
    n=len(profiles); m=n*10
    matrix=lil_matrix((n+10+31*5*5,m));low=[];high=[];row=0
    costs=np.empty(m)
    for i,profile in enumerate(profiles):
        p=pindex[profile['province']];g=int(profile['generation_category'].replace('+',''))-1
        probs=room_counts[p].copy()
        for b in range(10):
            broad=min(b,4)
            probs[b]=gen_room[p,g,broad]*(1 if b<4 else room_counts[p,b]/max(room_counts[p,4:].sum(),1))
        probs=probs/max(probs.sum(),1)
        for b in range(10):costs[i*10+b]=-math.log(max(probs[b],1e-12))+rng.random()*1e-8
        matrix[row,i*10:(i+1)*10]=1;low.append(1);high.append(1);row+=1
    for b in range(10):
        for i in range(n):matrix[row,i*10+b]=1
        low.append(room_target[b]);high.append(room_target[b]);row+=1
    for p in range(31):
        for g in range(5):
            for b in range(5):
                for i,profile in enumerate(profiles):
                    if pindex[profile['province']]==p and int(profile['generation_category'].replace('+',''))-1==g:
                        for detailed in ([b] if b<4 else range(4,10)):matrix[row,i*10+detailed]=1
                expected=gen_room[p,g,b]/sum(frame['ordinary_household_counts'])*1000
                low.append(math.floor(expected));high.append(math.ceil(expected));row+=1
    fit=milp(costs,integrality=np.ones(m),bounds=Bounds(np.zeros(m),np.ones(m)),
             constraints=LinearConstraint(matrix.tocsr(),low,high),options={'time_limit':60,'mip_rel_gap':.001})
    if fit.x is None:raise ValueError('H7_assignment_infeasible:'+fit.message)
    choices=np.argmax(fit.x.reshape(n,10),axis=1)
    assert np.allclose(matrix@np.rint(fit.x),np.clip(matrix@np.rint(fit.x),low,high))
    for profile,b in zip(profiles,choices):
        profile['housing']={'H5':1,'H7_bin_detailed':str(b+1) if b<9 else '10+',
                            'H7_independent_natural_rooms_design':int(b+1),
                            'H7_exact_tail_is_design':bool(b==9),
                            'H7_evidence':'census_A0801a_detailed_and_A0803a_generation_broad_margins; association_with_N_not_identified',
                            'census_source_household_H6_observed':None,
                            'source_sharing_H6_unknown_not_overwritten':True,
                            'functional_layout_generated':False,'IDF_binding_approved':False}
    # Build an N->PC-area-bin prior from samevisit whole occupied dwellings ONLY.
    # It is a weak auxiliary prior; hard area controls come from city census.
    prior=np.ones((max(p['exact_member_count'] for p in profiles)+1,10),float)
    supported=0
    for r in records:
        if r['visit_year']!=2021 or not r['area_whole_scope_supported'] or r['area_proxy'] is None or not 1<=r['area_proxy']<=2000:continue
        if r['N']>=len(prior):continue
        pc=r['area_proxy']/r['N'];b=int(np.searchsorted([8,12,16,19,29,39,49,59,69],pc,side='left'))
        prior[r['N'],b]+=r['weight'];supported+=1
    prior/=prior.sum(1,keepdims=True)
    area_counts=np.array(frame['ordinary_percap_area10_counts'],float); area_target=apportion(1000,area_counts.sum(0))
    # The national mean is rounded at source. Do not hardcode a fresh value.
    _,national_rows,_ = __import__('build_census_frame').table('A0112a')
    total_area=round(float(national_rows['全国'][3])*len(profiles))
    upper_pc=np.where(np.isfinite(PC_HI),PC_HI,total_area)
    matrix=lil_matrix((n+10+31*10+2,m));low=[];high=[];row=0;costs=np.empty(m)
    for i,p in enumerate(profiles):
        N=p['exact_member_count']
        for b in range(10):costs[i*10+b]=-math.log(max(prior[N,b],1e-15))+rng.random()*1e-8
        matrix[row,i*10:(i+1)*10]=1;low.append(1);high.append(1);row+=1
    for b in range(10):
        for i in range(n):matrix[row,i*10+b]=1
        low.append(area_target[b]);high.append(area_target[b]);row+=1
    for p in range(31):
        for b in range(10):
            for i,profile in enumerate(profiles):
                if pindex[profile['province']]==p:matrix[row,i*10+b]=1
            expected=area_counts[p,b]/sum(frame['ordinary_household_counts'])*1000
            low.append(math.floor(expected));high.append(math.ceil(expected));row+=1
    for i,p in enumerate(profiles):
        for b in range(10):matrix[row,i*10+b]=PC_LO[b]*p['exact_member_count']
    low.append(-np.inf);high.append(total_area);row+=1
    for i,p in enumerate(profiles):
        for b in range(10):matrix[row,i*10+b]=upper_pc[b]*p['exact_member_count']
    low.append(total_area);high.append(np.inf);row+=1
    fit2=milp(costs,integrality=np.ones(m),bounds=Bounds(np.zeros(m),np.ones(m)),
              constraints=LinearConstraint(matrix.tocsr(),low,high),options={'time_limit':60,'mip_rel_gap':.001})
    if fit2.x is None:raise ValueError('area_assignment_infeasible:'+fit2.message)
    area_bin=np.argmax(fit2.x.reshape(n,10),axis=1)
    assert np.allclose(matrix@np.rint(fit2.x),np.clip(matrix@np.rint(fit2.x),low,high))
    Ns=np.array([p['exact_member_count'] for p in profiles])
    lower=PC_LO[area_bin]*Ns;upper=upper_pc[area_bin]*Ns
    # Maximum area is implied by this finite cohort's total, not a stock cap.
    upper=np.minimum(upper,total_area-lower.sum()+lower)
    midpoint=np.array([4.5,10.5,14.5,18,24.5,34.5,44.5,54.5,64.5,85])
    initial=midpoint[area_bin]*Ns
    variance=(np.array([2,1,1,1,3,3,3,3,3,20])[area_bin]*Ns)**2
    # Coarse conditional source density is an auxiliary prior, especially for
    # the open70+ bin. It replaces an unsupported universal85m2/person point.
    density=collections.defaultdict(lambda:collections.defaultdict(float))
    source_counts=collections.Counter()
    for r in records:
        if r['visit_year']!=2021 or not r['area_whole_scope_supported'] or r['area_proxy'] is None or not 1<=r['area_proxy']<=2000:continue
        pc=r['area_proxy']/r['N'];b=int(np.searchsorted([8,12,16,19,29,39,49,59,69],pc,side='left'))
        #10m2 whole-dwelling bins are exported only as aggregate prior support.
        density[(r['N'],b)][int(r['area_proxy']//10)] += r['weight']
        source_counts[(r['N'],b)] += 1
    density_supported=0
    for i,(N,b) in enumerate(zip(Ns,area_bin)):
        available={k:w for k,w in density[(int(N),int(b))].items() if min((k+1)*10,upper[i])>=max(k*10,lower[i])}
        if available:
            k=weighted_choice(rng,list(available),list(available.values()))
            initial[i]=rng.uniform(max(k*10,lower[i]),min((k+1)*10,upper[i]));density_supported+=1
            if b==9:
                values=np.array([np.clip(k*10+5,lower[i],upper[i]) for k in available]);ww=np.array(list(available.values()))
                variance[i]=max(float(np.average((values-np.average(values,weights=ww))**2,weights=ww)),(20*N)**2)
    f=lambda lam:np.clip(initial-lam*variance,lower,upper).sum()-total_area
    lam=brentq(f,-1e5,1e5)
    areas=np.clip(initial-lam*variance,lower,upper);integer=np.floor(areas+1e-8).astype(int)
    remainder=total_area-int(integer.sum())
    order=sorted(range(n),key=lambda i:(-(areas[i]-integer[i]),i))
    for i in order:
        if not remainder:break
        if integer[i]+1<=upper[i]+1e-8:integer[i]+=1;remainder-=1
    assert remainder==0 and integer.sum()==total_area and np.all(integer>=lower) and np.all(integer<=upper)
    for p,b,a in zip(profiles,area_bin,integer):
        p['housing'].update(H6_census_building_area_design_m2=int(a),percap_area_bin_index=int(b),
                            H6_evidence='new_census_calibrated_area_design; not_inverse_of_CHFS_shared_area',
                            H6_scope='household_census_building_area_allocation; whole_dwelling_area_not_identified_until_occupancy_world_chosen',
                            gross_to_IDF_net_area_ratio=None,shared_occupancy_scenario=None,
                            area_within_bin_evidence='bounded_projection_from_coarsened_samevisit_whole_area_N_bin_prior_when_supported; fallback_bin_reference_design; not_observed_ordinary_city_conditional_density')
    return {'H7_solver_status':int(fit.status),'H7_solver_message':fit.message,'H7_mip_gap':float(fit.mip_gap),
            'percap_area_solver_status':int(fit2.status),'percap_area_solver_message':fit2.message,
            'percap_area_mip_gap':float(fit2.mip_gap),'H7_detailed_quotas':room_target.tolist(),
            'percap_area_quotas':area_target.tolist(),'building_area_sum_design_m2':int(integer.sum()),
            'source_N_area_prior_supported_records':supported,
            'within_bin_density_source_supported_slots':density_supported,
            'within_bin_density_projection_mean_abs_change_m2':float(np.mean(abs(integer-initial))),
            'within_bin_density_projection_max_abs_change_m2':float(np.max(abs(integer-initial))),
            'PCbin_operator':'robust_common_interior_of_plausible_grouping_conventions; exact_NBS_rounding_operator_not_assumed_identified',
            'area_prior_weights_are_not_population_frequency_estimates':True,
            'area_bin_and_room_census_margins_are_calibration_not_independent_validation':True}


def main():
    rng=random.Random(SEED); records,qc=load_source()
    unsupported=[r for r in records if not atom_age_order_supported(r)]
    qc['prior_rows_outside_conventional_age_order_role_support']=len(unsupported)
    qc['outside_role_support_weighted_source_mass']=sum(r['weight'] for r in unsupported)/sum(r['weight'] for r in records)
    qc['outside_role_support_is_not_proof_of_invalid_or_absent_real_households']=True
    records=[r for r in records if atom_age_order_supported(r)]
    slots=json.loads((OUT/'ORDINARY_ALLOCATION1000.json').read_text())['slots']
    frame=json.loads((OUT/'ORDINARY_CITY_FRAME.json').read_text());profiles=[]
    for slot in slots:
        profiles.append({**slot,'family':draw_family(slot,records,rng),
                         'stage_version':'JOINT_FAMILY_CENSUS_HOUSING_20261004_V6_CANDIDATE',
                         'complete_actor_card':False,'physical_IDF_generated':False})
    report=assign_census_housing(profiles,frame,records,rng)
    assert len(profiles)==1000 and sum(len(p['family']['members']) for p in profiles)==2524
    body={'schema':'eb.census_calibrated_joint_household_candidate.v6','seed':SEED,
          'target':frame['target'],'profile_reference_year':2020,'auxiliary_joint_attribute_source_year':2021,
          'year_transport_identity':'2020_census_constraints_plus_explicit_2021_attribute_proxy_transport; not_observed_2020_microdata',
          'generation_method':'joint_relation_sex_age_income_group_motif_and_census_constrained_housing',
          'source_QC':qc,'housing_calibration':report,'profiles':profiles,
          'new_complete_actor_packages':0,'new_IDF_bindings':0,'collection_release':False,'training_release':False,
          'national_full_joint_representativeness_validated':False}
    save('HOUSEHOLDS1000_JOINT_CANDIDATE.json',body)
    summary={'new_candidate_households':len(profiles),'new_candidate_residents':2524,
             'all_ordinary_new_frame':True,'ego_relative_family_roles_complete':1000,
             'full_pairwise_biological_parentage_observed':0,
             'grafted_tail_motifs':sum(p['family']['motif_graft_extrapolation'] for p in profiles),
             'source2022_family_prior_fallbacks':sum(p['family']['source_joint_attribute_visit_year']==2022 for p in profiles),
             'minor_singletons':sum(p['exact_member_count']==1 and p['family']['members'][0]['age_years']<20 for p in profiles),
             'H6_design_known_from_census_calibration':1000,'H7_design_known':1000,
             'new_IDFs':0,'complete_actor_packages':0,'source_unknowns_preserved':True,
             'housing_calibration':report,'scientific_benchmark_admitted':False}
    save('GENERATION_RESULT.json',summary);print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__ == '__main__': main()
