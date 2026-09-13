"""Production native EB/EP paired-run benchmark with a fixed model reply.

Each worker executes the same one-day ``no_dr`` and ``agent`` entry points used
by collection.  Network access is prohibited and the model method is replaced
with a deterministic invalid reply, so EB's native technical fallback is
exercised without a provider request or a simulated household judgement.
"""
import argparse
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import resource
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def prohibit_network(event, args):
    if event in {'socket.connect', 'socket.sendto'} and args[0].family in {socket.AF_INET, socket.AF_INET6}:
        raise RuntimeError('EP-only benchmark prohibits network access')
    if event == 'socket.getaddrinfo':
        raise RuntimeError('EP-only benchmark prohibits network resolution')

def worker(folder):
    sys.addaudithook(prohibit_network)
    # Exercise the production agent branch while replacing its model transport
    # below with an in-process fixed reply.
    os.environ['USE_LLM'] = 'true'
    for key in list(os.environ):
        if key.startswith('LLM_'):
            del os.environ[key]
    os.environ.update(LLM_API_KEY='offline-fixture-not-a-real-key',
                      LLM_MODEL='offline-fixture',LLM_BASE_URL='http://127.0.0.1:9/v1')
    from common import digest, normalize_answers, write_json
    from paired_contract import LOOKUP, prepare
    from verify_paired_physics import answers
    from household_config import ensure_household_config
    from native_runner import run_native
    from native_support import upstream
    upstream()
    from energybridge.llm.client import LLMClient
    from unittest.mock import patch
    folder.mkdir(parents=True, exist_ok=True)
    profile = normalize_answers(answers(), list(LOOKUP), LOOKUP)
    original, scenario = prepare(profile, 'ep_only_fixed_fixture')
    request = {'profile':profile,'original_plan':original,'scenario':scenario,'data_origin':'synthetic_engineering_test',
               'household_id':'ep_only_fixed_fixture'}
    household=ensure_household_config(request)
    request.update(household_config=household,household_config_hash=digest(household))
    calls=[]
    def fixed_model(*args, **kwargs):
        calls.append({'fixture':True})
        return {'text':'{}','metrics':{'fixture':True,'attempts':1,'retries':0}}
    (folder/'ready').touch()
    deadline = time.monotonic()+60
    while not (folder.parent/'start').exists():
        if time.monotonic()>deadline: raise TimeoutError('Benchmark start gate')
        time.sleep(.01)
    start = time.perf_counter()
    with (folder/'console.log').open('w') as log, redirect_stdout(log):
        with patch.object(LLMClient,'chat_with_metrics',fixed_model):
            baseline = run_native(folder/'baseline',request,method='no_dr')
            proposal = run_native(folder/'proposal',request,method='agent')
    elapsed = time.perf_counter()-start
    assert scenario['evaluation_window']['simulation_days']==1
    assert scenario['evaluation_window']['end_sim_h']==24
    assert baseline['horizon']==proposal['horizon']==24
    assert baseline['idf_sha256'] == proposal['idf_sha256']
    assert baseline['weather_sha256'] == proposal['weather_sha256']
    assert len(baseline['electricity'])==len(proposal['electricity'])==144
    pending=proposal['native']['human_evaluation_pending']
    assert pending
    for key in ('vpp_plan_acceptance_rate','vpp_plan_acceptance_probability_avg',
                'vpp_plan_rejected_count','accepted_effective_vpp_success_rate'):
        assert proposal['native'].get(key) is None
    assert calls
    decision=scenario['decision_h']
    prefix_energy=max(abs(a['kwh']-b['kwh']) for a,b in zip(baseline['electricity'],proposal['electricity']) if a['end_h']<=decision)
    prefix_temp=max(abs(a['c']-b['c']) for a,b in zip(baseline['temperature'],proposal['temperature']) if a['end_h']<=decision)
    result = {'status':'passed','data_origin':'synthetic_engineering_test','api_calls':0,
        'network_access':'blocked_by_audit_hook','controller':'native_technical_fallback_from_fixed_invalid_reply',
        'collection_methods':['no_dr','agent'],'simulation_days':1,
        'pair_seconds':round(elapsed,3),'baseline_seconds':baseline['seconds'],
        'proposal_seconds':proposal['seconds'],'peak_rss_mib':round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,2),
        'cpu_seconds':round(resource.getrusage(resource.RUSAGE_SELF).ru_utime+resource.getrusage(resource.RUSAGE_SELF).ru_stime,3),
        'fixed_model_calls':len(calls),'human_evaluation_pending':len(pending),
        'pre_decision_difference':{'comparison':'no_dr versus full-day agent method; equality is not required',
                                   'until_simulation_h':decision,'max_kwh_difference':prefix_energy,
                                   'max_temperature_difference_c':prefix_temp},
        'idf_sha256':proposal['idf_sha256'],'weather_sha256':proposal['weather_sha256'],
        'training_release':False}
    write_json(folder/'result.json', result)

