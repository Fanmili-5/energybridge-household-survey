"""Independent source, activity, service and provenance audit; no generator import."""
from pathlib import Path
from collections import Counter
from copy import deepcopy
import json,hashlib,sys
ROOT=Path(__file__).resolve().parent
WORK={'employed','employed_full_time','employed_part_time'}
QUOTAS={'A':166,'B':198,'C':125,'D':151,'E':156,'F':204}
def need(x,msg):
    if not x:raise ValueError(msg)
def intersects(a,b,x,y):return max(a,x)<min(b,y)
def home(es,mid,a,b):return not any(e['member_id']==mid and e['location']=='away' and intersects(a,b,e['start'],e['end']) for e in es)
def available(es,mid,a,b):return not any(e['member_id']==mid and (e['location']=='away' or e['kind'] in ('work','study','bathing')) and intersects(a,b,e['start'],e['end']) for e in es)
def count_home(es,mid,d):
    lo=d*1440+540;hi=d*1440+900
    intervals=[(max(lo,e['start']),min(hi,e['end'])) for e in es if e['member_id']==mid and e['location']=='away' and intersects(lo,hi,e['start'],e['end'])]
    total=0;right=lo
    for a,b in sorted(intervals):
        total+=max(0,b-max(a,right));right=max(right,b)
    return 360-total
