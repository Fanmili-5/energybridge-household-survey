"""Source-locked, jointly completed experimental household reference weeks."""
from pathlib import Path
from copy import deepcopy
from collections import Counter
import hashlib, json, math, sys

ROOT = Path(__file__).resolve().parent
PREVIOUS = ROOT.parent / 'stage1_benchmark_20261107_v3'
PIN = 'fe97dfcb377e9c8b24bd5a296930eb9289621c0e84855be32e96f586c735452d'
SEED = 'EB-household-joint-v4-20261107'
WORK = {'employed', 'employed_full_time', 'employed_part_time'}
QUOTAS = {'A':166,'B':198,'C':125,'D':151,'E':156,'F':204}
FAMILIES = ['onsite_workers','part_time_workers','mixed_home_based_work','care_or_home_activity']

def rank(*args):
    return int(hashlib.sha256(json.dumps([SEED,*args],sort_keys=True).encode()).hexdigest(),16)

def tag(p, key, reason, fields=(), status='benchmark_assigned'):
    p[key] = {'status':status,'source_fields':list(fields),'reason':reason}

def overlap(a,b,c,d):
    return max(a,c)<min(b,d)

def add(events, mid, kind, start, end, location, **kw):
    assert start<end, (kind,start,end)
    e = dict(member_id=mid,kind=kind,start=start,end=end,location=location,**kw)
    events.append(e)
    return e

def free(events, mid, a, b, care=False):
    excluded = {'work','study','meal','bathing','transport','school','nursery','extended_school_care','community_program','overnight_visit'}
    if care: excluded |= {'work','study'}
    return not any(e['member_id']==mid and overlap(a,b,e['start'],e['end']) and
                   (e['location']=='away' or e['kind'] in excluded) for e in events)

def at_home(events, mid, a, b):
    return not any(e['member_id']==mid and e['location']=='away' and overlap(a,b,e['start'],e['end']) for e in events)

def meal_location(events,mid,a,b):
    for e in events:
        if e['member_id']!=mid or not overlap(a,b,e['start'],e['end']):continue
        if e['kind'] in ('transport','escort','overnight_visit'):return None
        if e['kind']=='work' and e['location']=='away' and (a<e['worksite_start'] or b>e['worksite_end']):return None
    if any(e['member_id']==mid and e['kind']=='escort' and (overlap(a,b,*e['preparation_interval']) or overlap(a,b,*e['settling_interval'])) for e in events):return None
    if at_home(events,mid,a,b):return 'home'
    points=segments([(e['start'],e['end']) for e in events if e['member_id']==mid and e['location']=='away'],a,b)
    if all(any(e['member_id']==mid and e['location']=='away' and e['start']<=x and e['end']>=y for e in events) for x,y in points):return 'away'
    return None

def segments(intervals, lo, hi):
    points = sorted({lo,hi,*[max(lo,min(hi,x)) for pair in intervals for x in pair]})
    return [(a,b) for a,b in zip(points,points[1:]) if a<b]

def home_minutes(events, mid, day):
    lo=day*1440+540;hi=day*1440+900
    ints=[(e['start'],e['end']) for e in events if e['member_id']==mid and e['location']=='away']
    return sum(b-a for a,b in segments(ints,lo,hi) if not any(overlap(a,b,x,y) for x,y in ints))

def main_away(events, mid, day):
    es=[e for e in events if e['member_id']==mid and e['location']=='away' and
        e['kind'] not in ('escort','overnight_visit') and day*1440<=e['start']<(day+1)*1440]
    return [min(e['start'] for e in es)-day*1440,max(e['end'] for e in es)-day*1440] if es else []

def member_detail(c,m):
    return c.get('source_member_details',{}).get(m.get('source_person_key'),{})

