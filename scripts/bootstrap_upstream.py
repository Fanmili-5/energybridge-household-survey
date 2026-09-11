"""Fetch the pinned public EB source; never bundle local credentials or run models."""
import argparse
import subprocess
from pathlib import Path

COMMIT='2b17ae63e613da776c93e900f5dace50d63a88a8'
URL='https://github.com/Fanmili-5/EnergyBridge.git'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--path',type=Path,default=Path(__file__).resolve().parents[1]/'upstream_2b17ae6')
    parser.add_argument('--verify-only',action='store_true')
    args=parser.parse_args();path=args.path.resolve()
    if not path.exists():
        if args.verify_only:raise SystemExit('Pinned upstream is missing')
        subprocess.run(['git','clone','--filter=blob:none','--no-checkout',URL,str(path)],check=True)
        subprocess.run(['git','-C',str(path),'checkout','--detach',COMMIT],check=True)
    sha=subprocess.check_output(['git','-c','safe.directory='+str(path),'-C',str(path),'rev-parse','HEAD'],text=True).strip()
    if sha!=COMMIT:raise SystemExit('Existing upstream is a different version; do not overwrite it')
    dirty=subprocess.check_output(['git','-c','safe.directory='+str(path),'-C',str(path),'status','--porcelain','--untracked-files=no'],text=True)
    if dirty:raise SystemExit('Pinned upstream has modified tracked files')
    if (path/'.env').exists():raise SystemExit('Do not put credentials in the upstream checkout')
    print('Verified pinned EnergyBridge '+sha)


if __name__=='__main__':main()
