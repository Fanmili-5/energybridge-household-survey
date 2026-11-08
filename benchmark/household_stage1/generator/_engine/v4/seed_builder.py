"""Source-anchored household generation, limited to benchmark step one."""
from collections import Counter, defaultdict
from copy import deepcopy
import csv, hashlib, json, sys, re
from pathlib import Path
import source_adapters as src

ROOT = Path(__file__).resolve().parent
SEED = 'EB-stage1-20261107-v2'
src.SEED = SEED
QUOTAS = {'A':166,'B':198,'C':125,'D':151,'E':156,'F':204}
ROLE_NAMES = dict(src.ROLE_NAMES)
SOURCE_ROW_COUNTS = {}
RECS = ROOT.parent/'public_sources/recs2020/recs2020_public_v7.csv'
FILES = dict(src.FILES, RECS2020_v7=RECS, RECS2020_codebook=RECS.with_name('codebook_v7.xlsx'))
FACT = src.fact
COUNTRY_ALLOCATION = {'ES':{'A':166,'B':20,'C':10,'D':10}, 'GB':{'C':20,'D':20},
                      'US':{'B':178,'C':45,'D':71,'F':204}, 'IN':{'C':40,'D':40}, 'MX':{'C':10,'D':10,'E':156}}
SOURCES = {
 'ENABLE_EU': {'country':'ES','survey_year':None,'release':'2019-10-31, version 1.0','period_note':'Fieldwork dates not inferred from release year','url':'https://zenodo.org/records/3523916','geographic_scope':'Spain survey sample; not a national probability estimate in this benchmark'},
 'IDEAL': {'country':'GB','survey_year':None,'period':'2016-2018','release':'2018 metadata snapshot','url':'https://www.research.ed.ac.uk/en/datasets/ideal-household-energy-dataset/','geographic_scope':'Scottish study homes, not a representative UK sample'},
 'RECS2020_v7': {'country':'US','survey_year':2020,'release':'v7, January 2024','url':'https://www.eia.gov/consumption/residential/data/2020/index.php?view=microdata','geographic_scope':'US occupied primary housing units; benchmark selection is unweighted'},
 'IRES2020': {'country':'IN','survey_year':None,'period':'2019-2020; actual year retained per household','release':'IRES public household file','url':'https://doi.org/10.7910/DVN/U8NYUP','geographic_scope':'IRES covered Indian states; selected appliance-owning households'},
 'ENASIC2022': {'country':'MX','survey_year':2022,'release':'ENASIC 2022 public microdata','url':'https://www.inegi.org.mx/programas/enasic/2022/','geographic_scope':'Mexico care survey; selected co-resident adult-child care households'},
 'ENIGH2024': {'country':'MX','survey_year':2024,'release':'ENIGH 2024 public microdata','url':'https://www.inegi.org.mx/programas/enigh/nc/2024/','geographic_scope':'Reference-dwelling donors only; not the care household'},
}
ROLE_SPECS = {
 'A': {'core':'价格敏感、务实合作的通勤者','routine':'commuting','price_priority':'high','comfort_priority':'protect_evening_service','automation':'conditional','grid_motive':'insufficient_alone','thermal_rule':'若有空调，短时调整应保护归家舒适，最好不超过26°C'},
 'B': {'core':'经常有人在家、以温度舒适为前提','routine':'daytime_home_presence','price_priority':'secondary_to_comfort','comfort_priority':'very_high','automation':'only_if_barely_noticeable','grid_motive':'secondary','thermal_rule':'空调偏好24–25°C，25.5–26°C附近开始明显不适'},
 'C': {'core':'日常安排变化、谨慎对待自动控制','routine':'variable','price_priority':'conditional','comfort_priority':'protect_required_service','automation':'explain_and_allow_reversal','grid_motive':'conditional','thermal_rule':'若有空调，可协商小幅调整；必要任务不可取消'},
 'D': {'core':'日常安排稳定、支持响应且较信任自动化','routine':'stable','price_priority':'conditional','comfort_priority':'protect_required_service','automation':'allow_bounded_automation','grid_motive':'high','thermal_rule':'若有空调，可协商1–2°C短时变化；必要任务仍需完成'},
 'E': {'core':'同住照护者，以照护、安全和舒适为首要','routine':'protect_care','price_priority':'below_care_safety_comfort','comfort_priority':'very_high','automation':'minimal_disruption','grid_motive':'below_care','thermal_rule':'若有空调，只接受几乎不影响照护舒适的变化'},
 'F': {'core':'电动车通勤情境，优先保障次日出行','routine':'ev_commuting_scenario','price_priority':'high','comfort_priority':'protect_service_and_trip','automation':'conditional_optimization','grid_motive':'conditional','thermal_rule':'若有空调，可协商适度调整；不得损害出行或必要服务'},
}


