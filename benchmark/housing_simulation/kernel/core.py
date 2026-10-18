"""Portable, content-bound household physics; no historical cohort imports."""
import datetime as dt
import gzip
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(os.environ['EB_HOUSING_INPUT_ROOT']).resolve()
KERNEL = Path(__file__).resolve().parent
VERSION = 'eb.housing_physics.v2'

def read(path):
    p = Path(path)
    return json.loads(gzip.decompress(p.read_bytes()) if p.suffix == '.gz' else p.read_text())

def canonical(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)

def digest(x):
    return hashlib.sha256(canonical(x).encode()).hexdigest()

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def save(path, x):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = (canonical(x) + '\n').encode()
    if p.suffix == '.gz':
        data = gzip.compress(data, compresslevel=6, mtime=0)
        data = data[:9]+b'\xff'+data[10:]
    tmp = p.with_name(p.name + '.tmp.' + str(os.getpid()))
    tmp.write_bytes(data)
    tmp.replace(p)

def parse_idf(text):
    import re
    return [[v.strip() for v in p.split(',')] for p in re.sub(r'!.*', '', text).split(';') if p.strip()]

def offset(date, anchor):
    return (dt.date.fromisoformat(date) - dt.date.fromisoformat(anchor)).days * 1440

def overlap(a, z, b, y):
    return max(a, b) < min(z, y)

def code_hash():
    root=KERNEL.parent
    return digest({str(p.relative_to(root)):sha(p) for p in sorted(root.rglob('*.py'))})

def physics_hash():
    files={name:sha(KERNEL/name)for name in ('core.py','compiler.py','thermal_environment.py')}
    files['THERMAL_ENVIRONMENT_POLICY.json']=sha(ROOT/'THERMAL_ENVIRONMENT_POLICY.json')
    files['ASSUMPTIONS.json']=sha(KERNEL.parent/'ASSUMPTIONS.json')
    return digest(files)
