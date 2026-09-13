"""Capture actual intake -> EP fixture -> feedback -> exporters, with no model calls."""
import argparse, http.client, json, os, secrets, subprocess, sys, threading, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for key in list(os.environ):
    if key.startswith('LLM_') or key=='EB_PILOT_ENV_FILE':os.environ.pop(key)
os.environ.update(PYTHON_DOTENV_DISABLED='1',USE_LLM='0',EB_EP_SLOTS='1',EB_API_SLOTS='1')
sys.path.insert(0,str(ROOT/'realtime_pilot'))
from server import make_server
from common import digest
from paired_contract import QUESTIONS,QUESTIONNAIRE_VERSION,CONTEXT
from regional_test_support import answers

def main(out):
    out.mkdir(parents=True,exist_ok=False)
    os.environ['EB_RESOURCE_DIR']=str(out/'locks')
    saved=out/'captured';saved.mkdir()
    def write(name,value):
        (saved/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    server=make_server(0,out/'data',workers=1,disable_planning=True,timeout=300)
    server.store.worker_command=lambda folder:[sys.executable,str(ROOT/'realtime_pilot/deploy/ep_fixture_worker.py'),str(folder)]
    server.planning_disabled=False;server.store.pool.resume()
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    host,port=server.server_address;owner=secrets.token_hex(32)
    def call(path,body=None):
        c=http.client.HTTPConnection(host,port,timeout=30)
        c.request('GET' if body is None else 'POST',path,None if body is None else json.dumps(body),{'Cookie':'pilot_session='+owner,'Origin':f'http://{host}:{port}','Content-Type':'application/json'})
        r=c.getresponse();v=json.loads(r.read());c.close()
        assert r.status in (200,201,202),(r.status,v)
        return v
    try:
        session=call('/api/session')
        raw={q['id']:None for q in QUESTIONS};raw.update(answers())
        memberq=next(q for q in QUESTIONS if q['id']=='M_MEMBERS')
        raw['M_MEMBERS']=[{f['id']:m.get(f['id']) for f in memberq['fields']} for m in raw['M_MEMBERS']]
        payload={'request_id':secrets.token_hex(16),'answers':raw,'questionnaire_version':QUESTIONNAIRE_VERSION,
                 'questionnaire_hash':digest(QUESTIONS),'questionnaire_context_hash':session['questionnaire_context']['context_hash'],'research_consent':True,'scenario_understood':True,'research_notice_version':'eb.research_notice.v2','ui_version':'engineering_complete_intake_review'}
        write('01_questionnaire_http_request.json',payload)
        receipt=call('/api/households',payload);sid=receipt['id']
        intake=server.store.db.household(sid);write('02_household_submission_db.json',intake)
        assert intake['raw_answers']==raw
        print('Actual household intake saved',flush=True)
        generate={'submission_id':sid,'household_record_hash':receipt['household_record_hash'],'request_id':secrets.token_hex(16),
                  'scenario_id':CONTEXT['id'],'scenario_understood':True,'questionnaire_version':QUESTIONNAIRE_VERSION,'questionnaire_hash':digest(QUESTIONS)}
        write('03_generation_http_request.json',generate)
        job=call('/api/paired',generate);jid=job['id'];deadline=time.monotonic()+310
        while time.monotonic()<deadline:
            state=call('/api/jobs/'+jid+'/status')
            if state['status']=='complete':break
            assert state['status'] not in {'failed','timeout','interrupted','cancelled'},state
            time.sleep(.5)
        else:raise TimeoutError('EP fixture job did not complete')
        job=call('/api/jobs/'+jid);r=job['result'];assert r['timings']['llm']['call_count']==0
        print('Native paired EP complete; model calls = 0',flush=True)
        feedback={'choice':'reject','score':3.75,'comfort_score':2.5,'energy_score':4.1,'vpp_score':2.25,
                  'comment':'完整问卷链路工程测试评分，不是真人回答。',
                  **{k:r[k] for k in ('display_hash','original_plan_hash','proposal_plan_hash')}}
        write('07_feedback_http_request.json',feedback);call('/api/jobs/'+jid+'/decision',feedback)
        for name,doc in [('04_household_config.json','household_config.json'),('05_worker_request.json','request.json'),
                         ('06_paired_outcome.json','outcome.json'),('08_saved_decision.json','decision.json'),('09_sft_candidate.json','sft_candidate.json')]:
            value=server.store.db.document(jid,doc);assert value is not None,doc;write(name,value)
        candidate=server.store.db.document(jid,'sft_candidate.json')
        assert candidate['household_submission_id']==sid and candidate['household_record_hash']==receipt['household_record_hash']
        assert candidate['household_record']==intake['household_record']
        assert candidate['target_source']=='engineering_test' and candidate['training_release'] is False
        write('10_sft_messages.json',{'messages':candidate['messages']})
        for role in candidate['messages']:
            value=role['content'] if role['role']=='system' else json.loads(role['content'])
            write('10_'+role['role']+'_content.json',value)
        for script,filename,include in [('export_household_records.py','11_household_export.jsonl',True),
                                       ('export_candidates.py','12_sft_export.jsonl',True),
                                       ('export_candidates.py','13_default_human_export.jsonl',False)]:
            cmd=[sys.executable,str(ROOT/'realtime_pilot'/script),'--data-dir',str(out/'data'),'--output',str(saved/filename)]
            if include:cmd.append('--include-engineering')
            subprocess.run(cmd,check=True,capture_output=True)
        exported=json.loads((saved/'12_sft_export.jsonl').read_text());assert exported==candidate
        assert (saved/'13_default_human_export.jsonl').read_text()==''
        write('00_verification.json',{'passed':True,'origin':'synthetic_engineering_test','real_human_record':False,
            'actual_http_intake':True,'actual_energyplus':True,'planner':'fixed_engineering_fixture_no_api',
            'model_calls':0,'case_id':jid,'submission_id':sid,'question_fields':len(raw),
            'source_equal_to_saved_intake':True,'export_equal_to_saved_candidate':True,
            'default_human_export_rows':0,'training_release':False})
        print('Saved capture and verified both actual exporters',flush=True)
    finally:
        server.shutdown();server.store.stopping=True;server.store.pool.shutdown();server.server_close();server.store.db.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();main(a.out.resolve())
