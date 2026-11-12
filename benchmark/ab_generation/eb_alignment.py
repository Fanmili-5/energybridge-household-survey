"""EB execution semantics for household-V9 A/B proposals; opt-in, outcome-free."""
from collections import defaultdict
from copy import deepcopy
import math
import datetime as dt
from .common import digest

VERSION='eb.household_v9.execution_alignment.v1'
EB_COMMIT='2b17ae63e613da776c93e900f5dace50d63a88a8'
CONTIGUOUS='single_contiguous_session_per_episode'
FUNCTION={'ac':'AC','washer':'WM','dryer':'DR','dishwasher':'DW','water_heater':'WH','ev':'EV'}

# The repaired server copy is byte-identical to the pinned paper appliance file.
# A different target requires a new semantic replay, not a caller-supplied flag.
VERIFIED_NATIVE_TARGET_SHA256={'be072673de26228a286e5ab9223d160a2a71084fa7b6c9146dbc5d024a879de9'}

def verify_native_target(path):
    """Read the selected actual source file; do not trust a claimed capability."""
    import hashlib
    from pathlib import Path
    if path is None:raise ValueError('VERIFIED_NATIVE_TARGET_SOURCE_REQUIRED')
    sha=hashlib.sha256(Path(path).read_bytes()).hexdigest()
    if sha not in VERIFIED_NATIVE_TARGET_SHA256:
        raise ValueError('NATIVE_TARGET_NOT_VERIFIED_FOR_WHOLE_PLAN_EXECUTION:'+sha)
    return dict(appliance_source_sha256=sha,cross_midnight_programs_verified=True,
        scope='appliance source preflight; full physical-run version binding remains required')

def runs(rows):
    """Merge adjacent accounting bins, preserving real gaps and rejecting overlaps."""
    result=[]
    for row in sorted(rows,key=lambda r:(r['start_min'],r['end_min'])):
        a,z=row['start_min'],row['end_min']
        if not all(type(v) in (int,float) and math.isfinite(v) for v in (a,z)) or z<=a:
            raise ValueError('INVALID_EXECUTION_INTERVAL')
        if result and a<result[-1][1]-1e-8:raise ValueError('OVERLAPPING_EXECUTION_BINS')
        if result and abs(a-result[-1][1])<=1e-8:result[-1][1]=z
        else:result.append([a,z])
    return result

def operation_windows(case,dates,*,anchor=None,step_min=10):
    """Fit machine operation slots inside the unchanged exact V9 life windows.

    Calendar times are kept verbatim. Ceil/floor only shrink operator availability;
    they never move a meal/care/commute boundary or make an unavailable person free.
    """
    if step_min!=10:raise ValueError('EB_OPERATION_GRID_REQUIRES_10_MINUTES')
    dates=list(dates)
    if not dates or len(set(dates))!=len(dates):raise ValueError('DATES_REQUIRED_AND_UNIQUE')
    parsed=[dt.date.fromisoformat(d) for d in dates]
    anchor_date=dt.date.fromisoformat(anchor) if anchor else min(parsed)
    out={}
    members={m['id'] for m in case['household']['members']}
    for date,d in zip(dates,parsed):
        base=(d-anchor_date).days*1440
        if base<0:raise ValueError('DATE_BEFORE_CALENDAR_ANCHOR')
        source=case['household']['routine']['daily_services'][d.weekday()]
        windows={mid:[] for mid in members};bindings=[]
        for row in source['manual_operation_opportunities']:
            mid=row['member_id'];a,z=row['start'],row['end']
            if mid not in members:raise ValueError('UNKNOWN_SOURCE_WINDOW_MEMBER')
            lo=math.ceil(a/step_min)*step_min;hi=math.floor(z/step_min)*step_min
            if hi-lo<step_min:continue
            windows[mid].append([base+lo,base+hi])
            bindings.append(dict(member_id=mid,reference_week_day=d.weekday(),exact_source_min=[a,z],operation_grid_min=[lo,hi]))
        out[date]=dict(base_min=base,operator_windows=windows,source_window_bindings=bindings,
            original_family_calendar_changed=False,rounding='conservative_inside_original_operation_window')
    return out

