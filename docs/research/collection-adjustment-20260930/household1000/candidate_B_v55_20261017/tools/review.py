"""Full-population verification from raw10min states, independent of classifier functions."""
import sys,collections,math
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *

TOP_CHANGED={'schema','rules_sha256','pair_content_sha256','proposal','classification','source_B','B_frozen_sha256','source_generation_rules_sha256','classification_only_update'}
PFLAGS={'explicit_adverse_request','adverse_design_intent'}
CFLAGS={'boundary_variant','deliberate_reverse_direction','adverse_variant','requested_reverse_variant'}
BAD_TAGS={'opposing_or_excessive_response','beyond_deadline_overreaction','explicit_reverse_bounds','pause_opposes_up_request'}
def direction(n):return 'up'if n>1e-8 else'down'if n< -1e-8 else'unchanged'
def combined(ds):
    ds=set(ds)-{'unchanged'}
    return 'unchanged'if not ds else'mixed'if len(ds)>1 else next(iter(ds))
def request_relation(d,r):return 'unchanged'if d=='unchanged'else'mixed'if d=='mixed'else'aligned'if d==r else'opposing'
def value_direction(kind,a,b):
    if a is None:return 'up'
    if b is None:return 'down'
    if kind=='ac_setpoint':return combined([direction(b[0]-a[0]),direction(a[1]-b[1]),direction(b[2]-a[2])])
    return direction(b[0]-a[0])
def samples(plan):
    result={}
    for x in plan['controls']:
        fields={'ac_setpoint':['heating_setpoint_C','cooling_setpoint_C','fan_operating_mode'],'tank_setpoint':['value_C'],'ev_charge_window':['stop_at_target_soc']}[x['kind']]
        state=tuple(float(x[k])+0. for k in fields)
        for t in range(x['start_min'],x['end_min'],10):
            key=(x['kind'],x['asset_id'],t)
            if key in result:raise ValueError('overlapping control')
            result[key]=state
    return result

