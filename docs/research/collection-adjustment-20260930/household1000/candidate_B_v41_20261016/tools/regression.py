"""Concrete design regressions:recovery, VPP causality, unique doses and separate meters."""
import sys,collections
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *
from proposals import command_signature
from event_proposals import make,eligible,ev
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
 report={'analytic_event_shift_and_rebound_fixture_passed':True,'passed':True,'EV2_5kWh_minutes':widths,'EV_actual_unique_doses':3,'event_time_changes_actual_command':True,'request_target_changes_actual_command':True,'EV_manual_operations_unchanged':True,'station_date_requests_independent_of_household_and_answers':True,'conditional22_40_recovery_retained':True,'independent_EV_feed_not_counted_against_dwelling_inlet':True,'real_dwelling_overload_still_flagged':True}
 save(STAGE/'REGRESSION_RESULTS.json',report);print(canonical(report))
if __name__=='__main__':main()