def _bind_household_source_core(context,case,manifest_sha256,*,function_by_asset=None):
    """Bind an already constructed life/A context to V9 without rewriting facts.

    This is the execution guard interface. Device power, program, physical room,
    dated service needs and source calendars must already have been supplied by
    the life/physical-world adapter; the guard does not invent those inputs.
    """
    c=deepcopy(context);h=case['household'];mapping={}
    if c['household_id']!=case['case_id']:raise ValueError('HOUSEHOLD_CONTEXT_IDENTITY_MISMATCH')
    if c['source'].get('household_case_sha256')!=digest(case):raise ValueError('DATED_LIFE_ADAPTER_SOURCE_BINDING_REQUIRED')
    if 'AC' not in h['controlled_function_ids']:raise ValueError('V9_REQUIRES_CONTROLLED_AC')
    for d in c['devices']:
        kinds=d.get('types') or [d['kind']]
        fs=(function_by_asset or {}).get(d['asset_id']) or [FUNCTION[k] for k in kinds if k in FUNCTION]
        if not fs or len(set(fs))!=len(fs) or any(f not in FUNCTION.values() for f in fs):
            raise ValueError('UNKNOWN_NATIVE_FUNCTION_MAPPING:'+d['asset_id'])
        mapping[d['asset_id']]=list(fs)
        if 'EV' in fs:
            contract=h['service_contracts'].get('EV')
            # Non-controlled EV service can remain fixed, with the same profile.
            if contract:d['parameters']['charge_session_policy']=contract['operation_policy']
            elif h.get('ev',{}).get('charging_contiguity')=='one_continuous_session_is_required_for_base_need':d['parameters']['charge_session_policy']=CONTIGUOUS
    missing=set(h['controlled_function_ids'])-{f for fs in mapping.values() for f in fs}
    if missing:raise ValueError('MISSING_CONTROLLED_FUNCTION_ASSET:'+','.join(sorted(missing)))
    original=c['source'].get('household_input_manifest_sha256')
    if original is not None and original!=manifest_sha256:raise ValueError('HOUSEHOLD_MANIFEST_BINDING_DIFFERS')
    c['source']['household_input_manifest_sha256']=manifest_sha256
    c['native_execution_contract']=dict(version=VERSION,eb_commit=EB_COMMIT,case_id=case['case_id'],
        household_case_sha256=digest(case),household_input_manifest_sha256=manifest_sha256,
        controlled_functions=deepcopy(h['controlled_function_ids']),function_by_asset=mapping,
        operation_policy={**({'EV':CONTIGUOUS} if h.get('ev',{}).get('charging_contiguity')=='one_continuous_session_is_required_for_base_need' else {}),**{f:v['operation_policy'] for f,v in h['service_contracts'].items()}},
        fixed_predecessor_services_retained=True,mechanical_errors_are_training_diagnostics=True)
    return c

def _ev_profiles(c,plan,children,side):
    # Reconstruct positive nominal charging from the ACTUAL command windows and
    # the fixed A energy requirement, not the candidate's description/profiles.
    out={};changed=set()
    # Instructions, not explanation/component metadata, determine native mode.
    def commands(plan,aid,nid):
        return sorted((r['start_min'],r['end_min'],r.get('stop_at_target_soc'))
            for r in plan['controls'] if r.get('asset_id')==aid and r.get('need_id')==nid and r.get('kind')=='ev_charge_window')
    if side=='B':
        for row in plan['controls']+c['A']['controls']:
            if row.get('kind')!='ev_charge_window':continue
            key=(row['asset_id'],row.get('need_id'))
            if commands(plan,*key)!=commands(c['A'],*key):changed.add(key)
    for device in c['devices']:
        if 'ev' not in device.get('types',[device.get('kind')]):continue
        aid=device['asset_id'];groups=defaultdict(list)
        for row in plan['controls']:
            if row.get('asset_id')==aid and row.get('kind')=='ev_charge_window':groups[row.get('need_id')].append(row)
        for nid,windows in groups.items():
            needed=sum(r['grid_kWh'] for r in c['reference'].get('ev_charging_steps',[]) if r['need_id']==nid)
            left=needed;rows=[];kw=device['parameters']['charger_kw']
            if not windows or needed<=1e-10:out[(aid,nid)]=[];continue
            lo=math.floor(min(r['start_min'] for r in windows)/10)*10;hi=math.ceil(max(r['end_min'] for r in windows)/10)*10
            for t in range(lo,hi,10):
                if not any(r['start_min']<=t and t+10<=r['end_min'] for r in windows):continue
                # EB window override avoids VPP automatically. An unchanged EV
                # retains the ordinary normal-mode execution of A.
                if side=='B' and ((aid,nid) in changed or c.get('source',{}).get('appliance_command_protocol')=='eb.primary_appliance_calls.v1') and any(e['start_min']<t+10 and e['end_min']>t for e in c['events']):continue
                amount=min(kw/6,left)
                if amount>1e-10:rows.append(dict(start_min=t,end_min=t+10,grid_kWh=amount,power_kw=amount*6));left-=amount
                if left<=1e-10:break
            out[(aid,nid)]=rows
    return out

