"""Freeze calendar selection before any physics outcome is available."""
import collections, datetime as dt, random
from common import *
SOURCE_STAGE=BASE/'task_world_assembly_20261007'
FAMILIES=[['washer'],['ac'],['water_heater'],['ev'],['dishwasher'],['dryer'],['washer','dryer'],['ac','water_heater'],['ev','washer'],[]]

def selection(hid):
    seed=hashlib.sha256((hid+'/random10-calendar-v1/2025').encode()).hexdigest()
    rng=random.Random(int(seed,16));extra=rng.sample(range(4),2);dates=[];quarters=[]
    for q in range(4):
        begin=dt.date(2025,q*3+1,1);end=dt.date(2026,1,1) if q==3 else dt.date(2025,(q+1)*3+1,1)
        pool=[begin+dt.timedelta(days=i) for i in range((end-begin).days)];n=3 if q in extra else 2
        picked=rng.sample(pool,n);quarters.append({'quarter':q+1,'frame_days':len(pool),'sample_days':n})
        dates.extend({'date':d.isoformat(),'quarter':q+1,'conditional_inclusion_probability':n/len(pool),
                      'conditional_inverse_probability_weight':len(pool)/n} for d in picked)
    dates.sort(key=lambda d:d['date'])
    return {'seed_sha256':seed,'algorithm':'Python Random MT19937;quarter-stratified without replacement;two random quarters receive 3 days,others 2',
            'reference_year':2025,'quarters':quarters,'dates':dates,'outcome_independent':True,
            'all_dates_frozen_before_EP':True,'annual_energy_extrapolation_permitted':False}

def main():
    guard();old=read(SOURCE_STAGE/'WORLD_BINDINGS1000.json');profiles=read(V7/'HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json')['profiles'];profiles={p['slot_id']:p for p in profiles}
    records=[];quarter_counts=collections.Counter();month_counts=collections.Counter();presence=collections.Counter()
    for binding in old['records']:
        hid=binding['household_id'];w=read(SOURCE_STAGE/binding['world_path']);old_sha=sha(SOURCE_STAGE/binding['world_path'])
        w.pop('world_content_sha256',None);w['schema']='eb.six_device_random10_world.v1'
        w['random10_date_selection']=selection(hid)
        rng=random.Random(int(hashlib.sha256((hid+'/calendar-conditioned-task-family-v2').encode()).hexdigest(),16));control=rng.randrange(10);families=[]
        for i,selected in enumerate(w['random10_date_selection']['dates']):
            date=dt.date.fromisoformat(selected['date']);jobs=w['weekly_tasks'][date.weekday()]['jobs']
            available={k for k,a in w['assets'].items() if a['present'] and ((k=='ac' and 5<=date.month<=9) or
                        any(j['kind']==k and (k!='ev' or j['daily_drive_kWh']>0) for j in jobs))}
            candidates=[f for f in FAMILIES if f and set(f)<=available]
            families.append(rng.choice(candidates) if candidates and i!=control else [])
        w['random10_task_families']=families
        w['task_selection_design']={'rule':'random choice among installed calendar-eligible EB task families;one prespecified identity control per household;no-op retained when no eligible task',
            'identity_control_round':control+1,'energy_outputs_consulted':False,'dates_resampled_for_task_availability':False}
        w['source_world_file_sha256']=old_sha;w['source_world_stage']=SOURCE_STAGE.name
        w['protocol_sha256']=sha(OUT/'PROTOCOL.json')
        w['reference_initial_states']['EV_SOC']=.85 if w['assets']['ev']['present'] else None
        w['reference_initial_states']['thermal_history']='EnergyPlus warmup at each episode origin;one common prior day;identical nominal inputs and initial reference state for A/B;not measured'
        w['reference_initial_states']['episode_reset_scope']='independent sampled episodes;no assumed observed state or carry between different sampled dates'
        w.pop('reference_calendar_start',None);w.pop('reference_calendar_end',None)
        w['date_sampling_frame']={'begin':'2025-01-01','end':'2025-12-31','EP_annual_simulation':False}
        w['background_thermal_boundary']={'heating_air_setpoint_C':18.,'model':'EnergyPlus heating-only ideal supply;fixed external reference service',
            'scope':'noncontrolled building thermal boundary;separate thermal energy;not a seventh EB device or observed heating technology',
            'source':'Ding and Zhou 2020 Table 1 heating reference18C;availability-all-days is experimental design'}
        income=profiles[hid]['family'].get('income_reference_bin')
        w['economic_reference']={'source_income_bin':income,'source_scope':profiles[hid]['family'].get('income_scope'),
            'calendar_year':profiles[hid]['family'].get('income_calendar_reference_year'),
            'used_for':'ordinal source context only;not a 2025 observed income,price sensitivity,or inferred answer'}
        w['reference_shared_meter_allocation']={'rule':'equal share among declared using_household_ids for room lights/background;controlled devices on target household meter',
            'evidence_kind':'explicit reference billing design;not a housing-area statistic or observed shared bill'}
        w['background_scope']['shared_meter']='separate common-room reference energy;equal-user allocation explicitly designed'
        for s in w['random10_date_selection']['dates']:quarter_counts[s['quarter']]+=1;month_counts[s['date'][5:7]]+=1
        for k,a in w['assets'].items():presence[k]+=int(a['present'])
        w['world_content_sha256']=digest(w);path=OUT/'worlds'/f'{hid}.json';save(path,w)
        records.append({**binding,'world_path':str(path.relative_to(OUT)),'world_sha256':sha(path),'world_content_sha256':w['world_content_sha256'],
                        'random10_selection_sha256':digest(w['random10_date_selection'])})
    save(OUT/'WORLD_BINDINGS1000.json',{'schema':'eb.random10_world_bindings.v1','records':records})
    save(OUT/'DATE_SELECTION1000.json',{'households':len(records),'target_days':10*len(records),'quarter_counts':dict(quarter_counts),'month_counts':dict(month_counts),
        'device_presence_reference_design_not_population_prevalence':dict(presence),'sampling_protocol_sha256':sha(OUT/'PROTOCOL.json'),
        'selection_frozen_before_EP':True,'annual_EP_runs_requested':0,'support_days_not_extra_questionnaire_cases':True})
    print({'worlds_written':len(records),'random_target_days':len(records)*10,'annual_EP_requested':0},flush=True)
if __name__=='__main__':main()
