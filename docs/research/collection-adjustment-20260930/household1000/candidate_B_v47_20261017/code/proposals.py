"""Command comparison and existing-operation resource helpers."""
import math
from common import *

def replace_control(plan,old,parts):
    ix=plan['controls'].index(old);plan['controls'][ix:ix+1]=parts

def command_signature(plan):
    controls=[]
    for x in plan['controls']:
        if x['kind']=='ev_charge_window':
            controls.append({k:x[k]for k in ('kind','asset_id','need_id','start_min','end_min','stop_at_target_soc')if k in x})
        else:controls.append(x)
    return digest({'tasks':plan['tasks'],'operations':plan['operations'],'controls':controls})

def operation_slot(c,plan,old,earliest,latest,preferred):
    other=[o for o in plan['operations']if o['operation_id']!=old['operation_id']]
    for t in sorted(range(math.ceil(earliest/10)*10,math.floor((latest-10)/10)*10+1,10),key=lambda t:(abs(t-preferred),t)):
        day=next((d for d in c['days']if d['date']==str(dt.date.fromisoformat(c['date'])+dt.timedelta(days=t//1440))),None)
        if day is None:continue
        local=t%1440
        if not any(a<=local and local+10<=b for a,b in day['activity']['operator_windows_min'].get(old['operator_id'],[])):continue
        if any(overlap((t,t+10),(o['start_min'],o['end_min']))and(old['operator_id']==o['operator_id']or old['room_id']==o['room_id'])for o in other):continue
        base=t//1440*1440
        blocks=[(r['room_id'],base+r['start_min'],base+r['end_min'])for r in day['shared']['facility_reservations']]
        blocks +=[(old['_bath_room'],base+m,base+m+10)for m in day['activity']['family_context']['bath_times_min'].values()]
        if any(room==old['room_id']and overlap((t,t+10),(lo,hi))for room,lo,hi in blocks):continue
        return t
    return None