def check(c,s,old):
    h=c['household'];p=c['household_provenance'];cal=h['calendar'];es=cal['weekly_events'];ids={m['id'] for m in h['members']};adults={m['id'] for m in h['members'] if m['age_band'][0]>=18}
    # All raw-source fields must remain byte-equivalent as JSON objects.
    for key in old:
        if key not in ('case_id','household','household_provenance','schema_version','previous_case_id'):need(c[key]==old[key],'source-layer changed: '+key)
    need(c['previous_case_id']==old['previous_case_id'],'lost source case binding')
    if c['source']['dataset']=='ENABLE_EU':
        raw=s['es'][c['source']['household_key']];bound=next(m for m in h['members'] if m['id']==h['source_respondent_member_id'])
        sex={1:'male',2:'female'}.get(raw['S5']);birth=int(raw['S4']) if raw['S4'] and raw['S4']!=9999 else None
        need(bound.get('sex_from_source')==sex and bound.get('source_birth_year')==birth,'respondent sex/birth-year binding')
        job={1:'employed_full_time',2:'employed_part_time',3:'not_employed',4:'retired',5:'student',6:'not_employed'}.get(raw['S3'])
        if job:need(bound['employment']==job,'ENABLE respondent job binding')
        need(birth is None or bound['age_band'][0]<=2019-birth,'respondent birth-year age impossible by release')
    need(h['attitudes']==old['household']['attitudes'] and h['role_id']==old['household']['role_id'],'original EB condition changed')
    need(not cal['reference_week_contract']['same_week_as_survey'],'source week reconstruction claim')
    for m in h['members']:
        mid=m['id'];need(mid in ids,'member id')
        previous=next(x for x in old['household']['members'] if x['id']==mid)
        need(m['age_band']==previous['age_band'] and m.get('observed_age')==previous.get('observed_age'),'source-compatible member age changed')
        tag=p[f'members.{mid}.employment']
        if tag['status']=='benchmark_assigned' and mid in adults:need('joint coverage-design' in tag['reason'],'unconditional employment default')
        own=sorted([e for e in es if e['member_id']==mid],key=lambda x:x['start'])
        for a,b in zip(own,own[1:]):need(a['end']<=b['start'],'overlapping member activities '+mid)
        works=[e for e in own if e['kind']=='work']
        if mid in adults:
            need(sum(e['paid_minutes'] for e in works)==m['weekly_work']['paid_minutes'],'paid workload total')
            detail=c.get('source_member_details',{}).get(m.get('source_person_key'),{})
            obs=detail.get('work_hours_last_week',{}).get('value')
            if m['employment'] in WORK and obs is not None and obs>0:need(sum(e['paid_minutes'] for e in works)==int(obs*60),'observed weekly work hours not retained')
            if m['employment'] not in WORK:need(not works,'nonworker assigned job')
            for e in works:
                need(e['end']-e['start']==e['paid_minutes']+e['break_minutes']+e['commute_roundtrip_minutes'],'work plus commute duration')
                need(e['start']<=e['worksite_start']<=e['worksite_end']<=e['end'],'worksite geometry')
            frequency=c['source_person'].get('commute_frequency',{}).get('value')
            if mid==h['source_respondent_member_id'] and frequency is not None and m['employment'] in WORK:
                need(len(works)==frequency and all(e['location']=='away' for e in works),'observed commute frequency changed')
    for e in es:need(e['member_id'] in ids and 0<=e['start']<e['end']<=8*1440,'invalid event bounds')
    for d in range(7):
        expected=[mid for mid in ids if count_home(es,mid,d)>=210]
        need(set(expected)==set(cal['daytime_home_member_ids'][d]) and bool(expected)==cal['daytime_home'][d],'home count differs from event geometry')
        night=[mid for mid in ids if home(es,mid,(d+1)*1440,(d+1)*1440+1)]
        need(set(night)==set(cal['overnight_home_member_ids'][d]) and bool(night)==cal['overnight_home'][d],'overnight absence lacks connected event')
    known=c['known_presence']['value']
    if isinstance(known,dict) and 'someone_home_weekdays' in known:need(sum(cal['daytime_home'][:5])==known['someone_home_weekdays'],'source daytime count')
    if isinstance(known,dict) and 'occupied_days' in known:need(sum(cal['daytime_home'])==known['occupied_days'] and sum(cal['overnight_home'])==known['occupied_nights'],'source weekly occupancy')
    for day in h['routine']['daily_services']:
        d=day['day'];base=1440*d;seen=Counter();baths=day['bathing_services']
        for meal in day['meals']:
            a=base+meal['start'];b=base+meal['end'];need(0<=meal['start']<meal['end']<=1440 and bool(meal['participants']),'meal bounds/participants')
            for mid in meal['participants']:
                need(mid in ids,'unknown meal participant');seen[(mid,meal['kind'])]+=1
                need(home(es,mid,a,b)==(meal['location']=='home'),'meal location contradicts member activity')
                need(not any(e['member_id']==mid and e['kind'] in ('escort','transport','bathing','overnight_visit') and intersects(a,b,e['start'],e['end']) for e in es),'meal during travel or bathing')
                for e in es:
                    if e['member_id']==mid and e['kind']=='work' and e['location']=='away' and intersects(a,b,e['start'],e['end']):need(a>=e['worksite_start'] and b<=e['worksite_end'],'meal during work commute')
        need(all(seen[(mid,kind)]==1 for mid in ids for kind in ('breakfast','lunch','dinner')),'member lacks exactly three main meal needs')
        need({x['member_id'] for x in baths}==ids and len(baths)==len(ids),'missing individual bathing service')
        for a,b in zip(sorted(baths,key=lambda x:x['start']),sorted(baths,key=lambda x:x['start'])[1:]):need(a['end']<=b['start'],'one-bathroom capacity conflict')
        for x in baths:
            a=base+x['start'];b=base+x['end'];mid=x['member_id'];need(home(es,mid,a,b),'bathing while away')
            need(not any(e['member_id']==mid and e['kind'] in ('work','study') and intersects(a,b,e['start'],e['end']) for e in es),'bathing while working')
            if x['assistant_id'] and x['assistant_id']!='external_in_home_care':need(x['assistant_id'] in adults and available(es,x['assistant_id'],a,b),'bath assistant unavailable')
        need(day['chore_member_ids'],'no resident for chore opportunity')
        need(h['routine']['laundry_must_complete_whole_cycles'],'fragmented laundry need')
    for arrangement in h['care_arrangements']:
        child=arrangement['child_id'];need(arrangement['caregiver_id'] in adults,'invalid caregiver')
        need(p['care.'+child]['status']=='benchmark_assigned','experimental childcare relabelled observed')
        sessions=arrangement['institution_sessions'];member=next(m for m in h['members'] if m['id']==child)
        detail=c.get('source_member_details',{}).get(member.get('source_person_key'),{});hours=detail.get('nursery_hours',{}).get('value')
        if hours is not None and member['age_band'][1]<6 and member['school_enrolled']:need(len(sessions)==5 and all(x['end']-x['start']==hours*60 for x in sessions),'source nursery duration changed')
        for trip in arrangement['transport_legs']:
            who=trip['responsible'];a,b=trip['child_interval']
            need(who in adults or who in ('external_supervised_transport','independent_reference_travel'),'unknown escort')
            if who in adults:need(any(e['member_id']==who and e['kind']=='escort' and e['start']<=a and e['end']>=b and child in e.get('child_ids',[])+e.get('accompanying_child_ids',[]) for e in es),'escort missing from adult calendar')
        covered=arrangement['home_supervision']
        for x in covered:
            a=x['start'];b=x['end'];who=x['caregiver_id'];need(home(es,child,a,b),'home supervision while child away')
            if member['age_band'][1]<6:
                if x.get('mode')=='sleep_on_premise':need(a%1440>=1200,'infant daytime care bypassed as sleep')
                else:need(x.get('mode')=='direct_childcare','infant care reduced to reachable adult')
            if who!='external_in_home_care':
                reachable=x.get('mode') in ('adult_on_premise_reachable','sleep_on_premise')
                need(who in adults and (home(es,who,a,b) if reachable else available(es,who,a,b)),'caregiver absent, working or bathing')
        for d in range(7) if arrangement['home_care_must_have_adult'] else []:
            lo=d*1440+360;hi=d*1440+1320
            points=sorted({lo,hi,*[max(lo,min(hi,v)) for e in es if e['member_id']==child for v in (e['start'],e['end'])],*[max(lo,min(hi,v)) for x in covered for v in (x['start'],x['end'])]})
            for a,b in zip(points,points[1:]):
                if home(es,child,a,b):need(any(x['start']<=a and x['end']>=b for x in covered),'uncovered home child supervision interval')
    if h['ev']:
        v=h['ev'];hours=(v['departure_soc_target']-v['arrival_soc'])*v['reference_battery_kwh']/(v['reference_charger_kw']*v['charge_efficiency'])
        need(v['charging_contiguity']=='one_continuous_session_is_required_for_base_need','fragmented base EV charging')
        need(abs(hours-v['minimum_continuous_charge_hours'])<0.001,'EV arithmetic')
        need(v['parking_sessions'],'missing EV sessions')
        need(v['parking_sessions_are_opportunities_not_repeated_demands'] is True,'EV demand repeated without a weekly energy balance')
        for x in v['parking_sessions']:
            need(hours<=(x['next_departure']-x['arrival'])/60+1e-6,'EV charge exceeds parking window')
            need(home(es,v.get('vehicle_user_member_id',h['decision_maker_id']),x['arrival'],x['next_departure']),'EV reference car away inside parking window')
    if c['benchmark_role']=='C':need(h['routine']['information_contract']['changes'] and not h['routine']['information_contract']['claims_real_unpredictability'],'C variable-information scope')
    return True

