"""Attach per-coil identical native curves and raw pre-bound reporting.
No coefficient, original bounds, or physical control is changed.
"""
import copy
from common import *
from compile_inputs import get,put
FIELDS=['total_cooling_capacity_function_of_temperature_curve_name',
'energy_input_ratio_function_of_temperature_curve_name']
def attach(rows):
 curves={r[1]:r for r in rows if r[0].startswith('Curve:')};meta=[]
 for coil in [r for r in rows if r[0]=='Coil:Cooling:DX:SingleSpeed']:
  for field in FIELDS:
   old=get(coil,field);r=copy.deepcopy(curves[old]);name=coil[1]+'_observed_'+old;r[1]=name
   assert r[2:]==curves[old][2:];rows.append(r);put(coil,field,name)
   meta.append({'coil':coil[1],'curve':name,'original_curve':old,'field':field,
    'bounds':[[float(get(r,'minimum_value_of_'+a)),float(get(r,'maximum_value_of_'+a))] for a in ('x','y')]})
   for var in ['Performance Curve Output Value','Performance Curve Input Variable 1 Value','Performance Curve Input Variable 2 Value']:
    rows.append(['Output:Variable',name,var,'Detailed'])
  rows.append(['Output:Variable',coil[1],'Cooling Coil Electricity Rate','Detailed'])
 return meta
def read_actual(sql,meta):
 import sqlite3,collections
 db=sqlite3.connect('file:'+str(sql)+'?mode=ro',uri=True)
 rows=db.execute('SELECT t.TimeIndex,d.Name,d.KeyValue,r.Value FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE t.WarmupFlag=0 AND (d.Name LIKE "Performance Curve%" OR d.Name="Cooling Coil Electricity Rate")').fetchall();db.close()
 steps=collections.defaultdict(dict)
 for ti,name,key,value in rows:steps[ti][name,(key or '').upper()]=value
 statistics=[]
 for m in meta:
  counts=collections.Counter();bounds=m['bounds'];xs=[[],[]]
  for ti,f in steps.items():
   if f.get(('Cooling Coil Electricity Rate',m['coil'].upper()),0.)<=1e-8:continue
   values=[f.get((f'Performance Curve Input Variable {i+1} Value',m['curve'].upper())) for i in range(2)]
   if any(v in (None,-999) for v in values):continue
   counts['active_reports']+=1
   outside=False
   for i,(v,(lo,hi)) in enumerate(zip(values,bounds)):
    xs[i].append(v)
    if not lo-1e-6<=v<=hi+1e-6:counts['outside_axis_'+str(i+1)]+=1;outside=True
   if outside:counts['outside_any_axis']+=1
  statistics.append({**m,'counts':dict(counts),'raw_ranges':[[min(v),max(v)] if v else None for v in xs]})
 return {'status':'original_boundary_used' if any(s['counts'].get('outside_any_axis',0) for s in statistics) else 'no_active_outside_bound_reports',
  'statistics':statistics,'reported_counts_are_HVAC_calls_not_elapsed_minutes':True,
  'AHRI_rating_warning_distinct':True,'manufacturer_or_fitted_domain_validated':False}

