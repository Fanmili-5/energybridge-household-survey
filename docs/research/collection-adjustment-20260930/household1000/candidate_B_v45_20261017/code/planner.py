"""Allocate mechanisms and portfolios from frozen A inputs, before any B is built."""
import itertools,collections
from scipy.optimize import linear_sum_assignment
from common import *
from events import for_case
from event_proposals import eligible,mechanism_eligibility,continuous_thermal_pool

_scores={}
def opportunity(c,e,family):
    key=(c['case_id'],e['event_id'],family)
    if key not in _scores:_scores[key]=_opportunity(c,e,family)
    return _scores[key]

def _opportunity(c,e,family):
    pool,future=eligible(c);xs=continuous_thermal_pool(pool[family])if family=='ac'else pool[family];a,b=e['start_min'],e['end_min']
    if not xs:return 0
    def ol(x):return max(0,min(x['end_min'],b)-max(x['start_min'],a))
    if family=='ac':return max(ol(x)for x in xs)
    if family=='water_heater':return max(ol(x)for x in xs)
    if family=='ev':
        if e['direction']=='down':return max(max(0,min(x['actual_charge_end_min'],b)-max(x['start_min'],a))for x in xs)
        return max(max(0,min(x['end_min'],b)-max(x['start_min'],a))for x in xs)
    score=0
    for x in xs:
        end=max(t['end_min']for t in c['A']['tasks']if t['need_id']in(x['need_id'],x['need_id']+':dry'))
        if e['direction']=='down':score=max(score,max(0,min(end,b)-max(x['start_min'],a)))
        else:
            load=next(o for o in c['A']['operations']if o['kind']=='load'and o['need_id']==x['need_id'])
            n=next(n for n in c['needs_A']if n['need_id']==x['need_id'])
            earliest=max(DECISION,load['end_min']);latest=n['deadline_min']-(end-x['start_min'])
            if earliest<b and latest>=a:score=max(score,min(b-max(a,earliest),b-a))
    return score

def mechanism_score(c,e,kind):
    pool,future=eligible(c)
    if kind in('thermal_setpoint','thermal_pause','reverse_direction'):return opportunity(c,e,'ac')
    if kind in('hotwater_preheat','hotwater_target'):return opportunity(c,e,'water_heater')
    if kind in('ev_delay','ev_short_window'):return opportunity(c,e,'ev')
    fs=['washer','dishwasher']
    if kind=='handling_shift':fs=[f for f in fs if any(t['need_id']in future for t in pool[f])]
    return max([opportunity(c,e,f)for f in fs]+[0])

def decorate(c,assignment,families):
    events=c['VPP_events'];joint=len(events)>1 and (assignment['candidate_class']=='opportunity_prioritized'or rank(c['case_id'],'all-event-input-policy')%2==0)
    assignment.update(multi_event_policy='single_event'if len(events)==1 else'joint_all_events'if joint else'single_event_stress',
        eligibility_checked_before_B=True,available_mechanisms=sorted(k for k,v in mechanism_eligibility(c).items()if v))
    if joint and families:
        # Assign different devices to different windows where available, using
        # frozen A opportunities. Existing up-window service has priority;
        # no completed B, physical result, or human response enters this plan.
        choices=[];pool,_=eligible(c)
        for mapping in itertools.product(events,repeat=len(families)):
            preserved=0
            for family,e in zip(families,mapping):
                if e['direction']!='up':continue
                if family=='ev':
                    preserved+=any(overlap((x['start_min'],x.get('actual_charge_end_min',x['end_min'])),(e['start_min'],e['end_min']))for x in pool[family])
                elif family in('washer','dishwasher'):
                    preserved+=any(overlap((x['start_min'],x['end_min']),(e['start_min'],e['end_min']))for x in pool[family])
            positive=sum(opportunity(c,e,f)>0 for f,e in zip(families,mapping))
            score=sum(min(90,opportunity(c,e,f))for f,e in zip(families,mapping))
            choices.append((mapping,preserved,len({e['event_id']for e in mapping}),positive,score))
        chosen=max(choices,key=lambda x:(x[1],x[2],x[3],x[4],-rank(c['case_id'],'joint-family-event',[e['event_id']for e in x[0]])))
        assignment['family_event_assignments']={f:e['event_id']for f,e in zip(families,chosen[0])}
    return assignment

