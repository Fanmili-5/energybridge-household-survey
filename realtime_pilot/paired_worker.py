"""Paired live EP simulations; EB re-observes and replans until scenario end."""
import json
import os
import sys
import time
from pathlib import Path
from common import ROOT,UPSTREAM,digest,file_hash,write_json
from paired_contract import VERSION,participant_view
from paired_ep import pair_metrics
from eb_execution import source_manifest
from evaluation_window import window_for
from native_execution_diagnostics import diagnose_native_execution
from closed_loop import EBPlanner,simulate_live,display_trajectory

STAGES={'baseline':'正在计算原安排至共同评价终点','proposal':'EB 正在随仿真进展持续调整安排','planning':'EB 正在依据新状态更新安排','complete':'两份安排已完成同一时间范围的比较'}

def run(folder):
    from runtime_config import load_model_environment
    load_model_environment()
    started=time.perf_counter();request=json.loads((folder/'request.json').read_text())
    from household_config import ensure_household_config
    household=ensure_household_config(request)
    write_json(folder/'household_config.json',household)
    original=request['original_plan'];scenario=request['scenario']
    code_files=('paired_worker.py','runtime_config.py','native_execution_diagnostics.py','closed_loop.py','eb_controller_adapter.py','paired_contract.py','survey_time.py','paired_ep.py','eb_execution.py','proposal_contract.py','questionnaire_persona.py','household_config.py','household_extensions.py','member_questionnaire.py','survey_preferences.py','evaluation_window.py','service_outcomes.py','presentation.py','resource_limits.py')
    code_hashes={name:file_hash(ROOT/name) for name in code_files}
    def progress(stage,message=None):write_json(folder/'progress.json',{'stage':stage,'message':message or STAGES[stage]})
    diagnostics={}
    def check_execution(branch,trace):
        diagnostics[branch]=diagnose_native_execution(trace,branch=branch)
        write_json(folder/'native_execution_diagnostics.json',diagnostics)
        if not diagnostics[branch]['execution_compatible']:
            raise ValueError('Native execution incompatibility; household answers remain saved')
    progress('baseline');baseline=simulate_live(folder/'baseline',request)
    check_execution('baseline',baseline)
    progress('proposal');planner=EBPlanner(request,folder/'planning',progress)
    proposal=simulate_live(folder/'proposal',request,planner)
    check_execution('proposal',proposal)
    if not proposal['decisions']:raise ValueError('Missing EB closed-loop decisions')
    prediction=pair_metrics(baseline,proposal,scenario)
    plan={'execution_mode':'eb_closed_loop','decisions':proposal['decisions'],
          'control_trace_hash':digest(proposal['controls']),'horizon_end_sim_h':window_for(scenario)['end_sim_h']}
    display=display_trajectory(original,baseline,proposal,scenario,prediction)
    display['participant_view']=participant_view(display)
    source=source_manifest();source['scope']='live EP feedback, model next checks, native EB event checkpoints, repeated planning and actuator application'
    source['checkpoint_function']='family_runner._agent_next_vpp_checkpoint_hour'
    result={'schema_version':VERSION,'flow':'paired_ep_v1','task':'plan_judgement','original_plan':original,'original_plan_hash':digest(original),
      'proposal_plan':plan,'proposal_plan_hash':digest(plan),'display':display,'display_hash':digest(display),
      'execution_status':'not_run','simulation_status':'paired_energyplus_complete','forecast_status':'prototype_paired_prediction',
      'execution_mode':'eb_closed_loop','prediction':prediction,
      'timings':{'worker_total_seconds':round(time.perf_counter()-started,3),'baseline_ep_seconds':baseline['seconds'],
                 'proposal_ep_wall_seconds_including_planning':proposal['seconds'],'planning_rounds':len(planner.rounds),
                 'llm':{'call_count':len(planner.calls),'attempts':planner.calls}},
      'provenance':{'upstream_commit':source['commit'],'planning_source_sha256':file_hash(UPSTREAM/'energybridge/harness/planning.py'),
        'worker_sha256':file_hash(__file__),'adapter_sha256':file_hash(ROOT/'closed_loop.py'),'contract_sha256':file_hash(ROOT/'paired_contract.py'),
        'baseline_idf_sha256':baseline['idf_sha256'],'proposal_idf_sha256':proposal['idf_sha256'],'weather_sha256':baseline['weather_sha256'],
        'template_sha256':baseline['template_sha256'],'baseline_warnings':baseline['warning_count'],'proposal_warnings':proposal['warning_count'],
        'eb_execution':source,'live_observation_sql_check':proposal['live_observation_sql_check'],
        'physical_model':'same study prototype, native tank/EV and EB task electrical ports; not calibrated to respondent home',
        'adapter_assumptions':['Questionnaire ordinary P0; after notification the proposal uses native occupancy-controlled HVAC availability','Task port heat gains not calibrated',
                               'Shared horizon includes reported overnight deadlines and EV departure; proposal triggers native daily planning, baseline repeats ordinary routine','Human scores replace benchmark household grading'],
        'common_state_method':'identical IDF, weather, conditioning and live control path before notification; verified paired prefix equality',
        'is_full_benchmark':False,'real_appliances_controlled':False}}
    result['provenance']['source_files_at_start']=code_hashes
    result['provenance']['source_changed_during_run']=any(file_hash(ROOT/name)!=sha for name,sha in code_hashes.items())
    if result['provenance']['source_changed_during_run']:raise ValueError('Source changed during simulation; regenerate this pair')
    result['provenance']['fallback_rounds']=sum(bool(d.get('controller',{}).get('fallback_used')) for d in proposal['decisions'])
    result['household_config']=household
    result['household_config_hash']=request['household_config_hash']
    result['feedback_contract']={'required_scores':['score','comfort_score','energy_score','vpp_score']}
    result['assessment_stage']='after_simulated_trajectory_before_real_execution'
    result['assessment_cutoff_sim_h']=window_for(scenario)['end_sim_h']
    write_json(folder/'outcome.json',result);progress('complete')

if __name__=='__main__':
    folder=Path(sys.argv[1])
    try:run(folder)
    except Exception as exc:
        write_json(folder/'failure.json',{'error_type':type(exc).__name__,'status':'no_validated_pair'})
        print('Closed-loop generation failed; see retained decision and native EP logs.')
        sys.exit(1)
