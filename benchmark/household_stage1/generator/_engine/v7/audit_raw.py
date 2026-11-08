"""Independent first-step source and semantic audit. Does not import the generator."""
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path
from zipfile import ZipFile
import csv, hashlib, io, json, sys, re
import pyreadstat
CURRENT=Path(__file__).resolve().parent
ROOT=CURRENT.parent/'v4'
BASE=ROOT.parent
ROLE_IDS={'A':'role_a_price_cooperative_commuter','B':'role_b_home_comfort_gated','C':'role_c_irregular_cautious','D':'role_d_ideal_dr_participant','E':'role_e_caregiver_low_dr','F':'role_f_ev_commuter_optimizer'}
QUOTAS={'A':166,'B':198,'C':125,'D':151,'E':156,'F':204}
DEVICE_NAMES=('washer_available','dryer_available','dishwasher_available','space_ac_available','water_heater_available','home_vehicle_charging')
ORIGINAL_ROLE_SHA='668003f34e6ba08580b308a5def98063a89531979e65ac54d71715665dbac662'


def require(ok,message):
 if not ok:raise ValueError(message)
def n(x):
 try:return int(float(x))
 except (TypeError,ValueError):return -1
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def csvrows(p):
 with Path(p).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def zrows(name,member):
 with ZipFile(BASE/'public_sources'/name) as z:
  with io.TextIOWrapper(z.open(member),encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def index(rows,k):return {r[k]:r for r in rows}
def binary(r,f,yes=('1',),no=('0',)):
 return True if r.get(f) in yes else False if r.get(f) in no else None


def original_sources():
 data,meta=pyreadstat.read_sav(ROOT/'inputs/enable.sav',output_format='dict')
 es={str(r['UID']):r for r in (dict(zip(data,v)) for v in zip(*data.values()))}
 recs=index(csvrows(BASE/'public_sources/recs2020/recs2020_public_v7.csv'),'DOEID')
 with (BASE/'public_sources/ires-data.tab').open(encoding='utf-8-sig',newline='') as f:india=index(list(csv.DictReader(f,delimiter='\t')),'hhid')
 mxhomes=index(zrows('mexico_enasic_2022/enasic.zip','THOGAR.csv'),'LLAVEHOG')
 mxhouses=index(zrows('mexico_enasic_2022/enasic.zip','TVIVIENDA.csv'),'LLAVEVIV')
 people=index(zrows('mexico_enasic_2022/enasic.zip','TCSDEMPO.csv'),'LLAVESDE');members=defaultdict(list)
 mx_dwelling_households=Counter(h['LLAVEVIV'] for h in mxhomes.values())
 for r in people.values():members[r['LLAVEHOG']].append(r)
 donorhouses=index(zrows('mexico_enigh_2024/viviendas.zip','viviendas.csv'),'folioviv')
 donorhomes={(r['folioviv'],r['foliohog']):r for r in zrows('mexico_enigh_2024/hogares.zip','hogares.csv')}
 donorcounts=defaultdict(Counter)
 for (d,h),r in donorhomes.items():
  house=donorhouses[d]
  if house['tot_hog']=='1' and house['tipo_viv'] in ('1','2') and n(r['num_lavad'])>0:
   donorcounts[(n(house['num_cuarto']),n(house['tot_resid']))]['detached_house' if house['tipo_viv']=='1' else 'apartment']+=1
 return locals()


def check_device(case,name,value,status=None):
 f=case['devices'][name]
 require(f['value'] is value,'source device value '+name)
 if status is not None:require(f['status']==status,'source device status '+name)



def load_sources():
 s=original_sources()
 data,meta=pyreadstat.read_dta(CURRENT/'inputs/CRECS2012.dta',output_format='dict')
 s['china']={str(int(v['index'])):v for v in (dict(zip(data,x)) for x in zip(*data.values()))}
 s['carejobs']=index(zrows('mexico_enasic_2022/enasic.zip','TPOB_CUI.csv'),'LLAVEMOD')
 return s

def check_china(c,s):
 import math
 r=s['china'][c['source']['household_key']];h=c['household']
 require(c['source']['country']=='CN' and c['source']['survey_year']==2012 and r['valid']==1 and r['b1']==1,'China identity/year/urban scope')
 require(c['household_size']['value']==int(r['a1'])==len(h['members']),'China source household size')
 bounds={1:(0,12),2:(12,30),3:(30,50),4:(50,70),5:(70,90),6:(90,120),7:(120,150),8:(150,180),9:(180,250),10:(250,None)}
 lo,hi=bounds[int(r['b13'])];area=c['dwelling']['size']
 require(area['code']==int(r['b13']) and area['value']=={'lower_m2':lo,'upper_m2':hi,'lower_inclusive':lo==0},'China area band incorrectly decoded')
 require(c['dwelling']['observed_type']['value'] is None and h['dwelling']['type']=='reference_apartment' and c['household_provenance']['dwelling.type']['status']=='benchmark_assigned','China height band passed off as observed housing form')
 require(lo<h['dwelling']['reference_area_m2'] and (hi is None or h['dwelling']['reference_area_m2']<=hi),'China reference area outside source interval')
 for m in h['members']:
  slot=int(m['source_person_key'].split(':')[-1]);birth=int(r[f'a2_{slot}_c'])
  require(m['source_birth_year']==birth and m['age_band']==[max(0,2011-birth),2012-birth] and 'observed_age' not in m,'China birth-year age fabricated or aged into current year')
  job={1:'employed_full_time',2:'employed_part_time',3:'not_employed',4:'retired'}.get(r[f'a2_{slot}_d'])
  if job:require(m['employment']==job,'China observed member employment overwritten')
  rawsex=r[f'a2_{slot}_b']
  if rawsex in (1,2):require(m.get('sex_from_source')==('male' if rawsex==1 else 'female'),'China observed sex overwritten')
 def finite(v):return v is not None and (not isinstance(v,float) or math.isfinite(v))
 wash=any(r[f'c3_{i}b'] in (1,2,3) for i in (1,2,3))
 dry=any(r[f'c4_{i}b'] in (1,2) or finite(r[f'c4_{i}a']) and r[f'c4_{i}a'] in range(1,12) for i in (1,2,3))
 ac=any(r[f'd6_{i}a'] in (2,3) for i in range(1,6));heater=any(r[f'd4_{i}a'] in (1,2,3) for i in range(1,6))
 for name,value in [('washer_available',True if wash else None),('dryer_available',True if dry else None),('space_ac_available',True if ac else None),('water_heater_available',True if heater else None),('dishwasher_available',None),('home_vehicle_charging',None)]:check_device(c,name,value,'unknown' if value is None else 'observed')
 combos=[i for i in (1,2,3) if r[f'c4_{i}b']==1]
 if combos:
  expected=f"CRECS2012:{c['source']['household_key']}:washer_dryer:{combos[0]}"
  require(c['devices']['washer_available'].get('appliance_key')==c['devices']['dryer_available'].get('appliance_key')==expected,'China observed washer-dryer combo split into independent source assets')
 if r['a3'] in (1,2):require(c['known_presence']['value']=={'normally_someone_home_all_day':r['a3']==1},'China all-day presence source rewritten')
 require(c['devices']['home_vehicle_charging']['status']=='unknown','historical China charging guessed as observed')

def check_individual_facts(c,s):
 h=c['household'];ds=c['source']['dataset'];respondent=next(m for m in h['members'] if m['id']==h['source_respondent_member_id'])
 if ds=='RECS2020_v7':
  r=s['recs'][c['source']['household_key']];expected={'1':'employed_full_time','2':'employed_part_time','3':'retired','4':'not_employed'}.get(r['EMPLOYHH'])
  require(c['source_person']['employment']['value']==expected,'US source respondent employment decoder')
  if expected:require(respondent['employment']==expected,'US observed respondent job overwritten')
 elif ds=='IRES2020':
  r=s['india'][c['source']['household_key']]
  require(respondent.get('observed_age')==n(r['q202_resp_age']),'India respondent age binding')
  require(sum(m['school_enrolled'] for m in h['members'])==n(r['q215_no_members_studying']),'India observed total student count altered')
 elif ds=='ENASIC2022':
  for m in h['members']:
   r=s['carejobs'].get(m.get('source_person_key'),{});primary=r.get('P5_6');side=r.get('P5_8')
   expected='employed' if primary in ('1','2') or side in ('1','2','3','4','5','6') else {'3':'not_employed','4':'retired','5':'student','6':'home_caregiver','7':'unable_to_work','8':'not_employed'}.get(primary)
   if expected:require(m['employment']==expected,'Mexico observed member job overwritten')
   raw=s['people'][m['source_person_key']];require(m.get('observed_age')==n(raw['EDAD']),'Mexico observed member age overwritten')

def audit_case(c,s):
 role=c['benchmark_role'];ds=c['source']['dataset'];k=c['source']['household_key'];count=c['household_size']['value'];dw=c['dwelling'];dev=c['devices']
 require(role in ROLE_IDS and c['role_card_id']==ROLE_IDS[role],'role identifier')
 require(c['role_status']==c['attitudes']['status']==c['conditions']['status']=='benchmark_assigned','assigned roles and attitudes')
 require(c['routine']['status']=='benchmark_assigned' and c['routine']['not_occupancy_measurement'] is True,'routine provenance')
 require(c['family_constraints']['personal_schedule_does_not_imply_whole_house_vacancy'] is True,'whole household occupancy inference')
 require(c['source']['catalogue_id']==ds and 'survey_year' in c['source'] and bool(c['source']['release']),'source release catalogue')
 require(not any(x in c for x in ('acceptance_label','observed_response','human_answer','population_acceptance_probability')),'outcome leaked into household step')
 require(set(dev)==set(DEVICE_NAMES),'device schema')
 distinct=0;washer=dev['washer_available'].get('appliance_key')
 for name,f in {**dev,**c['additional_devices']}.items():
  require((f['value'] is None)==(f['status']=='unknown'),'unknown has a value')
  require(f['status'] in ('unknown','observed','derived','survey_imputed'),'invalid device provenance')
  if f['status']=='observed' and f['value'] is True and not(name!='washer_available' and washer and f.get('appliance_key')==washer):distinct+=1
 for cl in c['card']['device_clauses']:require(dev[cl['device']]['value'] is True,'card claims unsupported equipment')
 require(c['evidence_scope']['global_representativeness'] is False and c['evidence_scope']['source_survey_weights_used'] is False,'unsupported population claim')
 if ds=='ENABLE_EU':
  r=s['es'].get(k);require(r is not None,'ES source key')
  require(c['source']['country'] in ('ES','GB') and s['meta'].variable_value_labels['Country'][r['Country']]=={'ES':'Spain','GB':'United Kingdom'}[c['source']['country']],'ENABLE source country')
  fields=[f'S1{sex}c{a}' for sex in 'AB' for a in (1,2,3)]
  require(count==sum(r[f] for f in fields),'ES member count')
  require([g['value'] for g in c['members_summary']['value']]==[int(r[f]) for f in fields],'ES member bins')
  require(dw['observed_type']['value']==s['meta'].variable_value_labels['H1'][r['H1']],'ES dwelling type')
  require(dw['size']['value']==s['meta'].variable_value_labels['H3'][r['H3']] and dw['size']['measure']=='dwelling_area_band','ES dwelling area band')
  require(r['H11C'] in (1,2,4),'ES washer');check_device(c,'washer_available',True,'observed')
  for slot,f in [('dishwasher_available','H11B'),('space_ac_available','H11E')]:
   v=binary(r,f,(1,2,4),(5,));check_device(c,slot,v,'unknown' if v is None else 'observed')
  check_device(c,'water_heater_available',True if r['H11G'] in (1,2,4) else None)
  check_device(c,'dryer_available',None);check_device(c,'home_vehicle_charging',None)
 elif ds=='RECS2020_v7':
  r=s['recs'].get(k);require(r is not None,'RECS source key');require(c['source']['country']=='US','RECS country')
  require(count==n(r['NHSLDMEM']) and count<7,'RECS member count/topcode')
  require(c['household_size']['status']==('observed' if r['ZNHSLDMEM']=='0' else 'survey_imputed'),'RECS member imputation')
  require([g['value'] for g in c['members_summary']['value']]==[n(r[f]) for f in ('NUMCHILD','NUMADULT1','NUMADULT2')],'RECS source age bins')
  for g,f in zip(c['members_summary']['value'],('NUMCHILD','NUMADULT1','NUMADULT2')):require(g['status']==('observed' if r['Z'+f]=='0' else 'survey_imputed'),'RECS age-bin imputation')
  require(sum(g['value'] for g in c['members_summary']['value'])==count,'RECS age-bin closure')
  types={'2':'detached_house','3':'attached_house','4':'small_apartment_building','5':'large_apartment_building'}
  require(dw['observed_type']['value']==types[r['TYPEHUQ']],'RECS dwelling type')
  require(dw['size']['value']==round(n(r['TOTSQFT_EN'])*0.09290304,2) and dw['size']['measure']=='energy_consuming_dwelling_area_m2','RECS area scope')
  require(r['ZTYPEHUQ']==r['ZCWASHER']=='0','RECS nonimputed selection')
  require(c['known_presence']['value']=={'someone_home_weekdays':n(r['ATHOME'])},'RECS presence source')
  f=c['additional_devices'].get('fridge_available')
  if f:require(f['value'] is (n(r['NUMFRIG'])>0),'source fridge fact changed; fridge is never control coverage')
  for slot,f in [('washer_available','CWASHER'),('dryer_available','DRYER'),('dishwasher_available','DISHWASH'),('space_ac_available','AIRCOND')]:
   v=binary(r,f);check_device(c,slot,v,'unknown' if v is None else 'observed' if r['Z'+f]=='0' else 'survey_imputed')
  check_device(c,'home_vehicle_charging',binary(r,'EVCHRGHOME'))
  fuel=r['FUELH2O'];expected=True if fuel in ('1','2','3','5','7','8','99') else None
  check_device(c,'water_heater_available',expected,'unknown' if expected is None else 'observed' if r['ZFUELH2O']=='0' else 'survey_imputed')
  if expected:
   require(dev['water_heater_available']['energy_carrier']==('electricity' if fuel=='5' else 'non_electric' if fuel in ('1','2','3','7','8') else 'unknown'),'RECS water-heater carrier')
 elif ds=='IDEAL':
  r=s['homes'].get(k);require(r is not None,'IDEAL source key');require(c['source']['country']=='GB','IDEAL scope')
  require(count==n(r['residents']) and c['members_summary']['status']=='unknown' and c['members_summary']['value'] is None,'IDEAL member scope')
  room=s['rooms'][dw['size']['room_key']]
  require(room['homeid']==k and dw['size']['value']==n(room['floorarea'])/10 and dw['size']['measure']=='single_observed_room_area_m2','IDEAL room area scope')
  require(dw['observed_type']['value']==r['hometype'],'IDEAL dwelling type')
  require(c['known_presence']['value']=={'occupied_days':n(r['occupied_days']),'occupied_nights':n(r['occupied_nights'])},'IDEAL source presence')
  for slot,types in [('washer_available',('washingmachine','washingmachinetumbledrier')),('dryer_available',('tumbledrier','washingmachinetumbledrier')),('dishwasher_available',('dishwasher',)),('water_heater_available',('electricshower',))]:
   present=any(a['appliancetype'] in types for a in s['byhome'][k]);check_device(c,slot,True if present else None)
   if present:
    asset=s['apps'][dev[slot]['appliance_key']];require(asset['homeid']==k and asset['appliancetype'] in types and n(asset['number'])>0,'IDEAL source appliance link')
  check_device(c,'space_ac_available',None);check_device(c,'home_vehicle_charging',None)
  for f in c['additional_devices'].values():
   a=s['apps'][f['appliance_key']];require(a['homeid']==k and a['appliancetype']==f['appliance_type'] and n(a['number'])>0,'IDEAL additional device')
 elif ds=='IRES2020':
  r=s['india'].get(k);require(r is not None,'IRES source key');require(c['source']['country']=='IN','IRES scope')
  require(count==n(r['q213_no_members']),'IRES household size')
  years=re.findall(r'(?:2019|2020)',r['interview_date'])
  require(c['source']['survey_date_raw']==r['interview_date'] and c['source']['survey_year']==(int(years[0]) if len(years)==1 else None),'IRES actual fieldwork year')
  bins=('q214_no_members_lessthan18','q214_no_members_18_40','q214_no_members_41_60','q214_no_members_morethan60')
  require([g['value'] for g in c['members_summary']['value']]==[n(r[f]) for f in bins] and sum(n(r[f]) for f in bins)==count,'IRES age bins')
  require(dw['observed_type']['value']=={'1':'independent_house_or_bungalow','2':'multi_storey_apartment'}[r['q217_house_type']],'IRES dwelling type')
  require(dw['size']['value']==n(r['q223_house_no_bedrooms'])+n(r['q225_house_no_otherrooms']) and dw['size']['measure']=='dwelling_rooms_excluding_bathrooms','IRES room scope')
  check_device(c,'washer_available',binary(r,'q472_wash_mach_yn'),'observed');check_device(c,'space_ac_available',binary(r,'q427_ac_yn'),'observed')
  check_device(c,'water_heater_available',True if r['q451_geyser_use_1']=='1' else None)
  for slot in ('dryer_available','dishwasher_available','home_vehicle_charging'):check_device(c,slot,None)
 elif ds=='ENASIC2022':
  r=s['mxhomes'].get(k);require(r is not None,'ENASIC source key');require(c['source']['country']=='MX','ENASIC scope')
  house=s['mxhouses'][r['LLAVEVIV']];members=s['members'][k]
  require(count==len(members),'ENASIC household size')
  require(s['mx_dwelling_households'][r['LLAVEVIV']]==1 and dw['source_households_in_dwelling']['value']==1,'multiple households share source dwelling')
  roster={r['person_key']:r['age']['value'] for r in c['members_summary']['value']}
  require(roster=={m['LLAVESDE']:n(m['EDAD']) for m in members},'ENASIC source roster')
  require(dw['size']['value']==n(house['P1_3A']) and dw['size']['measure']=='dwelling_room_count','ENASIC rooms')
  require(dw['observed_type']['value'] is None and dw['observed_type']['status']=='unknown','ENASIC actual dwelling type unknown')
  check_device(c,'washer_available',binary(house,'P1_10_02',('1',),('2',)),'observed')
  check_device(c,'space_ac_available',binary(house,'P1_9_10',('1',),('2',)),'observed')
  check_device(c,'water_heater_available',True if house['P1_9_07']=='1' or house['P1_9_08']=='1' else False if house['P1_9_07']=='2' and house['P1_9_08']=='2' else None)
  for slot in ('dryer_available','dishwasher_available','home_vehicle_charging'):check_device(c,slot,None)
  care=c['care_context']['value'];child=s['people'][care['child_key']];adult=s['people'][care['adult_caregiver_key']]
  require(child['LLAVEHOG']==adult['LLAVEHOG']==k and 0<=n(child['EDAD'])<18<=n(adult['EDAD']),'same-household adult child care')
  gate,edge=('P4_16','P4_17') if n(child['EDAD'])<=5 else ('P4_27','P4_28')
  require(child[gate]=='1' and n(adult['LLAVESDE'][-2:]) in {n(child[f'{edge}_{i}']) for i in (1,2,3)},'caregiver relationship')
  require(care['child_age']==n(child['EDAD']) and care['caregiver_age']==n(adult['EDAD']),'caregiver ages')
  ref=dw['reference_type'];dh=s['donorhouses'][ref['donor_dwelling_key']];dr=s['donorhomes'][(ref['donor_dwelling_key'],ref['donor_household_key'])]
  require(ref['status']=='reference_matched' and ref['source_dataset']=='ENIGH2024','housing reference provenance')
  require(dh['tot_hog']=='1' and n(dr['num_lavad'])>0 and n(dh['num_cuarto'])==dw['size']['value'] and n(dh['tot_resid'])==count,'housing donor exact common fields')
  require(ref['value']=={'1':'detached_house','2':'apartment'}[dh['tipo_viv']],'housing donor type')
  expected=dict(s['donorcounts'][(dw['size']['value'],count)])
  require(ref['type_counts']==expected and ref['donor_pool_count']==sum(expected.values()) and sum(expected.values())>=30,'housing donor pool counts')
  require(ref['alternative_types']==[{'type':t,'donor_count':ct} for t,ct in sorted(expected.items()) if ct>=5],'housing reference alternatives')
  require(expected[ref['value']]>=5 and 'climate' in ref['unmatched_dimensions'],'housing reference uncertainty')
 elif ds=='CRECS2012':check_china(c,s)
 else:raise ValueError('Unknown source '+ds)
 check_individual_facts(c,s)
 return True
