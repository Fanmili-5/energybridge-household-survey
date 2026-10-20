"""Finite event-anchored requests, including unsuccessful plan diagnostics.

Only A-side inputs are consumed. B contains literal patches; nothing repairs an
invalid proposal after it has been evaluated. Thermal response stays unknown.
"""
import copy
import itertools
import math
from collections import Counter, defaultdict
from .common import digest
from .collection_design import (absolute_level, annotate_doses, amplitude_axes, event_status, issues,
    representatives, semantic_signature, tags, validate_context, working_context)
from .energy import task_power
from .generate import event_energy
from .model import apply, chain_need_ids, overlap
from .sampling import command_hash
from .collection_admission import program_construction_issues, engineering_issues
from .collection_thermal import describe as describe_ac
from .collection_relevance import direct, explain, asset_reasons


def _profile(c, tasks):
    devices = {d['asset_id']: d for d in c['devices']}
    return [{**t, 'power_kw': task_power(t, devices[t['asset_id']]['parameters'])} for t in tasks]


def _slots(c, op, left, right):
    """Calendar/booking domains; peer appliance conflicts are checked jointly."""
    length = op['end_min'] - op['start_min']
    out = set()
    for a, z in c['operator_windows'].get(op['operator_id'], []):
        lo = math.ceil(max(left, a, c['decision_min']) / 10) * 10
        hi = math.floor(min(right, z - length, c['horizon_min'][1] - length) / 10) * 10
        for t in range(lo, hi + 1, 10):
            if not any(r['room_id'] == op['room_id'] and overlap(t, t+length, r['start_min'], r['end_min'])
                       for r in c['reservations']):
                out.add(t)
    return sorted(out)


def _handling(c, tasks, ops, config, choice):
    """Bounded constructive loading/retrieval scheduling with dependency order.

    Three stable representatives are retained per loading/retrieval domain. This
    is not exhaustive handling CSP search; the limitation is exported.
    """
    moved = []; needs = {n['need_id']: n for n in c['needs']}
    jobs = sorted({t['need_id'] for t in tasks}, key=lambda n: min(t['start_min'] for t in tasks if t['need_id']==n))
    for nid in jobs:
        job = [t for t in tasks if t['need_id'] == nid]
        load = next((o for o in ops if o['need_id'] == nid and o['kind']=='load'), None)
        unload = next((o for o in ops if o['need_id'] == nid and o['kind']=='unload'), None)
        if load is None or unload is None:
            continue  # automatic washer/dryer combo has one handling chain
        n = needs[nid]; start=min(t['start_min'] for t in job); end=max(t['end_min'] for t in job)
        parent_ids = {t.get('depends_on_need_id') for t in job} - {None}
        parent_end = max((o['end_min'] for o in moved if o['need_id'] in parent_ids and o['kind']=='unload'), default=-1e12)
        duration = load['end_min'] - load['start_min']
        left = max(n['release_min'], start - duration - n['maximum_preload_wait_min'], parent_end)
        slots = _slots(c, load, left, start-duration)
        if n['timer_allowed'] is False:
            slots = [t for t in slots if t+duration == start]
        if not slots:
            return None
        pool = representatives(slots, config['quantiles'])
        t = min(slots,key=lambda t:(abs(t-load['start_min']),t)) if choice==3 else pool[min(choice,len(pool)-1)]
        moved.append({**load,'start_min':t,'end_min':t+duration})
        duration = unload['end_min']-unload['start_min']
        slots = _slots(c, unload, end, min(n['deadline_min']-duration, end+n.get('maximum_retrieval_wait_min',180)))
        if not slots:
            return None
        pool = representatives(slots,config['quantiles'])
        t = min(slots,key=lambda t:(abs(t-unload['start_min']),t)) if choice==3 else pool[min(choice,len(pool)-1)]
        moved.append({**unload,'start_min':t,'end_min':t+duration})
    return moved


