"""Trace author release entry points without paid calls or source modification.

Execute actual job constructors and multi-user preparation for all 50 main
jobs; stop at run_family_agent for planning methods. Then run two real no_dr
seven-day reference episodes and two official daily no_dr jobs through the
same multi-user entry with read-only tracing.
"""
from __future__ import annotations
import argparse
from contextlib import redirect_stdout
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--upstream', type=Path, required=True)
    ap.add_argument('--ep-root', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    root, out = args.upstream.resolve(), args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    # No inherited provider settings or .env files. Block networking, including
    # any unexpectedly introduced model call, at the Python audit boundary.
    for key in list(os.environ):
        if key.startswith(('LLM_', 'ROLEPLAY_', 'ENERGYBRIDGE_')):
            os.environ.pop(key)
    os.environ.update(PYTHON_DOTENV_DISABLED='1', USE_LLM='false', ROLEPLAY_USE_LLM='false',
                      EPLUS_ROOT=str(args.ep_root), ENERGYBRIDGE_HARNESS_PROFILE='agentic_v3')
    network_attempts = []
    def audit(event, values):
        if event in ('socket.connect', 'socket.getaddrinfo'):
            network_attempts.append(event)
            raise RuntimeError('External networking forbidden in author-mainline audit')
    sys.addaudithook(audit)
    os.chdir(root)
    sys.path[:0] = [str(root/'experiments/benchmark'), str(root), str(args.ep_root)]
    import run_household_matrix as matrix
    import run_daily_dr_memory_matrix as daily
    import run_multi_user_household as entry
    import family_runner as fr
    import run_persona_json as assets
    methods = ['EnergyBridge', 'hema_agent', 'mpc_dynamic', 'rule_milp', 'rl_ppo_pref_v2']
    rows, preparation = [], []
    original_prepare = entry._prepare_run_assets
    def observe_prepare(*values, **kwargs):
        result = original_prepare(*values, **kwargs)
        idf, epw, price = result
        preparation.append({'idf': str(idf), 'sha256': hashlib.sha256(idf.read_bytes()).hexdigest(),
                            'epw': str(epw), 'price': getattr(price, 'source', None)})
        return result
    class ReachedRunner(Exception): pass
    captured = []
    def capture(**kwargs):
        persona = kwargs['persona_config']
        captured.append({'method': kwargs['method'], 'days': kwargs['sim_days'],
                         'household_id': persona['id'], 'members': len(persona['members']),
                         'schema': persona['schema_version'],
                         'devices': sorted(kwargs['appliance_config']),
                         'idf': str(kwargs['idf_path']),
                         'pre_event_hook': kwargs['pre_event_preference_callback'].__name__,
                         'post_event_hook': kwargs['post_event_score_callback'].__name__})
        raise ReachedRunner()
    for city in ['Tianjin', 'Germany']:
        options = SimpleNamespace(date=city.lower(), results_root=str(out/'main'), days=7, city=city,
                    start_date='2025-06-01', mpc_horizon=6, households=None, methods=methods,
                    dr_memory_library='', vpp_start_hour=18, vpp_duration_hours=1, vpp_events_json='',
                    price_csv=str(root/'experiments/real_data'/('tianjin_tou_price_normalized.csv' if city=='Tianjin' else 'germany_2025_price.csv')))
        jobs = matrix._make_jobs(options)
        assert len(jobs) == 25
        for job in jobs:
            command = matrix._command_for(job)
            with (out/'preparation.log').open('a') as log, redirect_stdout(log), \
                 patch.object(entry, '_prepare_run_assets', observe_prepare), \
                 patch.object(fr, 'run_family_agent', capture), patch.object(sys, 'argv', command[2:]):
                try: entry.main()
                except ReachedRunner: pass
                else: raise AssertionError('Did not reach official family runner')
            rows.append({'city': city, 'job': job.household_id, **captured[-1], **preparation[-1]})
    assert len(rows) == 50
    for city in ['Tianjin', 'Germany']:
        for household in sorted({r['household_id'] for r in rows}):
            group = [r for r in rows if r['city']==city and r['household_id']==household]
            assert len({r['sha256'] for r in group}) == 1, 'Methods use different prepared IDFs'
    daily_jobs = []
    for month in ['june', 'july']:
        options = SimpleNamespace(results_root=str(out/'daily'), date=month,
             start_date='2025-06-01' if month=='june' else '2025-07-01', days=30, max_samples=7,
             vpp_events_json=str(root/f'dr_capacity_memory_toolkit/{month}_2025_daily_eb/config/vpp_events_{month}_memory_merged30.json'),
             households=None, methods=['no_dr', *methods], cities=['Germany','Tianjin'],
             germany_price_csv=str(root/'experiments/real_data/germany_2025_price.csv'),
             tianjin_price_csv=str(root/'experiments/real_data/tianjin_tou_price_normalized.csv'))
        jobs = daily._make_jobs(options)
        assert len(jobs) == 420
        for job in jobs:
            command = daily._command_for(job)
            assert command[command.index('--days')+1] == '1'
        daily_jobs.extend(jobs)
    # Both official matrix routes reach the same preparation function; inspect
    # a representative daily job as well, using its real generated event JSON.
    daily_command = daily._command_for(next(j for j in daily_jobs if j.method=='EnergyBridge'))
    with (out/'preparation.log').open('a') as log, redirect_stdout(log), \
         patch.object(entry, '_prepare_run_assets', observe_prepare), \
         patch.object(fr, 'run_family_agent', capture), patch.object(sys, 'argv', daily_command[2:]):
        try: entry.main()
        except ReachedRunner: pass
    daily_preparation = {**captured[-1], **preparation[-1]}
    # Run the author's multi-user no_dr path unmodified. This is a reference
    # execution, not a completed EnergyBridge/HEMA/PPO policy comparison.
    episodes = []
    original_init, original_write = fr._FamilyLoop.init, fr._write_appliance_actuators
    for city, days in [('Tianjin',7), ('Germany',7), ('Tianjin',1), ('Germany',1)]:
        handles, power_max = {}, {}
        def observe_init(loop, ex, state):
            ready = original_init(loop, ex, state)
            if ready and not handles:
                handles.update({name:getattr(loop,'h_'+name) for name in ['washer','dishwasher','dryer','refrigerator','ev','ewh_sp']})
            return ready
        def observe_write(ex, state, loop, powers, sim_h):
            for name, value in powers.items(): power_max[name] = max(power_max.get(name,0), value)
            return original_write(ex, state, loop, powers, sim_h)
        folder = out/'native_no_dr'/f'{city.lower()}_{days}days'
        argv = ['run_multi_user_household.py', '--household', 'household_s1_dual_commuter_standard',
                '--method','no_dr','--city',city,'--days','7','--start-date','2025-06-01',
                '--price-csv',str(root/'experiments/real_data'/('tianjin_tou_price_normalized.csv' if city=='Tianjin' else 'germany_2025_price.csv')),
                '--output',str(folder),'--vpp-start-hour','18','--vpp-duration-hours','1']
        if days == 1:
            job = next(j for j in daily_jobs if j.method=='no_dr' and j.city==city)
            argv = daily._command_for(job)[2:]
            argv[argv.index('--output')+1] = str(folder)
        with (out/(city.lower()+f'-{days}days-no-dr.log')).open('w') as log, redirect_stdout(log), \
             patch.object(fr._FamilyLoop,'init',observe_init), \
             patch.object(fr,'_write_appliance_actuators',observe_write), patch.object(sys,'argv',argv):
            entry.main()
        result = json.loads((folder/'benchmark_result.json').read_text())
        assert result['exit_code'] == 0, result.get('exit_code')
        assert all(handles[name] == -1 for name in ['washer','dishwasher','dryer','refrigerator'])
        assert all(power_max.get(name,0)>0 for name in ['washer','dishwasher','dryer','refrigerator'])
        episodes.append({'city':city,'days':days,'exit_code':result['exit_code'],
                         'handles':handles,'python_device_power_max_kw':power_max,
                         'energy_kwh': result.get('energy_kwh',result.get('energy_kwh_total')),
                         'llm_call_count':result.get('llm_call_count'), 'output':str(folder)})
    assert not network_attempts
    report = {'author':'https://github.com/Agentic-Intelligence-Lab/EnergyBridge',
              'commit':subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip(),
              'main_jobs_prepared_not_simulated':rows, 'daily_jobs_constructed_not_simulated':len(daily_jobs),
              'daily_preparation_example':daily_preparation,'real_reference_runs':episodes,
              'network_attempts':network_attempts, 'paid_model_calls':0,
              'main_policy_runs_completed':0, 'upstream_source_modified':False}
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'prepared_main_jobs':len(rows),'constructed_daily_jobs':len(daily_jobs),
                      'real_reference_runs':episodes,'report':str(out/'report.json')},indent=2))


if __name__ == '__main__': main()
