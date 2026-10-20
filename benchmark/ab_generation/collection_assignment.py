"""Optimize normalized coverage and redundancy together; never human outcomes."""
from collections import Counter,defaultdict
from .common import canonical,digest
from .collection_selection import POLICY,view,tokens,targets


def assignment_frame(rows,config):
    dated=defaultdict(list);cells=defaultdict(list)
    for r in rows:
        if r.get('engineering_issues') or r.get('engineering_diagnostic'):raise ValueError('ENGINEERING_DIAGNOSTIC_NOT_COLLECTION_ELIGIBLE')
        if r.get('relevance_diagnostic') or not r.get('event_relevance',{}).get('passed'):raise ValueError('UNRELATED_ACTION_NOT_COLLECTION_ELIGIBLE')
        if r['actual_outcomes'] is not None or r['human_acceptance'] is not None or r['actual_results_used_for_selection'] is not False:raise ValueError('COLLECTION_OUTCOME_LEAKAGE')
        dated[(r['household_id'],r['date'])].append(r)
        cells[(r['household_id'],r['date'],canonical(view(r)))].append(r)
    for pool in dated.values():
        if any(r['features']['device_count']=='0' for r in pool) and any(r['features']['device_count']!='0' for r in pool):raise ValueError('CONTROL_NOT_ELIGIBLE_WHEN_CHANGED_REQUEST_EXISTS')
    active=[]
    for _,pool in sorted(cells.items()):
        physical={}
        for r in sorted(pool,key=lambda r:r['id']):physical.setdefault(digest(r['patches']),r)
        active.extend(sorted(physical.values(),key=lambda r:digest([config['seed'],'cell',r['patches']]))[:config['assignment_representatives_per_cell']])
    active.sort(key=lambda r:(r['household_id'],r['date'],r['id']))
    universe=lambda pool:{(r['household_id'],r['date'],t) for r in pool for t in tokens(view(r))}
    if universe(rows)!=universe(active):raise ValueError('ASSIGNMENT_FRAME_LOST_SELECTION_COVERAGE')
    return active,{'catalogue_unique':len(rows),'assignment_active':len(active),
        'representatives_per_semantic_cell':config['assignment_representatives_per_cell'],
        'full_catalogue_retained':True,'outcomes_used':False,'coverage_universe_preserved':True,
        'coverage_universe':'v4_selection_concepts;raw_control_axes_are_descriptive','fine_dose_optimality_claim':False}


def goals(rows,households):return targets(rows,households)


