"""Engineering worker: real native EP, in-process model fixture, no network."""
import json
import os
from pathlib import Path
import socket
import sys
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
for key in list(os.environ):
    if key.startswith(('LLM_', 'ROLEPLAY_')) or key in ('EB_PILOT_ENV_FILE','EB_COMPUTE_URL'):
        os.environ.pop(key)
os.environ.update(PYTHON_DOTENV_DISABLED='1',USE_LLM='1',LLM_API_KEY='offline-fixture',
                  LLM_MODEL='offline-fixture',LLM_BASE_URL='http://127.0.0.1:9/v1')
def offline(event,args):
    if event=='socket.getaddrinfo' or (event in {'socket.connect','socket.sendto'} and args[0].family in {socket.AF_INET,socket.AF_INET6}):
        raise RuntimeError('No network permitted in EP fixture worker')
sys.addaudithook(offline)
from native_support import upstream
upstream()
from energybridge.llm.client import LLMClient
from native_worker import run
from common import write_json
def model(client,system,user,**kwargs):
    text='{}'
    if '[PLANNING PAYLOAD]' in user:
        text=json.dumps({'candidate_plans':[{'id':'fixture','plan':{
            'setpoint':26.5,'appliances':{},'next_check_hour':None}}],
            'selected_candidate_id':'fixture','selection_reason':'Synthetic engineering fixture.'})
    return {'text':text,'metrics':{'fixture':True}}
folder=Path(sys.argv[1])
with patch.object(LLMClient,'chat_with_metrics',new=model):
    run(folder)
result=json.loads((folder/'outcome.json').read_text())
result['provenance'].update(planner='fixed_engineering_fixture_no_api',network_access='prohibited')
result['timings']['llm']['fixture_call_count']=result['timings']['llm']['call_count']
result['timings']['llm']['call_count']=0
write_json(folder/'outcome.json',result)
