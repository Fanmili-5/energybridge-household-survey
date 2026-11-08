"""Construct a usable experimental household while preserving source evidence."""
from collections import Counter
from copy import deepcopy
from pathlib import Path
import hashlib,json,sys
import source_enrichment as sources
seed=sources.install()
ROOT=Path(__file__).resolve().parent
DESIGN_SEED='EB-complete-households-v3'
NAMES={'washer_available':'洗衣机','dryer_available':'烘干设备/功能','dishwasher_available':'洗碗机','space_ac_available':'空调','water_heater_available':'热水设备','home_vehicle_charging':'居家车辆充电','fridge_available':'冰箱','kettle_available':'电热水壶','electric_oven_available':'电烤箱'}
WORKING={'employed','employed_full_time','employed_part_time'}

def pick(values,*salt):return values[int(hashlib.sha256(json.dumps([DESIGN_SEED,*salt],ensure_ascii=False,sort_keys=True).encode()).hexdigest(),16)%len(values)]
def provenance(p,path,status,fields=(),reason=''):
 p[path]={'status':status,'source_fields':list(fields),'reason':reason}
def from_fact(p,path,f,reason=''):
 provenance(p,path,f['status'],f.get('fields',()),reason)
def hhmm(t):return f'{t//60:02d}:{t%60:02d}'

def roster(c,p):
 ms=c['members_summary'];sp=c['source_person'];out=[];ds=c['source']['dataset'];role=c['benchmark_role']
 def add(lo,hi,f,person=None,sex=None,exact=None):
  mid='M'+str(len(out)+1).zfill(2)
  # School-age is an explicit reference sub-group when only broad child counts exist.
  plo,phi=(6,17) if lo==0 and hi in (17,18) else (lo,hi)
  m={'id':mid,'age_band':[plo,phi],'employment':'not_in_workforce' if phi<18 else 'retired' if plo>=65 else 'not_employed','school_enrolled':phi<18,'activity':'school' if phi<18 else 'home_activity','work_mode':'not_applicable'}
  if person:m['source_person_key']=person
  if sex:m['sex_from_source']=sex
  if exact is not None:m['observed_age']=exact
  out.append(m)
  if (plo,phi)!=(lo,hi):provenance(p,f'members.{mid}.age_band','benchmark_assigned',f.get('fields',()),'school-age reference sub-group inside original child band; not observed exact ages')
  else:from_fact(p,f'members.{mid}.age_band',f)
  provenance(p,f'members.{mid}.employment','benchmark_assigned',reason='age-compatible default; overwritten by observed individual employment when available')
  provenance(p,f'members.{mid}.school_enrolled','benchmark_assigned',reason='reference education status; source enrollment takes precedence')
  return m
 if ms['scope']=='source_person_roster':
  for r in ms['value']:
   a=r['age']['value'];m=add(a,a,r['age'],person=r['person_key'],exact=a)
   details=c['source_member_details'][r['person_key']]
   if details['employment']['value'] is not None:m['employment']=details['employment']['value'];from_fact(p,f"members.{m['id']}.employment",details['employment'])
   if details['school_enrollment']['value'] is not None:m['school_enrolled']=details['school_enrollment']['value'];from_fact(p,f"members.{m['id']}.school_enrolled",details['school_enrollment'])
 elif ms['value'] is None:
  for _ in range(c['household_size']['value']):add(18,64,{'status':'benchmark_assigned','fields':[]})
 else:
  if ds=='ENABLE_EU':bounds=[(0,18),(18,65),(66,120),(0,18),(18,65),(66,120)]
  elif ds=='IRES2020':bounds=[(0,17),(18,40),(41,60),(61,120)]
  else:bounds=[(0,17),(18,64),(65,120)]
  for g,(lo,hi) in zip(ms['value'],bounds):
   for _ in range(g['value']):add(lo,hi,g,sex=('female' if g['label'].startswith('Women') else 'male') if ds=='ENABLE_EU' else None)
 adults=[m for m in out if m['age_band'][0]>=18]
 assert adults,'No eligible adult'
 age=sp['age']['value']
 if ds=='ENASIC2022':respondent=next(m for m in out if m.get('source_person_key')==sp['source_person'])
 elif age is not None:
  respondent=next(m for m in adults if m['age_band'][0]<=age<=m['age_band'][1]);respondent['observed_age']=age
  if ds.startswith('RECS') and age==90:
   respondent.pop('observed_age');respondent['observed_age_lower_bound']=90;respondent['age_band']=[90,120]
  from_fact(p,f"members.{respondent['id']}.observed_age",sp['age'])
 else:respondent=adults[0]
 if sp['employment']['value'] is not None:
  respondent['employment']=sp['employment']['value'];from_fact(p,f"members.{respondent['id']}.employment",sp['employment'])
 if ds=='ENASIC2022' and role=='E':actor=respondent
 elif role=='B' and respondent['employment'] in WORKING and sp['teleworking_household']['value'] is False:
  actor=next((m for m in adults if m is not respondent),respondent)
 else:actor=respondent
 if ds=='IRES2020':
  target=sp['household_students']['value']
  assert 0<=target<=len(out),'invalid observed student count'
  for i,m in enumerate(sorted(out,key=lambda m:m['age_band'][0])):
   m['school_enrolled']=i<target
   provenance(p,f"members.{m['id']}.school_enrolled",'benchmark_assigned',['q215_no_members_studying'],'member allocation respects observed total student count; identities not observed')
 if ds=='IDEAL':
  respondent['employment']='employed_full_time';provenance(p,f"members.{respondent['id']}.employment",'benchmark_assigned',reason='reference adult work arrangement; source household metadata do not identify employment')
 if respondent['employment']=='student':respondent['school_enrolled']=True
 for m in out:
  if m['school_enrolled']:m['activity']='school'
  elif m['employment'] in WORKING:m['activity']='work'
  elif m['employment']=='home_caregiver':m['activity']='care'
  else:m['activity']='home_activity'
  if m['employment'] in WORKING:
   m['work_mode']='hybrid' if m is respondent and sp['teleworking_household']['value'] is True else 'onsite'
  provenance(p,f"members.{m['id']}.work_mode",'benchmark_assigned',reason='experimental weekly work arrangement, not measured work hours')
 # Nonworking older members retain their employment status, not an invented job.
 return out,actor,respondent


