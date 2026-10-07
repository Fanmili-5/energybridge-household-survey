"""Versioned derived inputs only. This package has no EnergyPlus execution entrypoint."""
import hashlib, json, os, re, sys
from pathlib import Path
OUT = Path(__file__).resolve().parents[1]
BASE = OUT.parent
REPO = BASE.parents[3]
OLD = BASE / 'random10_task_worlds_20261007'
V12 = BASE / 'complete_reference_worlds_20261006_v12'
UP = REPO / 'upstream_2b17ae6'
SCHEMA_PATH = Path(os.environ.get('EB_EP_ROOT', '/Applications/EnergyPlus-24-1-0')) / 'Energy+.schema.epJSON'
KINDS = ['ac', 'washer', 'dishwasher', 'dryer', 'water_heater', 'ev']
def read(p): return json.loads(Path(p).read_text())
def canonical(x): return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
def digest(x): return hashlib.sha256(canonical(x).encode()).hexdigest()
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p, x):
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(canonical(x) + '\n')
def rank(*parts): return int(digest(list(parts))[:16], 16)
def parse(p): return [[v.strip() for v in q.split(',')] for q in re.sub(r'!.*', '', Path(p).read_text()).split(';') if q.strip()]
def dump(rows): return '\n'.join(',\n  '.join(str(x) for x in r) + ';' for r in rows) + '\n'
def school_guard():
    if sys.platform != 'linux': raise RuntimeError('Production and interface checks are assigned to school Linux')
    if not (OUT / 'EP_HOLD.json').exists(): raise RuntimeError('Retain the user EP hold')
    if (OUT / 'PACKAGE_MANIFEST.json').exists(): raise RuntimeError('Sealed inputs: use a new version')
