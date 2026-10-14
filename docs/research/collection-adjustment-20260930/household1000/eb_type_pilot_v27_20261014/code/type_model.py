"""Source-eligible task-world matching and explicit role policies; no inferred attitudes."""
import copy, collections
from common import *

TYPES = ('A','B','C','D','E','F')
SEED = 2026101401


def candidates(w):
    adults=[m for m in w['members'] if m['age_years']>=18]
    workers=[m for m in adults if m['employment_status']=='has_work' and m['age_years']<75]
    external=[o for o in w['operating_context']['operators'] if not o.get('resident',True)
              and 'guardian' in o['operator_id'] and o.get('roleplay_representative')]
    protected=[m for m in w['members'] if m['age_years']<6 or m['age_years']>=65]
    care=any(a['member_id']!=b['member_id'] for a in adults for b in protected)
    ev=any('ev' in d['types'] for d in w['parameter_pack']['devices'])
    allowed={'A':bool(workers),'B':bool(adults),'C':bool(adults or external),
             'D':bool(workers),'E':care,'F':bool(workers and ev)}
    return {'allowed':allowed,'adult_ids':[m['member_id']for m in adults],
            'worker_ids':[m['member_id']for m in workers],
            'external_guardian_ids':[o['operator_id']for o in external],
            'protected_candidate_ids':[m['member_id']for m in protected],
            'evidence':'source-conditioned references;work is matched proxy;care/EV access and preferences remain explicitly given'}


