"""Coarsened joint-age support, with exact ages explicitly synthesized.

A2001 does not identify biological/step/adoptive parentage. No minimum
biological age gap is invented. Minimum-change projection is a reference
regularizer, not an estimated distribution of exact ages.
"""
from common import *

_AGG=None
_PROFILES=None
def sources():
    global _AGG,_PROFILES
    if _AGG is None:
        _AGG=read(OUT/'JOINT_AGE_SOURCE_AGGREGATES.json')['motifs']
        _PROFILES={p['slot_id']:p['family'] for p in read(BASE/'data_production_audit_20261009_v1/source_snapshots/v7/HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json')['profiles']}
    return _AGG,_PROFILES

def compatible(m,a):
    return (m['ego_relation_code']==a[0] and (1 if m['sex']=='male' else 2)==a[1]
            and m['current_work_source_proxy']==a[4]
            and max(m['age_bin_reference'][0],5*a[2])<=min(m['age_bin_reference'][1],5*a[3]+4))

def assign(ms,atoms,graft):
    choices=[[j for j,a in enumerate(atoms) if compatible(m,a)] for m in ms]
    if any(not c for c in choices) and not graft:raise ValueError('AGE_ATOM_ALIGNMENT')
    if graft:choices=[c or [None] for c in choices]
    # Full motifs are a permutation; declared grafts can replicate coarse atoms.
    order=sorted(range(len(ms)),key=lambda i:(len(choices[i]),i));result=[None]*len(ms)
    def solve(k,used):
        if k==len(order):return len(used)==len(atoms)
        i=order[k]
        for j in sorted(choices[i],key=lambda j:(j in used,-1 if j is None else j)):
            if j in used and not graft:continue
            result[i]=j
            if solve(k+1,used|({j} if j is not None else set())):return True
        return False
    if not solve(0,set()):raise ValueError('AGE_ATOM_MATCHING')
    return result

def project(w):
    agg,profiles=sources();family=profiles[w['household_id']];ms=w['members'];old=[m['age_years'] for m in ms]
    relation_policy={'source':'CHFS2021 questionnaire A2001, family definition PDF pages12-13',
        'legal_step_and_adoptive_in_source_family_definition':True,'biological_parentage_identified':False,
        'subtype':None,'no_arbitrary_biological_minimum_age_gap':True}
    for m in ms:
        if m['ego_relation_code'] in (3,4,5,6,7,8,9):m['relationship_subtype_evidence']=relation_policy.copy()
    if len(ms)==1:
        w['joint_age_evidence']={'route':'unchanged census singleton age-sex reference',
            'exact_age_is_synthetic':True,'source_motif_hash':family['motif_group_hash'],'changed_members':0}
        return w
    mh=family['motif_group_hash'];source=agg[mh];mapping=assign(ms,source['coarse_atoms'],family['motif_graft_extrapolation'])
    ego=next(i for i,m in enumerate(ms) if m['ego_relation_code']==1)
    ops={o['operator_id'] for o in w['operating_context']['operators'] if o['resident']}
    upper={b['member_id'] for b in w['layout']['sleep_reference']['berths'] if b['level']>0}
    bounds=[]
    for m,j in zip(ms,mapping):
        a=source['coarse_atoms'][j] if j is not None else None
        lo=m['age_bin_reference'][0];hi=m['age_bin_reference'][1]
        if a is not None:lo=max(lo,5*a[2]);hi=min(hi,5*a[3]+4)
        if m['member_id'] in ops:lo=max(lo,18)
        if m['member_id'] in upper:lo=max(lo,6);hi=min(hi,59)
        bounds.append((lo,hi))
    feasible=[]
    for pat in source['patterns']:
        candidates=[]
        for root in range(bounds[ego][0],bounds[ego][1]+1):
            ages=[]
            for i,(lo,hi) in enumerate(bounds):
                if i==ego:lo=hi=root
                else:
                    if mapping[i] is not None:
                        g=pat['signed_gap_bin5'][mapping[i]];lo=max(lo,root+5*g-1);hi=min(hi,root+5*g+5)
                    if ms[i]['ego_relation_code'] in (3,4,5):lo=max(lo,root+1)
                    if ms[i]['ego_relation_code'] in (6,8):hi=min(hi,root-1)
                if lo>hi:break
                ages.append(max(lo,min(hi,old[i])))
            if len(ages)==len(ms):candidates.append((sum(abs(a-b) for a,b in zip(ages,old)),tuple(ages)))
        if candidates:feasible.append((pat,min(candidates)))
    if not feasible:raise ValueError('NO_JOINT_AGE_PROJECTION:'+w['household_id'])
    total=sum(x[0]['weight'] for x in feasible);u=(rank(w['household_id'],'v20-joint-age')/2**64)*total
    chosen=feasible[-1]
    for item in feasible:
        u-=item[0]['weight']
        if u<0:chosen=item;break
    pat,(_,ages)=chosen
    for m,before,age in zip(ms,old,ages):
        m['age_years']=age;m['source_V19_synthetic_age']=before
        m['age_evidence']='minimum-change synthetic age projection within original coarse age bin and coarsened joint ego-relative gap support; not source exact age'
    for b in w['layout']['sleep_reference']['berths']:
        b['age_years']=next(m['age_years'] for m in ms if m['member_id']==b['member_id'])
    w['joint_age_evidence']={'route':'coarsened source joint gap block with minimum-change reference projection',
        'source_motif_hash':mh,'source_coarse_atoms':source['coarse_atoms'],'member_to_source_atom':mapping,'unmapped_graft_members_have_no_source_joint_gap':[ms[i]['member_id'] for i,j in enumerate(mapping) if j is None],
        'signed_gap_bin5':pat['signed_gap_bin5'],'gap_uncertainty_rule':'[5*b-1,5*b+5] includes unknown birthdays',
        'selected_gap_source_count':pat['source_count'],'feasible_source_weight_fraction':total/sum(x['weight'] for x in source['patterns']),
        'source_visit_year':source['visit_year'],'graft_extrapolation':family['motif_graft_extrapolation'],
        'graft_replications_are_design_not_observed_joint_households':family['motif_graft_extrapolation'],
        'exact_age_is_synthetic':True,'birthday_and_parentage_subtype_unknown':True,
        'old_synthetic_ages':old,'new_synthetic_ages':list(ages),'changed_members':sum(a!=b for a,b in zip(old,ages)),
        'operator_and_upper_berth_eligibility_conditioning_is_reference_design':True}
    return w