def meminfo():
    fields = dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())
    return {k:int(fields[k].split()[0])/1024 for k in ('MemAvailable','SwapFree')}

def main(out, repeats):
    out.mkdir(parents=True, exist_ok=False)
    report = {'api_calls':0,'mode':'production_native_fixed_reply','pairs_per_worker':1,
        'includes_model_latency':False,'cpu_logical_count':os.cpu_count(),'batches':[]}
    for concurrency in (1,2,4):
        for repeat in range(repeats):
            batch = out/f'c{concurrency}_r{repeat+1}'
            batch.mkdir()
            processes=[]; logs=[]; start_memory=meminfo(); peak_rss=0; min_available=start_memory['MemAvailable']; min_swap=start_memory['SwapFree']
            try:
                for n in range(concurrency):
                    folder=batch/f'worker{n+1}'
                    log=(batch/f'worker{n+1}.log').open('w');logs.append(log)
                    processes.append(subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--worker',str(folder)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT))
                deadline=time.monotonic()+60
                while len(list(batch.glob('worker*/ready')))<concurrency:
                    if any(p.poll() is not None for p in processes):raise RuntimeError('Worker startup failed: '+str(batch))
                    if time.monotonic()>deadline:raise TimeoutError('Workers not ready')
                    time.sleep(.02)
                started=time.perf_counter();(batch/'start').touch()
                while any(p.poll() is None for p in processes):
                    rss=0
                    for p in processes:
                        try:
                            stat=Path(f'/proc/{p.pid}/status').read_text()
                            rss+=int(next(line.split()[1] for line in stat.splitlines() if line.startswith('VmRSS:')))/1024
                        except (OSError, StopIteration):pass
                    peak_rss=max(peak_rss,rss);memory=meminfo()
                    min_available=min(min_available,memory['MemAvailable']);min_swap=min(min_swap,memory['SwapFree'])
                    if time.perf_counter()-started>120:raise TimeoutError('EP-only batch exceeded 120 seconds')
                    time.sleep(.05)
                batch_seconds=time.perf_counter()-started
                assert all(p.returncode==0 for p in processes), str(batch)
                results=[json.loads(p.read_text()) for p in sorted(batch.glob('worker*/result.json'))]
                assert len(results)==concurrency
                entry={'concurrency':concurrency,'repeat':repeat+1,'batch_seconds':round(batch_seconds,3),
                    'pair_seconds':[r['pair_seconds'] for r in results],
                    'peak_worker_rss_mib':round(peak_rss,2),'min_available_mib':round(min_available,2),
                    'swap_used_delta_mib':round(start_memory['SwapFree']-min_swap,2),'results':results}
                report['batches'].append(entry)
                (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
                print(json.dumps({k:v for k,v in entry.items() if k!='results'}),flush=True)
            finally:
                for p in processes:
                    if p.poll() is None:p.kill();p.wait()
                for log in logs:log.close()
    report['status']='passed'
    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--worker',type=Path);p.add_argument('--out',type=Path);p.add_argument('--repeats',type=int,default=2);a=p.parse_args()
    if a.worker:worker(a.worker)
    elif a.out:main(a.out,a.repeats)
    else:p.error('--out or --worker required')
