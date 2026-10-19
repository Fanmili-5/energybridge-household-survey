"""Persistent daily thermostat routines on the frozen original50;other requests exact."""
import collections
import copy
import statistics
import shutil
from core import *

PARENT=BASE/'unified_physics50_v76_B60_macpreview_20261018'
PREVIOUS=BASE/'unified_physics50_v83_AC_habits_20261018'
STEP=10

def is_sleep(activity,rules):
    """Calendar producers use two names for the same overnight sleep state."""
    return activity in rules['sleep_recognition']['sleep_activity_aliases']

def slots(rows,lo=None,hi=None):
    return {t for x in rows for t in range(max(x['start_min'],lo)if lo is not None else x['start_min'],min(x['end_min'],hi)if hi is not None else x['end_min'],STEP)}

def ranges(minutes):
    out=[]
    for t in sorted(minutes):
        if out and out[-1][1]==t:out[-1][1]=t+STEP
        else:out.append([t,t+STEP])
    return out

def bridge(minutes,eligible,limit):
    out=set(minutes)
    for left,right in zip(ranges(minutes),ranges(minutes)[1:]):
        a,b=left[1],right[0]
        if b-a<=limit and all(t in eligible for t in range(a,b,STEP)):out.update(range(a,b,STEP))
    return out