def _raw_programs(c, d, config):
    for need in c['needs']:
        if need['asset_id'] != d['asset_id'] or need['kind'] not in ('washer','dishwasher','dryer'):
            continue
        nid=need['need_id']; ids=chain_need_ids(c['A'],nid)
        tasks=[t for t in c['A']['tasks'] if t['need_id'] in ids]
        if need['kind']=='dryer' and any(t.get('depends_on_need_id') for t in tasks):
            continue  # dependent drying belongs to the upstream washing unit
        if not tasks or not c['decision_min'] <= min(t['start_min'] for t in tasks) < 1440:
            continue
        ops=[o for o in c['A']['operations'] if o['need_id'] in ids]
        if not ops or min(o['start_min'] for o in ops) < c['decision_min']:
            continue  # underway handling is never rewritten
        first=min(t['start_min'] for t in tasks); finish=max(t['end_min'] for t in tasks)
        # Include one-grid boundary violations as diagnostic requests. The frozen
        # horizon remains a hard materialization bound; no task disappears at 24h.
        left=math.ceil((max(c['decision_min'],need['release_min']-10)-first)/10)*10
        right=math.floor((min(need['deadline_min']+10,c['horizon_min'][1])-finish)/10)*10
        unit=need['kind']+':'+d['asset_id']+':'+nid
        for delta in range(left,right+1,10):
            shifted=[{**t,'start_min':t['start_min']+delta,'end_min':t['end_min']+delta} for t in tasks]
            variants=[('timer_only',ops),('shift_chain',[{**o,'start_min':o['start_min']+delta,'end_min':o['end_min']+delta} for o in ops])]
            for choice in range(4):
                handling=_handling(c,shifted,ops,config,choice)
                if handling is not None:
                    variants.append(('retimed_handling',handling))
            for mechanism,moved in variants:
                if min((o['start_min'] for o in moved),default=c['decision_min']) < c['decision_min']:
                    continue
                if max([t['end_min'] for t in shifted]+[o['end_min'] for o in moved]) > c['horizon_min'][1]:
                    continue
                original={o['operation_id']:o for o in ops}
                manual=[abs(o['start_min']-original[o['operation_id']]['start_min']) for o in moved]
                patches=[{'type':'rows','collection':'tasks','identity':'task_id','rows':shifted},
                         {'type':'rows','collection':'operations','identity':'operation_id','rows':moved}]
                # The ordinary variant domain is constrained by precedence,
                # readiness and timer capability at construction, not by a later
                # success filter. Keep the excluded raw request in its own ledger.
                construction = program_construction_issues(c,shifted,moved)
                yield {'unit':unit,'family':need['kind'],'asset_id':d['asset_id'],'service_need_id':nid,'mechanism':mechanism,
                    'construction_route':'engineering_diagnostic' if construction else 'collection_request',
                    'construction_issues':construction,
                    'branch':'earlier' if delta<0 else 'later','needs':[nid],'patches':patches,
                    'profiles':{'A':_profile(c,tasks),'B':_profile(c,shifted)},
                    'magnitude':{'dose_coordinate':max([abs(delta)]+manual),'machine_shift_min':abs(delta),
                        'signed_machine_shift_min':delta,'manual_total_shift_min':sum(manual),
                        'manual_max_shift_min':max(manual,default=0),
                        'service_slack_min':need['deadline_min']-max(o['end_min'] for o in moved)}}


