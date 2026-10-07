"""Needs-first active-event contrast protocol; no B outputs or human labels used."""
import collections,concurrent.futures,copy,datetime as dt,hashlib,json,os,sys
from pathlib import Path
OUT=Path(__file__).resolve().parents[1];BASE=OUT.parent;SRC=BASE/'joint_static_production_20261007_v16';PILOT=BASE/'pilot50_frontend_20261007_v1'
sys.path.insert(0,str(SRC/'code'))
from plans import make_A,active_wash
from validate import validate
from common import digest,sha,save,read,rank
KINDS=['ac','washer','dishwasher','dryer','water_heater','ev']
PROTOCOL={'version':'needs_first_active_event_contrast_v1','purpose':'conditional assigned-role judgments about concrete DR plans;not unconditional annual-day acceptability','target_households':'same fifty source-anchored city ordinary residential reference families','device_scope':'same EB4to6 classes and physical assets;no added appliances','A_rule':'same source/designed activity and program demand;WH availability covers final given bath;A frozen before event/B','event_rule':'one60min synthetic DR event aligned to an eligible A opportunity;30min clock grid;notice60min earlier;not observed China dispatch','requested_reduction_kw':.5,'event_goal_source':'pinned EB mock_signal.py default .5kW;event clock generalized from mock to case-specific designed context','B_levels':{'program_shift_min':[30,60],'EV_delay_min':[30,60],'WH_heat_shift_min':[30,60],'AC_setpoint_increase_C':[1.0]},'B_choice':'least-used statically feasible family within household with SHA tie-break;no B energy,cost,human ranking','date_frame':'all2025 dates with at least one input-legal eligible contrast;then SHA-random3/3/2/2 quarterly sample;no EP/B-result date screening','identity_cases':'retained in original diagnostic batch;not primary ten preference tasks','no_eligible_dates':'logged in complete eligibility frame,not fake preference cases','admission':'static contrast and event relevance + actual state/meters/service review + human readability pilot;never infer actor preference from physics','human_answers':0,'collection_release':False,'training_release':False}

def baseline(w,date):
 needs,A,ws,initial=make_A(w,date)
 return {'schema':'eb.joint_same_need_pair.v1','case_id':w['household_id']+':'+str(date),'household_id':w['household_id'],'round_index':1,'date':str(date),'date_selection':{},'world_sha256':w['world_content_sha256'],'parameter_pack_sha256':w['parameter_pack_sha256'],'decision_abs_min':0,'event_window_min':[0,60],'horizon_min':3330,'primary_evaluation_min':[0,2880],'service_tail_min':[2880,3330],'tail_rule':'unchanged fixed next-morning service tail','world':{'devices':copy.deepcopy(w['parameter_pack']['devices']),'operator_windows':ws,'circuit_limit_kw':w['parameter_pack']['circuit_limit_kw'],'home_service_limit_kw':w['parameter_pack']['home_service_limit_kw'],'background_reserved_kw':w['parameter_pack']['background_reserved_kw']},'common_initialization_binding':initial,'needs_A':needs,'needs_B':copy.deepcopy(needs),'A':A,'B':copy.deepcopy(A),'A_frozen_before_B_sha256':digest(A),'human_adoption':None,'human_relative_preference':None,'simulated_consequences':None}

def weather_lookup(path):
 d=collections.defaultdict(dict)
 for line in Path(path).read_text().splitlines()[8:]:
  f=line.split(',');d[int(f[1]),int(f[2])][int(f[3])-1]=float(f[6])
 return d