def control_rows(aid,lookup,anchor):
    out=[]
    for t,state in sorted(lookup.items()):
        day=t//1440;date=str(dt.date.fromisoformat(anchor)+dt.timedelta(days=day));nid=f'{date}:AC84:{aid}'
        q={**state,'asset_id':aid,'kind':'ac_setpoint','need_id':nid,'start_min':t,'end_min':t+STEP}
        last=out[-1]if out else None
        same=lambda x:{k:v for k,v in x.items()if k not in('need_id','start_min','end_min')}
        if last and last['end_min']==t and (last['start_min']//1440)==day and same(last)==same(q):last['end_min']=t+STEP
        else:out.append(q)
    return out

def household(pack,rules):
    old=copy.deepcopy(pack);anchor=pack['anchor'];acs=[d for d in pack['world']['parameter_pack']['devices']if'ac'in d['types']]
    # Actual calendar presence remains separate: operator excursions do not toggle a thermostat.
    room_home=collections.defaultdict(set);room_awake=collections.defaultdict(set)
    member_home=collections.defaultdict(set);member_awake=collections.defaultdict(set);room_users=collections.defaultdict(set)
    all_minutes=set()
    for date,day in pack['days'].items():
        base=offset(date,anchor)
        for mid,cal in {**day['calendars'],**day['shared']['member_calendars']}.items():
            for item in cal:
                if item['location']!='home':continue
                ts=set(range(base+item['start_min'],base+item['end_min'],STEP));rid=item['room_id'];all_minutes.update(ts)
                room_home[rid].update(ts);room_users[rid].add(mid);member_home[mid].update(ts)
                if not is_sleep(item['activity'],rules):room_awake[rid].update(ts);member_awake[mid].update(ts)
    # Family members and co-residents with an actual right to use this room only.
    target={m['member_id']for m in pack['world']['members']};living=pack['world']['activity_contract']['room_map']['living']
    lo=0;hi=offset(pack['end_exclusive'],anchor);timeline=set(range(lo,hi,STEP));new=[];habits=[]
    annual=[x for day in old['days'].values()for x in day['controls']]
    for d in acs:
        aid=d['asset_id'];rid=d['room_id'];users=room_users[rid]or target
        # For a common living space include the household's home calendar even while it cooks/bathes.
        if rid==living:users=users|target
        home=set().union(*(member_home[mid]for mid in users));awake=set().union(*(member_awake[mid]for mid in users))
        oldrows=[x for x in annual if x['asset_id']==aid and x['kind']=='ac_setpoint'];oldslots=slots(oldrows)
        if rid=='combined_bed_living':
            mode='home_continuous';habit=bridge(home,timeline,rules['short_scheduled_whole_home_absence_hold_min'])
        elif rid==living:
            mode='awake_home_continuous';habit=bridge(awake,timeline,rules['short_scheduled_whole_home_absence_hold_min'])
        else:
            mode='sleep_and_settled_sessions';habit=set(room_home[rid]-room_awake[rid])
            # A room-use session is planned across a home episode,not ended by a kitchen/bath trip.
            settled_awake=bridge(awake,timeline,rules['short_scheduled_whole_home_absence_hold_min'])
            for a,b in ranges(settled_awake):
                use=sorted(t for t in room_awake[rid]if a<=t<b)
                if use:habit.update(range(use[0],use[-1]+STEP,STEP))
            home_hold=bridge(home,timeline,rules['short_scheduled_whole_home_absence_hold_min'])
            habit=bridge(habit|oldslots,home_hold,rules['bedroom_domestic_session_gap_hold_min'])
        permission=(habit|oldslots)&timeline
        base={k:oldrows[0][k]for k in('value_C','mode','heating_setpoint_C','cooling_setpoint_C')};base['fan_operating_mode']=0
        lookup={t:copy.deepcopy(base)for t in permission}
        for x in oldrows:
            state={k:x[k]for k in('value_C','mode','heating_setpoint_C','cooling_setpoint_C','fan_operating_mode')}
            for t in range(x['start_min'],x['end_min'],STEP):lookup[t]=copy.deepcopy(state)
        new+=control_rows(aid,lookup,anchor)
        habits.append({'asset_id':aid,'room_id':rid,'mode':mode,'calendar_users':sorted(users),'given_scenario_not_observed_habit':True,'old_permission_minutes':len(oldslots)*STEP,'new_permission_minutes':len(permission)*STEP})
    byday=collections.defaultdict(list)
    for x in new:byday[str(dt.date.fromisoformat(anchor)+dt.timedelta(days=x['start_min']//1440))].append(x)
    for date,day in pack['days'].items():day['controls']=[x for x in day['controls']if x['kind']!='ac_setpoint']+byday[date]
    w=pack['world'];w['parent_A46_world_content_sha256']=w['world_content_sha256'];w['AC_continuous_habits']={'schema':'eb.AC_habits50.v84','rules_sha256':sha(ROOT/'AC_HABIT_RULES.json'),'rooms':habits,'not_inferred_acceptance_or_empirical_population_distribution':True}
    w['thermal_control_contract']['parent_short_indoor_excursion_hold_min']=w['thermal_control_contract'].pop('short_indoor_excursion_hold_min',None)
    w['thermal_control_contract']['permission_authority']='AC_continuous_habits;momentary occupancy is exposure,not switch command'
    w['world_content_sha256']=digest({k:v for k,v in w.items()if k!='world_content_sha256'})
    pack['parent_source_A_world_sha256']=pack['source_A_world_sha256'];pack['source_A_world_sha256']=w['world_content_sha256']
    pack['AC_revision']={'parent_pack_sha256':digest(old),'rules_sha256':sha(ROOT/'AC_HABIT_RULES.json'),'all_other_requests_preserved':True}
    assert pack['tasks']==old['tasks']and pack['operations']==old['operations']and pack['journeys']==old['journeys']and pack['EV_battery_energy_events']==old['EV_battery_energy_events']
    for date in old['days']:
        assert {k:v for k,v in pack['days'][date].items()if k!='controls'}=={k:v for k,v in old['days'][date].items()if k!='controls'}
        assert [c for c in pack['days'][date]['controls']if c['kind']!='ac_setpoint']==[c for c in old['days'][date]['controls']if c['kind']!='ac_setpoint']
    return pack,habits

def pair(old,pack):
    p=copy.deepcopy(old);anchor=offset(p['date'],pack['anchor']);acs={d['asset_id']for d in pack['world']['parameter_pack']['devices']if'ac'in d['types']}
    oldac=[x for s in ['A','B']for x in p[s]['controls']if x['kind']=='ac_setpoint']
    lo=min(x['start_min']for x in oldac)//1440*1440;hi=((max(x['end_min']for x in oldac)+1439)//1440)*1440
    annual=[x for day in pack['days'].values()for x in day['controls']if x['kind']=='ac_setpoint']
    newA=[];newB=[]
    for aid in sorted(acs):
        original={s:{t:{k:x.get(k)for k in('value_C','mode','heating_setpoint_C','cooling_setpoint_C','fan_operating_mode')}for x in old[s]['controls']if x['asset_id']==aid and x['kind']=='ac_setpoint'for t in range(x['start_min'],x['end_min'],STEP)}for s in ['A','B']}
        new={t-anchor:{k:x.get(k)for k in('value_C','mode','heating_setpoint_C','cooling_setpoint_C','fan_operating_mode')}for x in annual if x['asset_id']==aid for t in range(max(x['start_min'],anchor+lo),min(x['end_min'],anchor+hi),STEP)}
        b=copy.deepcopy(new)
        for t in original['A'].keys()|original['B'].keys():
            av,bv=original['A'].get(t),original['B'].get(t)
            if av==bv:continue
            assert t>=p['decision_min']
            if bv is None:b.pop(t,None)
            else:
                assert t in b,'Original thermal request lost from new habit coverage'
                b[t]=copy.deepcopy(bv)
        for s,lookup,out in [('A',new,newA),('B',b,newB)]:
            rows=control_rows(aid,{t+anchor:v for t,v in lookup.items()},pack['anchor'])
            out.extend({**x,'start_min':x['start_min']-anchor,'end_min':x['end_min']-anchor}for x in rows)
    for side,newrows in [('A',newA),('B',newB)]:
        p[side]['controls']=[x for x in p[side]['controls']if x['kind']!='ac_setpoint']+newrows
        p[side]['controls'].sort(key=lambda x:(x['start_min'],x['asset_id'],x['kind']))
        assert p[side]['tasks']==old[side]['tasks']and p[side]['operations']==old[side]['operations']
        assert sorted((x for x in p[side]['controls']if x['kind']!='ac_setpoint'),key=canonical)==sorted((x for x in old[side]['controls']if x['kind']!='ac_setpoint'),key=canonical)
    needs_by_id={}
    for x in newA:
        n=needs_by_id.setdefault(x['need_id'],{'need_id':x['need_id'],'kind':'ac','asset_id':x['asset_id'],'release_min':x['start_min'],'deadline_min':x['end_min'],'quantity':0,'permission_intervals_min':[],'unit':'given persistent thermostat minutes;not compressor runtime','reference_heating_setpoint_C':x['heating_setpoint_C'],'reference_cooling_setpoint_C':x['cooling_setpoint_C'],'source_or_design_rule':'AC_habits50.v84;actual room occupancy separate'})
        n['release_min']=min(n['release_min'],x['start_min']);n['deadline_min']=max(n['deadline_min'],x['end_min']);n['quantity']+=x['end_min']-x['start_min'];n['permission_intervals_min'].append([x['start_min'],x['end_min']])
    needs=list(needs_by_id.values())
    for key in ['needs_A','needs_B']:p[key]=[n for n in p[key]if n['kind']!='ac']+copy.deepcopy(needs)
    p['schedule_hashes']={s:digest({k:p[s][k]for k in('tasks','operations','controls')})for s in ['A','B']}
    p['parent_A46_B60_source_pair_sha256']=old['source_pair_sha256']
    p['AC_revision']={'version':'A46-AC84/B60-AC84','rules_sha256':sha(ROOT/'AC_HABIT_RULES.json'),'only_AC_controls_and_corresponding_needs_changed':True,'VPP_scenario_and_non_AC_requests_fixed':True,'parent_B60_A_reference_is_not_new_A_forecast':True}
    p['opportunity_generation']['parent_A46_operating_reference']=p['opportunity_generation'].pop('A_operating_reference')
    p['opportunity_generation']['current_mode']='replay original B60 request on regenerated persistent AC baseline;actual effects rerun'
    p['opportunity_generation']['current_A_operating_reference_status']='new A simulation pending;parent forecast is provenance only'
    p.pop('source_pair_sha256',None);p.pop('source_pair_path',None)
    return p

def main():
    # Preserve the unaffected45 inputs byte for byte. Rebuild affected routines
    # from the same A46/B60 source, never from already-expanded permissions.
    m=read(PREVIOUS/'INPUT_MANIFEST.json');rules=read(ROOT/'AC_HABIT_RULES.json');records=[];profiles=[];changed=[]
    # These immutable native definitions and weather files are compiler inputs.
    (ROOT/'inputs').mkdir(parents=True,exist_ok=True)
    for ref in (PREVIOUS/'inputs').iterdir():
        if ref.is_file():shutil.copy2(ref,ROOT/'inputs'/ref.name)
    shutil.copytree(PREVIOUS/'inputs/weather',ROOT/'inputs/weather',dirs_exist_ok=True)
    original={r['household_id']:r for r in read(PARENT/'INPUT_MANIFEST.json')['records']}
    for row in m['records']:
        assert sha(PREVIOUS/row['path'])==row['sha256']
        previous=read(PREVIOUS/row['path'])
        affected=any(is_sleep(x['activity'],rules)and x['activity']!='sleep_rest'
                     for day in previous['days'].values()
                     for cal in day['shared']['member_calendars'].values()for x in cal)
        if not affected:
            for rel in [row['path']]+[c['path']for c in row['cases']]:
                target=ROOT/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(PREVIOUS/rel,target)
            for cp in row['cases']:
                source=PREVIOUS/'generated_pairs'/row['household_id']/(cp['date']+'.json.gz')
                target=ROOT/source.relative_to(PREVIOUS);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
            records.append(copy.deepcopy(row));profiles+=previous['world']['AC_continuous_habits']['rooms'];continue
        changed.append(row['household_id'])
        pack,habits=household(read(PARENT/row['path']),rules)
        path=ROOT/row['path'];save(path,pack);nr={**row,'sha256':sha(path),'cases':[]};profiles+=habits
        original_cases={c['date']:c for c in original[row['household_id']]['cases']}
        for cp in row['cases']:
            oc=original_cases[cp['date']]
            assert sha(PARENT/oc['path'])==oc['sha256'];old=read(PARENT/oc['path']);p=pair(old,pack)
            source=ROOT/'generated_pairs'/row['household_id']/(cp['date']+'.json.gz');save(source,p)
            p['source_pair_sha256']=sha(source);p['source_pair_path']=str(source.relative_to(REPO));target=ROOT/cp['path'];save(target,p)
            nr['cases'].append({**cp,'sha256':sha(target),'source_pair_sha256':sha(source),'schedule_hashes':p['schedule_hashes']})
        records.append(nr);print(canonical({'generated_households':len(records),'cases':sum(len(r['cases'])for r in records)}),flush=True)
    expected={'ordinary-v6-0334','ordinary-v6-0398','ordinary-v6-0426','ordinary-v6-0828','ordinary-v6-0858'}
    assert set(changed)==expected
    bindings={'schema':'eb.AC_habits50.generation_bindings.v84','parent_input_manifest_sha256':sha(PREVIOUS/'INPUT_MANIFEST.json'),'original_A46_B60_input_manifest_sha256':sha(PARENT/'INPUT_MANIFEST.json'),'rules_sha256':sha(ROOT/'AC_HABIT_RULES.json'),'records':records,'same_subset50':m['subset50_ids'],'source_master_1000_untouched':True,'schedules_modified':['AC only'],'changed_households':changed,'changed_cases':50,'unchanged_households_byte_identical':45,'unchanged_cases_byte_identical':450,'answers_created':0,'before_simulation':True}
    save(ROOT/'GENERATION_BINDINGS500.json',bindings)
    manifest={**m,'schema':'eb.AC_habits50.inputs.v84','records':records,'A_stage':'A46-AC84','B_stage':'B60-AC84','schedules_modified':True,'frozen_A_physical_inputs_reused':False,'modified_families':['ac'],'parent_A_stage':'A46-AC83','parent_B_stage':'B60-AC83','new_B_bindings_sha256':sha(ROOT/'GENERATION_BINDINGS500.json'),'B_generation_seal_sha256':sha(ROOT/'GENERATION_BINDINGS500.json'),'parent_B60_bindings_sha256':m['parent_B60_bindings_sha256'],'parent_input_manifest_sha256':sha(PREVIOUS/'INPUT_MANIFEST.json'),'preview_only':True}
    save(ROOT/'INPUT_MANIFEST.json',manifest);save(ROOT/'AC_HABIT_PROFILES.json',profiles)
    save(ROOT/'GENERATION_SEAL.json',{'bindings_sha256':sha(ROOT/'GENERATION_BINDINGS500.json'),'input_manifest_sha256':sha(ROOT/'INPUT_MANIFEST.json'),'rules_sha256':sha(ROOT/'AC_HABIT_RULES.json'),'code_sha256':sha(Path(__file__)),'frozen_before_physical_outputs':True,'online_deployed':False})

if __name__=='__main__':main()