def audit_rows(rows):
    verify_inputs();sig=rules_id();b=read(OUT/'PAIR_BINDINGS10000.json');errors=[];counts=collections.Counter()
    source={r['household_id']:r for r in read(SOURCE_B/'PAIR_BINDINGS10000.json')['records']}
    actualgrades=collections.defaultdict(collections.Counter);evstats=collections.Counter();windowlengths=collections.Counter();behaviors=collections.Counter();grades=collections.defaultdict(collections.Counter);transitions=collections.Counter();relations=collections.Counter();families=collections.Counter()
    noops=[];changed=[];examples={};all_patterns=collections.Counter();changed_patterns=collections.Counter();program_shifts=collections.defaultdict(collections.Counter)
    allowed={'schema','B','B_frozen_sha256','proposal','classification','assessment_B','HVAC_signals_B','VPP_response_reference','event_relations','source_B','rules_sha256','source_generation_rules_sha256','classification_only_update','pair_content_sha256','material_revision','EV_continuous_reference','revision_parent','device_strength_rebuild','selection_or_regeneration_based_on_B_outcome'}
    def fail(case,code):errors.append([case,code])
    native_refs={(r['household_id'],r['date']):r for r in read(OUT/'STATE_BINDINGS.json')['records']}
    for row in rows:
        oldrows={r['case_id']:r for r in source[row['household_id']]['rounds']};world=None
        if {r['case_id']for r in row['rounds']}!=set(oldrows):fail(row['household_id'],'CASE_IDS_CHANGED')
        for rr in row['rounds']:
            p=read(OUT/rr['path']);oref=oldrows[rr['case_id']];old=read(SOURCE_B/oref['path']);case=p['case_id'];counts['cases']+=1
            if sha(OUT/rr['path'])!=rr['sha256']or sha(SOURCE_B/oref['path'])!=oref['sha256']:fail(case,'HASH')
            if {k:v for k,v in p.items()if k not in allowed}!={k:v for k,v in old.items()if k not in allowed}:fail(case,'FIXED_CONTEXT_CHANGED')
            body=copy.deepcopy(p);claim=body.pop('pair_content_sha256')
            if digest(body)!=claim or digest(p['B'])!=p['B_frozen_sha256']:fail(case,'PAYLOAD_DIGEST')
            if p['A']!=old['A']or p['needs_A']!=old['needs_A']or p['needs_B']!=old['needs_B']:fail(case,'A_OR_DEMAND_CHANGED')
            if p['human_response']!={'accepted':None,'scores':None,'reason':None}or p['physical_results']is not None or p['questionnaire_stimulus']is not None:fail(case,'PREFILLED_OUTCOME')
            if world is None:
                wp=A_STAGE/p['A_source']['world_path'];world=read(wp);assets={d['asset_id']:d for d in world['parameter_pack']['devices']}
                if sha(wp)!=p['A_source']['world_sha256']:fail(case,'A_WORLD_HASH')
            q=p['proposal'];actual=p['classification']['actual_actions'];failure=p['classification']['constraint_failure']
            nr=native_refs[p['household_id'],p['date']];native_state=None
            for request in q['requested_device_strengths']:
                if request['device_family']not in('ac','water_heater'):continue
                for event in request['input_state_plan']['all_event_input_states']:
                    st=event['native_A_event_state']
                    if st['status']!='native_A_reference'or st['state_sha256']!=nr['state_sha256']:fail(case,'NATIVE_REFERENCE_LINEAGE')
                if native_state is None:
                    np=OUT/nr['state_path']
                    if sha(np)!=nr['state_sha256']:fail(case,'NATIVE_STATE_HASH')
                    native_state=read(np)
                aid=request['asset_ids'][0];mapping=native_state['asset_mapping'][aid]
                for event in request['input_state_plan']['all_event_input_states']:
                    st=event['native_A_event_state'];lo,hi=event['start_min'],event['end_min']
                    channels=native_state['channels']
                    def raw(key,var):return [[t,v]for t,v in channels.get(str(key)+'|'+var,[])if lo<=t<hi]
                    if request['device_family']=='ac':
                        keys=mapping['energy_keys'];he=raw(keys['Coil:Heating:DX:SingleSpeed'],'Heating Coil Electricity Energy');su=raw(keys['Coil:Heating:Electric'],'Heating Coil Electricity Energy');co=raw(keys['Coil:Cooling:DX:SingleSpeed'],'Cooling Coil Electricity Energy');indoor=raw(mapping['room_key'],'Zone Mean Air Temperature')
                        if st['timestep_profile']!={'indoor_C':indoor,'heat_J':he,'supplement_J':su,'cool_J':co}:fail(case,'NATIVE_EVENT_PROFILE')
                        active=len({t for t,v in he+su+co if v>1})*10
                    else:
                        tank=raw(mapping['tank_key'],'Water Heater Tank Temperature');power=raw(mapping['tank_key'],'Water Heater Heating Rate')
                        if st['timestep_profile']!={'tank_C':tank,'heater_W':power}:fail(case,'NATIVE_TANK_PROFILE')
                        active=len({t for t,v in power if v>1})*10
                    if active!=st['active_minutes']:fail(case,'NATIVE_ACTIVE_MINUTES')

            if any(k in q for k in ['level','requested_level','design_level','effective_level','actual_command_intensity']):fail(case,'OLD_GLOBAL_GRADE_ACTIVE')
            selected_ids={r['input_state_plan']['event']['event_id']for r in q['requested_device_strengths']}
            focus=next(iter(selected_ids))if len(selected_ids)==1 else None
            if q['focus_VPP_event_id']!=focus or q['multi_event_policy']['combined_target_success_guaranteed']:fail(case,'STALE_GLOBAL_FOCUS')
            if q['selected_input_vector']!='vector_0' or q['selection_uses_physical_outcomes_or_acceptance']:fail(case,'OUTCOME_SELECTION')
            aa,bb=samples(p['A']),samples(p['B']);diff={k:(aa.get(k),bb.get(k))for k in set(aa)|set(bb)if aa.get(k)!=bb.get(k)}
            if any(k[2]<480 for k in diff):fail(case,'PREDECISION_CONTROL_CHANGED')
            declared={};direction_at={}
            for x in actual['control_changes']:
                fields={'ac_setpoint':['heating_setpoint_C','cooling_setpoint_C','fan_operating_mode'],'tank_setpoint':['value_C'],'ev_charge_window':['stop_at_target_soc']}[x['kind']]
                av=tuple(x['A'][k]for k in fields)if x['A']else None;bv=tuple(x['B'][k]for k in fields)if x['B']else None;d=value_direction(x['kind'],av,bv)
                if x['control_request_direction']!=d:fail(case,'CONTROL_DIRECTION')
                for t in range(x['start_min'],x['end_min'],10):declared[x['kind'],x['asset_id'],t]=(av,bv);direction_at[x['kind'],x['asset_id'],t]=d
            if declared!=diff:fail(case,'CONTROL_CLASSIFICATION')
            anychange=bool(diff)
            for key,ident,outkey,fields in [('tasks','task_id','program_changes',['kind','asset_id','start_min','end_min']),('operations','operation_id','manual_operation_changes',['kind','asset_id','operator_id','room_id','start_min','end_min'])]:
                a={x[ident]:{k:x[k]for k in fields}for x in p['A'][key]};z={x[ident]:{k:x[k]for k in fields}for x in p['B'][key]}
                if set(a)!=set(z):fail(case,'INVENTED_OR_REMOVED_ACTION');continue
                expected={oid:(a[oid],z[oid])for oid in a if a[oid]!=z[oid]};got={x[ident]:(x['A'],x['B'])for x in actual[outkey]}
                if expected!=got:fail(case,'PROGRAM_OR_MANUAL_CLASSIFICATION')
                if any(a[k]['start_min']<480 for k in expected):fail(case,'PREDECISION_TASK_CHANGED')
                anychange=anychange or bool(expected)
            evops=lambda plan:[x for x in plan['operations']if x['kind'].startswith('EV_')]
            if evops(p['A'])!=evops(p['B']):fail(case,'EV_HANDLING_CHANGED')
            same=not old['classification']['actual_actions']['any_command_change']
            if same:
                if p['B']!=old['B']:fail(case,'FIXED100_PAYLOAD_CHANGED')
                counts['same100_payload_preserved']+=p['B']==old['B']
            else:counts['B_payload_changed']+=p['B']!=old['B']
            if anychange==same or actual['any_command_change']!=anychange:fail(case,'CHANGED_STATUS')
            group='changed_commands'if anychange else'identical_commands';counts[group]+=1
            if actual['comparison_group']!=group or rr['comparison_group']!=group:fail(case,'GROUP')
            if failure['flags']!=p['assessment_B']['constraint_flags']or failure['has_given_constraint_conflict']!=bool(failure['flags']):fail(case,'FAILURE_CLASS')
            flags=bool(failure['flags']);counts['constraint_conflict_cases']+=flags
            transitions[str(bool(old['assessment_B']['constraint_flags']))+'->'+str(flags)]+=1
            families.update(actual['changed_device_families'])
            requested=q['requested_device_strengths'];observed=q['actual_device_strengths'];levels={}
            touched={x['asset_id']for key in ['program_changes','manual_operation_changes','control_changes']for x in old['classification']['actual_actions'][key]}
            if {a for r in requested for a in r['asset_ids']}!=touched:fail(case,'SOURCE_OBJECTS_CHANGED')
            for r,obs in zip(requested,observed):
                key=r['controller_key'];fam=r['device_family'];aid=r['asset_ids'][0];d=assets[aid];j=rank('independent-device-strength-v53',case,key)%4;grade=LEVELS[j];levels[key]=j;grades[fam][grade]+=1
                if r['grade']!=grade or obs['requested_grade']!=grade or obs['controller_key']!=key:fail(case,'INDEPENDENT_ASSIGNMENT')
                params=r['parameters']
                context=r['input_state_plan'];behaviors[context['behavior']]+=1
                if not context['selected_before_B']or context['uses_B_success_or_human_acceptance']:fail(case,'STATE_PLAN_OUTCOME_SELECTION')
                if context['event']['event_id']not in{e['event_id']for e in p['VPP_events']}:fail(case,'UNKNOWN_PLANNED_EVENT')
                def independent_band(v,limits):
                    if abs(v)<1e-8:return 'none'
                    return next((LEVELS[k]for k,x in enumerate(limits)if v<=x+1e-8),'extreme')
                if fam in('washer','dishwasher'):
                    duration=d['parameters'].get(fam,d['parameters'])['duration_h']*60
                    lim=[math.ceil(duration*f/10-1e-9)*10 for f in(.25,.5,1,2)]
                    val=max([abs(x['start_shift_minutes'])for x in obs['program_changes']]+[0])
                    if not val:val=max([abs(x['start_shift_minutes'])for x in obs['manual_operation_changes']]+[0])
                    expectedgrade=independent_band(val,lim)
                elif fam=='ev':
                    val=max([1-(x['B_window_min'][1]-x['B_window_min'][0])/(x['A_window_min'][1]-x['A_window_min'][0])for x in obs['EV_window_metrics']]+[0]);expectedgrade=independent_band(val,[.25,.5,.75,1])
                    for m in obs['EV_window_metrics']:
                        negative=m['B_window_slack_minutes']<0;evstats[str((grade,negative))]+=1;windowlengths[str(m['B_window_min'][1]-m['B_window_min'][0])]+=1
                        need=next(x for x in p['needs_A']if x['need_id']==m['need_id']);aaev=next(x for x in p['A']['controls']if x['kind']=='ev_charge_window'and x['need_id']==m['need_id']);bbev=next(x for x in p['B']['controls']if x['kind']=='ev_charge_window'and x['need_id']==m['need_id'])
                        full=aaev['battery_energy_kWh']/(d['parameters']['charger_kw']*d['parameters']['efficiency'])*60
                        if abs(full-m['constant_power_full_charge_minutes'])>1e-7 or m['A_window_min']!=[aaev['start_min'],aaev['end_min']]or m['B_window_min']!=[bbev['start_min'],bbev['end_min']]:fail(case,'EV_RAW_METRICS')
                        if bbev['start_min']<aaev['start_min']or bbev['end_min']>aaev['end_min']:fail(case,'EV_OUTSIDE_CONNECTION')
                else:
                    keys=['heating_setpoint_C','cooling_setpoint_C']if fam=='ac'else['value_C']
                    val=max([abs(x['A'][k]-x['B'][k])for x in obs['control_segments']if x['A']and x['B']for k in keys]+[0]);limits=[.5,1,1.5,2]if fam=='ac'else[1,2,3,5]
                    if not val:
                        durations=[]
                        for asset in obs['asset_ids']:
                            times=sorted(t for(kind,aid,t)in diff if aid==asset);groups=[]
                            for t in times:
                                if groups and t==groups[-1][-1]+10:groups[-1].append(t)
                                else:groups.append([t])
                            durations.extend(len(g)*10 for g in groups)
                        val=max(durations+[0]);limits=[20,30,60,90]
                    expectedgrade=independent_band(val,limits)
                # Check every exposed axis independently from literal programs,
                # handling and sampled control changes; no aggregate grade.
                axis_expected={}
                if fam in('washer','dishwasher'):
                    lim=[math.ceil(duration*f/10-1e-9)*10 for f in(.25,.5,1,2)]
                    axis_expected={'program_shift_min':(max([abs(x['start_shift_minutes'])for x in obs['program_changes']]+[0]),lim),'manual_shift_min':(max([abs(x['start_shift_minutes'])for x in obs['manual_operation_changes']]+[0]),lim)}
                elif fam=='ev':
                    ms=obs['EV_window_metrics']
                    axis_expected={'window_fraction_removed':(max([1-(x['B_window_min'][1]-x['B_window_min'][0])/(x['A_window_min'][1]-x['A_window_min'][0])for x in ms]+[0]),[.25,.5,.75,1]),'start_delay_min':(max([x['delay_minutes']for x in ms]+[0]),[30,60,120,240]),'required_energy_shortfall_fraction':(max([max(0,-x['B_window_slack_minutes'])/x['constant_power_full_charge_minutes']for x in ms]+[0]),[.05,.15,.3,1])}
                    for x in ms:
                        if not x.get('formation_path'):fail(case,'MISSING_EV_CAUSE_CHAIN')
                else:
                    ks=['heating_setpoint_C','cooling_setpoint_C']if fam=='ac'else['value_C']
                    dv=max([abs(x['A'][k]-x['B'][k])for x in obs['control_segments']if x['A']and x['B']for k in ks]+[0]);groups=[]
                    for asset in obs['asset_ids']:
                        run=[]
                        for t in sorted(t for(kind,aid,t)in diff if aid==asset):
                            if run and t!=run[-1]+10:groups.append(len(run)*10);run=[]
                            run.append(t)
                        if run:groups.append(len(run)*10)
                    axis_expected={'setpoint_delta_C':(dv,[.5,1,1.5,2]if fam=='ac'else[1,2,3,5]),'continuous_command_change_min':(max(groups+[0]),[20,30,60,90])}
                if set(axis_expected)!=set(obs['actual_strength_axes']):fail(case,'AXIS_SET')
                for ax,(number,limits)in axis_expected.items():
                    shown=obs['actual_strength_axes'][ax]
                    if abs(shown['value']-number)>1e-7 or shown['grade']!=independent_band(number,limits):fail(case,'RAW_AXIS_MISMATCH:'+ax)
                if obs['actual_primary_grade']!=expectedgrade or abs(obs['actual_primary_value']-val)>1e-7:fail(case,'ACTUAL_GRADE_NOT_RAW_MAGNITUDE')
                for axis,v in obs['actual_strength_axes'].items():actualgrades[fam+':'+axis][v['grade']]+=1
                display=obs.get('strength_presentation',{})
                if display.get('overall_grade')is not None or not display.get('axes_must_be_shown_together')or {x['axis']: {'value':x['value'],'grade':x['grade']}for x in display.get('axes',[])}!=obs['actual_strength_axes']:fail(case,'MULTIAXIS_DISPLAY_MISMATCH')
                if 'actual_primary_grade'in q['actual_grades_from_executable_commands'][requested.index(r)]:fail(case,'PRIMARY_GRADE_STILL_EXPOSED')
                if fam=='ac':
                    if params['setpoint_delta_C']!=[.5,1,1.5,2][j]or params['exposure_cap_min']!=[20,30,60,90][j]or params['preconditioning_lead_cap_min']!=[20,40,60,120][j]:fail(case,'AC_NATIVE_GRID')
                elif fam=='water_heater':
                    if params['target_delta_C']!=[1,2,3,5][j]or params['exposure_cap_min']!=[20,30,60,90][j]:fail(case,'TANK_NATIVE_GRID')
                elif fam in ('washer','dishwasher'):
                    pdev=d['parameters'];duration=pdev.get(fam,pdev)['duration_h']*60;target=math.ceil(duration*[.25,.5,1,2][j]/10-1e-9)*10
                    if params['requested_shift_min']!=target or params['program_duration_min']!=duration:fail(case,'PROGRAM_NATIVE_GRID')
                    for pc in obs['program_changes']:
                        program_shifts[fam][pc['start_shift_minutes']]+=1
                        if abs(pc['start_shift_minutes'])>target:fail(case,'PROGRAM_MAGNITUDE')
                elif fam=='ev':
                    if params['required_charge_time_multiplier']!=[.25,.5,1,2][j]or params['event_target_scale']!=[.25,.5,1,1.5][j]:fail(case,'EV_NATIVE_GRID')
                    for ev in obs['EV_window_metrics']:
                        if not ev['required_target_soc_unchanged']or abs(ev['B_window_slack_minutes']-(ev['B_window_min'][1]-ev['B_window_min'][0]-ev['constant_power_full_charge_minutes']))>1e-7:fail(case,'EV_METRICS')
                        counts['negative_EV_window_slack_requests_kept']+=ev['B_window_slack_minutes']<0
                obs_diff={}
                for x in obs['control_segments']:
                    fields={'ac_setpoint':['heating_setpoint_C','cooling_setpoint_C','fan_operating_mode'],'tank_setpoint':['value_C'],'ev_charge_window':['stop_at_target_soc']}[x['kind']]
                    av=tuple(x['A'][k]for k in fields)if x['A']else None;bv=tuple(x['B'][k]for k in fields)if x['B']else None
                    for t in range(x['start_min'],x['end_min'],10):obs_diff[x['kind'],x['asset_id'],t]=(av,bv)
                    if fam in ('ac','water_heater')and x['A']and x['B']:
                        keys=['heating_setpoint_C','cooling_setpoint_C']if fam=='ac'else['value_C'];cap=params['setpoint_delta_C']if fam=='ac'else params['target_delta_C']
                        if any(abs(x['A'][k]-x['B'][k])>cap+1e-8 for k in keys):fail(case,'ACTUAL_TEMP_EXCEEDS_NATIVE_GRADE')
                if obs_diff!={k:v for k,v in diff.items()if k[1]in r['asset_ids']}:fail(case,'ACTUAL_NATIVE_CONTROL_METRICS')
                for listkey,plankey,ident in [('program_changes','tasks','task_id'),('manual_operation_changes','operations','operation_id')]:
                    oldids={x[ident]:x for x in p['A'][plankey]};newids={x[ident]:x for x in p['B'][plankey]}
                    expected={k:newids[k]['start_min']-x['start_min']for k,x in oldids.items()if x['asset_id']in r['asset_ids']and x['start_min']!=newids[k]['start_min']}
                    if {x[ident]:x['start_shift_minutes']for x in obs[listkey]}!=expected:fail(case,'ACTUAL_NATIVE_TIME_METRICS')
            if len(requested)!=len(observed):fail(case,'STRENGTH_LENGTH')
            if len(requested)>1:counts['multiple_independent_controllers']+=1;counts['mixed_grade_cases']+=len({x['grade']for x in requested})>1
            for i,vec in enumerate(q['candidate_input_vectors']):
                if vec['device_grade_indices']!={k:(v+i)%4 for k,v in levels.items()}or vec['integrity_errors']:fail(case,'INPUT_VECTOR')
                counts['candidate_integrity_checks']+=1
            if q['actual_unique_dose_count']!=len({x['command_signature']for x in q['candidate_input_vectors']}):fail(case,'DISTINCT_COMMAND_COUNT')
            for e,ec in zip(p['VPP_events'],actual['events']):
                expected={};net=0.;n=(e['end_min']-e['start_min'])//10
                for aid in {t['asset_id']for t in p['A']['tasks']+p['B']['tasks']}:
                    values=[]
                    for plan in [p['A'],p['B']]:
                        total=0.
                        for t in range(e['start_min'],e['end_min'],10):
                            for task in plan['tasks']:
                                if task['asset_id']==aid and task['start_min']<=t<task['end_min']:
                                    par=assets[aid]['parameters'];total+=par.get(task['kind'],par)['power_kw']
                        values.append(total/n)
                    delta=values[1]-values[0];net+=delta
                    if abs(delta)>1e-8:expected['program',aid]=direction(delta)
                controls=collections.defaultdict(set)
                for (kind,aid,t),dr in direction_at.items():
                    if e['start_min']<=t<e['end_min']:controls[kind,aid].add(dr)
                for key,ds in controls.items():expected[key]=combined(ds)
                got={(x.get('control_kind','program'),x['asset_id']):x['direction']for x in ec['components']};relation=request_relation(combined(expected.values()),e['direction']);relations[relation]+=1
                if got!=expected or ec['component_request_relation']!=relation:fail(case,'EVENT_DIRECTION_CLASS')
                if abs(net*(1 if e['direction']=='up'else-1)-ec['known_program_response_reference_kw'])>1e-7:fail(case,'PROGRAM_POWER_REFERENCE')
                if any(ec[k]is not None for k in ['whole_physical_response_kw','whole_target_met','human_acceptance']):fail(case,'FABRICATED_OUTCOME')
                for reference in ec['EV_event_state_reference']['devices']:
                    aid=reference['asset_id'];values=[]
                    for plan in(p['A'],p['B']):
                        energy=0.
                        for x in plan['controls']:
                            if x['kind']!='ev_charge_window'or x['asset_id']!=aid:continue
                            for minute in range(e['start_min'],e['end_min'],10):
                                if x['start_min']<=minute<x['actual_charge_end_min']:
                                    energy+=assets[aid]['parameters']['charger_kw']/6*(x['last_step_power_fraction']if minute==x['actual_charge_end_min']-10 else 1)
                        values.append(energy)
                    delta=(values[1]-values[0])*60/(e['end_min']-e['start_min'])
                    if abs(delta-reference['power_delta_kw'])>1e-7 or reference['response_relation']!=request_relation(direction(delta),e['direction']):fail(case,'EV_EVENT_STATE_REFERENCE')
                    counts['EV_event_literal_relation_differs_from_power_reference']+=next((x['request_relation']for x in ec['components']if x.get('control_kind')=='ev_charge_window'and x['asset_id']==aid),'unchanged')!=reference['response_relation']
            item={'case_id':case,'household_id':p['household_id'],'date':p['date'],'path':rr['path'],'sha256':rr['sha256']};(changed if anychange else noops).append(item)
            pattern=tuple(sorted(actual['changed_device_families']));all_patterns[str(pattern)]+=1
            if anychange:changed_patterns[str(pattern)]+=1
            example_key=case if case in('ordinary-v6-0145__2025-07-08','ordinary-v6-0048__2025-04-02','ordinary-v6-0001__2025-03-22','ordinary-v6-0002__2025-05-15')else 'mixed_device_grades'if len(requested)>=3 and len({x['grade']for x in requested})>=3 else 'EV_constraint_stress'if any(x['device_family']=='ev'and any(m['B_window_slack_minutes']<0 for m in x['EV_window_metrics'])for x in observed)else None
            if example_key and example_key not in examples:
                examples[example_key]={'case_id':case,'path':rr['path'],'old_intent':old['classification']['design_intent'],'requested':requested,'actual':observed,'constraint_flags':failure['flags'],'event_classifications':actual['events']}
        if counts['cases']%1000==0:print({'reviewed_cases':counts['cases'],'errors':len(errors)},flush=True)
    return {'errors':errors, 'counts':counts, 'actualgrades':actualgrades, 'evstats':evstats, 'windowlengths':windowlengths, 'behaviors':behaviors, 'grades':grades, 'transitions':transitions, 'relations':relations, 'families':families, 'noops':noops, 'changed':changed, 'examples':examples, 'all_patterns':all_patterns, 'changed_patterns':changed_patterns, 'program_shifts':program_shifts}

