"""Normalized coverage MILP, objective-equivalent compression, two signatures."""
from collections import Counter,defaultdict
from ..common import digest,canonical
from .contract import config
from .semantics import judgment_signature
from .input_boundaries import require_no_downstream_fields


def concepts(row,joint_order_mode='legacy_buckets_v1'):
    require_no_downstream_fields(row,'SELECTION_CANDIDATE')
    families=sorted({c['family'] for c in row['components'] if c['event_relevance']['role']=='direct_event_request'})
    detail=defaultdict(set)
    for c in row['components']:
        if c['event_relevance']['role']!='direct_event_request':continue
        detail[c['family']].add('mechanism='+c['mechanism'])
        if row.get('change_axes_version'):
            from .change_axes import VERSION,labels
            if row['change_axes_version']!=VERSION:raise ValueError('UNKNOWN_CHANGE_AXES_VERSION')
            detail[c['family']].update(k+'='+v for k,v in labels(c['change_axes']).items())
        else:detail[c['family']].add('dose='+c['relative_level'])
        if not row.get('change_axes_version') and c['family'] in ('ac','water_heater'):
            minutes=c['magnitude'].get('duration_min',0)
            detail[c['family']].add('duration_position='+('brief' if minutes<=20 else 'partial' if minutes<=40 else 'full_event'))
    slack=[c['magnitude']['service_slack_min'] for c in row['components'] if 'service_slack_min' in c['magnitude']]
    units=Counter(c['family'] for c in row['components'])
    known=row['known_event_reduction_kWh']
    count=row['independent_units']
    if type(count) is not int or count<0:raise ValueError('INVALID_INDEPENDENT_TASK_COUNT')
    if joint_order_mode not in ('legacy_buckets_v1','exact_witnessed_v1'):
        raise ValueError('UNKNOWN_JOINT_ORDER_SELECTION_POLICY')
    if joint_order_mode=='exact_witnessed_v1':
        if count!=len(row['components']) or len({c['id'] for c in row['components']})!=count:
            raise ValueError('INDEPENDENT_TASK_COUNT_DOES_NOT_MATCH_COMPONENTS')
        task_units=[c.get('unit') for c in row['components']]
        if any(not isinstance(unit,str) or not unit for unit in task_units):
            raise ValueError('MISSING_INDEPENDENT_TASK_UNIT')
        if len(set(task_units))!=count:
            raise ValueError('DUPLICATE_INDEPENDENT_TASK_UNIT')
    order=('no_change' if count==0 else 'tasks_'+str(count)) if joint_order_mode=='exact_witnessed_v1' else (
        'no_change' if count==0 else 'single' if count==1 else 'two' if count==2 else 'three_or_more')
    axes={'manual':row['features']['manual'],
        'nominal_event_sign':'reduction' if known>1e-8 else 'increase' if known<-1e-8 else 'zero',
        'joint_order':order,
        'same_family_multibatch':str(any(n>1 for f,n in units.items() if f in ('washer','dishwasher','dryer'))),
        'service_slack':'unknown' if not slack else 'shortfall' if min(slack)<0 else 'under_30' if min(slack)<30 else 'ample',
        'consent':row['consent_status'],
        'soft_preference_tension':str(any(j['soft_preference_tension'] for j in row['judgment_context'])),
        'member_opinions_differ':str(any(j.get('member_opinions_differ') for j in row['judgment_context'])),
        'service_or_life_conflict':str(bool(row['issues']))}
    tokens={'family='+f for f in families}
    tokens.update('trade.'+k+'='+v for k,v in axes.items())
    tokens.update('detail.'+f+'.'+x for f,values in detail.items() for x in values)
    # Quantized decision meaning, not raw actuator field count or wording.
    # Literal/raw dose alternatives remain in the full catalogue.
    signature=judgment_signature(row,detail,axes)
    composition=digest(sorted(units.items()))
    action=digest(row['patches'])
    return dict(families=families,tokens=tokens,signature=signature,composition=composition,action=action)


