#!/usr/bin/env python3
"""Extract authoritative city aggregates with spreadsheet cell provenance.

No profiles are generated. The IPF table is an explicitly modeled completion
of three observed margins, not an observed province-size-generation joint.
"""
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import numpy as np
import xlrd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def name(s):return ''.join(str(s).split())
def write(p,x):
 with p.open('x') as f:json.dump(x,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')

class Tables(HTMLParser):
 def __init__(self):super().__init__();self.tables=[];self.table=None;self.row=None;self.cell=None
 def handle_starttag(self,t,a):
  if t=='table':self.table=[]
  elif t=='tr' and self.table is not None:self.row=[]
  elif t in ('td','th') and self.row is not None:self.cell=''
 def handle_data(self,d):
  if self.cell is not None:self.cell+=d
 def handle_endtag(self,t):
  if t in ('td','th') and self.cell is not None:self.row.append(name(self.cell));self.cell=None
  elif t=='tr' and self.row is not None:self.table.append(self.row);self.row=None
  elif t=='table' and self.table is not None:self.tables.append(self.table);self.table=None

def main():
 target=read(ROOT/'city_representativeness_20261001/CITY_TARGET_AUDIT.json')
 provinces=[r['province'] for r in target['province_quotas']]
 keys=set(provinces)|{'全国'}
 tables={}
 for p in sorted((HERE/'raw').glob('*.xls')):
  s=xlrd.open_workbook(p).sheet_by_index(0)
  rows={}
  for i in range(s.nrows):
   r=s.row_values(i);k=name(r[0])
   if k in keys and isinstance(r[1],(int,float)):
    assert k not in rows
    rows[k]={'excel_row_1based':i+1,'counts_or_aggregates':[int(v) if isinstance(v,(int,float)) and float(v).is_integer() else v for v in r[1:]]}
  assert set(rows)==keys,(p.name,set(rows)^keys)
  assert sum(rows[k]['counts_or_aggregates'][0] for k in provinces)==rows['全国']['counts_or_aggregates'][0],p.name
  tables[p.stem]={'title':s.cell_value(0,0),'url':'https://www.stats.gov.cn/sj/pcsj/rkpc/7rp/zk/html/'+p.name,
    'file':'raw/'+p.name,'sha256':sha(p),'sheet':s.name,'header_rows':list(s.row_values(i) for i in range(2,7)),
    'notes':[s.cell_value(i,0) for i in range(s.nrows) if str(s.cell_value(i,0)).startswith('注')],
    'frame':'all_city_family_households_short_form' if p.stem in ('A0108a','A0109a') else
            'ordinary_dwelling_city_family_households_short_form' if p.stem=='A0803a' else
            'city_long_form_housing_table_sample; exact dwelling inclusion requires indicator documentation',
    'rows':rows}
 ordinary=tables['A0803a']
 for k,r in ordinary['rows'].items():assert sum(r['counts_or_aggregates'][1:])==r['counts_or_aggregates'][0],k
 source_pg=[]
 for k,r in ordinary['rows'].items():
  a=r['counts_or_aggregates'];m=np.array(a[1:]).reshape(5,5)
  source_pg.append({'province':k,'ordinary_city_households':a[0],
    'generation_room_counts':m.tolist(),'generation_totals':m.sum(1).tolist(),
    'room_totals':m.sum(0).tolist(),'source_excel_row_1based':r['excel_row_1based']})
 long_summary={}
 for k in keys:
  get=lambda t:tables[t]['rows'][k]['counts_or_aggregates']
  b=get('B0901a');assert sum(b[1:5])==sum(b[5:])==b[0]
  tenure=get('B0904a');assert sum(tenure[1:])==tenure[0]
  rent=get('B0905a');assert sum(rent[1:])==rent[0]==sum(tenure[1:3])
  kt=get('B0906a');assert sum(kt[1:])==kt[0]
  assert all(a<=b for a,b in zip(kt,tenure))
  car=get('B0913a');assert sum(car[1:])==car[0]
  vintage=get('B0902a');assert sum(vintage[3::3])==vintage[0]
  assert sum(vintage[4::3])==vintage[1] and sum(vintage[5::3])==vintage[2]
  facilities=get('B0903a')
  assert all(sum(facilities[a:b])==facilities[0] for a,b in [(1,3),(3,8),(8,10),(10,13),(13,18),(18,22)])
  long_summary[k]={'long_housing_total':tenure[0],'building_storeys_counts':b[1:5],
    'load_bearing_type_counts':b[5:],'storeys_and_bearing_are_separate_margins_not_joint':True,
    'vintage_counts':vintage[3::3],'vintage_room_totals':vintage[4::3],'vintage_building_area_totals_m2':vintage[5::3],
    'vintage_whole_area_means_m2':[round(a/n,4) if n else None for a,n in zip(vintage[5::3],vintage[3::3])],
    'tenure_counts':tenure[1:],'renter_total':rent[0],'renter_monthly_rent_counts':rent[1:],
    'kitchen_and_toilet_by_tenure_counts':kt[1:],
    'kitchen_and_toilet_fraction_by_tenure':[round(a/b,6) if b else None for a,b in zip(kt[1:],tenure[1:])],
    'building_has_elevator_count':facilities[1],'building_no_elevator_count':facilities[2],
    'cooking_fuel_counts':facilities[3:8],'piped_water_counts':facilities[8:10],
    'kitchen_exclusive_shared_none_counts':facilities[10:13],
    'toilet_type_counts':facilities[13:18],'bathing_facility_counts':facilities[18:22],
    'households_with_any_family_car':car[0]-car[-1],'households_without_family_car':car[-1],
    'car_is_not_EV_and_not_home_charging':True}
 # Province-specific eligibility must be applied to BOTH short-form margins.
 ps=[];pg=[]
 for r in target['province_quotas']:
  p=r['province'];u=r['under20_one_person_households_5_2a']
  a=tables['A0108a']['rows'][p]['counts_or_aggregates'];sizes=np.array(a[1::2],float);sizes[0]-=u
  b=tables['A0109a']['rows'][p]['counts_or_aggregates'];gens=np.array(b[1::2],float);gens[0]-=u
  assert sum(sizes)==sum(gens)==r['eligible_city_family_households']
  ps.append(sizes);pg.append(gens)
 ps=np.array(ps);pg=np.array(pg)
 lock=read(ROOT/'INPUT_LOCK.json')['files']
 national=np.array(read(lock['structure_json']['path'])['city']['matrix'],float)
 national[0,0]-=target['total_city_households']-target['eligible_city_households']
 assert np.array_equal(ps.sum(0),national.sum(1)) and np.array_equal(pg.sum(0),national.sum(0))
 x=np.broadcast_to(national[None,:,:],(31,10,5)).copy()
 def adjust(x,desired,axis):
  actual=x.sum(axis=axis,keepdims=True)
  ratio=np.divide(desired,actual,out=np.zeros_like(actual),where=actual>0)
  return x*ratio
 for it in range(20000):
  x=adjust(x,ps[:,:,None],2);x=adjust(x,pg[:,None,:],1);x=adjust(x,national[None,:,:],0)
  errors=[np.max(np.abs(x.sum(2)-ps)),np.max(np.abs(x.sum(1)-pg)),np.max(np.abs(x.sum(0)-national))]
  if max(errors)<1e-5:break
 assert max(errors)<1e-5,errors
 ipf={'method':'iterative proportional fitting from national size-generation seed',
   'status':'modeled_completion_of_observed_margins_not_observed_joint',
   'observed_margins':['province_x_size_eligible','province_x_generation_eligible','national_size_x_generation_eligible'],
   'starting_assumption':'province-independent national size-generation association, then margin calibration',
   'unobserved_association_status':'not identified by margins; alternative seeds needed in sensitivity',
   'iterations':it+1,'max_absolute_count_residual_by_margin':errors,
   'n_profiles_generated':0,'integer_assignment_done':False,
   'province_order':provinces,'size_categories':['1','2','3','4','5','6','7','8','9','10+'],
   'generation_categories':['1','2','3','4','5+'],
   'expected_counts_per1000':(x/target['eligible_city_households']*1000).tolist(),
   'five_plus_generation_expected_mass_per1000':float(x[:,:,4].sum()/target['eligible_city_households']*1000),
   'eligible_province_size_counts':ps.astype(int).tolist(),'eligible_province_generation_counts':pg.astype(int).tolist()}
 timeuse={}
 for n in ['timeuse_2024_2','timeuse_2024_3']:
  t=Tables();p=HERE/'raw'/f'{n}.html';t.feed(p.read_bytes().decode('utf-8'))
  timeuse[n]={'tables':t.tables,'sha256':sha(p),
    'unit':'individuals aged6plus; weekly weighted daily minutes and participation, not household counts',
    'not_available':['city-only split','city_x_age_x_employment_joint','individual diary clock windows','household task/operator assignment','under6 activity targets'],
    'weekday_weekend_weighting':[5/7,2/7],'use':'auxiliary time-budget plausibility; no hard city schedule quota'}
 result={'batch_id':'CITY1000_AUTHORITY_CONSTRAINTS_20261001_V1','target_scope':target['scope'],
   'tables':tables,'complete_province_generation_room_counts':source_pg,
   'long_form_housing_summary':long_summary,'modeled_population_completion':ipf,'timeuse':timeuse,
   'semantic_rules':['building_storeys != dwelling_floor_position','bearing_structure != insulation/Uvalue',
      'tenure != controllability/permission','kitchen/toilet presence != appliance installation',
      'family_installed_water_heater != electric_water_heater','car ownership != EV/home charging',
      'rent expense != household income/electricity bill','timeuse urban includes town; not city-only'],
   'code_sha256':sha(__file__),'profiles_generated':0,'A_B_generated':0,'engine_calls':0}
 write(HERE/'CITY_AUTHORITY_CONSTRAINTS.json',result)
 print(json.dumps({'tables':len(tables),'regions_per_table':len(keys),'full_province_generation_room_cells':31*5*5,
   'IPF_iterations':ipf['iterations'],'IPF_margin_count_errors':errors,
   'long_form_national':long_summary['全国'],'profiles_generated':0},ensure_ascii=False))

if __name__=='__main__':main()
