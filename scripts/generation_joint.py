#!/usr/bin/env python3
"""A42 rebuilt household life calendars and B43 input-conditioned VPP portfolios."""
import argparse,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'docs/research/collection-adjustment-20260930/household1000'
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('stage',choices=['A','B']);p.add_argument('phase',choices=['family-review','build','audit-A','review','design-review','regressions','thermal-probes','export','seal','publish','verify','status']);p.add_argument('--workers',type=int,default=4);a=p.parse_args();s=BASE/('normal_A_v42_20261016'if a.stage=='A'else'candidate_B_v43_20261016')
 if a.phase=='status':print((s/'ACCEPTANCE.json').read_text()if(s/'ACCEPTANCE.json').exists()else'{"accepted":false}');return 0
 if a.phase in ('audit-A','regressions','publish')and a.stage!='B':p.error(a.phase+' applies to B')
 if a.phase in ('family-review','thermal-probes')and a.stage!='A':p.error(a.phase+' applies to A')
 mapping={'family-review':'tools/review_family_EB.py','build':'code/generate.py','audit-A':'code/audit_A.py','review':'code/review.py','design-review':'tools/review_design.py','regressions':'tools/regression.py','thermal-probes':'tools/run_functional_probes.py','export':'code/export.py','seal':'tools/seal_stage.py','publish':'tools/publish_inputs.py','verify':'code/finalize.py'}
 cmd=[sys.executable,'-B',str(s/mapping[a.phase])]
 if a.phase=='build':cmd+=['--workers',str(a.workers),'--limit','1000']
 if a.phase=='verify':cmd+=['--verify-only']
 return subprocess.run(cmd,cwd=ROOT).returncode
if __name__=='__main__':raise SystemExit(main())
