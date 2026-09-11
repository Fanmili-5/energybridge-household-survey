"""Real EnergyPlus feedback test, deterministic planner fixture, no API or human labels."""
from contextlib import redirect_stdout
from pathlib import Path
from copy import deepcopy
from common import ROOT,normalize_answers,write_json
from paired_contract import LOOKUP,prepare
from verify_paired_physics import answers
from closed_loop import simulate_live
from paired_ep import pair_metrics

def main():
    profile=normalize_answers(answers(),list(LOOKUP),LOOKUP);original,scenario=prepare(profile,'closed_loop_probe')
    scenario.update(decision_h=16,event={'id':'live_feedback_test','trigger_h':18,'end_h':19,'day':4})
    request={'profile':profile,'original_plan':original,'scenario':scenario};folder=ROOT/'data/closed_loop_physics'
    folder.mkdir(parents=True,exist_ok=True);calls=[]
    def planner(loop,now,observed,history,reasons):
        assert history[-1]['end_h']==observed['end_h'];assert all(r['end_h']<=now+1e-7 for r in history)
        calls.append({'sim_h':now,'temperature_c':observed['temperature_c'],'history_end':history[-1]['end_h'],'trigger':reasons})
        plan=deepcopy(original['eb_ordinary_plan'])
        plan['setpoint']=27 if now<91 else 25
        plan['next_check_hour']=now+.5 if len(calls)==1 else None
        return plan,'确定性测试：根据新观测复查；这不是模型输出或真人回答。'
    with (folder/'console.log').open('w') as log,redirect_stdout(log):
        baseline=simulate_live(folder/'baseline',request)
        proposal=simulate_live(folder/'proposal',request,planner)
    metrics=pair_metrics(baseline,proposal,scenario)
    times=[c['sim_h'] for c in calls]
    assert 88 in times and 88.5 in times and 90 in times and 91 in times,times
    assert calls[1]['temperature_c']!=calls[0]['temperature_c'],calls
    assert all(d['observed']['end_h']<=d['sim_h']+1e-7 for d in proposal['decisions'])
    assert all(r['cooling_setpoint']==25 for r in proposal['controls'] if 91<=r['start_h']<95)
    result={'status':'passed','planner':'deterministic_engineering_fixture','calls':calls,'metrics':metrics,
            'live_observation_sql_check':proposal['live_observation_sql_check'],'task_energy_checks':proposal['task_energy_checks'],
            'baseline_idf_sha256':baseline['idf_sha256'],'proposal_idf_sha256':proposal['idf_sha256']}
    assert result['baseline_idf_sha256']==result['proposal_idf_sha256']
    write_json(folder/'verification.json',result);print(result)
if __name__=='__main__':main()
