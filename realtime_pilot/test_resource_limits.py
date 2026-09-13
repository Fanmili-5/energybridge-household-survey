import os,tempfile,unittest,fcntl
from unittest.mock import patch
from resource_limits import ep_compute,api_request,ApiDailyLimit
from pathlib import Path
class ResourceTests(unittest.TestCase):
    def test_daily_api_budget_is_shared(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'EB_RESOURCE_DIR':tmp,'EB_API_SLOTS':'1','EB_MAX_DAILY_API_CALLS':'2'}):
            with api_request():pass
            with api_request():pass
            with self.assertRaises(ApiDailyLimit):
                with api_request():pass

    def available(self,path):
        with path.open('a') as f:
            try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:return False
            fcntl.flock(f,fcntl.LOCK_UN);return True
    def test_wait_releases_cpu_and_exception_reacquires_then_frees(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'EB_RESOURCE_DIR':tmp,'EB_EP_SLOTS':'1','EB_API_SLOTS':'1'}):
            ep=Path(tmp)/'ep_0.lock';api=Path(tmp)/'api_0.lock'
            with ep_compute():
                self.assertFalse(self.available(ep))
                with self.assertRaisesRegex(RuntimeError,'fixture'):
                    with api_request():
                        self.assertTrue(self.available(ep))
                        self.assertFalse(self.available(api))
                        raise RuntimeError('fixture')
                self.assertFalse(self.available(ep))
                self.assertTrue(self.available(api))
            self.assertTrue(self.available(ep))