def _raw_ev(c,d,config):
    groups=defaultdict(list)
    for s in c['reference'].get('ev_charging_steps',[]):
        if c['decision_min'] <= s['start_min'] and s['grid_kWh']>0:
            groups[s['need_id']].append(s)
    for nid,steps in sorted(groups.items()):
        if not any(c['decision_min'] <= s['start_min'] < 1440 for s in steps):
            continue
        controls=[r for r in c['A']['controls'] if r['asset_id']==d['asset_id'] and r['kind']=='ev_charge_window' and r['need_id']==nid]
        if not controls:
            continue
        rating=d['parameters']['charger_kw']; energy=sum(s['grid_kWh'] for s in steps)
        anchor=min(s['start_min'] for s in steps)
        connection_end=c['_original_ev_connection_ends'][(d['asset_id'],nid)]
        end=min(connection_end,c['horizon_min'][1])
        length=math.ceil((energy/rating*60-1e-8)/10)*10
        latest=end-length
        points=representatives(range(anchor+10,latest+1,10),config['quantiles'])
        points += [anchor+10,config['event']['end_min'],latest-10,latest,latest+10]
        for resume in sorted(set(t for t in points if anchor<t<end)):
            remaining=energy; after=[]
            for t in range(resume,end,10):
                if not any(r['start_min']<=t and t+10<=r['end_min'] for r in controls):
                    continue
                amount=min(rating/6,remaining)
                if amount>1e-10:
                    after.append({'asset_id':d['asset_id'],'start_min':t,'end_min':t+10,'power_kw':amount*6})
                    remaining-=amount
                if remaining<=1e-10:
                    break
            yield {'unit':'ev:'+d['asset_id']+':'+nid,'family':'ev','asset_id':d['asset_id'],'service_need_id':nid,
                'mechanism':'ev_defer','branch':'later','needs':[],
                'patches':[{'type':'control_pause','asset_id':d['asset_id'],'kind':'ev_charge_window','need_id':nid,'start_min':anchor,'end_min':resume}],
                'profiles':{'A':[{**s,'asset_id':d['asset_id'],'power_kw':s['grid_kWh']*6} for s in steps],'B':after},
                'outside_case_horizon':remaining>1e-8 and connection_end>end,
                'extra_issues':['CHARGE_EXCEEDS_ORIGINAL_CONNECTION'] if remaining>1e-8 else [],
                'magnitude':{'dose_coordinate':resume-anchor,'pause_min':resume-anchor,
                    'service_slack_min':connection_end-max((s['end_min'] for s in after),default=resume),
                    'observation_slack_min':end-max((s['end_min'] for s in after),default=resume),
                    'original_connection_end_min':connection_end,'materialization_end_min':end,
                    'energy_shortfall_kWh':max(0,remaining),'required_A_grid_kWh':energy,
                    'manual_total_shift_min':0,'manual_max_shift_min':0,
                    'slack_basis':'original_declared_connection_end;observation_limit_is_separate'}}


