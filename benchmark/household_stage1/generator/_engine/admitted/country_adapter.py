from zipfile import ZipFile
import xml.etree.ElementTree as ET
import re
NS = {'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
"""Germany and Australia source adapters and constrained reference weeks."""
from pathlib import Path
from collections import Counter
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
import re
import sys

ROOT = Path(__file__).resolve().parent
BASE = Path(__file__).resolve().parent.parent
PLAN = BASE / '.'
V7 = BASE / 'v7'
sys.path.insert(0, str(V7))
import build_cohort as legacy
components, activity, weekend, control, services = (
    legacy.components, legacy.activity, legacy.weekend, legacy.control, legacy.services)
KEY = legacy.KEY
WORK = legacy.WORK
ROLES = 'ABCDEF'
SEED = 'EB-AU-DE-household-reference-20261108-v1'
AU_SOURCE = BASE / 'public_sources/eca2025/eca_jun2025_data.xlsx'
DE_SOURCE = BASE / 'v4/inputs/enable.sav'
AU_SHA = 'ceb26da8c07a06983254dc1d19a1d21f119fd9d9dcfe76730e0a141f3a3c3a07'
DE_SHA = '9e9d466dd932f79db63dde742a823ab84025e24dc69abd90915f12cc53e15aff'
AU_FIELDS = {'age_band':4, 'sex':5, 'state':8, 'region':9, 'energy_decision_responsibility':11,
             'employment':13, 'household_composition':16, 'children':18, 'adults':19,
             'working_adults':20, 'off_street_parking':45, 'air_conditioner':46,
             'cars':47, 'personal_wfh_days':49, 'work_hours_category':50,
             'never_commutes':58, 'tenure':60, 'dwelling_type':63,
             'water_heater_fuel':70, 'home_ev_charger':152, 'battery_electric_vehicle':153,
             'automation':155, 'dishwasher_time_shifting':308, 'heater_time_shifting':309,
             'hot_water_time_shifting':310, 'dryer_time_shifting':311,
             'washer_time_shifting':312, 'ac_time_shifting':313, 'life_support':353}
for d in range(7):
    for j, who in enumerate(('respondent', 'other', 'no_one')):
        AU_FIELDS[f'presence.day{d}.{who}'] = 21 + d*3 + j
JOB = {'Working full time':'employed_full_time', 'Working part time':'employed_part_time',
       'Working casually':'employed_part_time', 'Retired':'retired', 'Unemployed':'not_employed',
       'Full time home / parent duties':'home_caregiver', 'Full-time student':'student'}

def fact(value, fields=(), status='observed', **extra):
    return dict(value=value, fields=list(fields), status=status, **extra)

def scalar(x):
    if hasattr(x, 'item'):
        return x.item()
    raise TypeError(type(x).__name__)

def dumps(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True, default=scalar)

def save(path, value):
    path.parent.mkdir(exist_ok=True, parents=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=scalar)+'\n')

def write_rows(path, rows):
    path.parent.mkdir(exist_ok=True, parents=True)
    path.write_text(''.join(dumps(x)+'\n' for x in rows))

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def rank(*args):
    return hashlib.sha256(dumps([SEED, *args]).encode()).hexdigest()

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

def age_band(value):
    value = str(value).strip()
    match = re.fullmatch(r'(\d+)-(\d+)', value)
    if match:
        low, high = map(int, match.groups())
        return [low, high] if 18 <= low <= high else None
    match = re.fullmatch(r'(\d+)\+', value)
    return [int(match[1]), None] if match and int(match[1]) >= 18 else None

def base_row(dataset, key, country, n, house, size, washer):
    row = components.seed.src.ref(dataset, key, country, n, house, size, washer, anchors={})
    row['additional_devices'] = {'fridge_available':fact(None, (), 'unknown')}
    return row

