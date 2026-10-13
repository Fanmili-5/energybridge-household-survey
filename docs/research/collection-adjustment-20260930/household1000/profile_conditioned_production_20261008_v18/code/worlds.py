"""Profile-conditioned reference scenarios, not an estimated population diary."""
import collections,copy,sys
from common import *
sys.path.insert(0,str(BASE/'repair_execution_20261008_v1/code'))
from employment_semantics import decode_current_work

PROTOCOL={'schema':'eb.profile_conditioned_reference_rules.v18',
 'population':'unchanged city ordinary residential source anchors; towns/rural excluded',
 'reference_scenarios_not_diary_or_job_observations':True,
 'unknown_employment_stays_unknown':True,
 'time_grid_min':10,'living_day':[480,1920],
 'variation':'SHA chosen declared experimental levels within age/activity/daytype/resource eligibility, not sampled Chinese joint-clock frequencies',
 'source_domains':{'employment':'CHFS2021 A3100a coding plus aggregate A3132b/A3131a skip review',
 'laundry_frequency':'existing CRECS2012 coarse conditional frequency prior unchanged',
 'programs':'pinned EB washer120/dryer90/dish90 minutes and powers unchanged',
 'clock_parameters':'explicit reference experimental scenarios, not NBS/CHFS individual diaries',
 'personal_tradeoffs':'unknown; no income,age,sex-to-attitude mapping'},
 'B_selection':'input-only coverage; original dates retained, no per-household5/5 gate, no EP/human outcome selection',
 'physics':'generic EB paired DX/fan/curves; capacity classes retained, manufacturer offdesign claims withdrawn',
 'human_answers':0}

USAGE_KEYS={'earliest_h','preferred_h','latest_h','arrival_h','departure_h','daily_drive_kwh'}
def hardware_and_usage(value):
    clean={};evidence={}
    for k,v in value.items():
        if k in USAGE_KEYS:evidence[k]=copy.deepcopy(v)
        elif isinstance(v,dict):
            clean[k],sub=hardware_and_usage(v)
            if sub:evidence[k]=sub
        else:clean[k]=copy.deepcopy(v)
    return clean,evidence

def merge_ranges(ranges):
    out=[]
    for a,b in sorted(ranges):
        if a>=b:continue
        if out and a<=out[-1][1]:out[-1][1]=max(out[-1][1],b)
        else:out.append([a,b])
    return out

