"""Run backend tests with dummy model credentials and no external network access."""
import ipaddress
import os
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
for key in list(os.environ):
    if key.startswith('LLM_') or key=='EB_PILOT_ENV_FILE':os.environ.pop(key)
os.environ.update(PYTHON_DOTENV_DISABLED='1',USE_LLM='1',LLM_API_KEY='offline-fixture',
                  LLM_MODEL='offline-fixture',LLM_BASE_URL='http://127.0.0.1:9/v1',
                  NO_PROXY='127.0.0.1,localhost',no_proxy='127.0.0.1,localhost')


def audit(event,args):
    host=None
    if event=='socket.getaddrinfo':host=args[0]
    if event=='socket.connect' and isinstance(args[1],tuple):host=args[1][0]
    if host is None:return
    if host in ('localhost',b'localhost'):return
    try:allowed=ipaddress.ip_address(host).is_loopback
    except ValueError:allowed=False
    if not allowed:raise RuntimeError('Offline tests forbid external network access')


sys.addaudithook(audit)
os.chdir(ROOT/'realtime_pilot');sys.path.insert(0,str(Path.cwd()))
suite=unittest.defaultTestLoader.discover('.',pattern='test_*.py')
result=unittest.TextTestRunner(verbosity=1).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