def dwelling(c,p):
 dw=c['dwelling'];kind=dw['observed_type']
 if kind['value'] is None:kind=dw['reference_type']
 from_fact(p,'dwelling.type',kind)
 size=dw['size'];measure=size['measure'];n=c['household_size']['value']
 if measure in ('energy_consuming_dwelling_area_m2','respondent_reported_dwelling_area_m2','dwelling_area_m2'):
  area=size['value'];from_fact(p,'dwelling.reference_area_m2',size,'source measurement retained, not measured thermal geometry')
 elif measure=='dwelling_area_band':
  bounds={1:(30,42),2:(43,65),3:(66,90),4:(91,120),5:(121,200),6:(210,280)}[size['code']]
  area=round((bounds[0]+bounds[1])/2,1);provenance(p,'dwelling.reference_area_m2','benchmark_assigned',size['fields'],'mid-band design; open-ended bands use stated reference range')
 elif measure=='single_observed_room_area_m2':
  area=max(45+12*(n-1),size['value']+20);provenance(p,'dwelling.reference_area_m2','benchmark_assigned',size['fields'],'reference total area based on household size, greater than measured single room; not source whole-home area')
 else:
  area=round(max(25,15+12*size['value']),1);provenance(p,'dwelling.reference_area_m2','benchmark_assigned',size['fields'],'declared reference area from room count; no observed area imputed as truth')
 return {'type':kind['value'],'reference_area_m2':area,'source_size_measure':measure,'area_is_reference_input':True}


