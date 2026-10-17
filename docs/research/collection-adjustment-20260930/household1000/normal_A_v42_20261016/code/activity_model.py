"""One dated activity/room/care contract for all consumers; explicit design levels.

No diary distribution or missing occupation is identified by these scenarios.
WHO ranges are normative plausibility bounds, not population probabilities.
"""
import copy
import datetime as dt
from functools import lru_cache
from common import digest, rank, overlap

HOLIDAY_RANGES = [('2025-01-01','2025-01-01'),('2025-01-28','2025-02-04'),
    ('2025-04-04','2025-04-06'),('2025-05-01','2025-05-05'),
    ('2025-05-31','2025-06-02'),('2025-10-01','2025-10-08'),
    ('2026-01-01','2026-01-03')]
MAKEUP_WORK = {'2025-01-26','2025-02-08','2025-04-27','2025-09-28','2025-10-11'}
UNAVAILABLE = {'sleep_rest','day_nap','personal_and_breakfast','meal_and_rest',
    'dinner','bathing','home_work','given_short_work_activity','home_commitment',
    'household_chores','childcare_active','childcare_supervision','child_bathing_assistance',
    'school_home_study'}
UNAVAILABLE.add('given_protected_service_check')

def ranges(xs):
    out=[]
    for a,b in sorted(xs):
        if a>=b:continue
        if out and a<=out[-1][1]:out[-1][1]=max(b,out[-1][1])
        else:out.append([a,b])
    return out

def day_type(date):
    iso=date.isoformat()
    if any(a<=iso<=b for a,b in HOLIDAY_RANGES):return 'national_holiday'
    if iso in MAKEUP_WORK:return 'makeup_workday'
    return 'weekday' if date.weekday()<5 else 'weekend'

def school_day(date,age):
    iso=date.isoformat(); obligatory=age<15
    winter=('2025-01-12' if obligatory else '2025-01-19','2025-02-16')
    summer=('2025-07-07' if obligatory else '2025-07-14','2025-08-31')
    return day_type(date) in ('weekday','makeup_workday') and not any(a<=iso<=b for a,b in (winter,summer))

def room_map(w):
    rooms=[r for r in w['layout']['rooms'] if w['household_id'] in r['using_household_ids']]
    def find(kind,fallback):
        return next((r['room_id'] for r in rooms if r['census_room_class']==kind),fallback)
    private=w['members'][0]['reference_home_room_id']
    living=find('hall',private)
    kitchen=find('kitchen',living)
    bath=next((r['room_id'] for r in rooms if r['room_id']=='washroom'),
              next((r['room_id'] for r in rooms if r['census_room_class']=='non_H7_service'),living))
    # Meal provision is already an exogenous service. Do not put every family
    # member into a small equipment kitchen just because cooking occurs there.
    # Dining/living co-use is a declared layout scenario, not a survey estimate.
    return {'living':living,'meal':living,'kitchen':kitchen,'bath':bath,
            'corridor':find('corridor',living)}

def scenario(m,hid):
    age=m['age_years'];status=m['employment_status'];r=rank(hid,m['member_id'],'v19-activity')
    if age==0:return 'infant_home_care'
    if age<3:return 'toddler_given_daycare' if r%3==0 else 'toddler_home_care'
    if age<6:return 'preschool_home_care' if r%4==0 else 'preschool_given_daycare'
    if age<18:return 'school_reference'
    if status=='has_work':
        if age>=75:return 'given_short_work_reference'
        return ('commuter_reference','home_work_reference','flexible_work_reference')[r%3]
    if status=='no_current_work':return ('home_commitments_reference','community_activity_reference','mixed_activity_reference')[r%3]
    return ('unknown_outside_commitments','unknown_home_commitments','unknown_mixed_activity')[r%3]

