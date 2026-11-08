"""Read relevant source fields before constructing a complete household."""
from collections import Counter
from copy import deepcopy
import csv,io,json
from pathlib import Path
from zipfile import ZipFile
import pyreadstat
import seed_builder as seed
ROOT=Path(__file__).resolve().parent
BASE=ROOT.parent
EMPLOY={'1':'employed_full_time','2':'employed_part_time','3':'retired','4':'not_employed'}
CACHE={}

def rows(path,delimiter=','):
 with Path(path).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f,delimiter=delimiter))
def zrows(name,member):
 with ZipFile(BASE/'public_sources'/name) as z:
  with io.TextIOWrapper(z.open(member),encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def obs(value,fields,status='observed',**more):return {'value':value,'status':status,'fields':fields,**more}
def flagfact(raw,field,flag=None,cast=lambda x:x):
 value=raw.get(field)
 if value is None or value in ('','-2','-9','99','999'):return obs(None,[field],'unknown',raw=value)
 return obs(cast(value),[field]+([flag] if flag else []),'survey_imputed' if flag and raw.get(flag)!='0' else 'observed')

def load_sources():
 if not CACHE:raise RuntimeError('Raw sources not explicitly bound; normalized generation must not read historical files')
 return CACHE


def person_recs(raw,year):
 af='HHAGE' if year==2020 else 'HHAGE_PUB'
 return {'age':flagfact(raw,af,'Z'+af,int),'employment':flagfact(raw,'EMPLOYHH','ZEMPLOYHH',lambda v:EMPLOY[v]),'source_person':'survey_respondent','teleworking_household':flagfact(raw,'TELLWORK','ZTELLWORK',lambda x:x=='1'),'medical_device':flagfact(raw,'MEDICALDEV','ZMEDICALDEV',lambda x:x=='1'),'charger_type':flagfact(raw,'EVCHRGTYPE',cast=lambda x:{'1':'Level_1','2':'Level_2'}[x]),'charging_at_home_share_code':flagfact(raw,'EVHOMEAMT'),'dryer_fuel_code':flagfact(raw,'DRYRFUEL','ZDRYRFUEL')}


def enrich(row):
 sources=load_sources();ds,key=row['source']['dataset'],row['source']['household_key']
 if ds in ('RECS2020_v7','RECS2024_v1'):
  year=2020 if ds=='RECS2020_v7' else 2024;r=sources['recs'+str(year)][key]
  row['source_person']=person_recs(r,year)
  if int(r.get('NUMFRIG','0'))==0:row['additional_devices']['fridge_available']=obs(False,['NUMFRIG','ZNUMFRIG'],'observed' if r.get('ZNUMFRIG')=='0' else 'survey_imputed')
 elif ds=='ENABLE_EU':
  r=sources['es'][key];age=obs(None,[],'unknown')
  job={1:'employed_full_time',2:'employed_part_time',3:'not_employed',4:'retired',5:'student',6:'not_employed'}.get(r['S3'])
  row['source_person']={'age':age,'employment':obs(job,['S3'],'observed' if job else 'unknown'),'source_person':'survey_respondent','teleworking_household':obs(None,[],'unknown')}
  fridge=r.get('H11A')
  row['additional_devices']['fridge_available']=obs(fridge in (1,2,4),['H11A']) if fridge in (1,2,4,5) else obs(None,['H11A'],'unknown')
  row['source_person']['commute_frequency']=obs(int(r['M1A']),['M1A']) if r['M1A'] is not None and 0<=r['M1A']<=7 and r['M3A1']==1 else obs(None,['M1A','M3A1'],'unknown')
 elif ds=='IRES2020':
  r=sources['india'][key]
  row['additional_devices']['fridge_available']=obs(r['q466_fridge_yn']=='1',['q466_fridge_yn'])
  row['source_person']={'age':flagfact(r,'q202_resp_age',cast=int),'employment':obs(None,[],'unknown'),'source_person':'survey_respondent','teleworking_household':obs(None,[],'unknown'),'household_students':obs(int(r['q215_no_members_studying']),['q215_no_members_studying'])}
 elif ds=='IDEAL':
  row['source_person']={'age':obs(None,[],'unknown'),'employment':obs(None,[],'unknown'),'source_person':'unspecified_adult_decision_maker','teleworking_household':obs(None,[],'unknown')}
  row['additional_devices'].setdefault('fridge_available',obs(None,[],'unknown'))
 elif ds=='ENASIC2022':
  keyperson=row['anchors']['E']['value']['adult_caregiver_key'] if 'anchors' in row else row['care_context']['value']['adult_caregiver_key']
  row['source_person']={'age':obs(int(sources['mxpeople'][keyperson]['EDAD']),['TCSDEMPO.EDAD']),'employment':mx_job(sources['mxcare'].get(keyperson,{})),'source_person':keyperson,'teleworking_household':obs(None,[],'unknown')}
  row['source_member_details']={}
  roster=row['members_summary']['value']
  for m in roster:
   k=m['person_key'];r=sources['mxpeople'][k];a=int(r['EDAD']);care=sources['mxcare'].get(k,{})
   school_field='P3_10' if a<=5 else 'P3_15' if a<=24 else None
   school=obs(r[school_field]=='1',[f'TCSDEMPO.{school_field}']) if school_field and r.get(school_field) in ('1','2') else obs(None,[],'unknown')
   row['source_member_details'][k]={'employment':mx_job(care),'school_enrollment':school,'nursery_hours':flagfact(r,'P3_12',cast=int) if a<=5 else obs(None,[],'unknown'),'work_hours_last_week':flagfact(care,'P5_13',cast=int),'commute_hours_roundtrip':flagfact(care,'P5_14_1',cast=int),'commute_minutes_roundtrip':flagfact(care,'P5_14_2',cast=int)}
  h=sources['mxhouses'][sources['mxhomes'][key]['LLAVEVIV']]
  row['additional_devices']['fridge_available']=obs(h['P1_10_01']=='1',['TVIVIENDA.P1_10_01'],'observed') if h['P1_10_01'] in ('1','2') else obs(None,['TVIVIENDA.P1_10_01'],'unknown')
  # Both explicit no answers establish no boiler/solar equipment; missing does not.
  if h['P1_9_07']=='2' and h['P1_9_08']=='2':row['devices']['water_heater_available']=obs(False,['TVIVIENDA.P1_9_07','TVIVIENDA.P1_9_08'])
 return row


def mx_job(r):
 primary=r.get('P5_6');side=r.get('P5_8')
 if primary in ('1','2') or side in ('1','2','3','4','5','6'):value='employed'
 else:value={'3':'not_employed','4':'retired','5':'student','6':'home_caregiver','7':'unable_to_work','8':'not_employed'}.get(primary)
 return obs(value,['TPOB_CUI.P5_6','TPOB_CUI.P5_8'],'observed' if value else 'unknown',primary_activity_code=primary,work_verification_code=side)


def response_fits_age_groups(row):
 person=row['source_person'];age=person['age']['value'];groups=row['members_summary']['value']
 if age is None or not groups or row['members_summary']['scope']=='source_person_roster':return True
 if age<18:return False
 ds=row['source']['dataset']
 if ds.startswith('RECS'):ix=0 if age<18 else 1 if age<65 else 2
 elif ds=='IRES2020':ix=0 if age<18 else 1 if age<=40 else 2 if age<=60 else 3
 else:return True
 return groups[ix]['value']>0


def f2024_candidates():
 out=[]
 flags=['ZCWASHER','ZTYPEHUQ','ZEMPLOYHH','ZHHAGE_PUB','ZSQFTEST_PUB','ZNUMCHILD_PUB','ZNUMADULT1_PUB','ZNUMADULT2_PUB']
 for r in load_sources()['recs2024'].values():
  n=int(r['NHSLDMEM_PUB']);age=int(r['HHAGE_PUB']);nums=[int(r[f]) for f in ('NUMCHILD_PUB','NUMADULT1_PUB','NUMADULT2_PUB')]
  if not(r['EVCHRGHOME']=='1' and r['CWASHER']=='1' and r['EMPLOYHH'] in ('1','2') and 18<=age<65 and 1<=n<7 and sum(nums)==n and nums[0]<4 and nums[1]<4 and nums[2]<2 and all(r[f]=='0' for f in flags) and r['TYPEHUQ'] in seed.src.US_TYPE and (nums[1]+nums[2]>=2 or r['ATHOME']=='0')):continue
  row=seed.src.ref('RECS2024_v1',r['DOEID'],'US',obs(n,['NHSLDMEM_PUB'],'derived',uncensored_age_components=True),obs(seed.src.US_TYPE[r['TYPEHUQ']],['TYPEHUQ','ZTYPEHUQ']),obs(round(int(r['SQFTEST_PUB'])*0.09290304,2),['SQFTEST_PUB','ZSQFTEST_PUB'],'derived',measure='respondent_reported_dwelling_area_m2'),obs(True,['CWASHER','ZCWASHER']),anchors={'F':obs({'vehicle_charged_at_home':True},['EVCHRGHOME'])})
  for slot,field in [('dryer_available','DRYER'),('dishwasher_available','DISHWASH')]:row['devices'][slot]=seed.coded(r,field,flag='Z'+field)
  row['devices']['home_vehicle_charging']=obs(True,['EVCHRGHOME'])
  row['additional_devices']={}
  if int(r['NUMFRIG'])>0:row['additional_devices']['fridge_available']=obs(True,['NUMFRIG','ZNUMFRIG'],'observed' if r['ZNUMFRIG']=='0' else 'survey_imputed')
  row['members_summary']=obs([{'label':label,**obs(v,[f,'Z'+f])} for v,f,label in zip(nums,('NUMCHILD_PUB','NUMADULT1_PUB','NUMADULT2_PUB'),('age_0_17','age_18_64','age_65_plus'))],['NUMCHILD_PUB','NUMADULT1_PUB','NUMADULT2_PUB'],'derived',scope='published_age_groups')
  row['geography']=obs(r['REGIONC'],['REGIONC'],scope='US_census_region')
  row['known_presence']=obs({'someone_home_weekdays':int(r['ATHOME'])},['ATHOME','ZATHOME'],'observed' if r['ZATHOME']=='0' else 'survey_imputed')
  row['block']=['US',r['REGIONC'],row['dwelling']['observed_type']['value'],n,int(row['dwelling']['size']['value']//25)]
  row['source'].update(survey_year=2024,survey_reference_year=2024,fieldwork_year=None,survey_year_semantics='survey_reference_year',release='v1 May2026',catalogue_id='RECS2024_v1')
  out.append(enrich(row))
 return out


def home_carer_possible(row):
 if row['source']['dataset']!='ENASIC2022':return True
 needs=[]
 for m in row['members_summary']['value']:
  detail=row['source_member_details'][m['person_key']]
  if m['age']['value']<6 or (m['age']['value']<12 and detail['school_enrollment']['value'] is False):needs.append(m)
  hours=detail['nursery_hours']['value']
  if m['age']['value']<6 and hours is not None and hours>12:return False
 if not needs:return True
 for m in row['members_summary']['value']:
  if m['age']['value']<18:continue
  d=row['source_member_details'][m['person_key']];job=d['employment']['value'];a=d['commute_hours_roundtrip']['value'];b=d['commute_minutes_roundtrip']['value']
  if job not in ('employed','employed_full_time','employed_part_time') or (a in (None,0) and b in (None,0)):return True
 return False

def install():
 seed.SEED='EB-household-stage1-v3';seed.src.SEED=seed.SEED
 seed.SOURCES['RECS2024_v1']={'country':'US','survey_year':2024,'release':'v1 May2026','url':'https://www.eia.gov/consumption/residential/data/2024/index.php?view=microdata','geographic_scope':'employed 18-64 respondents, uncensored household age counts and home charging'}
 original=seed.load_candidates
 def load():
  pools=original()
  for co,rs in pools.items():
   for row in rs:enrich(row)
   pools[co]=[r for r in rs if not(r['source']['dataset']=='ENASIC2022' and any(m['age']['value']>=98 for m in r['members_summary']['value'])) and response_fits_age_groups(r) and home_carer_possible(r) and not(r['source']['dataset']=='RECS2020_v7' and sum(g['value'] for g in r['members_summary']['value'][1:])<=1 and r['source_person']['employment']['value'] in ('employed_full_time','employed_part_time') and r['source_person']['teleworking_household']['value'] is False and r['known_presence']['value']['someone_home_weekdays']>0)]
  # Do not assign a work-commuting F role on the strength of charging alone.
  for r in pools['US']:r['anchors'].pop('F',None)
  return pools
 seed.load_candidates=load
 return seed


def equipment_reference(case):
 if case['source']['dataset']!='RECS2024_v1':return
 r=load_sources()['recs2024'][case['source']['household_key']];area=case['dwelling']['size']['value'];n=case['household_size']['value']
 pool=[];level=None
 allrows=load_sources()['recs2020'].values()
 for candidate_level in [0,1,2]:
  pool=[]
  for d in allrows:
   if d['REGIONC']!=r['REGIONC'] or d['TYPEHUQ']!=r['TYPEHUQ'] or d['CWASHER']!='1':continue
   if int(d['NHSLDMEM'])>=7 or abs(int(d['NHSLDMEM'])-n)>(1 if candidate_level==2 else 0):continue
   if any(d[f]!='0' for f in ['ZAIRCOND','ZFUELH2O','ZTYPEHUQ','ZCWASHER','ZNHSLDMEM']):continue
   if d['FUELH2O'] not in ['1','2','3','5','7','8']:continue
   if any(d[k]!=r[k] for k in ['DRYER','DISHWASH']):continue
   if candidate_level==0 and d['EVCHRGHOME']!='1':continue
   pool.append(d)
  if pool:level=candidate_level;break
 assert pool,'No compatible reference equipment donor'
 pool.sort(key=lambda d:abs(float(d['TOTSQFT_EN'])*0.09290304-area)/area)
 closest=pool[:min(10,len(pool))]
 chosen=min(closest,key=lambda d:seed.rank('reference-equipment',case['case_id'],d['DOEID']))
 fuel=chosen['FUELH2O'];charger={'1':'Level_1','2':'Level_2'}.get(chosen['EVCHRGTYPE']) if chosen['EVCHRGHOME']=='1' else None
 case['reference_equipment']={'source_dataset':'RECS2020_v7','donor_household_key':chosen['DOEID'],'status':'reference_matched','match_level':level,'candidate_count':len(pool),'nearest_candidates_considered':len(closest),'matched_region':r['REGIONC'],'matched_house_type':r['TYPEHUQ'],'target_household_size':n,'donor_household_size':int(chosen['NHSLDMEM']),'matched_devices':['CWASHER','DRYER','DISHWASH'],'donor_area_m2':round(float(chosen['TOTSQFT_EN'])*0.09290304,2),'target_area_m2':area,'values':{'space_ac_available':chosen['AIRCOND']=='1','water_heater_available':True,'water_heater_carrier':'electricity' if fuel=='5' else 'solar' if fuel=='8' else 'non_electric'},'charger_type':charger,'limitations':['different household and survey year','nearest area is a reference, not physical calibration','charging match relaxed when level > 0','one-person size difference only at level2']}