def equipment(c,p):
 out={};allfacts={**c['devices'],**c['additional_devices']}
 for name,f in allfacts.items():
  matched=c.get('reference_equipment',{}).get('values',{})
  present=f['value'] if f['value'] is not None else matched[name] if name in matched else name in ('fridge_available','water_heater_available')
  out[name]={'present':present}
  if f['value'] is None and name in matched:provenance(p,f'equipment.{name}.present','reference_matched',reason='same-region compatible-household RECS2020 reference equipment; not observed on this household')
  elif f['value'] is None:provenance(p,f'equipment.{name}.present','benchmark_assigned' if present else 'benchmark_assigned_absence',reason='reference refrigeration or non-electric hot-water service' if present else 'minimal optional-equipment baseline; does not infer real absence')
  else:from_fact(p,f'equipment.{name}.present',f)
  if not present:continue
  carrier='electricity';status='derived';reason='electrical appliance function; no measured rated power inferred'
  if name=='water_heater_available':
   if f['value'] is None and 'water_heater_carrier' in matched:carrier=matched['water_heater_carrier'];status='reference_matched';reason='reference equipment donor fuel'
   elif 'energy_carrier' in f and f['energy_carrier']!='unknown':carrier=f['energy_carrier'];status=f['status'];reason='source carrier or identified electrical shower'
   elif f.get('appliance_type') in ('standalone_electric_boiler','electric_geyser'):carrier='electricity';reason='source explicitly identifies electric heating'
   else:carrier='non_electric';status='benchmark_assigned';reason='reference non-electric supply when source says boiler/solar but not fuel'
  if name=='dryer_available' and c['source']['dataset'].startswith('RECS'):
   fuel=c['source_person']['dryer_fuel_code']
   if fuel['value'] in ('1','2','3','7','8'):carrier='non_electric';status=fuel['status'];reason='source dryer fuel'
   elif fuel['value']=='5':carrier='electricity';status=fuel['status'];reason='source dryer fuel'
   else:status='benchmark_assigned';reason='reference electric dryer where carrier is not measured'
  out[name]['energy_carrier']=carrier;carrier_fields=c['source_person']['dryer_fuel_code'].get('fields',()) if name=='dryer_available' and c['source']['dataset'].startswith('RECS') else f.get('fields',())
  provenance(p,f'equipment.{name}.energy_carrier',status,carrier_fields,reason)
  if f.get('appliance_key'):out[name]['source_asset_key']=f['appliance_key']
 return out


def calendar(c,members,actor,respondent,p):
 role=c['benchmark_role'];known=c['known_presence']['value'];country=c['source']['country'];sp=c['source_person']
 if isinstance(known,dict) and 'someone_home_weekdays' in known:
  k=known['someone_home_weekdays'];days=sorted(range(5),key=lambda d:pick(list(range(999)),c['case_id'],'day',d))[:k];daymask=[d in days or d>=5 for d in range(7)];from_fact(p,'calendar.weekday_home_count',c['known_presence'])
 elif isinstance(known,dict) and 'occupied_days' in known:
  k=known['occupied_days'];days=sorted(range(7),key=lambda d:pick(list(range(999)),c['case_id'],'day',d))[:k];daymask=[d in days for d in range(7)];from_fact(p,'calendar.home_day_count',c['known_presence'])
 else:daymask=[True]*7;provenance(p,'calendar.home_day_count','benchmark_assigned',reason='reference week; not a whole-house vacancy inference from one commuter')
 if isinstance(known,dict) and 'occupied_nights' in known:
  k=known['occupied_nights'];nights=sorted(range(7),key=lambda d:pick(list(range(999)),c['case_id'],'night',d))[:k];nightmask=[d in nights for d in range(7)];from_fact(p,'calendar.home_night_count',c['known_presence'])
 else:nightmask=[True]*7;provenance(p,'calendar.home_night_count','benchmark_assigned',reason='reference week at home overnight')
 adults=[m for m in members if m['age_band'][0]>=18]
 if role in 'AF':
  workdays=c['routine']['personal_commute_scenario']['day_indices'];part=actor['employment']=='employed_part_time'
  leave=pick([450,480,510],c['case_id'],'leave') if not part else 570
  back=leave+(600 if not part else 450)
 elif role=='B' and sp.get('commute_frequency',{}).get('value') is not None:
  workdays=list(range(min(5,sp['commute_frequency']['value'])));leave=480;back=960
 elif actor['employment'] in WORKING:
  workdays=list(range(5));leave=420;back=930
 else:workdays=[];leave=480;back=930
 actor_away=[];home_people=[]
 for d in range(7):
  away=[leave,back] if d in workdays else []
  if not daymask[d] and not away:away=[480,930]
  actor_away.append(away)
  if daymask[d]:
   choices=[m for m in adults if m is not actor] if away else [actor]+[m for m in adults if m is not actor]
   if d<5 and c['source']['dataset']=='ENASIC2022':
    allowed=[]
    for m in choices:
     details=c.get('source_member_details',{}).get(m.get('source_person_key'),{})
     a=details.get('commute_hours_roundtrip',{}).get('value');b=details.get('commute_minutes_roundtrip',{}).get('value')
     if m['employment'] not in WORKING or (a in (None,0) and b in (None,0)):allowed.append(m)
    choices=allowed
   if not choices:
    if p.get('calendar.home_day_count',{}).get('status')=='benchmark_assigned' and c['source']['dataset']=='ENASIC2022':
     daymask[d]=False;home_people.append([]);continue
    if role not in 'AF' and actor['employment'] in WORKING and sp['teleworking_household']['value'] is not False:
     away=[];actor_away[-1]=[];choices=[actor]
    elif p.get('calendar.home_day_count',{}).get('status')=='benchmark_assigned':
     daymask[d]=False;home_people.append([]);continue
    else:raise ValueError('daytime_presence_needs_another_member')
   choices.sort(key=lambda m:(m['employment'] in WORKING,m['id']))
   helper=choices[0]
   if helper['employment'] in WORKING and d in workdays and (helper is not actor or not away):
    helper['work_mode']='hybrid';provenance(p,f"members.{helper['id']}.work_mode",'benchmark_assigned',reason='remote days assigned to satisfy observed household presence; source is not person-specific')
   home_people.append([helper['id']])
  else:home_people.append([])
 if role=='E':
  assert actor['employment']=='home_caregiver'
  daymask=[True]*7;home_people=[[actor['id']] for _ in range(7)];actor_away=[[] for _ in range(7)]
 # No measured house-level telework=False may be overridden by a new remote worker.
 if sp['teleworking_household']['value'] is False:
  for m in members:
   if m['work_mode']=='hybrid':
    if m is respondent:raise ValueError('source_no_telework_conflict')
    # The source says no member teleworks, so use a non-employed co-resident instead.
    if m['employment'] in WORKING:raise ValueError('source_no_telework_conflict')
 if role=='B':
  # B actor is the comfort beneficiary: do not place that person at an office all day.
  if actor['employment'] in WORKING and not(sp.get('commute_frequency',{}).get('value',0) or 0):
   if sp['teleworking_household']['value'] is False:raise ValueError('B_no_home_actor')
   actor['work_mode']='home_based';actor_away=[[] for _ in range(7)]
   provenance(p,f"members.{actor['id']}.work_mode",'benchmark_assigned',reason='home-based B role compatible with available employment evidence')
  elif actor['employment'] not in WORKING:actor_away=[[] for _ in range(7)]
 if role=='B':
  for d in range(5):
   if daymask[d] and not actor_away[d] and actor['id'] not in home_people[d]:home_people[d].append(actor['id'])
 provenance(p,'calendar.actor_away_intervals','benchmark_assigned',reason='reference routine; not a reconstruction of observed exact departure times')
 return {'daytime_home':daymask,'overnight_home':nightmask,'daytime_home_member_ids':home_people,'actor_away_intervals':actor_away,'actor_workdays':workdays,'daytime_definition':'most/all of normal daytime, not continuous 24-hour occupancy','timezone':'local_clock'}


