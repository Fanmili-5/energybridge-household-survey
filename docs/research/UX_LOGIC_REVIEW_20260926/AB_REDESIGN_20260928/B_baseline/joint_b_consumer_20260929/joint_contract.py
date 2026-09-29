"""Isolated joint-plan consumer. No simulation, storage, or human-label generation."""
from copy import deepcopy
from datetime import datetime
import hashlib,json,math

SCHEMA='eb.joint_b.consumer.v1'
UNIFIED_SCHEMA='eb.joint_b.consumer.v2'
HISTORY={'H0':[],'H1':[6],'H3':[4,5,6],'H5':[2,3,4,5,6],'H6':[1,2,3,4,5,6]}
ADOPTION={'accept','modify','reject','cannot_judge'}
PREFERENCE={'prefer_A','prefer_B','tie','reject_both','cannot_judge'}
MODEL_FIELD_IDS=('role-instructions','home-intro','home-visual','home-caption','home-summary',
    'home-device-inventory','home-targets','home-members','home-attitudes','joint-source-note','vpp-summary',
    'joint-weather','joint-state','joint-needs-list','selected-assets','joint-timeline',
    'joint-plan-A','joint-plan-B','joint-changes','joint-results',
    'answer-instructions','adoption-question','preference-question')

def canonical(value):
    def normalized(x):
        if isinstance(x,float):
            if not math.isfinite(x):raise ValueError('Nonfinite number')
            return int(x) if x.is_integer() else x
        if isinstance(x,dict):return {k:normalized(v)for k,v in x.items()}
        if isinstance(x,list):return [normalized(v)for v in x]
        return x
    return json.dumps(normalized(value),ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()
def split(round_index):
    if type(round_index)!=int or not 1<=round_index<=10:raise ValueError('Round must be 1..10')
    return 'train' if round_index<=6 else 'validation' if round_index<=8 else 'test'
def require(condition,message):
    if not condition:raise ValueError(message)
def interval(item):
    lo,hi=item.get('start_abs_min'),item.get('end_abs_min')
    require(type(lo)==int and type(hi)==int and lo<hi,'Invalid minute interval')
    return lo,hi
def no_answers(obj):
    if isinstance(obj,dict):
        require(not {'answer','answers','feedback','adoption','relative_preference'}.intersection(obj),'Answer in visible source')
        for v in obj.values():no_answers(v)
    elif isinstance(obj,list):
        for v in obj:no_answers(v)

def apply_commands(plan,commands,profile):
    """Deterministic reference check of supplied planned B, never physical output."""
    result=deepcopy(plan);assets={x['asset_id']:x for x in profile['profile']['devices']}
    ids=set();edited=set();windows={}
    for command in commands:
        require(command['command_id'] not in ids,'Duplicate command ID');ids.add(command['command_id'])
        asset_id=command['asset_id'];require(asset_id in assets,'Unknown command asset')
        require(assets[asset_id].get('controllable') is True,'Command asset not controllable')
        require(assets[asset_id]['device_class']==command['device_class'],'Command class mismatch')
        require(command['source_A_sha256']==digest(plan),'Wrong command A binding')
        rows=[r for r in result['rows']if r['asset_id']==asset_id];require(len(rows)==1,'Missing/duplicate asset plan')
        row=rows[0];lo,hi=interval(command)
        if command['kind'] in ('event_shift','event_interval'):
            event_id=command['event_id'];key=(asset_id,event_id);require(key not in edited,'Conflicting edits to same event');edited.add(key)
            events=[e for e in row['events']if e.get('event_id')==event_id];require(len(events)==1,'Missing/nonunique source event')
            event=events[0]
            require((event['start_abs_min'],event['end_abs_min'])==(command['A_start_abs_min'],command['A_end_abs_min']),'Wrong A event interval')
            if command['kind']=='event_shift':require(hi-lo==event['end_abs_min']-event['start_abs_min'],'Shift changed task duration')
            event.update(start_abs_min=lo,end_abs_min=hi)
        elif command['kind']=='ac_setpoint':
            require(command['device_class']=='ac','Setpoint command on non-AC')
            for a,b in windows.get(asset_id,[]):require(hi<=a or lo>=b,'Overlapping AC commands')
            windows.setdefault(asset_id,[]).append((lo,hi));out=[];covered=[]
            for event in row['events']:
                start,end=interval(event);left,right=max(start,lo),min(end,hi)
                if left>=right:out.append(event);continue
                require(event.get('setpoint_C')==command['from_setpoint_C'],'Wrong AC original temperature')
                covered.append((left,right))
                if start<left:out.append({**event,'end_abs_min':left})
                out.append({**event,'start_abs_min':left,'end_abs_min':right,'setpoint_C':command['to_setpoint_C']})
                if right<end:out.append({**event,'start_abs_min':right})
            cursor=lo
            for a,b in sorted(covered):require(a==cursor,'AC coverage gap/overlap');cursor=b
            require(cursor==hi,'AC command outside availability');row['events']=out
        else:raise ValueError('Unknown command kind')
    for row in result['rows']:
        row['events'].sort(key=lambda e:(e['start_abs_min'],e['end_abs_min']))
        for a,b in zip(row['events'],row['events'][1:]):require(a['end_abs_min']<=b['start_abs_min'],'Same-asset planned interval conflict')
    return result

def validate_case(case):
    require(case.get('schema') in {SCHEMA,UNIFIED_SCHEMA},'Unsupported consumer schema');no_answers(case)
    ident=case['identity']
    if ident['round_index'] is None:require(case.get('prototype_only') is True and ident['split'] is None,'Unassigned prototype only')
    elif ident['split'] is None:require(case['status']=='source_bound_candidate' and case['human_label_count']==0,'Unsplitted formal source only')
    else:require(ident['split']==split(ident['round_index']),'Split drift')
    profile=case['profile'];require(profile['role_id']==ident['role_id'],'Wrong profile role')
    require(case['bindings']['profile_sha256']==digest(profile),'Wrong profile binding')
    require(set(case['display_assignment'].values())=={'A','B'} and set(case['display_assignment'])=={'left','right'},'Invalid display assignment')
    plans=case['plans'];require(set(plans)=={'A','B'},'Both complete plans required')
    assets={a['asset_id']:a for a in profile['profile']['devices']};adjustable={a['asset_id']for a in assets.values()if a.get('controllable') is True}
    for side,plan in plans.items():
        require(plan['role_id']==ident['role_id'] and plan['date']==ident['date'],'Wrong plan source identity')
        require(plan['window_start_abs_min']<plan['window_end_abs_min'],'Invalid plan window')
        row_ids=[r['asset_id']for r in plan['rows']];require(len(row_ids)==len(set(row_ids)),'Duplicate asset row')
        require(adjustable<=set(row_ids)<=set(assets),'Incomplete inventory plan')
        for row in plan['rows']:
            require(row['device_class']==assets[row['asset_id']]['device_class'],'Plan class mismatch')
            require(row.get('schedule_complete') is True,'Complete source schedule required')
            for event in row['events']:
                interval(event)
                if row['device_class']=='electric_water_heater':require(event.get('operation_kind')=='heater_availability','Wrong heater semantics')
        require(case['bindings'][side+'_plan_sha256']==digest(plan),'Wrong '+side+' plan binding')
    require(plans['A']['window_start_abs_min']==plans['B']['window_start_abs_min'] and plans['A']['window_end_abs_min']==plans['B']['window_end_abs_min'],'A/B window mismatch')
    commands=case['commands'];require(isinstance(commands,list) and commands,'Explicit command list required')
    require(case['bindings']['commands_sha256']==digest(commands),'Wrong command-list binding')
    if case['schema']==SCHEMA:
        require(apply_commands(plans['A'],commands,profile)==plans['B'],
                'Full B differs from declared joint commands')
    vpp=case['vpp'];events=vpp.get('events',[vpp]);require(events,'Missing VPP events')
    require(len({e['event_id']for e in events})==len(events),'Duplicate VPP event')
    for event in events:
        lo,hi=interval(event)
        require(type(vpp['notice_abs_min'])==int and vpp['notice_abs_min']<=lo,'Invalid notification time')
        require(event['event_id'] and event['household_request']['text'],'Missing event/household request')
        require(event['household_request'].get('scope')=='household','Aggregate target cannot be household request')
        require(vpp.get('evidence_status') in {'engineering_fixture','declared_synthetic_event'},'VPP provenance not declared')
        if event.get('incentive') is not None:require(event['incentive'].get('text') and event['incentive'].get('definition_id'),'Undefined incentive')
    require(case['bindings']['vpp_sha256']==digest(vpp),'Wrong VPP binding')
    for q in case['quantities']:
        for side in ('A','B'):
            item=q[side]
            if item.get('value') is not None:
                require(type(item['value']) in (float,int) and item.get('unit') and item.get('evidence_sha256') and item.get('status') in {'computed','computed_proxy'},'Uncomputed quantity presented as result')
    if 'after_horizon' in case:
        tail=case['after_horizon']
        require(tail['status'] in {'not_provided','computed_design_proxy'} and tail['task_material_after_horizon']=='unknown','Unsupported post-event evidence')
        require(case['bindings']['after_horizon_sha256']==digest(tail),'Wrong post-event binding')
    if 'physical_readback' in case:
        physical=case['physical_readback']
        require(physical['schema']=='eb.joint_b.physical_limited.v1' and physical['status']=='limited_ground_warning_accepted','Unsupported physical result')
        require(physical['case_id']==ident['case_id'] and physical['role_id']==ident['role_id'],'Wrong physical case binding')
        require(len(physical['events'])==len(case['vpp'].get('events',[case['vpp']])),'Physical event count drift')
        require(all(physical.get(k) is None for k in ('whole_house_net_import','whole_house_cost','VPP_target_met','AC_electricity')),
                'Undeclared whole-house/AC physical result')
        for got,event in zip(physical['events'],case['vpp'].get('events',[case['vpp']])):
            require((got['start_abs_min'],got['end_abs_min'])==(event['start_abs_min'],event['end_abs_min']),
                    'Wrong physical event interval')
            for channel in got['channels']:
                require((channel['kind'],channel['unit']) in {('device_electricity','kWh'),('external_ev_energy','kWh'),
                    ('zone_temperature','C'),('ideal_cooling_thermal','kWh_th')},'Unsupported physical channel/unit')
        require(all((channel['kind'],channel['unit']) in {('device_electricity','kWh'),
            ('zone_temperature','C'),('ideal_cooling_thermal','kWh_th')}
            for channel in physical['summary_48h']['channels']), 'Unsupported 48h physical channel/unit')
        require(case['bindings']['physical_readback_sha256']==digest(physical),'Wrong physical binding')
    if 'A_only_readback' in case:
        a_only=case['A_only_readback']
        require(a_only['schema']=='eb.formal_A_only_annual.v1' and
                a_only['role_id']==ident['role_id'] and a_only['A_engine_run'] is True and
                a_only['B_engine_run'] is False and
                a_only['status'] in {'accepted_selected_outputs_engineering_only',
                                     'held_thermal_psychrometric_diagnosis'} and
                all(a_only.get(k) is None for k in ('whole_house_net_import','VPP_target_met','AC_electricity')),
                'Unsupported A-only evidence')
        require(a_only['selected_channels'] if a_only['status']=='accepted_selected_outputs_engineering_only'
                else not a_only['selected_channels'], 'A-only disposition/channel mismatch')
        require(case['bindings']['A_only_readback_sha256']==digest(a_only),'Wrong A-only binding')
    if case.get('schema')==UNIFIED_SCHEMA:
        physical=case['physical']
        require(physical['schema']=='eb.joint_b.physical.v2' and
                physical['status'] in {'not_computed','partial','complete','failed'} and
                isinstance(physical['channels'],list) and
                case['bindings']['physical_sha256']==digest(physical),
                'Wrong unified physical status/binding')
        if physical['status'] in {'not_computed','failed'}:
            require(not physical['channels'],'Uncomputed/failed physical channel has values')
        for channel in physical['channels']:
            require(channel['kind'] in {'device_electricity','external_ev_energy','zone_temperature',
                'ideal_cooling_thermal'} and channel['unit'] in {'kWh','kWh_th','C'} and
                channel['label'] and channel['scope'] in {'annual_A','event','48h'},
                'Unsupported physical channel/unit/scope')
            for side in ('A','B'):
                value=channel[side]
                require(value['status'] in {'not_computed','computed','held','failed'},
                        'Unknown side evidence status')
                if value['status']=='computed':
                    require(type(value['value']) in (int,float) and math.isfinite(value['value']) and
                            channel.get('evidence_sha256'),'Physical number lacks unit or evidence')
                else:require(value.get('value') is None,'Uncomputed physical number')
        require(isinstance(case.get('audit'),dict) and case['audit'].get('source_binding'),
                'Unified case needs independent audit source binding')
    require(case['status'] in {'engineering_fixture','source_bound_candidate'},'Unknown evidence status')
    require(case['human_label_count']==0 and case['training_release'] is False,'Prototype cannot release human labels')
    return case

def bind(case):
    """Fixture/import tool sets all content hashes before validation."""
    case['bindings'].update(profile_sha256=digest(case['profile']),A_plan_sha256=digest(case['plans']['A']),
        B_plan_sha256=digest(case['plans']['B']),commands_sha256=digest(case['commands']),vpp_sha256=digest(case['vpp']))
    if 'after_horizon' in case:case['bindings']['after_horizon_sha256']=digest(case['after_horizon'])
    if 'physical_readback' in case:case['bindings']['physical_readback_sha256']=digest(case['physical_readback'])
    if 'A_only_readback' in case:case['bindings']['A_only_readback_sha256']=digest(case['A_only_readback'])
    if 'physical' in case:case['bindings']['physical_sha256']=digest(case['physical'])
    return validate_case(case)

def visible_input(case):
    validate_case(case)
    # Strip binding/engineering identifiers from model input. Full source stays in sidecar.
    hidden={'role_id','member_id','asset_id','device_id','event_id','command_id','driver_member_id','definition_id',
            'base_household_group','conditions_status','human_permission','evidence_status','effect_path_status',
            'shared_A_pre_history','previous_answer_changes_physical_state'}
    def clean(value):
        if isinstance(value,dict):return {k:clean(v)for k,v in value.items()if k not in hidden and not k.endswith('sha256') and not k.startswith('source_')}
        if isinstance(value,list):return [clean(x)for x in value]
        return value
    assets={a['asset_id']:a for a in case['profile']['profile']['devices']}
    def asset_label(asset_id):
        a=assets[asset_id];zone=a.get('zone');labels=case['profile'].get('geometry',{}).get('zone_labels',{})
        location=labels.get(zone,zone) or '位置未提供'
        return {'device':a['device'],'location':location}
    plans={side:{**{k:v for k,v in plan.items()if k not in ('rows','role_id')},'rows':[
        {**asset_label(row['asset_id']),**clean({k:v for k,v in row.items()if k!='asset_id'})}for row in plan['rows']]}for side,plan in case['plans'].items()}
    return clean({'profile':case['profile'],'context':case['context'],'vpp':case['vpp'],'plans':plans,
        'commands':[{**asset_label(c['asset_id']),**c}for c in case['commands']], 'quantities':case['quantities'],
        'impacts':case['impacts'],'after_horizon':case.get('after_horizon'),
        'physical':case.get('physical') if case.get('schema')==UNIFIED_SCHEMA else case.get('physical_readback'),
        'result_note':case.get('result_note'),'display_assignment':case['display_assignment']})

def model_input_from_snapshot(rendered,assignment,history=None):
    """Project only the named page text fields; source structures stay in audit."""
    require(isinstance(rendered,dict),'Missing rendered snapshot')
    fields={}
    for key in MODEL_FIELD_IDS:
        require(isinstance(rendered.get(key),str),'Missing displayed field: '+key)
        fields[key]=rendered[key]
    date=rendered.get('joint-date')
    require(isinstance(date,str) and len(date)>=10 and date[:10].count('-')==2
            and (len(date)==10 or date[10:13]==' · '),'Missing displayed date')
    require(isinstance(assignment,dict) and set(assignment)=={'left','right'}
            and set(assignment.values())=={'A','B'},'Bad display assignment')
    result={'schema':'eb.joint_b.displayed_input.v1','date':date[:10],
            'fields':fields,'display_assignment':deepcopy(assignment),'history':deepcopy(history or [])}
    no_answers({k:v for k,v in result.items() if k!='history'})
    return result

def answer_quality_flags(answer):
    flags=[]
    if answer.get('adoption')=='accept' and answer.get('relative_preference')=='reject_both':
        flags.append('accept_B_and_reject_both')
    if answer.get('adoption') in {'modify','reject'} and answer.get('relative_preference')=='tie':
        flags.append('B_not_accepted_as_shown_but_tie')
    return flags

def legal_history(query,refs,records,condition='prior_training_only'):
    """References captured before query; revoked/revised history fails paired gate."""
    round_index=query['round_index'];pool=list(range(1,min(round_index,7)))
    require(condition=='prior_training_only' or (round_index>=7 and condition in HISTORY),'Invalid history condition')
    required=pool if condition=='prior_training_only' else HISTORY[condition]
    by_key={(r['presentation_id'],r['revision']):r for r in records};history={};issues=[]
    for ref in refs:
        r=by_key.get((ref['presentation_id'],ref['revision']))
        if not r:issues.append('missing_revision');continue
        n=r['round_index']
        if ref.get('round_index')!=n:issues.append('reference_round_mismatch');continue
        if r['role_id']!=query['role_id'] or r['participant_id']!=query['participant_id'] or n not in pool:
            issues.append('illegal_role_or_round');continue
        if r['answered_sequence']>=query['presented_sequence'] or r['status']!='submitted':issues.append('future_or_withdrawn');continue
        if r['answer_sha256']!=digest(r['answer']) or r['answer_sha256']!=ref['answer_sha256']:issues.append('answer_hash_mismatch');continue
        if r['visible_sha256']!=digest(r['visible_input']) or ref['visible_sha256']!=r['visible_sha256']:issues.append('visible_hash_mismatch');continue
        if r.get('model_input_sha256')!=digest(r.get('model_input')) or ref.get('model_input_sha256')!=r['model_input_sha256']:issues.append('model_input_hash_mismatch');continue
        latest=max((x['revision']for x in records if x['role_id']==r['role_id'] and x['participant_id']==r['participant_id'] and x['round_index']==n and x['answered_sequence']<query['presented_sequence']),default=0)
        if r['revision']!=latest:issues.append('obsolete_revision');continue
        model=r['model_input']
        if model.get('schema')!='eb.joint_b.displayed_input.v1' or set(model.get('fields',{}))!=set(MODEL_FIELD_IDS):issues.append('unapproved_model_fields');continue
        no_answers({k:v for k,v in model.items() if k!='history'})
        if n in history:issues.append('duplicate_round');continue
        # Earlier prompts may themselves contain history; keep only that round's shown query.
        history[n]={'round_index':n,'input':{**deepcopy(model),'history':[]},'answer':deepcopy(r['answer'])}
    # Shared query eligibility across H0/H1/...: missing full support is not hidden by H0.
    eligible=not issues and set(history)==set(pool)
    return {'history':[history[n]for n in required if n in history], 'eligible_for_paired_comparison':eligible,
            'issues':issues+([]if set(history)==set(pool)else['missing_or_withdrawn_training_support']), 'required_rounds':required}

def export_response(case,presentation,answer,refs,records,condition='prior_training_only'):
    require(case['identity']['round_index'] is not None,'Prototype has no formal split/export assignment')
    require(answer.get('adoption') in ADOPTION and answer.get('relative_preference') in PREFERENCE,'Two separate choices required')
    for key in ('modification_condition','rejection_reason','note'):require(answer.get(key) is None or isinstance(answer[key],str),'Invalid optional reason')
    visible=visible_input(case)
    require(set(presentation['display_assignment'])=={'left','right'} and set(presentation['display_assignment'].values())=={'A','B'},'Bad presentation assignment')
    visible['display_assignment']=presentation['display_assignment']
    require(presentation['visible_sha256']==digest(visible),'Presentation/input mismatch')
    require(presentation['source_package_sha256']==digest(case),'Wrong source package binding')
    require((presentation['role_id'],presentation['round_index'])==(case['identity']['role_id'],case['identity']['round_index']),'Presentation role/round mismatch')
    rendered=presentation.get('rendered_snapshot')
    require(isinstance(rendered,dict) and presentation.get('rendered_snapshot_sha256')==digest(rendered),'Wrong rendered snapshot binding')
    history=legal_history(presentation,refs,records,condition)
    model_input=model_input_from_snapshot(rendered,presentation['display_assignment'],history['history'])
    return {'schema':'eb.joint_b.engineering_export.v2','input':model_input,
        'test_feedback':deepcopy(answer),'metadata':{'source_binding':deepcopy(case['bindings']),'source_package_sha256':digest(case),
            'visible_sha256':digest(visible),'input_sha256':digest(model_input),
            'presentation':deepcopy(presentation),'history_refs':deepcopy(refs),'split':case['identity']['split'],
            'history_condition':condition,'history_gate':history,'quality_flags':answer_quality_flags(answer)},
        'audit':{'semantic_input':visible,'source_case':deepcopy(case),'rendered_snapshot':deepcopy(rendered)},
        'human_label_count':0,'training_release':False,
        'status':'engineering_fixture_not_human_feedback'}

def duplicate_keys(case):
    """No answers/results/left-right/date in signatures. Similarity is a review flag."""
    exact=sorted((c['asset_id'],c.get('event_id'),c['kind'])for c in case['commands'])
    signature=[]
    for c in case['commands']:
        signature.append((c['device_class'],c['kind'],c['start_abs_min']%1440,c['end_abs_min']-c['start_abs_min'],
            c.get('start_abs_min',0)-c.get('A_start_abs_min',c['start_abs_min']),c.get('to_setpoint_C'),c.get('from_setpoint_C')))
    result={'source_task_key':digest([case['identity']['role_id'],exact]),'near_family_key':digest(sorted(signature))}
    if case.get('scenario_family_id'):result['declared_scenario_family_id']=case['scenario_family_id']
    return result
