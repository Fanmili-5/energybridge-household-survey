"""Synthetic causal interventions, not generated actor cases or feedback."""
import copy
from common import *
from execution import realize
def op(kind,a,b,who,name):return {'operation_id':name,'operator_id':who,'need_id':'test-trip','kind':kind,'start_min':a,'end_min':b}
def main():
 school_guard();rows=[];counts={}
 for h in read(OUT/'SELECTION50.json')['records']:
  w=read(OUT/h['world_path']);ev=next((d for d in w['parameter_pack']['devices'] if 'ev' in d['types']),None)
  if not ev:continue
  who=w['members'][0]['member_id'];ws={who:[[0,1440]]};aid=ev['asset_id']
  need={'need_id':'test-trip','kind':'ev','asset_id':aid,'trip_departure_min':600,'release_min':720,'quantity':10.,'deadline_min':600}
  controls=[{'asset_id':aid,'kind':'ev_charge_window','start_min':0,'end_min':1440}]
  for kind in ('connected_departure_failure','low_SOC_departure_failure','successful_departure_away'):
   ww=copy.deepcopy(w)
   if kind=='connected_departure_failure':ops=[op('EV_plug',0,10,who,'a-plug'),op('EV_unplug',610,620,who,'b-unplug')]
   elif kind=='low_SOC_departure_failure':ww['reference_initial_states']['EV_SOC']=.05;ops=[op('EV_plug',610,620,who,'a-plug')]
   else:ops=[op('EV_plug',610,620,who,'a-away-plug'),op('EV_plug',720,730,who,'b-home-plug')]
   result=realize(ww,{'tasks':[],'controls':controls,'operations':ops},ws,[need]);trace=result['vehicle_causal_trace'];trip=trace['diagnostics'][0]
   if kind=='successful_departure_away':
    assert trip['trip_departed'] and not result['operations'][0]['succeeded'] and result['operations'][0]['failure_reason']=='vehicle_away' and result['operations'][1]['succeeded']
    assert sum(trace['grid_W'][aid][60:72])==0
   else:assert not trip['trip_departed'] and trip['traction_delivered_kWh']==0 and result['operations'][-1]['succeeded'] and trace['actual_trip_windows']==[]
   rows.append({'household_id':h['household_id'],'kind':kind,'passed':True,'trip':trip,'operations':result['operations']})
   counts[kind]=counts.get(kind,0)+1
  washer=next((d for d in w['parameter_pack']['devices'] if 'washer' in d['types']),None)
  if washer:
   task={'task_id':'test-wash','need_id':'test-wash','asset_id':washer['asset_id'],'kind':'washer','start_min':20,'end_min':140}
   n={'need_id':'test-wash','kind':'washer','delivery_deadline_min':900,'wearable_clothes_ready_after_required_chain':False}
   load={'operation_id':'a-load','operator_id':who,'need_id':'test-wash','kind':'load','start_min':0,'end_min':10}
   result=realize(w,{'tasks':[task],'controls':controls,'operations':[load,op('EV_plug',0,10,who,'b-plug')]},ws,[n])
   assert next(o for o in result['operations'] if o['kind']=='EV_plug')['failure_reason']=='operator_resource_conflict'
   rows.append({'household_id':h['household_id'],'kind':'shared_wet_EV_operator_conflict','passed':True});counts['shared_wet_EV_operator_conflict']=counts.get('shared_wet_EV_operator_conflict',0)+1
  if counts['connected_departure_failure']>=20:break
 save(OUT/'VEHICLE_CAUSAL_NEGATIVE_CONTROLS.json',{'status':'pass','counts':counts,'records':rows,
  'synthetic_not_real_actor_case':True,'source_counterexample':'V21/development/JOINT_VEHICLE_CAUSAL_COUNTEREXAMPLE.json','single_vehicle_energy_and_presence_authority':True,'EP_started':0,'human_answers':0})
 print(counts,flush=True)
if __name__=='__main__':main()

