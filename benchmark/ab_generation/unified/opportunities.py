"""Input-side opportunity specification, independent of candidate construction.

Potential means a mechanism has a plan-side basis, not that an engineering-valid
extension or a physical benefit has been proved. Missing implementation and
bounded search remain distinct from structural impossibility.
"""
import itertools
from pathlib import Path
from collections import Counter
from ..common import read, digest
from .semantics import mechanism

RULES = read(Path(__file__).with_name('DEVICE_RULES.json'))


def overlap(a,z,b,y):
    return max(a,b)<min(z,y)


def declare(c, cfg):
    entries=[];lo,hi=cfg['event']['start_min'],cfg['event']['end_min']
    def add(d,f,n,m,status,reason,axis=None):
        row=dict(asset_id=d['asset_id'],family=f,need_id=n,mechanism=m,axis=axis,
                 status=status,reason=reason,physical_response='not_computed',
                 unit=digest([d['asset_id'],n]),qualification_source='original_authority',
                 proposal_is_not_execution_consent=True)
        row['resource_ids']=sorted({'asset:'+d['asset_id']} |
            {'person:'+o['operator_id'] for o in c['A']['operations'] if n and o['need_id']==n} |
            {'room:'+o['room_id'] for o in c['A']['operations'] if n and o['need_id']==n})
        row['key']=digest([row['unit'],m,axis]);entries.append(row)
    present=set()
    for d in c['devices']:
        types=d.get('types',[d.get('kind')])
        # A combo's automatic dryer stage does not turn it into an independent
        # dryer. JSON/dictionary field order must never select the device family.
        kinds=set(types)&set(RULES['devices'])
        f=d.get('kind') if d.get('kind') in kinds else 'washer' if 'washer' in kinds else next(iter(sorted(kinds)),None)
        if f is None:continue
        present.add(f);ms=RULES['devices'][f]['mechanisms']
        if f in ('washer','dryer','dishwasher'):
            needs=[n for n in c['needs'] if n['asset_id']==d['asset_id'] and n['kind']==f]
            if not needs:
                for m in ms:add(d,f,None,m,'inapplicable','no_declared_service')
            for n in needs:
                nid=n['need_id'];ts=[t for t in c['A']['tasks'] if t['need_id'] in (nid,nid+':dry') and t['asset_id']==d['asset_id']]
                ops=[o for o in c['A']['operations'] if o['need_id']==nid]
                status='potential';reason='original_service_has_event_related_time_path;not_an_extension_proof'
                if not ts:status,reason='unknown','service_or_excerpt_has_no_program_evidence'
                elif min(t['start_min'] for t in ts)<c['decision_min'] or min(t['start_min'] for t in ts)>=1440:
                    status,reason='inapplicable','already_started_or_outside_declared_daily_grammar'
                elif not {'load','unload'}<={o['kind'] for o in ops}:status,reason='unknown','handling_or_boundary_evidence_missing'
                else:
                    end=max(t['end_min'] for t in ts);start=min(t['start_min'] for t in ts)
                    duration=end-start;early=max(c['decision_min'],n['release_min'])
                    latest=min(n['deadline_min']+10,c['horizon_min'][1])-duration
                    if not overlap(start,end,lo,hi) and not (early<hi and latest+duration>lo and early<=latest):
                        status,reason='inapplicable','no_direct_event_interval_in_declared_service_envelope;support_only_if_needed'
                for m in ms:
                    st,why=status,reason
                    if m=='timer_only' and n.get('timer_allowed') is False:
                        st,why='inapplicable','timer_capability_explicitly_absent'
                    elif st=='potential':
                        loads=[o for o in ops if o['kind']=='load'];unloads=[o for o in ops if o['kind']=='unload']
                        can_move=[o['start_min']>=c['decision_min'] and o['operator_id'] not in c.get('authority',{}).get('immutable_operator_ids',[]) and
                            o['operator_id'] in c.get('authority',{}).get('assets',{}).get(o['asset_id'],{}).get('authorized_operator_ids',[]) for o in ops]
                        if m=='shift_chain' and not all(can_move):
                            st,why='inapplicable','chain_shift_would_change_executed_or_unqualified_operation'
                        elif m=='retimed_handling' and not any(can_move):
                            st,why='inapplicable','no_changeable_handling_operation;machine_only_checked_separately'
                        elif m=='timer_only' and len(loads)==len(unloads)==1:
                            first=min(t['start_min'] for t in ts);duration=max(t['end_min'] for t in ts)-first
                            possible=[s for s in range(((max(loads[0]['end_min'],c['decision_min'])+9)//10)*10,unloads[0]['start_min']-duration+1,10)
                                if s!=first and (overlap(first,first+duration,lo,hi) or overlap(s,s+duration,lo,hi))]
                            if not possible:st,why='inapplicable','fixed_handling_has_no_event_related_machine_time_slack'
                    original_status=st;proof=None
                    if st=='potential' and cfg.get('opportunity_bounds')=='precedence_v1':
                        from .service_bounds import event_exclusion
                        proof=event_exclusion(c,nid,cfg['event'])
                        if proof:st,why='inapplicable',proof['reason']
                    add(d,f,nid,m,st,why)
                    if proof:
                        entries[-1]['pre_bound_status']=original_status
                        entries[-1]['independent_input_exclusion']=proof
        elif f in ('ac','water_heater'):
            kind='ac_setpoint' if f=='ac' else 'tank_setpoint'
            rows=[r for r in c['A']['controls'] if r['asset_id']==d['asset_id'] and r['kind']==kind and overlap(r['start_min'],r['end_min'],lo,hi)]
            occupied=f!='ac' or any(overlap(a,z,lo,hi) for a,z in c.get('occupancy',{}).get(d['room_id'],[]))
            for m in ms:
                for axis in (['cooling'] if m=='event_cooling_stop_fallback' else ['cooling','heating']) if f=='ac' else ['tank']:
                    st,why='potential','declared_thermal_control_path;actual_running_state_unknown'
                    if not rows:st,why='unknown','event_control_evidence_missing'
                    elif not occupied:st,why='inapplicable','no_declared_event_room_use_in_current_grammar'
                    elif m=='event_cooling_stop_fallback' and all(r['cooling_setpoint_C']==40 for r in rows):
                        st,why='inapplicable','already_in_declared_cooling_fallback_state'
                    elif m=='event_cooling_stop_fallback' and not c['reference'].get('ac_control_contract'):
                        st,why='unknown','fallback_actuator_semantics_not_declared'
                    elif axis=='heating' and m=='precondition_and_relax' and all(r['heating_setpoint_C']<=5 for r in rows):
                        st,why='inapplicable','inactive_heating_reference_not_defined_for_preconditioning'
                    add(d,f,None,m,st,why,axis)
        else:
            steps=[s for s in c['reference'].get('ev_charging_steps',[]) if s['grid_kWh']>0 and c['decision_min']<=s['start_min']<1440]
            nids=sorted({s['need_id'] for s in steps})
            for nid in nids or [None]:
                status='potential' if nid else 'inapplicable';reason='nominal_charging_demand;response_can_be_zero' if nid else 'no_future_nominal_charging_demand'
                if nid:
                    plugs=[o['end_min'] for o in c['A']['operations'] if o.get('need_id')==nid and o['kind']=='EV_plug']
                    unplugs=[o['start_min'] for o in c['A']['operations'] if o.get('need_id')==nid and o['kind']=='EV_unplug']
                    spans=[(a,z) for a,z in itertools.product(plugs,unplugs) if a<z]
                    spans += [(p['start_min'],p['end_min']) for p in c.get('physical_ev_connections',[]) if p['need_id']==nid]
                    if spans and not any(overlap(a,z,lo,hi) for a,z in spans):status,reason='inapplicable','literal_physical_connection_does_not_overlap_event'
                    elif not spans:status,reason='unknown','physical_connection_endpoint_evidence_missing'
                for m in ms:
                    add(d,f,nid,m,status,reason)
    return dict(schema='eb.input_opportunities.v2',source_context_sha256=digest(c),
                rules_sha256=digest(RULES),entries=entries,
                absent_families=sorted(set(RULES['devices'])-present),
                eligibility_is_not_feasibility=True,physical_truth_claimed=False)


def coverage(ledger, catalogue, selected_ids=()):
    rows=catalogue.get('rows',[]);selected=set(selected_ids);hits={};native=set()
    for values in catalogue.get('native_domains',[]):
        for c in values:
            if c:native.add((c['asset_id'],c.get('service_need_id'),mechanism(c['mechanism']),c.get('magnitude',{}).get('axis')))
    for row in rows:
        keys=set()
        for c in row['components']:
            if c['event_relevance']['role']!='direct_event_request':continue
            keys.add((c['asset_id'],c.get('service_need_id'),mechanism(c['mechanism']),c.get('magnitude',{}).get('axis')))
        hits[row['id']]=keys
    out=[];potential=[]
    for e in ledger['entries']:
        k=(e['asset_id'],e['need_id'],e['mechanism'],e['axis'])
        witnesses=[rid for rid,keys in hits.items() if k in keys]
        gap=None if witnesses else 'structure_inapplicable' if e['status']=='inapplicable' else 'evidence_insufficient' if e['status']=='unknown' else 'search_budget_or_constraints_unresolved' if k in native else 'generation_mechanism_missing_or_unresolved'
        out.append({**e,'candidate_witness_ids':witnesses,'selected_witness_ids':[r for r in witnesses if r in selected],
                    'native_mechanism_present':k in native,'gap':gap})
        if e['status']=='potential':potential.append((e,k))
    interactions=[]
    for strength in (2,3):
        for group in itertools.combinations(potential,strength):
            es=[e for e,k in group]
            if len({e['unit'] for e in es})<strength:continue
            if strength==3 and not any(set(a['resource_ids'])&set(b['resource_ids']) for a,b in itertools.combinations(es,2)):continue
            keys={k for e,k in group};ws=[rid for rid,ks in hits.items() if keys<=ks]
            interactions.append(dict(keys=[e['key'] for e in es],strength=strength,
                eligibility='joint_feasibility_unproved',witness_ids=ws,
                selected_ids=[r for r in ws if r in selected],
                status='feasible_witness' if ws else 'unknown_not_structurally_impossible'))
    return dict(schema='eb.independent_opportunity_coverage.v2',mechanisms=out,interactions=interactions,
                counts=dict(Counter(r['status'] for r in out)),
                potential=len(potential),witnessed=sum(bool(r['candidate_witness_ids']) for r in out if r['status']=='potential'),
                selected=sum(bool(r['selected_witness_ids']) for r in out if r['status']=='potential'),
                denominator_independent_of_generated_catalogue=True,
                actual_response_distribution_observed=False)
