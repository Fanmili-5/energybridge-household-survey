"""Refresh dated room/activity projections without reallocating EB types or roles."""
import copy,datetime as dt
from common import digest
from activity_model import dated,ranges,room_map
merge_ranges=ranges

def refresh(w):
    w=copy.deepcopy(w);w.pop('world_content_sha256',None)
    w['activity_contract']['room_map']=room_map(w)
    w['activity_contract']['meal_location_reference']='given living/dining co-use;combined bed/living for studio;not inferred kitchen dining or measured furniture/seating capacity'
    if 'type_generation_evidence'in w:w['type_generation_evidence']['hardware_parameters']='EB engineering parameter families retained;AC quantity,room installations and home/circuit planning bounds rebuilt under explicit all-household AC condition'
    w['schema']='eb.fixed_family_housing_reference_world.v32'
    w['world_content_sha256']=digest(w)
    example=[dated(w,dt.date(2025,2,17)+dt.timedelta(days=i))for i in range(7)]
    for m in w['members']:
        mid=m['member_id']
        m['weekly_calendar']=[{'weekday':i,'example_date':d['date'],'day_type':d['day_type'],'intervals':d['member_calendars'][mid]}for i,d in enumerate(example)]
        m['daily_reference_specs']=[{'weekday':i,'example_date':d['date'],**d['member_specs'][mid]}for i,d in enumerate(example)]
    for o in w['operating_context']['operators']:
        o['weekly_windows_min']={str(i):d['operator_windows_min'][o['operator_id']]for i,d in enumerate(example)}
    w['routine']['weekly_family_context']=[{'weekday':i,'example_date':d['date'],**d['family_context']}for i,d in enumerate(example)]
    w['parameter_pack_sha256']=digest(w['parameter_pack'])
    w.pop('world_content_sha256');w['world_content_sha256']=digest(w)
    return w
