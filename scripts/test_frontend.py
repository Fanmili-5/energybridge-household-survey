"""Browser -> actual HTTP/SQLite -> native EP fixture -> feedback; no model API."""
import argparse, json, os, subprocess, sys, tempfile, threading
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'realtime_pilot'))
from server import make_server
from regional_test_support import answers
from export_candidates import verify_candidate

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--human-mode',action='store_true',help='Exercise formal-mode routing with synthetic answers in a disposable database only')
    parser.add_argument('--intake-only',action='store_true',help='Verify current human intake and shared-browser reset without EnergyPlus or a model')
    args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='eb-browser-') as tmp:
        tmp=Path(tmp)
        fixture=tmp/'answers.json';fixture.write_text(json.dumps(answers(),ensure_ascii=False))
        server=make_server(0,tmp/'data',workers=1,disable_planning=args.intake_only,timeout=300,human_pilot=args.human_mode)
        if not args.intake_only:
            server.store.worker_command=lambda folder:[sys.executable,str(ROOT/'realtime_pilot/deploy/ep_fixture_worker.py'),str(folder)]
            server.planning_disabled=False;server.store.pool.resume()
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            host,port=server.server_address
            env={**os.environ,'EB_BROWSER_ORIGIN':f'http://{host}:{port}','EB_BROWSER_ANSWERS':str(fixture),'EB_BROWSER_INTAKE_ONLY':'1' if args.intake_only else '0'}
            subprocess.run(['node',str(ROOT/'scripts/verify_current_frontend.js')],env=env,check=True,timeout=240)
            if args.intake_only:
                intakes=server.store.db.households()
                assert len(intakes)==2,len(intakes)
                assert all(row['research_consent'] and row['scenario_understood'] for row in intakes)
                assert all(row['research_notice_version']=='eb.research_notice.v2' for row in intakes)
                assert len(server.store.jobs)==0
                print('Verified current formal intake at 390px and 1365px; server records survived browser reset; EP/model calls = 0.')
                return
            candidates=list(server.store.db.conn.execute("SELECT job_id,payload FROM documents WHERE name='sft_candidate.json'"))
            assert len(candidates)==2,len(candidates)
            for jid,payload in candidates:
                job=server.store.jobs[jid]
                docs={n:server.store.db.document(jid,n) for n in ('outcome.json','decision.json','household_record.json','questionnaire_submission.json','request.json')}
                intake=server.store.db.household(job['household_submission_id'])
                verify_candidate(json.loads(payload),job,docs,intake)
                assert docs['outcome.json']['timings']['llm']['call_count']==0
                expected='household_representative_self_report' if args.human_mode else 'engineering_test'
                assert json.loads(payload)['target_source']==expected
            output=tmp/'review.jsonl'
            subprocess.run([sys.executable,str(ROOT/'realtime_pilot/export_candidates.py'),'--data-dir',str(tmp/'data'),'--output',str(output)],check=True,capture_output=True,text=True)
            exported=[json.loads(line) for line in output.read_text().splitlines()]
            assert len(exported)==(2 if args.human_mode else 0)
            assert all(row['training_release'] is False for row in exported)
            print(f'Verified two browser feedback records and default export (human_mode={args.human_mode}); synthetic test data only, temporary database removed on exit; paid API calls = 0.')
        except Exception:
            for path in (tmp/'data').glob('*/attempts/*/worker.log'):
                print(path.read_text()[-3500:],flush=True)
            raise
        finally:
            server.shutdown();server.store.stopping=True;server.store.pool.shutdown();server.server_close();server.store.db.close()
if __name__=='__main__':main()