def goals(rows,views,carried=frozenset()):
    out=[];households=sorted({r['household_id'] for r in rows})
    def add(h,t,w):out.append(dict(household=h,tag=t,weight=w,already_covered=(h,t) in carried))
    for h in households:
        ts=set().union(*(v['tokens'] for r,v in zip(rows,views) if r['household_id']==h))
        fs=sorted(t for t in ts if t.startswith('family='))
        for t in fs:add(h,t,1/max(1,len(fs)))
        axes=defaultdict(list)
        for t in sorted(ts):
            if t.startswith('trade.'):axes[t.split('=')[0]].append(t)
        for vs in axes.values():
            for t in vs:add(h,t,1/len(axes)/len(vs))
    byfamily=defaultdict(lambda:defaultdict(list))
    for t in sorted(set().union(*(v['tokens'] for v in views))):
        if t.startswith('detail.'):
            f,axis=t[7:].split('.',1);byfamily[f][axis.split('=')[0]].append(t)
    for f,axes in byfamily.items():
        for vs in axes.values():
            for t in vs:add(None,t,1/len(byfamily)/len(axes)/len(vs))
    return out


def equivalent_frame(rows,cfg):
    cells=defaultdict(list)
    for row in rows:
        v=concepts(row,cfg.get('selection_joint_order','legacy_buckets_v1'))
        key=canonical([row['household_id'],row['date'],sorted(v['tokens']),v['signature'],v['composition'],v['families']])
        cells[key].append(row)
    selected=[];aliases={}
    for pool in cells.values():
        chosen=min(pool,key=lambda r:digest([cfg['seed'],'equivalent-tie',r['id']]))
        selected.append(chosen);aliases[chosen['id']]=[r['id'] for r in pool]
    return selected,aliases


