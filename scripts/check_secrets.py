"""Fail on forbidden tracked artifacts or high-confidence credential signatures.

Print file/line/rule only, never matched contents. Inspect the Git index, not a
directory-wide glob; this also detects secrets mistakenly staged but ignored.
"""
import argparse
import json
import lzma
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
RULES={
 'private_key':rb'-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----',
 'provider_token':rb'\b(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[A-Z0-9]{16})\b',
 'literal_auth_header':rb'(?i)(?:Bearer|Basic)\s+[A-Za-z0-9+/=_-]{24,}',
}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--json',action='store_true');parser.add_argument('--history',action='store_true');args=parser.parse_args()
    files=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    findings=[];count=0
    for name in filter(None,files):
        count+=1;path=Path(name)
        if (path.name.startswith('.env') and not path.name.endswith('.example') or '.local.' in path.name
            or path.name.startswith('ACCESS') or path.suffix in {'.pem','.key','.p12','.pfx','.db','.sqlite','.sqlite3','.log','.tar','.gz','.zip'}
            or any(part in {'data','exports','backups','upstream_2b17ae6'} for part in path.parts)):
            findings.append({'file':name,'rule':'forbidden_artifact'})
        body=subprocess.check_output(['git','show',':'+name],cwd=ROOT)
        if name=='simulation_resources/validation.json.xz':body=lzma.decompress(body)
        for rule,pattern in RULES.items():
            for match in re.finditer(pattern,body):findings.append({'file':name,'line':body[:match.start()].count(b'\n')+1,'rule':rule})
        # Credential assignments may use non-provider-specific tokens.
        for i,line in enumerate(body.splitlines(),1):
            if re.search(rb'(?i)(?:api[_-]?key|api_key_pool|password|secret|access_token)\s*["\']?\s*[:=]',line):
                for value in re.findall(rb'["\']([A-Za-z0-9_./+=-]{24,})["\']',line):
                    if any(c in value for c in (b'_',b'-',b'=')) and len(set(value))>14 and not re.fullmatch(rb'[0-9a-f]{32,}',value):
                        findings.append({'file':name,'line':i,'rule':'review_credential_assignment'})
    historical_blobs=0
    if args.history:
        if subprocess.check_output(['git','rev-parse','--is-shallow-repository'],cwd=ROOT,text=True).strip()=='true':
            findings.append({'file':'.git','rule':'incomplete_history_shallow_clone'})
        for entry in subprocess.check_output(['git','rev-list','--objects','--all'],cwd=ROOT,text=True).splitlines():
            oid,_,name=entry.partition(' ')
            if subprocess.check_output(['git','cat-file','-t',oid],cwd=ROOT).strip()!=b'blob':continue
            historical_blobs+=1
            body=subprocess.check_output(['git','cat-file','blob',oid],cwd=ROOT)
            if name=='simulation_resources/validation.json.xz':body=lzma.decompress(body)
            for rule,pattern in RULES.items():
                if re.search(pattern,body):findings.append({'file':name,'object':oid,'rule':'history_'+rule})
    report={'historical_blobs':historical_blobs,'scanned_files':count,'passed':not findings,'findings':findings}
    print(json.dumps(report,ensure_ascii=False,indent=2));raise SystemExit(1 if findings else 0)


if __name__=='__main__':main()