def assign(rows,config):
    import numpy as np
    import scipy
    from scipy.optimize import Bounds,LinearConstraint,milp
    from scipy.sparse import coo_array
    active,frame=assignment_frame(rows,config);households=sorted({r['household_id'] for r in active});n=len(active)
    views=[view(r) for r in active];concepts=[tokens(v) for v in views]
    dated=defaultdict(list);repeated=defaultdict(list);families=defaultdict(list);compositions=defaultdict(list)
    for i,r in enumerate(active):
        dated[(r['household_id'],r['date'])].append(i);repeated[(r['household_id'],views[i]['signature'])].append(i)
        compositions[(r['household_id'],views[i]['composition_signature'])].append(i)
        for f in views[i]['families']:families[(r['household_id'],f)].append(i)
    if any(sum(h==hid for h,_ in dated)!=10 for hid in households):raise ValueError('COLLECTION_REQUIRES_EXACTLY_TEN_DATE_SLOTS_PER_HOUSEHOLD')
    target=goals(active,households);g=len(target)
    repeat_groups=[v for v in repeated.values() if len({active[i]['date'] for i in v})>1]
    composition_groups=[v for v in compositions.values() if len({active[i]['date'] for i in v})>1]
    semantic_group_count=len(repeat_groups)
    repeat_groups+=composition_groups
    family_groups=sorted(families.items())
    total=n+g+len(repeat_groups)+len(family_groups);lower=np.zeros(total);upper=np.ones(total)
    upper[n+g:n+g+len(repeat_groups)]=9
    upper[n+g+len(repeat_groups):]=45
    integrality=np.ones(total);integrality[n+g+len(repeat_groups):]=0
    rr=[];cc=[];vv=[];lb=[];ub=[]
    def constraint(values,left,right):
        idx=len(lb);lb.append(left);ub.append(right)
        for j,x in values.items():rr.append(idx);cc.append(j);vv.append(float(x))
    for ids in dated.values():constraint(dict.fromkeys(ids,1),1,1)
    for j,t in enumerate(target):
        eligible=[i for i,r in enumerate(active) if (t['household'] is None or r['household_id']==t['household']) and t['tag'] in concepts[i]]
        constraint({**dict.fromkeys(eligible,1),n+j:1},1,np.inf)
    objective=np.zeros(total)
    for j,t in enumerate(target):objective[n+j]=t['weight']
    for j,ids in enumerate(repeat_groups):
        idx=n+g+j;constraint({**dict.fromkeys(ids,1),idx:-1},-np.inf,1)
        objective[idx]=POLICY['household_semantic_repeat_weight' if j<semantic_group_count else 'household_composition_repeat_weight']/9
    per_household=Counter(h for h,_ in families)
    for j,((h,f),ids) in enumerate(family_groups):
        idx=n+g+len(repeat_groups)+j
        # Exact convex piecewise-linear epigraph of n*(n-1)/2 at integer n.
        # Avoid weak big-M binary indicators for each repeated exposure.
        for k in range(1,10):constraint({**dict.fromkeys(ids,k),idx:-1},-np.inf,k*(k+1)/2)
        objective[idx]=POLICY['household_family_repeat_weight']/(45*per_household[h])
    def matrix():return LinearConstraint(coo_array((vv,(rr,cc)),shape=(len(lb),total)).tocsc(),np.array(lb),np.array(ub))
    options={'node_limit':config['solver_node_limit'],'mip_rel_gap':0.0,'presolve':True}
    first=milp(objective,integrality=integrality,bounds=Bounds(lower,upper),constraints=matrix(),options=options)
    if first.x is None:raise ValueError('COLLECTION_ASSIGNMENT_NO_FEASIBLE_SOLUTION:'+str(first.message))
    constraint({i:x for i,x in enumerate(objective) if x},float(first.fun)-1e-8,float(first.fun)+1e-8)
    second=np.zeros(total)
    rank=sorted(range(n),key=lambda i:digest([config['seed'],'selection-tie',active[i]['household_id'],active[i]['date'],views[i],active[i]['patches']]))
    for position,i in enumerate(rank):second[i]=(position+1)/(max(1,n)*max(1,len(dated)))
    last=milp(second,integrality=integrality,bounds=Bounds(lower,upper),constraints=matrix(),options=options)
    chosen=last if last.x is not None else first;selected=[r for i,r in enumerate(active) if chosen.x[i]>0.5]
    if any(abs(x-round(x))>1e-6 for x in chosen.x[:n+g+len(repeat_groups)]) or Counter((r['household_id'],r['date']) for r in selected)!=Counter({k:1 for k in dated}):raise ValueError('INVALID_INTEGER_ASSIGNMENT_READBACK')
    if float(objective@chosen.x)>float(first.fun)+1e-6:raise ValueError('TIE_CHANGED_PRIMARY_OBJECTIVE')
    selected_concepts={r['id']:tokens(view(r)) for r in selected};coverage=[]
    for t in target:
        hits=[r for r in selected if (t['household'] is None or r['household_id']==t['household']) and t['tag'] in selected_concepts[r['id']]]
        coverage.append({**t,'requested':1,'selected':len(hits),'deficit':int(not hits),
            'selected_households':len({r['household_id'] for r in hits}),
            'reason':None if hits else 'absent_from_declared_catalogue;not_proof_of_global_infeasibility' if not t['available_household_days'] else 'ten_slot_joint_coverage_redundancy_tradeoff_or_solver_budget'})
    def status(x):
        return {'status':int(x.status),'message':str(x.message),'objective':None if x.fun is None else float(x.fun),
            'proven_optimal':x.status==0,'mip_gap':None if getattr(x,'mip_gap',None) is None else float(x.mip_gap),
            'node_count':int(getattr(x,'mip_node_count',0) or 0)}
    duplicates=Counter((r['household_id'],view(r)['signature']) for r in selected)
    composition_duplicates=Counter((r['household_id'],view(r)['composition_signature']) for r in selected)
    exposure={h:dict(Counter(f for r in selected if r['household_id']==h for f in view(r)['families'])) for h in households}
    return {'schema':'eb.collection.assignment.v4','selected_ids':[r['id'] for r in selected],'coverage':coverage,
        'required_deficits':sum(r['deficit'] for r in coverage),'weighted_deficits':sum(r['weight']*r['deficit'] for r in coverage),
        'near_duplicate_excess':sum(max(0,v-1) for v in duplicates.values()),
        'composition_repeat_excess':sum(max(0,v-1) for v in composition_duplicates.values()),
        'repeat_definition':'v4_household_tradeoff_signature;not_raw_date_or_control_axis_vector',
        'family_exposure':exposure,'selection_policy':POLICY,'frame':frame,
        'solver':{'method':'joint_normalized_coverage_semantic_and_family_redundancy_MILP','scipy_version':scipy.__version__,
            'coverage':status(first),'repeat_and_tie':status(last),'primary_repeat_cost':float(objective[n+g:]@chosen.x[n+g:]),'node_limit_per_stage':config['solver_node_limit']},
        'outcomes_used':False,'population_representativeness_claim':False,'category_proportions_prescribed':False,
        'admission_labels_rewarded':False,'control_policy':'only_if_no_changed_request_in_declared_daily_domain','reselection_after_physical_or_human_results':False}
