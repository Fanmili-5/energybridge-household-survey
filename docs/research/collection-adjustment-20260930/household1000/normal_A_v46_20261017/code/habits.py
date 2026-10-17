import collections,statistics
from common import *
from activity_model import ranges
ANCHORS=[420,540,660,840,990,1140]
def _phase(d):return 'rest'if d['activity']['day_type']in('weekend','national_holiday')else'weekday'

def habit_profile(w,y,scheduler):
    device=next((d for d in w['parameter_pack']['devices']if'washer'in d['types']),None)
    if device is None:return {'applies_to_washer':False,'given_not_observed':True}
    duration=210 if'dryer'in device['types']else 120
    wait=240 if'dryer'in device['types']else 90
    score={};medians={};choices={}
    for phase in('weekday','rest'):
        all_days=[d for d in y['days'].values()if d['date'].startswith('2025')and _phase(d)==phase]
        sample=[min((d for d in all_days if dt.date.fromisoformat(d['date']).month==month),key=lambda d:rank(w['household_id'],phase,d['date']))for month in range(1,13)]
        counts=collections.Counter()
        for day in sample:
            base=origin(dt.date.fromisoformat(day['date']));loads=scheduler.slots(base,base+1440,device['room_id']);unloads=loads
            for anchor in ANCHORS:
                start=base+anchor;ls=[s for s in loads if start-720<=s[0]+10<=start];us=[s for s in unloads if start+duration<=s[0]<=start+duration+wait]
                if ls and us:counts[anchor]+=1
        eligible=[a for a in ANCHORS if counts[a]>=6]or[a for a in ANCHORS if counts[a]==max(counts.values(),default=0)]
        selected=min(eligible,key=lambda a:rank(w['household_id'],phase,'given-habit',a))
        earlier=[a for a in eligible if a<selected]
        linen=min(earlier,key=lambda a:rank(w['household_id'],phase,'linen-first',a))if earlier else selected
        choices[phase]={'usual_anchor_min':selected,'linen_day_anchor_min':linen,'eligible_anchors_min':eligible}
        medians[phase]=statistics.median(d['activity']['family_context']['dinner_min']for d in all_days)
        score[phase]={str(a):counts[a]for a in ANCHORS}
    return {'applies_to_washer':True,'given_not_observed':True,'choices':choices,'sampled_calendar_feasibility_counts':score,
        'dinner_reference_min':medians,'source':'12 dated calendars per phase;explicit operator/facility availability;hash chooses among feasible given habits',
        'linen_response':'given habit:prioritize already-generated household linen earlier when a feasible earlier habit exists',
        'not_inferred_from_age_sex_job_or_human_preference':True,'no_date_jitter':True}



def circulation_slots(options,events,style,hid,rid,slots_needed=6):
    """Six actual occupied slots near a given room-activity transition, never a global clock."""
    if len(options)<slots_needed:raise ValueError('INSUFFICIENT_OCCUPIED_CIRCULATION:'+rid)
    preferred=[(t,label)for t,label in events if label.startswith(style+':')]
    candidates=preferred or events
    if not candidates:raise ValueError('MISSING_ROOM_ACTIVITY_ANCHOR:'+rid)
    # Earliest real occurrence of the given habit in this 08-to-08 service day.
    anchor,label=min(candidates,key=lambda x:(x[0],x[1]))
    selected=sorted(sorted(options,key=lambda t:(max(anchor-t,0,t-(anchor+50)),abs(t-anchor),t))[:slots_needed])
    return selected,{'given_style':style,'activity_anchor_min':anchor,'activity_anchor':label,'fallback_to_actual_room_entry':not bool(preferred)}


def hold_short_indoor_absences(presence,person_room,person_home,limit=20):
    permission=set(presence);ledger=[];seq=ranges([[t,t+10]for t in presence])
    for left,right in zip(seq,seq[1:]):
        a,b=left[1],right[0]
        if not 0<b-a<=limit:continue
        returning=sorted(mid for mid,slots in person_room.items()if a-10 in slots and b in slots and all(t in person_home[mid]for t in range(a,b,10)))
        if not returning:continue
        permission.update(range(a,b,10));ledger.append({'start_min':a,'end_min':b,'returning_member_ids':returning,'reason':'short_indoor_excursion;routine_thermostat_retained','given_hold_limit_min':limit})
    return permission,ledger