def key(row): return row['source']['dataset'], row['source']['household_key']
def rank(*values): return hashlib.sha256(json.dumps([SEED,*values],ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
def choose(values,*salt): return values[int(rank(*salt),16)%len(values)]
def read_csv(path):
 with Path(path).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def num(x):
 try:return int(float(x))
 except (ValueError,TypeError):return -1

def coded(raw,field,yes={'1'},no={'0'},flag=None,**extra):
 val=True if raw.get(field) in yes else False if raw.get(field) in no else None
 status='unknown' if val is None else 'survey_imputed' if flag and raw.get(flag)!='0' else 'observed'
 return FACT(val,[field]+([flag] if flag else []),status,**extra)

def independent_devices(row):
 washer_asset=row['devices']['washer_available'].get('appliance_key')
 count=0
 for name,f in {**row['devices'],**row.get('additional_devices',{})}.items():
  if f['value'] is True and f['status']=='observed':
   if name!='washer_available' and washer_asset and f.get('appliance_key')==washer_asset:continue
   count+=1
 return count

def load_recs():
 out=[]
 raw_rows=read_csv(RECS)
 SOURCE_ROW_COUNTS['RECS2020_v7']=len(raw_rows)
 for r in raw_rows:
  n=num(r['NHSLDMEM']); area=num(r['TOTSQFT_EN'])
  if not (1<=n<7 and r['TYPEHUQ'] in src.US_TYPE and 200<=area<=15000 and r['CWASHER']=='1'
          and r['ZCWASHER']=='0' and r['ZTYPEHUQ']=='0'):continue
  status='survey_imputed' if r['ZNHSLDMEM']!='0' else 'observed'
  row=src.ref('RECS2020_v7',r['DOEID'],'US',FACT(n,['NHSLDMEM','ZNHSLDMEM'],status,topcoded_at=7,selected_below_topcode=True),
       FACT(src.US_TYPE[r['TYPEHUQ']],['TYPEHUQ','ZTYPEHUQ']),
       FACT(round(area*0.09290304,2),['TOTSQFT_EN'],'derived',measure='energy_consuming_dwelling_area_m2',source_sqft=area,source_measure='includes energy-consuming basements and finished spaces; not net residential floor area'),
       FACT(True,['CWASHER','ZCWASHER']),anchors={})
  for slot,field in [('dryer_available','DRYER'),('dishwasher_available','DISHWASH'),('space_ac_available','AIRCOND')]:
   row['devices'][slot]=coded(r,field,flag='Z'+field)
  row['devices']['home_vehicle_charging']=coded(r,'EVCHRGHOME')
  fuel=r.get('FUELH2O'); fflag=r.get('ZFUELH2O')
  if fuel in {'1','2','3','5','7','8','99'}:
   row['devices']['water_heater_available']=FACT(True,['FUELH2O','ZFUELH2O'],'survey_imputed' if fflag!='0' else 'observed',
      energy_carrier='electricity' if fuel=='5' else 'non_electric' if fuel in {'1','2','3','7','8'} else 'unknown',source_fuel_code=fuel)
  row['additional_devices']={}
  if num(r.get('NUMFRIG'))>0:
   row['additional_devices']['fridge_available']=FACT(True,['NUMFRIG','ZNUMFRIG'],'survey_imputed' if r.get('ZNUMFRIG')!='0' else 'observed')
  groups=[]
  for field,label in [('NUMCHILD','age_0_17_topcoded_4'),('NUMADULT1','age_18_64'),('NUMADULT2','age_65_plus')]:
   v=num(r.get(field)); groups.append({'label':label,**FACT(v,[field,'Z'+field],'survey_imputed' if r.get('Z'+field)!='0' else 'observed')})
  if sum(g['value'] for g in groups)!=n or any(g['value']<0 for g in groups):continue
  row['members_summary']=FACT(groups,[g['fields'][0] for g in groups],'derived',scope='published_age_groups',exact_ages_known=False,child_count_topcoded_at=4)
  row['known_presence']=FACT({'someone_home_weekdays':num(r['ATHOME'])},['ATHOME','ZATHOME'],'survey_imputed' if r['ZATHOME']!='0' else 'observed',scope='at_least_one_member_not_an_identified_person')
  row['block']=['US',r['REGIONC'],row['dwelling']['observed_type']['value'],n,int(row['dwelling']['size']['value']//25)]
  if r['ATHOME']=='5' and r['ZATHOME']=='0' and row['devices']['space_ac_available']['value'] is True and row['devices']['space_ac_available']['status']=='observed':
   row['anchors']['B']=FACT({'someone_home_weekdays':5},['ATHOME','ZATHOME'])
  if r['EVCHRGHOME']=='1':row['anchors']['F']=FACT({'vehicle_charged_at_home':True},['EVCHRGHOME'])
  row['geography']=FACT(r['REGIONC'],['REGIONC'],scope='US_census_region')
  out.append(row)
 return out

def load_candidates():
 pools={}
 pools['US']=load_recs()
 india=src.india_candidates(); ir={r['hhid']:r for r in src.load_csv('IRES2020','\t')}
 SOURCE_ROW_COUNTS['IRES2020']=len(ir)
 for row in india:
  r=ir[key(row)[1]];gs=[]
  for f,label in [('q214_no_members_lessthan18','under18'),('q214_no_members_18_40','age18_40'),('q214_no_members_41_60','age41_60'),('q214_no_members_morethan60','over60')]:
   gs.append({'label':label,**FACT(num(r[f]),[f])})
  row['members_summary']=FACT(gs,[g['fields'][0] for g in gs],'derived',scope='source_age_bins')
  row['devices']['space_ac_available']=coded(r,'q427_ac_yn')
  row['geography']=FACT(r['state_abbv'],['state_abbv'],scope='Indian_state')
  row['source']['survey_date_raw']=r['interview_date']
  years=re.findall(r'(?:2019|2020)',r['interview_date'])
  row['source']['observed_survey_year']=int(years[0]) if len(years)==1 else None
  row['known_presence']=FACT(None,[],'unknown',scope='member_presence')
  row['block']=['IN',*row['block']]
 pools['IN']=[r for r in india if r['devices']['space_ac_available']['value'] is True and sum(g['value'] for g in r['members_summary']['value'])==r['household_size']['value'] and all(g['value']>=0 for g in r['members_summary']['value'])]
 mexico=src.mexico_candidates(); people=defaultdict(list)
 with src.zip_rows('ENASIC2022','THOGAR.csv') as records:
  home_records={r['LLAVEHOG']:r for r in records}
 homes_per_dwelling=Counter(r['LLAVEVIV'] for r in home_records.values())
 SOURCE_ROW_COUNTS['ENASIC2022_households']=len(home_records)
 SOURCE_ROW_COUNTS['ENASIC_preliminary_care_and_housing_match_candidates']=len(mexico)
 with src.zip_rows('ENASIC2022','TCSDEMPO.csv') as records:
  for r in records:people[r['LLAVEHOG']].append(r)
 for row in mexico:
  pp=people[key(row)[1]]; roster=[{'person_key':r['LLAVESDE'],'age':FACT(num(r['EDAD']),['TCSDEMPO.EDAD'],topcoded_at=98)} for r in pp]
  row['dwelling']['source_households_in_dwelling']=FACT(homes_per_dwelling[home_records[key(row)[1]]['LLAVEVIV']],['THOGAR.LLAVEVIV'],'derived')
  row['members_summary']=FACT(roster,['TCSDEMPO.LLAVESDE','TCSDEMPO.EDAD'],'derived',scope='source_person_roster',topcode_note='98 denotes source age ceiling; retain as censored boundary')
  row['geography']=FACT(None,[],'unknown',scope='subnational_location')
  row['known_presence']=FACT(None,[],'unknown',scope='member_presence')
  ref=row['dwelling']['reference_type'];counts=ref['type_counts']; supported={k:v for k,v in counts.items() if v>=5}
  ref['selection_rule']='deterministic unweighted donor selection; coverage design, not population imputation'
  ref['alternative_types']=[{'type':k,'donor_count':v} for k,v in sorted(supported.items())]
  ref['unmatched_dimensions']=['subnational_geography','climate','floor_area','construction','survey_year_2022_vs_2024']
  ref['uncertainty']='conditional reference only; target household actual type remains unknown'
  row['block']=['MX',ref['value'],row['household_size']['value'],row['dwelling']['size']['value']]
 pools['MX']=[r for r in mexico if r['dwelling']['source_households_in_dwelling']['value']==1 and r['devices']['space_ac_available']['value'] is True and all(0<=m['age']['value']<=98 for m in r['members_summary']['value'])]
 for country,rows in pools.items():
  for r in rows:
   source=SOURCES[r['source']['dataset']]
   r['source'].update(survey_year=r['source'].get('observed_survey_year',source['survey_year']),release=source['release'],catalogue_id=r['source']['dataset'])
   r['source']['survey_reference_year']=2020 if r['source']['dataset']=='IRES2020' else source['survey_year']
   r['source']['fieldwork_year']=r['source'].get('observed_survey_year')
   r['source']['survey_year_semantics']='observed_fieldwork_year' if r['source']['dataset']=='IRES2020' else 'survey_reference_year'
   r.setdefault('additional_devices',{})
  pools[country]=[r for r in rows if independent_devices(r)>=2]
 return pools


def routine(role,identity,anchor,pair=None):
 """Activity preferences are not appliance start commands or whole-home vacancy."""
 salt=pair or identity
 base=choose(list(range(17*60,21*60+31,15)),'routine-base',salt)
 if role=='C':
  offsets=sorted([-60,-30,0,30,60],key=lambda o:rank('weekday-order',salt,o))
  times=[base+o for o in offsets]
 elif role=='D':times=[base]*5
 else:times=None
 out={'scope':'preferred_start_of_flexible_household_activities','status':'benchmark_assigned','not_occupancy_measurement':True,'conditional_on_activity_needed_and_resident_available':True,'weekday_activity_start_minutes':times,'weekend_activity_start_minutes':None}
 if role in 'CD':
  out['template_id']=hashlib.sha256(json.dumps([role,times]).encode()).hexdigest()[:16]
  out['mean_weekday_minutes']=base
 if role in 'AF':
  depart=choose(list(range(7*60,9*60+1,15)),'depart',identity)
  back=choose(list(range(17*60,20*60+1,15)),'return',identity)
  days=anchor['value']['days_to_work_or_study'] if role=='A' else 5
  chosen=sorted(range(5),key=lambda d:rank('commute-weekday',identity,d))[:min(days,5)]
  if days>5:chosen+=sorted([5,6],key=lambda d:rank('commute-weekend',identity,d))[:days-5]
  out['personal_commute_scenario']={'depart_minutes':depart,'return_minutes':back,'day_indices':sorted(chosen),'days_per_week':days,'timing_status':'benchmark_assigned','frequency_status':anchor['status'] if role=='A' else 'benchmark_assigned','day_selection_rule':'weekdays_first_experimental_assignment','household_other_member_presence':'unknown'}
 if role=='E':
  # These define preferred protection blocks only, not observed care times.
  shift=choose([-30,-15,0,15,30],'care-window',identity)
  out['care_protection_windows_minutes']=[[420+shift,540+shift],[1080+shift,1260+shift]]
  out['care_window_status']='benchmark_assigned'
 return out


def effective_card(case):
 role=case['benchmark_role'];sp=ROLE_SPECS[role];devices=case['devices']; core=sp['core']
 names={'washer_available':'洗衣机','dryer_available':'烘干功能','dishwasher_available':'洗碗机','space_ac_available':'空调','water_heater_available':'热水设备','home_vehicle_charging':'居家车辆充电'}
 confirmed=[names[k] for k,f in devices.items() if f['value'] is True]
 absent=[names[k] for k,f in devices.items() if f['value'] is False]
 unknown=[names[k] for k,f in devices.items() if f['value'] is None]
 clauses=[{'device':k,'text':names[k]+'的必要服务应受到保护'} for k,f in devices.items() if f['value'] is True]
 if devices['space_ac_available']['value'] is True:clauses.append({'device':'space_ac_available','text':sp['thermal_rule']})
 return {'language':'zh','core':core,'status':'benchmark_assigned','device_clauses':clauses,'confirmed_equipment':confirmed,'absent_equipment':absent,'unknown_equipment':unknown,'role_card_adaptation':'Original role motivations retained; equipment examples instantiated only when source supports equipment. Original numerical acceptance priors are not generated observations or labels.'}


def generate():
 pools=load_candidates();used=set();cases=[];logs=[];coverage={}
 for country,pool in pools.items():
  coverage[country]={'carrier_candidates':len(pool),'role_anchor_candidates':{r:sum(r in x['anchors'] for x in pool) for r in 'ABEF'}}
 def add(row,role,pair=None,block=None):
  ident=key(row);assert ident not in used;used.add(ident)
  x=deepcopy({k:v for k,v in row.items() if k not in ('anchors','block')})
  anchor=row['anchors'].get(role,FACT('variable_routine' if role=='C' else 'stable_routine',[],'benchmark_assigned'))
  x.update(case_id='EB2-'+role+'-'+rank(role,*ident)[:16],benchmark_role=role,role_card_id=ROLE_NAMES[role],role_status='benchmark_assigned',role_anchor=anchor)
  if x['source']['dataset']=='ENASIC2022':
   care=row['anchors']['E'];x['care_context']=deepcopy(care)
  else:x['care_context']=FACT(None,[],'unknown')
  x['attitudes']=FACT({k:v for k,v in ROLE_SPECS[role].items() if k not in ('core','routine','thermal_rule')},[],'benchmark_assigned',role_definition_source='original_EB_role_card')
  r=routine(role,list(ident),anchor,pair)
  conditions={}
  if role=='A':conditions={'preferences':'price_and_reliable_evening_service','role_subject':'survey_respondent_commuter','whole_house_daytime_absence':None}
  if role=='B':conditions={'daytime_comfort_priority':True,'presence_scope':'at_least_one_household_member','role_subject':'household_decision_maker_in_comfort_scenario'}
  if role in 'CD':conditions={'weekday_activity_start_minutes':r['weekday_activity_start_minutes'],'activity_scope':r['scope'],'flexibility':ROLE_SPECS[role]['automation'],'role_subject':'household_decision_maker','work_status':None}
  if role=='E':conditions={'protect_care_activities':True,'role_subject':anchor['value']['adult_caregiver_key'],'care_scope':'co_resident_child_care_only','care_time_windows':r['care_protection_windows_minutes']}
  if role=='F':conditions={'vehicle_use':'work_commute','charge_deadline':'next_morning_departure','observed_powertrain':None,'observed_commute_use':None,'role_subject':'EV_commuting_scenario_decision_maker'}
  x['conditions']=FACT(conditions,[],'benchmark_assigned');x['routine']=r
  if pair:x['cd_pair_id']=pair;x['matching_block']=list(block)
  x['evidence_scope']={'household_identity':'source_survey_household','role_and_attitudes':'controlled_experimental_assignment','routine_times':'controlled_experimental_assignment','population_weight':None,'source_survey_weights_used':False,'global_representativeness':False}
  x['family_constraints']={'required_services_must_be_preserved':True,'personal_schedule_does_not_imply_whole_house_vacancy':True,'unmeasured_member_work_school_times':None,'care_windows_observed':False,'role_definition_id':ROLE_NAMES[role]}
  x['card']=effective_card(x);cases.append(x)
 def sample(country,role,n,pred):
  pool=[r for r in pools[country] if key(r) not in used and pred(r)]
  assert len(pool)>=n,(country,role,len(pool),n)
  pool.sort(key=lambda r:rank('select',country,role,*key(r)))
  logs.append({'country':country,'role':role,'remaining_eligible':len(pool),'selected':n})
  for row in pool[:n]:add(row,role)
 # Reserve the rarer ES comfort anchors before selecting commuters.
 sample('ES','B',20,lambda r:'B' in r['anchors'] and 'A' not in r['anchors'] and r['devices']['space_ac_available']['value'] is True)
 sample('ES','A',166,lambda r:'A' in r['anchors'] and r['devices']['space_ac_available']['value'] is True)
 sample('US','F',204,lambda r:'F' in r['anchors'])
 sample('US','B',178,lambda r:'B' in r['anchors'])
 sample('MX','E',156,lambda r:'E' in r['anchors'] and r['source_person']['employment']['value']=='home_caregiver')
 for country,n in [('GB',20),('IN',40),('ES',10),('MX',10),('US',45)]:
  groups=defaultdict(list)
  for r in pools[country]:
   if key(r) in used or r['source']['dataset']=='RECS2024_v1':continue
   signature=tuple((r['devices'][f]['value'],r['devices'][f]['status']) for f in src.DEVICE_FIELDS)
   groups[(tuple(r['block']),signature)].append(r)
  pairs=[]
  for (block,sig),rs in groups.items():
   rs.sort(key=lambda r:rank('pair-order',*key(r)))
   pairs.extend((a,b,block) for a,b in zip(rs[::2],rs[1::2]))
  pairs.sort(key=lambda p:rank('pair-select',country,*key(p[0]),*key(p[1])))
  coverage[country]['available_cd_pairs_after_anchor_reservations']=len(pairs)
  assert len(pairs)>=n,(country,'pairs',len(pairs),n)
  for a,b,block in pairs[:n]:
   pid='CD2-'+country+'-'+rank(*key(a),*key(b))[:12]
   add(a,'C',pid,block);add(b,'D',pid,block)
 sample('US','D',26,lambda r:r['source']['dataset']=='RECS2020_v7')
 cases.sort(key=lambda c:(c['benchmark_role'],c['case_id']))
 return cases,{'raw_source_rows':dict(SOURCE_ROW_COUNTS),'candidate_pools':coverage,'selection_log':logs,'country_role_design':COUNTRY_ALLOCATION}


def validate(cases):
 assert len(cases)==1000 and Counter(c['benchmark_role'] for c in cases)==QUOTAS
 assert len({c['case_id'] for c in cases})==len({key(c) for c in cases})==1000
 assert {co:dict(Counter(c['benchmark_role'] for c in cases if c['source']['country']==co)) for co in COUNTRY_ALLOCATION}==COUNTRY_ALLOCATION
 pairs=defaultdict(list);invent=defaultdict(Counter)
 for c in cases:
  role=c['benchmark_role'];assert independent_devices(c)>=2
  assert c['role_card_id']==ROLE_NAMES[role] and c['role_status']=='benchmark_assigned'
  assert c['attitudes']['status']==c['conditions']['status']=='benchmark_assigned'
  assert c['source']['catalogue_id'] in SOURCES
  assert c['household_size']['value']>=1
  for device,f in c['devices'].items():
   assert f['status'] in ('observed','survey_imputed','derived','unknown')
   assert (f['value'] is None)==(f['status']=='unknown')
   invent[device][f['status']+'_'+str(f['value'])]+=1
  for clause in c['card']['device_clauses']:assert c['devices'][clause['device']]['value'] is True
  if role=='B':assert c['devices']['space_ac_available']['value'] is True and c['devices']['space_ac_available']['status']=='observed' and c['role_anchor']['status']=='observed'
  if role in 'CD':
   t=c['routine']['weekday_activity_start_minutes'];assert len(t)==5 and min(t)>=16*60 and max(t)<=22*60+30
   assert max(t)-min(t)>=90 if role=='C' else len(set(t))==1
  if 'cd_pair_id' in c:pairs[c['cd_pair_id']].append(c)
  if c['members_summary']['value'] is not None and c['members_summary']['scope']!='source_person_roster':
   assert sum(g['value'] for g in c['members_summary']['value'])==c['household_size']['value']
  if c['source']['dataset']=='ENASIC2022':assert c['dwelling']['observed_type']['value'] is None and c['dwelling']['reference_type']['status']=='reference_matched'
 assert len(pairs)==125
 for p in pairs.values():
  a,b=sorted(p,key=lambda c:c['benchmark_role']);assert a['benchmark_role']=='C' and b['benchmark_role']=='D'
  assert a['matching_block']==b['matching_block'] and a['routine']['mean_weekday_minutes']==b['routine']['mean_weekday_minutes']
  assert all(a['devices'][f]['value']==b['devices'][f]['value'] and a['devices'][f]['status']==b['devices'][f]['status'] for f in src.DEVICE_FIELDS)
 distinct={r:len({c['routine']['template_id'] for c in cases if c['benchmark_role']==r}) for r in 'CD'}
 assert min(distinct.values())>=12
 return {'count':len(cases),'role_quotas':QUOTAS,'country_role_counts':COUNTRY_ALLOCATION,'cd_pairs':len(pairs),'unpaired_D':26,'distinct_cd_routines':distinct,'minimum_observed_distinct_devices':min(map(independent_devices,cases)),'device_evidence_counts':{k:dict(v) for k,v in invent.items()},'role_equipment_conflicts':0}


def hhmm(m):return f'{m//60:02d}:{m%60:02d}'
def readable(c):
 s=c['source'];dw=c['dwelling'];ms=c['members_summary'];r=c['routine'];role=c['benchmark_role']
 groups='成员年龄与个人活动分工未知' if ms['value'] is None else '；'.join((f"{m['person_key']}: {m['age']['value']}岁（顶码边界98）" if 'person_key' in m else f"{m['label']}: {m['value']}人") for m in ms['value'])
 housing=dw['observed_type']['value'] or '实测房型未知；参考房型 '+dw['reference_type']['value']+'（来自另一调查家庭）'
 devices='；'.join(f"{k}={f['value']} [{f['status']}]" for k,f in c['devices'].items())
 text=f"## {c['case_id']} · {role}类\n\n真实调查信息：国家 {s['country']}；来源 {s['dataset']}，原户键 {s['household_key']}；{c['household_size']['value']}人 [{c['household_size']['status']}]。\n\n成员信息：{groups}。\n\n住房：{housing}；尺度 {dw['size']['value']}，测量范围 {dw['size']['measure']}。\n\n设备原始证据：{devices}。其他确认设备：{', '.join(c['additional_devices']) or '无额外记录'}。\n\n实验角色：{c['card']['core']}。态度和以下时间是实验设置。\n\n"
 if role in 'CD':text+='周一至周五偏好的可协商家务活动时刻（仅当天确有家务且成员可用时适用）：'+', '.join(hhmm(t) for t in r['weekday_activity_start_minutes'])+'。这不是出入家时间，也不是电器开关指令。\n\n'
 if role in 'AF':
  cm=r['personal_commute_scenario'];text+=f"实验通勤安排：出门 {hhmm(cm['depart_minutes'])}、归家 {hhmm(cm['return_minutes'])}，每周 {cm['days_per_week']}天。其他成员在家情况未知。\n\n"
 if role=='F':text+='来源只确认居家充电；车辆动力类型和真实通勤用途未知。实验指定电动车通勤与次日出发前完成充电，尚未指定物理充电参数。\n\n'
 if c['care_context']['value'] is not None:text+='实测照护关系：同住成人照护儿童。实际照护时间未知。\n\n'
 if role=='E':text+='实验保护时段：'+', '.join(hhmm(a)+'–'+hhmm(b) for a,b in r['care_protection_windows_minutes'])+'。\n\n'
 text+='实验态度约束：'+json.dumps(c['attitudes']['value'],ensure_ascii=False)+'。\n\n'
 text+='适用的设备条款：'+'；'.join(x['text'] for x in c['card']['device_clauses'])+'。\n\n'
 text+='未知项：'+', '.join(c['card']['unknown_equipment'])+'；未测量成员的工作/上学日程；未观测的偏好和真实接受率。\n\n'
 return text