def configure(w):
    """Configure once; no date/outcome-dependent selection of household identities."""
    hid=w['household_id'];ms=w['members'];adults=[m for m in ms if m['age_years']>=18]
    for m in ms:
        m['reference_activity_role']=scenario(m,hid)
        m['activity_scenario_is_observed']=False
        m['exact_times_are_design_not_individual_diary']=True
        m['activity_scenario_evidence']='R02 declared eligible activity levels; source work status remains separate; no occupation imputation'
        m['activity_scenario_level']=rank(hid,m['member_id'],'activity-dose')%3
        m['infant_months_reference']=[2,6,10][rank(hid,m['member_id'],'infant-stage')%3] if m['age_years']==0 else None
        m['infant_months_is_given_not_observed']=m['age_years']==0
        m['preschool_care']='given resident/external home supervision' if m['reference_activity_role'].endswith('home_care') else 'given daycare with dated opening/transport contract' if 'daycare' in m['reference_activity_role'] else 'not_applicable'
    home_children=[m for m in ms if m['reference_activity_role'].endswith('home_care')]
    caregivers=[m for m in adults if m['employment_status']!='has_work' and m['age_years']<75]
    caregiver=min(caregivers,key=lambda m:rank(hid,m['member_id'],'caregiver')) if home_children and caregivers else None
    if caregiver:
        caregiver['reference_activity_role']='given_home_care_reference'
        caregiver['activity_scenario_evidence']='R03 given care responsibility conditioned on household children, not observed job/sex/attitude'
    care_id=caregiver['member_id'] if caregiver else hid+':given_home_caregiver' if home_children else None
    w['care_contract']={'home_care_child_ids':[m['member_id'] for m in home_children],
        'caregiver_id':care_id,'caregiver_is_resident':caregiver is not None,
        'supervision_is_given':True,'additional_care_willingness':None,
        'external_care_cost':None,'source':'R03 explicit shared supervision and care appointments; not an observed childcare service',
        'daycare_transport':'given centre transport when the centre is open; not additional residents'}
    ev=next((d for d in w['parameter_pack']['devices'] if 'ev' in d['types']),None)
    if ev:
        eligible=[m for m in adults if 18<=m['age_years']<75]
        moving=[m for m in eligible if m['reference_activity_role'] in ('commuter_reference','flexible_work_reference')]
        driver=min(moving or eligible,key=lambda m:rank(hid,m['member_id'],'given-driver')) if eligible else None
        # Resident driving authorisation is an explicit fictional-world fact, never a source licence.
        shared=bool(driver and rank(hid,'transport-mode')%3==0 and len(adults)>1)
        mode='given_family_shared_vehicle' if shared else 'given_resident_driver' if driver else 'given_external_driving_service'
        handler=driver if driver else adults[0] if adults else None
        if handler:ev['operator_id']=handler['member_id']
        else:ev['operator_id']=w['operating_context']['operators'][0]['operator_id']
        w['given_transport_contract']={'mode':mode,'handling_operator_id':ev['operator_id'],
            'driver_id':driver['member_id'] if driver else hid+':given_external_driver',
            'driver_is_resident':driver is not None,'travelling_member_id':handler['member_id'] if handler else ms[0]['member_id'],
            'resident_driving_licence_observed':None,
            'reference_driving_authorization':'explicit given scenario only' if driver else 'given external service authorisation',
            'external_service_windows_min':[[540,1020]] if not driver else [],
            'external_service_coverage':'pre-authorised A journeys within saved windows; extra requests require negotiation' if not driver else 'not_applicable',
            'external_driver_cost':None,'source':'R04 declared transport resource, not inferred ownership/licence or national use pattern',
            'trip_energy_levels_kWh':[2.5,10.0,25.0],
            'trip_energy_level_source':'declared doses of EB25kWh reference traction task; hardware capacity/power/efficiency unchanged'}
        ev['installation']['driver']=mode+'; see given_transport_contract'
        ev['installation']['trip_source']='dated journey contract, common to A/B; not a commute imputed to unknown employment'
        w['given_external_services']['transport_driver']=copy.deepcopy(w['given_transport_contract'])
    w['activity_contract']={'schema':'eb.dated_activity_rules.v19','evidence_registry':'RULE_EVIDENCE.json',
        'exact_clocks':'given experimental levels within source eligibility and normative bounds, not Chinese joint diaries',
        'school_calendar':'Beijing2024to2025 official prototype; given transferred reference for other provinces, not their observed school calendar',
        'daycare_calendar':'given opening on national working days; local closures unobserved',
        'national_holiday_calendar':'official2025 holidays and makeup days; Jan2026 carry dates separately sourced',
        'unknown_work_is_not_inferred':'unknown role activities contain no work label',
        'room_map':room_map(w),'age_clock_norms':'WHO2019 under5; older ages are explicit reference levels',
        'cooling_reference_modes':{'awake_setpoint_C':26.0,'sleep_setpoint_C':26.0,
            'sleep_control_service_given':True,'subjective_comfort_known':False},
        'bathing_assistance_contract':'given10min capability and exact common baseline appointments; no inferred capability or willingness; resident availability checked before booking',
        'metabolic_power_scope':'retained EB person heat gain reference, not age/body calibrated physiology',
        'given_scenario_mixture_is_not_population_probability':True}
    return w


