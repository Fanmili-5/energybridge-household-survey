"""Paths, deterministic identities and byte bindings for normal A production."""
import datetime as dt
import hashlib
import json
import gzip
import os
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1]
BASE = OUT.parent
REPO = BASE.parents[3]
MASTER = BASE / 'household_master_v33_20261016'
EP_SCHEMA=Path(os.environ.get('EB_EP_ROOT','/Applications/EnergyPlus-24-1-0'))/'Energy+.schema.epJSON'
sys.path[:0] = json.loads((BASE/'idf_joint_production_20261005/RUNTIME.json').read_text())['stable_PYTHONPATH'].split(':')
ANCHOR = dt.date(2024, 12, 15)
END = dt.date(2026, 1, 15)

def read(path):
    path=Path(path)
    return json.loads(gzip.decompress(path.read_bytes()) if path.suffix==".gz" else path.read_text())
def canonical(value): return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
def digest(value): return hashlib.sha256(canonical(value).encode()).hexdigest()
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def rank(*values): return int(digest(list(values))[:16], 16)
def overlap(a, b): return max(a[0], b[0]) < min(a[1], b[1])
def save(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.tmp.'+str(os.getpid()));tmp.write_text(canonical(value)+'\n');tmp.replace(path)
def origin(date): return (date-ANCHOR).days*1440
def dates(): return [ANCHOR+dt.timedelta(days=i) for i in range((END-ANCHOR).days)]
def verify_inputs():
    if sha(EP_SCHEMA)!=read(OUT/'INPUT_LOCK.json')['EnergyPlus_schema_sha256']:raise ValueError('EP_SCHEMA_CHANGED')
    for name, expected in read(OUT/'INPUT_LOCK.json')['files'].items():
        if sha(REPO/name)!=expected: raise ValueError('PINNED_INPUT_CHANGED:'+name)
def rules_id():
    return digest({'code':{p.name:sha(p)for p in sorted((OUT/'code').glob('*.py'))},
                   'rules':sha(OUT/'GENERATION_RULES.json'),'inputs':sha(OUT/'INPUT_LOCK.json')})

def save_gzip(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+".tmp."+str(os.getpid()))
    tmp.write_bytes(gzip.compress((canonical(value)+"\n").encode(),compresslevel=6,mtime=0));tmp.replace(path)