def _energy_bins(rows):
    values=defaultdict(float)
    for row in rows:
        for t in range(int(row['start_min']),int(row['end_min']),10):
            values[t]+=row.get('power_kw',row.get('grid_kWh',0)*6)/6
    return dict(values)

def _audit_with_legacy_connection_bindings(c,plan,children=(),*,side='B'):
    """Check task identity, continuity and native capability; separate service risk."""
    if side not in ('A','B'):raise ValueError('INVALID_PLAN_SIDE')
    contract=c.get('native_execution_contract')
    if not contract:
        required=any(c.get('source',{}).get(k) for k in ('household_case_sha256','household_input_manifest_sha256'))
        return dict(enabled=required,hard_errors=['V9_NATIVE_EXECUTION_BINDING_REQUIRED'] if required else [],
            service_risks=[],passed=not required)
    if contract['version']!=VERSION:raise ValueError('UNKNOWN_NATIVE_EXECUTION_CONTRACT')
    errors=[];risks=[];mapping=contract['function_by_asset'];controlled=set(contract['controlled_functions'])
    original={t['task_id']:t for t in c['A']['tasks']};tasks=defaultdict(list)
    for t in plan['tasks']:tasks[t['task_id']].append(t)
    for tid,old in original.items():
        rows=tasks.get(tid,[])
        if len(rows)!=1:errors.append('PROGRAM_TASK_SPLIT_OR_REMOVED:'+tid);continue
        new=rows[0]
        if new['kind']!=old['kind'] or new['asset_id']!=old['asset_id'] or new['need_id']!=old['need_id']:
            errors.append('PROGRAM_IDENTITY_CHANGED:'+tid);continue
        if new['end_min']-new['start_min']!=old['end_min']-old['start_min']:
            errors.append('PROGRAM_DURATION_CHANGED:'+tid)
        if new!=old and FUNCTION[new['kind']] not in controlled:errors.append('UNCONTROLLED_FUNCTION_CHANGED:'+tid)
        if old['start_min']<c['decision_min'] and new!=old:errors.append('STARTED_PROGRAM_RESCHEDULED:'+tid)
    if set(tasks)-set(original):errors.append('INVENTED_PROGRAM_TASK')
    needs={n['need_id']:n for n in c['needs']}
    for t in plan['tasks']:
        if t['end_min']<=t['start_min']:errors.append('INVALID_PROGRAM_INTERVAL:'+t['task_id'])
        declared=needs.get(t['need_id'],{}).get('duration_min')
        if declared is not None and abs(t['end_min']-t['start_min']-declared)>1e-8:errors.append('PROGRAM_CAPABILITY_DURATION_MISMATCH:'+t['task_id'])
    for i,t in enumerate(plan['tasks']):
        for other in plan['tasks'][i+1:]:
            if t['asset_id']==other['asset_id'] and t['start_min']<other['end_min'] and other['start_min']<t['end_min']:errors.append('SHARED_PROGRAM_ASSET_OVERLAP')
    by_need={t['need_id']:t for t in plan['tasks']}
    for t in plan['tasks']:
        n=needs.get(t['need_id'],{})
        if t['start_min']<n.get('release_min',-math.inf):errors.append('PROGRAM_BEFORE_LOAD_RELEASE:'+t['task_id'])
        parent=n.get('upstream_need_id') or n.get('depends_on_need_id')
        if parent:
            p=by_need.get(parent)
            if p is None or p['end_min']>t['start_min']:errors.append('DRY_BEFORE_SAME_LOAD_WASH_COMPLETES:'+t['task_id'])
        if t['end_min']>n.get('deadline_min',math.inf):risks.append('SERVICE_DEADLINE_RISK:'+t['task_id'])
    control_kind={'ac_setpoint':'AC','tank_setpoint':'WH','ev_charge_window':'EV'}
    for row in plan['controls']:
        function=control_kind.get(row.get('kind'))
        if not function or function not in mapping.get(row.get('asset_id'),[]):errors.append('UNKNOWN_OR_MISMATCHED_NATIVE_CONTROL')
        if row['end_min']<=row['start_min']:errors.append('INVALID_CONTROL_INTERVAL')
    for function in set(control_kind.values())-controlled:
        old=sorted((r for r in c['A']['controls'] if control_kind.get(r['kind'])==function),key=digest)
        new=sorted((r for r in plan['controls'] if control_kind.get(r['kind'])==function),key=digest)
        if old!=new:errors.append('UNCONTROLLED_FIXED_SERVICE_CHANGED:'+function)
    # The original EB ShiftableAppliance exposes one start/duration per day.
    per_day=defaultdict(list)
    for t in plan['tasks']:per_day[(t['asset_id'],t['kind'],t['start_min']//1440)].append(t)
    for key,rows in per_day.items():
        if len(rows)>1:errors.append('NATIVE_SINGLE_DAILY_TASK_CAPABILITY_EXCEEDED:'+str(key))
    # Preserve qualified manual handling and the actual life windows.
    old_ops={o['operation_id']:o for o in c['A']['operations']}
    if set(old_ops)!={o['operation_id'] for o in plan['operations']} or len(plan['operations'])!=len(old_ops):errors.append('HANDLING_OPERATION_REMOVED_OR_DUPLICATED')
    for op in plan['operations']:
        if op['operation_id'] not in old_ops:errors.append('INVENTED_HANDLING_OPERATION');continue
        original_op=old_ops[op['operation_id']]
        if any(op.get(k)!=original_op.get(k) for k in ('asset_id','need_id','kind','room_id')) or op['end_min']-op['start_min']!=original_op['end_min']-original_op['start_min']:
            errors.append('HANDLING_IDENTITY_OR_DURATION_CHANGED:'+op['operation_id'])
        if side=='B' and op!=original_op and original_op['start_min']<c['decision_min']:
            errors.append('EXECUTED_HANDLING_OPERATION_CHANGED:'+op['operation_id'])
        authority=c['authority']['assets'].get(op['asset_id'],{})
        if op['operator_id'] not in authority.get('authorized_operator_ids',[]):errors.append('HANDLER_NOT_AUTHORIZED:'+op['operation_id'])
        if not handler_in_source_window(c,op):
            errors.append('HANDLER_OUTSIDE_SOURCE_OPERATION_WINDOW:'+op['operation_id'])
    ev_runs=[]
    # Permission intervals themselves must be expressible by one native window;
    # a gap is only representable when it is the declared full smart VPP event.
    groups=defaultdict(list)
    for row in plan['controls']:
        if row.get('kind')=='ev_charge_window':groups[(row['asset_id'],row.get('need_id'))].append(row)
    for (aid,nid),windows in groups.items():
        try:
            permission_runs=runs(windows)
            for (_,end),(start,_) in zip(permission_runs,permission_runs[1:]):
                allowed=contract['operation_policy'].get('EV')=='eb_smart_vpp_pause' and any(end==e['start_min'] and start==e['end_min'] for e in c['events'])
                if not allowed:errors.append('EV_PERMISSION_GAP_NOT_NATIVE:'+str(nid))
        except ValueError as exc:errors.append(str(exc))
        physical=[p for p in c.get('physical_ev_connections',[]) if p['need_id']==nid]
        if not physical:
            plugs=[o['end_min'] for o in plan['operations'] if o.get('asset_id')==aid and o.get('need_id')==nid and o['kind']=='EV_plug']
            unplugs=[o['start_min'] for o in plan['operations'] if o.get('asset_id')==aid and o.get('need_id')==nid and o['kind']=='EV_unplug']
            if len(plugs)==len(unplugs)==1:physical=[dict(start_min=plugs[0],end_min=unplugs[0])]
        if not physical:errors.append('EV_PHYSICAL_CONNECTION_EVIDENCE_REQUIRED:'+str(nid))
        elif any(not any(p['start_min']<=r['start_min']<r['end_min']<=p['end_min'] for p in physical) for r in windows):
            errors.append('EV_PERMISSION_OUTSIDE_PHYSICAL_CONNECTION:'+str(nid))
    try:
        for (aid,nid),rows in _ev_profiles(c,plan,children,side).items():
            positive=[r for r in rows if r.get('power_kw',r.get('grid_kWh',1))>1e-10]
            spans=runs(positive);policy=contract['operation_policy'].get('EV')
            if policy==CONTIGUOUS and len(spans)>1:errors.append('EV_UNDECLARED_INTERRUPTION:'+str(nid))
            if policy=='eb_smart_vpp_pause' and side=='B':
                gaps=list(zip([z for a,z in spans[:-1]],[a for a,z in spans[1:]]))
                if any(not any(abs(a-e['start_min'])<1e-8 and abs(z-e['end_min'])<1e-8 for e in c['events']) for a,z in gaps):errors.append('EV_PAUSE_NOT_NATIVE_SMART_EVENT:'+str(nid))
                if any(a<e['end_min'] and z>e['start_min'] for a,z in spans for e in c['events']):errors.append('SMART_EV_CHARGES_DURING_VPP:'+str(nid))
            child=next((r for r in children if r.get('family')=='ev' and r.get('service_need_id')==nid),None)
            required=sum(r['grid_kWh'] for r in c['reference'].get('ev_charging_steps',[]) if r['need_id']==nid)
            delivered=sum(r.get('grid_kWh',r.get('power_kw',0)/6) for r in positive)
            if required-delivered>1e-8:risks.append('EV_DEPARTURE_ENERGY_RISK:'+str(nid))
            if child and side=='B' and child.get('profiles') is not None:
                declared=_energy_bins(child['profiles'].get('B',[]));actual=_energy_bins(positive)
                if any(abs(declared.get(t,0)-actual.get(t,0))>1e-6 for t in set(declared)|set(actual)):errors.append('DECLARED_EV_PROFILE_DIFFERS_FROM_NATIVE_COMMANDS:'+str(nid))
                # EB charge-window override automatically pauses in VPP. A
                # continuous native proposal must avoid crossing that event.
                windows=[r for r in plan['controls'] if r.get('asset_id')==aid and r.get('need_id')==nid and r.get('kind')=='ev_charge_window']
                if policy==CONTIGUOUS and len(spans)>1 and any(r['start_min']<e['end_min'] and r['end_min']>e['start_min'] for r in windows for e in c['events']):
                    errors.append('NATIVE_EV_WINDOW_WOULD_PAUSE_INSIDE_VPP:'+str(nid))
            if side=='A':
                declared=_energy_bins([r for r in c['reference'].get('ev_charging_steps',[]) if r['need_id']==nid])
                actual=_energy_bins(positive)
                if any(abs(declared.get(t,0)-actual.get(t,0))>1e-6 for t in set(declared)|set(actual)):
                    errors.append('A_EV_PROFILE_DIFFERS_FROM_NATIVE_COMMANDS:'+str(nid))
            ev_runs.append(dict(asset_id=aid,need_id=nid,runs_min=spans,required_A_grid_kWh=required,delivered_nominal_grid_kWh=delivered))
    except ValueError as e:errors.append(str(e))
    return dict(enabled=True,version=VERSION,eb_commit=contract['eb_commit'],passed=not errors,
        hard_errors=sorted(set(errors)),service_risks=sorted(set(risks)),ev_runs=ev_runs,
        scope='native action and declared service semantics; actual physical outcomes remain separate')

def compact_plan(c,plan,children=(),*,side='B'):
    result=audit(c,plan,children,side=side)
    if not result['enabled']:raise ValueError('NATIVE_EXECUTION_BINDING_REQUIRED_FOR_PLAN_SUMMARY')
    if result['hard_errors']:raise ValueError('PLAN_NOT_EB_ALIGNED:'+','.join(result['hard_errors']))
    return dict(schema='eb.aligned_execution_summary.v1',
        program_tasks=[{k:t[k] for k in ('task_id','asset_id','kind','need_id','start_min','end_min')} for t in plan['tasks']],
        charging_sessions=result.get('ev_runs',[]),thermal_controls=deepcopy([r for r in plan['controls'] if r['kind']!='ev_charge_window']),
        operations=deepcopy(plan['operations']),validation=result,
        meaning='whole task/session summary for review and reward inputs; not an independent RL action decoder')

def handler_in_source_window(c,op):
    """Only the bound source EV transaction gets asset-specific availability."""
    ordinary=c.get('operator_windows',{}).get(op['operator_id'],[])
    if op['kind'] in ('EV_plug','EV_unplug'):
        episode=c.get('native_execution_contract',{}).get('EV_episode_binding')
        if episode and episode['asset_id']==op['asset_id'] and episode['mapped_operator_id']==op['operator_id']:
            ordinary=c.get('native_operation_windows_by_asset',{}).get(op['asset_id'],{}).get(op['operator_id'],[])
    return any(a<=op['start_min'] and op['end_min']<=z for a,z in ordinary)

def audit(c,plan,children=(),*,side='B'):
    result=_audit_with_legacy_connection_bindings(c,plan,children,side=side)
    if side=='B' and c.get('question_unit')=='one_dated_household_day':
        from .primary_day_clock import start_supported
        original={r['task_id']:r for r in c['A']['tasks']}
        if any(not start_supported(c,original.get(r['task_id']),r) for r in plan['tasks']):
            result['hard_errors']=list(result.get('hard_errors',[]))+['PRIMARY_METHOD_START_CLOCK_NOT_EXPRESSIBLE']
            result['passed']=False
    if c.get('question_unit')=='one_dated_household_day' and 'daily_service_requirements' in c:
        from .daily_services import audit_daily_plan
        daily=audit_daily_plan(c,plan)
        result['daily_service_acceptance']=daily
        if not daily['passed']:
            result['hard_errors']=list(result.get('hard_errors',[]))+[r['code'] for r in daily['errors']]
            result['passed']=False
    if c.get('source',{}).get('appliance_command_protocol')=='eb.primary_appliance_calls.v1':
        if plan['operations']:result['hard_errors'].append('NON_EB_MANUAL_OPERATION')
        needs={n['need_id']:n for n in c['needs']}
        for task in plan['tasks']:
            n=needs[task['need_id']];window=n['start_window_min']
            if not window[0]<=task['start_min']<window[1] or task['end_min']>n['deadline_min']:
                result['hard_errors'].append('PRIMARY_PROGRAMME_OUTSIDE_ALLOWED_WINDOW')
            if not 0<=task['start_min']<task['end_min']<=1440:
                result['hard_errors'].append('NON_EV_PROGRAMME_OVERNIGHT_FORBIDDEN')
        heater_rows=defaultdict(list)
        for row in plan['controls']:
            if row['kind']=='tank_setpoint':
                heater_rows[(row['asset_id'],row['start_min']//1440)].append(row)
                maximum=next(d['parameters']['maximum_C'] for d in c['devices'] if d['asset_id']==row['asset_id'])
                if not 45<=row['value_C']<=min(75,maximum):result['hard_errors'].append('PRIMARY_WATER_HEATER_TEMPERATURE_UNREPRESENTABLE')
                if row['end_min']-row['start_min']>240:result['hard_errors'].append('PRIMARY_WATER_HEATER_WINDOW_WOULD_BE_CLAMPED')
            if row['kind']=='tank_setpoint' and row['start_min']//1440!=(row['end_min']-1)//1440:
                result['hard_errors'].append('NON_EV_WATER_HEATER_OVERNIGHT_FORBIDDEN')
        if any(len(rows)!=1 for rows in heater_rows.values()):result['hard_errors'].append('PRIMARY_WATER_HEATER_NEEDS_SINGLE_DAILY_WINDOW')
        if any(x.startswith('EV_DEPARTURE_ENERGY_RISK') for x in result.get('service_risks',[])):
            result['hard_errors'].append('EV_DEPARTURE_TARGET_NOT_MET')
        result['hard_errors']=sorted(set(result['hard_errors']))
        result['passed']=not result['hard_errors']
    from .connection_states import ORIGIN,valid,covers
    if any(r.get('origin')==ORIGIN for r in c.get('physical_ev_connections',[])):
        if not valid(c) or not covers(c,plan):
            result['hard_errors']=list(result.get('hard_errors',[]))+['UNBOUND_SOURCE_EV_CONNECTION_STATE']
            result['passed']=False
    if c.get('source',{}).get('appliance_command_protocol')=='eb.primary_appliance_calls.v1':
        from .eb_agent_contract import plan_errors
        result['hard_errors'].extend(plan_errors(c,plan))
        if result['hard_errors']:result['passed']=False
    return result

def bind_household(context,case,manifest_sha256,*,function_by_asset=None):
    from .connection_states import valid,attach
    previous=context.get('native_execution_contract',{}).get('source_connected_episode')
    clocks=context.get('native_execution_contract',{}).get('primary_programme_windows')
    water=context.get('native_execution_contract',{}).get('primary_water_heater_configuration')
    if previous is not None and not valid(context):
        raise ValueError('SOURCE_CONNECTION_REBINDING_REQUIRES_VALID_ORIGIN')
    result=_bind_household_source_core(context,case,manifest_sha256,function_by_asset=function_by_asset)
    if clocks is not None:result['native_execution_contract']['primary_programme_windows']=clocks
    if water is not None:result['native_execution_contract']['primary_water_heater_configuration']=water
    # A day view keeps complete predecessor/retrieval chains. Re-derive their
    # actual source dates too; do not silently discard pre/post-day evidence.
    if result.get('source',{}).get('appliance_command_protocol')!='eb.primary_appliance_calls.v1' and result.get('question_unit')=='one_dated_household_day' and all(k in result for k in ('date','A','horizon_min')):
        import datetime as _dt
        base=_dt.date.fromisoformat(result['date'])
        minutes=list(result['horizon_min'])
        for op in result['A']['operations']:minutes.extend((op['start_min'],op['end_min']))
        dates=sorted({(base+_dt.timedelta(days=int(t)//1440)).isoformat() for t in minutes})
        origin=min(dates)
        source_windows=operation_windows(case,dates,anchor=origin)
        shift=(base-_dt.date.fromisoformat(origin)).days*1440
        result['operator_windows']={}
        for day in source_windows.values():
            for mid,windows in day['operator_windows'].items():
                result['operator_windows'].setdefault(mid,[]).extend([[a-shift,z-shift] for a,z in windows])
    if previous is not None:
        attach(result,previous)
        if not valid(result):raise ValueError('SOURCE_CONNECTION_REBINDING_CHANGED_SOURCE')
    if result.get('source',{}).get('appliance_command_protocol')=='eb.primary_appliance_calls.v1':
        from .eb_agent_contract import household_bounds,VERSION as AGENT_ACTION_VERSION
        result['native_execution_contract']['agent_action_bounds']=household_bounds(case['household'])
        result['native_execution_contract']['agent_action_contract']=AGENT_ACTION_VERSION
    if result.get('question_unit')=='one_dated_household_day' and 'reference' in result and 'A' in result:
        from .sampling import command_hash
        result['reference'].setdefault('binding',{})['A_commands_sha256']=command_hash(result['A'])
        result['reference']['binding']['context_sha256']=digest({k:v for k,v in result.items() if k!='reference'})
    return result