def german_pool():
    import pyreadstat
    assert sha(DE_SOURCE) == DE_SHA
    data, meta = pyreadstat.read_sav(DE_SOURCE, output_format='dict')
    fields = [f'S1{s}c{a}' for s in 'AB' for a in (1,2,3)]
    raw, pool = {}, []
    for values in zip(*data.values()):
        x = {k:None if isinstance(v,float) and not math.isfinite(v) else v for k,v in zip(data,values)}
        if meta.variable_value_labels['Country'].get(x['Country']) != 'Germany':
            continue
        raw[str(x['UID'])] = x
        counts = [x[f] for f in fields]
        if x['H1'] not in (1,2,3,4) or x['H3'] not in (1,2,3,4,5,6) or x['H11C'] not in (1,2,4):
            continue
        if not all(v is not None and v >= 0 and v == int(v) for v in counts):
            continue
        if not 1 <= sum(counts) <= 8 or counts[1]+counts[4] < 1:
            continue
        row = base_row('ENABLE_EU', str(x['UID']), 'DE', fact(int(sum(counts)), fields, 'derived'),
                       fact(meta.variable_value_labels['H1'][x['H1']], ['H1'], code=int(x['H1'])),
                       fact(meta.variable_value_labels['H3'][x['H3']], ['H3'], measure='dwelling_area_band', code=int(x['H3'])),
                       fact(True, ['H11C'], code=int(x['H11C'])))
        for device, field in [('dishwasher_available','H11B'),('space_ac_available','H11E')]:
            row['devices'][device] = (fact(x[field] in (1,2,4), [field]) if x[field] in (1,2,4,5)
                                      else fact(None, [field], 'unknown'))
        if x['H11G'] in (1,2,4):
            row['devices']['water_heater_available'] = fact(True,['H11G'],appliance_type='standalone_electric_boiler')
        row['members_summary'] = fact([dict(label=('Women' if f[2]=='A' else 'Men')+'_'+str(i%3),
                                    **fact(int(v),[f])) for i,(f,v) in enumerate(zip(fields,counts))],
                                    fields, 'derived', scope='original_sex_and_age_bins')
        row['known_presence'] = (fact({'source_respondent_home_constraint_item':int(x['C4G']),
                                  'scope':'respondent spends much time in dwelling and cannot lower daytime heating; not whole-house occupancy'}, ['C4G'])
                                  if x['C4G'] in (1,2,3,4,5) else fact(None,['C4G'],'unknown'))
        row['geography'] = fact('DE',['Country'],'derived',scope='survey_country')
        row['additional_devices']['fridge_available'] = (fact(x['H11D'] in (1,2,4),['H11D'])
                       if x['H11D'] in (1,2,4,5) else fact(None,['H11D'],'unknown'))
        row['source_technology_presence']={'standalone_electric_water_heater':
             fact(x['H11G'] in (1,2,4),['H11G']) if x['H11G'] in (1,2,4,5) else fact(None,['H11G'],'unknown')}
        if x['H11G']==5:
            row['devices']['water_heater_available']=fact(None,['H11G'],'unknown',
                 scope='explicitly no standalone electric water heater; generic gas/central/other hot-water service not measured here')
        job = {1:'employed_full_time',2:'employed_part_time',3:'not_employed',4:'retired',5:'student',6:'not_employed'}.get(x['S3'])
        row['source_person'] = {'age':fact(None,(),'unknown'), 'employment':fact(job,['S3'],'observed' if job else 'unknown'),
                   'source_person':'survey_respondent', 'teleworking_household':fact(None,(),'unknown'),
                   'commute_frequency':fact(None,['M1A','M3A1'],'unknown')}
        birth = int(x['S4']) if x['S4'] is not None and x['S4'] != 9999 and 1900 <= x['S4'] <= 2019 else None
        sex = {1:'male',2:'female'}.get(x['S5'])
        row['respondent_demographics'] = {'sex':fact(sex,['S5'],'observed' if sex else 'unknown'),
                                        'birth_year':fact(birth,['S4'],'observed' if birth else 'unknown')}
        row['source'].update(survey_year=None, survey_reference_year=None, release='Zenodo1.0,2019-10-31',
                    release_year=2019, fieldwork_year=None, survey_year_semantics='release year is not individual interview year',
                    url='https://zenodo.org/records/3523916')
        row['source_file_sha256'] = DE_SHA
        row['block'] = ['DE', int(x['H1']), int(x['H3']), *map(int, counts)]
        row['pool_id'] = 'ENABLE_EU:'+str(x['UID'])
        pool.append(row)
    assert len(raw) == 711 and len(pool) == 539
    return pool, raw, meta

