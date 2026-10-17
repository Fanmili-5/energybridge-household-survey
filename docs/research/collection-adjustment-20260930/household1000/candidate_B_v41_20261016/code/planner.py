"""Allocate mechanisms and portfolios from frozen A inputs, before any B is built."""
import itertools,collections
from scipy.optimize import linear_sum_assignment
from common import *
from events import for_case
from event_proposals import eligible

_scores={}
def opportunity(c,e,family):
    key=(c['case_id'],e['event_id'],family)
    if key not in _scores:_scores[key]=_opportunity(c,e,family)
    return _scores[key]

def _opportunity(c,e,family):
    pool,future=eligible(c);xs=pool[family];a,b=e['start_min'],e['end_min']
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

def allocate(rows):
    counts=collections.Counter();assignments={};summary=collections.Counter()
    for ri,row in enumerate(rows):
        _scores.clear();w=read(A_STAGE/row['A_world_path']);cases=[read(A_STAGE/r['path'])for r in row['cases']]
        for c in cases:c['VPP_events']=for_case(w,c)
        available=set(range(10));selected={}
        # Two portfolio slots per household; retain half the pause/reverse slots
        # each across households. This is a declared input design, not a success quota.
        removed='thermal_pause'if rank(w['household_id'],'extra-portfolio-slot')%2 else'reverse_direction'
        wanted=[k for k in MECHANISMS if k not in('coordinated',removed)]
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
            counts[combo]+=1;available.remove(i);selected[i]={'mechanism':'coordinated','portfolio':list(combo),'focus_event_id':e['event_id'],'input_opportunity_families':positive,'requested_families':len(combo),'candidate_class':'opportunity_prioritized'if slot==0 else'preassigned_stress','selection_used_B_results':False}
        indexes=sorted(available);matrix=[];best_events={}
        for kind in wanted:
            row_scores=[]
            for i in indexes:
                e=max(cases[i]['VPP_events'],key=lambda e:(mechanism_score(cases[i],e,kind),-rank(cases[i]['case_id'],kind,e['event_id'])))
                best_events[kind,i]=e
                row_scores.append(mechanism_score(cases[i],e,kind)*100+rank(w['household_id'],kind,i)%97/100)
            matrix.append(row_scores)
        rr,cc=linear_sum_assignment(matrix,maximize=True)
        for k,j in zip(rr,cc):
            kind=wanted[k];i=indexes[j];e=best_events[kind,i]
            selected[i]={'mechanism':kind,'focus_event_id':e['event_id'],'input_opportunity_score':mechanism_score(cases[i],e,kind),'candidate_class':'mechanism_coverage_including_limited_opportunity','selection_used_B_results':False}
        for i,c in enumerate(cases):assignments[c['case_id']]=selected[i];summary[selected[i]['mechanism']]+=1
        if (ri+1)%100==0:print({'input_design_households':ri+1},flush=True)
    return {'schema':'eb.input_only_coverage_plan.v41','A_bindings_sha256':sha(A_STAGE/'A_BINDINGS10000.json'),'assignments':assignments,'requested_portfolio_counts':{'+'.join(k):v for k,v in counts.items()},'requested_mechanisms':dict(summary),'allocation_before_B_construction':True,'A_dates_events_or_answers_resampled':False}
