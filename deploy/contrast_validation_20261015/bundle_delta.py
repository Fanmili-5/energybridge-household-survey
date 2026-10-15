"""Transport sealed private packages using rsync batch; never edit the basis."""
import argparse,hashlib,json,subprocess
from pathlib import Path

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def verify(root):
    m=json.loads((root/'FORMAL_RELEASE.json').read_text())
    for name,value in m['files'].items():assert sha(root/name)==value
    return m
def main():
    p=argparse.ArgumentParser();p.add_argument('--basis',type=Path,required=True);p.add_argument('--release',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    assert not a.output.exists();old=verify(a.basis);new=verify(a.release)
    assert old['batch']==new['batch']and old['release_signature']!=new['release_signature']
    subprocess.run(['rsync','-arzc','--no-whole-file','--only-write-batch='+str(a.output),str(a.release)+'/',str(a.basis)+'/'],check=True)
    assert verify(a.basis)==old,'basis package must remain immutable'
    receipt={'schema':'eb.sealed_release_delta.v1','batch':new['batch'],'basis_release_signature':old['release_signature'],'target_release_signature':new['release_signature'],'batch_sha256':sha(a.output),'batch_bytes':a.output.stat().st_size,'rsync_version':subprocess.run(['rsync','--version'],capture_output=True,text=True,check=True).stdout.splitlines()[0],'basis_all_payload_hashes_unchanged':True,'target_all_payload_hashes_verified':True,'production_activation_performed':False}
    a.output.with_suffix('.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt),flush=True)
if __name__=='__main__':main()