def australia_pool():
    assert sha(AU_SOURCE) == AU_SHA
    records = xlsx_rows(AU_SOURCE)
    header, body = records[0], records[1:]
    screened = {x[1] for x in body if australian_core(x)}
    raw, pool, excluded = {}, [], []
    for x in body:
        key = x[1]
        raw[key] = x
        if key not in screened:
            continue
        child, adult, working = [int(float(x[i])) for i in (18,19,20)]
        job = JOB.get(x[13])
        reason = None
        if job is None:
            reason = 'respondent employment Other not silently converted to unemployment'
        elif (job in WORK and working == 0) or (job not in WORK and working > adult-1):
            reason = 'respondent employment and household working-adult total conflict'
        days = []
        for d in range(7):
            flags = [x.get(21+d*3+j) for j in range(3)]
            if not all(v in ('Yes','No') for v in flags):
                reason = 'unusable daily presence answer'; break
            me, other, nobody = [v == 'Yes' for v in flags]
            if nobody == (me or other):
                reason = 'daily no-one checkbox conflicts with positive/missing presence'; break
            days.append({'respondent':me,'other':other,'no_one':nobody})
        # This bounded reference-week adapter supports measured daytime-business categories.
        if job in WORK and x[50] != 'Standard business hours (such as 9AM - 5PM or similar)':
            reason = 'non-standard or unspecified working-hour category outside this reference-week adapter'
        if child and len(days)==7 and any(not days[d]['other'] for d in (5,6)):
            reason = 'child household requires weekend external programme outside current bounded adapter'
        if adult == 1 and len(days)==7 and any(d['other'] for d in days):
            reason = 'single-adult household other-home answer needs child-specific home-care age evidence'
        if reason:
            excluded.append({'source_key':key,'reason':reason}); continue
        row = base_row('ECA2025', key, 'AU', fact(child+adult,['A2.children','A2.adults'],'derived'),
                       fact(x[63],['A10.dwelling_type']),
                       fact(None,(),'unknown',measure='not_measured'),
                       fact(True,['Q79.washer'],'derived',scope='reported_functional_time_shifting_use_not_private_ownership'))
        for device, index, field in [('dryer_available',311,'Q79.dryer'),('dishwasher_available',308,'Q79.dishwasher')]:
            positive = x[index] in ('Rarely','Sometimes','Regularly')
            row['devices'][device] = fact(True if positive else None,[field], 'derived' if positive else 'unknown',
                          scope='positive functional use; Never/not-relevant/missing does not establish nonownership')
        row['devices']['space_ac_available'] = fact(x[46]=='Yes',['A4.air_conditioner'])
        fuel = x[70]
        row['devices']['water_heater_available'] = (fact(True,['A13.water_heater_fuel'],
                   energy_carrier='electricity' if fuel=='Electricity' else 'non_electric',
                   appliance_type='source_hot_water_technology_unspecified') if fuel in ('Electricity','Gas')
                   else fact(None,['A13.water_heater_fuel'],'unknown'))
        charging = x[152]=='You already have this' and x[153]=='You already have this' and x[45]=='Yes'
        row['devices']['home_vehicle_charging'] = fact(True if charging else None,
                   ['Technology.home_ev_charger','Technology.battery_electric_vehicle','A4.off_street_parking'],
                   'derived' if charging else 'unknown',
                   scope='same-respondent household BEV+home-charger+parking reports; driver and power not observed')
        ab = age_band(x[4])
        row['members_summary'] = fact([dict(label='Children_under18',**fact(child,['A2.children'])),
                                      dict(label='Adults_18plus',**fact(adult,['A2.adults']))],
                                      ['A2.children','A2.adults'],'derived',scope='source_adult_child_count_groups')
        wfh = (0 if x[49]=='Don’t usually work from home' else 5 if x[49]=='5 days or more per week'
               else int(x[49][0]) if re.fullmatch(r'[1-4] days? per week',str(x[49])) else None)
        row['source_person'] = {'age':fact(None,['Q1.age_band'],'unknown'),
                   'age_band':fact(ab,['Q1.age_band']), 'sex':fact(x[5],['Q2.gender']),
                   'employment':fact(job,['Q6b.employment']), 'source_person':'survey_respondent',
                   'teleworking_household':fact(None,(),'unknown'),
                   'personal_wfh_days':fact(wfh,['A7a.personal_wfh_days'],'observed' if wfh is not None else 'unknown'),
                   'commute_frequency':fact(None,(),'unknown'),
                   'never_commutes':fact(x[58]=='Yes' if x[58] in ('Yes','No') else None,['A8.never_commutes'],
                                       'observed' if x[58] in ('Yes','No') else 'unknown'),
                   'medical_device':fact(x[353]=='Yes',['Q66.life_support'])}
        row['source_household_counts'] = {'children':fact(child,['A2.children']), 'adults':fact(adult,['A2.adults']),
                                         'working_adults':fact(working,['A2.working_adults'])}
        row['known_presence'] = fact({'source_daily_home_09_17':days},
                                     [f'A3.day{d}.{who}' for d in range(7) for who in ('respondent','other','no_one')])
        row['geography'] = fact({'country':'AU','state':x[8],'region':x[9]},['ResState','ResReg'])
        row['source'].update(survey_year=2025,survey_reference_year=2025,fieldwork_period='June2025 wave',
                       release='Consumer Energy Report Card June2025 public raw labelled workbook',
                       url='https://energyconsumersaustralia.com.au/our-work/surveys/energy-consumer-survey-data',
                       household_identity_scope='public respondent-level household report; physical household address not independently verified')
        row['source_record_fields'] = {name:x.get(index) for name,index in AU_FIELDS.items()}
        row['source_file_sha256'] = AU_SHA
        row['block'] = ['AU',x[63],child,adult,working,x[16]]
        row['pool_id'] = 'ECA2025:'+key
        pool.append(row)
    return pool, raw, header, excluded

def make_case(row, role, pair=None):
    c = legacy.make_case(row, role, pair)
    c['case_id'] = 'EB8-'+role+'-'+rank(row['pool_id'],role)[:16]
    c['extension_contract'] = 'AU-DE-source-and-calendar-v1'
    c['source']['catalogue_id'] = c['source']['dataset']
    return c

