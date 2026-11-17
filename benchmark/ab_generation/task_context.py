"""Life-derived dated task conditions, committed before either plan exists."""
from copy import deepcopy
import datetime as dt
import json, math, os
from pathlib import Path
from .common import digest

VERSION = 'eb.shared_daily_tasks.v4'
SEED = 20261116
PROGRAMMES = {'washer':'WM','dryer':'DR','dishwasher':'DW'}
POLICY = {
 'schema':VERSION, 'seed':SEED,
 'scope':'independent complete-day reference workload; not measured daily-use frequency',
 'laundry':'reference day processes the previous-day accumulated clothing batch, witnessed by previous-day bathing/change events; no waiting for the current evening to manufacture ordinary A demand',
 'dishes':'one batch from a recorded home meal group (previous dinner or current breakfast/lunch/dinner); deterministic choice among complete same-day feasible sources before plans',
 'clothes_change_at_bath':'explicit reference task rule, not a measured survey fact',
 'same_load_dryer':'preserve existing WM predecessor contract; for fixed background washer/dryer missing a contract, explicitly instantiate the same named batch before plans; no manual transfer action',
 'ready':'max(original EB execution earliest, last source event end); whole same-day programme and household precedence retained',
 'events':'external scene is separate from workload identity; default18-19, predeclared optional starts16-20 on10min grid; A remains event blind',
 'knowledge':'all reference-day routines given for whole-plan judgment; no claim of forecasting unannounced C changes',
 'source_clocks_modified':False, 'old_A_B_used':False,
 'human_labels_or_physical_outcomes_used':False,
}

def routine(h,date):
    day=dt.date.fromisoformat(date).weekday()
    return next(r for r in h['routine']['daily_services'] if r['day']==day)

def sources(case,date):
    """Only existing frozen household activities may create source records."""
    h=case['household']; out=[]
    for offset in (-1,0):
        day=(dt.date.fromisoformat(date)+dt.timedelta(days=offset)).isoformat()
        r=routine(h,day)
        for kind,rows in [('bath',r.get('bathing_services',[])),('meal',r.get('meals',[]))]:
            for i,row in enumerate(rows):
                if kind=='meal' and row['location']!='home':continue
                out.append(dict(event_id=digest([case['case_id'],day,kind,i,row]),
                    source_date=day,day_offset=offset,kind=kind,
                    start_min=offset*1440+row['start']%1440,
                    end_min=offset*1440+row['end']%1440,
                    reference_activity=deepcopy(row)))
    return out

def derive_tasks(case,date,reference):
    """No plan, candidate, event outcome or answer is an argument."""
    h=case['household']; src=sources(case,date)
    functions={f for a in h['service_asset_registry'].values() for f in a['functions']}
    jobs={}
    for kind,fun in PROGRAMMES.items():
        if fun not in functions:continue
        ref=reference['programs'][kind]
        latest=min(1440,round(float(ref.get('latest_h',24))*60))
        jobs[fun]=dict(function=fun,kind=kind,
            native_earliest_min=round(float(ref.get('earliest_h',8))*60),
            deadline_min=latest,duration_min=ref['duration_min'],required_programmes=1)
    tasks=[]
    if 'WM' in jobs:
        total=jobs['WM']['duration_min']+jobs.get('DR',{}).get('duration_min',0)
        options=[]
        for offset in (-1,):
            group=[e for e in src if e['kind']=='bath' and e['day_offset']==offset]
            if not group:continue
            ready=max(jobs['WM']['native_earliest_min'],max(e['end_min'] for e in group))
            if math.ceil(ready/10)*10+total<=min(jobs['WM']['deadline_min'],jobs.get('DR',jobs['WM'])['deadline_min']):
                options.append((offset,ready,group))
        if not options:raise ValueError('NO_LIFE_DERIVED_LAUNDRY_BATCH:'+case['case_id']+':'+date)
        pick=int(digest([SEED,'laundry',case['case_id'],date])[:8],16)%len(options)
        offset,ready,group=options[pick]
        batch=digest([VERSION,case['case_id'],date,'laundry',[e['event_id'] for e in group]])
        wm={**jobs['WM'], 'ready_min':ready,'load_id':batch,
            'source_events':group,'preparation':'clothes_from_recorded_bathing_events',
            'source_day_offset':offset,'load_quantity_is_reference_not_measured':True}
        tasks.append(wm)
        if 'DR' in jobs:
            predecessor=h.get('service_contracts',{}).get('DR',{}).get('predecessor',{})
            if predecessor.get('same_load_required') is False:raise ValueError('EXPLICIT_DIFFERENT_LOAD_NEEDS_SEPARATE_MODEL')
            tasks.append({**jobs['DR'],'ready_min':max(ready,jobs['DR']['native_earliest_min']),
                'load_id':batch,'ready_after_function':'WM','source_events':deepcopy(group),
                'dependency_origin':'existing_household_contract' if predecessor else 'explicit_reference_background_batch_instantiation',
                'preparation':'same_load_after_predecessor','source_day_offset':offset,
                'load_quantity_is_reference_not_measured':True})
    elif 'DR' in jobs:raise ValueError('SOURCE_DRYER_WITHOUT_WASHER')
    if 'DW' in jobs:
        options=[]
        for offset,meal in [(-1,'dinner'),(0,'breakfast'),(0,'lunch'),(0,'dinner')]:
            group=[e for e in src if e['kind']=='meal' and e['day_offset']==offset and e['reference_activity']['kind']==meal]
            if not group:continue
            ready=max(jobs['DW']['native_earliest_min'],max(e['end_min'] for e in group))
            if math.ceil(ready/10)*10+jobs['DW']['duration_min']<=jobs['DW']['deadline_min']:
                options.append((offset,meal,ready,group))
        if not options:raise ValueError('NO_LIFE_DERIVED_DISH_BATCH')
        pick=int(digest([SEED,'dishes',case['case_id'],date])[:8],16)%len(options)
        offset,meal,ready,group=options[pick]
        tasks.append({**jobs['DW'],'ready_min':ready,
            'load_id':digest([VERSION,case['case_id'],date,'dishes',[e['event_id'] for e in group]]),
            'source_events':group,'preparation':'dishes_from_named_home_meal_group',
            'source_day_offset':offset,'source_meal':meal,
            'load_quantity_is_reference_not_measured':True})
    today=routine(h,date)
    result=dict(schema=VERSION,date=date,household_id=case['case_id'],
        household_case_sha256=digest(case),reference_sha256=digest(reference),policy_sha256=digest(POLICY),
        tasks=sorted(tasks,key=lambda t:t['function']),
        service_origins=dict(
            AC=dict(basis='given reference occupied-day thermal service, actual temperature needs later physics',comfort=deepcopy(h['comfort'])),
            WH=dict(bathing_events=deepcopy(today['bathing_services']),actual_hot_water_service_not_verified=True) if 'WH' in functions else None,
            EV=dict(driver=h['ev']['vehicle_user_member_id'],parking=deepcopy(h['ev']['parking_sessions'][dt.date.fromisoformat(date).weekday()]),
                arrival_soc=h['ev']['arrival_soc'],target_soc=h['ev']['departure_soc_target'],connection_rule='source parking intersect driver home; continuous episode') if 'EV' in functions else None),
        information_contract=deepcopy(h['routine']['information_contract']),
        information_perspective=POLICY['knowledge'],
        A_and_B_share_tasks=True,manual_loading_actions_added=False,
        source_clocks_modified=False,old_A_B_used=False)
    result['sha256']=digest(result)
    return result