def configure_habits(w):
    hid=w['household_id'];style=rank(hid,'given-household-rhythm')%4
    weekday=[1050,1080,1140,1170][style]
    rest=weekday+(30 if rank(hid,'given-rest-meal-routine')%2 else 0)
    w['living_habits']={'schema':'eb.joint_living_habits.v42','given_not_observed':True,
      'dinner_min':{'weekday':weekday,'rest':rest},'arrival_to_dinner_min':30,
      'bath_style':['before_dinner','after_dinner','later_evening'][rank(hid,'given-evening-sequence')%3],
      'after_school_weekdays':[[0,2],[1,3],[2,4]][rank(hid,'given-school-activity-days')%3],
      'after_school_minutes':60,'late_obligation_weekdays':[[1,3],[0,2],[2,4]][rank(hid,'given-weekly-obligation-days')%3],
      'weekly_obligation_meaning':'given late work/activity session at11:00 on fixed weekdays for already-declared variable activity roles;no occupation imputation',
      'choice_basis':'reproducible household-level experimental habit factors,not population probabilities or age/sex preference predictions',
      'daily_change_basis':'actual holiday,school term,weekly obligations,dated return and existing resource constraints;no random minute displacement',
      'B_VPP_price_or_answers_used':False}
    w['activity_contract'].update(schema='eb.joint_dated_activity.v42',upstream_calendars_rebuilt=True,old_annual_calendars_reused=False)
    return w


def compress(grid):
    out=[];a=0
    for i in range(1,145):
        if i==144 or grid[i]!=grid[a]:
            activity,room,location=grid[a]
            out.append({'start_min':a*10,'end_min':i*10,'start_h':a/6,'end_h':i/6,
                'activity':activity,'room_id':room,'location':location});a=i
    return out

