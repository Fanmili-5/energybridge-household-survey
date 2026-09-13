"""Read-only deployment gate; uses EB_COMPUTE_URL/TOKEN_FILE, never calls a model."""
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'realtime_pilot'))
from remote_compute import check_remote_ready

def main():
    try:
        health=check_remote_ready()
    except Exception as exc:
        # Do not echo transport credentials or private paths from exceptions.
        print(json.dumps({'ready':False,'error_type':type(exc).__name__,
                          'action':'Check SSH route and matching deployed releases; no task was submitted.'}))
        return 1
    print(json.dumps({'ready':True,'compute':health,'model_calls':0}))
    return 0

if __name__=='__main__':raise SystemExit(main())