def jointly_assign(c, ordinal, alternative):
    h=c['household'];p=c['household_provenance'];family=FAMILIES[(ordinal+alternative)%4]
    adults=[m for m in h['members'] if m['age_band'][0]>=18]
    unknown=[]
    for i,m in enumerate(adults):
        if p[f"members.{m['id']}.employment"]['status'] in ('observed','survey_imputed'):
            continue
        unknown.append(m['id'])
        if m['school_enrolled']:
            job='student'
        elif m['age_band'][0]>=65:
            job='employed_part_time' if (ordinal+i+alternative)%4==0 else 'retired'
        elif family=='onsite_workers':job='employed_full_time'
        elif family=='part_time_workers':job='employed_part_time'
        elif family=='mixed_home_based_work':job='employed_full_time'
        else:job='home_caregiver' if any(x['age_band'][0]<12 for x in h['members']) else 'not_employed'
        m['employment']=job
        tag(p,f"members.{m['id']}.employment",'joint coverage-design family '+family+'; not estimated employment or a national rate')
    no_remote=c['source_person']['teleworking_household']['value'] is False
    for m in h['members']:
        working=m['employment'] in WORK
        home_based=(family=='mixed_home_based_work' and m['id'] in unknown and not no_remote)
        m['work_mode']='home_based' if working and home_based else 'onsite' if working else 'not_applicable'
        m['activity']='work' if working else 'school' if m['school_enrolled'] else 'care' if m['employment']=='home_caregiver' else 'home_activity'
        tag(p,f"members.{m['id']}.work_mode",'joint weekly activity design; source household telework constraints retained')
    h['completion_design']={'family':family,'unobserved_adult_member_ids':unknown,'selection':'balanced cyclic coverage within country-role cells; constrained feasibility fallback','alternative_index':alternative,'population_employment_estimate':False,'sex_used_for_activity_assignment':False}
    tag(p,'completion_design','declared experimental design; one shared household configuration, not independent defaults')

def target_presence(c):
    known=c['known_presence']['value'];key=c['case_id']
    if isinstance(known,dict) and 'someone_home_weekdays' in known:
        order=sorted(range(5),key=lambda d:rank(key,'home-day',d))
        selected=set(order[:known['someone_home_weekdays']])
        return [d in selected if d<5 else None for d in range(7)]
    if isinstance(known,dict) and 'occupied_days' in known:
        order=[5,6]+sorted(range(5),key=lambda d:rank(key,'home-day',d))
        selected=set(order[:known['occupied_days']]);return [d in selected for d in range(7)]
    return [None]*7

