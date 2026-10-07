"""Joint room/area/reference-layout assignment under unchanged census controls.

Survey SHI is a proxy, not observed census H7. Sharing q is an engineering
scenario penalized by complexity, not an estimated Chinese sharing rate.
"""
import collections,copy,hashlib,json,math,random,sys
from pathlib import Path
import numpy as np
from scipy.optimize import Bounds,LinearConstraint,milp,brentq
from scipy.sparse import lil_matrix
from reference_world import minimum_area,sized_world

OUT=Path(__file__).resolve().parent.parent;BASE=OUT.parent
sys.path.insert(0,str(BASE/'chfs_census_bridge_20261003'))
import run_bridge as rb
sys.path.insert(0,str(BASE/'production_route_v6_20261004/code'))
from build_census_frame import apportion

LO=np.array([1,9,13,17,20,30,40,50,60,70],float)
HI=np.array([8,12,16,19,29,39,49,59,69,np.inf],float)
SEED=20261005
def save(name,d):(OUT/name).write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def fold(h):return int(hashlib.sha256(('EB_HOUSING_JOINT_PROXY_20261005|'+str(h)).encode()).hexdigest(),16)%5
def pcbin(pc):return int(np.searchsorted([8,12,16,19,29,39,49,59,69],pc,side='left'))

def balance_weighted_area(integer,lower,upper,profiles,total_area=92170):
    """Global bounded integer rounding for the population-weighted estimand.

    Official mean92.17 is published to2decimals. Its +/-0.005 interval is
    a declared nearest-rounding reference convention, not identified raw data.
    Use a small numerical inset so engine/serialization do not hit the edge.
    """
    n=len(integer);w=np.array([p['relative_population_weight'] for p in profiles]);old=integer.copy()
    residents=np.array([p['family']['resident_count'] for p in profiles]);t=2*n
    A=lil_matrix((1+4*n,2*n+1));A[0,:n]=w
    low=[total_area-.0049*w.sum()];high=[total_area+.0049*w.sum()]
    for i in range(n):
        A[1+4*i,i]=1;A[1+4*i,n+i]=-1;low.append(-np.inf);high.append(int(old[i]))
        A[2+4*i,i]=-1;A[2+4*i,n+i]=-1;low.append(-np.inf);high.append(-int(old[i]))
        A[3+4*i,i]=1;A[3+4*i,t]=-residents[i];low.append(-np.inf);high.append(int(old[i]))
        A[4+4*i,i]=-1;A[4+4*i,t]=-residents[i];low.append(-np.inf);high.append(-int(old[i]))
    lb=np.r_[lower,np.zeros(n+1)];ub=np.r_[upper,np.full(n+1,np.inf)]
    integer_mask=np.r_[np.ones(n),np.zeros(n+1)];constraints=LinearConstraint(A.tocsr(),low,high)
    first=milp(np.r_[np.zeros(2*n),1.],integrality=integer_mask,bounds=Bounds(lb,ub),
      constraints=constraints,options={'time_limit':60,'mip_rel_gap':0.0})
    if first.x is None:raise ValueError('weighted_area_minimax_projection_infeasible:'+first.message)
    ub[-1]=first.x[-1]+1e-6
    fit=milp(np.r_[np.zeros(n),np.ones(n),0.],integrality=integer_mask,bounds=Bounds(lb,ub),
      constraints=constraints,options={'time_limit':60,'mip_rel_gap':0.0})
    if fit.x is None:raise ValueError('weighted_area_moment_joint_correction_infeasible:'+fit.message)
    answer=np.rint(fit.x[:n]).astype(int)
    assert np.all(answer>=lower) and np.all(answer<=upper)
    assert abs(w@answer/w.sum()-total_area/n)<=.0049+1e-8
    save('UNWEIGHTED_AREA_ASSIGNMENT_BEFORE_CORRECTION.json',{'household_areas':[{ 'household_id':p['slot_id'],'area_design_m2':int(A)} for p,A in zip(profiles,old)],'source_values_are_generated_reference_designs_not_microdata':True})
    return answer,{'method':'lexicographic_global_integer_minimax_percap_area_change_then_minimum_total_absolute_change; preserve_bins_and_geometry',
      'regularizer_is_design_not_statistical_confidence':True,
      'minimax_solver_status':int(first.status),'minimax_mip_gap':float(first.mip_gap),
      'maximum_percap_area_change_m2':float(max(abs(answer-old)/residents)),
      'solver_status':int(fit.status),'solver_message':fit.message,'mip_gap':float(fit.mip_gap),
      'population_weight_sum':float(w.sum()),'official_rounded_reference_mean_m2':total_area/n,
      'rounding_halfwidth_reference_m2':.005,'solver_numerical_inset_halfwidth_m2':.0049,
      'rounding_operator_is_reference_convention_not_source_raw_mean_observation':True,
      'estimand':'population mean restored with province weights; unweighted cohort total is not an additional official moment',
      'before_weighted_mean_m2':float(w@old/w.sum()),'after_weighted_mean_m2':float(w@answer/w.sum()),
      'unweighted_mean_m2':float(np.mean(answer)),'changed_households':int(np.count_nonzero(answer!=old)),
      'mean_absolute_change_m2':float(np.mean(abs(answer-old))),'maximum_absolute_change_m2':int(max(abs(answer-old))),
      'all_family_room_PC_bin_and_sharing_assignments_preserved':True}

