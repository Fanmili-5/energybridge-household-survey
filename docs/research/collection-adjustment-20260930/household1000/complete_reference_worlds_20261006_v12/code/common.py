"""Isolated source-backed completion; earlier sealed stages stay read-only."""
import json,hashlib,sys
from pathlib import Path
OUT=Path(__file__).resolve().parent.parent;BASE=OUT.parent
V7=BASE/'idf_joint_production_20261005';V8=BASE/'household_housing_evidence_20261006';V9=BASE/'production_evidence_completion_20261006';V10=BASE/'joint_housing_service_worlds_20261006';V11=BASE/'operational_evidence_completion_20261006'
sys.path[:0]=json.loads((V7/'RUNTIME.json').read_text())['stable_PYTHONPATH'].split(':')
def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,d):Path(p).write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def guard():
 if (OUT/'PACKAGE_MANIFEST.json').exists():raise SystemExit('sealed;read-only audit only')
def parse(p):
 import re
 return [[x.strip() for x in item.split(',')] for item in re.sub(r'!.*','',Path(p).read_text()).split(';') if item.strip()]
def dump(rows):return '\n'.join(',\n  '.join(str(x) for x in r)+';' for r in rows)+'\n'
SCHEMA=read('/Applications/EnergyPlus-24-1-0/Energy+.schema.epJSON')
def obj(kind,values):
 fields=SCHEMA['properties'][kind]['legacy_idd']['fields'];last=max(fields.index(k) for k in values);return [kind]+[values.get(f,'') for f in fields[:last+1]]
