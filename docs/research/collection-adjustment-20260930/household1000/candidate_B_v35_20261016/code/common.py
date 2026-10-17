"""Immutable V34 inputs, deterministic rules and atomic versioned outputs."""
import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path

OUT=Path(__file__).resolve().parents[1]
BASE=OUT.parent
REPO=BASE.parents[3]
A_STAGE=BASE/'normal_A_v34_1_20261016'
MASTER=BASE/'household_master_v33_20261016'
DECISION=480
LEVELS=['low','medium','high','extreme']
MECHANISMS=['thermal_setpoint','program_timer','ev_delay','hotwater_preheat',
            'handling_shift','thermal_pause','ev_short_window','hotwater_target',
            'coordinated','reverse_direction']

def read(p):return json.loads(Path(p).read_text())
def canonical(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(x):return hashlib.sha256(canonical(x).encode()).hexdigest()
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def rank(*x):return int(digest(x)[:16],16)
def save(p,x):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    t=p.with_name(p.name+'.tmp.'+str(os.getpid()));t.write_text(canonical(x)+'\n');t.replace(p)
def overlap(a,b):return max(a[0],b[0])<min(a[1],b[1])
def rules_id():return digest({'code':{p.name:sha(p)for p in sorted((OUT/'code').glob('*.py'))},'rules':sha(OUT/'GENERATION_RULES.json'),'inputs':sha(OUT/'INPUT_LOCK.json')})
def verify_inputs():
    for p,h in read(OUT/'INPUT_LOCK.json')['files'].items():
        if sha(REPO/p)!=h:raise ValueError('PINNED_INPUT_CHANGED:'+p)
def choose(values,key):return min(values,key=lambda x:rank(key,x))if values else None
def rel(p):return str(Path(p).relative_to(OUT))
