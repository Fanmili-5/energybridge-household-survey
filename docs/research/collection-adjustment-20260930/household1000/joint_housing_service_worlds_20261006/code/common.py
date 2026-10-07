"""Pinned runtime and immutable inputs for the new joint-world layer."""
import hashlib,json,sys
from pathlib import Path
OUT=Path(__file__).resolve().parent.parent;BASE=OUT.parent
V7=BASE/'idf_joint_production_20261005';V8=BASE/'household_housing_evidence_20261006';V9=BASE/'production_evidence_completion_20261006'
sys.path[:0]=json.loads((V7/'RUNTIME.json').read_text())['stable_PYTHONPATH'].split(':')
sys.path[:0]=[str(V7/'code'),str(V8/'code'),str(V9/'code')]
def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,d):Path(p).write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def guard():
 if (OUT/'PACKAGE_MANIFEST.json').exists():raise SystemExit('sealed;read-only audit only')