def main():
    from concurrent.futures import ProcessPoolExecutor
    verify_inputs();sig=rules_id();b=read(OUT/'PAIR_BINDINGS10000.json')
    errors=[];counts=collections.Counter();actualgrades=collections.defaultdict(collections.Counter);evstats=collections.Counter();windowlengths=collections.Counter();behaviors=collections.Counter();grades=collections.defaultdict(collections.Counter);transitions=collections.Counter();relations=collections.Counter();families=collections.Counter();noops=[];changed=[];examples={};all_patterns=collections.Counter();changed_patterns=collections.Counter();program_shifts=collections.defaultdict(collections.Counter)
    def fail(case,code):errors.append([case,code])
    jobs=[b['records'][i:i+25]for i in range(0,len(b['records']),25)]
    with ProcessPoolExecutor(max_workers=4)as pool:
        for index,result in enumerate(pool.map(audit_rows,jobs),1):
            errors.extend(result['errors']);noops.extend(result['noops']);changed.extend(result['changed'])
            for name in ('counts','evstats','windowlengths','behaviors','transitions','relations','families','all_patterns','changed_patterns'):locals()[name].update(result[name])
            for name in ('actualgrades','grades','program_shifts'):
                for key,value in result[name].items():locals()[name][key].update(value)
            for key,value in result['examples'].items():examples.setdefault(key,value)
            if index%4==0:print({'reviewed_cases':counts['cases'],'errors':len(errors)},flush=True)
    if rules_id()!=sig or digest(read(OUT/'PAIR_BINDINGS10000.json'))!=digest(b):raise ValueError('RULES_CHANGED_DURING_REVIEW')
    subset=read(OUT/'SUBSET50.json');mainrows={r['household_id']:r for r in b['records']}
    if {r['household_id']for r in subset['records']}!={r['household_id']for r in read(SOURCE_B/'SUBSET50.json')['records']}or any(r!=mainrows[r['household_id']]for r in subset['records']):fail('subset','NOT_SAME_ROWS')
    if subset['type_counts']!={'A':5,'B':15,'C':16,'D':5,'E':4,'F':5}:fail('subset','RATIO')
    if {r['case_id']for r in noops}!={r['case_id']for r in read(SOURCE_B/'NO_COMMAND_CHANGE_CASES.json')['records']}:fail('all','FIXED100_IDS')
    if counts['cases']!=10000 or len(b['records'])!=1000 or counts['changed_commands']!=9900 or counts['identical_commands']!=100 or counts['same100_payload_preserved']!=100 or counts['candidate_integrity_checks']!=40000:fail('all','COUNTS')
    save(OUT/'NO_COMMAND_CHANGE_CASES.json',{'cases':100,'records':noops,'diagnostic_index_only':True,'retained_in_total_dataset':True,'preset_acceptance':None})
    save(OUT/'CHANGED_COMMAND_CASES.json',{'cases':9900,'records':changed,'diagnostic_index_only':True})
    report={'accepted':not errors,'rules_sha256':sig,'bindings_sha256':sha(OUT/'PAIR_BINDINGS10000.json'),'counts':dict(counts),'households':1000,'cases':10000,'source_A46_unchanged':True,'all10000_used_as_one_dataset':True,'subset50_type_counts':subset['type_counts'],'subset50_same_main_rows':True,'actual_grade_counts':{k:dict(v)for k,v in actualgrades.items()},'EV_failures_by_draft_grade':dict(evstats),'EV_actual_window_minutes':dict(windowlengths),'device_request_behavior_counts':dict(behaviors),'independent_native_grade_counts':{k:dict(v)for k,v in grades.items()},'constraint_transitions_B53_to_B55':dict(transitions),'event_request_relation_counts':dict(relations),'changed_device_family_counts':dict(families),'actual_program_shift_minutes':{k:dict(v)for k,v in program_shifts.items()},'portfolio_pattern_counts':dict(changed_patterns),'old_scalar_strength_active':False,'human_labels_generated':0,'physical_acceptance':False,'errors':errors,'scope':'native device requests,actual executable differences,event directions,given constraints;physical delivery and human acceptance pending'}
    save(OUT/'review/实际案例.json',examples);save(OUT/'ACCEPTANCE.json',report);print(canonical(report))
    if errors:raise SystemExit(2)

if __name__=='__main__':main()
