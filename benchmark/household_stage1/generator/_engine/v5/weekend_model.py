"""Declared weekend coverage, constrained by existing work and home-count evidence."""
from copy import deepcopy
import activity_model as activity
STRATA=('no_added_outing','short_outings','half_day_outing','split_household_outing')
def apply(c,events,targets,ordinal):
    h=c['household'];p=c['household_provenance'];members=h['members'];allids=[m['id'] for m in members];adults=[m['id'] for m in members if m['age_band'][0]>=18];children=[m['id'] for m in members if m['age_band'][0]<18]
    stratum=STRATA[ordinal%4]
    if stratum=='no_added_outing':plans=[[]]
    elif stratum=='short_outings':plans=[[(5,600,690,allids),(6,900,990,allids)],[(6,600,690,allids)],[(5,900,990,allids)]]
    elif stratum=='half_day_outing':plans=[[(6,810,1050,allids)],[(5,810,1050,allids)]]
    else:
        cohort=([adults[0]]+children) if len(adults)>1 else allids
        plans=[[(5,600,840,cohort)],[(6,810,1050,cohort)],[(5,810,1050,cohort)]]
    rejected=[];chosen=None
    for plan in plans:
        candidate=deepcopy(events);ok=True
        for j,(day,start,end,people) in enumerate(plan):
            a=day*1440+start;b=day*1440+end
            if any(not activity.free(candidate,mid,a-15,b+15,care=True) for mid in people):ok=False;break
            if children and not any(mid in adults for mid in people):ok=False;break
            group=f"{c['case_id']}-weekend-{day}-{j}"
            for mid in people:activity.add(candidate,mid,'family_outing',a,b,'away',group_id=group,participants=people,activity_reason='reference shopping, visit or family activity; not observed',supervising_adult_ids=[mid for mid in people if mid in adults],experimental=True)
        if ok:
            for d in (5,6):
                t=targets[d]
                if t is not None and bool([mid for mid in allids if activity.home_minutes(candidate,mid,d)>=210])!=t:ok=False;break
        if ok:chosen=(candidate,plan);break
        rejected.append('conflicts with locked work/presence or adult availability')
    if chosen is None:
        # Source work/occupation is never changed to create a leisure slot.
        chosen=(events,[])
    final,plan=chosen
    h['weekend_design']={'requested_stratum':stratum,'actual_added_outings':len(plan),'blocks':[{'day':d,'start':a,'end':b,'participants':ps} for d,a,b,ps in plan],'infeasible_plans':rejected,'fallback_to_existing_commitments':chosen[0] is events and stratum!='no_added_outing','status':'benchmark_assigned','not_a_population_rate':True}
    activity.tag(p,'weekend_design','cyclic weekend coverage within country-role cells; observed work and presence constraints kept, not fitted weekend rates')
    return final
