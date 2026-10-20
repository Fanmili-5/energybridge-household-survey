"""Two-stage integer coverage assignment. No energy or acceptance objective."""
from collections import Counter,defaultdict
from .common import canonical,digest


CORE = {
    'event':['reduction','zero','increase','unknown','unknown_with_known_reduction'],
    'manual':['changed','unchanged'],
    'thermal_direction':['aligned','opposing'],
}


def assignment_frame(rows,config):
    dated=defaultdict(list)
    for r in rows:
        if r.get('engineering_issues') or r.get('engineering_diagnostic'):
            raise ValueError('ENGINEERING_DIAGNOSTIC_NOT_COLLECTION_ELIGIBLE')
        if r.get('relevance_diagnostic') or not r.get('event_relevance',{}).get('passed'):
            raise ValueError('UNRELATED_ACTION_NOT_COLLECTION_ELIGIBLE')
        dated[(r['household_id'],r['date'])].append(r)
    for pool in dated.values():
        if any(r['features']['device_count']=='0' for r in pool) and any(r['features']['device_count']!='0' for r in pool):
            raise ValueError('CONTROL_NOT_ELIGIBLE_WHEN_CHANGED_REQUEST_EXISTS')
    cells=defaultdict(list)
    for r in rows:
        if r['actual_outcomes'] is not None or r['human_acceptance'] is not None or r['actual_results_used_for_selection'] is not False:
            raise ValueError('COLLECTION_OUTCOME_LEAKAGE')
        key=(r['household_id'],r['date'],canonical(r['features']),tuple(r['issues']),r['near_duplicate_key'])
        cells[key].append(r)
    active=[]
    for _,pool in sorted(cells.items()):
        active.extend(sorted(pool,key=lambda r:digest([config['seed'],'assignment-cell',r['id']]))[:config['assignment_representatives_per_cell']])
    active.sort(key=lambda r:(r['household_id'],r['date'],r['id']))
    # Representatives can differ in only provenance/fine doses. Check that the
    # declared coverage universe and household-day eligibility were conserved.
    universe=lambda v:{(r['household_id'],r['date'],tag) for r in v for tag in r['tags']}
    if universe(rows)!=universe(active):
        raise ValueError('ASSIGNMENT_FRAME_LOST_DECLARED_COVERAGE')
    return active,{'catalogue_unique':len(rows),'assignment_active':len(active),
        'representatives_per_semantic_cell':config['assignment_representatives_per_cell'],
        'full_catalogue_retained':True,'outcomes_used':False,'coverage_universe_preserved':True,
        'fine_dose_optimality_claim':False}


def goals(rows,households):
    out=[]
    for h in households:
        hh=[r for r in rows if r['household_id']==h]
        maximum=max(int(r['features']['device_count']) for r in hh)
        axes={**CORE,'device_count':[str(n) for n in range(1,maximum+1)]}
        for axis,levels in sorted(axes.items()):
            for level in levels:
                tag=axis+'='+level
                out.append({'id':h+'::'+tag,'household':h,'tag':tag,
                    'available_household_days':len({r['date'] for r in hh if tag in r['tags']})})
        for tag in sorted({t for r in hh for t in r['tags'] if t.startswith('amplitude=')}):
            out.append({'id':h+'::'+tag,'household':h,'tag':tag,
                'available_household_days':len({r['date'] for r in hh if tag in r['tags']})})
    # Admission labels are reports, never quotas or a coverage reward. Control
    # remains a scarcity fallback, not a requested household/batch witness.
    for tag in sorted({t for r in rows for t in r['tags']
                       if ('|' in t or t.startswith(('composition=','mechanism=','service_slack=','amplitude=')))
                       and 'admission=' not in t and t not in ('composition=control','mechanism=control')
                       and 'device_count=0' not in t}):
        out.append({'id':'batch::'+tag,'household':None,'tag':tag,
            'available_household_days':len({(r['household_id'],r['date']) for r in rows if tag in r['tags']})})
    return out


