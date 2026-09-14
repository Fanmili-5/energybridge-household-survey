"""Run the pinned EB loop with explicit questionnaire/evaluation boundaries.

The upstream file stays immutable. The derived entry defers human scores and
uses the native switch to skip simulated consent; the planning callback and
simulator loop are unchanged.
Each invocation lives in the isolated job process, never the HTTP process.
"""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
import ast
import inspect
import json
import math
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

from common import ROOT, UPSTREAM, digest, file_hash, write_json


def _disable_sdk_retries(client):
    """Keep retry accounting in EB's explicit loop, not inside the SDK."""
    if getattr(client, 'max_retries', 0) == 0:
        return client
    copier = getattr(client, 'copy', None) or getattr(client, 'with_options', None)
    return copier(max_retries=0) if callable(copier) else client
from native_support import upstream
from resource_limits import ep_compute, api_request

BOUNDARY_VERSION = 'eb.native_questionnaire_boundaries.v3'
PINNED_RUNNER_SHA256 = '697a955ae9a5a34132c030c8d0f3b96ef6c0f63ec2caa24a2c1def23989de1d7'


def storage_snapshot(value):
    """Represent original unavailable metrics as JSON null, never as zero."""
    unavailable=[]
    def clean(item,path):
        if isinstance(item,float) and not math.isfinite(item):
            unavailable.append(path)
            return None
        if isinstance(item,dict):return {k:clean(v,path+'/'+str(k)) for k,v in item.items()}
        if isinstance(item,(tuple,list)):return [clean(v,path+'/'+str(i)) for i,v in enumerate(item)]
        return item
    result=clean(value,'')
    result['serialization']={'nonfinite_as_null':unavailable,'values_changed_in_controller':False}
    return result


def collection_entry(runner):
    """Compile the upstream entry with narrowly checked evaluation edits.

    No dummy scores and no fake roleplay source. A pending score cannot update
    preference memory. Collection is restricted to one event on the last day,
    so no subsequent control decision depends on unavailable human feedback.
    """
    if file_hash(Path(runner.__file__)) != PINNED_RUNNER_SHA256:
        raise RuntimeError('Pinned EB runner changed; source alignment must be re-audited')
    source = inspect.getsource(runner.run_family_agent)
    replacements = [
        ('allowed_score_sources = {"roleplay_llm"}',
         'allowed_score_sources = {"roleplay_llm", "human_pending"}'),
        ('sc = r.get("score") or 0.0',
         'sc = None if r.get("source") == "human_pending" else (r.get("score") or 0.0)'),
        ('_write_live_snapshot(status="scored_event")',
         '_write_live_snapshot(status="awaiting_human_feedback" if result.get("source") == "human_pending" else "scored_event")\n'
         '        if result.get("source") == "human_pending":\n'
         '            return'),
        ('if method != "no_dr" and not human_mode and len(pref_scores) != len(vpp_events):',
         'if method != "no_dr" and not human_mode and len(pref_scores) + sum(e.get("source") == "human_pending" for e in loop.vpp_event_log) != len(vpp_events):'),
    ]
    for old, new in replacements:
        if source.count(old) != 1:
            raise RuntimeError('Upstream scoring boundary changed; re-audit before running')
        source = source.replace(old, new)
    # Store an inspectable derived function, not another hand-written controller.
    namespace = dict(runner.__dict__)
    exec(compile(source, str(UPSTREAM / 'questionnaire_score_boundary.py'), 'exec'), namespace)
    return namespace['run_family_agent'], source


