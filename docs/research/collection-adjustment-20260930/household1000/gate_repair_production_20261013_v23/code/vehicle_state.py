"""Vehicle state within the shared causal resource/event ledger."""
from common import overlap
class VehicleState:
 def __init__(self,w,plan):
  self.ev=next((d for d in w['parameter_pack']['devices'] if 'ev' in d['types']),None)
  self.plan=plan;self.connected_start=None;self.connections=[];self.away=[];self.diagnostics=[];self.grid=[];self.states=[]
  self.soc=w['reference_initial_states']['EV_SOC']
 def available(self,o):return not any(overlap((o['start_min'],o['end_min']),ab) for ab in self.away)
 def operate(self,o):
  if self.ev is None:return 'EV_missing'
  if o['kind']=='EV_plug':
   if self.connected_start is not None:return 'already_connected'
   self.connected_start=o['end_min']
  else:
   if self.connected_start is None:return 'not_connected'
   self.connections.append({'asset_id':self.ev['asset_id'],'start_min':self.connected_start,'end_min':o['start_min']});self.connected_start=None
  return None
 def trip(self,n,minute):
  if self.ev is None:return
  q=self.ev['parameters'];before=self.soc;required=n['quantity'];short=max(0.,required-before*q['capacity_kwh'])
  conflict=self.connected_start is not None and self.connected_start<=minute;success=not conflict and short<1e-10
  if success:
   self.away.append([minute,n['release_min']])
   if minute>=0:self.soc-=required/q['capacity_kwh']
  if minute>=0:self.diagnostics.append({'absolute_min':minute,'trip_energy_shortfall_kWh':short,'SOC_before':before,
   'trip_departed':success,'traction_delivered_kWh':required if success else 0.,'departure_connection_conflict':conflict,
   'travel_mode_if_service_failed':None,'actual_vehicle_away_until':n['release_min'] if success else None})
 def charge(self,minute):
  if self.ev is None:return
  aid=self.ev['asset_id'];q=self.ev['parameters']
  c=next((c for c in self.plan['controls'] if c['asset_id']==aid and c['start_min']<=minute<c['end_min']),None)
  present=not any(a<=minute<b for a,b in self.away);kwh=0.
  if c and present and self.connected_start is not None and self.connected_start<=minute:
   kwh=min(q['charger_kw']/6,max(0.,q['target_soc']-self.soc)*q['capacity_kwh']/q.get('efficiency',.92));self.soc+=kwh*q.get('efficiency',.92)/q['capacity_kwh']
  assert -1e-9<=self.soc<=1+1e-9
  self.grid.append(kwh*6000);self.states.append(self.soc)
 def final(self,horizon):
  if self.ev is None:return {'connections':[],'grid_W':{},'SOC_after_step':{},'diagnostics':[],'actual_trip_windows':[]}
  if self.connected_start is not None:self.connections.append({'asset_id':self.ev['asset_id'],'start_min':self.connected_start,'end_min':horizon,'unplug_missing':True})
  assert len(self.grid)==horizon//10
  return {'connections':self.connections,'grid_W':{self.ev['asset_id']:self.grid},'SOC_after_step':{self.ev['asset_id']:self.states},
   'diagnostics':self.diagnostics,'actual_trip_windows':[ab for ab in self.away if ab[1]>0],
   'ordering':'shared manual-resource operations,departure,program,charging10min; return is actual interval end',
   'past_carry':'negative-time presence/connection carried; battery initialized at time0 without prehistory energy double count',
   'other_activities':'fixed given commitments remain conditional; alternative transport or actual rescheduling unknown'}