def _raw_thermal(c,d,config):
    family='ac' if 'ac' in d['types'] else 'water_heater'
    kind='ac_setpoint' if family=='ac' else 'tank_setpoint'
    controls=[r for r in c['A']['controls'] if r['asset_id']==d['asset_id'] and r['kind']==kind]
    event=config['event']; lo=event['start_min']
    if not any(r['start_min']<=lo<r['end_min'] for r in controls):
        return
    if family=='ac' and not any(a<=lo<z for a,z in c['occupancy'].get(d['room_id'],[])):
        return
    for axis in config['ac_axes'] if family=='ac' else ['tank']:
        key=axis+'_setpoint_C' if family=='ac' else 'value_C'
        reference=next(r[key] for r in controls if r['start_min']<=lo<r['end_min'])
        variants=itertools.product(
                config['ac_delta_C'] if family=='ac' else config['tank_delta_C'],
                config['thermal_duration_min'],('aligned','opposing'),('event_setpoint','precondition_and_relax'))
        variants=[(delta,duration,direction,mechanism,lead)
            for delta,duration,direction,mechanism in variants
            for lead in (config['ac_precondition_min'] if family=='ac' and mechanism=='precondition_and_relax'
                         else [config['precondition_min'] if mechanism=='precondition_and_relax' else 0])]
        for delta,duration,direction,mechanism,lead in variants:
            # The v1 state encoding declares a cooling fallback only. Heating
            # event requests are supported; preheating across an inactive state
            # needs its own typed contract and is not silently mislabelled.
            if family=='ac' and axis=='heating' and mechanism=='precondition_and_relax':
                continue
            hi=lo+duration
            if not all(any(r['start_min']<=t and t+10<=r['end_min'] for r in controls) for t in range(lo,hi,10)):
                continue
            if family=='ac' and not all(any(a<=t and t+10<=z for a,z in c['occupancy'].get(d['room_id'],[])) for t in range(lo,hi,10)):
                continue
            change=delta*(1 if axis=='cooling' else -1)*(1 if direction=='aligned' else -1)
            patches=[]
            for r in controls:
                a,z=max(lo,r['start_min']),min(hi,r['end_min'])
                if a<z:
                    values={key:r[key]+change}
                    if axis=='cooling' and 'value_C' in r:
                        values['value_C']=values[key]
                    patches.append({'type':'control_interval','asset_id':d['asset_id'],'kind':kind,'start_min':a,'end_min':z,'values':values})
            if mechanism=='precondition_and_relax':
                start=lo-lead
                if start<c['decision_min'] or not all(any(r['start_min']<=t and t+10<=r['end_min'] for r in controls) for t in range(start,lo,10)):
                    continue
                # Reference is the occupied event service target, not an away
                # setback (e.g. 40C). Actual command deltas are reported too.
                target=reference-change
                values={key:target}
                if axis=='cooling' and any('value_C' in r for r in controls):
                    values['value_C']=target
                patches.insert(0,{'type':'control_interval','asset_id':d['asset_id'],'kind':kind,'start_min':start,'end_min':lo,'values':values})
            max_delta=max(abs(p['values'][key]-r[key]) for p in patches for r in controls
                          if overlap(p['start_min'],p['end_min'],r['start_min'],r['end_min']))
            magnitude={'dose_coordinate':delta,'service_delta_C':delta,'actual_max_command_delta_C':max_delta,
                'duration_min':duration,'precondition_min':lead,
                'axis':axis,'direction':direction,'mode_evidence':'declared_experimental_request_axis;not_observed_equipment_activity',
                'manual_total_shift_min':0,'manual_max_shift_min':0}
            if family=='ac':
                magnitude['ac_intervention']=describe_ac(c,d['asset_id'],patches,axis,event,config['ac_delta_C'])
            yield {'unit':family+':'+d['asset_id']+':'+axis,'family':family,'asset_id':d['asset_id'],
                'mechanism':mechanism,'branch':axis+':'+direction,'needs':[],'patches':patches,'profiles':None,
                'magnitude':magnitude}
        # Explicitly named stop-cooling request, retaining EB's fallback encoding.
        # This interface has no native availability actuator: never claim hard OFF.
        contract=c['reference'].get('ac_control_contract')
        if family=='ac' and axis=='cooling' and contract:
            for duration in config['thermal_duration_min']:
                hi=lo+duration
                if not all(any(r['start_min']<=t and t+10<=r['end_min'] for r in controls) for t in range(lo,hi,10)):
                    continue
                patches=[{'type':'control_interval','asset_id':d['asset_id'],'kind':kind,
                    'start_min':lo,'end_min':hi,'values':{key:contract['cooling_off_fallback_C']}}]
                ac=describe_ac(c,d['asset_id'],patches,axis,event,config['ac_delta_C'])
                yield {'unit':family+':'+d['asset_id']+':'+axis,'family':family,'asset_id':d['asset_id'],
                    'mechanism':'event_cooling_stop_fallback','branch':'cooling:aligned','needs':[],
                    'patches':patches,'profiles':None,'magnitude':{'dose_coordinate':duration,
                        'service_delta_C':None,'duration_min':duration,'precondition_min':0,
                        'actual_max_command_delta_C':max(abs(contract['cooling_off_fallback_C']-r[key]) for r in controls if overlap(lo,hi,r['start_min'],r['end_min'])),
                        'axis':axis,'direction':'aligned','ac_intervention':ac,
                        'manual_total_shift_min':0,'manual_max_shift_min':0}}


