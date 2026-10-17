#!/usr/bin/env python3
"""One entry for the1000-household master and its proportional50 subset."""
import argparse,json,subprocess,sys
from pathlib import Path

REPO=Path(__file__).resolve().parents[1]
BASE=REPO/'docs/research/collection-adjustment-20260930/household1000'
STAGE=BASE/'household_master_v33_20261016'


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('phase',choices=['status','resources','build','review','export','seal','verify']);p.add_argument('--workers',type=int,default=6);a=p.parse_args()
    if a.phase=='status':
        pointer=BASE/'CURRENT_MASTER_INPUTS.json'
        print(pointer.read_text()if pointer.exists()else json.dumps({'stage':STAGE.name,'master_households':1000,'status':'build_not_accepted','EP_allowed':False}));return 0
    script={'resources':'prepare_resources.py','build':'build_master.py','review':'independent_review.py','export':'export_review.py','seal':'seal_master.py','verify':'seal_master.py'}[a.phase]
    command=[sys.executable,'-B',str(STAGE/'code'/script)]
    if a.phase=='build':command+=['--workers',str(a.workers),'--limit','1000']
    if a.phase=='verify':command+=['--verify-only']
    return subprocess.run(command,cwd=REPO).returncode

if __name__=='__main__':raise SystemExit(main())
