
"""Source parking opportunity -> fixed connected-episode reference condition.

This does not claim observed plugging or consent. The reference condition is
shared by A and B and cannot be extended by either proposal.
"""
from .common import digest

ORIGIN='given_source_parking_episode'
VERSION='eb.source_connected_parking_episode.v1'

def attach(context,episode):
    e={k:v for k,v in episode.items() if k!='binding_sha256'}
    bind=context['native_execution_contract']
    e['household_case_sha256']=bind['household_case_sha256']
    e['household_input_manifest_sha256']=bind['household_input_manifest_sha256']
    e['version']=VERSION
    e['need_id']=next(r['need_id'] for r in context['physical_ev_connections'] if r['origin']==ORIGIN)
    for row in context['physical_ev_connections']:
        if row['need_id']==e['need_id']:
            e['context_connection_interval']=[row['start_min'],row['end_min']]
    e['connection_state_is_reference_condition_not_observed_plugging']=True
    e['connection_state_is_shared_by_AB']=True
    e['binding_sha256']=digest(e)
    bind['source_connected_episode']=e
    return context

def valid(context):
    bind=context.get('native_execution_contract') or {}
    e=bind.get('source_connected_episode')
    if not isinstance(e,dict) or e.get('version')!=VERSION:return False
    h=e.get('binding_sha256');body={k:v for k,v in e.items() if k!='binding_sha256'}
    if not h or digest(body)!=h:return False
    source=context.get('source') or {}
    for key in ('household_case_sha256','household_input_manifest_sha256'):
        if not e.get(key) or e[key]!=bind.get(key) or e[key]!=source.get(key):return False
    if not e.get('connection_state_is_reference_condition_not_observed_plugging') or not e.get('connection_state_is_shared_by_AB'):return False
    rows=[r for r in context.get('physical_ev_connections',[]) if r.get('origin')==ORIGIN]
    if len(rows)!=1:return False
    row=rows[0]
    if row.get('need_id')!=e.get('need_id') or [row.get('start_min'),row.get('end_min')]!=e.get('context_connection_interval'):return False
    a,z=e.get('connection_interval',[None,None]);lo,hi=e.get('physical_home_witness',[None,None])
    if not all(type(v) is int for v in (a,z,lo,hi)) or not lo<=a<z<=hi:return False
    if not e.get('mapped_operator_id') or not e.get('source_driver_member_id') or not e.get('asset_id'):return False
    return True

def covers(context,plan):
    if not valid(context):return False
    e=context['native_execution_contract']['source_connected_episode']
    lo,hi=e['context_connection_interval'];aid=e['asset_id'];nid=e['need_id']
    if any(o['asset_id']==aid and o['kind'] in ('EV_plug','EV_unplug') for o in plan['operations']):return False
    for r in plan['controls']:
        if r['kind']!='ev_charge_window':continue
        if r['asset_id']!=aid or r.get('need_id')!=nid or not lo<=r['start_min']<r['end_min']<=hi:return False
    return True