def complete(c):
 p={};members,actor,respondent=roster(c,p);eq=equipment(c,p);cal=calendar(c,members,actor,respondent,p);role=c['benchmark_role']
 care=[]
 for child in members:
  if child['age_band'][1]<6 or (child['age_band'][0]<12 and not child['school_enrolled']):
   carers=[m for m in members if m['age_band'][0]>=18 and m['employment'] not in WORKING]
   if role=='E':carer=actor
   elif carers:carer=carers[0]
   else:
    carers=[m for m in members if m['age_band'][0]>=18 and (c.get('source_member_details',{}).get(m.get('source_person_key'),{}).get('commute_hours_roundtrip',{}).get('value') in (None,0) and c.get('source_member_details',{}).get(m.get('source_person_key'),{}).get('commute_minutes_roundtrip',{}).get('value') in (None,0))]
    assert carers,'no source-compatible home carer'
    carer=carers[0];carer['work_mode']='home_based';provenance(p,f"members.{carer['id']}.work_mode",'benchmark_assigned',reason='home-based reference work arrangement to maintain infant supervision')
   if carer is actor:
    cal['actor_away_intervals']=[[] for _ in range(7)]
   care.append({'child_id':child['id'],'caregiver_id':carer['id'],'daytime_setting':'preschool' if child['school_enrolled'] else 'home','home_care_must_have_adult':True})
   provenance(p,'care.'+child['id'],'benchmark_assigned',reason='reference childcare logistics; observed enrollment and source care link retained separately')
   if child['age_band'][1]<6 or not child['school_enrolled']:
    cal['daytime_home']=[True]*7
    for d in range(7):
     if carer['id'] not in cal['daytime_home_member_ids'][d]:cal['daytime_home_member_ids'][d].append(carer['id'])
 # Existing E relation is preserved even if the cared-for child is older than five.
 if role=='E':
  childkey=c['care_context']['value']['child_key'];ch=next(m for m in members if m.get('source_person_key')==childkey)
  if not any(x['child_id']==ch['id'] and x['caregiver_id']==actor['id'] for x in care):care.append({'child_id':ch['id'],'caregiver_id':actor['id'],'daytime_setting':'school' if ch['school_enrolled'] else 'home','source_care_link':True})
 daily=[]
 for d in range(7):
  away=cal['actor_away_intervals'][d]
  if role in 'CD' and d<5:preferred=c['routine']['weekday_activity_start_minutes'][d]
  else:preferred=max(1080,(away[1]+30) if away else 1080)
  if away and preferred<away[1]:raise ValueError('activity_before_actor_return')
  shower=min(1350,max(1200,preferred+45));breakfast=max(330,min(480,(away[0]-30) if away else 450))
  daily.append({'day':d,'breakfast_minutes':breakfast,'lunch_minutes':750,'lunch_at_home':cal['daytime_home'][d],'dinner_minutes':max(1080,(away[1]+30) if away else 1110),'flexible_chore_window':[preferred,min(1410,preferred+120)],'shower_window':[max(1080,shower-30),min(1410,shower+30)]})
 provenance(p,'routine.daily_services','benchmark_assigned',reason='coherent reference meal, bathing and whole-cycle chore needs; these are not appliance on/off schedules')
 cycles=3
 if c['source']['dataset']=='IRES2020':
  value=c.get('source_laundry_weekly_uses',{}).get('value') or c.get('source_laundry_cycles_per_week') or -1
  if 1<=value<=21:cycles=value;provenance(p,'routine.laundry_cycles_per_week','observed',['q473_wash_mach_week_use_no'])
 if 'routine.laundry_cycles_per_week' not in p:provenance(p,'routine.laundry_cycles_per_week','benchmark_assigned',reason='three whole-cycle laundry needs per reference week')
 ev={}
 if eq['home_vehicle_charging']['present']:
  charger=c['source_person'].get('charger_type',sources.obs(None,[],'unknown'))
  matched_charger=c.get('reference_equipment',{}).get('charger_type')
  typ=charger['value'] or matched_charger or 'Level_2';power=1.44 if typ=='Level_1' else pick([3.6,7.2],c['case_id'],'charger')
  cap=pick([50,60,75],c['case_id'],'battery');arrival=pick([0.4,0.5,0.6],c['case_id'],'soc');target=0.8
  day=next((d for d in range(7) if cal['actor_away_intervals'][d]),None)
  away=cal['actor_away_intervals'][day] if day is not None else [480,480]
  window=(1440-away[1]+away[0])/60
  feasible_soc=[v for v in [0.4,0.5,0.6,0.7] if (target-v)*cap/(power*0.9)<=window]
  assert feasible_soc,'EV reference parameters cannot satisfy parking window'
  arrival=pick(feasible_soc,c['case_id'],'joint-soc')
  ev={'reference_powertrain':'battery_electric','charger_type':typ,'reference_charger_kw':power,'reference_battery_kwh':cap,'arrival_soc':arrival,'departure_soc_target':target,'charge_efficiency':0.9,'home_arrival_minutes':away[1],'next_departure_minutes':away[0],'parking_window_hours':window,'minimum_continuous_charge_hours':round((target-arrival)*cap/(power*0.9),4),'commute_use':'work_commute_experiment' if role=='F' else 'personal_mobility_experiment','charging_contiguity':'one_continuous_session_is_required_for_base_need'}
  assert ev['minimum_continuous_charge_hours']<=window,'EV charge infeasible'
  provenance(p,'ev','benchmark_assigned',reason='reference EV and service requirement; measured home charging retained; actual battery, powertrain and commute are not inferred')
  provenance(p,'ev.charger_type',charger['status'] if charger['value'] else 'reference_matched' if matched_charger else 'benchmark_assigned',charger.get('fields',()),'published charger class if available; otherwise Level2 reference, not observed')
 if role=='E':care_windows=c['routine']['care_protection_windows_minutes']
 else:care_windows=[]
 comfort={'preferred_cooling_c':[24,25] if role=='B' else [24,26], 'allowed_short_adjustment_c':{'A':1,'B':0.5,'C':1,'D':2,'E':0.5,'F':1}[role], 'comfort_ceiling_c':26} if eq['space_ac_available']['present'] else {}
 provenance(p,'comfort','benchmark_assigned',reason='original EB role-compatible reference comfort bounds, not inferred measured preferences')
 member_away={}
 for m in members:
  week=[]
  for d in range(7):
   if m['id']==actor['id']:away=cal['actor_away_intervals'][d]
   elif m['id'] in cal['daytime_home_member_ids'][d]:away=[]
   elif m['school_enrolled'] and d<5:
    if m['age_band'][1]<6:
     hours=c.get('source_member_details',{}).get(m.get('source_person_key'),{}).get('nursery_hours',{}).get('value')
     hours=hours if isinstance(hours,int) and 1<=hours<=12 else 4
     away=[480,480+hours*60]
    else:away=[450,1050]
   elif m['employment'] in WORKING and d<5:away=[450,1020]
   elif not cal['daytime_home'][d]:away=[480,930]
   else:away=[]
   week.append(away)
  member_away[m['id']]=week
  provenance(p,f"calendar.member_away_intervals.{m['id']}",'benchmark_assigned',reason='source-compatible reference work, study, care and personal outings; not observed exact times')
 for m in members:
  if m['age_band'][0]>=18 or not m['school_enrolled'] or m['age_band'][1]<6:continue
  for d in range(5):
   adults_away=[member_away[a['id']][d] for a in members if a['age_band'][0]>=18]
   start=min(480,max((a[0] for a in adults_away if a),default=480))
   end=960 if any(not a for a in adults_away) else max(960,min(a[1] for a in adults_away))
   member_away[m['id']][d]=[start,end]
  provenance(p,f"calendar.member_away_intervals.{m['id']}",'benchmark_assigned',reason='reference school and supervised before/after-school provision, ending when an adult can be home; not observed institutional hours')
 cal['member_away_intervals']=member_away
 cal['overnight_home_member_ids']=[[m['id'] for m in members] if home else [] for home in cal['overnight_home']]
 provenance(p,'calendar.overnight_home_member_ids','benchmark_assigned',reason='reference member allocation preserving measured household night count')
 h={'comfort':comfort,'country':c['source']['country'],'members':members,'decision_maker_id':actor['id'],'source_respondent_member_id':respondent['id'],'dwelling':dwelling(c,p),'equipment':eq,'calendar':cal,'routine':{'daily_services':daily,'laundry_cycles_per_week':cycles,'laundry_must_complete_whole_cycles':True,'care_protection_windows':care_windows},'care_arrangements':care,'ev':ev,'attitudes':deepcopy(c['attitudes']['value']),'role_id':c['role_card_id'],'role_name':c['card']['core'],'medical_service_must_not_be_interrupted':c['source_person'].get('medical_device',{}).get('value') is True}
 medical=c['source_person'].get('medical_device',sources.obs(None,[],'unknown'))
 provenance(p,'medical_service_must_not_be_interrupted',medical['status'] if medical['value'] is not None else 'benchmark_assigned_absence',medical.get('fields',()),'known medical service preserved; no unmeasured medical equipment added to the reference case')
 provenance(p,'attitudes','benchmark_assigned',reason='original EnergyBridge role condition; no observed acceptance label')
 provenance(p,'routine.care_protection_windows','benchmark_assigned',reason='reference service protection windows, not observed care times')
 c['household']=h;c['household_provenance']=p;c['benchmark_view']='household';c['schema_version']='household_step1_v3';return c