def candidates(w,date,weather):
 p=baseline(w,date);out=[]
 def keep(q,family,amount,target):
  q['B']['changed_controls']=[c for c in q['B']['controls'] if c not in q['A']['controls']]
  q['proposal']={'family':family,'amount':amount,'target_asset_id':target,'origin':'needs-first active-event contrast protocol','energy_cost_or_human_outputs_consulted':False,'LLM_call_occurred':False,'protocol_sha256':digest(PROTOCOL)}
  q['decision_abs_min']=q['event_window_min'][0]-60
  if q['decision_abs_min']<0:return
  if not validate(q):out.append(q)
 # Program start shifts of30/60min, including the actual linked dryer.
 for t in p['A']['tasks']:
  if t['start_min']>=1440 or t['kind'] not in ['washer','dishwasher']:continue
  for amount in [30,60]:
   q=copy.deepcopy(p);E=t['start_min']//30*30;q['event_window_min']=[E,E+60]
   for x in q['B']['tasks']:
    if x['need_id'] in [t['need_id'],t['need_id']+':dry']:x['start_min']+=amount;x['end_min']+=amount
   keep(q,'task_shift',amount,t['asset_id'])
   # Optional joint AC intervention in the same event,without changing demands.
   if any(c['kind']=='ac_setpoint' and c['start_min']<E+60 and c['end_min']>E for c in q['A']['controls']):
    hot=max(weather[date.month,date.day].get(h,-100) for h in [E//60,min(E//60+1,23)])>=28
    if hot:
     z=copy.deepcopy(q);changed=[]
     for c in z['B']['controls']:
      a,b=max(E,c['start_min']),min(E+60,c['end_min'])
      if c['kind']!='ac_setpoint' or a>=b:changed.append(c);continue
      if c['start_min']<a:changed.append({**c,'end_min':a})
      changed.append({**c,'start_min':a,'end_min':b,'value_C':27.})
      if b<c['end_min']:changed.append({**c,'start_min':b})
     z['B']['controls']=changed;keep(z,'task_plus_ac',amount,t['asset_id'])
 for c in p['A']['controls']:
  if c['start_min']>=1440:continue
  kind=c['kind'];E=c['start_min']//30*30
  if kind in ['ev_charge_window','tank_setpoint']:
   for amount in [30,60]:
    q=copy.deepcopy(p);q['event_window_min']=[E,E+60]
    for z in q['B']['controls']:
     if z==c:z['start_min']+=amount;z['end_min']+=amount if kind=='tank_setpoint' else 0
    keep(q,'ev_charge_delay' if kind=='ev_charge_window' else 'hotwater_preheat_shift',amount,c['asset_id'])
  if kind=='ac_setpoint':
   # Forecast temperature is input context,not a B-result selection rule.
   hot=max(weather[date.month,date.day].get(h,-100) for h in [E//60,min(E//60+1,23)])>=28
   if not hot:continue
   q=copy.deepcopy(p);q['event_window_min']=[E,E+60];changed=[]
   for z in q['B']['controls']:
    a,b=max(E,z['start_min']),min(E+60,z['end_min'])
    if z['kind']!='ac_setpoint' or a>=b:changed.append(z);continue
    if z['start_min']<a:changed.append({**z,'end_min':a})
    changed.append({**z,'start_min':a,'end_min':b,'value_C':27.})
    if b<z['end_min']:changed.append({**z,'start_min':b})
   q['B']['controls']=changed;keep(q,'ac_setpoint',1.,c['asset_id']);break
 return out

def pattern(w,date,weather):
 tomorrow=date+dt.timedelta(days=1)
 return (date.weekday(),active_wash(w,date),active_wash(w,tomorrow),5<=date.month<=9,5<=tomorrow.month<=9,max(weather[date.month,date.day].get(h,-100) for h in range(16,24))>=28,tuple(weather[date.month,date.day].get(h,-100)>=28 for h in range(16,24)))

def one(h):
 w=read(SRC/h['world_path']);old_sha=sha(SRC/h['world_path']);w['source_V16_world_file_sha256']=old_sha
 # Same tank and demand. Correct the shared availability rule,not tank capacity.
 if w['assets']['water_heater']['present']:
  before=w['routine']['tank_heat_window_min'][:];last=w['routine']['bath_start_min']+10*w['N'];w['routine']['tank_heat_window_min'][1]=max(before[1],last)
  w['parameter_pack']['control_defaults']['water_heater']['pre_heat_window_end_h']=w['routine']['tank_heat_window_min'][1]/60
  w['assets']['water_heater']['config']['pre_heat_window_end_h']=w['routine']['tank_heat_window_min'][1]/60
  w['reference_change_ledger'].append({'field':'reference_WH_heat_end_min','before':before[1],'after':w['routine']['tank_heat_window_min'][1],'rule':'cover last immutable bath need;capacity120L,power3kW,mixed target unchanged','scope':'designed baseline availability rule,not observed diary'})
 w['evidence_layer']['previous_date_sampling_frame']=w['date_sampling_frame']
 w['date_sampling_frame']={'reference_year':2025,'scope':'conditional input-legal active-event dates','annual_energy_extrapolation_permitted':False,'B_results_used_for_eligibility':False}
 w['parameter_pack_sha256']=digest(w['parameter_pack']);w['protocol_sha256']=digest(PROTOCOL);w['world_content_sha256']=digest({k:v for k,v in w.items() if k!='world_content_sha256'})
 weather=weather_lookup(h['weather']['path']);frames=collections.defaultdict(list);ineligible=[];cache={}
 for j in range(365):
  date=dt.date(2025,1,1)+dt.timedelta(days=j);key=pattern(w,date,weather)
  if key not in cache:cache[key]=bool(candidates(w,date,weather))
  if cache[key]:frames[(date.month-1)//3+1].append(date)
  else:ineligible.append(str(date))
 # Household-specific quota is kept at the already declared quarter counts.
 quotas=collections.Counter((dt.date.fromisoformat(r['date']).month-1)//3+1 for r in h['rounds']);dates=[]
 for quarter in [1,2,3,4]:
  assert len(frames[quarter])>=quotas[quarter],('not enough input-legal dates',w['household_id'],quarter)
  chosen=sorted(frames[quarter],key=lambda d:rank('contrast50-v1',w['household_id'],str(d)))[:quotas[quarter]]
  dates.extend({'date':str(d),'quarter':quarter,'eligible_frame_days':len(frames[quarter]),'conditional_inclusion_probability':quotas[quarter]/len(frames[quarter])} for d in chosen)
 dates.sort(key=lambda r:r['date']);w['random10_date_selection']={'reference_year':2025,'dates':dates,'algorithm':'SHA randomized within predeclared input-legal active-event date frame','annual_energy_extrapolation_permitted':False,'outcome_independent':True,'all_dates_frozen_before_EP':True,'quarters':dict(quotas),'eligibility_is_conditional_design_not_all_365days':True}
 w['world_content_sha256']=digest({k:v for k,v in w.items() if k!='world_content_sha256'});save(OUT/'worlds'/f'{w["household_id"]}.json',w)
 save(OUT/'actors'/f'{w["household_id"]}.json',read(SRC/'actors'/f'{w["household_id"]}.json'))
 usage=collections.Counter();records=[]
 for i,row in enumerate(dates,1):
  qs=candidates(w,dt.date.fromisoformat(row['date']),weather);assert qs
  q=min(qs,key=lambda x:(usage[x['proposal']['family']],rank(qs[0]['case_id'],x['proposal']['family'],x['proposal']['amount'],x['proposal']['target_asset_id'])))
  usage[q['proposal']['family']]+=1;q['round_index']=i;q['date_selection']=row;assert not validate(q)
  assert q['A']!=q['B'];save(OUT/'pairs'/w['household_id']/f'{i:02d}.json',q)
  records.append({'round_index':i,'date':row['date'],'pair_path':f'pairs/{w["household_id"]}/{i:02d}.json','pair_sha256':sha(OUT/'pairs'/w['household_id']/f'{i:02d}.json'),'proposal_family':q['proposal']['family'],'event_window_min':q['event_window_min']})
 save(OUT/'eligibility_frames'/f'{w["household_id"]}.json',{'eligible_dates':{q:list(map(str,x)) for q,x in frames.items()},'ineligible_dates':ineligible,'basis':'A opportunity + future legal reference controls;no EnergyPlus/B/human results used','pattern_cache_count':len(cache)})
 return {**h,'world_path':f'worlds/{w["household_id"]}.json','world_sha256':sha(OUT/'worlds'/f'{w["household_id"]}.json'),'parameter_pack_sha256':w['parameter_pack_sha256'],'rounds':records,'new_frame_counts':{q:len(x) for q,x in frames.items()}}
if __name__=='__main__':
 assert sys.platform=='linux';assert not (OUT/'SELECTION50.json').exists(),'new versions only'
 save(OUT/'PROTOCOL.json',PROTOCOL);old=read(PILOT/'SELECTION50.json');rows=[]
 with concurrent.futures.ProcessPoolExecutor(max_workers=16) as pool:
  for h in pool.map(one,old['records']):rows.append(h);print({'generated_households':len(rows),'total':50},flush=True)
 save(OUT/'SELECTION50.json',{'households':50,'pairs':500,'records':rows,'method':'same fifty household anchors;predeclared conditional input-eligible date sampling;no B-result/human selection','previous_diagnostic_dates_preserved_at':str(PILOT),'source_old_selection_sha256':sha(PILOT/'SELECTION50.json')})
 save(OUT/'EXECUTION_AUTHORIZATION.json',{'user_feedback':'我看了几个a/b基本上没差异这咋收集','scope':'corrected contrasts within already authorized50 household server development test','selection_sha256':sha(OUT/'SELECTION50.json'),'EP_scope_hold_lifted_for_selected50':True,'full1000_EP_authorized':False,'human_collection_release':False,'training_release':False})