def init_australia(c, ordinal, alternative):
    p, h = {}, {}
    c['household_provenance'], c['household'] = p, h
    counts = {k:f['value'] for k,f in c['source_household_counts'].items()}
    sp = c['source_person']; role = c['benchmark_role']; members = []
    band = deepcopy(sp['age_band']['value'])
    operational = [band[0],band[1] if band[1] is not None else 90]
    respondent = {'id':'M01','age_band':operational,'source_age_band':band,
                  'source_person_key':c['pool_id']+':respondent','employment':sp['employment']['value'],
                  'school_enrolled':sp['employment']['value']=='student','activity':'home_activity','work_mode':'not_applicable'}
    respondent['sex_from_source'] = {'Male':'male','Female':'female'}.get(sp['sex']['value'], 'another_gender')
    members.append(respondent)
    components.from_fact(p,'members.M01.employment',sp['employment'])
    if band[1] is None:
        activity.tag(p,'members.M01.age_band','reference operational sub-band65-90 inside observed65+; upper bound is not observed',['Q1.age_band'])
    else:
        components.from_fact(p,'members.M01.age_band',sp['age_band'])
    for i in range(counts['adults']-1):
        mid = 'M'+str(len(members)+1).zfill(2)
        bound = [max(18,operational[0]-10), min(90,operational[1]+10)] if counts['adults']==2 and 'partner' in c['source_record_fields']['household_composition'] else [25,59]
        m = {'id':mid,'age_band':bound,'source_age_band':[18,None],'employment':'not_employed',
             'school_enrolled':False,'activity':'home_activity','work_mode':'not_applicable'}
        members.append(m)
        activity.tag(p,f'members.{mid}.age_band','reference adult sub-band inside source18+ count; no observed individual age/sex/kinship',['A2.adults'])
    for i in range(counts['children']):
        mid = 'M'+str(len(members)+1).zfill(2)
        age = 6 + int(rank(c['pool_id'],'child_age',i)[:8],16)%12
        if role=='E' and i==0:age = 6 + int(rank(c['pool_id'],'care_child_age')[:8],16)%6
        members.append({'id':mid,'age_band':[age,age],'source_age_band':[0,17],
                        'employment':'not_in_workforce','school_enrolled':True,'activity':'school','work_mode':'not_applicable'})
        activity.tag(p,f'members.{mid}.age_band','experimental school-age reference inside observed0-17 child count; exact age not measured',['A2.children'])
        activity.tag(p,f'members.{mid}.employment','age-compatible experimental child activity',['A2.children'])
    adults = members[:counts['adults']]
    need = counts['working_adults']-int(respondent['employment'] in WORK)
    choices = sorted(adults[1:],key=lambda m:rank(c['pool_id'],role,'worker_slot',m['id'],alternative))
    if need < 0 or need > len(choices):raise ValueError('observed working-adult total incompatible')
    for m in choices:
        if m in choices[:need]:
            m['employment'] = 'employed_part_time' if (ordinal+alternative)%4==1 else 'employed_full_time'
        activity.tag(p,f"members.{m['id']}.employment",'joint coverage-design: reference worker identity consistent with observed working-adult total',['A2.working_adults'])
    flags = c['known_presence']['value']['source_daily_home_09_17']
    if role in 'AF':
        possible = [m for m in adults if m['employment'] in WORK and m['age_band'][0]<65 and
                    (m is not respondent or (sp['personal_wfh_days']['value'] != 5 and sp['never_commutes']['value'] is not True))]
        possible.sort(key=lambda m:(m is not respondent,m['id']))
    elif role in 'BE':
        possible = [m for m in adults if all(x['respondent'] if m is respondent else x['other'] for x in flags[:5]) and
                    (m['employment'] not in WORK or (role=='B' and m is respondent and sp['personal_wfh_days']['value']==5))]
        possible.sort(key=lambda m:(m is not respondent,m['employment'] in WORK,m['id']))
    else:possible = [respondent]
    if not possible:raise ValueError('no actor satisfies source employment, home-presence and role together')
    actor = possible[0]
    if role in 'AF' and actor['age_band'][1]>=65:
        actor['age_band'][1] = 64
        activity.tag(p,f"members.{actor['id']}.age_band",'working-age reference sub-band inside unmeasured adult source group',['A2.adults'])
    if role=='E' and not counts['children']:raise ValueError('E requires source-supported resident child')
    for m in members:
        mid = m['id']
        if f'members.{mid}.school_enrolled' not in p:
            activity.tag(p,f'members.{mid}.school_enrolled','reference education status; source student respondent status retained')
        m['activity'] = 'work' if m['employment'] in WORK else 'school' if m['school_enrolled'] else 'care' if role=='E' and m is actor else 'home_activity'
        m['work_mode'] = 'onsite' if m['employment'] in WORK else 'not_applicable'
        activity.tag(p,f'members.{mid}.work_mode','reference mode constrained by personal source WFH answers when measured')
    h.update(members=members,decision_maker_id=actor['id'],source_respondent_member_id='M01',country='AU',
             equipment=components.equipment(c,p),calendar={},routine={},care_arrangements=[],ev={},
             attitudes=deepcopy(c['attitudes']['value']),role_id=c['role_card_id'],role_name=c['card']['core'],
             medical_service_must_not_be_interrupted=sp['medical_device']['value'] is True)
    kind = c['dwelling']['observed_type']['value']; n = len(members)
    if kind.startswith('An apartment'):area = 60+20*((n-1)//2)
    elif kind.startswith('A larger'):area = 150+10*min(n,5)
    elif kind.startswith('A smaller'):area = 85+10*min(n,5)
    else:area = 80+10*min(n,5)
    h['dwelling'] = {'type':kind,'reference_area_m2':area,'source_size_measure':'not_measured','area_is_reference_input':True}
    components.from_fact(p,'dwelling.type',c['dwelling']['observed_type'])
    activity.tag(p,'dwelling.reference_area_m2','explicit reference model area by source type and household count; no statistical or same-household area claim')
    h['completion_design'] = {'family':'source_total_constrained_reference','unobserved_adult_member_ids':[m['id'] for m in adults[1:]],
                             'selection':'observed total and personal WFH compatible reference slots','alternative_index':alternative,
                             'population_employment_estimate':False,'sex_used_for_activity_assignment':False}
    activity.tag(p,'completion_design','source-total-constrained experimental member identity allocation')
    activity.tag(p,'decision_maker_id','experimental adult role actor; household source respondent remains separately bound')
    activity.equipment_detail(c)
    h['comfort'] = ({'preferred_cooling_c':[24,25] if role=='B' else [24,26],
                     'allowed_short_adjustment_c':{'A':1,'B':.5,'C':1,'D':2,'E':.5,'F':1}[role],
                     'comfort_ceiling_c':26} if h['equipment']['space_ac_available']['present'] else {})
    activity.tag(p,'comfort','original EB role reference bounds, not inferred from source attitudes')
    h['routine'] = {'laundry_cycles_per_week':3,'laundry_must_complete_whole_cycles':True,
                    'care_protection_windows':c['routine'].get('care_protection_windows_minutes',[])}
    activity.tag(p,'routine.laundry_cycles_per_week','three experimental weekly whole-cycle service needs, not observed frequency')
    if role=='E':
        child = next(m for m in members if m['age_band'][1]<12)
        h['role_care_binding'] = {'caregiver_id':actor['id'],'child_id':child['id'],'status':'benchmark_assigned',
             'not_inferred_from_country':True,'reference_responsibility_is_not_source_care_measurement':True}
    if h['equipment']['home_vehicle_charging']['present'] or role=='F':
        h['ev'] = {'reference_powertrain':'battery_electric','charger_type':'Level_2','reference_charger_kw':3.6,
                   'reference_battery_kwh':60,'arrival_soc':.5,'departure_soc_target':.8,'charge_efficiency':.9,
                   'vehicle_user_member_id':actor['id'],'commute_use':'conditional_personal_mobility_experiment',
                   'charging_contiguity':'one_continuous_session_is_required_for_base_need'}
        activity.tag(p,'ev','reference vehicle size and driver authorization; source BEV and charger kept separately')
    h['role_condition_binding'] = {'role':role,'actor_id':actor['id'],'actor_employment_status':p[f"members.{actor['id']}.employment"]['status'],
         'source_actual_role_measured':False,'country_used_to_choose_role':False,'conditional_reference_EV':role=='F',
         'source_home_EV_observed':c['devices']['home_vehicle_charging']['value'] is True}

def home_minutes_09_17(events, mid, day):
    a,b = day*1440+540,day*1440+1020
    away = sorted((max(a,e['start']),min(b,e['end'])) for e in events if e['member_id']==mid and e['location']=='away' and activity.overlap(a,b,e['start'],e['end']))
    total,right = 0,a
    for x,y in away:
        total += max(0,y-max(x,right)); right = max(right,y)
    return 480-total

def australia_activities(c):
    h=c['household'];p=c['household_provenance'];ms=h['members'];adults=[m for m in ms if m['age_band'][0]>=18]
    flags=c['known_presence']['value']['source_daily_home_09_17'];respondent=adults[0];events=[]
    wfh=c['source_person']['personal_wfh_days']['value'];yes=[d for d in range(5) if flags[d]['respondent']]
    if respondent['employment'] in WORK:
        if wfh is None or wfh>len(yes):raise ValueError('source personal WFH and day-specific presence cannot jointly fit business-hour week')
        if respondent['employment']=='employed_full_time' and wfh!=len(yes):raise ValueError('full-time business-hours and personal home days mismatch')
        remote_days=set(sorted(yes,key=lambda d:rank(c['case_id'],'wfh',d))[:wfh])
        if c['source_person']['never_commutes']['value'] is True and wfh<5:
            raise ValueError('source never-commutes answer conflicts with current five-day work reference')
    else:remote_days=set()
    for m in adults:
        m['weekly_work']={'paid_minutes':0,'basis':'not_applicable','source_last_week_hours':None,'source_week_reconstruction':False}
    for d,x in enumerate(flags):
        others=adults[1:]
        if x['other'] and not others:raise ValueError('other home person cannot be silently invented')
        helper=(next((m for m in others if m['id']==h['decision_maker_id']),None) or
                min(others,key=lambda m:(m['employment'] in WORK,rank(c['case_id'],'home_helper',m['id'])))) if x['other'] else None
        for m in adults:
            mid=m['id'];is_self=m is respondent;should_home=x['respondent'] if is_self else m is helper
            shift=[0,60,-30,45,-60][d] if d<5 and mid==h['decision_maker_id'] and c['benchmark_role']=='C' else 0
            if m['employment'] in WORK and d<5:
                paid=240 if m['employment']=='employed_part_time' else 480
                remote=(d in remote_days) if is_self else should_home
                start=510+shift
                if should_home and not remote:
                    if paid>240:raise ValueError('full-time on-site worker cannot satisfy source majority home day')
                    start=810
                travel=0 if remote else 40
                pause=30 if paid>=300 else 0
                end=start+paid+pause+travel
                activity.add(events,mid,'work',d*1440+start,d*1440+end,'home' if remote else 'away',
                             paid_minutes=paid,commute_roundtrip_minutes=travel,break_minutes=pause,
                             reference_shift=True,worksite_start=d*1440+start+travel/2,
                             worksite_end=d*1440+end-travel/2)
                m['weekly_work']['paid_minutes']+=paid
                m['weekly_work'].update(basis='experimental_typical_week',source_commute_roundtrip_minutes=40,
                                       commute_measured=False)
            elif m['school_enrolled'] and d<5:
                start=720 if should_home else 600
                duration=120 if should_home else 300
                activity.add(events,mid,'study',d*1440+start,d*1440+start+duration,
                             'home' if should_home else 'away',activity_reason='reference adult education consistent with source home-day answer')
            elif not should_home:
                a,b=(600+shift,900+shift) if d<5 else (600,900)
                activity.add(events,mid,'community_program',d*1440+a,d*1440+b,'away',
                             activity_reason='experimental volunteering, learning or personal-errand block; source records only usual absence, not this activity')
            elif mid==h['decision_maker_id'] and c['benchmark_role']=='C' and d<5:
                activity.add(events,mid,'community_program',d*1440+720+shift,d*1440+810+shift,'away',
                             activity_reason='experimental short variable activity within source majority-home condition')
    for m in adults:
        modes=[e['location']=='home' for e in events if e['member_id']==m['id'] and e['kind']=='work']
        m['work_mode']='home_based' if modes and all(modes) else 'hybrid' if any(modes) else 'onsite' if modes else 'not_applicable'
        activity.tag(p,f"members.{m['id']}.weekly_work",'reference workload; personal WFH frequency and observed working-adult total retained')
    return events

def presence_check(c, events, final=True):
    if c['source']['country']=='AU':
        members=c['household']['members'];mid=c['household']['source_respondent_member_id']
        for d,x in enumerate(c['known_presence']['value']['source_daily_home_09_17']):
            me=home_minutes_09_17(events,mid,d)
            others=[home_minutes_09_17(events,m['id'],d) for m in members if m['id']!=mid and (final or m['age_band'][0]>=18)]
            if x['respondent'] and me<270:raise ValueError('source respondent majority-home answer not realized')
            if not x['respondent'] and me>240:raise ValueError('source respondent negative home answer not realized')
            if x['other'] and not any(v>=270 for v in others):raise ValueError('source other-member home answer not realized')
            if not x['other'] and any(v>240 for v in others):raise ValueError('source other-member negative home answer not realized')
    else:
        value=(c['known_presence']['value'] or {}).get('source_respondent_home_constraint_item')
        respondent=c['household']['source_respondent_member_id']
        daily=[home_minutes_09_17(events,respondent,d)>=270 for d in range(5)]
        if value==5 and not all(daily):raise ValueError('source respondent high daytime-home constraint not realized')
        if value in (1,2) and sum(daily)>2:raise ValueError('negative respondent daytime-home constraint contradicted by majority-week home pattern')

def set_de_targets(c, events):
    value=(c['known_presence']['value'] or {}).get('source_respondent_home_constraint_item')
    h=c['household'];adults=[m for m in h['members'] if m['age_band'][0]>=18]
    respondent=next(m for m in adults if m['id']==h['source_respondent_member_id'])
    if value in (1,2):
        for d in range(5):
            for m in [respondent]:
                if home_minutes_09_17(events,m['id'],d)>240:
                    delta=([0,60,-30,45,-60][d] if m['id']==h['decision_maker_id'] and c['benchmark_role']=='C' else 0)
                    a,b=d*1440+600+delta,d*1440+900+delta
                    own=[e for e in events if e['member_id']==m['id'] and e['start']//1440==d]
                    if any(e['kind'] in ('work','study') and activity.overlap(a,b,e['start'],e['end']) for e in own):
                        raise ValueError('negative home answer requires unsupported work shift')
                    events[:]=[e for e in events if not(e['member_id']==m['id'] and e['kind']=='community_program' and e['start']//1440==d)]
                    activity.add(events,m['id'],'community_program',a,b,'away',activity_reason='explicit reference outside activity respects negative usual-home response')
    elif value==5:
        for d in range(5):
            if home_minutes_09_17(events,respondent['id'],d)>=270:continue
            raise ValueError('strong respondent home constraint not realized')

def enrich_interfaces(c):
    h=c['household'];p=c['household_provenance'];events=h['calendar']['weekly_events']
    # Explicit manual opportunities exclude meals, bathing, work, trips and handoff buffers.
    for day in h['routine']['daily_services']:
        base=day['day']*1440;a,b=day['flexible_chore_window'];opportunities=[]
        for mid in day['chore_member_ids']:
            cuts=[(e['start']-base,e['end']-base) for e in events if e['member_id']==mid and
                  (e['location']=='away' or e['kind'] in ('work','study','bathing'))]
            cuts += [(x['start'],x['end']) for x in day['meals'] if mid in x['participants']]
            cuts += [(e['start']-base-15,e['end']-base+15) for e in events if e['member_id']==mid and e['kind']=='escort']
            for x,y in activity.segments(cuts,a,b):
                if y-x>=10 and not any(activity.overlap(x,y,u,v) for u,v in cuts):
                    opportunities.append({'member_id':mid,'start':x,'end':y,'scope':'manual loading/unloading/start opportunity, not a whole appliance operating interval'})
        if not opportunities:raise ValueError('chore window has no actual ten-minute resident operation opportunity')
        day['manual_operation_opportunities']=opportunities
    h['decision_authorization']={'status':'benchmark_assigned','decision_maker_id':h['decision_maker_id'],
        'scope':'conditional household authority over enrolled reference services; preserve all members required services',
        'real_family_consent_observed':False,'ev_driver_id':h.get('ev',{}).get('vehicle_user_member_id'),
        'ev_adjustment_authorization':'reference driver permits bounded schedule changes only within parking/departure service contract' if h.get('ev') else None}
    activity.tag(p,'decision_authorization','explicit experimental authority, not inferred from kinship or survey billing responsibility')
    template=c['routine'].get('personal_commute_scenario')
    if template:
        actor=h['decision_maker_id'];work=next((e for e in events if e['member_id']==actor and e['kind']=='work' and e['location']=='away'),None)
        if work:
            template.update(depart_minutes=work['start']%1440,return_minutes=work['end']%1440,
                            day_indices=sorted({e['start']//1440 for e in events if e['member_id']==actor and e['kind']=='work' and e['location']=='away'}),
                            authoritative_view='household.calendar.weekly_events',summary_scope='first reference workday; full week remains authoritative')
            template['days_per_week']=len(template['day_indices'])
            if c['role_anchor']['status']=='benchmark_assigned':
                c['role_anchor']['value']['days_to_work_or_study']=template['days_per_week']
    h['calendar']['source_presence_compatibility']={'checked':True,'AU_source_clock':'09:00-17:00',
        'AU_positive_reference_threshold_minutes':270,'AU_negative_reference_max_minutes':240,
        'DE_C4G_scope':'respondent personal heating-context constraint; qualitative response is not a measured number of home days',
        'scope':'reference scenario compatible with usual survey answers, not observed travel diary'}

def build_week(c, ordinal):
    if c['source']['country']=='AU':
        events=australia_activities(c);targets=[None]*7;nights=[True]*7
    else:
        events,targets,nights=activity.build_activities(c)
        set_de_targets(c,events)
    original=deepcopy(events)
    events=weekend.apply(c,events,targets,ordinal)
    try:presence_check(c,events,final=False)
    except ValueError:
        events=original
        h=c['household'];requested=h['weekend_design']['requested_stratum']
        h['weekend_design'].update(actual_added_outings=0,blocks=[],fallback_to_existing_commitments=True,
                                   infeasible_plans=h['weekend_design']['infeasible_plans']+['source daily presence conflict'])
    activity.schooling_and_care(c,events)
    for e in events:
        member=next(m for m in c['household']['members'] if m['id']==e['member_id'])
        if e['kind']=='extended_school_care' and member['age_band'][0]>=12:
            e['kind']='school_waiting'
            e['provider']='experimental school arrival/waiting or study period; no young-child care inference'
    activity.accompany_school_runs(c,events)
    activity.build_services(c,events)
    activity.refresh_supervision(c,events)
    activity.finalize_calendar(c,events,targets,nights)
    presence_check(c,events)
    enrich_interfaces(c)
    return c

def initialize(c, ordinal, alternative=0):
    if c['source']['country']=='AU':init_australia(c,ordinal,alternative)
    else:
        legacy.initialize(c,ordinal,alternative)
        for m in c['household']['members']:
            status=c['household_provenance'][f"members.{m['id']}.employment"]['status']
            if m['age_band'][0]>=66 and status not in ('observed','survey_imputed'):
                m.update(employment='retired',school_enrolled=False,work_mode='not_applicable',activity='home_activity')
                activity.tag(c['household_provenance'],f"members.{m['id']}.employment",
                    'joint coverage-design: retired reference older co-resident; source retirement/job not measured, no invented long work shifts')
        prepare_german_respondent_constraint(c)
    materialize_reference_ages(c)
    return build_week(c,ordinal)

def prepare_german_respondent_constraint(c):
    h=c['household'];p=c['household_provenance'];role=c['benchmark_role']
    value=(c['known_presence']['value'] or {}).get('source_respondent_home_constraint_item')
    respondent=next(m for m in h['members'] if m['id']==h['source_respondent_member_id'])
    actor=next(m for m in h['members'] if m['id']==h['decision_maker_id'])
    needs_other=(value==5 and role in 'AF' and actor is respondent) or (value in (1,2) and role in 'BE' and actor is respondent)
    if needs_other:
        choices=[m for m in h['members'] if m is not respondent and m['age_band'][0]>=18
                 and (role not in 'AF' or m['age_band'][0]<65)]
        if not choices:raise ValueError('respondent-specific home constraint leaves no compatible role actor')
        actor=min(choices,key=lambda m:m['id'])
        actor['employment']='employed_full_time' if role in 'AF' else 'home_caregiver' if role=='E' else 'not_employed'
        actor['school_enrolled']=False
        actor['work_mode']='onsite' if role in 'AF' else 'not_applicable'
        actor['activity']='work' if role in 'AF' else 'care' if role=='E' else 'home_activity'
        activity.tag(p,f"members.{actor['id']}.employment",'joint coverage-design: reference co-resident actor preserves observed respondent employment and personal home constraint')
        if role in 'AF' and actor['age_band'][1]>=65:actor['age_band'][1]=64
        h['decision_maker_id']=actor['id']
        if role=='F' and h.get('ev'):h['ev']['vehicle_user_member_id']=actor['id']
        h['role_condition_binding'].update(actor_id=actor['id'],actor_employment_status='benchmark_assigned')
        if role=='E':h['role_care_binding']['caregiver_id']=actor['id']
    if value==5 and respondent['employment'] in WORK:
        respondent['work_mode']='home_based'
        activity.tag(p,f"members.{respondent['id']}.work_mode",'reference home work makes respondent-specific daytime-home constraint compatible; source does not measure exact WFH days',['C4G'])
    if value in (1,2) and respondent['employment'] in WORK:
        respondent['work_mode']='onsite'
        activity.tag(p,f"members.{respondent['id']}.work_mode",'reference onsite work compatible with low respondent daytime-home constraint',['C4G'])

def materialize_reference_ages(c):
    """Separate source intervals from concrete experimental people used in the week."""
    h=c['household'];p=c['household_provenance'];respondent=h['source_respondent_member_id']
    originals={m['id']:deepcopy(m['age_band']) for m in h['members']}
    de_bounds=[]
    if c['source']['country']=='DE':
        for group,bounds in zip(c['members_summary']['value'],[(0,18),(18,65),(66,None)]*2):
            de_bounds.extend([list(bounds) for _ in range(group['value'])])
    for i,m in enumerate(h['members']):
        lo,hi=originals[m['id']]
        source_band=deepcopy(m.get('source_age_band',de_bounds[i] if de_bounds else [lo,hi]))
        m['source_age_band']=source_band
        if m['id']==respondent and c['source']['country']=='DE' and m.get('source_birth_year') is not None:
            year=m['source_birth_year'];possible=list(range(max(lo,2015-year),min(hi,2019-year)+1))
            if not possible:raise ValueError('no source-birth-compatible reference age')
            age=possible[len(possible)//2]
        elif m['id']==respondent:
            age=71 if source_band[1] is None else (lo+hi)//2
            age=max(lo,min(hi,age))
        elif hi<18:
            choices=[n for n in (7,9,11,13,15,17) if lo<=n<=hi]
            age=choices[int(rank(c['pool_id'],'reference_child',m['id'])[:8],16)%len(choices)] if choices else lo
        elif lo>=65:
            choices=[n for n in (67,70,73,76,79) if lo<=n<=hi]
            age=choices[int(rank(c['pool_id'],'reference_older',m['id'])[:8],16)%len(choices)] if choices else lo
        else:
            choices=[n for n in (28,35,42,49,56,62) if lo<=n<=min(hi,64 if m['employment'] in WORK else hi)]
            if m['employment']=='retired':
                choices=[n for n in (56,60,64) if lo<=n<=hi] or choices
            age=choices[int(rank(c['pool_id'],'reference_adult',m['id'])[:8],16)%len(choices)] if choices else (lo+hi)//2
        m['reference_age']=int(age)
        m['age_band']=[int(age),int(age)]
        old_fields=p.get(f"members.{m['id']}.age_band",{}).get('source_fields',[])
        activity.tag(p,f"members.{m['id']}.source_age_band",'source respondent interval or source count-group interval; co-resident identities are reference slots',old_fields,
                     status='observed' if c['source']['country']=='AU' and m['id']==respondent else 'derived')
        activity.tag(p,f"members.{m['id']}.age_band",'concrete experimental reference age inside source-compatible interval; source interval and respondent birth year remain separate',old_fields)
        activity.tag(p,f"members.{m['id']}.reference_age",'experimental age for readable household scenario, not an observed exact age',old_fields)
    h['reference_age_design']={'all_reference_ages_are_experimental':True,'source_intervals_retained':True,
         'not_demographic_imputation_or_population_age_estimate':True,'school_age_only_when_source_has_coarse_child_counts':True}

def xlsx_rows(path):
    with ZipFile(path) as z:
        strings = []
        if 'xl/sharedStrings.xml' in z.namelist():
            doc = ET.fromstring(z.read('xl/sharedStrings.xml'))
            strings = [''.join(si.itertext()) for si in doc.findall('m:si', NS)]
        doc = ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
        result = []
        for row in doc.findall('m:sheetData/m:row', NS):
            record = {}
            for cell in row.findall('m:c', NS):
                letters = re.match('[A-Z]+', cell.attrib['r'])[0]
                col = 0
                for letter in letters:
                    col = 26 * col + ord(letter) - 64
                value = cell.find('m:v', NS)
                if cell.attrib.get('t') == 'inlineStr':
                    inline = cell.find('m:is', NS)
                    parsed = ''.join(inline.itertext()) if inline is not None else None
                elif value is None:
                    parsed = None
                elif cell.attrib.get('t') == 's':
                    parsed = strings[int(value.text)]
                else:
                    parsed = value.text
                record[col - 1] = parsed
            result.append(record)
        return result

def australian_core(row):
    def integer(value):
        try:
            v=float(value)
            return int(v) if math.isfinite(v) and v>=0 and v==int(v) else None
        except (TypeError,ValueError):return None
    child,adult,working=[integer(row.get(i)) for i in (18,19,20)]
    age=age_band(row.get(4))
    return (None not in (child,adult,working) and age is not None
        and 1<=child+adult<=8 and adult>=1 and working<=adult
        and str(row.get(63)).startswith(('A semi-detached','An apartment','A larger','A smaller'))
        and row.get(312) in ('Rarely','Sometimes','Regularly'))
