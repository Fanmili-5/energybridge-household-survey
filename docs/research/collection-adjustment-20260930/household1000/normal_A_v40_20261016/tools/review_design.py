"""All-household upstream readback and causal/invariance controls, separate from static feasibility."""
import json,sys,copy,collections,datetime as dt
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *
from activity_model import build_day
from dishes import preference

def main():
    records=read(OUT/'A_BINDINGS10000.json')['records'];oldstage=BASE/'normal_A_v38_20261016';old={r['household_id']:r for r in read(oldstage/'A_BINDINGS10000.json')['records']}
    counts=collections.Counter();dinners=collections.Counter();old_dinners=collections.Counter();starts=collections.Counter();habits=collections.Counter();unique=collections.Counter();bad=[];examples=[];fixture=None
    for ri,r in enumerate(records):
        w=read(OUT/r['A_world_path']);y=read(OUT/r['annual_A_path']);ow=read(oldstage/old[r['household_id']]['A_world_path'])
        if any(w[k]!=ow[k]for k in('members','layout','parameter_pack','role_policy','random10_date_selection')):bad.append([r['household_id'],'FAMILY_HARDWARE_OR_DATES_CHANGED'])
        if not y.get('upstream_calendar_regenerated')or y.get('parent_annual_A_sha256'):bad.append([r['household_id'],'OLD_ANNUAL_REUSED'])
        habits[tuple(w['living_habits']['dinner_min'][k]for k in('weekday','rest'))]+=1
        for c in r['cases']:
            p=read(OUT/c['path']);d=y['days'][c['date']];activity=d['activity'];dinners[activity['family_context']['dinner_min']]+=1;counts['cases']+=1
            rebuilt=build_day(w,dt.date.fromisoformat(c['date']))
            if rebuilt!=activity:bad.append([c['case_id'],'UPSTREAM_CALENDAR_NOT_REBUILT'])
            if activity['habit_realization']['date_hash_minute_jitter']or activity['habit_realization']['VPP_B_or_answers_used']:bad.append([c['case_id'],'JITTER_OR_OUTCOME_USED'])
            # Each resident's meals and baths must precede their own saved sleep.
            for mid,s in activity['member_specs'].items():
                if s['dinner_min']+30>s['sleep_min']or s['bath_min']+10>s['sleep_min']:bad.append([c['case_id'],mid,'MEAL_OR_BATH_AFTER_SLEEP'])
            cp=next(t for t in old[r['household_id']]['cases']if t['date']==c['date']);previous=read(oldstage/cp['path']);oldact=next(z['activity']for z in previous['days']if z['date']==c['date']);old_dinners[oldact['family_context']['dinner_min']]+=1
            counts['changed_target_day_calendar_records']+=activity!=oldact
            counts['changed_target_day_member_calendars']+=activity['member_calendars']!=oldact['member_calendars']
            counts['changed_family_dinner_times']+=activity['family_context']['dinner_min']!=oldact['family_context']['dinner_min']
            base=origin(dt.date.fromisoformat(c['date']))
            starts.update(t['start_min']-base for t in y['tasks']if t['kind']=='dishwasher'and t['need_id']==c['date']+':dishes')
            if fixture is None and w['N']==1 and w['members'][0]['age_years']>=18 and activity['family_context']['dinner_min']==activity['habit_realization']['usual_dinner_min']and activity['family_context']['dinner_min']<=1140:fixture=(copy.deepcopy(w),c['date'])
        unique[r['unique_substantive_days']]+=1
        if r['household_id']in('ordinary-v6-0001','ordinary-v6-0102','ordinary-v6-0263','ordinary-v6-0661'):
            examples.append({'household_id':r['household_id'],'habits':w['living_habits'],'days':[{'date':c['date'],'context':y['days'][c['date']]['activity']['habit_realization'],'member_specs':y['days'][c['date']]['activity']['member_specs']}for c in r['cases']]})
        if (ri+1)%100==0:print({'upstream_design_households':ri+1},flush=True)
    w,date=fixture;day=build_day(w,dt.date.fromisoformat(date));w2=copy.deepcopy(w)
    for ph in w2['living_habits']['dinner_min']:w2['living_habits']['dinner_min'][ph]+=60
    day2=build_day(w2,dt.date.fromisoformat(date));assert day2['family_context']['dinner_min']==day['family_context']['dinner_min']+60
    wrapper=lambda d:{'activity':d}
    assert preference(wrapper(day2),wrapper(day2),'after_meal')==preference(wrapper(day),wrapper(day),'after_meal')+60
    counter=copy.deepcopy(w);counter['VPP_events']=[{'target_kw':999}];counter['B']={'arbitrary':'bad'};counter['human_answers']={'accepted':False}
    assert day==build_day(counter,dt.date.fromisoformat(date))
    assert day==build_day(w,dt.date.fromisoformat(date))
    # A genuinely later return is tested through an already-declared variable role.
    later_return_test=False
    for r in records:
        fw=read(OUT/r['A_world_path']);member=next((m for m in fw['members']if m['reference_activity_role']=='given_variable_work_reference'and m['age_years']>=18),None)
        if member is None:continue
        date0=dt.date(2025,3,17);early=copy.deepcopy(fw);late=copy.deepcopy(fw);early['living_habits']['late_obligation_weekdays']=[];late['living_habits']['late_obligation_weekdays']=[0]
        a=build_day(early,date0);b=build_day(late,date0);mid=member['member_id']
        assert b['member_specs'][mid]['arrival_min']>a['member_specs'][mid]['arrival_min']
        assert b['family_context']['member_dinners_min'][mid]>=b['member_specs'][mid]['arrival_min']+20
        later_return_test=True;break
    if not later_return_test:bad.append(['NO_LATER_RETURN_CAUSAL_FIXTURE'])
    tests={'stable_household_habit_changes_real_calendar':True,'dinner_dependency_changes_dish_release_preference':True,'later_actual_return_constrains_dinner':later_return_test,'A_independent_of_VPP_B_and_answers':True,'same_inputs_reproduce_calendar':True}
    report={'schema':'eb.upstream_life_design_review.v40','accepted':not bad and counts['cases']==10000,'counts':dict(counts),'errors':bad,'dinner_minutes_counts':dict(dinners),'previous_A38_dinner_minutes_counts':dict(old_dinners),'household_dinner_habit_counts':{str(k):v for k,v in habits.items()},'unique_substantive_days':dict(unique),'causal_and_invariance_tests':tests,'no_empirical_population_frequency_claim':True,'thermal_delivery_validated':False,'rules_sha256':rules_id()}
    save(OUT/'DESIGN_REVIEW.json',report);save(OUT/'review/生活习惯与十天示例.json',examples)
    save(OUT/'DISHWASHER_DESIGN_REVIEW.json',{'case_dish_batches':sum(starts.values()),'starts_at21':starts[1260],'top10_relative_start_minutes':starts.most_common(10),'source_rules_sha256':rules_id(),'counts_do_not_prove_observed_habit_frequencies':True})
    print(canonical(report))
    if not report['accepted']:raise SystemExit(2)
if __name__=='__main__':main()
