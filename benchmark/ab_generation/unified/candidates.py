"""Native finite request grammar and CP-SAT existential proposal witnesses.

The grammar is declared before admission. IPOG factors are mechanism/dose cells;
each cell retains ALL literal command alternatives, not two hash representatives.
The complete extension oracle searches those alternatives under engineering and
event-relevance constraints only. Service/consent stress never blocks a witness.
"""
import copy
import itertools
from collections import Counter,defaultdict
from ortools.sat.python import cp_model
from ..common import digest,canonical
from ..collection_candidates import _raw_programs,_raw_ev,_raw_thermal,_features,_slots,_profile
from ..collection_design import working_context,issues as legacy_issues,absolute_level
from ..collection_admission import engineering_issues as legacy_engineering_issues
from ..collection_relevance import asset_reasons
from .ev_request_relevance import explain,direct
from ..model import apply,control_issues
from ..generate import event_energy
from ..sampling import command_hash
from .contract import config,stream
from .input_boundaries import require_no_downstream_fields
from .ipog import generate,round_robin
from .semantics import program_window_issues
from .factorized import ProgramRecipe,prepare_template,export as export_native


def issues(c,patches,needs=()):
    checks,gates,power=legacy_issues(c,patches,needs)
    # The legacy replay module intentionally remains unchanged. Its same-date
    # assumption is not the continuous daily-window contract used by new A.
    checks=sorted((set(checks)-{'MACHINE_WINDOW_VIOLATED'}) |
                  program_window_issues(c,apply(c['A'],patches),needs))
    if not any('_unified_id' in r for r in c['A']['controls'] if r['kind']=='ev_charge_window'):return checks,gates,power
    # The legacy capacity screen stops at the last permitted A control. For a
    # CP schedule this is only the last scheduled charge, not the physical end.
    from ..power import site_capacity
    view={**c,'A':{**c['A'],'controls':[r for r in c['A']['controls'] if r['kind']!='ev_charge_window']}}
    for p in c.get('physical_ev_connections',[]):
        original=next((r for r in c['A']['controls'] if r['kind']=='ev_charge_window' and r['need_id']==p['need_id']),None)
        if original:view['A']['controls'].append({**original,'start_min':p['start_min'],'end_min':p['end_min']})
    corrected=site_capacity(view,apply(c['A'],patches))
    checks=sorted(set([x for x in checks if not x.startswith('SITE_')]+corrected['issues']))
    corrected['EV_basis']='explicit_scheduled_A_energy_and_literal_B_windows_inside_declared_physical_connection'
    return checks,gates,corrected


def engineering_issues(c,b,needs=(),reported=()):
    errors=legacy_engineering_issues(c,b,needs,reported)
    if 'INCOMPLETE_EV_CONNECTION' not in errors:return errors
    # A declared already-plugged initial state is evidence, not a new plug
    # operation. Only this explicit source origin can discharge a missing plug.
    invalid=False
    for row in b['controls']:
        if row['kind']!='ev_charge_window':continue
        ops=[o for o in b['operations'] if o['asset_id']==row['asset_id'] and o['need_id']==row['need_id']]
        plug=[o for o in ops if o['kind']=='EV_plug'];unplug=[o for o in ops if o['kind']=='EV_unplug']
        if len(plug)==len(unplug)==1:continue
        if row in c['A']['controls'] and (row['end_min']<=c['horizon_min'][0] or row['start_min']>=c['horizon_min'][1]):continue
        evidence=[p for p in c.get('physical_ev_connections',[]) if p['need_id']==row['need_id'] and p.get('origin')=='given_anchor_connection'
            and p['start_min']<=row['start_min']<row['end_min']<=p['end_min']]
        if not (not plug and len(unplug)==1 and evidence and evidence[0]['end_min']==unplug[0]['start_min']):invalid=True
    return errors if invalid else [e for e in errors if e!='INCOMPLETE_EV_CONNECTION']