def source():
    frame=rb.load_bridge_pool();rows=[];qc=collections.Counter()
    for d in frame.to_dict('records'):
        if d['visit_year']!=2021:continue
        if not d['area_scope_supported'] or d['area_origin']!='c2003_source_building_area':continue
        weight=rb.number(d['weight'])
        if weight is None or weight<=0 or not d['residence_complete'] or not d['reported_roster_consistent_or_unasked'] or d['active_member_conflict']:continue
        n,g,r,a=[rb.number(d[k]) for k in ['co_resident_count','generation_count_proxy','room_count_h7_proxy','area_candidate_m2']]
        if n is None or n<1 or g is None or r is None or not 1<=r<=99 or a is None or not 1<=a<=2000:continue
        rows.append({'N':int(n),'G':int(g),'R':min(int(r),10),'B':pcbin(a/n),'weight':float(d['weight']),
                     'fold':fold(d['_local_hhid']),'_area_private':float(a),'_room_private':int(r)})
        if a<5*r:qc['source_reported_area_outside_selected_5m2_room_reference_domain_not_declared_invalid']+=1
    qc['accepted_samevisit_current_owned_whole_direct_building_area_room_proxy_households']=len(rows)
    qc['survey_SHI_is_not_observed_census_H7']=True
    qc['rental_shared_old_branch_population_not_represented_by_this_auxiliary_subframe']=True
    mean=np.mean([d['weight'] for d in rows])
    for d in rows:d['w']=d['weight']/mean
    return rows,dict(qc)

def distributions(records):
    glob=np.full((10,10),.1);by=collections.defaultdict(lambda:np.zeros((10,10)))
    # In CV, use training-fold weights only to set smoothing mass. A mean
    # computed across test weights would otherwise leak into prior strength.
    mean_weight=np.mean([r['weight'] for r in records])
    for r in records:
        w=r['weight']/mean_weight
        glob[r['R']-1,r['B']]+=w;by[(r['N'],r['G'])][r['R']-1,r['B']]+=w
    glob/=glob.sum()
    return glob,by

def pmf(glob,by,N,G):
    counts=by[(N,G)];return (counts+10*glob)/(counts.sum()+10)

def evaluate(records,qc):
    folds=[]
    for k in range(5):
        train=[d for d in records if d['fold']!=k];test=[d for d in records if d['fold']==k]
        glob,by=distributions(train);sums=np.zeros(3)
        for d in test:
            joint=pmf(glob,by,d['N'],d['G']);factor=joint.sum(1)[:,None]*joint.sum(0)[None,:]
            sums+=np.array([-math.log(joint[d['R']-1,d['B']]),-math.log(factor[d['R']-1,d['B']]),1])*d['weight']
        folds.append({'fold':k,'train_households':len(train),'test_households':len(test),
                      'joint_NLL_nats':sums[0]/sums[2],'factorized_NLL_nats':sums[1]/sums[2],'weight_mass':sums[2]})
    total=sum(x['weight_mass'] for x in folds)
    j=sum(x['weight_mass']*x['joint_NLL_nats'] for x in folds)/total
    f=sum(x['weight_mass']*x['factorized_NLL_nats'] for x in folds)/total
    report={'evaluation':'5fold_whole_household_SHI_and_percap_direct_building_area_proxy_joint_log_score',
      'source_QC':qc,'evaluated_households':len(records),'folds':folds,'joint_NLL_nats':j,'factorized_NLL_nats':f,
      'delta_joint_minus_factorized':j-f,'same_train_NG_conditions_same_marginals_and_same_smoothing':True,
      'global_cell_pseudocount':.1,'local_shrinkage_prior_equivalent_households':10,
      'source_weights_normalized_by_source_mean_for_smoothing_only':True,'scored_by_original_household_weights':True,
      'CV_smoothing_weight_mean_computed_with_training_fold_only':True,
      'no_test_household_used_in_training':True,'full_generator_national_population_or_real_housing_validation':False,
      'survey_design_standard_errors_available':False,'development_comparison_not_final_blind_test':True}
    save('ROOM_AREA_PROXY_HOLDOUT.json',report);return report