def _finish(c,raw,config):
    check,gate,power=issues(c,raw['patches'],raw['needs'])
    if raw.get('outside_case_horizon'):
        gate=sorted(set(gate+['EV_REQUIRES_TAIL_BEYOND_CASE_HORIZON;NOT_DEPARTURE_FAILURE']))
    if gate:
        return {'quarantined':True,'gate_issues':gate,'unit':raw['unit'],
                'patches':raw['patches'],'magnitude':raw['magnitude'],'request_sha256':digest(raw)}
    b=apply(c['A'],raw['patches']); bh=command_hash(b)
    if bh==command_hash(c['A']):
        return None
    check=sorted(set(check+raw.get('extra_issues',[])))
    logic=engineering_issues(c,b,raw['needs'],check+raw.get('construction_issues',[]))
    if logic:
        return {'engineering_diagnostic':True,'engineering_issues':logic,
                'issues':sorted(set(check+logic)),'request':raw,
                'request_sha256':digest(raw),'repaired':False,'replacement_generated':False}
    known=0. if raw['profiles'] is None else event_energy(raw['profiles']['A'],config['event'])-event_energy(raw['profiles']['B'],config['event'])
    row={**raw,'issues':check,'power_status':power['status'],'unknown_thermal_response':raw['profiles'] is None,
         'known_event_reduction_kWh':known,'working_B_sha256':bh,
         'actual_outcomes':None,'human_acceptance':None}
    row['absolute_level']=absolute_level(row)
    row['id']=digest({'binding':c['reference']['binding'],'working_B_sha256':bh})
    return row


def _features(children,check,changed):
    amplitudes=amplitude_axes(children)
    manual=sum(r['magnitude'].get('manual_total_shift_min',0) for r in children)
    directions={r['magnitude']['direction'] for r in children if 'direction' in r['magnitude']}
    slack=min((r['magnitude']['service_slack_min'] for r in children if 'service_slack_min' in r['magnitude']),default=None)
    return {'device_count':str(len(changed)),'intensity':'not_aggregated_use_amplitude_axes',
        'amplitude_axes':sorted(amplitudes),'amplitude_profile':';'.join(sorted(amplitudes)) or 'none',
        'admission':'diagnostic' if check else 'control' if not children else 'plan_valid',
        'event':event_status(sum(r['known_event_reduction_kWh'] for r in children),any(r['unknown_thermal_response'] for r in children)),
        'manual':'unchanged' if manual==0 else 'changed',
        'thermal_direction':next(iter(directions)) if len(directions)==1 else 'mixed' if directions else 'none',
        'service_slack':'unknown_or_not_applicable' if slack is None else 'negative' if slack<0 else 'under_30min' if slack<30 else '30_to_120min' if slack<=120 else 'over_120min',
        'composition':'+'.join(sorted({r['family'] for r in children})) or 'control',
        'mechanisms':sorted({r['mechanism'] for r in children}) or ['control']}


