"""Independent all-world/all-date audit and deliberate corruption regressions."""
import collections,copy,datetime as dt
from common import *
from checks import assess
def main():
    school_guard();sel=read(OUT/'SELECTION1000.json');fail=[];clockset=set();members=0;unknown=0;changed2=0;overnight=0
    for h in sel['records']:
        w=read(OUT/h['world_path']);old=read(SOURCE/'worlds'/f'{h["household_id"]}.json')
        if any(w[k]!=old[k] for k in ('N','G','H6','H7','layout','ego_relationships','random10_date_selection')):fail.append([h['household_id'],'ANCHOR_CHANGED'])
        if len(h['rounds'])!=10 or [r['date'] for r in h['rounds']]!=[r['date'] for r in old['random10_date_selection']['dates']]:fail.append([h['household_id'],'DATE_OR_COUNT_CHANGED'])
        oldtypes=[d['types'] for d in old['parameter_pack']['devices']]
        if [d['types'] for d in w['parameter_pack']['devices']]!=oldtypes:fail.append([h['household_id'],'DEVICE_COVERAGE_CHANGED'])
        for device in w['parameter_pack']['devices']:
            if 'ev' in device['types']:
                tc=w['given_transport_contract']
                if tc['handling_operator_id']!=device['operator_id'] or tc['driver_is_resident'] is not False or tc['resident_driving_licence_observed'] is not None:
                    fail.append([h['household_id'],'DRIVER_HANDLING_SOURCE_CONFLATION'])
        for m in w['members']:
            members+=1;clockset.add(digest(m['weekly_calendar']))
            if m['current_work_source_proxy'] is None:
                unknown+=1
                if m['employment_status']!='unknown' or m['age_years']>=18 and m['reference_activity_role'] not in ('unspecified_activity_reference',):fail.append([m['member_id'],'UNKNOWN_PROMOTED_TO_JOB'])
            if m['age_years']>=18 and m['current_work_source_proxy']==2:
                changed2+=1
                if m['employment_status']!='has_work':fail.append([m['member_id'],'CHFS_CODE2_WRONG'])
            for d in m['weekly_calendar']:
                ints=d['intervals']
                if ints[0]['start_min']!=0 or ints[-1]['end_min']!=1440 or any(x['end_min']!=y['start_min'] for x,y in zip(ints,ints[1:])):fail.append([m['member_id'],'INCOMPLETE_DAY'])
                if m['reference_activity_role']=='home_worker' and d['weekday']<5 and not any(x['activity']=='home_work' for x in ints):fail.append([m['member_id'],'TRANSPORT_ERASED_HOME_WORK'])
        for day in w['routine']['weekly_family_context']:
            times=sorted(day['bath_times_min'].values())
            if any(b<a+10 for a,b in zip(times,times[1:])):fail.append([h['household_id'],'BATH_RESOURCE_OVERLAP'])
            for m in w['members']:
                s=day['bath_times_min'][m['member_id']];c=m['weekly_calendar'][day['weekday']]['intervals']
                if not any(x['activity']=='bathing' and x['start_min']<=s and s+10<=x['end_min'] for x in c):fail.append([m['member_id'],'BATH_NOT_IN_OWN_DAY'])
        for r in h['rounds']:
            p=read(OUT/r['pair_path'])
            if sha(OUT/r['pair_path'])!=r['pair_sha256'] or p['world_sha256']!=w['world_content_sha256']:fail.append([p['case_id'],'BINDING'])
            a=assess(p)
            if a['integrity_errors'] or a['constraint_flags']['A']:fail.append([p['case_id'],a])
            if p['A']==p['B']:fail.append([p['case_id'],'IDENTITY_PAIR'])
            for need in p['needs_A']:
                if need['kind']=='washer':
                    drying=any(x['kind']=='dryer' and x['upstream_need_id']==need['need_id'] for x in p['needs_A'])
                    if need['wearable_clothes_ready_at_program_end'] is not (False if drying else None):fail.append([p['case_id'],'WASH_END_IS_NOT_CHAIN_DELIVERY'])
            overnight+=sum(c['start_min']//1440!=(c['end_min']-1)//1440 for c in p['A']['controls']+p['B']['controls'])
    sample=read(OUT/sel['records'][0]['rounds'][0]['pair_path']);regressions=[]
    broken=copy.deepcopy(sample)
    if broken['needs_B']:broken['needs_B'][0]['quantity']+=1
    else:broken['needs_B'].append({'need_id':'corrupted extra demand','quantity':1})
    assert 'NEEDS_CHANGED' in assess(broken)['integrity_errors'];regressions.append('altered demand detected')
    broken=copy.deepcopy(sample);broken['A']['tasks'].append({'fake':'rewrite'})
    assert digest(broken['A'])!=broken['A_frozen_before_B_sha256'];regressions.append('frozen A alteration detected')
    broken=copy.deepcopy(sample);broken['B']['controls'].append({'asset_id':sample['world']['devices'][0]['asset_id'],'kind':'ac_setpoint','start_min':0,'end_min':10,'value_C':25})
    assert 'PRE_NOTICE_INPUT_CHANGED' in assess(broken)['integrity_errors'];regressions.append('pre-notice intervention detected')
    v=read(OUT/'worlds/ordinary-v6-0195.json');m=next(m for m in v['members'] if m['age_years']==95)
    assert m['employment_status']=='unknown' and m['reference_activity_role']=='unspecified_activity_reference';regressions.append('95-year-old unknown remains unknown and no invented commute')
    report={'households':len(sel['records']),'pairs':sum(len(h['rounds']) for h in sel['records']),'members':members,'failures':fail,
      'unique_weekly_calendars':len(clockset),'unknown_employment_members':unknown,'adult_code2_correct_has_work':changed2,
      'cross_midnight_controls_retained':overnight,'deliberate_corruption_regressions':regressions,
      'authoritative_joint_diary_calibration':False,'human_validity_measured':False,'human_answers':0}
    save(OUT/'INPUT_AUDIT.json',report);print({k:v for k,v in report.items() if k!='failures'},'failures',len(fail),flush=True)
    if fail:raise RuntimeError(str(fail[:10]))
if __name__=='__main__':main()