def _thermostats(w,y):
    acs=[d for d in w['parameter_pack']['devices']if'ac'in d['types']];presence={d['asset_id']:set()for d in acs}
    room_assets=collections.defaultdict(list)
    for d in acs:room_assets[d['room_id']].append(d['asset_id'])
    events=collections.defaultdict(list);person_room=collections.defaultdict(lambda:collections.defaultdict(set));person_home=collections.defaultdict(set)
    opmap=collections.defaultdict(dict)
    for o in y['operations']:
        if not o['operator_id']in{m['member_id']for m in w['members']}:continue
        opmap[o['start_min']][o['operator_id']]=None if o['kind'].startswith('EV_')else o['room_id']
    for key,day in y['days'].items():
        base=origin(dt.date.fromisoformat(key));previous=y['days'].get(str(dt.date.fromisoformat(key)-dt.timedelta(days=1)));following=y['days'].get(str(dt.date.fromisoformat(key)+dt.timedelta(days=1)))
        prevcal={**previous['activity']['member_calendars'],**previous['shared']['member_calendars']}if previous else{}
        nextcal={**following['activity']['member_calendars'],**following['shared']['member_calendars']}if following else{}
        calendar={**day['activity']['member_calendars'],**day['shared']['member_calendars']}
        occupied=collections.defaultdict(set)
        for mid,seq in calendar.items():
            for j,item in enumerate(seq):
                if item['location']!='home':continue
                rid=item['room_id'];a=base+item['start_min'];b=base+item['end_min']
                if rid in room_assets:
                    before=seq[j-1]if j else(prevcal.get(mid)or[None])[-1]
                    after=seq[j+1]if j+1<len(seq)else(nextcal.get(mid)or[None])[0]
                    state=lambda x:(x['activity'],x['room_id'],x['location'])if x else None
                    if before is not None and state(before)!=state(item):events[rid].append((a,'room_entry:'+item['activity']))
                    if item['activity']=='sleep_rest':
                        if after is not None and state(after)!=state(item):events[rid].append((b,'wake_activity:sleep_end'))
                        if before is not None and state(before)!=state(item):events[rid].append((a,'evening_room_activity:sleep_start'))
                    if item['activity']=='personal_and_breakfast':events[rid].append((a,'wake_activity:personal_and_breakfast'))
                    if item['activity']=='dinner':events[rid].append((b,'evening_room_activity:dinner_end'))
                    if j and seq[j-1]['location']=='outside':events[rid].append((a,'return_to_room:actual_return'))
                for t in range(base+item['start_min'],base+item['end_min'],10):
                    person_home[mid].add(t)
                    rid=opmap.get(t,{}).get(mid,item['room_id'])
                    if rid in room_assets:occupied[rid].add(t);person_room[rid][mid].add(t)
        for rid,minutes in occupied.items():
            for aid in room_assets[rid]:presence[aid].update(minutes)
    grouped={}
    for aid,slots in presence.items():
        grouped[aid]=collections.defaultdict(list)
        for t in sorted(slots):grouped[aid][t//1440].append(t)
    event_days=collections.defaultdict(lambda:collections.defaultdict(list))
    for rid,items in events.items():
        for t,label in items:event_days[rid][t//1440].append((t,label))
    fan={aid:set()for aid in presence};start=origin(ANCHOR);stop=origin(END)
    for aid,slots in presence.items():
        rid=next(d['room_id']for d in acs if d['asset_id']==aid)
        style=w['living_habits']['circulation_styles'][rank(w['household_id'],rid,'given-room-circulation-habit')%3]
        for base in range(start,stop,1440):
            index=base//1440
            options=[t for t in grouped[aid][index]+grouped[aid][index+1]if base+480<=t<base+1920]
            choices=[(t,label)for t,label in event_days[rid][index]+event_days[rid][index+1]if base+480<=t<base+1920]
            # Actual return may first enter a corridor without AC. Associate
            # its first subsequent use of this room, without inventing presence.
            if style=='return_to_room':
                day=y['days'][str(ANCHOR+dt.timedelta(days=(base-start)//1440))]
                returns=[base+s['arrival_min']for s in day['activity']['member_specs'].values()if s.get('arrival_min')is not None]
                for arrival in returns:
                    after=[t for t in options if t>=arrival]
                    if after:choices.append((min(after),'return_to_room:first_occupied_slot_after_actual_return'))
            complete=base+1920<=stop
            selected,reason=circulation_slots(options,choices,style,w['household_id'],rid,6 if complete else min(6,len(options)))
            fan[aid].update(selected)
            key=str(ANCHOR+dt.timedelta(days=(base-start)//1440))
            y['days'][key].setdefault('circulation_assignments',[]).append({'asset_id':aid,'room_id':rid,
                **{**reason,'activity_anchor_min':reason['activity_anchor_min']-base},
                'selected_minutes':[t-base for t in selected],'given_daily_minutes':60,'complete_service_day':complete,'selected_actual_minutes':len(selected)*10,
                'A_independent_of_events_prices_and_answers':True,'no_date_jitter_or_spread_quota':True})
    permission={};holds={}
    for d in acs:
        aid=d['asset_id'];rid=d['room_id'];permission[aid],holds[aid]=hold_short_indoor_absences(presence[aid],person_room[rid],person_home,w['thermal_control_contract']['short_indoor_excursion_hold_min'])
    permission_days={}
    for aid,slots in permission.items():
        permission_days[aid]=collections.defaultdict(list)
        for t in sorted(slots):permission_days[aid][t//1440].append(t)
    cool=w['role_policy']['thermal']['usual_setpoint_C'];heat=22.
    for key,day in y['days'].items():
        base=origin(dt.date.fromisoformat(key))
        for d in acs:
            aid=d['asset_id'];slots=permission_days[aid][base//1440]
            day.setdefault('thermal_context',{})[aid]={'asset_id':aid,'room_id':d['room_id'],
                'actual_occupied_intervals_min':ranges([[t-base,t-base+10]for t in grouped[aid][base//1440]]),
                'A_permission_intervals_min':ranges([[t-base,t-base+10]for t in slots]),
                'hardware_request_intervals_min':[[0,1440]],'request_requires_human_agreement':True,
                'short_indoor_holds':[dict(h,start_min=max(h['start_min'],base)-base,end_min=min(h['end_min'],base+1440)-base)for h in holds[aid]if h['start_min']<base+1440 and h['end_min']>base],
                'usual_heating_setpoint_C':heat,'usual_cooling_setpoint_C':cool,
                'maximum_preconditioning_lead_min':w['thermal_control_contract']['maximum_preconditioning_lead_min']}
            for flag in(0,1):
                intervals=ranges([[t,t+10]for t in slots if int(t in fan[aid])==flag])
                for j,(a,b)in enumerate(intervals):
                    nid=key+':HVAC:'+aid+':'+str(flag)+':'+str(j)
                    day['needs'].append({'need_id':nid,'kind':'ac','asset_id':aid,'mode':'dual_thermostat','release_min':a,'deadline_min':b,'quantity':b-a,
                        'unit':'routine thermostat permission minutes including declared short indoor holds','served_rooms':[d['room_id']],'requester':sorted(mid for mid,seq in {**day['activity']['member_calendars'],**day['shared']['member_calendars']}.items()if any(item['location']=='home'and item['room_id']==d['room_id']and max(base+item['start_min'],a)<min(base+item['end_min'],b)for item in seq)),
                        'reference_heating_setpoint_C':heat,'reference_cooling_setpoint_C':cool,'reference_setpoint_C':cool,
                        'source_or_design_rule':'routine dual thermostat includes bounded same-person indoor excursion hold;actual occupancy remains separate;fan minimum uses occupied minutes'})
                    day['controls'].append({'kind':'ac_setpoint','asset_id':aid,'need_id':nid,'mode':'dual_thermostat','start_min':a,'end_min':b,
                        'value_C':cool,'heating_setpoint_C':heat,'cooling_setpoint_C':cool,'fan_operating_mode':flag,'heating_and_cooling_deadband_C':cool-heat})