def _request(c,children,config):
    children=sorted(children,key=lambda r:r['id']);patches=[p for r in children for p in r['patches']]
    check,gate,power=issues(c,patches,sorted({n for r in children for n in r['needs']}))
    if gate:
        raise ValueError('COLLECTION_IMMUTABLE_GATE')
    check=sorted(set(check+[i for r in children for i in r.get('extra_issues',[])]))
    # Two requests cannot silently overwrite the same original task or operation.
    identities=[(p['collection'],r[p['identity']]) for p in patches if p['type']=='rows' for r in p['rows']]
    if len(identities)!=len(set(identities)):
        check=sorted(set(check+['OVERLAPPING_PATCH_IDENTITIES']))
    logic=engineering_issues(c,apply(c['A'],patches),
        sorted({n for r in children for n in r['needs']}),check)
    if logic:
        return {'engineering_diagnostic':True,'engineering_issues':logic,
            'issues':sorted(set(check+logic)),'request':{'patches':patches,
                'component_ids':[r['id'] for r in children]},
            'request_sha256':digest([r['id'] for r in children]),
            'repaired':False,'replacement_generated':False}
    relevance=explain(c,children,config['event'])
    if not relevance['passed']:
        return {'relevance_diagnostic':True,'relevance':relevance,
            'request':{'patches':patches,'component_ids':[r['id'] for r in children]},
            'request_sha256':digest([r['id'] for r in children]),
            'repaired':False,'replacement_generated':False}
    changed=set()
    for r in children:
        for p in r['patches']:
            if p['type']=='rows':
                original={x[p['identity']]:x for x in c['A'][p['collection']]}
                changed.update(x['asset_id'] for x in p['rows'] if x!=original[x[p['identity']]])
            else:
                changed.add(p['asset_id'])
    row={'household_id':c['household_id'],'date':c['date'],'case_id':c['case_id'],
        'patches':patches,'component_ids':[r['id'] for r in children],
        'program_needs':sorted({n for r in children for n in r['needs']}),
        'components':[{**{k:copy.deepcopy(r[k]) for k in ('id','unit','asset_id','family','mechanism','absolute_level','relative_level','magnitude','patches')},
                       'event_relevance':copy.deepcopy(relevance['components'][r['id']]),
                       'service_need_id':r.get('service_need_id')} for r in children],
        'event_relevance':relevance,'asset_change_reasons':asset_reasons(c,children,relevance),
        'issues':check,'power_status':power['status'],'features':_features(children,check,changed),
        'changed_assets':sorted(changed),'independent_units':len(children),
        'known_event_reduction_kWh':sum(r['known_event_reduction_kWh'] for r in children),
        'unknown_thermal_response':any(r['unknown_thermal_response'] for r in children),
        'actual_outcomes':None,'human_acceptance':None,'actual_results_used_for_selection':False}
    row['engineering_issues']=[]
    row['working_B_sha256']=command_hash(apply(c['A'],patches))
    row['id']=digest({'binding':c['reference']['binding'],'B':row['working_B_sha256']})
    row['tags']=tags(row);row['near_duplicate_key']=semantic_signature(c,row)
    return row


def presence_subsets(keys,budget):
    """Lazy cardinality round-robin; budget also bounds subset construction."""
    streams={n:iter(itertools.combinations(keys,n)) for n in range(2,len(keys)+1)}
    ordered=[]
    while streams and len(ordered)<budget:
        for n in sorted(list(streams),reverse=True):
            subset=next(streams[n],None)
            if subset is None:del streams[n]
            else:ordered.append(subset)
            if len(ordered)>=budget:break
    return ordered