def assign(model='joint'):
    rng=random.Random(SEED);records,qc=source();holdout=evaluate(records,qc)
    body=json.loads((BASE/'production_route_v6_20261004/HOUSEHOLDS1000_JOINT_CANDIDATE.json').read_text())
    frame=json.loads((BASE/'production_route_v6_20261004/ORDINARY_CITY_FRAME.json').read_text())
    # The census also reports a rounded mean room count. A10+ bin does not
    # justify setting every tail home to exactly10. Balance a finite cohort
    # moment at the rounded mean and retain that design identity explicitly.
    from build_census_frame import table
    national_room_mean=float(table('A0112a')[1]['全国'][4])
    room_moment_target=round(national_room_mean*len(body['profiles']))
    rt=apportion(1000,np.array(frame['ordinary_room10_counts']).sum(0))
    tail_mean=(room_moment_target-sum((i+1)*int(rt[i]) for i in range(9)))/int(rt[9])
    if tail_mean<10:raise ValueError('room_moment_not_feasible_with_current_detailed_bin_quota')
    tail_values=sorted({math.floor(tail_mean),math.ceil(tail_mean)})
    room_choices=list(range(1,10))+tail_values
    profiles=copy.deepcopy(body['profiles']);prov=frame['provinces'];pidx={p:i for i,p in enumerate(prov)}
    groups=collections.defaultdict(list)
    for i,p in enumerate(profiles):groups[(pidx[p['province']],p['exact_member_count'],p['family']['generation_count'])].append(i)
    glob,by=distributions(records);keys=sorted(groups);total_area=92170
    cells=[];cost=[]
    for j,(p,n,g) in enumerate(keys):
        joint=pmf(glob,by,n,g);prior=joint if model=='joint' else joint.sum(1)[:,None]*joint.sum(0)[None,:]
        for r in room_choices:
            for b in range(10):
                for q in [1,2,4,8]:
                    lo=max(int(math.ceil(LO[b]*n)),int(math.ceil(minimum_area(r,q)-1e-8)))
                    hi=int(HI[b]*n) if np.isfinite(HI[b]) else total_area
                    if lo>hi:continue
                    cells.append((j,p,n,g,r,b,q,lo,hi))
                    # q penalization is a declared reference-world preference.
                    cost.append(-math.log(prior[min(r,10)-1,b]/(len(tail_values) if r>=10 else 1))+math.log(q)+rng.random()*1e-7)
    m=len(cells);matrix=lil_matrix((len(keys)+20+31*25+31*10+3,m));low=[];high=[];row=0
    gcells=collections.defaultdict(list)
    for k,c in enumerate(cells):gcells[c[0]].append(k)
    for j,key in enumerate(keys):
        matrix[row,gcells[j]]=1;low.append(len(groups[key]));high.append(len(groups[key]));row+=1
    bt=apportion(1000,np.array(frame['ordinary_percap_area10_counts']).sum(0))
    for r in range(1,11):
        for k,c in enumerate(cells):
            if min(c[4],10)==r:matrix[row,k]=1
        low.append(rt[r-1]);high.append(rt[r-1]);row+=1
    for b in range(10):
        for k,c in enumerate(cells):
            if c[5]==b:matrix[row,k]=1
        low.append(bt[b]);high.append(bt[b]);row+=1
    for p in range(31):
        for g in range(1,6):
            for rbroad in range(1,6):
                for k,c in enumerate(cells):
                    if c[1]==p and c[3]==g and min(c[4],5)==rbroad:matrix[row,k]=1
                exp=frame['ordinary_generation_room_counts'][p][g-1][rbroad-1]/frame['official_households']*1000
                low.append(math.floor(exp));high.append(math.ceil(exp));row+=1
    for p in range(31):
        for b in range(10):
            for k,c in enumerate(cells):
                if c[1]==p and c[5]==b:matrix[row,k]=1
            exp=frame['ordinary_percap_area10_counts'][p][b]/frame['official_households']*1000
            low.append(math.floor(exp));high.append(math.ceil(exp));row+=1
    group_weights={j:profiles[groups[key][0]]['relative_population_weight'] for j,key in enumerate(keys)}
    for k,c in enumerate(cells):matrix[row,k]=c[7]*group_weights[c[0]]
    low.append(-np.inf);high.append(total_area);row+=1
    for k,c in enumerate(cells):matrix[row,k]=c[8]*group_weights[c[0]]
    low.append(total_area);high.append(np.inf);row+=1
    for k,c in enumerate(cells):matrix[row,k]=c[4]
    low.append(room_moment_target);high.append(room_moment_target);row+=1
    assert row==matrix.shape[0]
    fit=milp(np.array(cost),integrality=np.ones(m),bounds=Bounds(np.zeros(m),np.array([len(groups[keys[c[0]]]) for c in cells])),
      constraints=LinearConstraint(matrix.tocsr(),low,high),options={'time_limit':120,'mip_rel_gap':.02})
    if fit.x is None:
        save('JOINT_ASSIGNMENT_FAILURE.json',{'solver_status':int(fit.status),'message':fit.message,'variables':m,'model':model,
          'no_target_household_resampled_or_removed':True,'reference_domain_may_require_additional_historical_geometry_sources':True})
        raise RuntimeError('joint_reference_assignment_failed:'+fit.message)
    x=np.rint(fit.x).astype(int);lhs=matrix@x
    assert all(a-1e-6<=v<=b+1e-6 for a,v,b in zip(low,lhs,high))
    selected=[]
    for j,key in enumerate(keys):
        choices=[]
        for k in gcells[j]:choices += [cells[k]]*int(x[k])
        assert len(choices)==len(groups[key]);rng.shuffle(choices)
        selected.extend(zip(groups[key],choices))
    selected.sort();lower=np.array([c[7] for _,c in selected],float);upper=np.array([c[8] for _,c in selected],float)
    density=collections.defaultdict(lambda:collections.defaultdict(float))
    for d in records:density[(d['N'],d['R'],d['B'])][int(d['_area_private']//10)]+=d['weight']
    initial=[];var=[];density_support=0
    for _,c in selected:
        _,p,n,g,r,b,q,lo,hi=c;weights={v:w for v,w in density[(n,min(r,10),b)].items() if min((v+1)*10,hi)>=max(v*10,lo)}
        if weights:
            binval=rng.choices(list(weights),weights=list(weights.values()))[0];value=rng.uniform(max(binval*10,lo),min((binval+1)*10,hi));density_support+=1
        else:value=float(np.clip(np.array([4.5,10.5,14.5,18,24.5,34.5,44.5,54.5,64.5,85])[b]*n,lo,hi))
        initial.append(value);var.append((max(3,20 if b==9 else 3)*n)**2)
    initial=np.array(initial);var=np.array(var,float)
    population_weights=np.array([p['relative_population_weight'] for p in profiles])
    lam=brentq(lambda a:np.clip(initial-a*var*population_weights,lower,upper)@population_weights-total_area,-1e6,1e6)
    areas=np.clip(initial-lam*var*population_weights,lower,upper)
    integer=np.rint(areas).astype(int)
    integer,weighted_area_correction=balance_weighted_area(integer,lower,upper,profiles,total_area)
    save('WEIGHTED_AREA_MOMENT_CORRECTION.json',weighted_area_correction)
    worlds=OUT/'worlds';worlds.mkdir(exist_ok=True);qcounts=collections.Counter();changes=collections.Counter()
    sys.path.insert(0,str(BASE/'benchmark_foundation_20261004/code'));from census_projection import project
    for (i,c),area in zip(selected,integer):
        j,p,n,g,r,b,q,lo,hi=c;profile=profiles[i];old=profile['housing'];world=sized_world(r,q,int(area),profile['slot_id'])
        projection=project(world);target=next(h for h in projection['households'] if h['household_id']==profile['slot_id'])
        assert target['H6_census_integer_m2']==area and target['H7_independent_natural_rooms']==r
        path=worlds/(profile['slot_id']+'.json');path.write_text(json.dumps({'world':world,'census_projection':projection},ensure_ascii=False,indent=2)+'\n')
        changes['H7_changed']+=old['H7_independent_natural_rooms_design']!=r;changes['H6_changed']+=old['H6_census_building_area_design_m2']!=area
        qcounts[q]+=1
        profile['housing']={**old,'H7_bin_detailed':str(r) if r<10 else '10+','H7_independent_natural_rooms_design':r,
          'H6_census_building_area_design_m2':int(area),'percap_area_bin_index':b,
          'H7_exact_tail_is_design':r>=10,
          'H6_scope':'target_reference_household_census_area_allocation; real_source_whole_dwelling_unknown',
          'functional_layout_generated':True,'IDF_binding_approved':False,
          'world_path':str(path.relative_to(OUT)),'shared_household_count_design':q,
          'H6_evidence':'census_controls_and_geometry_constrained_reference_design; not_observed_source_home',
          'H7_evidence':'census_controls_and_explicit_exclusive_natural_room_reference_design',
          'gross_to_net_area_ratio_for_this_world':world['usable_total_area_m2']/world['whole_unit_building_area_m2'],
          'shared_occupancy_scenario':'exclusive_reference_unit' if q==1 else f'shared_reference_unit_{q}_households',
          'room_area_source_prior':'samevisit2021_current_owned_whole_direct_area_SHI_proxy; transport_not_national_observation',
          'area_within_bin_evidence':'joint_R_B_q_reference_assignment; same_N_R_B_10m2_source_density_or_explicit_fallback; weighted_population_area_projection_and_integer_correction',
          'sleeping_operator_and_appliance_installation_world_complete':False}
        profile['population_anchor_stage_version']=profile['stage_version']
        profile['stage_version']='JOINT_REFERENCE_HOUSING_IDF_20261005'
        assert profile['family']==body['profiles'][i]['family']
    result={'1000_population_anchors_preserved':True,'residents':2524,'joint_variables':m,'solver_status':int(fit.status),
      'solver_message':fit.message,'mip_gap':float(fit.mip_gap),'joint_prior_model':model,'source_QC':qc,
      'proxy_holdout_joint_NLL':holdout['joint_NLL_nats'],'proxy_holdout_factorized_NLL':holdout['factorized_NLL_nats'],
      'room_quota':rt.tolist(),'percap_area_quota':bt.tolist(),'H6_total_m2':int(integer.sum()),
      'exact_reference_room_total':room_moment_target,'census_rounded_mean_room_count':national_room_mean,
      'tail_exact_counts_are_minimum_variance_finite_cohort_design_not_observed_tail_mean':True,
      'tail_reference_exact_values':tail_values,'tail_reference_exact_mean':tail_mean,
      'reference_worlds_generated':1000,'census_H6_H7_roundtrip_checked':1000,'q_reference_design_counts':dict(qcounts),
      'q_counts_are_not_estimated_Chinese_sharing_frequencies':True,'housing_assignment_changes':{k:int(v) for k,v in changes.items()},
      'same_N_R_B_source_density_supported_slots':density_support,
      'projection_mean_absolute_area_change_m2':float(np.mean(abs(integer-initial))),
      'area_projection_estimand':'weighted_population_mean; unweighted_cohort_mean_reported_separately',
      'unweighted_area_mean_m2':float(np.mean(integer)),
      'weighted_area_mean_m2':weighted_area_correction['after_weighted_mean_m2'],
      'weighted_area_correction':weighted_area_correction,
      'reference_geometry_only; sleeping_and_installed_services_complete':False,
      'national_joint_stock_or_physical_energy_calibration_validated':False,'complete_actor_packages':0,'scientific_benchmark_admitted':False}
    save('JOINT_HOUSING_RESULT.json',result);save('HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json',{
      'schema':'eb.joint_geometry_household_candidate.20261005','source_population_anchor_path':str(BASE/'production_route_v6_20261004/HOUSEHOLDS1000_JOINT_CANDIDATE.json'),
      'profiles':profiles,'result':result,'collection_release':False,'training_release':False})
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':assign()
