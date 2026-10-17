"""Materialize immutable per-case native reference pointers as replay completes.

Allows B construction to consume completed A references while other households
are still replaying. Final full-state bindings remain the release authority.
"""
import time,json,gzip,hashlib
from pathlib import Path
OUT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    a=json.loads((OUT.parent/'normal_A_v46_20261017/A_BINDINGS10000.json').read_text());expected={(r['household_id'],c['date'])for r in a['records']for c in r['cases']};compiler=sha(OUT/'tools/native_A_state.py');seen={};indexed=set()
    while len(indexed)<10000:
        for f in (OUT/'state_reference').glob('*/RESULT.json'):
            stamp=f.stat().st_mtime_ns
            if seen.get(str(f))==stamp:continue
            seen[str(f)]=stamp
            try:r=json.loads(f.read_text())
            except (ValueError,OSError):continue
            key=(r['household_id'],r['date'])
            if key not in expected or not r['passed']or not r.get('state_path'):continue
            p=OUT/r['state_path']
            if sha(p)!=r['state_sha256']:continue
            state=json.loads(gzip.decompress(p.read_bytes()))
            if state['compiler_sha256']!=compiler:continue
            dest=OUT/'state_records'/r['household_id']/(r['date']+'.json');dest.parent.mkdir(parents=True,exist_ok=True)
            body=json.dumps(r,sort_keys=True,separators=(',',':'))+'\n'
            if dest.exists():
                previous=json.loads(dest.read_text());existing=OUT/previous['state_path']
                if sha(existing)!=previous['state_sha256']:raise ValueError('REFERENCED_STATE_CHANGED')
                indexed.add(key);continue
            tmp=dest.with_suffix('.tmp');tmp.write_text(body);tmp.replace(dest);indexed.add(key)
        if len(indexed)%1000<8:print({'indexed_A_references':len(indexed)},flush=True)
        time.sleep(2)
    # Retain engine completion separately; release index follows the exact
    # immutable state references consumed by B, even when equivalent probes
    # produced another valid SQL file for the same case.
    while True:
        full=OUT/'STATE_BINDINGS.json'
        if full.exists():
            d=json.loads(full.read_text())
            if d.get('cases')==10000:break
        time.sleep(2)
    original=OUT/'NATIVE_REPLAY_COMPLETION.json';original.write_bytes(full.read_bytes())
    d['records']=[json.loads((OUT/'state_records'/hid/(date+'.json')).read_text())for hid,date in sorted(expected)];d['passed']=all(r['passed']for r in d['records']);d['native_replay_completion_sha256']=sha(original);d['index_policy']='immutable completed A references consumed by B;equivalent extra probes retained as development records'
    tmp=full.with_suffix('.tmp');tmp.write_text(json.dumps(d,sort_keys=True,separators=(',',':'))+'\n');tmp.replace(full)
    print({'indexed_A_references':10000,'ready':True},flush=True)
if __name__=='__main__':main()