def mechanism_families(c,kind):
    if kind in('thermal_setpoint','thermal_pause','reverse_direction'):return ['ac']
    if kind in('ev_delay','ev_short_window'):return ['ev']
    if kind in('hotwater_preheat','hotwater_target'):return ['water_heater']
    return [] # one actual program is selected from the input pool; no fictitious two-device assignment

def allocate(rows):
    counts=collections.Counter();mechanism_counts=collections.Counter();assignments={};summary=collections.Counter()
    for ri,row in enumerate(rows):
        _scores.clear();w=read(A_STAGE/row['A_world_path']);cases=[read(A_STAGE/r['path'])for r in row['cases']]
        for c in cases:c['VPP_events']=for_case(w,c)
        available=set(range(10));selected={}
        removed='thermal_pause'if rank(w['household_id'],'extra-portfolio-slot')%2 else'reverse_direction'
        catalog=[k for k in MECHANISMS if k not in('coordinated',removed)]
        for slot in range(2):
            options=[]
            for i in available:
                c=cases[i];pool,_=eligible(c);fs=sorted(k for k,v in pool.items()if v)
                for combo in list(itertools.combinations(fs,2))+list(itertools.combinations(fs,3)):
                    for e in c['VPP_events']:
                        scores=[opportunity(c,e,f)for f in combo];positive=sum(x>0 for x in scores)
                        options.append((i,combo,e,positive,sum(min(x,90)for x in scores)))
            full=[o for o in options if o[3]==len(o[1])]
            candidates=(full or options)if slot==0 else options
            if not candidates:raise ValueError('NO_INPUT_PORTFOLIO:'+w['household_id'])
            i,combo,e,positive,score=min(candidates,key=lambda o:(counts[o[1]],-o[3],-o[4],rank(w['household_id'],slot,o[0],o[1],o[2]['event_id'])))
            counts[combo]+=1;available.remove(i)
            selected[i]=decorate(cases[i],{'mechanism':'coordinated','portfolio':list(combo),'focus_event_id':e['event_id'],'input_opportunity_families':positive,'requested_families':len(combo),'candidate_class':'opportunity_prioritized'if slot==0 else'preassigned_stress','selection_used_B_results':False},list(combo))
        indexes=sorted(available);matrix=[];options=[];best_events={}
        # Eligibility is a hard input constraint. Repetition carries a design
        # penalty, so a home lacking tank/EV gets a mix of other existing
        # mechanisms rather than eight catalog slots followed by one fallback.
        for kind in catalog:
            for occurrence in range(8):
                row_scores=[]
                for i in indexes:
                    possible=mechanism_eligibility(cases[i])[kind]
                    if not possible:row_scores.append(-1e12);continue
                    e=max(cases[i]['VPP_events'],key=lambda e:(mechanism_score(cases[i],e,kind),-rank(cases[i]['case_id'],kind,e['event_id'])))
                    best_events[kind,i]=e
                    row_scores.append(-occurrence*100000+mechanism_score(cases[i],e,kind)*100-mechanism_counts[kind]*.01+rank(w['household_id'],kind,i)%97/100)
                matrix.append(row_scores);options.append(kind)
        rr,cc=linear_sum_assignment(matrix,maximize=True)
        for k,j in zip(rr,cc):
            kind=options[k];i=indexes[j]
            if matrix[k][j]<-1e11:raise ValueError('NO_ELIGIBLE_INPUT_ASSIGNMENT:'+w['household_id'])
            e=best_events[kind,i];mechanism_counts[kind]+=1
            selected[i]=decorate(cases[i],{'mechanism':kind,'focus_event_id':e['event_id'],'input_opportunity_score':mechanism_score(cases[i],e,kind),'candidate_class':'mechanism_coverage_including_limited_opportunity','selection_used_B_results':False},mechanism_families(cases[i],kind))
        for i,c in enumerate(cases):assignments[c['case_id']]=selected[i];summary[selected[i]['mechanism']]+=1
        if (ri+1)%100==0:print({'input_design_households':ri+1},flush=True)
    return {'schema':'eb.input_only_coverage_plan.v45','A_bindings_sha256':sha(A_STAGE/'A_BINDINGS10000.json'),'assignments':assignments,'requested_portfolio_counts':{'+'.join(k):v for k,v in counts.items()},'requested_mechanisms':dict(summary),'allocation_before_B_construction':True,'eligibility_is_hard_input_constraint':True,'multi_event_policies':dict(collections.Counter(x['multi_event_policy']for x in assignments.values())),'A_dates_events_or_answers_resampled':False}