def work_parameters(c,m):
    detail=member_detail(c,m);job=m['employment']
    observed=detail.get('work_hours_last_week',{}).get('value')
    hours=float(observed) if observed is not None and 0<observed<=80 else 20.0 if job=='employed_part_time' else 40.0
    commute_h=detail.get('commute_hours_roundtrip',{}).get('value')
    commute_m=detail.get('commute_minutes_roundtrip',{}).get('value')
    commute=(commute_h or 0)*60+(commute_m or 0) if commute_h is not None or commute_m is not None else 40
    freq=c['source_person'].get('commute_frequency',{}).get('value') if m['id']==c['household']['source_respondent_member_id'] else None
    n=int(freq) if freq is not None and freq>0 else max(1,min(7,math.ceil(hours/max(5,11-commute/60))))
    if freq is None and hours>=30:n=max(5,n)
    paid=int(round(hours*60));pieces=[paid//n+(d<paid%n) for d in range(n)]
    return pieces,commute,observed,freq

def build_activities(c):
    h=c['household'];p=c['household_provenance'];ms=h['members'];adult=[m for m in ms if m['age_band'][0]>=18]
    actor=h['decision_maker_id'];targets=target_presence(c);events=[];helper=[];no_remote=c['source_person']['teleworking_household']['value'] is False
    params={m['id']:work_parameters(c,m) for m in adult if m['employment'] in WORK}
    for d,t in enumerate(targets):
        candidates=[m for m in adult if not (m['id']==actor and c['benchmark_role'] in 'AF' and d<len(params.get(m['id'],([],))[0]))]
        candidates.sort(key=lambda m:(m['employment'] in WORK,m['school_enrolled'],rank(c['case_id'],'helper',m['id'])))
        helper.append(candidates[0]['id'] if t is True and candidates else None)
        if t is True and not candidates:raise ValueError('no compatible daytime member')
    shifts=[0,60,-30,45,-60] if c['benchmark_role']=='C' else [0]*5
    for m in adult:
        mid=m['id'];m['weekly_work']={'paid_minutes':0,'basis':'not_applicable','source_last_week_hours':None,'source_week_reconstruction':False}
        if m['employment'] in WORK:
            pieces,commute,observed,freq=params[mid];m['weekly_work'].update(paid_minutes=sum(pieces),basis='source_last_week_hours_as_reference_load' if observed is not None and observed>0 else 'experimental_typical_week',source_last_week_hours=observed,source_commute_roundtrip_minutes=commute,commute_measured=bool(member_detail(c,m).get('commute_hours_roundtrip',{}).get('value') is not None or member_detail(c,m).get('commute_minutes_roundtrip',{}).get('value') is not None))
            actual_modes=[]
            for d,paid in enumerate(pieces):
                can_remote=not no_remote and not (mid==actor and c['benchmark_role'] in 'AF') and not (mid==h['source_respondent_member_id'] and freq is not None) and not (member_detail(c,m).get('commute_hours_roundtrip',{}).get('value') or member_detail(c,m).get('commute_minutes_roundtrip',{}).get('value'))
                remote=(m['work_mode']=='home_based' and targets[d] is not False) or (helper[d]==mid and can_remote)
                if remote and not can_remote:remote=False
                start=510
                if mid==actor and c['benchmark_role']=='A':start=540
                if helper[d]==mid and not remote:start=780
                if targets[d] is False:start=540 if paid<=300 else 480
                start+=shifts[d] if d<5 and mid==actor and helper[d]!=mid else 0
                extra=30 if paid>=300 else 0;end=start+paid+extra+(0 if remote else commute)
                if end>1365:
                    if helper[d]==mid and not remote:raise ValueError('late shift cannot retain both home count and evening needs')
                    start-=end-1365;end=1365
                travel=0 if remote else commute
                add(events,mid,'work',d*1440+start,d*1440+end,'home' if remote else 'away',paid_minutes=paid,commute_roundtrip_minutes=travel,break_minutes=extra,reference_shift=True,worksite_start=d*1440+start+travel/2,worksite_end=d*1440+end-travel/2)
                actual_modes.append(remote)
            m['work_mode']='home_based' if all(actual_modes) else 'hybrid' if any(actual_modes) else 'onsite'
        elif m['school_enrolled']:
            for d in range(5):
                start=1020 if helper[d]==mid else 480
                add(events,mid,'study',d*1440+start,d*1440+start+180,'away',activity_reason='reference adult education timetable')
        else:
            for d,t in enumerate(targets):
                if t is False:
                    offset=shifts[d] if d<5 and mid==actor else 0
                    add(events,mid,'community_program',d*1440+600+offset,d*1440+840+offset,'away',activity_reason='structured community activity / personal errands reference block; not a measured job')
                elif mid==actor and c['benchmark_role']=='C' and d<5:
                    add(events,mid,'community_program',d*1440+720+shifts[d],d*1440+810+shifts[d],'away',activity_reason='controlled variation in personal activity, not an observed diary')
        tag(p,f'members.{mid}.weekly_work','reference paid workload and commute, source-hour anchors retained separately from an actual week',member_detail(c,m).get('work_hours_last_week',{}).get('fields',()))
    # Every absent daytime has an explicit non-work activity for remaining adults.
    for d,t in enumerate(targets):
        if t is False:
            for m in adult:
                if home_minutes(events,m['id'],d)>=210:
                    a=d*1440+600;b=d*1440+840
                    if any(e['member_id']==m['id'] and e['location']=='away' and overlap(a,b,e['start'],e['end']) for e in events):
                        raise ValueError('daytime target incompatible with reference shift')
                    add(events,m['id'],'community_program',a,b,'away',activity_reason='off-work community learning / errands reference block')
    # Source household telework=yes is existential, not an identified person.
    if c['source_person']['teleworking_household']['value'] is True:
        if not any(e['kind']=='work' and e['location']=='home' for e in events):
            options=[e for e in events if e['kind']=='work' and not (e['member_id']==actor and c['benchmark_role'] in 'AF') and targets[e['start']//1440] is not False]
            if options:
                e=options[0];e['location']='home';e['end']-=e['commute_roundtrip_minutes'];e['commute_roundtrip_minutes']=0;e['worksite_start']=e['start'];e['worksite_end']=e['end']
                next(m for m in ms if m['id']==e['member_id'])['work_mode']='hybrid'
            else:
                h['completion_design']['source_telework_not_assigned_this_week']=True
                h['completion_design']['source_telework_scope_note']='household survey flag retained; not linked to a worker or forced onto a different reference week'
    known=c['known_presence']['value'];nightmask=[True]*7
    if isinstance(known,dict) and 'occupied_nights' in known:
        # Each night is a connected, explicitly timed reference overnight visit.
        for d in [5,6,4,3,2,1,0][:7-known['occupied_nights']]:
            nightmask[d]=False
            for m in ms:add(events,m['id'],'overnight_visit',d*1440+1290,(d+1)*1440+390,'away',activity_reason='reference overnight visit 21:30 to next day 06:30; destination unspecified experiment')
    return events,targets,nightmask

def schooling_and_care(c,events):
    h=c['household'];p=c['household_provenance'];ms=h['members'];adults=[m for m in ms if m['age_band'][0]>=18];care=[]
    for child in ms:
        if child['age_band'][0]>=18:continue
        mid=child['id'];young=child['age_band'][1]<6;supervised=child['age_band'][0]<12
        relation=c.get('care_context',{}).get('value') or {}
        source_link=child.get('source_person_key')==relation.get('child_key') and bool(relation)
        caregiver=next((m['id'] for m in adults if source_link and m.get('source_person_key')==relation.get('adult_caregiver_key')),None)
        if caregiver is None and c['benchmark_role']=='E':caregiver=h['decision_maker_id']
        if caregiver is None:caregiver=min(adults,key=lambda m:(m['employment'] in WORK,rank(c['case_id'],'caregiver',m['id'])))['id']
        legs=[];institution=[]
        if child['school_enrolled']:
            hours=member_detail(c,child).get('nursery_hours',{}).get('value')
            for d in range(5):
                begin=d*1440+480 if young else d*1440+510
                end=begin+int(hours*60) if young and hours is not None else begin+240 if young else d*1440+930
                drop=begin if young else d*1440+480
                pickup=end if young else d*1440+960
                if not young and supervised:
                    returns=[e['end'] for e in events if e['member_id'] in [a['id'] for a in adults] and e['kind'] in ('work','study') and d*1440<=e['start']<(d+1)*1440 and e['end']<=d*1440+1080]
                    if not any(at_home(events,a['id'],pickup,pickup+30) for a in adults) and returns:pickup=max(pickup,min(returns)+30)
                if drop<begin:add(events,mid,'extended_school_care',drop,begin,'away',provider='reference supervised before-school service')
                add(events,mid,'nursery' if young else 'school',begin,end,'away',provider='source enrollment, experimental exact timetable')
                if end<pickup:add(events,mid,'extended_school_care',end,pickup,'away',provider='reference supervised after-school service')
                institution.append({'day':d,'start':begin,'end':end,'kind':'nursery' if young else 'school','hours_basis':'observed_duration' if young and hours is not None else 'experimental'})
                for typ,a,b in [('dropoff',drop-15,drop),('pickup',pickup,pickup+15)]:
                    adult_start=a if typ=='dropoff' else a-15
                    adult_end=b+15 if typ=='dropoff' else b
                    route='nursery' if young else 'school'
                    shared=next((e for e in events if e['kind']=='escort' and e.get('escort_leg')==typ and e.get('reference_route')==route and e['start']==adult_start and e['end']==adult_end),None)
                    escorts=[adult for adult in adults if free(events,adult['id'],adult_start-15,adult_end+15,care=True)] if supervised else []
                    escorts.sort(key=lambda m:(m['id']!=caregiver,m['id']))
                    who=shared['member_id'] if shared else escorts[0]['id'] if escorts else 'external_supervised_transport' if supervised else 'independent_reference_travel'
                    add(events,mid,'transport',a,b,'away',escort=who)
                    if shared:shared['child_ids'].append(mid)
                    elif escorts:add(events,who,'escort',adult_start,adult_end,'away',child_id=mid,child_ids=[mid],escort_leg=typ,reference_route=route,required_turnaround_buffer_minutes=15,preparation_interval=[adult_start-15,adult_start],settling_interval=[adult_end,adult_end+15],activity_reason='shared reference route when institution category and clocks match; dropoff returns alone, pickup returns with child')
                    legs.append({'day':d,'kind':typ,'child_interval':[a,b],'responsible':who,'basis':'experimental_logistics'})
        if supervised or source_link:
            coverage=[]
            for d in range(7) if supervised else []:
                lo=d*1440+360;hi=d*1440+1320
                cuts=[(e['start'],e['end']) for e in events if e['member_id']==mid or e['member_id'] in [m['id'] for m in adults]]
                for a,b in segments(cuts,lo,hi):
                    if not at_home(events,mid,a,b):continue
                    available=[m['id'] for m in adults if free(events,m['id'],a,b,care=True)]
                    assigned=caregiver if caregiver in available else available[0] if available else 'external_in_home_care'
                    if coverage and coverage[-1]['end']==a and coverage[-1]['caregiver_id']==assigned:coverage[-1]['end']=b
                    else:coverage.append({'start':a,'end':b,'caregiver_id':assigned,'basis':'experimental_supervision'})
            care.append({'child_id':mid,'caregiver_id':caregiver,'daytime_setting':'preschool' if young and child['school_enrolled'] else 'school' if child['school_enrolled'] else 'home','source_care_link':source_link,'institution_sessions':institution,'transport_legs':legs,'home_supervision':coverage,'home_care_must_have_adult':supervised,'external_services_are_experimental':True})
            tag(p,'care.'+mid,'per-child institution, handoff and home supervision; outside services explicitly experimental')
    h['care_arrangements']=care
    r=c.get('care_context',{}).get('value')
    h['observed_care_links']=[]
    if r:
        adult=next(m['id'] for m in ms if m.get('source_person_key')==r['adult_caregiver_key'])
        child=next(m['id'] for m in ms if m.get('source_person_key')==r['child_key'])
        h['observed_care_links']=[{'caregiver_id':adult,'child_id':child,'scope':'source_last_week','source_fields':c['care_context']['fields'],'status':c['care_context']['status']}]
        tag(p,'care.observed_links','same-household source care relation, independent of role and reference-week assignment',c['care_context']['fields'],status=c['care_context']['status'])

def build_services(c,events):
    h=c['household'];p=c['household_provenance'];ms=h['members'];daily=[];adults=[m for m in ms if m['age_band'][0]>=18]
    for d in range(7):
        base=d*1440
        first=min([e['start']-base for e in events if base<=e['start']<base+1440 and e['member_id'] in [m['id'] for m in ms] and e['kind'] in ('work','study','transport','escort','community_program')]+[480])
        breakfast=min(450,first-40)
        if breakfast<315:raise ValueError('reference morning has no breakfast interval')
        meals=[]
        for kind,start,duration in [('breakfast',breakfast,20),('lunch',750,30)]:
            groups={}
            for m in ms:
                found=None
                for offset in [0,-15,15,-30,30,-45,45,-60,60,-90,90]:
                    t=start+offset;loc=meal_location(events,m['id'],base+t,base+t+duration)
                    if loc:found=(t,loc);break
                if found is None:raise ValueError('no non-travel meal interval')
                groups.setdefault(found,[]).append(m['id'])
            for (t,loc),ids in sorted(groups.items()):meals.append({'kind':kind,'start':t,'end':t+duration,'participants':ids,'location':loc,'supervision':'resident or explicitly contracted care' if any(m['id'] in ids and m['age_band'][0]<12 for m in ms) else 'not_required'})
        dinners={}
        for m in ms:
            end=max([e['end']-base for e in events if e['member_id']==m['id'] and e['location']=='away' and base<=e['start']<base+1440 and e['kind'] in ('work','study','escort','community_program','transport')]+[1050])
            t=max(1080,end+20)
            loc='home'
            if t>1260:
                e=next((e for e in events if e['member_id']==m['id'] and e['kind']=='work' and e['location']=='away' and base<=e['start']<base+1440),None)
                t=int(min(1140,e['worksite_end']-base-30)) if e else 1140;loc='away'
            if m['age_band'][1]<12:t=1080;loc='home' if at_home(events,m['id'],base+t,base+t+30) else 'away'
            found=None
            for offset in [0,-15,15,-30,30,-45,45,-60,60]:
                time=t+offset;where=meal_location(events,m['id'],base+time,base+time+30)
                if where:found=(time,where);break
            if found is None:raise ValueError('no dinner interval outside travel')
            dinners.setdefault(found,[]).append(m['id'])
        for (t,loc),ids in sorted(dinners.items()):meals.append({'kind':'dinner','start':t,'end':t+30,'participants':ids,'location':loc})
        # Meals inside work/school are breaks, never a second activity elsewhere.
        bathing=[];used=[]
        for m in sorted(ms,key=lambda m:(m['age_band'][0]>=12,m['id'])):
            mid=m['id'];duration=15 if m['age_band'][1]<6 else 10
            chosen=None;assistant=None;fallback=None
            for t in range(1200 if m['age_band'][0]>=18 and any(x['age_band'][1]<6 for x in ms) else 1110,1391-duration,5):
                if not free(events,mid,base+t,base+t+duration,care=False):continue
                if any(e['member_id']==mid and e['kind']=='escort' and (overlap(base+t,base+t+duration,*e['preparation_interval']) or overlap(base+t,base+t+duration,*e['settling_interval'])) for e in events):continue
                if any(mid in meal['participants'] and overlap(t,t+duration,meal['start'],meal['end']) for meal in meals):continue
                if any(overlap(t,t+duration,a,b) for a,b in used):continue
                if m['age_band'][1]<12 and t+duration>1260:continue
                if m['age_band'][1]<6:
                    options=[a['id'] for a in adults if free(events,a['id'],base+t,base+t+duration,care=True) and not any(a['id'] in meal['participants'] and overlap(t,t+duration,meal['start'],meal['end']) for meal in meals)]
                    if not options:
                        if fallback is None:fallback=t
                        continue
                    assistant=options[0]
                chosen=t;break
            if chosen is None and fallback is not None:chosen=fallback;assistant='external_in_home_care'
            if chosen is None:raise ValueError('no nonoverlapping per-member bathing slot')
            bathing.append({'member_id':mid,'start':chosen,'end':chosen+duration,'assistant_id':assistant,'service':'assisted_bath' if m['age_band'][1]<6 else 'shower'})
            used.append((chosen,chosen+duration));add(events,mid,'bathing',base+chosen,base+chosen+duration,'home')
        chores=[e['end']-base for e in events if e['kind']=='work' and e['member_id']==h['decision_maker_id'] and base<=e['start']<base+1440]
        preferred=c['routine'].get('weekday_activity_start_minutes',[1080]*5)[d] if c['benchmark_role'] in 'CD' and d<5 else 1080
        start=max(1020,min(1200,preferred))
        candidates=list(dict.fromkeys([start,1080,1020,1140,1200,570,600,660,360,390,420]+list(range(360,1291,15))))
        chosen=None
        for t in candidates:
            available=[a['id'] for a in adults if at_home(events,a['id'],base+t,base+t+120)
                       and not any(e['member_id']==a['id'] and e['kind']=='work' and overlap(base+t,base+t+120,e['start'],e['end']) for e in events)
                       and not (c['benchmark_role']=='E' and a['id']==h['decision_maker_id'] and any(overlap(t,t+120,x,y) for x,y in h['routine']['care_protection_windows']))]
            if available:chosen=(t,available);break
        if chosen is None:raise ValueError('no two-hour household chore opportunity')
        start,chore_members=chosen
        daily.append({'day':d,'breakfast_minutes':breakfast,'lunch_minutes':750,'lunch_at_home':any(x['kind']=='lunch' and x['location']=='home' for x in meals),'dinner_minutes':min(x['start'] for x in meals if x['kind']=='dinner'),'meals':meals,'bathing_services':bathing,'shower_window':[min(x['start'] for x in bathing),max(x['end'] for x in bathing)],'flexible_chore_window':[start,start+120],'chore_member_ids':chore_members,'chore_window_is_service_opportunity_not_appliance_schedule':True})
    h['routine']['daily_services']=daily
    h['routine']['laundry_must_complete_whole_cycles']=True
    h['routine']['information_contract']={'reference_week_is_actual_diary':False,'C_changes_are_measured':False,'schedule_change_model':'controlled day-to-day departures and activity timing, announced 60 minutes before first changed activity' if c['benchmark_role']=='C' else 'reference regular schedule; non-work days and source presence constraints may differ','changes':[{'day':d,'shift_minutes':s,'notice_minutes':60} for d,s in enumerate([0,60,-30,45,-60]) if s] if c['benchmark_role']=='C' else [],'claims_real_unpredictability':False}
    tag(p,'routine.daily_services','explicit meal participants and individually allocated nonoverlapping bathing demands; not an appliance dispatch plan')
    tag(p,'routine.information_contract','controlled schedule-information experimental condition; no measured unpredictability claim')

def finalize_calendar(c,events,targets,nights):
    h=c['household'];p=c['household_provenance'];ids=[m['id'] for m in h['members']];actor=h['decision_maker_id']
    # Bathing at home does not alter away occupancy, only care availability.
    people=[[mid for mid in ids if home_minutes(events,mid,d)>=210] for d in range(7)]
    actual=[bool(x) for x in people]
    for d,t in enumerate(targets):
        if t is not None and actual[d]!=t:raise ValueError('presence constraint differs after complete logistics')
    cal={'timezone':'local_clock','daytime_definition':'reference 09:00-15:00; a member home at least 210 of 360 minutes. Survey count retained; clock threshold experimental.','daytime_home':actual,'daytime_home_member_ids':people,'overnight_home':nights,'overnight_home_member_ids':[[mid for mid in ids if at_home(events,mid,d*1440+1440,d*1440+1441)] for d in range(7)],'member_away_intervals':{mid:[main_away(events,mid,d) for d in range(7)] for mid in ids},'weekly_events':sorted(events,key=lambda e:(e['start'],e['member_id'],e['kind'])),'reference_week_contract':{'same_week_as_survey':False,'observed_weekly_workload_retained_when_available':True,'exact_clocks':'experimental','school_calendar':'term-time reference week, no actual date or local holiday assertion','off_week_boundary':'Sunday overnight visit may return next Monday 06:30; boundary event retained'},'actor_workdays':sorted({e['start']//1440 for e in events if e['kind']=='work' and e['member_id']==actor})}
    cal['actor_away_intervals']=cal['member_away_intervals'][actor]
    h['calendar']=cal
    tag(p,'calendar.weekly_events','joint work, study, school transport and connected overnight reference events; exact clocks experimental')
    tag(p,'calendar.member_away_intervals','main-day summary only; full events include escort and overnight boundary intervals')
    for mid in ids:tag(p,'calendar.member_away_intervals.'+mid,'summary of full experimental event calendar, not an observed diary')
    tag(p,'calendar.daytime_home_member_ids','derived from full events using declared experimental majority-day threshold',status='derived')
    tag(p,'calendar.reference_week_contract','new experimental reference week, not a reconstruction of source fieldwork week')
    if h['ev']:
        ev=h['ev'];sessions=[];actor=ev.get('vehicle_user_member_id',actor)
        for d in range(7):
            today=[e for e in events if e['member_id']==actor and e['location']=='away' and e['kind']!='overnight_visit' and d*1440<=e['start']<(d+1)*1440]
            nextday=(d+1)%7
            tomorrow=[e for e in events if e['member_id']==actor and e['location']=='away' and e['kind']!='overnight_visit' and nextday*1440<=e['start']<(nextday+1)*1440]
            depart=min([e['start']-nextday*1440 for e in tomorrow]+[510])
            end=(d+1)*1440+depart;begin=max([e['end'] for e in today]+[d*1440+1080])
            if any(e['member_id']==actor and e['location']=='away' and overlap(begin,end,e['start'],e['end']) and e['start']>=begin for e in events):continue
            sessions.append({'arrival':begin,'next_departure':end,'parking_hours':round((end-begin)/60,4)})
        if not sessions:raise ValueError('EV has no explicit uninterrupted home parking window')
        shortest=min(x['parking_hours'] for x in sessions)
        feasible=[v/100 for v in range(20,80,5) if (0.8-v/100)*ev['reference_battery_kwh']/(ev['reference_charger_kw']*0.9)<=shortest]
        if not feasible:raise ValueError('EV continuous demand infeasible in all reference parking windows')
        ev['arrival_soc']=feasible[rank(c['case_id'],'soc')%len(feasible)];ev['departure_soc_target']=0.8
        ev['minimum_continuous_charge_hours']=round((0.8-ev['arrival_soc'])*ev['reference_battery_kwh']/(ev['reference_charger_kw']*0.9),4)
        first=sessions[0];ev.update(home_arrival_minutes=first['arrival']%1440,next_departure_minutes=first['next_departure']%1440,parking_window_hours=first['parking_hours'],parking_sessions=sessions,all_reference_parking_sessions_feasible=True,vehicle_follows_reference_actor_for_away_trips=True,parking_start_may_be_after_actual_arrival=True,service_scope='one selected parking-session episode; not repeated daily charging demand',parking_sessions_are_opportunities_not_repeated_demands=True)

def equipment_detail(c):
    h=c['household'];p=c['household_provenance']
    for name,f in {**c['devices'],**c['additional_devices']}.items():
        q=h['equipment'][name]
        if not q['present']:continue
        typ=f.get('appliance_type')
        if typ:q['appliance_type']=typ;tag(p,'equipment.'+name+'.appliance_type','source appliance distinction retained',f.get('fields',()),f['status'])
        else:q['appliance_type']='reference_'+name.removesuffix('_available');tag(p,'equipment.'+name+'.appliance_type','generic reference function; precise source technology not measured')
        if name=='water_heater_available':
            instant=typ=='instantaneous_electric_shower'
            q['thermal_storage_model']='none_instantaneous' if instant else 'not_established'
            q['storage_shift_eligible']=False
            q['storage_capacity_litres']=None
            tag(p,'equipment.'+name+'.thermal_storage_model','instantaneous shower has no storage; other heater storage not established',f.get('fields',()),f['status'] if instant else 'benchmark_model_boundary')
            tag(p,'equipment.'+name+'.storage_shift_eligible','no storage-load shifting admission without a typed storage model',status='benchmark_model_boundary')

def refresh_supervision(c,events):
    h=c['household'];adults=[m for m in h['members'] if m['age_band'][0]>=18]
    for care in h['care_arrangements']:
        if not care['home_care_must_have_adult']:continue
        mid=care['child_id'];coverage=[]
        child=next(m for m in h['members'] if m['id']==mid)
        mode='direct_childcare' if child['age_band'][1]<6 else 'adult_on_premise_reachable'
        care['supervision_mode']=mode
        for d in range(7):
            cuts=[(e['start'],e['end']) for e in events if e['member_id']==mid or e['member_id'] in [m['id'] for m in adults]]
            for a,b in segments(cuts,d*1440+360,d*1440+1320):
                if not at_home(events,mid,a,b):continue
                # A child's assisted bath is supervised by its named assistant.
                bath=next((x for x in h['routine']['daily_services'][d]['bathing_services'] if x['member_id']==mid and x['assistant_id'] and overlap(a,b,d*1440+x['start'],d*1440+x['end'])),None)
                asleep=mode=='direct_childcare' and a>=d*1440+max(1200,next(x['end'] for x in h['routine']['daily_services'][d]['bathing_services'] if x['member_id']==mid)+30)
                available=[m['id'] for m in adults if at_home(events,m['id'],a,b)] if mode=='adult_on_premise_reachable' or asleep else [m['id'] for m in adults if free(events,m['id'],a,b,care=True)]
                assigned=bath['assistant_id'] if bath else care['caregiver_id'] if care['caregiver_id'] in available else available[0] if available else 'external_in_home_care'
                current_mode='sleep_on_premise' if asleep else mode
                if coverage and coverage[-1]['end']==a and coverage[-1]['caregiver_id']==assigned and coverage[-1].get('mode')==current_mode:coverage[-1]['end']=b
                else:coverage.append({'start':a,'end':b,'caregiver_id':assigned,'basis':'experimental_supervision','mode':'sleep_on_premise' if asleep else mode})
        care['home_supervision']=coverage

def accompany_school_runs(c,events):
    h=c['household'];adults=[m for m in h['members'] if m['age_band'][0]>=18]
    for e in list(events):
        if e['kind']!='escort':continue
        a,b=e['start'],e['end'];adult=e['member_id']
        for care in h['care_arrangements']:
            if not care['home_care_must_have_adult']:continue
            child=care['child_id']
            if child in e['child_ids'] or not at_home(events,child,a,b):continue
            if any(m['id']!=adult and at_home(events,m['id'],a,b) for m in adults):continue
            add(events,child,'transport',a,b,'away',escort=adult,accompany_school_run=True)
            e.setdefault('accompanying_child_ids',[]).append(child)
            care['transport_legs'].append({'day':a//1440,'kind':'accompany_other_child_school_run','child_interval':[a,b],'responsible':adult,'basis':'experimental_logistics'})

def complete(original,ordinal,alternative=0):
    c=deepcopy(original);old=c['case_id'];c['case_id']=old.replace('EB3-','EB4-');c['previous_case_id']=old
    c['schema_version']='household_step1_v4';c['household']['completion_design']={}
    if c['source']['dataset']=='ENABLE_EU':
        supplement=json.loads((ROOT/'source_supplement.json').read_text())[c['source']['household_key']]
        c['source_supplement_v4']=deepcopy(supplement);h=c['household'];p=c['household_provenance']
        sex=supplement['respondent_sex']['value'];birth=supplement['respondent_birth_year']['value']
        choices=[m for m in h['members'] if m['age_band'][0]>=18 and m.get('sex_from_source')==sex and (birth is None or m['age_band'][0]<=2019-birth)]
        if not choices:raise ValueError('respondent sex/birth-year incompatible with adult roster')
        previous=h['source_respondent_member_id'];bound=next((m for m in choices if m['id']==previous),choices[0])
        old_member=next(m for m in h['members'] if m['id']==previous)
        if bound['id']!=previous:
            bound['employment']=old_member['employment'];p[f"members.{bound['id']}.employment"]=deepcopy(p[f'members.{previous}.employment'])
            old_member['employment']='not_employed';old_member['school_enrolled']=False
            tag(p,f'members.{previous}.employment','unmeasured co-resident: pending joint completion')
            h['source_respondent_member_id']=bound['id']
            if h['decision_maker_id']==previous:h['decision_maker_id']=bound['id']
        if bound['employment']=='student':bound['school_enrolled']=True
        bound['source_birth_year']=birth
        tag(p,'source_respondent_binding','source S5 sex and source birth-year upper-age compatibility with anonymous roster position; exact identity among compatible members is experimental',['S5','S4'],status='derived')
    jointly_assign(c,ordinal,alternative);equipment_detail(c)
    events,targets,nights=build_activities(c)
    schooling_and_care(c,events);accompany_school_runs(c,events);build_services(c,events);refresh_supervision(c,events);finalize_calendar(c,events,targets,nights)
    return c


