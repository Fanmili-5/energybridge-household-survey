"""Questionnaire -> native no_dr/agent runs -> immutable human feedback view."""
import json
import time
from common import ROOT, UPSTREAM, digest, file_hash, write_json
from household_config import ensure_household_config
from native_runner import run_native, BOUNDARY_VERSION
from native_presentation import metrics, display
from paired_contract import VERSION, participant_view


class NativeProposalUnavailable(RuntimeError):
    pass


def native_plan_outcomes(native):
    """Record original lifecycle decisions without adding a selection gate."""
    outcomes=[]
    for day in native.get('all_day_decisions',[]):
        for row in day:
            stages=row.get('adaptive_decision_audit',{}).get('plan_lifecycle',{}).get('stages',{})
            outcomes.append({'h':row['h'],'stages':{k:v.get('status') for k,v in stages.items()},
                'fallback_used':any('fallback' in str(v.get('status','')) for v in stages.values())})
    return outcomes


def run(folder):
    from runtime_config import load_model_environment
    load_model_environment()
    started=time.perf_counter()
    request=json.loads((folder/'request.json').read_text())
    household=ensure_household_config(request)
    files=('native_runner.py','native_worker.py','native_presentation.py','native_assets.py','native_scenario.py','native_support.py','paired_contract.py',
           'household_config.py','proposal_contract.py','presentation.py','resource_limits.py','simulation_environment.py','date_sampling.py')
    hashes={name:file_hash(ROOT/name) for name in files}
    def progress(stage,message):write_json(folder/'progress.json',{'stage':stage,'message':message})
    write_json(folder/'household_config.json',household)
    if request['scenario'].get('environment'):
        write_json(folder/'simulation_environment.json',request['scenario']['environment'])
    progress('baseline','正在运行原 EB 日常对照仿真')
    validation={'date':request['scenario']['simulation_start_date'],'policy':'native_baseline_before_planning_no_resampling','status':'running'}
    write_json(folder/'date_validation.json',validation)
    try:
        baseline=run_native(folder/'baseline',request,method='no_dr',progress=progress)
    except Exception as exc:
        write_json(folder/'date_validation.json',{**validation,'status':'failed','error_type':type(exc).__name__,'planning_started':False})
        raise
    validation.update(status='passed',baseline_idf_sha256=baseline['idf_sha256'],weather_sha256=baseline['weather_sha256'],baseline_llm_call_count=baseline['native']['llm_call_count'])
    write_json(folder/'date_validation.json',validation)
    progress('proposal','正在运行原 EB 规划与 EP 连续仿真')
    proposal=run_native(folder/'proposal',request,method='agent',progress=progress)
    if not proposal['native']['llm_call_count']:
        raise NativeProposalUnavailable('No successful native model call')
    prediction=metrics(baseline,proposal,request['scenario'])
    shown=display(request['original_plan'],baseline,proposal,request['scenario'],prediction)
    shown['participant_view']=participant_view(shown)
    # Full reasoning/evidence stays in hash-addressed native_result.json.
    # HTTP responses and SQLite receipts need executable actions, not repeated
    # megabytes of internal objective/evidence traces for every decision.
    decision_keys=('h','sp','effective_setpoint','room_temp_c','outdoor_temp_c','hvac_availability',
                   'actions','requested_actions','raw_appliance_actions','actuator_application')
    decisions=[[{key:row[key] for key in decision_keys if key in row} for row in day]
               for day in proposal['native']['all_day_decisions']]
    plan={'execution_mode':'eb_native_loop','decisions':decisions,
          'control_trace_hash':digest(proposal['controls']),'horizon_end_sim_h':24}
    baseline_plan={'execution_mode':'native_no_dr','routine_actions':baseline['native']['no_dr_routine_actions'],
                   'control_trace_hash':digest(baseline['controls']),'horizon_end_sim_h':24}
    artifacts={'date_validation.json':file_hash(folder/'date_validation.json')}
    for branch in ('baseline','proposal'):
        if request['scenario'].get('environment'):
            artifacts[f'{branch}/simulation_environment.json']=file_hash(folder/branch/'simulation_environment.json')
        for name in ('native_result.json','actuator_trace.json','native_boundary_manifest.json','collection_entry.py','ep_metric_series.json','eplusout.err'):
            artifacts[f'{branch}/{name}']=file_hash(folder/branch/name)
    result={'schema_version':VERSION,'flow':'paired_ep_v1','task':'plan_judgement',
        'original_plan':request['original_plan'],'original_plan_hash':digest(request['original_plan']),
        'baseline_plan':baseline_plan,'baseline_plan_hash':digest(baseline_plan),
        'proposal_plan':plan,'proposal_plan_hash':digest(plan),'display':shown,'display_hash':digest(shown),
        'execution_status':'not_run','simulation_status':'paired_energyplus_complete',
        'forecast_status':'research_prototype_prediction','execution_mode':'eb_native_loop','prediction':prediction,
        'household_config':household,'household_config_hash':digest(household),
        'simulation_environment':request['scenario'].get('environment'),
        'date_validation':validation,
        'feedback_contract':{'required_scores':['score','comfort_score','energy_score','vpp_score'],
                             'required_comment':True},
        'assessment_stage':'after_simulated_trajectory_before_real_execution','assessment_cutoff_sim_h':24,
        'human_evaluation_context':{'artifact':'proposal/native_result.json',
            'sha256':artifacts['proposal/native_result.json'],'field':'human_evaluation_pending',
            'count':len(proposal['native']['human_evaluation_pending'])},
        'timings':{'worker_total_seconds':time.perf_counter()-started,
            'baseline_ep_seconds':baseline['seconds'],'proposal_ep_wall_seconds_including_planning':proposal['seconds'],
            'planning_rounds':sum(len(day) for day in proposal['native']['all_day_decisions']),
            'llm':{'call_count':proposal['native']['llm_call_count'],'attempts':[]}},
        'provenance':{'upstream_commit':'2b17ae63e613da776c93e900f5dace50d63a88a8',
            'entry':'family_runner.run_family_agent','boundary_version':BOUNDARY_VERSION,
            'upstream_sha256':file_hash(UPSTREAM/'experiments/benchmark/family_runner.py'),
            'source_files_at_start':hashes,'source_changed_during_run':False,'artifact_hashes':artifacts,
            'baseline_idf_sha256':baseline['idf_sha256'],'proposal_idf_sha256':proposal['idf_sha256'],
            'weather_sha256':baseline['weather_sha256'],'physical_asset_binding':proposal['asset_binding'],
            'subjective_acceptance_gate':'removed; native technical checks retained; not human consent',
            'native_plan_outcomes':native_plan_outcomes(proposal['native']),
            'sample_selection':'complete simulation retained regardless of technical fallback, savings or predicted acceptance',
            'final_score_source':'pending_human','is_full_benchmark':False,'real_appliances_controlled':False,
            'common_state_method':'same model and weather; native independent policies from day one; no prefix equality claim'}}
    if any(file_hash(ROOT/name)!=sha for name,sha in hashes.items()):raise RuntimeError('Source changed during native run')
    json.dumps(result,allow_nan=False)  # SQLite receipt cannot contain NaN/Infinity.
    write_json(folder/'outcome.json',result)
    progress('complete','两份原生仿真安排已准备好，请代表家庭评价')
