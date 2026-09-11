"""Private engineering test worker. Never selectable through an HTTP request."""
import sys,socket
from pathlib import Path
from copy import deepcopy
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
def offline(event,args):
    if event=='socket.getaddrinfo' or (event in {'socket.connect','socket.sendto'} and args[0].family in {socket.AF_INET,socket.AF_INET6}):
        raise RuntimeError('No network permitted in EP fixture worker')
sys.addaudithook(offline)
import paired_worker
from common import write_json
class FixedPlanner:
    def __init__(self,request,folder,progress):
        self.request=request;self.rounds=[];self.calls=[];self.last_audit={'engineering_fixture':True}
    def __call__(self,loop,sim_h,observed,history,reasons):
        plan=deepcopy(self.request['original_plan']['eb_ordinary_plan'])
        plan['setpoint']=26.5
        plan['next_check_hour']=None
        self.rounds.append({'sim_h':sim_h,'test_fixture':True})
        return plan,'工程测试固定方案，不是模型生成方案。'
paired_worker.EBPlanner=FixedPlanner
folder=Path(sys.argv[1])
paired_worker.run(folder)
import json
r=json.loads((folder/'outcome.json').read_text())
r['provenance']['planner']='fixed_engineering_fixture_no_api'
r['provenance']['network_access']='prohibited'
assert r['timings']['llm']['call_count']==0
write_json(folder/'outcome.json',r)