def allocate(worlds,minimum=5,auto_share=None,support_override=None,weighted_reference=False,fixed_assignment=None):
    """HiGHS integer projection of conditional q;population/rosters never changed."""
    import numpy as np
    from scipy.optimize import milp,Bounds,LinearConstraint
    from scipy.sparse import lil_matrix
    support=support_override or [candidates(w)for w in worlds];n=len(worlds);q=np.zeros((n,6))
    for i,row in enumerate(support):
        allowed=[k for k,t in enumerate(TYPES)if row['allowed'][t]]
        if not allowed:raise RuntimeError('unmatched source conditions:'+worlds[i]['household_id'])
        q[i,allowed]=1/len(allowed)
        if auto_share is not None and row['allowed']['A'] and row['allowed']['D']:
            total=q[i,0]+q[i,3];q[i,0]=total*(1-auto_share);q[i,3]=total*auto_share
    weights=np.array([w['population_weight']for w in worlds])if weighted_reference else np.ones(n)
    expected=(q*weights[:,None]).sum(axis=0)/weights.sum()*n;nv=6*n+12
    mat=lil_matrix((n+18,nv));lo=np.zeros(n+18);hi=np.zeros(n+18)
    for i in range(n):mat[i,i*6:(i+1)*6]=1;lo[i]=hi[i]=1
    for k in range(6):
        mat[n+k,k:6*n:6]=1;lo[n+k]=minimum;hi[n+k]=n
        mat[n+6+k,k:6*n:6]=1;mat[n+6+k,6*n+k]=-1;lo[n+6+k]=-np.inf;hi[n+6+k]=expected[k]
        mat[n+12+k,k:6*n:6]=-1;mat[n+12+k,6*n+6+k]=-1;lo[n+12+k]=-np.inf;hi[n+12+k]=-expected[k]
    assignment_support=copy.deepcopy(support)
    for w,r in zip(worlds,assignment_support):
        fixed=(fixed_assignment or {}).get(w['household_id'])
        if fixed is not None:
            if not r['allowed'][fixed]:raise RuntimeError('accepted original50 no longer feasible:'+w['household_id'])
            r['allowed']={t:t==fixed for t in TYPES}
    upper=np.concatenate([np.array([[int(r['allowed'][t])for t in TYPES]for r in assignment_support]).ravel(),np.full(12,np.inf)])
    objective=np.concatenate([np.array([rank(SEED,w['household_id'],t,'allocation-tie')%100000/100000*1e-7 for w in worlds for t in TYPES]),np.ones(12)])
    if n<=50:
        result=milp(objective,integrality=np.concatenate([np.ones(6*n),np.zeros(12)]),bounds=Bounds(np.zeros(nv),upper),constraints=LinearConstraint(mat.tocsc(),lo,hi),options={'time_limit':60,'mip_rel_gap':1e-8})
        if result.status!=0:raise RuntimeError('allocation not proven optimal:'+str(result.message))
        x=np.rint(result.x[:6*n]).reshape(n,6).astype(int)
        solver_details={'method':'joint HiGHS MILP development50','count_solver_status':int(result.status)}
    else:
        # Hall subset capacities are necessary and sufficient for a feasible
        # household-to-type bipartite assignment with these integer demands.
        # All63 nonempty subsets are included, not just marginal capacities.
        # Solve the small count problem exactly before deterministic min-cost
        # assignment, avoiding thousands of interchangeable branching choices.
        from scipy.optimize import linprog
        small=[];lower=[];higher=[]
        row=np.zeros(18);row[:6]=1;small.append(row);lower.append(n);higher.append(n)
        for mask in range(1,64):
            ks=[k for k in range(6)if mask&(1<<k)]
            row=np.zeros(18);row[ks]=1
            cap=sum(any(s['allowed'][TYPES[k]]for k in ks)for s in assignment_support)
            small.append(row);lower.append(-np.inf);higher.append(cap)
        for k in range(6):
            row=np.zeros(18);row[k]=1;row[6+k]=-1
            small.append(row);lower.append(-np.inf);higher.append(expected[k])
            row=np.zeros(18);row[k]=-1;row[12+k]=-1
            small.append(row);lower.append(-np.inf);higher.append(-expected[k])
        count_result=milp(np.r_[np.zeros(6),np.ones(12)],integrality=np.r_[np.ones(6),np.zeros(12)],
            bounds=Bounds(np.r_[np.full(6,minimum),np.zeros(12)],np.r_[np.full(6,n),np.full(12,np.inf)]),
            constraints=LinearConstraint(np.array(small),np.array(lower),np.array(higher)),
            options={'time_limit':60,'mip_rel_gap':1e-8})
        if count_result.status!=0:raise RuntimeError('count allocation not proven optimal:'+str(count_result.message))
        target=np.rint(count_result.x[:6]).astype(int)
        flow=lil_matrix((n+6,n*6))
        for i in range(n):flow[i,i*6:(i+1)*6]=1
        for k in range(6):flow[n+k,k:6*n:6]=1
        result=linprog(objective[:6*n]*1e7,A_eq=flow.tocsc(),b_eq=np.r_[np.ones(n),target],
            bounds=list(zip(np.zeros(n*6),upper[:n*6])),method='highs',options={'time_limit':60})
        if result.status!=0:raise RuntimeError('household assignment not proven optimal:'+str(result.message))
        # Integral vertex follows from total unimodularity of the bipartite
        # flow matrix; explicitly reject numerical nonintegral output.
        assert np.max(abs(result.x-np.rint(result.x)))<1e-7
        x=np.rint(result.x).reshape(n,6).astype(int)
        assert np.array_equal(x.sum(axis=0),target)
        solver_details={'method':'HiGHS small integer counts with all63 Hall capacities;HiGHS min-cost bipartite LP',
            'count_solver_status':int(count_result.status),'count_mip_gap':float(count_result.mip_gap),
            'assignment_solver_status':int(result.status),'all_subset_capacity_constraints':63,
            'no_solver_time_limit_incumbent_accepted':True}
    assert np.all(x.sum(axis=1)==1) and np.all(x<=upper[:6*n].reshape(n,6))
    counts=x.sum(axis=0);assert np.all(counts>=minimum)
    return {w['household_id']:TYPES[int(x[i].argmax())]for i,w in enumerate(worlds)}, {
        'seed':SEED,'minimum_per_type':minimum,'minimum_is_research_coverage_not_power':True,
        'conditional_q_is_observed':False,'conditional_reference_expected_counts':dict(zip(TYPES,expected.tolist())),
        'reference_uses_structural_population_weights':weighted_reference,
        'integer_counts':dict(zip(TYPES,counts.tolist())),
        'total_absolute_count_projection_error':float(abs(counts-expected).sum()),
        'solver_status':int(result.status),'mip_gap':float(getattr(result,'mip_gap',solver_details.get('count_mip_gap',0))),
        'solver_details':solver_details,
        'accepted_original50_fixed_assignments':len(fixed_assignment or {}),
        'q_reference_computed_before_fixed_pilot_assignment':True,
        'auto_share_design_sensitivity':auto_share,
        'supported_household_counts':{t:sum(r['allowed'][t]for r in support)for t in TYPES},
        'source_structure_or_ages_modified':False,'population_prevalence_estimated':False}


