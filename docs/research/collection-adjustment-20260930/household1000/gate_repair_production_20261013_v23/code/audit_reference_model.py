"""Exact extrema of native temperature modifiers, native parameter/flow binding."""
from common import *
from compile_inputs import CURVES,DX,FAN,get
def extrema(r):
 a,b,c,d,e,f=map(float,r[2:8]);xlo,xhi=float(get(r,'minimum_value_of_x')),float(get(r,'maximum_value_of_x'));ylo,yhi=float(get(r,'minimum_value_of_y')),float(get(r,'maximum_value_of_y'))
 pts=[(x,y) for x in (xlo,xhi) for y in (ylo,yhi)]
 if c:
  for y in (ylo,yhi):pts.append((-(b+f*y)/(2*c),y))
 if e:
  for x in (xlo,xhi):pts.append((x,-(d+f*x)/(2*e)))
 det=4*c*e-f*f
 if det:pts.append(((-2*e*b+f*d)/det,(-2*c*d+f*b)/det))
 pts=[(x,y) for x,y in pts if xlo<=x<=xhi and ylo<=y<=yhi]
 vals=[a+b*x+c*x*x+d*y+e*y*y+f*x*y for x,y in pts]
 x,y=19.44444,35
 return {'curve':r[1],'original_bounds':[[xlo,xhi],[ylo,yhi]],'exact_rectangle_min':min(vals),'exact_rectangle_max':max(vals),
 'rating_reference_multiplier':a+b*x+c*x*x+d*y+e*y*y+f*x*y,'extrema_candidates':pts}
def main():
 school_guard();names=[get(DX,k) for k in ['total_cooling_capacity_function_of_temperature_curve_name','energy_input_ratio_function_of_temperature_curve_name']]
 mods=[extrema(r) for r in CURVES if r[1] in names];fails=[];n=0
 for h in read(OUT/'WORLD_BINDINGS1000.json')['records']:
  w=read(OUT/h['world_path']);old=read(SOURCE/h['world_path'])
  if w['parameter_pack']['devices']!=old['parameter_pack']['devices']:
   for new,prev in zip(w['parameter_pack']['devices'],old['parameter_pack']['devices']):
    if new['parameters']!=prev['parameters']:fails.append([h['household_id'],'EB_PARAMETER_CHANGED'])
  for device in w['parameter_pack']['devices']:
   if 'ac' not in device['types']:continue
   n+=1;q=device['parameters'];ratio=q['flow_m3_h']/3600/q['cooling_W']
   if not .00004027<=ratio<=.00006041:fails.append([h['household_id'],'FLOW_CAPACITY_RANGE',ratio])
   if float(q['gross_rated_COP'])!=float(get(DX,'gross_rated_cooling_cop')):fails.append([h['household_id'],'NATIVE_COP'])
 for m in mods:
  if m['exact_rectangle_min']<=0:fails.append([m['curve'],'NONPOSITIVE_BOUNDED_MODIFIER'])
 result={'status':'pass' if not fails else 'fail','native_temperature_modifiers':mods,'AC_instances':n,'failures':fails,
 'manufacturer_validation':False,'outside_fit_domain_verified':False,
 'interpretation':'known mathematical bound behavior and preserved native inputs only; no empirical extrapolation validation'}
 save(OUT/'REFERENCE_MODEL_AUDIT.json',result);print({k:v for k,v in result.items() if k!='native_temperature_modifiers'},flush=True)
 if fails:raise RuntimeError(str(fails[:5]))
if __name__=='__main__':main()

