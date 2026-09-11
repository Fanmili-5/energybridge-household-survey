"""One engineering HTTP case with real EB API, two native EP runs and feedback readback."""
import argparse
import http.cookiejar
import json
from pathlib import Path
import threading
import time
import urllib.request
import uuid
from common import ROOT,digest,write_json
from paired_contract import CONTEXT
from verify_paired_physics import answers
from server import make_server

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--allow-api',action='store_true')
    parser.add_argument('--report',type=Path,default=ROOT/'PAIRED_LIVE_VERIFICATION.json')
    args=parser.parse_args()
    if not args.allow_api:parser.error('Actual EB API call requires --allow-api')
    server=make_server(0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_address[1]}'
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def call(path,body=None):
        req=urllib.request.Request(base+path,data=None if body is None else json.dumps(body).encode(),headers={'Origin':base,'Content-Type':'application/json'})
        with opener.open(req,timeout=15) as response:return json.load(response)
    try:
        assert call('/api/session')['collection_mode']=='engineering'
        started=time.perf_counter();job=call('/api/paired',{'request_id':str(uuid.uuid4()),'answers':answers(),'scenario_id':CONTEXT['id'],'scenario_understood':True})
        print(json.dumps({'case_id':job['id'],'stage':'submitted'}),flush=True);last=None
        for _ in range(250):
            job=call('/api/jobs/'+job['id']);stage=job.get('progress',{}).get('stage',job['status'])
            if stage!=last:print(json.dumps({'stage':stage,'seconds':round(time.perf_counter()-started,1)}),flush=True);last=stage
            if job['status'] in {'complete','failed','timeout','cancelled','interrupted'}:break
            time.sleep(1)
        if job['status']!='complete':raise RuntimeError('Case did not complete: '+job['id']+' '+job['status'])
        result=job['result'];payload={'choice':'reject','score':3,'comfort_score':2,'energy_score':4,'vpp_score':2,
              'comment':'工程测试回答：用于核验四项独立评分、二元决定和两份仿真结果绑定，不是受访者意见。',
              **{k:result[k] for k in ('display_hash','original_plan_hash','proposal_plan_hash')}}
        assert call('/api/jobs/'+job['id']+'/decision',payload)['saved']
        saved=call('/api/jobs/'+job['id']);assert saved['decision_saved'] and saved['decision']['score']==3
        row=json.loads((ROOT/'data/web'/job['id']/'sft_candidate.json').read_text())
        assert row['flow']=='paired_ep_v1' and row['target_source']=='engineering_test' and row['training_release'] is False
        assert json.loads(row['messages'][-1]['content'])=={'decision':'reject','score':3,'comfort_score':2,'energy_score':4,'vpp_score':2,'comment':payload['comment']}
        assert digest(result['display'])==row['display_hash']
        report={'case_id':job['id'],'schema_version':result['schema_version'],'status':'passed','flow':row['flow'],'data_origin':row['data_origin'],'prefix_check':result['prediction']['prefix_check'],
          'feedback_readback':{k:saved['decision'][k] for k in ('choice','score','comfort_score','energy_score','vpp_score')},
          'timings':result['timings'],'http_end_to_end_seconds':job['end_to_end_seconds'],'prediction':result['prediction'],
          'provenance':result['provenance'],'training_release':False,'concurrency_benchmark':False}
        write_json(args.report,report);print(json.dumps({'status':report['status'],'case_id':job['id'],
            'schema_version':result['schema_version'],'seconds':job['end_to_end_seconds'],
            'rounds':result['timings']['planning_rounds'],'fallback_rounds':result['provenance']['fallback_rounds'],
            'report':str(args.report)},ensure_ascii=False),flush=True)
    finally:
        server.shutdown();server.store.pool.shutdown(wait=True,cancel_futures=True);server.server_close()
if __name__=='__main__':main()
