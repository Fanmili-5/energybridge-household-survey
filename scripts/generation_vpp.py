#!/usr/bin/env python3
"""Current A38 dish habits and B39 VPP-conditioned portfolio production."""
import argparse,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'docs/research/collection-adjustment-20260930/household1000'
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('stage',choices=['A','B']);p.add_argument('phase',choices=['family-review','build','audit-A','review','export','seal','verify','status']);p.add_argument('--workers',type=int,default=4);a=p.parse_args();s=BASE/('normal_A_v38_20261016'if a.stage=='A'else'candidate_B_v39_20261016')
 if a.phase=='status':print((s/'ACCEPTANCE.json').read_text()if(s/'ACCEPTANCE.json').exists()else'{"accepted":false}');return 0
 f=s/'tools/review_family_EB.py'if a.phase=='family-review'else s/'code'/dict(build='generate.py',review='review.py',export='export.py',seal='finalize.py',verify='finalize.py',**{'audit-A':'audit_A.py'})[a.phase]
 cmd=[sys.executable,'-B',str(f)]
 if a.phase=='build':cmd+=['--workers',str(a.workers),'--limit','1000']
 if a.phase=='verify':cmd+=['--verify-only']
 return subprocess.run(cmd,cwd=ROOT).returncode
if __name__=='__main__':raise SystemExit(main())
