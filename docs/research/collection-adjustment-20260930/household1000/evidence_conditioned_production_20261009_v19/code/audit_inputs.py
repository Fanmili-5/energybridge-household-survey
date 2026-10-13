"""All1000 dated source/age/care/room/task audit; no actor answer labels."""
import collections,copy,datetime as dt,concurrent.futures
from common import *
from checks import assess
from activity_model import dated,UNAVAILABLE,day_type

def one(h):
    w=read(OUT/h['world_path']);old=read(SOURCE/'worlds'/f'{h["household_id"]}.json');fail=[];stats=collections.Counter();free=[];examples=[]
    if any(w[k]!=old[k] for k in ('N','G','H6','H7','layout','ego_relationships','random10_date_selection')):fail.append(['ANCHOR_CHANGED'])
    if [d['types'] for d in w['parameter_pack']['devices']]!=[d['types'] for d in old['parameter_pack']['devices']]:fail.append(['DEVICE_COVERAGE_CHANGED'])
    if [r['date'] for r in h['rounds']]!=[r['date'] for r in old['random10_date_selection']['dates']]:fail.append(['DATES_CHANGED'])
    for new,prev in zip(w['members'],old['members']):
        if any(new[k]!=prev[k] for k in ('member_id','age_years','sex','current_work_source_proxy','ego_relation_code','generation_level')):fail.append(['SOURCE_MEMBER_CHANGED'])
        if new['current_work_source_proxy'] is None:
            stats['unknown_employment_members']+=1
            if new['employment_status']!='unknown':fail.append(['UNKNOWN_PROMOTED_TO_KNOWN'])
        if new['age_years']>=18 and new['current_work_source_proxy']==2:
            stats['adult_code2_correct_has_work']+=1
            if new['employment_status']!='has_work':fail.append(['CODE2_WRONG'])
        stats['members']+=1
    for row in h['rounds']:
        p=read(OUT/row['pair_path']);stats['pairs']+=1
        if sha(OUT/row['pair_path'])!=row['pair_sha256'] or p['world_sha256']!=w['world_content_sha256']:fail.append([p['case_id'],'BINDING'])
        assess_result=assess(p)
        if assess_result['integrity_errors'] or assess_result['constraint_flags']['A']:fail.append([p['case_id'],assess_result])
        if p['A']==p['B']:fail.append([p['case_id'],'IDENTITY_PAIR'])
        days=p['dated_activity_days']
        if days!=[dated(w,dt.date.fromisoformat(p['date'])+dt.timedelta(days=d)) for d in range(3)]:fail.append([p['case_id'],'DATED_CONTEXT_CHANGED'])
        for day in days:
            stats['dated_household_days']+=1
            rooms={r['room_id'] for r in w['layout']['rooms'] if w['household_id'] in r['using_household_ids']}
            for m in w['members']:
                mid=m['member_id'];ints=day['member_calendars'][mid]
                if ints[0]['start_min']!=0 or ints[-1]['end_min']!=1440 or any(a['end_min']!=b['start_min'] for a,b in zip(ints,ints[1:])):fail.append([p['case_id'],mid,'INCOMPLETE_DAY'])
                if any(i['location']=='home' and i['room_id'] not in rooms for i in ints):fail.append([p['case_id'],mid,'ROOM_ACCESS'])
                asleep=sum(i['end_min']-i['start_min'] for i in ints if i['activity'] in ('sleep_rest','day_nap'))
                age=m['age_years'];bounds=(840,1020) if age==0 and m['infant_months_reference']<4 else (720,960) if age==0 else (660,840) if age<3 else (600,780) if age<6 else (540,720) if age<13 else (480,600) if age<18 else None
                if bounds and not bounds[0]<=asleep<=bounds[1]:fail.append([p['case_id'],mid,'SLEEP_BOUND',asleep,bounds])
                if age==0:
                    stats['infant_days_with_naps']+=bool(any(i['activity']=='day_nap' for i in ints))
                    stats['infant_days']+=1
                if m['employment_status']=='unknown' and age>=18 and any(i['activity'] in ('work','home_work','given_short_work_activity') for i in ints):fail.append([p['case_id'],mid,'UNKNOWN_WORK_IMPUTED'])
                if day['day_type']=='national_holiday' and any(i['activity'] in ('school','given_daycare') for i in ints):fail.append([p['case_id'],mid,'HOLIDAY_CLASS'])
                if m['employment_status']=='unknown' and age>=18 and mid in day['operator_windows_min']:
                    free.append(sum(b-a for a,b in day['operator_windows_min'][mid]))
            for who,windows in day['operator_windows_min'].items():
                if who not in day['member_calendars']:continue
                for a,b in windows:
                    if any(i['location']!='home' or i['activity'] in UNAVAILABLE or i['activity']=='given_child_meal' for i in day['member_calendars'][who] if overlap((a,b),(i['start_min'],i['end_min']))):fail.append([p['case_id'],who,'AVAILABILITY_CONFLATION'])
            bath=sorted(day['family_context']['bath_times_min'].values())
            if any(b<a+10 for a,b in zip(bath,bath[1:])):fail.append([p['case_id'],'BATH_RESOURCE_OVERLAP'])
            for entry in day['supervision_ledger']:
                who=entry['responsible_person_id'];a=entry['start_min'];b=entry['end_min']
                if who in day['member_calendars']:
                    spans=[i for i in day['member_calendars'][who] if overlap((a,b),(i['start_min'],i['end_min']))]
                    if any(i['location']!='home' or i['activity'] in ('sleep_rest','day_nap','home_work','work') for i in spans):fail.append([p['case_id'],who,'CARE_UNCOVERED'])
                elif not any(v['person_id']==who and v['start_min']<=a and b<=v['end_min'] for v in day['external_visits']):fail.append([p['case_id'],who,'EXTERNAL_CARE_UNBOUND'])
            # Independently enumerate every child's calendar, rather than only
            # checking care records that the generator happens to emit.
            for child in (m for m in w['members'] if m['age_years']<6):
                cid=child['member_id'];stats['under6_child_days_checked']+=1
                if 'daycare' in child['reference_activity_role'] and day['day_type'] not in ('weekday','makeup_workday'):stats['daycare_closed_child_days_checked']+=1
                for item in day['member_calendars'][cid]:
                    if item['location']!='home':continue
                    for a in range(item['start_min'],item['end_min'],10):
                        b=a+10
                        if item['activity'] not in ('sleep_rest','day_nap'):
                            entries=[e for e in day['supervision_ledger'] if cid in e['child_ids'] and e['start_min']==a and e['end_min']==b]
                            stats['under6_awake_home_slots_checked']+=1
                            if len(entries)!=1:fail.append([p['case_id'],cid,a,'UNDER6_SUPERVISION_OMISSION'])
                        else:
                            present=any(m['age_years']>=18 and any(i['location']=='home' and i['start_min']<=a and b<=i['end_min'] for i in day['member_calendars'][m['member_id']]) for m in w['members'])
                            provider=any(v['start_min']<=a and b<=v['end_min'] and 'care coverage' in v['reason'] for v in day['external_visits'])
                            stats['under6_rest_presence_slots_checked']+=1
                            if not (present or provider):fail.append([p['case_id'],cid,a,'UNDER6_REST_UNATTENDED'])
            trip=day['transport']
            if trip:
                tc=w['given_transport_contract']
                if tc['resident_driving_licence_observed'] is not None or trip['driver_id']!=tc['driver_id']:fail.append([p['case_id'],'DRIVER_SOURCE_CONFLATION'])
                member=trip['travelling_member_id']
                if any(i['location']!='outside' for i in day['member_calendars'][member] if overlap((trip['departure_min'],trip['arrival_min']),(i['start_min'],i['end_min']))):fail.append([p['case_id'],member,'JOURNEY_CHRONOLOGY'])
            if day['day_type']=='national_holiday':stats['national_holiday_days']+=1
        stats['cross_midnight_controls_retained']+=sum(c['start_min']//1440!=(c['end_min']-1)//1440 for c in p['A']['controls']+p['B']['controls'])
        stats['sleep_service_intervals']+=sum(n['kind']=='ac' and n.get('includes_given_sleep_service',False) for n in p['needs_A'])
        for n in p['needs_A']:
            if n['kind']=='washer':
                dryer=any(x['kind']=='dryer' and x['upstream_need_id']==n['need_id'] for x in p['needs_A'])
                if n['wearable_clothes_ready_at_program_end'] is not (False if dryer else None):fail.append([p['case_id'],'WASH_END_DELIVERY_CONFLATION'])
    return h['household_id'],stats,free,fail

def main():
    school_guard();sel=read(OUT/'SELECTION1000.json');fail=[];counts=collections.Counter();free=[]
    with concurrent.futures.ProcessPoolExecutor(max_workers=16) as pool:
        for hid,stats,values,errors in pool.map(one,sel['records']):counts.update(stats);free.extend(values);fail.extend([[hid,*error] for error in errors])
    sample=read(OUT/sel['records'][0]['rounds'][0]['pair_path']);broken=copy.deepcopy(sample)
    broken['needs_B'][0]['quantity']+=1;assert 'NEEDS_CHANGED' in assess(broken)['integrity_errors']
    broken=copy.deepcopy(sample);broken['B']['controls'].append({'asset_id':sample['world']['devices'][0]['asset_id'],'kind':'ac_setpoint','start_min':0,'end_min':10,'value_C':25});assert 'PRE_NOTICE_INPUT_CHANGED' in assess(broken)['integrity_errors']
    free.sort();report={'schema':'eb.dated_world_input_audit.v19','households':len(sel['records']),**dict(counts),'failures':fail,
        'unknown_adult_dated_free_minutes':{'n':len(free),'min':min(free),'median':free[len(free)//2],'max':max(free),'mean':sum(free)/len(free)},
        'authoritative_joint_diary_calibration':False,'human_validity_measured':False,'human_answers':0,
        'assertions':'source anchors,age sleep,naps,care cover,dated rooms and availability,A/B/version integrity,holiday calendars',
        'regressions':['altered demand detected','pre-notice control alteration detected']}
    save(OUT/'INPUT_AUDIT.json',report);print({k:v for k,v in report.items() if k!='failures'},'failures',len(fail),flush=True)
    if fail:raise RuntimeError(str(fail[:10]))
if __name__=='__main__':main()