def calendar(blocks):
    grid=[('home_activity','home')]*144
    for lo,hi,activity,location in blocks:
        for s in range(lo//10,hi//10):grid[s]=(activity,location)
    result=[];a=0
    for s in range(1,145):
        if s==144 or grid[s]!=grid[a]:
            result.append({'start_h':a/6,'end_h':s/6,'start_min':a*10,'end_min':s*10,
                           'activity':grid[a][0],'location':grid[a][1]});a=s
    return result

def activity(m,hid):
    age=m['age_years'];proxy=m['current_work_source_proxy'];r=rank(hid,m['member_id'],'v18-scenario')
    evidence=decode_current_work(proxy)
    if age<6:role='preschool_with_given_daycare';why='age-eligible given daycare reference service'
    elif age<18:role='school';why='age-eligible given schooling reference, not observed enrollment'
    elif evidence['current_work_evidence']=='has_work' and age<75:
        role='home_worker' if r%3==0 else 'commuter';why='source has-work proxy permits work; location and shift are explicit reference levels'
    elif evidence['current_work_evidence']=='has_work':
        role='short_work_reference';why='has-work proxy retained; declared short daytime reference, no full-day commute or observed retirement claim'
    elif evidence['current_work_evidence']=='no_current_work':
        role='home_activity';why='source no-current-work proxy; daily activities remain reference scenarios'
    else:role='unspecified_activity_reference';why='employment unknown preserved; home/errand scenario does not assign a profession'
    specs=[]
    for day in range(7):
        rest=day>=5;shift=(r%3)*20
        departure=None;arrival=None
        if role in ('commuter','school','preschool_with_given_daycare') and not rest:
            departure=(450+shift if role=='commuter' else 470 if role=='school' else 500)
            arrival=(1050+shift if role=='commuter' else 990 if role=='school' else 980)
            wake=departure-70;sleep=1320+shift if age>=18 else 1260 if age>=6 else 1200
        else:
            wake=(360+shift if age>=75 else 400+shift if age<18 else 420+shift)+(30 if rest else 0)
            sleep=1260+shift if age>=75 else 1220 if age<6 else 1320 if age<18 else 1340+shift
        specs.append({'weekday':day,'wake_min':wake,'sleep_min':sleep,'departure_min':departure,
                      'arrival_min':arrival,'day_type':'rest_day_reference' if rest else 'weekday_reference'})
    return role,why,evidence,specs

def build(src):
    w=copy.deepcopy(src);hid=w['household_id'];old_hash=w['world_content_sha256'];ms=w['members']
    for m in ms:
        role,why,e,specs=activity(m,hid)
        m.update(reference_activity_role=role,activity_role_assignment=why,
                 employment_evidence=e,employment_status=e['current_work_evidence'],
                 employment_proxy=m['current_work_source_proxy'],activity_scenario_is_observed=False,
                 daily_reference_specs=specs,exact_times_are_design_not_individual_diary=True)
        m['employment_aggregate_source']='SOURCE_EMPLOYMENT_AGGREGATES.json; no per-person skip or donor assignment'
    adults=[m for m in ms if m['age_years']>=18]
    ev=next((d for d in w['parameter_pack']['devices'] if 'ev' in d['types']),None)
    driver=next((m for m in ms if ev and m['member_id']==ev['operator_id']),None)
    if ev:
        # Plug handling, travelling in the vehicle and driving are distinct.
        # The retained EB-world driving service is nonresident, not a licence
        # imputed to a household member (including elderly unknown workers).
        transport={'handling_operator_id':ev['operator_id'],
                   'travelling_member_id':driver['member_id'] if driver else None,
                   'driving_service_id':hid+':given_nonresident_driver',
                   'driver_is_resident':False,'resident_driving_licence_observed':None,
                   'evidence':'retained explicitly given nonresident driving service; current member interval is a passenger/errand scenario, not observed employment or licence'}
        w['given_transport_contract']=transport
        w['given_external_services']['transport_driver']=copy.deepcopy(transport)
        ev['source_V17_transport_installation_evidence']={k:ev['installation'][k] for k in ('driver','trip_source') if k in ev['installation']}
        ev['installation']['driver']='given nonresident driving service; household plug operator/passenger is separately bound in given_transport_contract'
        ev['installation']['trip_source']='episode given vehicle service and passenger/errand calendar, not observed commuting or resident driving licence'
    if driver:
        for s in driver['daily_reference_specs'][:5]:
            if s['departure_min'] is None:
                s.update(departure_min=540,arrival_min=720,transport_purpose='given errand/transport reference; not employment')
            else:s['transport_purpose']='given transport task aligned to reference away interval'
    primary=next((m for m in adults if 18<=m['age_years']<75),adults[0] if adults else None)
    family_days=[]
    for day in range(7):
        returns=[m['daily_reference_specs'][day]['arrival_min'] or 1020 for m in ms if m['age_years']>=6]
        dinner=max(1080,max(returns,default=1020)+30)+(rank(hid,'dinner')%3)*10
        dinner=min(dinner,1170);bath={};occupied=[]
        care=next((m for m in adults if m['reference_activity_role'] in ('home_activity','unspecified_activity_reference')),primary)
        for m in sorted(ms,key=lambda m:(m['daily_reference_specs'][day]['sleep_min'],m['age_years'],m['member_id'])):
            s=m['daily_reference_specs'][day]
            earliest=(s['arrival_min'] or 990)+10 if m['age_years']<6 else dinner+50
            if m['age_years']<6 and care:
                cs=care['daily_reference_specs'][day]
                earliest=max(earliest,(cs['arrival_min'] or (1020 if care['reference_activity_role']=='home_worker' and day<5 else 990))+10)
            if m['age_years']>=75:earliest=max(1020,dinner-40)
            earliest=max(earliest,s['wake_min']+60)
            if overlap((earliest,earliest+10),(dinner,dinner+30)):earliest=dinner+30
            while any(overlap((earliest,earliest+10),x) for x in occupied):earliest+=10
            if earliest+10>s['sleep_min']:raise ValueError('BATH_BEFORE_SLEEP:'+m['member_id'])
            bath[m['member_id']]=earliest;occupied.append((earliest,earliest+10))
        for m in ms:
            s=m['daily_reference_specs'][day];s['dinner_min']=dinner;s['bath_min']=bath[m['member_id']]
            blocks=[]
            if s['departure_min'] is not None:
                dep,arr=s['departure_min'],s['arrival_min']
                task='work' if m['reference_activity_role']=='commuter' else 'school' if m['age_years']<18 else 'given_transport_and_errands'
                blocks += [(dep,dep+30,'travel','outside'),(dep+30,arr-30,task,'outside'),(arr-30,arr,'travel','outside')]
            # A given vehicle errand must not erase the remaining home work.
            if m['reference_activity_role']=='home_worker' and day<5:
                for a,b in ((510,720),(780,1020)):
                    pieces=[(a,b)] if s['departure_min'] is None else [(a,min(b,s['departure_min'])),(max(a,s['arrival_min']),b)]
                    blocks += [(x,y,'home_work','home') for x,y in pieces if x<y]
            elif m['reference_activity_role']=='short_work_reference' and day<5:
                a=540 if s['departure_min'] is None else s['arrival_min']+60
                blocks += [(a,a+120,'given_short_work_activity','home')]
            lunch_location='outside' if s['departure_min'] is not None and s['departure_min']<=720<s['arrival_min'] else 'home'
            blocks += [(s['wake_min'],s['wake_min']+30,'personal_and_breakfast','home'),(720,750,'meal_and_rest',lunch_location),
                       (dinner,dinner+30,'dinner','home'),(bath[m['member_id']],bath[m['member_id']]+10,'bathing','home')]
            if care and care['member_id']==m['member_id']:
                for child in [c for c in ms if c['age_years']<6]:
                    b=bath[child['member_id']];blocks.append((b,b+10,'given_child_bathing_assistance','home'))
            blocks += [(0,s['wake_min'],'sleep_rest','home'),(s['sleep_min'],1440,'sleep_rest','home')]
            s['blocks']=blocks
        family_days.append({'weekday':day,'dinner_min':dinner,'bath_times_min':bath,
                            'child_bathing_assistant':care['member_id'] if care and any(m['age_years']<6 for m in ms) else None,
                            'shared_resource_rule':'one sequential reference bathing resource; given exclusive reservations for shared housing'})
    for m in ms:
        m['weekly_calendar']=[{'weekday':s['weekday'],'day_type':s['day_type'],'intervals':calendar(s.pop('blocks'))} for s in m['daily_reference_specs']]
    operators=[]
    order=([primary]+[m for m in adults if m is not primary]) if primary else []
    for m in order:
        windows={str(d['weekday']):merge_ranges([[i['start_min'],i['end_min']] for i in d['intervals']
                  if i['location']=='home' and i['activity'] not in ('sleep_rest','home_work','given_short_work_activity','personal_and_breakfast','meal_and_rest','dinner','bathing','given_child_bathing_assistance')]) for d in m['weekly_calendar']}
        operators.append({'operator_id':m['member_id'],'resident':True,'weekly_windows_min':windows,
                          'evidence':'same member full reference calendar; free awake home slots, work/meal/bath/care excluded',
                          'willingness_to_handle_extra_operations':None})
    if not operators:
        op=copy.deepcopy(src['operating_context']['operators'][0])
        op['weekly_windows_min']={str(d):[[420,480],[1050,1260]] for d in range(7)}
        op['evidence']='retained given nonresident assistance; availability not an additional resident';op['willingness_to_handle_extra_operations']=None
        operators=[op]
    w['operating_context']['operators']=operators
    w['routine']['weekly_family_context']=family_days
    w['routine']['exact_activity_and_service_clocks']='conditioned reference scenarios with explicit reasons; not empirical joint diaries'
    w['routine']['stable_habit_variation_level']=rank(hid,'stable-habits')%3
    w['service_semantics']={
        'mandatory_services':{'laundry':'same batch/EB program + separate retained retrieval deadline; wearable readiness unknown without dryer',
                             'dishes':'EB cleaning program and next-use retrieval',
                             'hot_water':'30L mixed/resident at given bathing appointment',
                             'transport':'given25kWh trip; reference85% access target is distinct',
                             'cooling':'26C reference control while served-room members awake/home;27C given control bound, not comfort'},
        'usual_arrangements':{'employment_and_activity':'source work evidence separate from designed location/shift',
                             'family_meals_and_baths':'weekly_family_context; coordinated shared resource',
                             'laundry_frequency':'unchanged historical coarse prior'},
        'negotiable_conditions':{'automated_start_shift':'can be proposed within service and handling windows; subjective willingness unknown',
                                 'extra_handling':'requires actor negotiation and available operator; not presumed accepted',
                                 'control_changes':'given bounds retained as reference constraints; conflicting B stays visible'},
        'unknown_subjective_tradeoffs':{'temperature_tolerance':None,'noise_aversion':None,'price_sensitivity':None,
                                       'willingness_to_change_habit':None,'willingness_to_assist':None},
        'sources_or_reasons':'CHFS coding, preserved CRECS frequency, EB program quantities, explicitly designed role/activity scenarios; no demographic attitude scores'}
    for d in w['parameter_pack']['devices']:
        if set(d['types'])&{'washer','dryer','dishwasher'}:d['operator_id']=operators[0]['operator_id']
        if 'ac' in d['types']:
            q=d['parameters'];d['previous_OEM_anchor']=copy.deepcopy(q);cap=q['cooling_W']
            flow=.40270*cap/10000;fan=400*flow/.50054;comp=cap/4.06853019625951
            q.update(key='EB_native_DX_reference_scaled_capacity',flow_m3_h=flow*3600,
                     rated_electric_W=fan+comp,max_electric_W=fan+comp,
                     gross_rated_COP=4.06853019625951,SHR=.70108,
                     manufacturer_specific_model=False,
                     parameter_bundle='pinned EB family_simple_3day DX/fan/HPAC curves; ratio-preserving scale by retained capacity')
            d['max_electric_kw']=(fan+comp)/1000;d['model_family']='EB native paired generic single-speed reference; not Haier variable-speed model'
            d['parameter_source']='pinned EB native DX/fan/HPAC performance bundle; geometry/capacity anchor separately recorded in parameters.spatial_capacity_anchor_url'
            if 'url' in q:q['spatial_capacity_anchor_url']=q.pop('url')
        d['parameters'],usage=hardware_and_usage(d['parameters'])
        if usage:d['source_EB_usage_defaults_evidence']={'values':usage,'not_current_task_times_or_observed_habits':True}
        if 'water_heater' in d['types'] and 'inlet_C' in d['parameters']:
            w['reference_physical_boundary_defaults']={'main_inlet_C':d['parameters'].pop('inlet_C'),
                'source':'original EB fixed reference; seasonal EPW-based correlation is a separately bound sensitivity, not measured pipe water'}
    temporal_aliases=['EV_arrival_min','EV_departure_min','bath_start_min','wash_preferred_min','dish_preferred_min','tank_heat_window_min']
    w['source_V17_legacy_semantics_evidence']={'assets':copy.deepcopy(src['assets']),
        'flat_temporal_examples':{k:r for k,r in src['routine'].items() if k in temporal_aliases},'not_active_constraints':True}
    for k in temporal_aliases:w['routine'].pop(k,None)
    w['routine']['time_source']='member daily_reference_specs + weekly_family_context -> episode needs/tasks/controls/operations; legacy flat clocks are evidence only'
    w['assets']={k:{'kind':k,'present':any(k in d['types'] for d in w['parameter_pack']['devices']),
                   'asset_ids':[d['asset_id'] for d in w['parameter_pack']['devices'] if k in d['types']],
                   'parameter_source':'parameter_pack.devices; clocks and service requirements belong to the episode contract',
                   'physical_model_scope':'reference model,not observed ownership or calibrated household equipment'} for k in KINDS}
    w['parameter_pack_sha256']=digest(w['parameter_pack'])
    for a in w['assets'].values():a['physical_model_scope']='pinned reference model; not household equipment validation'
    w['source_V17_world_content_sha256']=old_hash;w['repair_rules_sha256']=digest(PROTOCOL)
    w['profile_to_world_reason_trace']={'employment':'current_work_source_proxy -> employment_evidence; unknown retained',
      'activity':'age eligibility/work proxy + declared work-location/short-work/scenario level',
      'routines':'member scenario + weekday/rest day -> wake/away/sleep; household returns -> meal; sleep/arrival/children -> coordinated bath',
      'operator_windows':'actual full calendar minus work/meals/bath/care -> handling availability',
      'services_and_B':'same frozen service quantities/deadlines -> A then B applicability, flexibility and negotiation; no subjective labels'}
    w['active_clock_authority']='episode absolute-minute ledger; no flat legacy clock in the active routine or hardware parameters'
    w['schema']='eb.profile_conditioned_world.v18';w['world_content_sha256']=digest({k:v for k,v in w.items() if k!='world_content_sha256'})
    return w

def main():
    school_guard();sel=read(SOURCE/'SELECTION1000.json');rows=[];roles=collections.Counter();clocks=set()
    for r in sel['records']:
        src=read(SOURCE/r['world_path']);w=build(src);path=OUT/'worlds'/f'{w["household_id"]}.json';save(path,w)
        assert all(w[k]==src[k] for k in ('N','G','H6','H7','layout','random10_date_selection','ego_relationships'))
        for m in w['members']:roles[m['reference_activity_role']]+=1;clocks.add(digest(m['weekly_calendar']))
        rows.append({**{k:copy.deepcopy(v) for k,v in r.items() if k not in ('rounds','world_sha256','parameter_pack_sha256')},
                     'world_path':str(path.relative_to(OUT)),'world_sha256':sha(path),'parameter_pack_sha256':w['parameter_pack_sha256'],
                     'source_V17_world_sha256':sha(SOURCE/r['world_path'])})
    save(OUT/'WORLD_BINDINGS1000.json',{'households':len(rows),'records':rows})
    save(OUT/'PROTOCOL.json',PROTOCOL)
    save(OUT/'WORLD_BUILD_REVIEW.json',{'households':len(rows),'members':sum(roles.values()),'activity_scenarios':dict(roles),
        'unique_weekly_calendars':len(clocks),'source_rosters_housing_dates_preserved':True,
        'unknown_employment_promoted_to_job':0,'scientific_joint_diary_calibration':False,'human_answers':0})
    print(read(OUT/'WORLD_BUILD_REVIEW.json'),flush=True)
if __name__=='__main__':main()
