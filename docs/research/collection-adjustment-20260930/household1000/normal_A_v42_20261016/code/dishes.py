"""Given household dishwashing habits, driven by real dated dinner/wake/bath clocks."""
import collections,math
from common import *
STYLES=['after_meal','after_evening_routine','next_morning_timer']

def phase(day):return 'rest'if day['activity']['day_type']in('weekend','national_holiday')else'weekday'
def preference(day,nextday,style):
    dinner=max(day['activity']['family_context']['member_dinners_min'].values());release=dinner+30
    if style=='after_meal':return release+10
    if style=='after_evening_routine':
        baths=day['activity']['family_context']['bath_times_min'].values()
        return max(release+10,max(baths,default=dinner)+20)
    wakes=[x['end_min']for seq in nextday['activity']['member_calendars'].values()for x in seq if x['start_min']==0 and x['activity']in('sleep','sleep_rest')]
    return 1440+max(390,min(450,min(wakes,default=420)+20))

def profile(w,y,scheduler):
    device=next((d for d in w['parameter_pack']['devices']if'dishwasher'in d['types']),None)
    if not device:return {'applies':False,'given_not_observed':True}
    result={};keys=sorted(y['days']);days=y['days']
    for ph in ('weekday','rest'):
        selected=[min([d for d in days.values()if d['date'].startswith(f'2025-{month:02d}')and phase(d)==ph],key=lambda d:rank(w['household_id'],'dish',ph,d['date']))for month in range(1,13)]
        scores=collections.Counter()
        for day in selected:
            date=dt.date.fromisoformat(day['date']);base=origin(date);nextday=days[str(date+dt.timedelta(days=1))];release=base+max(day['activity']['family_context']['member_dinners_min'].values())+30
            deadline=base+1440+nextday['activity']['family_context']['dinner_min']-30
            loads=scheduler.slots(release,deadline-90,device['room_id']);unloads=scheduler.slots(release+100,deadline,device['room_id'])
            for style in STYLES:
                start=base+preference(day,nextday,style)
                if start%1440<390 or start%1440+90>1410:continue
                if any(start-720<=t+10<=start for t,_ in loads)and any(start+90<=t<=min(start+810,deadline-10)for t,_ in unloads):scores[style]+=1
        eligible=[s for s in STYLES if scores[s]>=6]or[s for s in STYLES if scores[s]==max(scores.values(),default=0)]
        usual=min(eligible,key=lambda s:rank(w['household_id'],'dish-habit',ph,s))
        result[ph]={'style':usual,'calendar_feasibility_counts':{s:scores[s]for s in STYLES},'eligible_styles':eligible}
    return {'applies':True,'given_not_observed':True,'choices':result,
      'basis':'EB after-dinner service and overnight timer window;researcher-given stable household style;dated dinner/bath/wake clocks;12 monthly calendars per phase',
      'B_VPP_price_or_answers_used':False,'daily_use_preserved':True,'random_minute_jitter':False}
