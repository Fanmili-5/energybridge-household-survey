"""Cross-process CPU/API admission. Does not change EB plans or EP simulation time."""
from contextlib import contextmanager
from contextvars import ContextVar
import fcntl
import json
import os
from pathlib import Path
import time

_current_ep=ContextVar('current_ep_lease',default=None)


class ApiDailyLimit(RuntimeError):
    pass


def claim_daily_api_call():
    """Persistently bound logical model calls across worker processes (UTC)."""
    root=os.environ.get('EB_RESOURCE_DIR')
    limit=int(os.environ.get('EB_MAX_DAILY_API_CALLS','0'))
    if not root or limit<=0:return
    path=Path(root);path.mkdir(parents=True,exist_ok=True)
    ledger=path/'api_daily_calls.json';lock=(path/'api_daily_calls.lock').open('a+')
    try:
        fcntl.flock(lock,fcntl.LOCK_EX)
        try:state=json.loads(ledger.read_text()) if ledger.exists() else {}
        except (OSError,json.JSONDecodeError):state={}
        day=int(time.time()//86400)
        count=int(state.get('count',0)) if state.get('utc_day')==day else 0
        if count>=limit:raise ApiDailyLimit('Daily logical model-call budget reached')
        state={'utc_day':day,'count':count+1,'limit':limit,'updated_at':time.time()}
        with ledger.open('w') as target:
            json.dump(state,target,separators=(',',':'));target.flush();os.fsync(target.fileno())
    finally:
        fcntl.flock(lock,fcntl.LOCK_UN);lock.close()
class Lease:
    def __init__(self,kind,slots):
        self.root=Path(os.environ['EB_RESOURCE_DIR'])
        self.root.mkdir(parents=True,exist_ok=True)
        self.kind=kind;self.slots=slots;self.file=None
    def acquire(self):
        while self.file is None:
            for i in range(self.slots):
                f=(self.root/f'{self.kind}_{i}.lock').open('a')
                try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError:f.close()
                else:self.file=f;return
            time.sleep(.025)
    def release(self):
        if self.file is not None:
            fcntl.flock(self.file,fcntl.LOCK_UN)
            self.file.close();self.file=None

def lease(kind,default):
    if not os.environ.get('EB_RESOURCE_DIR'):return None
    n=int(os.environ.get('EB_'+kind.upper()+'_SLOTS',default))
    if not 1<=n<=32:raise ValueError('Invalid resource slot count')
    return Lease(kind,n)

@contextmanager
def ep_compute():
    slot=lease('ep',2)
    if slot:slot.acquire()
    token=_current_ep.set(slot)
    try:yield
    finally:
        if slot:slot.release()
        _current_ep.reset(token)

@contextmanager
def api_request():
    ep=_current_ep.get()
    slot=lease('api',2)
    # The native EP callback is synchronous. It retains its own process/state
    # while waiting, so another household can use the released CPU slot.
    if ep:ep.release()
    try:
        if slot:slot.acquire()
        claim_daily_api_call()
        yield
    finally:
        if slot:slot.release()
        if ep:ep.acquire()
