"""One immutable experimental world feeds every task and physical projection."""
import hashlib, json, re, sys, os
from pathlib import Path
OUT = Path(__file__).resolve().parent.parent
BASE = OUT.parent
REPO = BASE.parents[3]
V7 = BASE / 'idf_joint_production_20261005'
V9 = BASE / 'production_evidence_completion_20261006'
V10 = BASE / 'joint_housing_service_worlds_20261006'
V11 = BASE / 'operational_evidence_completion_20261006'
V12 = BASE / 'complete_reference_worlds_20261006_v12'
UP = REPO / 'upstream_2b17ae6'
EP_ROOT = Path(os.environ.get('EB_EP_ROOT','/Applications/EnergyPlus-24-1-0'))
ENGINE = EP_ROOT/'energyplus'
sys.path[:0] = json.loads((V7/'RUNTIME.json').read_text())['stable_PYTHONPATH'].split(':')
def read(p): return json.loads(Path(p).read_text())
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for block in iter(lambda:f.read(4194304),b''): h.update(block)
    return h.hexdigest()
def canonical(d): return json.dumps(d,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':'))
def digest(d): return hashlib.sha256(canonical(d).encode()).hexdigest()
def save(p,d):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def guard():
    if (OUT/'PACKAGE_MANIFEST.json').exists(): raise SystemExit('sealed; use read-only audit or new version')
def rank(hid,label): return int(hashlib.sha256((hid+'/'+label+'/assembly-v1').encode()).hexdigest()[:16],16)
def parse(p): return [[v.strip() for v in q.split(',')] for q in re.sub(r'!.*','',Path(p).read_text()).split(';') if q.strip()]
def dump(rows): return '\n'.join(',\n  '.join(str(x) for x in row)+';' for row in rows)+'\n'
SCHEMA=read(EP_ROOT/'Energy+.schema.epJSON')
def obj(kind,values):
    fields=SCHEMA['properties'][kind]['legacy_idd']['fields'];last=max(fields.index(k) for k in values)
    return [kind]+[values.get(f,'') for f in fields[:last+1]]
def get(row,field):
    i=SCHEMA['properties'][row[0]]['legacy_idd']['fields'].index(field)+1
    return row[i] if i<len(row) else ''
def put(row,field,value):
    i=SCHEMA['properties'][row[0]]['legacy_idd']['fields'].index(field)+1
    row.extend(['']*max(0,i+1-len(row)));row[i]=value