def assign(rows,config):
    import numpy as np
    import scipy
    from scipy.optimize import Bounds,LinearConstraint,milp
    from scipy.sparse import coo_array
    active,frame=assignment_frame(rows,config)
    households=sorted({r['household_id'] for r in active})
    dated=defaultdict(list)
    for i,r in enumerate(active):dated[(r['household_id'],r['date'])].append(i)
    if any(sum(h==hid for h,_ in dated)!=10 for hid in households):
        raise ValueError('COLLECTION_REQUIRES_EXACTLY_TEN_DATE_SLOTS_PER_HOUSEHOLD')
    target=goals(active,households);n=len(active);g=len(target)
    repeated=defaultdict(list)
    for i,r in enumerate(active):repeated[(r['household_id'],r['near_duplicate_key'])].append(i)
    repeat_groups=[v for v in repeated.values() if len({active[i]['date'] for i in v})>1]
    total=n+g+len(repeat_groups);lower=[0.]*total;upper=[1.]*(n+g)+[10.]*len(repeat_groups)
    rr=[];cc=[];vv=[];lb=[];ub=[]
    def constraint(values,left,right):
        idx=len(lb);lb.append(left);ub.append(right)
        for j,x in values.items():rr.append(idx);cc.append(j);vv.append(float(x))
    for ids in dated.values():constraint({i:1 for i in ids},1,1)
    for j,t in enumerate(target):
        eligible=[i for i,r in enumerate(active) if (t['household'] is None or r['household_id']==t['household']) and t['tag'] in r['tags']]
        constraint({**{i:1 for i in eligible},n+j:1},1,np.inf)
    for j,ids in enumerate(repeat_groups):constraint({**{i:1 for i in ids},n+g+j:-1},-np.inf,1)
    def matrix():
        return LinearConstraint(coo_array((vv,(rr,cc)),shape=(len(lb),total)).tocsc(),np.array(lb),np.array(ub))
    options={'node_limit':config['solver_node_limit'],'mip_rel_gap':0.0,'presolve':True}
    first=np.zeros(total);first[n:n+g]=1
    a=milp(first,integrality=np.ones(total),bounds=Bounds(lower,upper),constraints=matrix(),options=options)
    if a.x is None:raise ValueError('COLLECTION_ASSIGNMENT_NO_FEASIBLE_SOLUTION:'+str(a.message))
    # Lock the achieved integer coverage, even if the budget did not prove it
    # optimal. A time/node limit is never reported as proof of infeasibility.
    achieved=round(sum(a.x[n:n+g]));constraint({n+j:1 for j in range(g)},achieved,achieved)
    second=np.zeros(total);second[n+g:]=1
    # Aggregate tie contribution < 0.25, so one duplicate always dominates it.
    rank=sorted(range(n),key=lambda i:digest([config['seed'],'assignment-tie',active[i]['id']]))
    for position,i in enumerate(rank):second[i]=(position+1)/(4*max(1,n)*max(1,len(dated)))
    b=milp(second,integrality=np.ones(total),bounds=Bounds(lower,upper),constraints=matrix(),options=options)
    chosen=b if b.x is not None else a
    selected=[r for i,r in enumerate(active) if chosen.x[i]>0.5]
    # Independent integer readback; never round a fractional relaxation to cases.
    if any(abs(x-round(x))>1e-6 for x in chosen.x) or Counter((r['household_id'],r['date']) for r in selected)!=Counter({k:1 for k in dated}):
        raise ValueError('INVALID_INTEGER_ASSIGNMENT_READBACK')
    coverage=[]
    for t in target:
        hits=[r for r in selected if (t['household'] is None or r['household_id']==t['household']) and t['tag'] in r['tags']]
        coverage.append({**t,'requested':1,'selected':len(hits),'deficit':int(not hits),
            'selected_households':len({r['household_id'] for r in hits}),
            'reason':None if hits else 'absent_from_declared_catalogue;not_proof_of_global_infeasibility'
                if not t['available_household_days'] else 'ten_slot_assignment_tradeoff_or_solver_budget'})
    def status(x):
        return {'status':int(x.status),'message':str(x.message),'objective':None if x.fun is None else float(x.fun),
            'proven_optimal':x.status==0,'mip_gap':None if getattr(x,'mip_gap',None) is None else float(x.mip_gap),
            'node_count':int(getattr(x,'mip_node_count',0) or 0)}
    duplicates=Counter((r['household_id'],r['near_duplicate_key']) for r in selected)
    return {'schema':'eb.collection.assignment.v2','selected_ids':[r['id'] for r in selected],
        'coverage':coverage,'required_deficits':sum(r['deficit'] for r in coverage),
        'near_duplicate_excess':sum(max(0,v-1) for v in duplicates.values()),
        'frame':frame,'solver':{'method':'two_stage_lexicographic_MILP','scipy_version':scipy.__version__,
            'coverage':status(a),'repeat_and_tie':status(b),'node_limit_per_stage':config['solver_node_limit']},
        'outcomes_used':False,'population_representativeness_claim':False,
        'category_proportions_prescribed':False,'admission_labels_rewarded':False,
        'control_policy':'only_if_no_changed_request_in_declared_daily_domain',
        'reselection_after_physical_or_human_results':False}
