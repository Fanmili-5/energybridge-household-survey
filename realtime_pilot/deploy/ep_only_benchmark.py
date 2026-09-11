"""Native EP paired-run benchmark; fixed controls, no model and no networking.

Each worker owns its own EnergyPlus API state and output folders. Includes
initialization, P0/P1 simulation and output validation; excludes model latency.
"""
import argparse
from contextlib import redirect_stdout
from copy import deepcopy
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
    os.environ['USE_LLM'] = 'false'
    for key in list(os.environ):
        if key.startswith('LLM_'):
            del os.environ[key]
    from common import normalize_answers, write_json
    from paired_contract import LOOKUP, prepare
    from verify_paired_physics import answers
    from closed_loop import simulate_live, EBPlanner
    from paired_ep import pair_metrics
    def forbidden_model(*args, **kwargs):
        raise AssertionError('Model planner must never run in this benchmark')
    EBPlanner.__call__ = forbidden_model
    folder.mkdir(parents=True, exist_ok=True)
    profile = normalize_answers(answers(), list(LOOKUP), LOOKUP)
    original, scenario = prepare(profile, 'ep_only_fixed_fixture')
    scenario.update(decision_h=16, event={'id':'ep_only_event','trigger_h':18,'end_h':19,'day':4})
    request = {'profile':profile,'original_plan':original,'scenario':scenario}
    calls = []
    def controller(loop, now, observed, history, reasons):
        assert history[-1]['end_h'] == observed['end_h']
        assert all(row['end_h'] <= now+1e-7 for row in history)
        calls.append({'sim_h':now, 'temperature_c':observed['temperature_c']})
        plan = deepcopy(original['eb_ordinary_plan'])
        plan['setpoint'] = 27 if now < 91 else 25
        plan['next_check_hour'] = now+.5 if len(calls) == 1 else None
        return plan, 'Fixed engineering controller; no model call or human evaluation.'
    (folder/'ready').touch()
    deadline = time.monotonic()+60
    while not (folder.parent/'start').exists():
        if time.monotonic()>deadline: raise TimeoutError('Benchmark start gate')
        time.sleep(.01)
    start = time.perf_counter()
    with (folder/'console.log').open('w') as log, redirect_stdout(log):
        baseline = simulate_live(folder/'baseline', request)
        proposal = simulate_live(folder/'proposal', request, controller)
        metrics = pair_metrics(baseline, proposal, scenario)
    elapsed = time.perf_counter()-start
    times = [c['sim_h'] for c in calls]
    assert all(t in times for t in (88,88.5,90,91)), times
    assert calls[0]['temperature_c'] != calls[1]['temperature_c']
    assert baseline['idf_sha256'] == proposal['idf_sha256']
    assert proposal['live_observation_sql_check']
    result = {'status':'passed','data_origin':'synthetic_engineering_test','api_calls':0,
        'network_access':'blocked_by_audit_hook','controller':'fixed_engineering_fixture',
        'pair_seconds':round(elapsed,3),'baseline_seconds':baseline['seconds'],
        'proposal_seconds':proposal['seconds'],'peak_rss_mib':round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,2),
        'cpu_seconds':round(resource.getrusage(resource.RUSAGE_SELF).ru_utime+resource.getrusage(resource.RUSAGE_SELF).ru_stime,3),
        'simulated_days':proposal['evaluation_window']['simulation_days'],
        'evaluation_end_h':proposal['evaluation_window']['end_sim_h'],
        'prefix_check':metrics['prefix_check'],'energy_checks':proposal['task_energy_checks'],
        'warnings':{'baseline':baseline['warning_count'],'proposal':proposal['warning_count']},
        'native_callback_count':len(proposal['controls']),'fixed_controller_calls':len(calls),
        'idf_sha256':proposal['idf_sha256'],'metrics':metrics,'training_release':False}
    write_json(folder/'result.json', result)

def meminfo():
    fields = dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())
    return {k:int(fields[k].split()[0])/1024 for k in ('MemAvailable','SwapFree')}

def main(out, repeats):
    out.mkdir(parents=True, exist_ok=False)
    report = {'api_calls':0,'mode':'ep_only_fixed_controller','pairs_per_worker':1,
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
