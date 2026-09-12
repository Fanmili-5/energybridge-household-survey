"""Package the reviewed Git index and hash-verified assets, never a directory glob."""
import argparse, hashlib, io, json, subprocess, sys, tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'realtime_pilot'))
from resource_versions import paths, safe_asset

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    subprocess.run([sys.executable,str(ROOT/'scripts/check_secrets.py')],check=True,cwd=ROOT)
    names=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().strip('\0').split('\0')
    # Match exactly what was scanned; refuse unstaged source drift.
    for name in names:
        indexed=subprocess.check_output(['git','show',':'+name],cwd=ROOT)
        if (ROOT/name).read_bytes()!=indexed:raise ValueError('Stage reviewed source before packaging: '+name)
    assets={}
    current=json.loads((ROOT/'simulation_resources/catalog.json').read_text())
    base='models/tianjin_family_eb_v1/family_all_appliances.idf'
    assets[base]=safe_asset(ROOT,base,current['source_idf_sha256'])
    for catalog in [ROOT/'simulation_resources/catalog.json',*sorted((ROOT/'simulation_resources/versions').glob('*/catalog.json'))]:
        base=ROOT if catalog.parent.name=='simulation_resources' else catalog.parent
        for name,checksum in paths(json.loads(catalog.read_text())):
            asset=safe_asset(base,name,checksum);assets[str(asset.relative_to(ROOT))]=asset
    upstream=json.loads((ROOT/'UPSTREAM_TRACKED_FILES.json').read_text())
    for name,checksum in upstream['files'].items():
        asset=safe_asset(ROOT/'upstream_2b17ae6',name,checksum)
        assets['upstream_2b17ae6/'+name]=asset
    allfiles={name:ROOT/name for name in names};allfiles.update(assets)
    manifest={'version':1,'git_head_before_release':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
              'files':{name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in sorted(allfiles.items())}}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with tarfile.open(a.output,'w:gz',compresslevel=1) as archive:
        for name,path in sorted(allfiles.items()):archive.add(path,arcname=name,recursive=False)
        body=json.dumps(manifest,sort_keys=True).encode();info=tarfile.TarInfo('RELEASE_MANIFEST.json');info.size=len(body);archive.addfile(info,io.BytesIO(body))
    print(json.dumps({'file':str(a.output),'files':len(allfiles),'sha256':hashlib.sha256(a.output.read_bytes()).hexdigest()}))
if __name__=='__main__':main()
