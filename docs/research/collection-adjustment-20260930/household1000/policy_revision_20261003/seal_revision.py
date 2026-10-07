#!/usr/bin/env python3
"""Hash this revision and independently confirm unchanged sealed baselines."""
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import unquote

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent


def sha(path):
    with Path(path).open('rb') as stream:
        digest=hashlib.sha256()
        while chunk:=stream.read(1024*1024):digest.update(chunk)
    return digest.hexdigest()


def verify_manifest(root,filename='PACKAGE_MANIFEST.json'):
    manifest=json.loads((root/filename).read_text());entries=manifest['files']
    if isinstance(entries,list):
        pairs=[(entry['path'],entry['sha256']) for entry in entries]
    else:
        pairs=[(name,value if isinstance(value,str) else value['sha256']) for name,value in entries.items()]
    errors=[]
    for name,expected in pairs:
        path=(root/name).resolve()
        if not path.is_relative_to(root.resolve()):errors.append('outside_manifest_root:'+name)
        elif not path.is_file() or sha(path)!=expected:errors.append(name)
    return {'root':str(root),'manifest_sha256':sha(root/filename),'files_checked':len(pairs),
            'mismatches':errors,'pass':not errors}


def main():
    frozen=json.loads((HERE/'FROZEN_BASELINE_BINDINGS.json').read_text())
    baseline=[]
    for row in frozen['read_only_baselines']:
        root=ROOT/row['root'];check=verify_manifest(root)
        check['manifest_itself_unchanged']=check['manifest_sha256']==row['manifest_sha256']
        baseline.append(check)
    audit=verify_manifest(ROOT/'household_to_idf_20261003/reviewer_audit_20261003','REVIEW_MANIFEST.json')
    audit['manifest_itself_unchanged']=audit['manifest_sha256']==frozen['read_only_audit_manifest_sha256']
    baseline.append(audit)
    new_packages=[verify_manifest(ROOT/name) for name in
                  ['generation_model_v2_20261003','household_to_idf_v3_20261003']]
    exclude={'PACKAGE_MANIFEST.json','PACKAGE_VERIFICATION.json'}
    files={str(p.relative_to(HERE)):sha(p) for p in HERE.rglob('*')
           if p.is_file() and p.name not in exclude and '__pycache__' not in p.parts}
    manifest={'schema':'eb.policy_revision.package_manifest.v1','files':files,
              'sealed_generation_and_physical_packages':new_packages,
              'frozen_baselines':baseline}
    (HERE/'PACKAGE_MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    byte_errors=[name for name,expected in files.items() if sha(HERE/name)!=expected]
    links=[];broken=[]
    for p in HERE.rglob('*.md'):
        for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
            target=target.strip().split(' "')[0].strip('<>')
            if target.startswith(('https://','http://','codex://','#','mailto:')):continue
            target=unquote(target.split('#')[0]);target=re.sub(r':\d+$','',target)
            if not target:continue
            resolved=Path(target) if target.startswith('/') else p.parent/target
            links.append(str(resolved))
            if not resolved.exists():broken.append({'file':str(p),'target':target})
    passed=not byte_errors and not broken and all(c['pass'] and c.get('manifest_itself_unchanged',True) for c in baseline+new_packages)
    result={'schema':'eb.policy_revision.package_verification.v1','pass':passed,
            'revision_files_checked':len(files),'revision_byte_mismatches':byte_errors,
            'frozen_baselines':baseline,'new_generation_and_core_packages':new_packages,
            'local_markdown_links_checked':len(links),'broken_links':broken,
            'manifest_sha256':sha(HERE/'PACKAGE_MANIFEST.json'),
            'scope':'package byte integrity and specified bindings; scientific validity is assessed separately',
            'collection_release':False,'training_release':False}
    (HERE/'PACKAGE_VERIFICATION.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ['pass','revision_files_checked','revision_byte_mismatches','local_markdown_links_checked','broken_links']}))
    raise SystemExit(0 if passed else 1)


if __name__=='__main__':main()