def numeric_handling_slots(c,op,left,right):
    """Original time grid without the soft calendar/reservation admission gate.

    Qualification, past-operation immutability and service-chain engineering
    remain separate constraints. An unavailable operator is a proposal conflict,
    never evidence of consent or of a newly available helper.
    """
    length=op['end_min']-op['start_min']
    lo=((max(left,c['decision_min'])+9)//10)*10
    hi=min(right,c['horizon_min'][1]-length)//10*10
    return list(range(lo,hi+1,10))


def program_grammar(c,d,lc,handling_calendar_domain='convenience_only'):
    """Independent physical stages, full local load/retrieval Cartesian grid.

    Separately installed dryers are separate variables. An automatic combo
    remains one inseparable service. Source dependencies are restored on every
    literal task; the temporary adapter view only disables legacy chain shifting.
    """
    slots=numeric_handling_slots if handling_calendar_domain=='include_life_conflicts' else _slots
    view={**c,'A':{**c['A'],'tasks':[dict(t) for t in c['A']['tasks']]}}
    original={t['task_id']:t for t in c['A']['tasks']}
    for task in view['A']['tasks']:
        if task.get('depends_on_need_id'):task.pop('depends_on_need_id')
    # A future timer-controlled program can already be loaded at decision time.
    # Enumerate its machine choices, then keep every executed operation fixed.
    starts=[o['start_min'] for o in c['A']['operations'] if o['asset_id']==d['asset_id']]
    view['decision_min']=min([c['decision_min']]+starts)
    handled=set();needs={n['need_id']:n for n in c['needs']}
    for raw in _raw_programs(view,d,lc):
        raw=copy.deepcopy(raw)
        original_tasks=[original[t['task_id']] for p in raw['patches'] if p.get('collection')=='tasks' for t in p['rows']]
        if any(t['start_min']<c['decision_min'] for t in original_tasks):continue
        for patch in raw['patches']:
            if patch.get('collection')=='tasks':
                for t in patch['rows']:
                    if original[t['task_id']].get('depends_on_need_id'):
                        t['depends_on_need_id']=original[t['task_id']]['depends_on_need_id']
        parent_ids={t.get('depends_on_need_id') for p in raw['patches'] if p.get('collection')=='tasks' for t in p['rows']}-{None}
        raw['needs']=sorted(set(raw['needs'])|parent_ids)
        if raw['mechanism']!='retimed_handling':yield raw
        tasks=next(p['rows'] for p in raw['patches'] if p.get('collection')=='tasks')
        key=tuple((t['task_id'],t['start_min'],t['end_min']) for t in tasks)
        if key in handled:continue
        handled.add(key);nid=raw['service_need_id'];need=needs[nid]
        ops=[o for o in c['A']['operations'] if o['need_id']==nid]
        if len(ops)!=2 or {o['kind'] for o in ops}!={'load','unload'}:continue
        load=next(o for o in ops if o['kind']=='load');unload=next(o for o in ops if o['kind']=='unload')
        first=min(t['start_min'] for t in tasks);end=max(t['end_min'] for t in tasks)
        loads=slots(c,load,max(need['release_min'],first-(load['end_min']-load['start_min'])-need['maximum_preload_wait_min']),first-(load['end_min']-load['start_min']))
        if load['start_min']<c['decision_min']:
            loads=[load['start_min']] if load['end_min']<=first and load['start_min']>=need['release_min'] else []
        if not need['timer_allowed']:loads=[x for x in loads if x+load['end_min']-load['start_min']==first]
        unloads=slots(c,unload,end,min(need['deadline_min']-(unload['end_min']-unload['start_min']),end+need.get('maximum_retrieval_wait_min',180)))
        raw['_deadline']=need['deadline_min']
        permitted=[]
        for op,points in ((load,loads),(unload,unloads)):
            movable=(op['start_min']>=c['decision_min'] and op['operator_id'] not in c['authority']['immutable_operator_ids'] and
                     op['operator_id'] in c['authority']['assets'][op['asset_id']]['authorized_operator_ids'])
            permitted.append(points if movable else [t for t in points if t==op['start_min']])
        excluded=len(loads)*len(unloads)-len(permitted[0])*len(permitted[1])
        if excluded:
            yield dict(symbolic_exclusion=True,request_count=excluded,
                family=raw['family'],asset_id=raw['asset_id'],service_need_id=nid,
                issues=['HARD_OPERATION_PERMISSION_DOMAIN'],
                template=raw,load=load,unload=unload,all_loads=loads,all_unloads=unloads,
                allowed_loads=permitted[0],allowed_unloads=permitted[1],
                encoding='cartesian_minus_allowed_cartesian;lossless_expandable',
                repaired=False,replacement_generated=False)
        loads,unloads=permitted
        prepared=prepare_template(raw)
        for a,z in itertools.product(loads,unloads):
            yield ProgramRecipe(raw,load,unload,a,z,prepared)


def relevance(c,children,event):
    result=explain(c,children,event)
    if result['passed']:return result
    roots=[r for r in children if direct(c,r,event)]
    root_tasks={t['task_id']:t for r in roots for p in r['patches'] if p.get('collection')=='tasks' for t in p['rows']}
    before=apply(c['A'],[p for r in roots for p in r['patches']]);after=apply(c['A'],[p for r in children for p in r['patches']])
    def bad(plan,own):
        problems=set();tasks=plan['tasks'];ops=plan['operations']
        for t in tasks:
            if t['need_id'] not in own:continue
            parent=t.get('depends_on_need_id')
            if parent:
                unload=next((o for o in ops if o['need_id']==parent and o['kind']=='unload'),None)
                load=next((o for o in ops if o['need_id']==t['need_id'] and o['kind']=='load'),None)
                if unload and load and unload['end_min']>load['start_min']:problems.add(('material_transfer',parent,t['need_id']))
            for other in tasks:
                if other['task_id'] in root_tasks and other['asset_id']==t['asset_id'] and other['task_id']!=t['task_id'] and max(t['start_min'],other['start_min'])<min(t['end_min'],other['end_min']):
                    problems.add(('machine_occupancy',other['need_id'],t['need_id']))
        return problems
    for child in children:
        if child['id'] in result['components']:continue
        own={t['need_id'] for p in child['patches'] if p.get('collection')=='tasks' for t in p['rows']}
        introduced=bad(before,own)-bad(c['A'],own);resolved=introduced-bad(after,own)
        if resolved:
            result['components'][child['id']]=dict(role='necessary_service_or_machine_dependency',
                evidence=[dict(kind=k,root_need_id=p,support_need_id=s,absent_in_A=True,present_without_support=True,absent_with_support=True) for k,p,s in sorted(resolved)])
    result['unrelated_component_ids']=[r['id'] for r in children if r['id'] not in result['components']]
    result['passed']=not result['unrelated_component_ids'];return result


def prepare(context,cfg):
    if context['reference']['information_set']['mode']!='offline_unexecuted_A_plan':
        raise ValueError('UNIFIED_DEFAULT_FORBIDS_FUTURE_THERMAL_OBSERVATIONS')
    if context['reference'].get('thermal'):raise ValueError('UNDECLARED_FUTURE_A_STATE')
    if any(context.get(k) is not None for k in ('actual_outcomes','human_acceptance','human_score','human_reason')):
        raise ValueError('OUTCOME_OR_ANSWER_IN_GENERATOR_INPUT')
    # A display cutoff is not an EV departure or a service deadline. Extend the
    # planning view only using already supplied original endpoint evidence.
    view=copy.deepcopy(context);end=view['horizon_min'][1]
    active={t['need_id'] for t in context['A']['tasks'] if context['decision_min']<=t['start_min']<1440}
    for n in context['needs']:
        if n['need_id'] in active:end=max(end,n['deadline_min'])
    for row in context['A']['controls']:
        if row['kind']!='ev_charge_window' or row['start_min']>=1440 or row['end_min']<=context['decision_min']:continue
        endpoints=[o['start_min'] for o in context['A']['operations'] if o['kind']=='EV_unplug' and o['need_id']==row['need_id']]
        if endpoints:end=max(end,max(endpoints))
    view['horizon_min']=[context['horizon_min'][0],end]
    c=working_context(view);c['events']=[copy.deepcopy(cfg['event'])]
    c['reference']=copy.deepcopy(c['reference'])
    c['reference']['binding']={'A_commands_sha256':command_hash(context['A']),
        'context_sha256':digest({k:v for k,v in context.items() if k!='reference'}),'method':digest(cfg)}
    return c


def legacy_config(cfg):
    # Reuse literal command adapters, never the old selection/budget policy.
    from ..collection_design import DEFAULT
    c=copy.deepcopy(DEFAULT);c.update(seed=cfg['seed'],event=copy.deepcopy(cfg['event']),
        ac_axes=['cooling','heating'],
        ac_delta_C=[i/2 for i in range(1,round(max(cfg['ac_delta_C'])*2)+1)],
        tank_delta_C=list(range(1,round(max(cfg['tank_delta_C']))+1)),
        thermal_duration_min=cfg['thermal_duration_min'],ac_precondition_min=cfg['precondition_min'])
    return c


def ev_grammar(c,d,cfg):
    """Full resume grid; explicit CP schedules can recover within real plug spans.

    Moving a scheduled control row never moves plug/unplug or creates a charger.
    Failed pause-only requests remain available with their original energy need.
    """
    groups=defaultdict(list)
    for s in c['reference'].get('ev_charging_steps',[]):
        if s['start_min']>=c['decision_min'] and s['grid_kWh']>0:groups[s['need_id']].append(s)
    for nid,steps in sorted(groups.items()):
        if not any(s['start_min']<1440 for s in steps):continue
        controls=[r for r in c['A']['controls'] if r['asset_id']==d['asset_id'] and r['kind']=='ev_charge_window' and r['need_id']==nid]
        if not controls:continue
        explicit=all('_unified_id' in r for r in controls)
        physical=[r for r in c.get('physical_ev_connections',[]) if r['need_id']==nid]
        if explicit and not physical:continue
        end=max(r['end_min'] for r in physical) if explicit else c['_original_ev_connection_ends'][(d['asset_id'],nid)]
        end=min(end,c['horizon_min'][1]);anchor=min(s['start_min'] for s in steps);energy=sum(s['grid_kWh'] for s in steps)
        starts=[('ev_defer',anchor,z) for z in range(anchor+10,end,10)]
        starts.extend(('event_pause_and_recover',lo,hi) for lo in range(1080,1140,10) for hi in range(lo+10,1141,10))
        for mechanism,lo,hi in starts:
            if explicit:
                moving=sorted(controls,key=lambda r:r['start_min']);at=max(anchor,hi) if mechanism=='ev_defer' else anchor
                moved=[];after=[]
                for r,s in zip(moving,sorted(steps,key=lambda r:r['start_min'])):
                    while at<end and (lo<=at<hi or not any(p['start_min']<=at and at+10<=p['end_min'] for p in physical)):at+=10
                    if at+10>end:break
                    moved.append({**r,'start_min':at,'end_min':at+10})
                    after.append(dict(asset_id=d['asset_id'],start_min=at,end_min=at+10,power_kw=s['grid_kWh']*6));at+=10
                if len(moved)==len(moving):
                    patches=[dict(type='rows',collection='controls',identity='_unified_id',rows=moved)]
                    left=0
                else:
                    # Literal failed pause; do not invent recovery outside plug span.
                    patches=[dict(type='control_pause',asset_id=d['asset_id'],kind='ev_charge_window',need_id=nid,start_min=lo,end_min=hi)]
                    after=[dict(asset_id=d['asset_id'],start_min=s['start_min'],end_min=s['end_min'],power_kw=s['grid_kWh']*6) for s in steps if not lo<=s['start_min']<hi]
                    left=energy-sum(s['power_kw']/6 for s in after)
            else:
                left=energy;after=[]
                for t in range(max(anchor,hi) if mechanism=='ev_defer' else anchor,end,10):
                    if lo<=t<hi or not any(r['start_min']<=t and t+10<=r['end_min'] for r in controls):continue
                    amount=min(d['parameters']['charger_kw']/6,left)
                    if amount>1e-10:after.append(dict(asset_id=d['asset_id'],start_min=t,end_min=t+10,power_kw=amount*6));left-=amount
                patches=[dict(type='control_pause',asset_id=d['asset_id'],kind='ev_charge_window',need_id=nid,start_min=lo,end_min=hi)]
            yield dict(unit='ev:'+d['asset_id']+':'+nid,family='ev',asset_id=d['asset_id'],service_need_id=nid,
                mechanism=mechanism,branch='later' if mechanism=='ev_defer' else 'event_pause',needs=[],patches=patches,
                profiles={'A':[{**s,'asset_id':d['asset_id'],'power_kw':s['grid_kWh']*6} for s in steps],'B':after},
                extra_issues=['CHARGE_EXCEEDS_ORIGINAL_CONNECTION'] if left>1e-8 else [],
                magnitude=dict(dose_coordinate=hi-lo,pause_min=hi-lo,
                    **({'permission_pause_interval_min':[lo,hi]} if explicit else {}),
                    service_slack_min=end-max((s['end_min'] for s in after),default=hi),
                    energy_shortfall_kWh=max(0,left),required_A_grid_kWh=energy,manual_total_shift_min=0,manual_max_shift_min=0))


def heating_precondition(c,d,local):
    """Known occupied heating reference only; no invented heating-OFF sentinel."""
    lo=local['event']['start_min'];controls=[r for r in c['A']['controls'] if r['asset_id']==d['asset_id'] and r['kind']=='ac_setpoint']
    refs=[r for r in controls if r['start_min']<=lo<r['end_min'] and r['heating_setpoint_C']>5]
    if not refs:return
    reference=refs[0]['heating_setpoint_C']
    for delta,duration,lead,direction in itertools.product(local['ac_delta_C'],local['thermal_duration_min'],local['ac_precondition_min'],('aligned','opposing')):
        start=lo-lead;hi=lo+duration
        if start<c['decision_min'] or not all(any(r['start_min']<=t and t+10<=r['end_min'] for r in controls) for t in range(start,hi,10)):continue
        if not all(any(a<=t and t+10<=z for a,z in c['occupancy'].get(d['room_id'],[])) for t in range(lo,hi,10)):continue
        change=-delta if direction=='aligned' else delta
        patches=[dict(type='control_interval',asset_id=d['asset_id'],kind='ac_setpoint',start_min=start,end_min=lo,values={'heating_setpoint_C':reference-change})]
        patches.extend(dict(type='control_interval',asset_id=d['asset_id'],kind='ac_setpoint',start_min=max(lo,r['start_min']),end_min=min(hi,r['end_min']),values={'heating_setpoint_C':r['heating_setpoint_C']+change}) for r in controls if r['start_min']<hi and r['end_min']>lo)
        yield dict(unit='ac:'+d['asset_id']+':heating',family='ac',asset_id=d['asset_id'],mechanism='precondition_and_relax',branch='heating:'+direction,needs=[],patches=patches,profiles=None,
            magnitude=dict(dose_coordinate=delta,service_delta_C=delta,duration_min=duration,precondition_min=lead,axis='heating',direction=direction,
                actual_max_command_delta_C=max(abs(p['values']['heating_setpoint_C']-r['heating_setpoint_C']) for p in patches for r in controls if p['start_min']<r['end_min'] and p['end_min']>r['start_min']),
                manual_total_shift_min=0,manual_max_shift_min=0))


def heating_description(c,raw):
    # Cooling's 40C fallback says nothing about heating availability. Keep axes
    # independent instead of suppressing heating delta when cooling is stopped.
    before=[r for r in c['A']['controls'] if r['asset_id']==raw['asset_id'] and r['kind']=='ac_setpoint'];phases=[]
    for p in raw['patches']:
        for a in before:
            lo=max(p['start_min'],a['start_min']);hi=min(p['end_min'],a['end_min'])
            if lo<hi:phases.append(dict(start_min=lo,end_min=hi,A_heating_setpoint_C=a['heating_setpoint_C'],B_heating_setpoint_C=p['values']['heating_setpoint_C'],same_time_setpoint_delta_C=p['values']['heating_setpoint_C']-a['heating_setpoint_C']))
    return dict(schema='eb.heating_intervention.v1',axis='heating',phases=phases,
        state_change='unchanged',preconditioning_min=raw['magnitude'].get('precondition_min',0),
        cooling_stop_requested_min=0,additional_thermostat_enabled_min=0,
        amplitude_axes={'temperature_offset':'small' if raw['magnitude']['service_delta_C']<=.5 else 'medium' if raw['magnitude']['service_delta_C']<=1 else 'large',
            'preconditioning':'none' if not raw['magnitude'].get('precondition_min') else 'record_raw_minutes',
            'event_duration':'record_raw_minutes'},
        state='heating_threshold_request;availability_and_actual_runtime_unknown',
        native_availability_off_claimed=False,cooling_fallback_is_not_heating_state=True,
        actual_compressor_runtime_min=None,actual_room_temperature_C=None,response_kWh=None)


def coupled_precondition(c,raw,local):
    """Construct the nearest companion bound satisfying the original deadband.

    This is a separate native operator, not a repair after outcome evaluation.
    Single-axis requests remain in the diagnostic grammar. Each companion change
    has the algebraic withdrawal witness: restoring it violates the deadband.
    """
    if raw['family']!='ac' or raw['mechanism']!='precondition_and_relax':return None
    axis=raw['magnitude']['axis'];controls=[r for r in c['A']['controls'] if r['asset_id']==raw['asset_id'] and r['kind']=='ac_setpoint']
    patches=[];changes=[]
    for patch in raw['patches']:
        for a in controls:
            lo=max(patch['start_min'],a['start_min']);hi=min(patch['end_min'],a['end_min'])
            if lo>=hi:continue
            values=dict(patch['values']);heat=values.get('heating_setpoint_C',a['heating_setpoint_C']);cool=values.get('cooling_setpoint_C',a['cooling_setpoint_C'])
            gap=a.get('heating_and_cooling_deadband_C',0)
            if axis=='cooling' and heat>cool-gap:
                values['heating_setpoint_C']=cool-gap
                changes.append(dict(start_min=lo,end_min=hi,field='heating_setpoint_C',A=a['heating_setpoint_C'],B=cool-gap,
                    required_deadband_C=gap,without_companion_gap_C=cool-heat,reason='necessary_original_deadband_companion'))
            elif axis=='heating' and cool<heat+gap:
                values['cooling_setpoint_C']=heat+gap
                if 'value_C' in a:values['value_C']=heat+gap
                changes.append(dict(start_min=lo,end_min=hi,field='cooling_setpoint_C',A=a['cooling_setpoint_C'],B=heat+gap,
                    required_deadband_C=gap,without_companion_gap_C=cool-heat,reason='necessary_original_deadband_companion'))
            patches.append({**patch,'start_min':lo,'end_min':hi,'values':values})
    if not changes:return None
    item=copy.deepcopy(raw);item['patches']=patches
    item['magnitude'].update(coupled_thermostat_axes=True,companion_setpoint_changes=changes,
        max_companion_delta_C=max(abs(r['B']-r['A']) for r in changes),
        construction_operator='minimal_companion_projection_onto_original_deadband',
        companion_is_not_pre_authorized=True)
    if axis=='heating':item['magnitude']['ac_intervention']=heating_description(c,item)
    else:
        from ..collection_thermal import describe
        item['magnitude']['ac_intervention']=describe(c,raw['asset_id'],patches,axis,local['event'],local['ac_delta_C'])
    return item


def raw_grammar(c,cfg):
    lc=legacy_config(cfg)
    for d in sorted(c['devices'],key=lambda d:d['asset_id']):
        kinds=set(d['types'])
        if kinds&{'washer','dryer','dishwasher'}:yield from program_grammar(c,d,lc,cfg.get('handling_calendar_domain','convenience_only'))
        elif 'ev' in kinds:
            yield from ev_grammar(c,d,cfg)
        elif kinds&{'ac','water_heater'}:
            # All event start-grid points and complete 10-minute duration grid.
            for lo in range(1080,1140,10):
                local=copy.deepcopy(lc);local['event']['start_min']=lo
                local['thermal_duration_min']=[x for x in cfg['thermal_duration_min'] if lo+x<=1140]
                raws=itertools.chain(_raw_thermal(c,d,local),heating_precondition(c,d,local) if 'ac' in kinds else ())
                for raw in raws:
                    # value_C is a legacy cooling alias, never another state.
                    if raw['family']=='ac':
                        for p in raw['patches']:
                            values=p.get('values',{})
                            if 'cooling_setpoint_C' in values and any('value_C' in r for r in c['A']['controls'] if r['asset_id']==d['asset_id'] and r['kind']=='ac_setpoint'):
                                values['value_C']=values['cooling_setpoint_C']
                    if raw['magnitude'].get('axis')=='heating':raw['magnitude']['ac_intervention']=heating_description(c,raw)
                    yield raw
                    paired=coupled_precondition(c,raw,local)
                    if paired:yield paired


def catalogue_domains(c,cfg):
    units=defaultdict(dict);raw_count=0;unmodified=0;diagnostics=[];gaps=[];supports=[]
    indexed={k:{r[idkey]:r for r in c['A'][k]} for k,idkey in [('tasks','task_id'),('operations','operation_id')]}
    def changes(raw):
        for p in raw['patches']:
            if p['type']=='rows':
                originals=indexed.get(p['collection']) or {r[p['identity']]:r for r in c['A'][p['collection']]}
                if any(r!=originals.get(r[p['identity']]) for r in p['rows']):return True
            else:
                for r in c['A']['controls']:
                    if r['asset_id']!=p['asset_id'] or r['kind']!=p['kind'] or r['start_min']>=p['end_min'] or r['end_min']<=p['start_min']:continue
                    if p['type']=='control_pause' and r.get('need_id')==p['need_id']:return True
                    if p['type']=='control_interval' and any(r.get(k)!=v for k,v in p['values'].items()):return True
        return False
    for raw in raw_grammar(c,cfg):
        if raw.get('symbolic_exclusion'):
            raw_count+=raw['request_count'];diagnostics.append(raw);continue
        raw_count+=1
        if not changes(raw):unmodified+=1;continue
        if raw['family'] in ('washer','dryer','dishwasher'):
            raw['construction_mechanism']=raw['mechanism']
            ops=next(p['rows'] for p in raw['patches'] if p.get('collection')=='operations')
            shifts=[o['start_min']-indexed['operations'][o['operation_id']]['start_min'] for o in ops]
            delta=raw['magnitude'].get('signed_machine_shift_min',0)
            raw['mechanism']='timer_only' if not any(shifts) else 'shift_chain' if all(x==delta for x in shifts) else 'retimed_handling_full_grid' if isinstance(raw,ProgramRecipe) else 'retimed_handling'
        # Both thermal axes on an asset are alternatives in the same factor;
        # this prevents double counting a single AC as two independent devices.
        key=(raw['asset_id'],raw.get('service_need_id')) if raw['family'] in ('washer','dryer','dishwasher','ev') else (raw['asset_id'],None)
        raw['unit']=canonical(key);raw['id']=digest(raw['patches'])
        hard=[]
        for p in raw['patches']:
            if p.get('collection')=='tasks' and any(t['start_min']<c['decision_min'] for t in p['rows']):hard.append('PROPOSED_PROGRAM_BEFORE_DECISION')
        for p in raw['patches']:
            if p.get('collection')!='operations':continue
            for op in p['rows']:
                if op==indexed['operations'].get(op['operation_id']):continue
                if op['start_min']<c['decision_min'] or indexed['operations'][op['operation_id']]['start_min']<c['decision_min']:hard.append('EXECUTED_OR_PAST_OPERATION_CHANGED')
                if op['operator_id'] in c['authority']['immutable_operator_ids']:hard.append('CONTEXT_OPERATOR_IMMUTABLE')
                if op['operator_id'] not in c['authority']['assets'][op['asset_id']]['authorized_operator_ids']:hard.append('OPERATOR_NOT_AUTHORIZED_FOR_ASSET')
        if hard:
            diagnostics.append(dict(request_sha256=raw['id'],issues=sorted(set(hard)),request=raw,
                rejection_stage='native_hard_permission_domain',repaired=False,replacement_generated=False));continue
        if raw.get('construction_issues'):
            diagnostics.append(dict(request_sha256=raw['id'],issues=raw['construction_issues'],request=raw,
                                    repaired=False,replacement_generated=False));continue
        if raw.get('outside_case_horizon'):
            gaps.append(dict(asset_id=raw['asset_id'],reason='EVIDENCE_TAIL_MISSING;NOT_DEPARTURE_FAILURE',request_sha256=raw['id']));continue
        if raw['family'] in ('ac','water_heater'):
            raw['_intrinsic_issues']=control_issues(c,apply(c['A'],raw['patches']))
            if raw['_intrinsic_issues']:
                diagnostics.append(dict(request_sha256=raw['id'],issues=raw['_intrinsic_issues'],request=raw,repaired=False,replacement_generated=False))
        if not direct(c,raw,cfg['event']):
            supports.append(raw);continue  # Not an independent event opportunity.
        units[key].setdefault(raw['id'],raw)
    root_assets={key[0] for key in units};root_need_ids={r['service_need_id'] for pool in units.values() for r in pool.values() if r.get('service_need_id')}
    retained_supports=[]
    for raw in supports:
        parent_ids={t.get('depends_on_need_id') for p in raw['patches'] if p.get('collection')=='tasks' for t in p['rows']}-{None}
        if raw['asset_id'] in root_assets or parent_ids&root_need_ids:
            units[(raw['asset_id'],raw.get('service_need_id'))].setdefault(raw['id'],raw)
        else:retained_supports.append(raw)
    supports=retained_supports
    values=[];descriptors=[];factor_domains=[]
    for key,pool in sorted(units.items(),key=lambda x:digest([cfg['seed'],'factor-order',c['household_id'],c['date'],x[0]])):
        group=list(pool.values());coordinates=defaultdict(set)
        for r in group:coordinates[(r['mechanism'],r['branch'])].add(r['magnitude']['dose_coordinate'])
        cells=defaultdict(list)
        for r in group:
            xs=sorted(coordinates[(r['mechanism'],r['branch'])]);x=r['magnitude']['dose_coordinate']
            # Actual raw units remain authoritative; this is only within-domain
            # position, never a claim of low/high lived impact or energy response.
            q=xs.index(x)/max(1,len(xs)-1)
            label='single_available_value' if len(xs)==1 else 'small_relative' if q<=cfg['relative_cuts'][0] else 'medium_relative' if q<=cfg['relative_cuts'][1] else 'large_relative'
            r['relative_level']=label;r['absolute_level']=absolute_level(r)
            if cfg['method_revision']=='delivery_v2_11':
                from .change_axes import annotate
                annotate(c,r,cfg['event'])
            prof=r['profiles'];known=0 if prof is None else event_energy(prof['A'],cfg['event'])-event_energy(prof['B'],cfg['event'])
            r['known_event_reduction_kWh']=known;r['unknown_thermal_response']=prof is None
            r['dose_origin']='conditional_native_grid_position;experimental_cutpoints;not_discomfort'
            if cfg['method_revision']=='delivery_v2_11':
                from .change_axes import labels
                label=labels(r['change_axes'])
            cell=canonical([r['mechanism'],r['branch'],label,
                'manual_changed' if r['magnitude'].get('manual_total_shift_min') else 'manual_unchanged',
                'event_root' if direct(c,r,cfg['event']) else 'support_requires_witness'])
            cells[cell].append(r)
        descriptor=[{'label':'no_change','ids':[0]}];flat=[None]
        for label,rs in sorted(cells.items(),key=lambda item:digest([cfg['seed'],'cell-order',c['household_id'],c['date'],item[0]])):
            ids=[]
            for r in sorted(rs,key=lambda r:digest([cfg['seed'],'native-order',c['household_id'],c['date'],r['id']])):ids.append(len(flat));flat.append(r)
            descriptor.append(dict(label=label,ids=ids))
        values.append(flat);descriptors.append(descriptor);factor_domains.append(list(range(len(descriptor))))
    return dict(values=values,descriptors=descriptors,domains=factor_domains,
        engineering_diagnostics=diagnostics,gaps=gaps,raw_count=raw_count,unmodified=unmodified,
        support_domain=supports,
        scope='complete_enumerated_native_grammar;full_local_load_retrieval_grid;separate_dryer_variable;not_all_physical_control_laws')


def request(c,children,cfg,portrait=None):
    lc=legacy_config(cfg);patches=[p for r in children for p in r['patches']];needids=sorted({n for r in children for n in r['needs']})
    checks,gates,power=issues(c,patches,needids)
    pending=bool('TARGET_CONTROL_NOT_AUTHORIZED' in gates)
    immutable=[g for g in gates if g!='TARGET_CONTROL_NOT_AUTHORIZED']
    if immutable:return dict(engineering_diagnostic=True,issues=immutable,request_sha256=digest(patches),patches=patches)
    checks=sorted(set([i for i in checks if i!='TARGET_CONTROL_NOT_AUTHORIZED']+[i for r in children for i in r.get('extra_issues',[])]))
    identities=[(p['collection'],r[p['identity']]) for p in patches if p['type']=='rows' for r in p['rows']]
    if len(identities)!=len(set(identities)):checks.append('OVERLAPPING_PATCH_IDENTITIES')
    b=apply(c['A'],patches);eng=engineering_issues(c,b,needids,checks)
    if eng:return dict(engineering_diagnostic=True,issues=eng,request_sha256=digest(patches),patches=patches)
    relevant=relevance(c,children,cfg['event'])
    if not relevant['passed']:return dict(relevance_diagnostic=True,relevance=relevant,request_sha256=digest(patches),patches=patches)
    changed=set()
    for r in children:
        for p in r['patches']:
            if p['type']=='rows':
                original={x[p['identity']]:x for x in c['A'][p['collection']]}
                changed.update(x['asset_id'] for x in p['rows'] if x!=original[x[p['identity']]])
            else:changed.add(p['asset_id'])
    components=[{**{k:copy.deepcopy(r[k]) for k in ('id','unit','family','asset_id','mechanism','relative_level','absolute_level','magnitude','patches')},
        'service_need_id':r.get('service_need_id'),'event_relevance':relevant['components'][r['id']]} for r in children]
    if cfg['method_revision']=='delivery_v2_11':
        from .change_axes import annotate
        for component,child in zip(components,children):
            if 'legacy_axis_metadata' in child:component['legacy_axis_metadata']=copy.deepcopy(child['legacy_axis_metadata'])
            if 'construction_operator' in child:component['construction_operator']=child['construction_operator']
            annotate(c,component,cfg['event'])
    preferences={d['asset_id']:d for d in (portrait or {}).get('joint_sampling',{}).get('devices',[])}
    authorizations={d['asset_id']:d.get('authorization',{}) for d in (portrait or {}).get('devices',[])}
    judgment=[]
    for r in children:
        aid=r['asset_id'];pr=preferences.get(aid,{});auth=authorizations.get(aid,{})
        bound=pr.get('original_reschedule_bound_min');shift=r['magnitude'].get('machine_shift_min',r['magnitude'].get('pause_min',0))
        exceeds=bound is not None and shift>bound
        axis=r['magnitude'].get('axis');m=r['magnitude'];why=[]
        if exceeds:why.append('OUTSIDE_ORIGINAL_NUMERIC_RESCHEDULE_SCOPE')
        if auth.get('mode') in ('confirm_each_proposal','same_day_confirmation'):why.append('HOUSEHOLD_CONFIRMATION_REQUIRED')
        if axis=='heating' and auth.get('bounds',{}).get('heating_change_numeric_bound') is None:why.append('HEATING_SCOPE_NOT_DECLARED')
        if r['family']=='ac' and m.get('ac_intervention',{}).get('cooling_stop_requested_min') and pr.get('off_authorization') is not True:why.append('STOP_CONTROL_REQUIRES_CONFIRMATION')
        if cfg['method_revision']=='delivery_v2_11':
            if m.get('pre_event_preparation_min',0):why.append('PRE_EVENT_PREPARATION_REQUIRES_CONFIRMATION')
            if m.get('in_event_preparation_min',0):why.append('IN_EVENT_PREPARATION_REQUIRES_CONFIRMATION')
        elif m.get('precondition_min',0):why.append('PRECONDITIONING_EXECUTION_CONSENT_NOT_OBTAINED')
        if m.get('coupled_thermostat_axes'):why.append('COMPANION_SETPOINT_CHANGE_REQUIRES_CONFIRMATION')
        if why:pending=True
        machine_tension=bool(pr.get('preferred_shift_limit_min') is not None and shift>pr['preferred_shift_limit_min'])
        handling_tension=bool(pr.get('handling_change_sensitive') and m.get('manual_total_shift_min'))
        members=pr.get('member_device_preferences',{})
        opinions=[{k:v for k,v in opinion.items() if k in ('routine_sensitive','handling_change_sensitive','comfort_sensitive','confirmation_preferred','cooling_preferred_C','preferred_shift_limit_min')}
                  for opinion in members.values()]
        judgment.append(dict(asset_id=aid,reference_member=pr.get('shared_preference_resolution',{}).get('default_owner_member_id'),
            actual_proposed_operator_ids=sorted({o['operator_id'] for p in r['patches'] if p.get('collection')=='operations' for o in p['rows']}),
            confirmation_holder=auth.get('holder_member_id'),member_preferences=pr.get('member_device_preferences',{}),
            original_reschedule_bound_min=bound,exceeds_original_numeric_scope=exceeds,
            soft_preference_tension=machine_tension or handling_tension,machine_time_tension=machine_tension,handling_tension=handling_tension,
            member_opinions_differ=len({canonical(o) for o in opinions})>1,confirmation_reasons=why,
            explicit_consent_obtained=False,authorization_preference=auth.get('mode','unknown'),
            actual_authority_expanded=False))
    row=dict(household_id=c['household_id'],date=c['date'],case_id=c['case_id'],patches=patches,
        component_ids=[r['id'] for r in children],components=components,program_needs=needids,
        event_relevance=relevant,asset_change_reasons=asset_reasons(c,children,relevant),issues=checks,
        changed_assets=sorted(changed),independent_units=len(children),features=_features(children,checks,changed),
        known_event_reduction_kWh=sum(r['known_event_reduction_kWh'] for r in children),
        unknown_thermal_response=any(r['unknown_thermal_response'] for r in children),power_status=power['status'],
        actual_outcomes=None,human_acceptance=None,human_score=None,human_reason=None,actual_results_used_for_selection=False,
        engineering_issues=[],judgment_context=judgment,consent_status='new_confirmation_required' if pending else 'proposal_only;execution_consent_not_obtained',
        working_B_sha256=command_hash(b),A_commands_sha256=command_hash(c['A']),
        portrait_sha256=digest(portrait),physical_status='not_computed')
    for child in children:
        changes=child['magnitude'].get('companion_setpoint_changes')
        if changes:row['asset_change_reasons'][child['asset_id']].append(dict(role='necessary_original_deadband_companion',
            evidence=changes,execution_consent_obtained=False))
    if cfg['method_revision']=='delivery_v2_11':
        from .change_axes import refresh_row_features
        refresh_row_features(row)
    if cfg['method_revision'] in ('delivery_v2_9','delivery_v2_10','delivery_v2_11'):
        from .semantics import LINK_VERSION,linked_contexts
        row['judgment_context_version']=LINK_VERSION
        for component,judgment in zip(components,row['judgment_context']):
            judgment.update(component_id=component['id'],service_need_id=component.get('service_need_id'))
        linked_contexts(row)
    row['id']=digest([c['reference']['binding'],row['working_B_sha256'],row['portrait_sha256']])
    return row


class Oracle:
    """Existential CP-SAT completion, with engineering no-goods and full ledger."""
    def __init__(self,c,grammar,cfg,portrait):
        self.c=c;self.g=grammar;self.cfg=cfg;self.portrait=portrait;self.model=cp_model.CpModel()
        self.x=[self.model.new_int_var(0,len(v)-1,'native:'+str(i)) for i,v in enumerate(grammar['values'])]
        self.rows={};self.diagnostics=[];self.cache={};self.calls=0;self.materializations=0;self.witnesses=[]
        # No event-free arbitrary filler; supports need an actual root witness.
        roots=[];self.root_indices={};self.propagation_log=[];self.forward_search_log=[]
        self.valid_indices={i:tuple(j for j,r in enumerate(vals) if not r or not r.get('_intrinsic_issues'))
                            for i,vals in enumerate(grammar['values'])}
        for i,vals in enumerate(grammar['values']):
            for j,r in enumerate(vals):
                if r and r.get('_intrinsic_issues'):self.model.add(self.x[i]!=j)
            inds=[j for j,r in enumerate(vals) if r and direct(c,r,cfg['event'])]
            self.root_indices[i]=set(inds)
            b=self.model.new_bool_var('event_root:'+str(i));roots.append(b)
            if inds:
                self.model.add_linear_expression_in_domain(self.x[i],cp_model.Domain.from_values(inds)).only_enforce_if(b)
                self.model.add_linear_expression_in_domain(self.x[i],cp_model.Domain.from_values([j for j in range(len(vals)) if j not in self.root_indices[i]])).only_enforce_if(b.Not())
            else:self.model.add(b==0)
        self.model.add(sum(roots)>=1)
        # Propagate physical occupancy and wash->dry transfer before literal
        # materialization. Human/calendar/service conflicts remain soft cases.
        chains={};holds=defaultdict(list);self.hold_rows={};self.fixed_holds=[];self.parents={}
        encode_physical=sum(len(v) for v in grammar['values'])<=cfg['oracle_native_encoding_budget']
        for i,values in enumerate(grammar['values']):
            first=values[1]
            if first['family'] not in ('washer','dryer','dishwasher'):continue
            nid=first['service_need_id'];aid=first['asset_id'];table=[]
            for j,r in enumerate(values):
                if isinstance(r,ProgramRecipe):
                    table.append([j,*r.hold()]);continue
                ops=c['A']['operations'] if r is None else next(p['rows'] for p in r['patches'] if p.get('collection')=='operations')
                load=next((o for o in ops if o['need_id']==nid and o['kind']=='load'),None)
                unload=next((o for o in ops if o['need_id']==nid and o['kind']=='unload'),None)
                if load and unload:table.append([j,load['start_min'],unload['end_min'],load['end_min']])
            if len(table)!=len(values):continue
            self.hold_rows[i]=dict(asset_id=aid,need_id=nid,values=table)
            if not encode_physical:continue
            variables=[]
            for k in range(1,4):variables.append(self.model.new_int_var(min(r[k] for r in table),max(r[k] for r in table),'chain:'+nid+':'+str(k)))
            self.model.add_allowed_assignments([self.x[i]]+variables,table)
            load,unload_end,load_end=variables;size=self.model.new_int_var(1,max(r[2]-r[1] for r in table),'hold:'+nid)
            self.model.add(size==unload_end-load)
            holds[aid].append(self.model.new_interval_var(load,size,unload_end,'machine:'+nid))
            chains[nid]=(load,unload_end,load_end)
        modeled={r['need_id'] for r in self.hold_rows.values()}
        for t in c['A']['tasks']:
            nid=t['need_id'];parent=t.get('depends_on_need_id')
            if parent and nid in modeled:self.parents[nid]=parent
            if parent and nid in chains:
                if parent in chains:self.model.add(chains[nid][0]>=chains[parent][1])
                else:
                    op=next((o for o in c['A']['operations'] if o['need_id']==parent and o['kind']=='unload'),None)
                    if op:self.model.add(chains[nid][0]>=op['end_min'])
        for aid in sorted({r['asset_id'] for r in self.hold_rows.values()}):
            intervals=holds.get(aid,[])
            for load in c['A']['operations']:
                if load['kind']!='load' or load['asset_id']!=aid or load['need_id'] in modeled:continue
                unload=next((o for o in c['A']['operations'] if o['need_id']==load['need_id'] and o['kind']=='unload'),None)
                if unload:
                    if encode_physical:intervals.append(self.model.new_fixed_size_interval_var(load['start_min'],unload['end_min']-load['start_min'],'unchanged:'+load['need_id']))
                    self.fixed_holds.append((aid,load['start_min'],unload['end_min'],load['need_id']))
            if intervals:self.model.add_no_overlap(intervals)
    def physical_compatible(self,native):
        intervals=list(self.fixed_holds);times={}
        for i,hold in self.hold_rows.items():
            _,load,end,_=hold['values'][native[i]];intervals.append((hold['asset_id'],load,end,hold['need_id']));times[hold['need_id']]=(load,end)
        for i,(aid,a,z,nid) in enumerate(intervals):
            for bid,b,y,other in intervals[i+1:]:
                if aid==bid and max(a,b)<min(z,y):return False
        for nid,parent in self.parents.items():
            end=times[parent][1] if parent in times else next((o['end_min'] for o in self.c['A']['operations'] if o['need_id']==parent and o['kind']=='unload'),None)
            if end is not None and times[nid][0]<end:return False
        return True
    def remember(self,native,row):
        self.rows.setdefault(row['id'],row)
        cells=[next(k for k,d in enumerate(self.g['descriptors'][i]) if v in d['ids']) for i,v in enumerate(native)]
        self.witnesses.append((list(native),cells,row['id']))
        return ('feasible',cells,row['id'])
    def __call__(self,partial,order=None,native_required=None):
        native_required=native_required or {}
        key=(tuple(sorted(partial.items())),order,tuple((i,tuple(v)) for i,v in sorted(native_required.items())))
        if key in self.cache:return self.cache[key]
        for native,cells,rid in self.witnesses:
            if all(cells[i]==v for i,v in partial.items()) and all(native[i] in ids for i,ids in native_required.items()) and (order is None or sum(v!=0 for v in native)==order):
                return ('feasible',cells,rid)
        if self.materializations>=self.cfg['rows_per_unit']*max(1,len(self.x)):
            return ('unknown',None,'materialized_request_budget')
        query_start=self.materializations
        # The query budget is checked here too, including lazy no-good re-solves.
        limit=self.cfg['queries_per_row']*self.cfg['rows_per_unit']*max(1,len(self.x))
        allowed={}
        for i,values in enumerate(self.g['values']):
            if i not in partial and i not in native_required:
                allowed[i]=self.valid_indices[i];continue
            cell=self.g['descriptors'][i][partial[i]]['ids'] if i in partial else None
            ids=sorted(set(native_required[i]).intersection(cell)) if cell is not None and i in native_required else sorted(set(native_required[i] if i in native_required else cell))
            allowed[i]=[j for j in ids if 0<=j<len(values) and (j==0 or not values[j].get('_intrinsic_issues'))]
        if self.cfg.get('oracle_propagation') in ('interval_v1','interval_forward_v1'):
            from .interval_propagation import propagate
            allowed,proof=propagate(allowed,self.hold_rows,self.fixed_holds,self.parents,
                                    self.c['A']['operations'],self.root_indices,order)
            self.propagation_log.append(dict(partial=partial,order=order,native_required_counts={i:len(ids) for i,ids in native_required.items()},**proof))
            if proof['empty']:
                answer=('infeasible',None,proof['reason']);self.cache[key]=answer;return answer
        elif any(not ids for ids in allowed.values()):
            answer=('infeasible',None,'empty_native_query_domain');self.cache[key]=answer;return answer
        if order is not None:
            atoms={}
            for native,_,_ in self.witnesses:
                active=[(i,v) for i,v in enumerate(native) if v]
                if len(active)==1:atoms.setdefault(*active[0])
            for subset in itertools.islice(itertools.combinations(sorted(atoms),order),self.cfg['queries_per_row']*16):
                native=[atoms[i] if i in subset else 0 for i in range(len(self.x))]
                if any(v not in allowed[i] for i,v in enumerate(native)):continue
                if not self.physical_compatible(native):continue
                if self.calls>=limit or self.materializations>=self.cfg['rows_per_unit']*max(1,len(self.x)) or self.materializations-query_start>=self.cfg['queries_per_row']:break
                self.calls+=1;self.materializations+=1
                row=request(self.c,[self.g['values'][i][v] for i,v in enumerate(native) if v],self.cfg,self.portrait)
                if not row.get('engineering_diagnostic') and not row.get('relevance_diagnostic'):
                    answer=self.remember(native,row);self.cache[key]=answer;return answer
                self.diagnostics.append({**row,'search_scope':'joint_order_constraint_attempt;not_outcome_reroll'})
        # Cheap complete witnesses precede a full existential proof query.
        # This is NOT a smaller candidate universe: failure here is never an
        # infeasibility claim. All native alternatives remain in the CP model.
        # No outcome, service-success or acceptance label orders these attempts.
        if self.cfg.get('oracle_propagation')=='interval_forward_v1':
            from .interval_search import assignments
            stats={}
            self.forward_search_log.append(dict(partial=partial,order=order,stats=stats))
            for native in assignments(allowed,self.hold_rows,self.fixed_holds,self.parents,
                    self.c['A']['operations'],self.root_indices,order,
                    self.cfg['oracle_forward_node_budget'],stats):
                if self.calls>=limit or self.materializations>=self.cfg['rows_per_unit']*max(1,len(self.x)) or self.materializations-query_start>=self.cfg['queries_per_row']:break
                if not self.physical_compatible(native):continue
                self.calls+=1;self.materializations+=1
                row=request(self.c,[self.g['values'][i][v] for i,v in enumerate(native) if v],self.cfg,self.portrait)
                if row.get('engineering_diagnostic') or row.get('relevance_diagnostic'):
                    row.update(repaired=False,replacement_generated=False,search_scope='bounded_forward_constraint_search;not_outcome_reroll')
                    self.diagnostics.append(row);self.model.add_forbidden_assignments(self.x,[native]);continue
                answer=self.remember(native,row);self.cache[key]=answer;return answer
        elif partial or native_required:
            pools=[]
            for i,values in enumerate(self.g['values']):
                ids=allowed[i] if i in partial or i in native_required or 0 not in allowed[i] else [0]
                pools.append([j for j in ids if j==0 or not values[j].get('_intrinsic_issues')])
            if any(not p for p in pools):
                answer=('infeasible',None,'all_native_values_violate_intrinsic_hard_control_constraints');self.cache[key]=answer;return answer
            # Fast finite scan only propagates the same engineering relations;
            # its cutoff cannot certify an empty conditional opportunity.
            for native in itertools.islice(itertools.product(*pools),self.cfg['queries_per_row']*256):
                if order is not None and sum(v!=0 for v in native)!=order:continue
                if self.calls>=limit or self.materializations>=self.cfg['rows_per_unit']*max(1,len(self.x)) or self.materializations-query_start>=self.cfg['queries_per_row']:break
                if not self.physical_compatible(native):continue
                if not any(v and direct(self.c,self.g['values'][i][v],self.cfg['event']) for i,v in enumerate(native)):continue
                self.calls+=1;self.materializations+=1;children=[self.g['values'][i][v] for i,v in enumerate(native) if v]
                row=request(self.c,children,self.cfg,self.portrait)
                if row.get('engineering_diagnostic') or row.get('relevance_diagnostic'):
                    row.update(repaired=False,replacement_generated=False,search_scope='bounded_complete_witness_attempt;not_outcome_reroll')
                    self.diagnostics.append(row);self.model.add_forbidden_assignments(self.x,[native]);continue
                answer=self.remember(native,row);self.cache[key]=answer;return answer
        while self.calls<limit:
            if self.materializations>=self.cfg['rows_per_unit']*max(1,len(self.x)):return ('unknown',None,'materialized_request_budget')
            if self.materializations-query_start>=self.cfg['queries_per_row']:return ('unknown',None,'per_extension_effort_budget;other_factors_not_starved')
            if sum(len(v) for v in allowed.values())>self.cfg['oracle_native_encoding_budget']:
                return ('unknown',None,'native_encoding_budget;full_domain_retained_not_proved_impossible')
            self.calls+=1;m=self.model.clone()
            for i,ids in allowed.items():
                domain=cp_model.Domain.from_values(ids).flattened_intervals()
                m.proto.variables[self.x[i].index].domain.clear()
                m.proto.variables[self.x[i].index].domain.extend(domain)
            for i,v in partial.items():m.add_linear_expression_in_domain(self.x[i],cp_model.Domain.from_values(self.g['descriptors'][i][v]['ids']))
            for i,ids in native_required.items():m.add_linear_expression_in_domain(self.x[i],cp_model.Domain.from_values(ids))
            if order is not None:
                nonzero=[]
                for i,x in enumerate(self.x):
                    b=m.new_bool_var('active:'+str(i));m.add(x!=0).only_enforce_if(b);m.add(x==0).only_enforce_if(b.Not());nonzero.append(b)
                m.add(sum(nonzero)==order)
            # Minimize gratuitous components, never service failures or energy.
            # Required target values still force arbitrary feasible joint order.
            active=[]
            for i,x in enumerate(self.x):
                b=m.new_bool_var('present:'+str(i));m.add(x!=0).only_enforce_if(b);m.add(x==0).only_enforce_if(b.Not());active.append(b)
            m.minimize(sum(active))
            solver=cp_model.CpSolver();solver.parameters.num_search_workers=1
            solver.parameters.cp_model_presolve=True
            solver.parameters.cp_model_probing_level=0
            solver.parameters.linearization_level=0
            solver.parameters.max_deterministic_time=self.cfg['oracle_deterministic_time']
            solver.parameters.random_seed=stream(self.cfg['seed'],'B-oracle',self.c['household_id'],self.c['date'])
            status=solver.solve(m)
            if status==cp_model.INFEASIBLE:
                answer=('infeasible',None,'CP_proof_in_declared_native_grammar');self.cache[key]=answer;return answer
            if status not in (cp_model.FEASIBLE,cp_model.OPTIMAL):return ('unknown',None,'oracle_budget')
            native=[solver.value(x) for x in self.x]
            children=[self.g['values'][i][v] for i,v in enumerate(native) if v]
            self.materializations+=1
            row=request(self.c,children,self.cfg,self.portrait)
            if row.get('engineering_diagnostic') or row.get('relevance_diagnostic'):
                row.update(repaired=False,replacement_generated=False,search_scope='constraint_backtracking;not_outcome_reroll')
                self.diagnostics.append(row)
                self.model.add_forbidden_assignments(self.x,[native]);continue
            answer=self.remember(native,row);self.cache[key]=answer;return answer
        return ('unknown',None,'oracle_query_budget')


def generate_day(context,cfg=None,portrait=None):
    require_no_downstream_fields(context,'B_CONTEXT')
    require_no_downstream_fields(portrait,'B_PORTRAIT')
    cfg=config(cfg);before=digest(context);c=prepare(context,cfg)
    baseline_checks,baseline_gate,_=issues(c,[],[])
    # Legacy full-A service checks are performed separately; never change A.
    baseeng=engineering_issues(c,c['A'],(),[i for i in baseline_checks if i!='TARGET_CONTROL_NOT_AUTHORIZED'])
    if baseeng:return dict(schema=cfg['schema'],status='baseline_engineering_error',rows=[],engineering_diagnostics=baseeng,
        A_input_unchanged=True,physical_status='not_computed')
    g=catalogue_domains(c,cfg);oracle=Oracle(c,g,cfg,portrait);n=len(g['domains']);budget=cfg['rows_per_unit']*max(1,n)
    orders=[];within=[];mechanism_probes=[];same_family_probes=[]
    def breadth():
        from collections import deque
        from .semantics import mechanism
        queues=defaultdict(deque)
        for i,values in enumerate(g['values']):
            mechanisms=defaultdict(list)
            for j,r in enumerate(values[1:],1):
                name=mechanism(r['mechanism']) if cfg.get('oracle_propagation') in ('interval_v1','interval_forward_v1') else r['mechanism']
                mechanisms[(name,r['magnitude'].get('axis','program'))].append(j)
            for name,ids in sorted(mechanisms.items()):queues[values[1]['family']].append((i,name,ids))
        while any(queues.values()):
            for family in sorted(queues):
                if not queues[family]:continue
                i,name,ids=queues[family].popleft()
                if cfg['mechanism_joint_extension']:
                    ids=[j for j in ids if j in oracle.root_indices[i]]
                singleton=oracle({j:0 for j in range(n) if j!=i},native_required={i:ids})
                joint=None
                if cfg['mechanism_joint_extension'] and singleton[0]!='feasible':
                    joint=oracle({},native_required={i:ids})
                status,_,reason=joint if joint is not None else singleton
                mechanism_probes.append(dict(factor=i,mechanism=name,status=status,reason=reason,
                    singleton=singleton,joint_extension=joint,
                    scope='direct_mechanism_then_joint_extension;declared_native_domain_only' if cfg['mechanism_joint_extension'] else
                          'single_unit;failure_does_not_exclude_joint_extension'))
    if cfg.get('oracle_propagation') in ('interval_v1','interval_forward_v1'):breadth()
    # Breadth before within-device detail: one single-unit witness per factor,
    # every joint cardinality, then pair/triple coverage and remaining details.
    # Prevent a richly described AC from exhausting a small budget on its own.
    for i,domain in enumerate(g['domains']):
        if len(domain)>1:oracle({**{j:0 for j in range(n) if j!=i},i:domain[1]})
    if cfg.get('oracle_propagation')=='interval_forward_v1':
        # Named same-family task pairs are real interaction targets, not quotas.
        # Different batches retain their original identity and full native grid.
        for i,j in itertools.combinations(range(n),2):
            a,b=g['values'][i][1],g['values'][j][1]
            if a['family']!=b['family'] or a['family'] not in ('washer','dryer','dishwasher'):continue
            required={k:list(range(1,len(g['values'][k]))) for k in (i,j)}
            status,_,reason=oracle({k:0 for k in range(n) if k not in (i,j)},native_required=required)
            joint=None
            if status!='feasible':joint=oracle({},native_required=required)
            same_family_probes.append(dict(factors=[i,j],family=a['family'],status=status,reason=reason,
                joint_extension=joint,scope='named_same_family_pair;no_selection_quota'))
    for k in range(1,n+1):
        status,_,reason=oracle({},order=k);orders.append(dict(order=k,status=status,reason=reason))
    # Mechanism breadth has priority over extra raw-dose descriptions. Each
    # mechanism gets a bounded existential request, with no success ordering.
    if cfg.get('oracle_propagation') not in ('interval_v1','interval_forward_v1'):
        for i,values in enumerate(g['values']):
            mechanisms=defaultdict(list)
            for j,r in enumerate(values[1:],1):mechanisms[(r['mechanism'],r['magnitude'].get('axis','program'))].append(j)
            for name,ids in sorted(mechanisms.items()):
                oracle({j:0 for j in range(n) if j!=i},native_required={i:ids})
    resources=[]
    for values in g['values']:
        r=values[1];nid=r.get('service_need_id')
        resources.append({'asset:'+r['asset_id']} | {'person:'+o['operator_id'] for o in c['A']['operations'] if nid and o['need_id']==nid} |
                         {'room:'+o['room_id'] for o in c['A']['operations'] if nid and o['need_id']==nid})
    triples=[t for t in itertools.combinations(range(n),3) if
        any(resources[a]&resources[b] for a,b in itertools.combinations(t,2))]
    search=generate if cfg['search_strategy']=='ipog_c' else round_robin
    cover=search(g['domains'],oracle,triples=triples,seed=cfg['seed'],row_budget=budget,
                   query_budget=cfg['queries_per_row']*budget)
    # Named within-device interactions retain independent temperature, duration
    # and preconditioning coordinates rather than only a few lucky raw doses.
    for i,values in enumerate(g['values']):
        named=defaultdict(list)
        for j,r in enumerate(values[1:],1):
            m=r['magnitude']
            if cfg['method_revision']=='delivery_v2_11':
                from .change_axes import labels
                position=canonical(labels(r['change_axes']))
            else:position=r['relative_level']
            key=(r['mechanism'],position,m.get('duration_min'),m.get('precondition_min'))
            named[key].append(j)
        for target,ids in sorted(named.items(),key=lambda item:canonical(item[0])):
            status,_,reason=oracle({j:0 for j in range(n) if j!=i},native_required={i:ids})
            within.append(dict(factor=i,target=list(target),status=status,reason=reason))
    # Named within-program/thermal triples are represented by native cells;
    # cross-unit strength-three is reserved for shared-resource dependencies.
    rows=sorted(oracle.rows.values(),key=lambda r:r['id'])
    support_attempts=0
    # Conditional support closure: only inspect support actions for root plans
    # which actually introduced a resource/capacity conflict. Several supported
    # actions may be added; cardinality is not capped at two device families.
    for root in list(rows):
        if not any(i.startswith(('OPERATOR_','ROOM_','SITE_')) for i in root['issues']):continue
        children=[next(r for values in g['values'] for r in values[1:] if r['id']==cid) for cid in root['component_ids']]
        used={r['unit'] for r in children}
        for support in g['support_domain']:
            if support_attempts>=budget or oracle.materializations>=budget:break
            if support['unit'] in used:continue
            support_attempts+=1
            support=copy.deepcopy(support);support.update(relative_level='support_context',absolute_level=absolute_level(support),
                known_event_reduction_kWh=0.0,unknown_thermal_response=support['profiles'] is None)
            proposed=children+[support]
            explanation=relevance(c,proposed,cfg['event'])
            if not explanation['passed']:continue
            oracle.materializations+=1
            row=request(c,proposed,cfg,portrait)
            if row.get('engineering_diagnostic') or row.get('relevance_diagnostic'):oracle.diagnostics.append(row);continue
            oracle.rows.setdefault(row['id'],row);children=proposed;used.add(support['unit'])
        if support_attempts>=budget:break
    rows=sorted(oracle.rows.values(),key=lambda r:r['id'])
    # All witnesses, including singleton/order/device-detail probes, contribute
    # to the SAME predeclared denominator; never leave a found target unknown.
    existing={tuple(r):i for i,r in enumerate(cover['rows'])}
    for _,cells,_ in oracle.witnesses:
        if tuple(cells) not in existing:existing[tuple(cells)]=len(cover['rows']);cover['rows'].append(cells)
    axes={tuple(i for i,v in t['target']) for t in cover['coverage']};hits={}
    for cells,index in existing.items():
        for axis in axes:hits.setdefault(tuple((i,cells[i]) for i in axis),index)
    for t in cover['coverage']:
        key=tuple(tuple(x) for x in t['target'])
        if key in hits:t.update(status='feasible',witness_row=hits[key],reason=None)
    cover['complete']=all(t['status']=='infeasible' or t['witness_row'] is not None for t in cover['coverage'])
    for item in orders:
        witness=next((w for w in oracle.witnesses if sum(v!=0 for v in w[0])==item['order']),None)
        if witness:item.update(status='feasible',reason=witness[2])
    if not rows:
        status,_,why=oracle({})
        only_engineering_roots=bool(g['values']) and all(r.get('_intrinsic_issues') for vs in g['values'] for r in vs[1:])
        from .opportunities import declare
        missing_evidence=bool(g['gaps']) or any(e['status']=='unknown' for e in declare(context,cfg)['entries'])
        if status=='infeasible' and not only_engineering_roots and not missing_evidence:
            row=request(c,[],cfg,portrait);row['no_opportunity_reason']='no_engineering_valid_event_relevant_request_in_declared_native_grammar'
            rows=[row]
        else:why='search_unresolved;not_no_opportunity'
    else:why=None
    if digest(context)!=before:raise ValueError('UNIFIED_MUTATED_FROZEN_A')
    encoded,templates=export_native(g['values']+[g['support_domain'],
        [r['request'] for r in g['engineering_diagnostics'] if isinstance(r.get('request'),ProgramRecipe)]])
    native=encoded[:-2];support_native=encoded[-2]
    return dict(schema='eb.unified.day.v2',household_id=c['household_id'],date=c['date'],
        status='candidate_catalogue' if rows else 'search_unresolved',rows=rows,
        A_commands_sha256=command_hash(context['A']),context_sha256=before,
        coverage=cover,factors=g['descriptors'],joint_orders=orders,
        within_device_interactions=within,
        mechanism_probes=mechanism_probes,same_family_probes=same_family_probes,
        engineering_diagnostics=g['engineering_diagnostics']+[r for r in oracle.diagnostics if r.get('engineering_diagnostic')],
        relevance_diagnostics=[r for r in oracle.diagnostics if r.get('relevance_diagnostic')],
        raw_requests=g['raw_count'],raw_zero_changes=g['unmodified'],native_alternatives=sum(len(v)-1 for v in g['values']),
        native_grammar_scope=g['scope'],gaps=g['gaps'],unresolved_reason=why,
        support_search=dict(domain=len(g['support_domain']),attempts=support_attempts,
            scope='conditional_conflict_witness_closure;unsearched_support_combinations_unknown;no_infeasibility_claim'),
        oracle_calls=oracle.calls,materialized_requests=oracle.materializations,materialization_budget=budget,physical_status='not_computed',A_input_unchanged=True,
        constraint_propagation_log=oracle.propagation_log,forward_search_log=oracle.forward_search_log,
        native_domains=native,native_templates=templates,
        native_encoding='lossless_shared_program_templates_and_handling_coordinates_v2',
        support_native_domain=support_native,
        actual_outcomes_used=False,human_answers_generated=False)
