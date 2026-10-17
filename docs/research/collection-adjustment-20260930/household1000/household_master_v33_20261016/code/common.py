"""Versioned repair; source worlds and original selection are read-only."""
import hashlib, json, os, re, sys
from pathlib import Path
OUT = Path(__file__).resolve().parents[1]
BASE = OUT.parent
REPO = BASE.parents[3]
SOURCE = BASE/'substantive_repair_v30_20261015'
PILOT = BASE/'roleplay_mixed_production_20261007_v17'
V16 = BASE/'joint_static_production_20261007_v16'
V12 = BASE/'complete_reference_worlds_20261006_v12'
UP = REPO/'upstream_2b17ae6'
SCHEMA_PATH = Path(os.environ.get('EB_EP_ROOT','/Applications/EnergyPlus-24-1-0'))/'Energy+.schema.epJSON'
KINDS = ['ac','washer','dishwasher','dryer','water_heater','ev']
def read(p): return json.loads(Path(p).read_text())
def canonical(x): return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(x): return hashlib.sha256(canonical(x).encode()).hexdigest()
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,x):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_name(p.name+'.tmp.'+str(os.getpid()));tmp.write_text(canonical(x)+'\n');tmp.replace(p)
def rank(*x): return int(digest(list(x))[:16],16)
def parse(p): return [[v.strip() for v in s.split(',')] for s in re.sub(r'!.*','',Path(p).read_text()).split(';') if s.strip()]
def dump(rows): return '\n'.join(',\n  '.join(str(x) for x in r)+';' for r in rows)+'\n'
def school_guard():
    if sys.platform!='linux': raise RuntimeError('Generation, validation, compilation and simulation run on school Linux')
def overlap(a,b): return max(a[0],b[0])<min(a[1],b[1])
def clock(t): return ('前日' if t<0 else '当天' if t<1440 else '次日' if t<2880 else '第3天')+f' {t%1440//60:02d}:{t%60:02d}'

def atomic_text(path,text):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_name(path.name+".tmp."+str(os.getpid()));tmp.write_text(text);tmp.replace(path)

def verify_dependencies():
    for name,expected in read(OUT/'DEPENDENCY_LOCK.json')['files_relative_to_household1000'].items():
        if sha(BASE/name)!=expected:raise RuntimeError('ANCESTOR_DEPENDENCY_CHANGED:'+name)