def build_policy(w,typ):
    evidence=candidates(w);assert evidence['allowed'][typ]
    byid={m['member_id']:m for m in w['members']};adults=[byid[x]for x in evidence['adult_ids']]
    if typ in ('A','D','F'):pool=[byid[x]for x in evidence['worker_ids']]
    elif typ=='E':
        pool=[a for a in adults if any(a['member_id']!=x for x in evidence['protected_candidate_ids'])]
        preferred=[a for a in pool if a['employment_status']!='has_work' and a['age_years']<75]
        pool=preferred or pool
    else:pool=adults
    holder=min(pool,key=lambda m:rank(SEED,w['household_id'],m['member_id'],'holder')) if pool else None
    holder_id=holder['member_id']if holder else evidence['external_guardian_ids'][0]
    subject=holder or w['members'][0]
    level=rank(SEED,w['household_id'],'policy-dose')%3
    usual={'A':[24.5,25.,25.5],'B':[24.5,25.,25.5],'C':[24.5,25.,25.5],
           'D':[24.5,25.,25.5],'E':[24.,24.5,25.],'F':[24.5,25.,25.5]}[typ][level]
    temporary={'A':[.5,1.,1.],'B':[.25,.5,.5],'C':[.5,1.,1.],
               'D':[1.5,2.,2.],'E':[.25,.5,.5],'F':[.5,1.,1.]}[typ][level]
    auto=typ in ('D','F');protect=[]
    if typ=='E':
        protected=min([byid[x]for x in evidence['protected_candidate_ids']if x!=holder_id],key=lambda m:rank(SEED,w['household_id'],m['member_id'],'protected'))
        protect=[{'person_id':protected['member_id'],'service':'daily two joint presence/temperature checks and protected bath/cooling',
                  'reason':'given care responsibility;age only supports candidate structure;dependency/illness not asserted',
                  'evidence_kind':'researcher_given','duration_min_each':10}]
    policy={'schema':'eb.stable_role_policy.v27','version':'v27.1','actual_seed':SEED,
        'holder':{'person_id':holder_id,'resident':holder is not None,'adult':True,
                  'age_observed_for_synthetic_role':False,'authority_scope':'given household appliance proposals;other member services retained',
                  'source':'matched adult member'if holder else 'existing explicitly given nonresident adult guardian;not an additional resident'},
        'schedule_subject_id':subject['member_id'],
        'thermal':{'usual_setpoint_C':usual,'temporary_increase_C':temporary,'maximum_change_duration_min':60,
                   'absolute_upper_control_C':usual+temporary,'physical_indoor_comfort_known':False,
                   'evidence_kind':'researcher_given_EB_anchor','EB_preferred_interval_preserved':True},
        'service_policy':{'laundry_handover_hour':[12,18,20][rank(SEED,w['household_id'],'handover')%3],
            'reschedule_limit_min':{'A':120,'B':30,'C':10,'D':180,'E':10,'F':90}[typ]+(0 if typ in ('C','E')else level*10),
            'handover_boundary_negotiable':typ in ('A','D','F'),
            'importance_given': 'protected services first'if typ=='E'else 'time-dependent essential services',
            'mobility_service_first':typ=='F',
            'evidence_kind':'researcher_given;not source inventory or willingness'},
        'economics':{'cost_priority_given':typ in ('A','D','F'),
            'explanation_before_agreement':typ in ('A','C'),
            'source_income_used_as_preference':False,'evidence_kind':'researcher_given'},
        'permissions':{'automatic_within_declared_bounds':auto,'confirmation_before_action':not auto,
            'same_day_reconfirmation':typ=='C','notification_required':True,
            'protected_service_veto':typ=='E','additional_helper_booking_requires_confirmation':True,
            'evidence_kind':'researcher_given;not observed resident consent'},
        'protected_services':protect,'unmeasured_source_preferences':None,
        'human_acceptance_or_rejection':None,'policy_constant_across_dates':True}
    policy['policy_sha256']=digest(policy)
    return policy


def permission_audit(w,p):
    policy=w['role_policy'];deltas=p['B']['changed_controls'];issues=[]
    for c in deltas:
        if c['kind']=='ac_setpoint'and c['value_C']>policy['thermal']['absolute_upper_control_C']+1e-9:
            issues.append('given_temperature_permission_exceeded')
    for t in p['B']['tasks']:
        old=next(z for z in p['A']['tasks']if z['need_id']==t['need_id'])
        if abs(t['start_min']-old['start_min'])>policy['service_policy']['reschedule_limit_min']:
            issues.append('given_reschedule_permission_exceeded')
    if policy['permissions']['confirmation_before_action']:issues.append('confirmation_required_before_implementation')
    if policy['permissions']['same_day_reconfirmation']:issues.append('same_day_reconfirmation_required')
    return {'issues':sorted(set(issues)),'automatic_execution_authorized_by_given_policy':not issues,
            'given_policy_sha256':policy['policy_sha256'],'human_answer':None,
            'issues_are_not_acceptance_labels':True}