@contextmanager
def native_boundaries(runner, household, controls, loops, progress, audit_dir=None):
    original_init = runner._init_agent_preference_memory
    original_write = runner._write_appliance_actuators
    from energybridge.harness import memory_v3, profile_v3
    original_memory_view = memory_v3._onboarding_view
    original_profile_answers = profile_v3._normalise_answers
    def memory_input(questionnaire):
        if not isinstance(questionnaire,dict) or not isinstance(questionnaire.get('answers'),list):
            return original_memory_view(questionnaire)
        result = original_memory_view({'answers':[]})
        result['answers'] = [row for answer in questionnaire['answers']
                             for row in original_memory_view({'answers':[answer]})['answers']]
        return result
    def profile_input(questionnaire, audit):
        if not isinstance(questionnaire,dict) or not isinstance(questionnaire.get('answers'),list):
            return original_profile_answers(questionnaire,audit)
        return [row for answer in questionnaire['answers']
                for row in original_profile_answers({'answers':[answer]}, audit)]
    def initialize(loop, *args, **kwargs):
        loops.append(loop)
        return original_init(loop, *args, **kwargs)
    def onboarding(persona_config, controller_observable_only=False):
        # These are actual answers. No LLM answers the initial questionnaire.
        result = deepcopy(household['onboarding'])
        answers = []
        for raw in result['answers']:
            text = raw['answer']
            for i in range(0, max(1,len(text)), 500):
                answer = deepcopy(raw)
                answer['answer'] = text[i:i+500]
                if raw['id']=='A_EB_CONTROL':
                    aliases={'confirm_required':'confirm_before_changes','high_trust_auto':'automatic_optimization_ok'}
                    answer['selected_option_ids'] += [aliases[x] for x in raw['selected_option_ids'] if x in aliases]
                if len(text)>500:
                    answer['id'] = raw['id']+'_part_'+str(i//500+1)
                    answer['selected_option_ids'] = []
                answers.append(answer)
        result['answers'] = answers
        return result
    def project(answers):
        # The original 4-question projection would discard the rest of this
        # real questionnaire. Only the input boundary is widened here.
        return {'source': 'household_representative_questionnaire',
                'answers': deepcopy(answers['answers']),
                'inferred_profile': {}, 'preference_rules': []}
    def writer(ex, state, loop, powers, sim_h):
        values = {}
        class ObserveExchange:
            def __getattr__(self, key): return getattr(ex, key)
            def set_actuator_value(self, state, handle, value):
                values[handle] = value
                return ex.set_actuator_value(state, handle, value)
        original_write(ObserveExchange(), state, loop, powers, sim_h)
        handles = {'washer':'h_washer','dishwasher':'h_dishwasher','dryer':'h_dryer',
                   'ev':'h_ev','water_heater':'h_ewh_sp','refrigerator':'h_refrigerator'}
        availability = ex.get_actuator_value(state,loop.h_hvac_avail) if loop.h_hvac_avail!=-1 else None
        cooling = ex.get_actuator_value(state,loop.h_cool) if loop.h_cool!=-1 else loop.sp
        controls.append({'start_h':float(sim_h), 'cooling_setpoint':float(cooling),
                         'hvac_available': availability is not None and availability>0,
                         'native_device_power_kw':deepcopy(powers),
                         'actuators':{key:values[getattr(loop, attr)] for key,attr in handles.items()
                                      if getattr(loop,attr,-1) in values}})
    def clarification(inputs, request, *, persona_config):
        updated = deepcopy(inputs)
        reply = {'question':str(request.get('question','')), 'answer':'本次没有采集这个追问的真人回答；请使用已填写的问卷信息，不得推断同意。',
                 'certainty':'unsure', 'conditions':'', 'source':'questionnaire_clarification_unavailable',
                 'decision_relevance':request.get('decision_relevance','')}
        updated.setdefault('observable_profile',{})['event_clarification'] = reply
        return updated, {'status':'unavailable','request':deepcopy(request),'observable_reply':reply,
                         'hidden_resume_returned':False,'raw_roleplay_response_returned':False}, {}
    overrides = {'_init_agent_preference_memory':initialize,
                 '_run_agent_onboarding_questionnaire':onboarding,
                 '_observable_agent_onboarding_projection':project,
                 '_adaptive_v3_answer_clarification':clarification,
                 '_write_appliance_actuators':writer}
    # Every upstream controller/model call shares the website's API limiter.
    from energybridge.llm.client import LLMClient
    original_chat = LLMClient.chat_with_metrics
    original_get_client = LLMClient._get_client_for_key
    call_count = 0
    callback_errors = []
    original_unraisable = sys.unraisablehook
    def unraisable(event):
        # ctypes otherwise prints a Python callback failure and lets EP report
        # exit=0. Such a partial controller run must never become a rated pair.
        callback_errors.append(type(event.exc_value).__name__)
        original_unraisable(event)
    def limited_chat(client, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        path = Path(audit_dir)/'model_calls'/f'{call_count:04d}' if audit_dir else None
        if path:
            write_json(path/'request.json',{'system_prompt':args[0] if args else kwargs.get('system_prompt'),
                'user_prompt':args[1] if len(args)>1 else kwargs.get('user_prompt'),
                'source':'native_model_call','model':client.config.model})
        progress('planning', 'EB 原生流程正在规划；请保留此页面。')
        try:
            with api_request(): result=original_chat(client, *args, **kwargs)
        except Exception as exc:
            if path:write_json(path/'failure.json',{'error_type':type(exc).__name__})
            raise
        if path:write_json(path/'response.json',{'text':result.get('text'),'source':'native_model_response'})
        return result
    def one_layer_transport(client, key):
        sdk_client = _disable_sdk_retries(original_get_client(client, key))
        client._client = sdk_client
        return sdk_client
    with patch.dict(runner.__dict__, overrides), patch.object(LLMClient, 'chat_with_metrics', limited_chat), \
         patch.object(LLMClient, '_get_client_for_key', one_layer_transport), \
         patch.object(memory_v3,'_onboarding_view',memory_input), patch.object(profile_v3,'_normalise_answers',profile_input), \
         patch.object(sys,'unraisablehook',unraisable):
        yield
    if callback_errors:raise RuntimeError('Native callback failed; simulation cannot be rated')


def run_native(folder, request, *, method, progress=lambda *args: None):
    if method not in ('agent', 'no_dr'): raise ValueError('Unsupported collection method')
    from household_config import ensure_household_config
    household = ensure_household_config(request)
    scenario = request['scenario']
    window = scenario['evaluation_window']
    days = int(window['simulation_days'])
    event = deepcopy(scenario['event'])
    # This restriction prevents a missing human score influencing later days.
    if event['day'] != days or window['end_sim_h'] != days*24:
        raise ValueError('Native collection requires the event on the final simulation day')
    offset = (days-1)*24
    event.update(trigger_h=offset+event['trigger_h'], end_h=offset+event['end_h'])
    runner, _ = upstream()
    sys.modules.setdefault('family_runner', runner)
    from experiments.benchmark.run_persona_json import _prepare_run_assets
    folder = Path(folder)
    folder.parent.mkdir(parents=True, exist_ok=True)
    template = UPSTREAM / 'experiments/models/family_home/family_simple.idf'
    args = SimpleNamespace(city='tianjin', epw=None, weather_csv=None,
                           regenerate_epw=False, price_csv=None, idf=template)
    environment=scenario.get('environment')
    if environment:
        from simulation_environment import verify
        template,epw_source,ddy_source=verify(environment)
        args.idf=template;args.epw=epw_source
        # city=tianjin deliberately retains the original normalized TOU experiment.
        # Weather is explicit and never resolved through that tariff key.
        if scenario['simulation_start_date']!=environment['simulation_start_date'] or days!=environment['simulation_days']:
            raise ValueError('Scenario and resolved environment disagree')
    start_date=scenario.get('simulation_start_date','2007-07-01')
    idf, epw, price = _prepare_run_assets(args, folder, days, start_date, household)
    if environment:
        from simulation_environment import localize_idf
        localization=localize_idf(idf,epw,ddy_source)
    from native_assets import reporting_assets, bind_native_appliances
    binding = bind_native_appliances(idf, runner._APPL_DESIGN_W)
    asset_binding = reporting_assets(idf)
    asset_binding['source_template'] = {
        'path': str(template.relative_to(ROOT.parent if environment else UPSTREAM)), 'sha256': file_hash(template),
        'simulation_days': days, 'simulation_start_date': start_date,
    }
    asset_binding['appliance_binding_repair'] = binding
    price_source=Path(price.source)
    if not price_source.is_file():
        raise ValueError('Native tariff source is missing')
    asset_binding['tariff']={
        'id':scenario['tariff']['id'],
        'source':str(price_source.relative_to(UPSTREAM) if price_source.is_relative_to(UPSTREAM) else price_source),
        'sha256':file_hash(price_source),
        'unit':price.price_unit,
        'geographic_scope':scenario['tariff']['geographic_scope'],
    }
    if environment:
        asset_binding['simulation_environment']=environment
        asset_binding['regional_localization']=localization
        write_json(folder/'simulation_environment.json',environment)
    asset_binding['equipment_or_control_changes'] = True
    asset_binding['equipment_changes'] = True
    asset_binding['control_changes'] = False
    controls, loops, pending = [], [], []
    def human_pending(**context):
        pending.append(deepcopy(context))
        return {'source':'human_pending', 'label':'awaiting_human_feedback',
                'score':None, 'comfort_score':None, 'energy_score':None, 'vpp_score':None,
                'comment':''}
    def preferences(*args, **kwargs):
        return json.dumps(household['observable_profile'], ensure_ascii=False)
    environment = {'ENERGYBRIDGE_HARNESS_PROFILE':'agentic_v3',
                   'ENERGYBRIDGE_DISABLE_ACCEPTANCE_FALLBACK':'1',
                   'ENERGYBRIDGE_PERSIST_AGENT_MEMORY':'1',
                   'ENERGYBRIDGE_LOAD_AGENT_MEMORY':'0', 'ENERGYBRIDGE_AGENT_MEMORY_STORE':''}
    started = time.perf_counter()
    from native_clock import synchronized_appliances
    _, suite_class = upstream()
    with patch.dict(os.environ, environment), synchronized_appliances(runner, suite_class, loops) as clock_audit, \
         native_boundaries(runner, household, controls, loops, progress, folder):
        entry, derived_source = collection_entry(runner)
        with ep_compute():
            result = entry(idf_path=idf, epw_path=epw, output_dir=folder,
                           weather_label=scenario.get('environment',{}).get('weather',{}).get('city','Tianjin'), user_pref='', persona_config=household,
                           appliance_config=household['appliances'], method=method,
                           sim_days=days, start_date=start_date,
                           day_ahead_price_profile=price, vpp_events_config=[event],
                           vpp_schedule_source='questionnaire_randomized_final_day_event',
                           pre_event_preference_callback=preferences,
                           post_event_score_callback=human_pending)
    # The original runner recreates its output directory at entry.
    if scenario.get('environment'):
        write_json(folder/'simulation_environment.json',scenario['environment'])
    if result.exit_code != 0: raise RuntimeError('Native EnergyPlus simulation failed')
    error_log=folder/'eplusout.err'
    if not error_log.is_file():raise RuntimeError('Missing native EnergyPlus diagnostics')
    errors=error_log.read_text(errors='replace')
    if '** Severe **' in errors or '**  Fatal  **' in errors or '** Fatal **' in errors:
        raise RuntimeError('EnergyPlus reported a severe or fatal error; diagnostics retained; no human rating generated')
    if not loops: raise RuntimeError('Missing native loop audit')
    loop = loops[-1]
    handles = {'ac':'h_cool','washer':'h_washer','dishwasher':'h_dishwasher','dryer':'h_dryer',
               'ev':'h_ev','water_heater':'h_ewh_sp','refrigerator':'h_refrigerator'}
    missing = [key for key,attr in handles.items() if household['appliances'].get(key,{}).get('present') and getattr(loop,attr,-1)==-1]
    asset_binding['unbound_native_device_ports']=missing
    if missing:
        write_json(folder/'physical_binding_failure.json',asset_binding)
        raise RuntimeError('Selected native devices missing EnergyPlus bindings: '+','.join(missing))
    asset_binding['device_timeline_source']='native appliance_sim powers; actual EP writes recorded separately'
    # Keep the full native decision history, not its truncated dashboard tail.
    data = asdict(result)
    # Native aggregate gate metrics describe consent in the benchmark; our
    # technical pass/fail must never be exported as household acceptance.
    for key in ('vpp_plan_acceptance_rate','vpp_plan_acceptance_probability_avg',
                'vpp_plan_rejected_count','accepted_effective_vpp_success_rate'):
        data[key] = None
    data['all_day_decisions'] = deepcopy(loop.day_agent_decisions)
    data['human_evaluation_pending'] = pending
    data['household_binding'] = {'household_config_hash':digest(household),
        'questionnaire_answer_ids':[a['id'] for a in household['onboarding']['answers']],
        'memory_onboarding':deepcopy(getattr(loop,'agent_preference_memory',{}).get('onboarding')),
        'profile_evidence':deepcopy(getattr(loop,'agent_household_model',{}).get('evidence_index',[]))}
    data=storage_snapshot(data)
    write_json(folder/'native_result.json', data)
    (folder/'collection_entry.py').write_text(derived_source)
    write_json(folder/'appliance_clock.json', clock_audit)
    write_json(folder/'native_boundary_manifest.json', {
        'version':BOUNDARY_VERSION, 'upstream_entry':'family_runner.run_family_agent',
        'upstream_sha256':file_hash(Path(runner.__file__)),
        'derived_entry_sha256':file_hash(folder/'collection_entry.py'),
        'scope':'questionnaire input; native consent bypass; deferred human score; tracing; API admission; zone-synchronized appliance execution',
        'execution_clock': clock_audit['version'],
        'method':method,'settings':environment, 'human_labels_generated':False,
        'physical_asset_binding':asset_binding})
    # Commands are effective from their native write time until the next write.
    unique = {r['start_h']:r for r in controls if 0 <= r['start_h'] < days*24}
    rows = [unique[h] for h in sorted(unique)]
    for i, row in enumerate(rows):
        row['end_h'] = rows[i+1]['start_h'] if i+1<len(rows) else days*24
    write_json(folder/'actuator_trace.json', rows)
    trace = result.daily_trace_rows
    if not trace or max(r['sim_h'] for r in trace) < days*24-.25:
        raise RuntimeError('Incomplete native simulation timeline')
    from native_assets import read_series, find
    physical = read_series(folder, horizon=days*24,start_date=start_date)
    from native_service_evidence import evidence
    services=evidence(clock_audit,physical,household,horizon=days*24)
    write_json(folder/'service_evidence.json',services)
    energy = find(physical, 'Electricity:Facility', horizon=days*24, unit='J')
    temperature = find(physical, 'Zone Mean Air Temperature', 'living_unit1', horizon=days*24)
    electricity=[{'end_h':r['end_h'],'kwh':r['value']/3600000} for r in energy]
    temperatures=[{'end_h':r['end_h'],'c':r['value']} for r in temperature]
    write_json(folder/'ep_metric_series.json',{
        'schema_version':'eb.ep_metric_series.v1','source':'EnergyPlus SQLite output',
        'simulation_start_date':start_date,'horizon_hours':days*24,
        'environment_hash':scenario.get('environment',{}).get('environment_hash'),
        'electricity_facility':{'unit':'kWh per interval','rows':electricity},
        'living_unit1_mean_air_temperature':{'unit':'degC','rows':temperatures}})
    return {'native':data, 'controls':rows, 'execution_clock':clock_audit, 'seconds':time.perf_counter()-started,
            'temperature':temperatures, 'service_evidence':services,
            'electricity':electricity,
            'execution':{'services':data['appliance_results']},
            'task_outcomes':{device:{'completed':app._days[days-1].completed}
                             for device,app in loop.appliance_suite._shiftable.items() if app.present},
            'asset_binding':asset_binding,
            'idf_sha256':file_hash(idf), 'weather_sha256':file_hash(epw),
            'decisions':[], 'horizon':days*24}
