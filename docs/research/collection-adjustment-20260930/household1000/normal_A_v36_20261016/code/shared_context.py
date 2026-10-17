"""V33 auxiliary calendars, recomputed against the same dated target activity."""
import datetime as dt
from common import rank,digest,overlap
from activity_model import dated,day_type

def dated_context(w,date):
    if isinstance(date,str):date=dt.date.fromisoformat(date)
    target=dated(w,date);context=w['shared_context'];dtype=day_type(date);rooms=w['layout']['rooms']
    calendars={};grids={};reservations=[];external_visits=[];bath=next((r for r in rooms if r['room_id']=='washroom'),None)
    if bath and len(bath['using_household_ids'])>1:
        for mid,start in target['family_context']['bath_times_min'].items():
            reservations.append({'person_id':mid,'household_id':w['household_id'],'room_id':bath['room_id'],
                                 'start_min':start,'end_min':start+10,'purpose':'target bath'})
    hall=next((r['room_id']for r in rooms if r['census_room_class']=='hall'),None)
    for h in context['households']:
        for m in h['members']:
            mid=m['member_id'];private=m['reference_home_room_id'];grid=[('at_home',private,'home')]*144
            for slot in list(range(0,42))+list(range(138,144)):grid[slot]=('sleep',private,'home')
            lo,hi=(48,108)if dtype in('weekday','makeup_workday')else(60,72)
            for slot in range(lo,hi):grid[slot]=('outside_commitment',None,'outside')
            if hall:
                for slot in range(114,120):grid[slot]=('shared_living',hall,'home')
            if bath and h['household_id']in bath['using_household_ids']:
                candidates=[t for t in range(1080,1380,10)if all(not overlap((t,t+10),(r['start_min'],r['end_min']))for r in reservations if r['room_id']==bath['room_id'])]
                if not candidates:raise ValueError('SHARED_BATH_CAPACITY:'+w['household_id']+':'+str(date))
                t=candidates[0];reservations.append({'person_id':mid,'household_id':h['household_id'],
                    'room_id':bath['room_id'],'start_min':t,'end_min':t+10,'purpose':'auxiliary bath,separate hot-water supply'})
                grid[t//10]=('bathing',bath['room_id'],'home')
            grids[mid]=grid
    # A shared kitchen is a resource with a finite sequence of cooking slots.
    for kitchen in[r for r in rooms if r['census_room_class']=='kitchen'and len(r['using_household_ids'])>1]:
        users=kitchen['using_household_ids'];dinner=target['family_context']['dinner_min']
        reservations.append({'household_id':w['household_id'],'person_id':None,'room_id':kitchen['room_id'],
            'start_min':dinner-30,'end_min':dinner,'purpose':'target meal preparation/provision'})
        for other in users:
            if other==w['household_id']:continue
            hh=next((h for h in context['households']if h['household_id']==other),None)
            cook=hh['members'][0]['member_id']if hh else other+':given_kitchen_visitor'
            slots=[t for t in range(1080,1380,20)if all(not overlap((t,t+20),(r['start_min'],r['end_min']))for r in reservations if r['room_id']==kitchen['room_id'])
                   and(cook not in grids or all(grids[cook][i][2]=='home'and grids[cook][i][0]not in('sleep','bathing')for i in range(t//10,(t+20)//10)))]
            if not slots:raise ValueError('SHARED_KITCHEN_CAPACITY:'+w['household_id'])
            t=slots[0];reservations.append({'household_id':other,'person_id':cook,'room_id':kitchen['room_id'],
                'start_min':t,'end_min':t+20,'purpose':'given auxiliary meal preparation;target appliances excluded'})
            if cook in grids:
                for i in range(t//10,(t+20)//10):grids[cook][i]=('meal_preparation',kitchen['room_id'],'home')
            else:external_visits.append({'person_id':cook,'room_id':kitchen['room_id'],'start_min':t,'end_min':t+20,'outside_residence_not_population_target':True})
    for mid,grid in grids.items():
        out=[];a=0
        for i in range(1,145):
            if i==144 or grid[i]!=grid[a]:
                activity,room,location=grid[a];out.append({'start_min':a*10,'end_min':i*10,'activity':activity,'room_id':room,'location':location});a=i
        calendars[mid]=out
    result={'date':date.isoformat(),'member_calendars':calendars,'facility_reservations':reservations,'external_visits':external_visits,
            'target_activity_day_sha256':target['activity_day_sha256'],'A_B_common':True}
    result['context_sha256']=digest(result);return result