def stamp(grid,a,b,activity,room,location='home'):
    for s in range(max(0,a)//10,min(1440,b)//10):
        if location=='home'and grid[s][2]=='outside':
            # These contexts are given optional at-home windows, not mandatory services.
            if activity in ('home_commitment','household_chores','school_home_study'):continue
            raise ValueError('home-only activity conflicts with declared outside episode: '+activity)
        grid[s]=(activity,room,location)

def sleep_spec(m,date,working):
    age=m['age_years'];shift=(rank(m['member_id'],'wake-shift')%3-1)*20
    if age==0:
        wake=420+shift;night=700;nap=200 if m['infant_months_reference']<4 else 120
    elif age<3:wake=420+shift;night=680;nap=90
    elif age<6:wake=420+shift;night=660;nap=60
    elif age<13:wake=400+shift;night=600;nap=0
    elif age<18:wake=400+shift;night=540;nap=0
    else:
        wake=(390 if m['reference_activity_role']=='commuter_reference' and working else 420)+shift
        night=480+(20 if age>=75 else 0);nap=0
    if not working:wake+=30
    bedtime=1440+wake-night
    return wake,bedtime,nap

def build_day(w,date):
    hid=w['household_id'];ms=w['members'];rooms=w['activity_contract']['room_map'];dtype=day_type(date)
    working=dtype in ('weekday','makeup_workday');grids={};specs={};departures={};arrivals={};travel_ledger={};meal_appointments={}
    for m in ms:
        mid=m['member_id'];age=m['age_years'];role=m['reference_activity_role'];sleep_room=m['reference_home_room_id']
        wake,bedtime,nap=sleep_spec(m,date,working)
        if mid==w['care_contract']['caregiver_id'] and w['care_contract']['home_care_child_ids']:
            children=[c for c in ms if c['member_id'] in w['care_contract']['home_care_child_ids']]
            early=min(sleep_spec(c,date,working)[0] for c in children)
            night=1440+wake-bedtime;wake=min(wake,early);bedtime=1440+wake-night
        grid=[('home_free_activity',rooms['living'],'home')]*144
        dep=arr=None;level=m['activity_scenario_level']
        if role=='school_reference' and school_day(date,age):
            dep=460+(level%2)*10;arr=990+(level%2)*20
            if w.get('eb_reference_type_assignment')=='C' and mid==w['role_policy']['schedule_subject_id']:
                arr+=w['living_habits']['after_school_minutes'] if date.weekday() in w['living_habits']['after_school_weekdays'] else 0
            stamp(grid,dep,dep+30,'travel',None,'outside');stamp(grid,dep+30,arr-30,'school',None,'outside');stamp(grid,arr-30,arr,'travel',None,'outside')
        elif 'daycare' in role and working:
            dep=500;arr=1000
            stamp(grid,dep,dep+20,'given_daycare_transport',None,'outside');stamp(grid,dep+20,arr-20,'given_daycare',None,'outside');stamp(grid,arr-20,arr,'given_daycare_transport',None,'outside')
        elif role=='commuter_reference' and working:
            dep=460+level*20;arr=dep+570
            travel=[20,30,60][level]
            stamp(grid,dep,dep+travel,'travel',None,'outside');stamp(grid,dep+travel,arr-travel,'work',None,'outside');stamp(grid,arr-travel,arr,'travel',None,'outside')
        elif role in ('given_variable_work_reference','given_variable_short_work_reference','given_variable_nonwork_reference'):
            varied=0 # weekly obligation type below determines clocks; no date-hash shifts
            if working or date.weekday()==5:
                late=date.weekday() in w['living_habits']['late_obligation_weekdays']
                dep=max(660 if late else 510,wake+30);duration=480 if role=='given_variable_work_reference'else 120+level*30 if role=='given_variable_short_work_reference'else (120 if age>=75 else 240)
                arr=dep+duration
                stamp(grid,dep,dep+20,'travel',None,'outside')
                stamp(grid,dep+20,arr-20,'work'if role in ('given_variable_work_reference','given_variable_short_work_reference')else 'unclassified_outside_commitment',None,'outside')
                stamp(grid,arr-20,arr,'travel',None,'outside')
            else:stamp(grid,600,660,'home_commitment',rooms['living'])
        elif role in ('home_work_reference','flexible_work_reference') and working:
            if role=='flexible_work_reference' and date.weekday() in (1,3):
                dep=500+level*10;arr=dep+530
                stamp(grid,dep,dep+20,'travel',None,'outside');stamp(grid,dep+20,arr-20,'work',None,'outside');stamp(grid,arr-20,arr,'travel',None,'outside')
            else:
                stamp(grid,510,720,'home_work',sleep_room);stamp(grid,780,1050-level*20,'home_work',sleep_room)
        elif role=='given_short_work_reference' and working:stamp(grid,540,660+level*30,'given_short_work_activity',sleep_room)
        elif age>=18 and role!='given_home_care_reference':
            if role in ('unknown_outside_commitments','community_activity_reference'):
                dur=(300+level*60) if age<75 else (90+level*30)
                if working or date.weekday() in (5,):
                    dep=550+level*10;arr=dep+dur
                    stamp(grid,dep,dep+20,'travel',None,'outside');stamp(grid,dep+20,arr-20,'unclassified_outside_commitment' if m['employment_status']=='unknown' else 'community_activity',None,'outside');stamp(grid,arr-20,arr,'travel',None,'outside')
            elif role in ('unknown_mixed_activity','mixed_activity_reference') and date.weekday() in (0,2,5):
                dep=560;arr=680 if age<85 else 620
                stamp(grid,dep,arr,'given_outside_errand',None,'outside')
            # Home commitments/chores represent meaningful unavailable time, not occupations or attitudes.
            if role in ('unknown_home_commitments','home_commitments_reference','unknown_mixed_activity','mixed_activity_reference'):
                stamp(grid,540,650+level*30,'home_commitment',rooms['living'])
                stamp(grid,800,900+level*20,'home_commitment',rooms['living'])
            stamp(grid,980,1020,'household_chores',rooms['kitchen'])
        if role=='school_reference' and not school_day(date,age):
            stamp(grid,540,620 if age<13 else 660,'school_home_study',sleep_room)
            if date.weekday() in (1,4,6):
                dep,arr=900,960;stamp(grid,dep,arr,'given_recreation_outside',None,'outside')
        # Stable sleep and age-appropriate naps; daycare naps remain located at the centre.
        if nap:
            chunks=[(570,570+nap//2),(810,810+nap//2)] if age==0 else [(780,780+nap)]
            for a,b in chunks:
                location='outside' if dep is not None and dep<=a<b<=arr else 'home'
                stamp(grid,a,b,'day_nap',None if location=='outside' else sleep_room,location)
        stamp(grid,wake,wake+30,'personal_and_breakfast',rooms['meal'])
        # Travel is a prior commitment. A meal may be a work/school break,
        # but cannot replace the trip home or jump between home and outside.
        travel_ledger[mid]=[copy.deepcopy(x) for x in compress(grid)
            if x['activity'] in ('travel','given_daycare_transport')]
        lunch_slots=[t for t in range(660,811,10)
            if len({grid[s][2] for s in range(t//10,(t+30)//10)})==1
            and all(grid[s][0] not in ('travel','given_daycare_transport','day_nap','sleep_rest')
                for s in range(t//10,(t+30)//10))]
        if not lunch_slots:raise ValueError('NO_LUNCH_WITHOUT_REPLACING_TRAVEL:'+hid+':'+mid+':'+str(date))
        lunch=min(lunch_slots,key=lambda t:(abs(t-720),t));location=grid[lunch//10][2]
        stamp(grid,lunch,lunch+30,'meal_and_rest',None if location=='outside'else rooms['meal'],location)
        meal_appointments[mid]={'preferred_lunch_min':720,'actual_lunch_min':lunch,
            'location':location,'travel_preserved':True,'changed_for_prior_commitment':lunch!=720}
        stamp(grid,0,wake,'sleep_rest',sleep_room);stamp(grid,bedtime,1440,'sleep_rest',sleep_room)
        grids[mid]=grid;specs[mid]={'wake_min':wake,'sleep_min':bedtime,'departure_min':dep,'arrival_min':arr,'day_type':dtype,'nap_min':nap,'lunch_min':lunch}
        departures[mid]=dep;arrivals[mid]=arr
    # Family dinner follows return, with separate infant/young-child feeding before bedtime.
    adult_returns=[arrivals[m['member_id']] or 1020 for m in ms if m['age_years']>=18]
    if not adult_returns:adult_returns=[arrivals[m['member_id']] or 1020 for m in ms]
    ph='weekday'if working else'rest'
    habit=w['living_habits']['dinner_min'][ph]
    dinner=max(habit,max(adult_returns,default=1020)+w['living_habits']['arrival_to_dinner_min'])
    dinners={m['member_id']:max((specs[m['member_id']]['arrival_min']or 0)+20,min(dinner,specs[m['member_id']]['sleep_min']-90)if m['age_years']<18 else dinner)for m in ms}
    baths={};reserved=[];care=w['care_contract'];external_visits=[]
    bath_assist={};bath_evidence={}
    adults=[m for m in ms if m['age_years']>=18]
    for m in sorted(ms,key=lambda m:(m['age_years'],m['member_id'])):
        mid=m['member_id'];s=specs[mid];age=m['age_years'];dinnertime=dinners[mid]
        dinners[mid]=dinnertime
        stamp(grids[mid],dinnertime,dinnertime+30,'dinner' if age>=3 else 'given_child_meal',rooms['meal'])
        earliest=max((s['arrival_min'] or 1000)+20,1020) if age<6 else max(dinnertime+50,1040)
        if age>=18:
            bath_style=w['living_habits']['bath_style']
            earliest=max((s['arrival_min']or 960)+20,dinnertime-60)if bath_style=='before_dinner'else dinnertime+40 if bath_style=='after_dinner'else max(dinnertime+40,1230)
        if age>=75:earliest=min(earliest,max((s['arrival_min']or 960)+20,dinnertime-40))
        assistant=None
        if age<6:
            options=[a for a in adults if (arrivals[a['member_id']] or 0)+20<s['sleep_min']-10]
            assistant=min(options,key=lambda a:((arrivals[a['member_id']] or 0),rank(hid,a['member_id'],'bath-helper')))['member_id'] if options else hid+':given_bath_helper'
            if assistant in arrivals:earliest=max(earliest,(arrivals[assistant] or 0)+20)
        preferred_bath=earliest
        search_start=earliest if age<6 else max(1020,(s['arrival_min']or 960)+20)
        candidates=[t for t in range(search_start,min(s['sleep_min']-9,1350),10)
            if not any(overlap((t,t+10),x) for x in reserved)
            and not overlap((t,t+10),(dinners[mid],dinners[mid]+30))
            and grids[mid][t//10][2]=='home'and grids[mid][t//10][0]=='home_free_activity']
        if not candidates:raise ValueError('NO_AGE_APPROPRIATE_BATH:'+hid+':'+mid+':'+date.isoformat())
        assistance_evidence=None
        if age<6:
            # Choose the bath time and helper jointly. A home worker is present
            # but unavailable; a ten-minute work break is never invented.
            joint=[(t,a['member_id']) for t in candidates for a in adults
                if grids[a['member_id']][t//10][2]=='home'
                and grids[a['member_id']][t//10][0]=='home_free_activity'
                and not overlap((t,t+10),(dinners[a['member_id']],dinners[a['member_id']]+30))]
            if joint:
                bath,assistant=min(joint,key=lambda x:(x[0],rank(hid,x[1],'bath-helper')))
                assistance_evidence={'resident_available_activity':grids[assistant][bath//10][0],
                    'given_capability_not_observed':True,'overwrote_work_or_commitment':False}
            else:
                if not w['background_context']['care_support_contract']['bath_assistance_prebooked']:raise ValueError('NO_PREDECLARED_BATH_ASSISTANCE')
                bath=candidates[0];assistant=hid+':given_bath_helper'
                assistance_evidence={'resident_available_activity':None,'given_exact_external_appointment':True,
                    'extra_B_assistance_authorized':False,'cost':None,'overwrote_work_or_commitment':False}
        else:bath=min(candidates,key=lambda t:(abs(t-preferred_bath),t))
        reserved.append((bath,bath+10));baths[mid]=bath
        stamp(grids[mid],bath,bath+10,'bathing',rooms['bath'])
        if assistant in grids:stamp(grids[assistant],bath,bath+10,'child_bathing_assistance',rooms['bath'])
        elif assistant:external_visits.append({'person_id':assistant,'room_id':rooms['bath'],'start_min':bath,'end_min':bath+10,'reason':'given bathing assistance'})
        bath_assist[mid]=assistant
        if assistance_evidence:bath_evidence[mid]=assistance_evidence
        specs[mid].update(dinner_min=dinnertime,bath_min=bath,preferred_bath_min=preferred_bath,bath_calendar_or_shared_resource_fallback=bath!=preferred_bath)
    supervision=[]
    # Source employment remains unknown even where the role is assigned reference commitments.
    calendars={mid:compress(grid) for mid,grid in grids.items()}
    # Declared E protection is an actual booked activity, not an age label.
    # It never overwrites employment, sleep, bath or other commitments.
    protected_checks=[]
    policy=w.get('role_policy',{});holder=policy.get('holder',{}).get('person_id')
    for protected in policy.get('protected_services',[]):
        target=protected['person_id']
        for lo,hi in [(360,720),(1020,1350)]:
            slots=[s for s in range(lo//10,hi//10)if holder in grids and
                   grids[holder][s][0]=='home_free_activity'and grids[holder][s][2]=='home'and
                   grids[target][s][2]=='home'and grids[target][s][0]not in ('sleep_rest','day_nap','bathing')]
            if not slots:raise ValueError('NO_PROTECTED_JOINT_CHECK:'+hid+':'+str(date))
            slot=slots[0];room=grids[target][slot][1];grids[holder][slot]=('given_protected_service_check',room,'home')
            protected_checks.append({'person_id':target,'responsible_person_id':holder,'room_id':room,
                'start_min':slot*10,'end_min':slot*10+10,'evidence_kind':'researcher_given','capability_observed':False})
    calendars={mid:compress(grid) for mid,grid in grids.items()}
    operators={}
    for o in w['operating_context']['operators']:
        mid=o['operator_id']
        operators[mid]=ranges([[i['start_min'],i['end_min']] for i in calendars[mid]
            if i['location']=='home' and i['activity'] not in UNAVAILABLE and i['activity']!='given_child_meal']) if mid in calendars else o['presence_windows_min']
    transport=None
    if 'given_transport_contract' in w:
        tc=w['given_transport_contract'];mid=tc['travelling_member_id'];s=specs[mid];member=next(m for m in ms if m['member_id']==mid)
        business=member['reference_activity_role'] in ('commuter_reference','flexible_work_reference','given_variable_work_reference','given_variable_short_work_reference') and s['departure_min'] is not None and any(g[0]=='work'and g[2]=='outside'for g in grids[mid])
        errand=date.weekday() in (1,5) and dtype!='national_holiday' and member['reference_activity_role']!='given_home_care_reference' and not (working and member['reference_activity_role'] in ('home_work_reference','flexible_work_reference','given_short_work_reference')) and not (member['age_years']<18 and school_day(date,member['age_years']))
        daily_given=w.get('normal_A_contract',{}).get('daily_mobility_task_given',False)
        if daily_given:errand=False # allocate daily mobility to real activity/free time, not over existing home commitments
        added_daily=False;existing_episode=False;daily_dep=daily_arr=None
        if daily_given and not business:
            outside=[i for i in compress(grids[mid])if i['location']=='outside']
            if outside:
                blocks=ranges([[i['start_min'],i['end_min']]for i in outside])
                daily_dep,daily_arr=max(blocks,key=lambda ab:(ab[1]-ab[0],-ab[0]));existing_episode=True
            else:
                available=[i for i in compress(grids[mid])if i['activity']=='home_free_activity'and i['location']=='home'
                           and min(i['end_min'],1200)-max(i['start_min'],540)>=20]
                if not available:raise ValueError('NO_DAILY_MOBILITY_WITHOUT_OVERWRITING_COMMITMENTS:'+hid+':'+str(date))
                interval=min(available,key=lambda i:(abs(max(i['start_min'],540)-570),i['start_min']))
                daily_dep=max(interval['start_min'],540);daily_arr=min(interval['end_min'],daily_dep+60,1200)
            added_daily=True
        if business or errand or added_daily:
            dep=daily_dep if added_daily else s['departure_min'] if s['departure_min'] is not None else 570
            arr=daily_arr if added_daily else s['arrival_min'] if s['arrival_min'] is not None else 690
            if not business and not existing_episode:
                stamp(grids[mid],dep,arr,'given_vehicle_errand',None,'outside');calendars[mid]=compress(grids[mid])
                if mid in operators:operators[mid]=ranges([[i['start_min'],i['end_min']] for i in calendars[mid] if i['location']=='home' and i['activity'] not in UNAVAILABLE and i['activity']!='given_child_meal'])
            dose=(2.5 if arr-dep<=60 else 5. if arr-dep<=180 else 10.)if added_daily else 25. if business and member['activity_scenario_level']==2 else 10. if business else 10. if date.weekday()==5 else 2.5
            transport={'driver_id':tc['driver_id'],'driver_is_resident':tc['driver_is_resident'],
                'handling_operator_id':tc['handling_operator_id'],'travelling_member_id':mid,
                'departure_min':dep,'arrival_min':arr,'traction_kWh':dose,
                'purpose':'explicit daily benchmark mobility associated with existing outside activity'if added_daily and existing_episode else 'explicit daily benchmark mobility task in otherwise free time'if added_daily else 'given work-aligned vehicle journey' if business else 'given weekly supply journey' if date.weekday()==5 else 'given nearby household vehicle errand',
                'daily_task_given_not_population_frequency':daily_given,'existing_work_school_commitments_overwritten':False,
                'route_and_energy_are_given_not_observed':True,
                'passenger_present':True,
                'source':'R04 given journey/energy dose, not a measured commute or inferred unknown employment'}
        # Clear access window can exist without a mandatory journey; no invented daily traction.
    # Allocate supervision after all journeys. Paid work is never overwritten by care or vehicle errands.
    care=w['care_contract'];homecare=[m['member_id'] for m in ms if m['age_years']<6];primary=care['caregiver_id']
    external_needed=[]
    for slot in range(144):
        awake=[cid for cid in homecare if grids[cid][slot][2]=='home' and grids[cid][slot][0] not in ('sleep_rest','day_nap')]
        if not awake:
            # Even a daycare child is at home on closed days. Resting children
            # need adult presence, without declaring the adult continuously awake.
            resting_home=[cid for cid in homecare if grids[cid][slot][2]=='home']
            if resting_home and not any(m['age_years']>=18 and grids[m['member_id']][slot][2]=='home' for m in ms):external_needed.append(slot)
            continue
        eligible=[m['member_id'] for m in ms if m['age_years']>=18 and grids[m['member_id']][slot][2]=='home' and grids[m['member_id']][slot][0] in ('home_free_activity','dinner','personal_and_breakfast','meal_and_rest','child_bathing_assistance','given_protected_service_check')]
        who=primary if primary in eligible else min(eligible,key=lambda mid:rank(hid,mid,'daily-supervision')) if eligible else hid+':given_home_caregiver'
        room=grids[awake[0]][slot][1]
        if who in grids:
            if grids[who][slot][0]=='home_free_activity':grids[who][slot]=('childcare_supervision',room,'home')
        else:external_needed.append(slot)
        supervision.append({'start_min':slot*10,'end_min':slot*10+10,'child_ids':awake,'responsible_person_id':who,'given_not_observed':True})
    # One booked continuous provider visit covers a gap, rather than instantaneous provider appearances.
    if external_needed:
        if not w['background_context']['care_support_contract']['external_supervision_prebooked']:raise ValueError('NO_PREDECLARED_CHILD_CARE_SUPPORT')
        for slot in range(min(external_needed),max(external_needed)+1):
            children=[cid for cid in homecare if grids[cid][slot][2]=='home']
            if not children:continue
            room=grids[children[0]][slot][1]
            external_visits.append({'person_id':hid+':given_home_caregiver','room_id':room,'start_min':slot*10,'end_min':slot*10+10,'reason':'given booked care coverage gap'})
    calendars={mid:compress(grid) for mid,grid in grids.items()}
    operators={o['operator_id']:ranges([[i['start_min'],i['end_min']] for i in calendars[o['operator_id']] if i['location']=='home' and i['activity'] not in UNAVAILABLE and i['activity']!='given_child_meal']) if o['operator_id'] in calendars else o['presence_windows_min'] for o in w['operating_context']['operators']}
    for mid,travels in travel_ledger.items():
        for trip in travels:
            if any(grids[mid][s][0]!=trip['activity'] or grids[mid][s][2]!='outside'
                   for s in range(trip['start_min']//10,trip['end_min']//10)):
                raise ValueError('PREDECLARED_TRAVEL_OVERWRITTEN:'+hid+':'+mid+':'+str(date))
    for mid,sequence in calendars.items():
        outside=[i for i in sequence if i['location']=='outside']
        specs[mid]['departure_min']=outside[0]['start_min']if outside else None
        specs[mid]['arrival_min']=outside[-1]['end_min']if outside else None
        specs[mid]['all_dated_outside_episodes']=[[i['start_min'],i['end_min']]for i in outside]
    result={'date':date.isoformat(),'day_type':dtype,'member_calendars':calendars,'member_specs':specs,
        'operator_windows_min':operators,'family_context':{'dinner_min':dinner,'member_dinners_min':dinners,
            'bath_times_min':baths,'child_bathing_assistants':bath_assist,'child_bathing_assistance_evidence':bath_evidence,'bath_resource':'same single reserved reference bath resource'},
        'care_context':{**copy.deepcopy(care),'under6_supervision_child_ids':homecare,'scope':'all under6 at home, including before/after daycare and closed days; awake supervision and resting adult presence are given reference conditions'},'supervision_ledger':supervision,'protected_service_ledger':protected_checks,'external_visits':external_visits,'transport':transport,
        'school_calendar_status':w['activity_contract']['school_calendar'],
        'protected_travel_ledger':travel_ledger,'meal_appointments':meal_appointments,
        'habit_realization':{'phase':ph,'usual_dinner_min':habit,'actual_family_dinner_min':dinner,'latest_adult_return_min':max(adult_returns,default=1020),
            'dinner_rule':'stable household habit or actual return plus meal provision time,whichever later',
            'causal_contexts':['calendar:'+dtype]+(['school_term']if any(m['age_years']<18 and school_day(date,m['age_years'])for m in ms)else[])+(['given_weekly_late_obligation']if date.weekday()in w['living_habits']['late_obligation_weekdays']and any(m['reference_activity_role'].startswith('given_variable_')for m in ms)else[]),
            'date_hash_minute_jitter':False,'VPP_B_or_answers_used':False}}
    result['activity_day_sha256']=digest(result)
    return result

_CACHE={}
def dated(w,date):
    if isinstance(date,str):date=dt.date.fromisoformat(date)
    key=(w.get('world_content_sha256',digest([w['household_id'],w['activity_contract']])),date.isoformat())
    if key not in _CACHE:
        if len(_CACHE)>1200:_CACHE.clear()
        _CACHE[key]=build_day(w,date)
    return _CACHE[key]

def resident_slot(w,day,member_id,slot,operations=(),tasks=()):
    """Single location authority, including actual handling requests for each side."""
    item=next(i for i in day['member_calendars'][member_id] if i['start_min']<=slot*10<i['end_min'])
    for o in operations:
        if o['operator_id']==member_id and o['start_min']<=slot*10<o['end_min']:
            if o['kind'].startswith('EV_'):return {'activity':'given_EV_handling','location':'outside','room_id':None}
            t=next((t for t in tasks if t['need_id']==o['need_id']),None)
            if t:
                d=next(d for d in w['parameter_pack']['devices'] if d['asset_id']==t['asset_id'])
                return {'activity':'given_appliance_handling','location':'home','room_id':d['room_id']}
    return item