def frozen_tasks(case,date,reference):
    root=os.environ.get('EB_FROZEN_TASK_ROOT')
    if not root:return derive_tasks(case,date,reference)
    path=Path(root)/'tasks'/case['case_id']/(date+'.json')
    result=json.loads(path.read_text()); hashed={k:v for k,v in result.items() if k!='sha256'}
    if digest(hashed)!=result['sha256'] or result['household_case_sha256']!=digest(case) or result['reference_sha256']!=digest(reference):
        raise ValueError('FROZEN_TASK_IDENTITY_MISMATCH')
    return result

def bind(problem,case,reference):
    tc=frozen_tasks(case,problem['anchor'],reference)
    by_kind={t['kind']:t for t in tc['tasks']}
    if set(by_kind)!={j['kind'] for j in problem['jobs']}:raise ValueError('TASK_INVENTORY_MISMATCH')
    for job in problem['jobs']:
        t=by_kind[job['kind']]
        job['native_execution_release_min']=job['release_min']
        job['release_min']=t['ready_min']
        job['start_window_min'][0]=math.ceil(t['ready_min']/10)*10
        if t.get('ready_after_function'):
            job['depends_on_need_id']=problem['anchor']+':daily:washer'
            job['programme_order_origin']=t['dependency_origin']
        job['task_load_id']=t['load_id']
        job['task_context_sha256']=tc['sha256']
    problem['task_context']=deepcopy(tc)
    return problem

def attach(problem):
    if problem.get('task_context',{}).get('schema')!=VERSION:
        raise ValueError('LIFE_TASKS_MUST_PRECEDE_A_BINDING')
    return problem

def upgrade_problem(problem):
    if problem.get('task_context',{}).get('schema')!=VERSION:
        raise ValueError('OLD_B_CANNOT_BE_RELABELED_AS_LIFE_DERIVED')
    return deepcopy(problem)

def audit_tasks(task_context,plan):
    errors=[];by_kind={r['kind']:r for r in plan['tasks']}
    if len(by_kind)!=len(plan['tasks']):errors.append('DUPLICATE_DAILY_PROGRAMME')
    if set(by_kind)!={r['kind'] for r in task_context['tasks']}:errors.append('SHARED_TASK_SET_CHANGED')
    for t in task_context['tasks']:
        row=by_kind.get(t['kind'])
        if row is None:continue
        if row['start_min']<t['ready_min']:errors.append('TASK_BEFORE_DECLARED_READY_TIME')
        if row['end_min']>t['deadline_min']:errors.append('TASK_AFTER_DECLARED_DEADLINE')
        if row['end_min']-row['start_min']!=t['duration_min']:errors.append('INCOMPLETE_DAILY_PROGRAMME')
        if t.get('ready_after_function'):
            p=by_kind.get('washer')
            if p is None or p['end_min']>row['start_min']:errors.append('SAME_LOAD_PREDECESSOR_NOT_FINISHED')
    return sorted(set(errors))