def select_block(rows,cfg=None,carried=frozenset()):
    import numpy as np
    import scipy
    from scipy.optimize import milp,Bounds,LinearConstraint
    from scipy.sparse import coo_array
    cfg=config(cfg);cells=defaultdict(list)
    for r in rows:
        if r.get('engineering_issues') or any(r.get(k) is not None for k in
                ('actual_outcomes','human_acceptance','human_score','human_reason')):
            raise ValueError('ENGINEERING_OR_OUTCOME_LEAKAGE')
        if cfg['method_revision']=='delivery_v2_11':
            from .change_axes import VERSION
            if r.get('change_axes_version')!=VERSION:raise ValueError('CURRENT_SELECTION_REQUIRES_SEPARATE_ACTION_AXES')
    if len({r['id'] for r in rows})!=len(rows):raise ValueError('DUPLICATE_CANDIDATE_ID')
    all_views={r['id']:concepts(r,cfg['selection_joint_order']) for r in rows}
    for r in rows:
        v=all_views[r['id']]
        # Full equality of all coefficients and repeat groups, not two arbitrary
        # representatives per coarse actuator cell. Preserve every alias.
        key=canonical([r['household_id'],r['date'],sorted(v['tokens']),v['signature'],v['composition'],v['families']])
        cells[key].append(r)
    active=[];aliases={}
    for pool in cells.values():
        chosen=min(pool,key=lambda r:digest([cfg['seed'],'equivalent-tie',r['id']]))
        active.append(chosen);aliases[chosen['id']]=[r['id'] for r in pool]
    active.sort(key=lambda r:(r['household_id'],r['date'],r['id']));views=[all_views[r['id']] for r in active]
    n=len(active)
    if not n:return dict(selected_ids=[],status='no_eligible_slots',coverage=[],aliases=aliases)
    dated=defaultdict(list);semantic=defaultdict(list);compositions=defaultdict(list);family=defaultdict(list)
    for i,(r,v) in enumerate(zip(active,views)):
        h=r['household_id'];dated[(h,r['date'])].append(i);semantic[(h,v['signature'])].append(i);compositions[(h,v['composition'])].append(i)
        for f in v['families']:family[(h,f)].append(i)
    gs=goals(active,views,carried);g=len(gs)
    rep=[(vs,cfg['repeat_context']) for vs in semantic.values() if len(vs)>1]+[(vs,cfg['repeat_composition']) for vs in compositions.values() if len(vs)>1]
    fam=list(family.items());total=n+g+len(rep)+len(fam)
    lower=np.zeros(total);upper=np.ones(total);integrality=np.ones(total);objective=np.zeros(total)
    upper[n+g:n+g+len(rep)]=10;upper[n+g+len(rep):]=45;integrality[n+g+len(rep):]=0
    rr=[];cc=[];vv=[];lb=[];ub=[]
    def constraint(values,a,b):
        k=len(lb);lb.append(a);ub.append(b)
        for j,x in values.items():rr.append(k);cc.append(j);vv.append(float(x))
    for vs in dated.values():constraint(dict.fromkeys(vs,1),1,1)
    for j,t in enumerate(gs):
        ids=[i for i,(r,v) in enumerate(zip(active,views)) if (t['household'] is None or r['household_id']==t['household']) and t['tag'] in v['tokens']]
        constraint({**dict.fromkeys(ids,1),n+j:1},0 if t['already_covered'] else 1,np.inf);objective[n+j]=t['weight']
    for j,(vs,weight) in enumerate(rep):
        index=n+g+j;constraint({**dict.fromkeys(vs,1),index:-1},-np.inf,1);objective[index]=weight/9
    perhome=Counter(h for h,f in family)
    for j,((h,f),vs) in enumerate(fam):
        index=n+g+len(rep)+j
        for k in range(1,10):constraint({**dict.fromkeys(vs,k),index:-1},-np.inf,k*(k+1)/2)
        objective[index]=cfg['repeat_family']/(45*perhome[h])
    def matrix():return LinearConstraint(coo_array((vv,(rr,cc)),shape=(len(lb),total)).tocsc(),np.array(lb),np.array(ub))
    options=dict(node_limit=cfg['selection_nodes'],mip_rel_gap=0.0,presolve=True)
    scale=None;scale_objective=np.zeros(total)
    if cfg['selection_joint_order']=='exact_witnessed_v1':
        targets=[(j,t) for j,t in enumerate(gs) if t['tag'].startswith('trade.joint_order=')]
        per_house=Counter(t['household'] for _,t in targets)
        for j,t in targets:scale_objective[n+j]=1/(len(per_house)*per_house[t['household']])
        scale=milp(scale_objective,integrality=integrality,bounds=Bounds(lower,upper),constraints=matrix(),options=options)
        if scale.x is None:
            return dict(status='solver_unknown_no_incumbent',selected_ids=[],coverage=[],aliases=aliases,
                        solver_message=scale.message,joint_order_stage='no_incumbent;no_replacement')
        # Soft coverage maximization, never fixed per-order counts or ratios.
        # An unproved incumbent only supplies an upper bound, not an optimum.
        constraint({i:x for i,x in enumerate(scale_objective) if x},-np.inf,float(scale.fun)+1e-8)
    first=milp(objective,integrality=integrality,bounds=Bounds(lower,upper),constraints=matrix(),options=options)
    if first.x is None and scale is None:
        return dict(status='solver_unknown_no_incumbent',selected_ids=[],coverage=[],aliases=aliases,solver_message=first.message)
    incumbent=first.x if first.x is not None else scale.x
    objective_value=float(objective@incumbent)
    constraint({i:x for i,x in enumerate(objective) if x},objective_value-1e-8,objective_value+1e-8)
    tie=np.zeros(total)
    for rank,i in enumerate(sorted(range(n),key=lambda i:digest([cfg['seed'],'selection-tie',active[i]['id']]))):tie[i]=(rank+1)/n
    last=milp(tie,integrality=integrality,bounds=Bounds(lower,upper),constraints=matrix(),options=options)
    x=last.x if last.x is not None else incumbent;selected=[r for i,r in enumerate(active) if x[i]>.5]
    if Counter((r['household_id'],r['date']) for r in selected)!=Counter({k:1 for k in dated}):raise ValueError('INVALID_SLOT_ASSIGNMENT')
    if float(objective@x)>objective_value+1e-6:raise ValueError('TIE_CHANGED_COVERAGE_OBJECTIVE')
    if scale is not None and float(scale_objective@x)>float(scale.fun)+1e-6:
        raise ValueError('LATER_STAGE_WORSENED_JOINT_ORDER_COVERAGE')
    selected_views=[all_views[r['id']] for r in selected];coverage=[]
    for t in gs:
        hits=[r['id'] for r,v in zip(selected,selected_views) if (t['household'] is None or r['household_id']==t['household']) and t['tag'] in v['tokens']]
        coverage.append({**t,'selected_ids':hits,'deficit':int(not hits and not t['already_covered']),
            'reason':None if hits or t['already_covered'] else 'given_dates_compete_for_slots_or_solver_budget' if t['tag'].startswith('trade.joint_order=') and scale is not None else 'ten_slots_coverage_repeat_tradeoff_or_solver_budget'})
    def status(s):return dict(status=int(s.status),optimal=s.status==0,gap=float(s.mip_gap) if getattr(s,'mip_gap',None) is not None else None,nodes=int(getattr(s,'mip_node_count',0) or 0))
    order_coverage=[]
    for h in sorted({r['household_id'] for r in rows}):
        available=sorted({r['independent_units'] for r in rows if r['household_id']==h})
        chosen=Counter(r['independent_units'] for r in selected if r['household_id']==h)
        order_coverage.append(dict(household_id=h,available_task_counts=available,
            selected_task_counts=dict(sorted(chosen.items())),missing_task_counts=sorted(set(available)-chosen.keys()),
            witnessed_dates_by_count={k:sorted({r['date'] for r in rows if r['household_id']==h and r['independent_units']==k}) for k in available},
            scope='eligible_catalogue_witnesses;absent_is_not_proven_no_opportunity'))
    return dict(status='assigned',selected_ids=[r['id'] for r in selected],coverage=coverage,aliases=aliases,
        compression_scope='identical_declared_objective_coefficients_and_all_repeat_keys;not_fine_dose_optimality',
        catalogue_rows=len(rows),active_rows=n,solver=dict(coverage=status(first),tie=status(last),scipy=scipy.__version__,
            **({'joint_order':status(scale)} if scale is not None else {})),
        selection_joint_order=cfg['selection_joint_order'],joint_order_coverage=order_coverage,
        objective_priority=['witnessed_exact_task_count_coverage','existing_coverage_and_repetition','seeded_tie'] if scale is not None else ['existing_coverage_and_repetition','seeded_tie'],
        coverage_stage_used_fallback=first.x is None,
        semantic_repeat_excess=sum(max(0,n-1) for n in Counter((r['household_id'],v['signature']) for r,v in zip(selected,selected_views)).values()),
        proportions_prescribed=False,physical_or_human_outcomes_used=False)


def assign(rows,cfg=None):
    cfg=config(cfg);homes=sorted({r['household_id'] for r in rows},key=lambda h:digest([cfg['seed'],'household-order',h]))
    blocks=[];carry=set();selected=[]
    for start in range(0,len(homes),cfg['block_households']):
        group=set(homes[start:start+cfg['block_households']]);block=select_block([r for r in rows if r['household_id'] in group],cfg,carry)
        blocks.append(block);selected+=block['selected_ids']
        ids=set(block['selected_ids'])
        for r in rows:
            if r['id'] in ids:carry.update((None,t) for t in concepts(r,cfg['selection_joint_order'])['tokens'])
    return dict(schema='eb.unified.selection.v1',selected_ids=selected,blocks=blocks,household_order=homes,
        block_households=cfg['block_households'],global_optimality_claimed=False)
