"""Read the final IDF schedules back independently of the schedule writer."""
import gzip
from functools import lru_cache
from core import *

@lru_cache(maxsize=8)
def pack(hid):return read(ROOT/'inputs/households'/f'{hid}.json.gz')

def schedules(rows):
    output={}
    for row in rows:
        if row[0].lower()!='schedule:compact':continue
        periods=[];current=None;i=3
        while i<len(row):
            value=row[i]
            if value.lower().startswith('through:'):
                md=tuple(map(int,value.split(':',1)[1].strip().split('/')))
                current=[];periods.append((md,current))
            elif value.lower().startswith('until:'):
                h,m=map(int,value.split(':',1)[1].strip().split(':'));current.append((h*60+m,float(row[i+1])));i+=1
            i+=1
        output[row[1].lower()]=periods
    return output

def at(series,date,minute):
    for md,seq in series:
        if (date.month,date.day)<=md:
            return next(v for end,v in seq if minute<end)
    raise ValueError('MISSING_SCHEDULE_DATE')

def audit(pair,side,folder,inputs):
    import hashlib
    folder=Path(folder);raw=gzip.decompress((folder/'model.idf.gz').read_bytes())if(folder/'model.idf.gz').exists()else(folder/'model.idf').read_bytes()
    errors=[]
    if hashlib.sha256(raw).hexdigest()!=inputs['idf_sha256']:errors.append({'code':'ARCHIVED_IDF_HASH'})
    ss=schedules(parse_idf(raw.decode()));w=pack(pair['household_id']);date=dt.date.fromisoformat(pair['date'])
    hi=min(4320,max(1920,inputs['actual_intervention_end_min']or 1920));control_map={}
    for c in pair[side]['controls']:
        for t in range(max(480,c['start_min']),min(hi,c['end_min']),10):control_map[(c['asset_id'],c['kind'],t)]=c
    for hvac in w['HVAC']:
        for t in range(480,hi,10):
            day=date+dt.timedelta(days=t//1440);local=t%1440+5;c=control_map.get((hvac['asset_id'],'ac_setpoint',t))
            expected={'available':int(c is not None),'fan_mode':c['fan_operating_mode']if c else 0,
                      'heat_sp':c['heating_setpoint_C']if c else 5,'cool_sp':c['cooling_setpoint_C']if c else 50}
            for key,name in hvac['schedule_names'].items():
                if abs(at(ss[name.lower()],day,local)-expected[key])>1e-8:
                    errors.append({'code':'IDF_CONTROL_NOT_EQUAL_FROZEN_REQUEST','side':side,'asset':hvac['asset_id'],'minute':t,'channel':key});break
    tank=next((d for d in w['world']['parameter_pack']['devices']if 'water_heater'in d['types']),None)
    if tank:
        for t in range(480,hi,10):
            c=control_map.get((tank['asset_id'],'tank_setpoint',t));expected=c['value_C']if c else 10
            if abs(at(ss['tank_target'],date+dt.timedelta(days=t//1440),t%1440+5)-expected)>1e-8:
                errors.append({'code':'IDF_TANK_CONTROL_NOT_EQUAL_FROZEN_REQUEST','minute':t})
    return errors[:20]
