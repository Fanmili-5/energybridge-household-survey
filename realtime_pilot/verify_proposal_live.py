"""Opt-in real API verification of plan generation and HTTP decision readback."""
import http.cookiejar
import json
import time
import urllib.request
from common import ROOT, write_json
from test_proposals import payload

base='http://127.0.0.1:8766'
client=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
def api(path, body=None):
    request=urllib.request.Request(base+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json','Origin':base})
    with client.open(request,timeout=10) as response:return json.load(response)

if __name__=='__main__':
    schema=api('/api/session')
    p=payload();p['request_id']='live_proposal_'+str(time.time_ns())
    begin=time.perf_counter();j=api('/api/proposals',p)
    while j['status'] not in {'complete','failed','timeout','cancelled','interrupted'}:
        if time.perf_counter()-begin>245:
            api('/api/jobs/'+j['id']+'/cancel',{})
            raise TimeoutError('Live verification stopped')
        time.sleep(.5);j=api('/api/jobs/'+j['id'])
    report={'job_id':j['id'],'status':j['status'],'seconds':round(time.perf_counter()-begin,3),'task':'plan_judgement','data_origin':'synthetic_engineering_test','training_release':False,'execution_status':'not_run'}
    if j['status']=='complete':
        r=j['result'];decision={'choice':'reject','score':3,'comfort_score':2,'energy_score':4,'vpp_score':2,'comment':'自动化功能测试：希望空调保持原温度，不是真人问卷答案。',**{k:r[k] for k in ('display_hash','original_plan_hash','proposal_plan_hash')}}
        assert api('/api/jobs/'+j['id']+'/decision',decision)['saved']
        assert api('/api/jobs/'+j['id']+'/decision',decision)['duplicate']
        readback=api('/api/jobs/'+j['id'])
        assert readback['decision']['choice']=='reject' and readback['decision']['selected_plan']=='original'
        assert readback['original_plan']['devices']['washer']['start_h']==18
        assert set(r['proposal_plan']['appliances'])=={'washer_start_h'}
        row=json.loads((ROOT/'data/web'/j['id']/'sft_candidate.json').read_text())
        assert row['task']=='plan_judgement' and row['target_source']=='engineering_test'
        report.update(decision_readback=True,immutable_pair=True,proposal=r['proposal_plan'],timings=r['timings'],display=r['display'])
    write_json(ROOT/'PROPOSAL_LIVE_VERIFICATION.json',report)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if j['status']!='complete':raise SystemExit(1)
