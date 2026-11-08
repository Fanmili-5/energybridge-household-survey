from pathlib import Path
from collections import Counter
import hashlib, importlib.util, json, sys

ROOT=Path(__file__).resolve().parent
BASE=ROOT.parent
V4=BASE/'v4'
V5=BASE/'v5'
V6=BASE/'v6'
COUNTRIES=('CN','US','GB','ES','IN','MX')
QUOTAS={'A':166,'B':198,'C':125,'D':151,'E':156,'F':204}
MATRIX={'A':[28,28,28,28,27,27],'B':[33]*6,'C':[21,21,21,21,21,20],
        'D':[25,25,25,25,25,26],'E':[26]*6,'F':[34]*6}
KEY={'AC':'space_ac_available','WM':'washer_available','DR':'dryer_available','DW':'dishwasher_available','WH':'water_heater_available','EV':'home_vehicle_charging'}
WORK={'employed','employed_full_time','employed_part_time'}

def rank(*xs):return hashlib.sha256(json.dumps(['EB7-country-role-20261107',*xs],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
def fact(v,fs=(),status='observed',**kw):return dict(value=v,fields=list(fs),status=status,**kw)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write_json(p,d):Path(p).write_text(json.dumps(d,ensure_ascii=False,indent=2,sort_keys=True,default=lambda x:x.item())+'\n')
def write_rows(p,rs):Path(p).write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True,separators=(',',':'),default=lambda x:x.item())+'\n' for r in rs))
def rows(p):return [json.loads(x) for x in Path(p).read_text().splitlines()]
def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m

def libraries():
    sys.path.insert(0,str(V4))
    import legacy_components as components
    activity=load_module('activity_model',V5/'activity_model.py')
    weekend=load_module('weekend_model',V5/'weekend_model.py')
    control=load_module('control_inventory',V5/'control_inventory.py')
    services=load_module('service_contracts_v6',V6/'service_contracts.py')
    return components,activity,weekend,control,services