def card(c):
 h=c['household'];p=c['household_provenance'];lines=[f"## {c['case_id']} · {c['benchmark_role']}类",f"来源：{c['source']['country']} / {c['source']['dataset']} / 原户键{c['source']['household_key']}。",f"本实验家庭：{len(h['members'])}人，{h['dwelling']['type']}，参考面积{h['dwelling']['reference_area_m2']}㎡ [{p['dwelling.reference_area_m2']['status']}]。"]
 job={'employed_full_time':'全职工作','employed_part_time':'兼职工作','employed':'工作','retired':'退休','not_employed':'未就业','home_caregiver':'家务/照护','home_based_activity':'居家活动','not_in_workforce':'未进入劳动力市场','student':'学生','unable_to_work':'不能工作'}
 for m in h['members']:
  age=str(m['observed_age'])+'岁' if 'observed_age' in m else (str(m['age_band'][0])+'岁及以上' if m['age_band'][1]>=120 else str(m['age_band'][0])+'–'+str(m['age_band'][1])+'岁')
  lines.append(f"成员{m['id']}：{age}；{job.get(m['employment'],m['employment'])} [{p['members.'+m['id']+'.employment']['status']}]；在校={m['school_enrolled']}；{'本次角色承担者' if m['id']==h['decision_maker_id'] else '同住成员'}。")
 lines.append('实验角色：'+h['role_name']+'；'+{'A':'省钱收益明确、晚间生活可靠才愿意合作','B':'舒适高于省钱，只考虑几乎不影响体感与生活节奏的调整','C':'先解释、可撤回，不取消必要任务，不假定每天日程一致','D':'支持电网响应和有边界的自动化，必要任务仍须完成','E':'照护、安全和舒适高于省电，尽量保持原安排','F':'关注电价并允许适度优化，优先保障次日出行电量'}[c['benchmark_role']]+'。')
 equipped=[]
 for k,v in h['equipment'].items():
  if v['present']:equipped.append(NAMES[k]+' ['+p['equipment.'+k+'.present']['status']+']'+('，'+v['energy_carrier'] if k=='water_heater_available' else ''))
 if h['comfort']:lines.append('实验空调偏好：'+str(h['comfort']['preferred_cooling_c'])+'℃，短时调整不超过'+str(h['comfort']['allowed_short_adjustment_c'])+'℃。')
 lines.append('配置设备：'+'；'.join(equipped)+'。')
 absent=[NAMES[k] for k,v in h['equipment'].items() if not v['present'] and p['equipment.'+k+'.present']['status']=='benchmark_assigned_absence']
 if absent:lines.append('实验最小配置不纳入：'+'、'.join(absent)+'。这些设备的原调查状态仍保留在来源层，不认定原家庭实际没有。')
 lines.append('一周日间有人在家：'+','.join('周'+str(d+1) for d,v in enumerate(h['calendar']['daytime_home']) if v)+'。具体日期由实验指定，已测量的天数保持。')
 away=h['calendar']['actor_away_intervals'];d=next((d for d in range(7) if away[d]),None)
 if d is not None:lines.append('角色外出日示例：'+hhmm(away[d][0])+'出门，'+hhmm(away[d][1])+'返回 [实验设定]。')
 lines.append('周一至周五家务需求窗口：'+'；'.join(hhmm(x['flexible_chore_window'][0])+'–'+hhmm(x['flexible_chore_window'][1]) for x in h['routine']['daily_services'][:5])+' [实验设定]。')
 lines.append('每周洗衣需求'+str(h['routine']['laundry_cycles_per_week'])+'次，须完整完成周期；每日洗澡需求采用给定窗口 [实验设定，洗衣频率若来自IRES则另有观测标记]。')
 if h['care_arrangements']:lines.append('照护安排：'+json.dumps(h['care_arrangements'],ensure_ascii=False)+'；保护窗口 '+str(h['routine']['care_protection_windows'])+' [具体窗口为实验设定]。')
 if h['ev']:lines.append('电动车情境：'+str(h['ev']['reference_battery_kwh'])+'kWh参考电池，'+str(h['ev']['reference_charger_kw'])+'kW参考充电，SOC '+str(h['ev']['arrival_soc'])+'→'+str(h['ev']['departure_soc_target'])+'；最少连续充电'+str(h['ev']['minimum_continuous_charge_hours'])+'小时，可用'+str(h['ev']['parking_window_hours'])+'小时 [实验参数]。在职和居家充电来自同户调查，真实通勤用途未被观测。')
 lines.append('证据边界：原调查事实、调查填补、参考匹配及实验补全逐字段保留；本卡的具体作息和态度用于角色扮演，不是该家庭的实测偏好。')
 text='\n\n'.join(lines)+'\n\n'
 for a,b in {'benchmark_assigned_absence':'实验最小配置','benchmark_assigned':'实验补全','survey_imputed':'调查方填补','reference_matched':'跨源匹配','observed':'调查记录','derived':'来源派生','employed_full_time':'全职工作','employed_part_time':'兼职工作','non_electric':'非电力热源','electricity':'电力'}.items():text=text.replace(a,b)
 return text


