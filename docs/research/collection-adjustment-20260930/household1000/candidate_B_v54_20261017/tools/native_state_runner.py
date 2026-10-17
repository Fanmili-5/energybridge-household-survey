"""Semantics-preserving calendar memoization and resumable native A state replay.

The original compiler is immutable during replay. Only repeated resident_slot
calls within the same build are memoized. Old successful references are reused
only if compiler, state and input hashes still match. No failure is selected out.
"""
import sys,json,gzip
from pathlib import Path
import native_A_state as native
from functools import lru_cache
_cache={};_resident=native.resident_slot;_build=native.build;_run=native.run_one

def memo_resident(w,activity,member,slot,operations,tasks):
    key=(id(activity),member,slot)
    if key not in _cache:_cache[key]=_resident(w,activity,member,slot,operations,tasks)
    return _cache[key]
def memo_build(hid,date):
    _cache.clear()
    return _build(hid,date)
native.resident_slot=memo_resident;native.build=memo_build
@lru_cache(maxsize=1)
def completed():
    results={};compiler=native.sha(native.__file__)
    for f in (native.DEST/'state_reference').glob('*/RESULT.json'):
        r=json.loads(f.read_text())
        if not r['passed']or not r.get('state_path'):continue
        p=native.DEST/r['state_path'];ip=f.parent/'INPUT.json'
        if not p.exists()or native.sha(p)!=r['state_sha256']or native.sha(ip)!=r['inputs_sha256']:continue
        s=json.loads(gzip.decompress(p.read_bytes()))
        if s['compiler_sha256']==compiler:results[r['household_id'],r['date']]=r
    return results

def resumed_run(hid,date):
    previous=completed().get((hid,date))
    return previous if previous else _run(hid,date)
native.run_one=resumed_run
if __name__=='__main__':
    native.main()
    if '--household'not in sys.argv:
        p=native.DEST/'STATE_BINDINGS.json';data=native.read(p);data['execution_wrapper_sha256']=native.sha(__file__);native.save(p,data)
