"""Concrete design regressions:recovery, VPP causality, unique doses and separate meters."""
import sys,collections
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *
from proposals import command_signature
from event_proposals import make,eligible,ev,thermal,mechanism_eligibility
from planner import allocate
from joint_timing import program_target
from events import for_case,known_load_series,response_reference
from assess import assess
from recovery import reference_recovery

def main():
 bindings=read(A_STAGE/'A_BINDINGS10000.json')['records'];r=bindings[0];w=read(A_STAGE/r['A_world_path']);fixture=None
 for k in r['cases']:
  c=read(A_STAGE/k['path']);pool,_=eligible(c)
  if pool['ev']and all(abs(x['battery_energy_kWh']-2.5)<1e-7 for x in pool['ev']):fixture=c,pool['ev'];break
 assert fixture is not None
 c,pool=fixture;event={'start_min':1080,'end_min':1140,'direction':'down'};widths=[];plans=[]
 for l in range(4):
  p=copy.deepcopy(c['A']);z=ev(p,w,c,pool,event,l,short=True);widths.append(z['window_B_min'][1]-z['window_B_min'][0]);plans.append(p)
  assert p['operations']==c['A']['operations']
 assert widths==[90,30,10,10]and command_signature(plans[2])==command_signature(plans[3])
 # Event timing changes the executable charging request, while human visits stay fixed.
 p=copy.deepcopy(c['A']);ev(p,w,c,pool,{**event,'start_min':900,'end_min':960},0,short=True)
 assert command_signature(p)!=command_signature(plans[0])and p['operations']==plans[0]['operations']
 a=for_case(w,c);otherw=copy.deepcopy(w);otherw['household_id']='unrelated';otherw['human_answers']='arbitrary';otherw['parameter_pack']={}
 assert a==for_case(otherw,c)
 c0=copy.deepcopy(c);c0['VPP_events']=for_case(w,c0);c1=copy.deepcopy(c0)
 for e in c0['VPP_events']:e['target_kw']=.5
 for e in c1['VPP_events']:e['target_kw']=2.
 idx=(-rank(w['household_id'],'mechanism_rotation'))%10
 p0,_=make(w,c0,idx);p1,_=make(w,c1,idx)
 assert command_signature(p0)!=command_signature(p1)
 # Original22:30 collision remains an error;conditional22:40 retrieval clears the machine.
 old=read(BASE/'candidate_B_v35_20261016/runs/8aeb7c583a0cd1e9/pairs/ordinary-v6-0002/2025-03-25.json');oldw=read(BASE/'normal_A_v34_1_20261016'/old['A_source']['world_path']);oldc={k:old[k]for k in('A','date','days','needs_A','case_id')}
 rec=reference_recovery(oldw,oldc,old['B']);assert any(x['requested_start_min']==1350 and x['reference_start_min']==1360 for x in rec['operation_adjustments'])
 # A dedicated EV bay cannot manufacture a dwelling inlet overload.
 y=copy.deepcopy(w);fixed=known_load_series({**c['A'],'controls':[]},w);peak=max(v for m,v in fixed.items()if 480<=m<4320)+w['parameter_pack']['background_reserved_kw'];y['parameter_pack']['home_service_limit_kw']=peak+.01
 assert not any(x['code']=='REQUESTED_KNOWN_POWER_EXCEEDS_INLET'for x in assess(y,c,c['A'])['constraint_flags'])
 y['parameter_pack']['home_service_limit_kw']=peak-.01
 assert any(x['code']=='REQUESTED_KNOWN_POWER_EXCEEDS_INLET'for x in assess(y,c,c['A'])['constraint_flags'])
 # Analytic shift fixture:1.5kW for one hour moves after event;event response1.5kW,post energy+1.5kWh,primary delta0.
 toyw={'parameter_pack':{'devices':[{'asset_id':'washer','parameters':{'power_kw':1.5},'types':['washer']}]}}
 toya={'tasks':[{'asset_id':'washer','kind':'washer','start_min':600,'end_min':660}],'operations':[],'controls':[]}
 toyb={'tasks':[{'asset_id':'washer','kind':'washer','start_min':660,'end_min':720}],'operations':[],'controls':[]}
 ref=response_reference(toyw,{'A':toya},toyb,[{'event_id':'toy','start_min':600,'end_min':660,'direction':'down','target_kw':1}],{'conditional_recovery_reference':{'realized_tasks':toyb['tasks']}})
 assert ref['events'][0]['requested_known_response_average_kw']==1.5 and ref['events'][0]['requested_post2h_extra_kWh']==1.5 and ref['known_load_requested_primary_delta_kWh']==0
 # Up-request direction is independent of daily maximum, including the
 # previously cold 20:00 example; dual bounds cannot cross at strong doses.
 rows={r['household_id']:r for r in bindings};tr=rows['ordinary-v6-0251'];tw=read(A_STAGE/tr['A_world_path']);tc=read(A_STAGE/next(x['path']for x in tr['cases']if x['date']=='2025-09-25'));te=for_case(tw,tc)[0];tp,_=eligible(tc)
 assert te['direction']=='up'
 thermal_plans=[]
 for maximum in(-20,50):
  altered=copy.deepcopy(tc)
  for day in altered['days']:day['weather']['maximum_C']=maximum
  plan=copy.deepcopy(altered['A']);change=thermal(plan,tw,altered,tp['ac'],te,2);thermal_plans.append(plan)
  assert change['heating_delta_C']>=0 and change['cooling_delta_C']<=0 and change['response_status']=='uncertain_pending_physics'
  assert all(x['cooling_setpoint_C']-x['heating_setpoint_C']>=2.-1e-8 for x in plan['controls']if x['kind']=='ac_setpoint')
 assert command_signature(thermal_plans[0])==command_signature(thermal_plans[1])
 # Multi-event up: preserving noon charging avoids making an evening
 # request silently destroy the already served noon request.
 mr=rows['ordinary-v6-0369'];mw=read(A_STAGE/mr['A_world_path']);mc=read(A_STAGE/next(x['path']for x in mr['cases']if x['date']=='2025-12-01'));mes=for_case(mw,mc);mp,_=eligible(mc)
 assert len(mes)==2 and all(e['direction']=='up'for e in mes)
 joint=copy.deepcopy(mc);joint['_joint_events']=mes;plan=copy.deepcopy(mc['A']);evchange=ev(plan,mw,joint,mp['ev'],mes[-1],0)
 assert evchange['window_B_min'][0]==evchange['window_A_min'][0] and evchange['joint_timing_basis'].startswith('preserve_A')
 joint['VPP_events']=mes;joint['input_design_assignment']={'mechanism':'thermal_setpoint','focus_event_id':mes[-1]['event_id'],'multi_event_policy':'joint_all_events','eligibility_checked_before_B':True}
 plan,q=make(mw,joint,0)
 assert set(q['joint_event_ids_considered'])=={e['event_id']for e in mes}
 assert {x['event_id']for x in q['changes']}=={e['event_id']for e in mes}
 # Deliberate bad/reverse requests survive; physical labels stay unknown.
 joint['input_design_assignment']['mechanism']='reverse_direction';_,badq=make(mw,joint,0)
 assert all(x['deliberate_reverse_direction']for x in badq['changes'])
 # Gap selection considers the union before any B exists.
 e1={'event_id':'one','start_min':600,'end_min':660,'direction':'down'};e2={'event_id':'two','start_min':720,'end_min':780,'direction':'down'}
 target,basis=program_target({'_joint_events':[e1,e2]},e1,{'start_min':600},60,{'end_min':590},{'release_min':480,'deadline_min':900},720)
 assert target==660 and basis.startswith('avoid_union')
 # No heater is assigned to 0001 and then converted to washer timer.
 design=allocate(bindings[:2])
 for r0 in bindings[:2]:
  for rr0 in r0['cases']:
   a0=design['assignments'][rr0['case_id']];cc=read(A_STAGE/rr0['path'])
   assert mechanism_eligibility(cc)[a0['mechanism']]
   if r0['household_id']=='ordinary-v6-0001':assert a0['mechanism']not in('hotwater_preheat','hotwater_target')
 # The saved per-device event is authoritative for multi-event narratives.
 nr=rows['ordinary-v6-0050'];nw=read(A_STAGE/nr['A_world_path']);nn=next((i,x)for i,x in enumerate(nr['cases'])if x['date']=='2025-12-23');nc=read(A_STAGE/nn[1]['path']);nc['VPP_events']=for_case(nw,nc)
 nc['input_design_assignment']=read(OUT/'INPUT_COVERAGE_PLAN.json')['assignments'][nc['case_id']]
 np,nq=make(nw,nc,nn[0]);tankch=next(x for x in nq['changes']if x['device_family']=='water_heater')
 assert tankch['selected_event_id']!=nq['focus_VPP_event_id']
 from event_proposals import tank_description
 ne=next(x for x in nc['VPP_events']if x['event_id']==tankch['selected_event_id'])
 no=next(x for x in nc['A']['controls']if x['kind']=='tank_setpoint'and x['asset_id']==tankch['asset_id']and[x['start_min'],x['end_min']]==tankch['window_A_min'])
 nps=[x for x in np['controls']if x['kind']=='tank_setpoint'and x['asset_id']==tankch['asset_id']and[x['start_min'],x['end_min']]in tankch['segments_B_min']]
 assert tankch['description']==tank_description(np,no,nps,ne,False)
 report={'per_device_event_binding_narrative_passed':True,'all_window_union_gap_fixture_passed':True,'up_EV_noon_service_preserved':True,'joint_thermal_covers_both_events':True,'preassignment_eligibility_fixture_passed':True,'thermal_direction_independent_of_daily_maximum':True,'dual_bounds_minimum_gap_preserved':True,'deliberate_reverse_candidates_retained':True,'analytic_event_shift_and_rebound_fixture_passed':True,'passed':True,'EV2_5kWh_minutes':widths,'EV_actual_unique_doses':3,'event_time_changes_actual_command':True,'request_target_changes_actual_command':True,'EV_manual_operations_unchanged':True,'station_date_requests_independent_of_household_and_answers':True,'conditional22_40_recovery_retained':True,'independent_EV_feed_not_counted_against_dwelling_inlet':True,'real_dwelling_overload_still_flagged':True}
 save(STAGE/'REGRESSION_RESULTS.json',report);print(canonical(report))
if __name__=='__main__':main()
