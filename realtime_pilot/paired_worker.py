"""Current CLI entry: only the native EB collection worker is executable here."""
import sys
import os
from pathlib import Path
from common import write_json
from native_worker import run

if __name__=='__main__':
    folder=Path(sys.argv[1])
    try:
        if os.environ.get('EB_COMPUTE_URL'):
            from remote_compute import run_remote
            run_remote(folder)
        else:
            run(folder)
    except Exception as exc:
        write_json(folder/'failure.json',{'error_type':type(exc).__name__,'status':'incomplete_simulation'})
        print('Native EB collection failed; see retained native logs.')
        sys.exit(1)