def generate_day(context,config):
    validate_context(context); before=digest(context); c=working_context(context)
    baseline_needs={t['need_id'] for t in c['A']['tasks'] if c['decision_min']<=t['start_min']<1440}
    baseline_needs={n['need_id'] for n in c['needs'] if n['need_id'] in baseline_needs}
    # A46 lists an automatic combo's dry stage as a separate service need but
    # gives the parent one loading/retrieval chain. Do not demand a fictitious
    # second handling chain; the parent check already includes this same asset.
    automatic_children={nid for nid in baseline_needs if nid.endswith(':dry')
        and any(t['need_id']==nid[:-4] and t['asset_id']==u['asset_id']
                for t in c['A']['tasks'] for u in c['A']['tasks'] if u['need_id']==nid)
        and any(o['need_id']==nid[:-4] and o['kind']=='load' for o in c['A']['operations'])
        and not any(o['need_id']==nid for o in c['A']['operations'])}
    baseline_needs-=automatic_children
    baseline_check,_,_=issues(c,[],baseline_needs)
    baseline_logic=engineering_issues(c,c['A'],baseline_needs,baseline_check)
    if baseline_logic:
        raise ValueError('BASELINE_ENGINEERING_ERROR;A_NOT_MODIFIED:'+','.join(baseline_logic))
    singles={}; gaps=[];evaluated=0;quarantined={};engineering={};unrelated={}
    for d in sorted(c['devices'],key=lambda d:d['asset_id']):
        if not c['authority']['assets'][d['asset_id']]['target_control_authorized']:
            gaps.append({'asset_id':d['asset_id'],'reason':'NOT_AUTHORIZED'});continue
        types=set(d['types'])
        fn=_raw_programs if types&{'washer','dishwasher','dryer'} else _raw_ev if 'ev' in types else _raw_thermal if types&{'ac','water_heater'} else None
        count=0
        for raw in fn(c,d,config) if fn else []:
            evaluated+=1;row=_finish(c,raw,config)
            if row and row.get('quarantined'):
                quarantined.setdefault(row['request_sha256'],row)
                continue
            if row and row.get('engineering_diagnostic'):
                engineering.setdefault(row['request_sha256'],row)
                continue
            if row:
                singles.setdefault(row['id'],row);count+=1
        if not count:
            gaps.append({'asset_id':d['asset_id'],'reason':'DEPENDENCY_ONLY' if types=={'dryer'} else 'NO_REQUEST_IN_DECLARED_DAILY_DOMAIN'})
    atomic=sorted(singles.values(),key=lambda r:r['id']);annotate_doses(atomic,config)
    rows={}
    for r in atomic:
        candidate=_request(c,[r],config)
        if candidate.get('engineering_diagnostic'):
            raise ValueError('ATOMIC_CONSTRUCTION_ADMISSION_MISMATCH')
        if candidate.get('relevance_diagnostic'):
            unrelated.setdefault(candidate['request_sha256'],candidate)
        else:
            rows[candidate['id']]=candidate
    control=_request(c,[],config)
    groups=defaultdict(list)
    for r in atomic:
        groups[r['unit']].append(r)
    domains={}
    for key,group in sorted(groups.items()):
        sub=defaultdict(list)
        for r in group:
            ac=r['magnitude'].get('ac_intervention',{})
            sub[(r['mechanism'],r['absolute_level'],bool(r['issues']),r['branch'],
                 str(bool(direct(c,r,config['event']))),str(ac.get('amplitude_axes',{})))].append(r)
        domain=[]
        for feature,pool in sorted(sub.items()):
            # Dose representatives and event boundary witnesses, not best costs.
            coords=representatives([r['magnitude']['dose_coordinate'] for r in pool],config['quantiles'])
            for x in coords:
                domain.append(min((r for r in pool if r['magnitude']['dose_coordinate']==x),key=lambda r:digest([config['seed'],r['id']])))
        domains[key]=sorted({r['id']:r for r in domain}.values(),key=lambda r:digest([config['seed'],r['id']]))
    root_domains={k:[r for r in v if direct(c,r,config['event'])] for k,v in domains.items()}
    root_domains={k:v for k,v in root_domains.items() if v}
    support_domains={k:[r for r in v if not direct(c,r,config['event'])] for k,v in domains.items()}
    support_domains={k:v for k,v in support_domains.items() if v}
    keys=sorted(root_domains);required_subsets=2**len(keys)-1-len(keys)
    opportunity_ledger=[]
    for d in c['devices']:
        own=[r for r in atomic if r['asset_id']==d['asset_id']]
        roots=[r for r in own if direct(c,r,config['event'])]
        opportunity_ledger.append({'asset_id':d['asset_id'],
            'authorized':c['authority']['assets'][d['asset_id']]['target_control_authorized'],
            'independent_root_units':len({r['unit'] for r in roots}),
            'event_root_requests':len(roots),'outside_event_requests':len(own)-len(roots),
            'outside_event_request_is_independent_opportunity':False,
            'absence_scope':'declared_bounded_daily_domain;not_global_infeasibility'})
        if own and not roots:
            gaps.append({'asset_id':d['asset_id'],'reason':'NO_EVENT_ROOT_IN_DECLARED_DAILY_DOMAIN',
                'outside_event_requests_retained':len(own),'support_requires_specific_constraint_witness':True})
    # Every size gets a turn, then every subset, then further dose combinations.
    # The entire evaluated catalogue (including newly arising joint failures) stays.
    # Separate a bounded search allowance for proved outside-event support.
    # This is a computational allowance, never a requested sample proportion.
    support_budget=config['joint_budget']//4
    root_budget=config['joint_budget']-support_budget
    ordered=presence_subsets(keys,root_budget)
    attempts=0;observed=set();attempted_subsets=set()
    for trial in range(config['joint_trials_per_subset']):
        for subset in ordered:
            if attempts>=root_budget:
                break
            children=[]
            for j,k in enumerate(subset):
                pool=root_domains[k]
                # Reserve two predeclared trials for individually plan-valid
                # components, then include the entire diagnostic domain. This
                # is constraint-directed generation, not success/outcome sampling.
                valid=[r for r in pool if not r['issues']]
                if trial<2 and valid:
                    pool=valid
                children.append(pool[(trial*(j+1)+j)%len(pool)])
            row=_request(c,children,config)
            if row.get('engineering_diagnostic'):
                engineering.setdefault(row['request_sha256'],row)
            elif row.get('relevance_diagnostic'):
                unrelated.setdefault(row['request_sha256'],row)
            else:
                rows.setdefault(row['id'],row)
                observed.add(subset)
            # A structural conflict consumes its scheduled attempt. No retry,
            # alternative children, successful replacement or outcome reroll.
            attempts+=1;attempted_subsets.add(subset)
        if attempts>=root_budget:
            break
    support_attempts=0
    support_pairs=[(a,b) for a in sorted(root_domains) for b in sorted(support_domains) if a!=b]
    for trial in range(config['joint_trials_per_subset']):
        for a,b in support_pairs:
            if support_attempts>=support_budget:break
            children=[root_domains[a][trial%len(root_domains[a])],
                      support_domains[b][trial%len(support_domains[b])]]
            row=_request(c,children,config)
            if row.get('engineering_diagnostic'):
                engineering.setdefault(row['request_sha256'],row)
            elif row.get('relevance_diagnostic'):
                unrelated.setdefault(row['request_sha256'],row)
            else:
                rows.setdefault(row['id'],row)
            support_attempts+=1
        if support_attempts>=support_budget:break
    if digest(context)!=before:
        raise ValueError('COLLECTION_MUTATED_A_INPUT')
    if not rows:
        control['fallback_reason']='no_change_in_declared_construction_domain;not_global_no_opportunity_proof'
        rows[control['id']]=control
    return {'schema':'eb.collection.day.v3','context_sha256':before,'A_commands_sha256':command_hash(context['A']),
        'rows':sorted(rows.values(),key=lambda r:r['id']),'quarantined_requests':list(quarantined.values()),
        'engineering_diagnostics':list(engineering.values()),'control_record':control,
        'relevance_diagnostics':list(unrelated.values()),'relevance_diagnostics_retained':len(unrelated),
        'event_opportunities':opportunity_ledger,
        'engineering_diagnostics_retained':len(engineering),'no_retries_or_replacements':True,
        'gaps':gaps,'evaluated_atomic_requests':evaluated,
        'atomic_unique':len(atomic),'event_root_units':len(root_domains),
        'joint_evaluations':attempts+support_attempts,'joint_root_evaluations':attempts,
        'joint_support_evaluations':support_attempts,
        'support_search_scope':'bounded_one_root_one_support;not_exhaustive_multi_support_closure',
        'joint_subset_required':required_subsets,'joint_subset_observed':len(observed),
        'joint_subset_attempted':len(attempted_subsets),
        'joint_search_status':'eligible_presence_missing;not_infeasibility_proof' if len(observed)<required_subsets else 'eligible_presence_covered;higher_order_doses_not_exhaustive',
        'retimed_handling_search':'three_calendar_quantiles_plus_nearest_A;not_exhaustive_CSP',
        'invalid_retained':sum(bool(r['issues']) for r in rows.values()),
        'physical_status':'not_run','B_outcomes_used':False,'A_input_unchanged':True}
