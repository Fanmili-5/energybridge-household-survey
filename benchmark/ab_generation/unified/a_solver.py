"""Life-only demand compilation and joint CP-SAT scheduling. No VPP input.

Legacy validation/calendars/thermal policies/mobility facts are reused. Textile
requirements are compiled independently of whether an earlier scheduler served
them, preventing a greedy failure from duplicating future inventory demands.
"""
import copy
import datetime as dt
import math
from collections import defaultdict
from ortools.sat.python import cp_model
from ..common import digest
from .. import life
from ..energy import batch_energy
from .contract import stream
from .automatic_programs import hardware,legacy_view,bind_reference_contract
from .input_boundaries import require_no_downstream_fields


def dated_targets(portrait, anchor):
    out={};by_day=defaultdict(set)
    for d in portrait.get('joint_sampling',{}).get('devices',[]):
        for row in d.get('time_preference',{}).get('per_service',[]):
            if row.get('preferred_start_min') is not None:
                date=row['source_date']
                base=(dt.date.fromisoformat(date)-dt.date.fromisoformat(anchor)).days*1440
                out[(d['asset_id'],date,row.get('need_id'))]=base+row['preferred_start_min']
                by_day[(d['asset_id'],date)].add(base+row['preferred_start_min'])
    for (aid,date),values in by_day.items():
        if len(values)==1:out[(aid,date,None)]=next(iter(values))
    return out


def target_ledger(problem,portrait,feasible):
    targets=dated_targets(portrait,problem['anchor']);rows=[]
    for d in portrait.get('joint_sampling',{}).get('devices',[]):
        for r in d.get('time_preference',{}).get('per_service',[]):
            key=(d['asset_id'],r.get('source_date'),r.get('need_id'))
            exact=[j for j in problem['jobs'] if (j['asset_id'],j['date'],j['need_id'])==key]
            matches=exact or [j for j in problem['jobs'] if (j['asset_id'],j['date'])==key[:2] and key[:2]+(None,) in targets]
            status='missing_target' if r.get('preferred_start_min') is None else 'not_connected' if not matches else 'consumed_by_supported_A_target' if feasible else 'solver_unresolved_or_infeasible'
            if matches and any(j.get('automatic_parent_need_id') for j in matches) and r.get('preferred_start_min') is not None:
                status='independent_target_not_applied_to_automatic_phase'
            rows.append(dict(asset_id=key[0],source_date=key[1],need_id=key[2],preferred_start_min=r.get('preferred_start_min'),
                matched_need_ids=[j['need_id'] for j in matches],mapping='exact_service' if exact else 'unambiguous_day_level' if matches else None,
                status=status,reason=None if status=='consumed_by_supported_A_target' else
                'fixed_automatic_sequence_uses_parent_start_plus_wash_duration' if status=='independent_target_not_applied_to_automatic_phase' else
                'missing_source_target' if status=='missing_target' else 'no_supported_service_in_declared_horizon;not_clock_folded' if not matches else 'no_feasible_schedule_witness'))
    return rows


def compile_life(spec, world):
    # This call validates the complete existing input contract; its A is returned
    # ONLY as the unchanged comparison arm and never supplies habit parameters.
    original_world_sha256=digest(world);capability_binding=None
    declared_contract=spec.get('provenance',{}).get('program_capability_contract')
    if declared_contract:
        world,capability_binding=bind_reference_contract(world,declared_contract)
    local_spec,local_world,automatic=legacy_view(spec,world)
    legacy=life.generate_household(local_spec,local_world)
    days=legacy['days'];assets={d['asset_id']:d for d in world['devices']}
    roots=[p for p in spec['program_policies'] if p['trigger']!='after_service']
    children=[p for p in spec['program_policies'] if p['trigger']=='after_service']
    inventory={p['service_id']:p['initial_inventory_kg'] for p in roots if p['trigger']=='textile'}
    jobs=[]
    for date,day in days.items():
        base=day['base_min'];daytype='weekend' if dt.date.fromisoformat(date).weekday()>=5 else 'weekday'
        for p in roots:
            eligible={m['member_id'] for m in world['members'] if m['household_id'] in assets[p['asset_id']]['using_household_ids']}
            if p['trigger']=='textile':
                inventory[p['service_id']]+=p['daily_quantity_kg'];available=inventory[p['service_id']]
                if not p['daily_service'] and available<p['capacity_kg']:continue
                arrivals=[e['start_min'] for mid,cal in day['calendars'].items() if mid in eligible
                    for prior,e in zip(cal,cal[1:]) if prior['location']=='away' and e['location']=='home']
                release=base+(max(arrivals) if arrivals else p['no_arrival_release_min'])
                count=math.ceil(available/p['capacity_kg']) if p['daily_service'] else math.floor((available+1e-9)/p['capacity_kg'])
                quantities=[min(p['capacity_kg'],max(0,available-i*p['capacity_kg'])) for i in range(count)]
            else:
                meals=[t for mid,t in day['meal_end_min_by_member'].items() if mid in eligible]
                if not meals:continue
                release=base+max(meals);quantities=[len(meals)]
            for index,quantity in enumerate(quantities):
                nid=date+':'+p['service_id']+':'+str(index)
                for policy in [p]+[c for c in children if c['upstream_service_id']==p['service_id']]:
                    child=policy is not p
                    auto_child=child and policy is automatic.get(p['service_id'])
                    n=dict(need_id=nid+(':dry' if auto_child else ':'+policy['service_id'] if child else ''),date=date,
                        asset_id=policy['asset_id'],kind=policy['kind'],release_min=release,
                        deadline_min=release+policy['deadline_after_release_min'],quantity=quantity,
                        batch_capacity_kg=p.get('capacity_kg'),unit='kg' if p['trigger']=='textile' else 'declared_dinner_participants',
                        preferred_start_min=base+policy['preferred_start_min'][daytype],
                        policy=copy.deepcopy(policy),origin='independent_life_inventory_compiler')
                    if auto_child:
                        n['automatic_parent_need_id']=nid
                        n['source_service_id']=policy['service_id']
                        n['automatic_policy_interpretation']=dict(
                            preferred_start_min='derived_parent_start_plus_wash_duration;not_independent_target',
                            maximum_preload_wait_min='not_applicable;no_manual_transfer',
                            timer_allowed='phase_starts_automatically;primary_timer_rule_retained',
                            maximum_retrieval_wait_min='hard_limit_after_final_phase')
                    elif child:n['depends_on_need_id']=nid
                    elif p['service_id'] in automatic:
                        n['automatic_child_need_id']=nid+':dry'
                        n['automatic_tail_duration_min']=automatic[p['service_id']]['duration_min']
                    jobs.append(n)
                if p['trigger']=='textile':inventory[p['service_id']]-=quantity
    return dict(schema='eb.unified.life_problem.v1',household_id=spec['household_id'],
        anchor=spec['anchor'],end_exclusive=spec['end_exclusive'],days=days,jobs=jobs,
        world=copy.deepcopy(world),fixed_operations=[o for o in legacy['A']['operations'] if o['kind'].startswith('EV_')],
        controls=copy.deepcopy(legacy['A']['controls']),EV=copy.deepcopy(legacy['EV']),
        source_spec_sha256=digest(spec),source_world_sha256=original_world_sha256,legacy_comparator=legacy if not automatic else None,
        input_lineage=dict(program_jobs='original_inventory_and_meals;independent_of_greedy_service_success',
            days='original_member_calendars',fixed_EV_operations='original_mobility_connection_actions',
            EV='original_mobility_and_nominal_battery_compiler;not_program_schedule',
            thermal_controls='original_thermostat_policies;not_B_or_physical_observations',
            nonprogram_requirements='original_bath_mobility_requirements'),
        thermostat_policies=copy.deepcopy(spec['thermostat_policies']),
        nonprogram_requirements=copy.deepcopy([n for n in legacy['requirements'] if n['kind'] not in ('washer','dryer','dishwasher')]),
        remaining_unallocated_textile_kg=inventory,
        **(dict(automatic_input_contract='explicit_automatic_programs;one_asset_one_handling_chain',
                legacy_comparator_status='unavailable_for_automatic_input;partial_legacy_program_A_not_used',
                automatic_service_ids=sorted(automatic)) if automatic else {}),
        **(dict(automatic_capability_binding=capability_binding) if capability_binding is not None else {}))


def solve(problem, portrait=None, *, seed=0, deterministic_time=20, target_mode='frozen_v3'):
    require_no_downstream_fields(problem,'A_PROBLEM')
    require_no_downstream_fields(portrait,'A_PORTRAIT')
    if set(problem)&{'events','tariff','B','human_answers','acceptance'}:
        raise ValueError('DOWNSTREAM_INFORMATION_IN_A_PROBLEM')
    portrait=portrait or {};p=copy.deepcopy(problem);model=cp_model.CpModel()
    world=p['world'];assets={d['asset_id']:d for d in world['devices']};members={m['member_id']:m for m in world['members']}
    limit=len(p['days'])*1440; horizon=limit//10
    pref={d['asset_id']:d for d in portrait.get('joint_sampling',{}).get('devices',[])}
    targets=dated_targets(portrait,p['anchor']);target_context=None
    if target_mode!='frozen_v3':
        from .dated_target_context import VERSION,derive
        if target_mode!=VERSION:raise ValueError('UNKNOWN_A_TARGET_CONTEXT_MODE')
        target_context=derive(p,portrait)
        for r in target_context['rows']:
            if r['target_min'] is not None:
                targets[(r['asset_id'],r['source_date'],r['need_id'])]=r['target_min']
    person=defaultdict(list);rooms=defaultdict(list);machine=defaultdict(list)
    power_intervals=[];power_W=[];variables={};costs=[];causes=[];assumptions={}
    for o in p['fixed_operations']:
        iv=model.new_fixed_size_interval_var(o['start_min']//10,(o['end_min']-o['start_min'])//10,o['operation_id'])
        person[o['operator_id']].append(iv)
    if any(f['reason'].startswith(('NO_REAL_EV_','INVALID_EV_')) for f in p['EV']['failures']):
        model.add(0==1)
    def available(aid, role):
        d=assets[aid];rows=[]
        # Baseline allocation among explicitly qualified resident operators is
        # an experimental scheduling decision, never execution consent for B.
        # External helpers need an explicit normal assignment, not just ability.
        candidates=[m for m in members.values() if aid in m['can_operate_asset_ids'] and m['household_id'] in d['using_household_ids']]
        registered=d.get('operator_id')
        declared=d.get('normal_operator_ids')
        candidates=[m for m in candidates if m['member_id']==registered] if registered else candidates
        if declared is not None:candidates=[m for m in candidates if m['member_id'] in declared]
        if not registered and declared is None:
            external=[m for m in candidates if m['household_id']!=p['household_id']]
            candidates=[m for m in candidates if m['household_id']==p['household_id']]
            if external and not candidates:causes.append(dict(asset_id=aid,reason='EXTERNAL_HELPER_ASSIGNMENT_NOT_DECLARED'))
        for mid,m in enumerate(sorted(candidates,key=lambda x:x['member_id'])):
            for day in p['days'].values():
                for a,z in day['operator_windows'].get(m['member_id'],[]):
                    for t in range(a,z,10):
                        if t+10<=z and not any(r['room_id']==d['room_id'] and
                            day['base_min']+r['start_min']<t+10 and day['base_min']+r['end_min']>t for r in day['reservations']):
                            rows.append((t//10,m['member_id']))
        return rows
    for j in p['jobs']:
        nid=j['need_id'];aid=j['asset_id'];policy=j['policy'];duration=policy['duration_min']//10
        automatic_parent=j.get('automatic_parent_need_id')
        if automatic_parent:
            if automatic_parent not in variables:raise ValueError('AUTOMATIC_PARENT_NOT_COMPILED_FIRST')
            parent,load,parent_start,unload,li,ui,ids,*_=variables[automatic_parent]
            if parent['asset_id']!=aid or parent.get('automatic_child_need_id')!=nid:
                raise ValueError('AUTOMATIC_PHASE_ASSET_OR_ID_MISMATCH')
            s=model.new_int_var(0,horizon,nid+':start')
            model.add(s==parent_start+parent['policy']['duration_min']//10)
            model.add(s*10>=j['release_min']);model.add((unload+1)*10<=min(limit,j['deadline_min']))
            model.add(unload-s-duration<=policy['maximum_retrieval_wait_min']//10)
            starts=[t for t in range(horizon-duration+1) if all(
                any(a<=q%1440 and q%1440+10<=z for a,z in policy['machine_windows_min'])
                for q in range(t*10,(t+duration)*10,10))]
            if not starts:model.add(0==1)
            else:model.add_linear_expression_in_domain(s,cp_model.Domain.from_values(starts))
            hp=hardware(assets[aid],j['kind']);energy=batch_energy(j,policy,hp)
            watts=math.ceil(energy.get('power_kw',hp['power_kw'])*1000-1e-8)
            power_intervals.append(model.new_fixed_size_interval_var(s,duration,nid+':power'));power_W.append(watts)
            parent_target=variables[automatic_parent][8]
            target=parent_target+parent['policy']['duration_min']
            variables[nid]=(j,load,s,unload,li,ui,ids,energy,target,0,0)
            continue
        slots=available(aid,'handling'); ids=sorted({m for _,m in slots});indices={m:i for i,m in enumerate(ids)}
        release=j['release_min']//10;deadline=min(limit,j['deadline_min'])//10
        l=model.new_int_var(0,horizon,nid+':load');s=model.new_int_var(0,horizon,nid+':start');u=model.new_int_var(0,horizon,nid+':unload')
        li=model.new_int_var(0,max(0,len(ids)-1),nid+':loader');ui=model.new_int_var(0,max(0,len(ids)-1),nid+':retriever')
        assumption=model.new_bool_var(nid+':required');model.add_assumption(assumption);assumptions[assumption.index]=nid
        loadrows=[(t,indices[m]) for t,m in slots if release<=t and t+1<=deadline]
        if not loadrows:model.add(assumption==0)
        else:
            model.add_allowed_assignments([l,li],loadrows).only_enforce_if(assumption)
            model.add_allowed_assignments([u,ui],loadrows).only_enforce_if(assumption)
        starts=[t for t in range(max(0,release+1),max(0,deadline-duration)) if all(
            any(a<=q%1440 and q%1440+10<=z for a,z in policy['machine_windows_min'])
            for q in range(t*10,(t+duration)*10,10))]
        if not starts:model.add(assumption==0)
        else:model.add_linear_expression_in_domain(s,cp_model.Domain.from_values(starts)).only_enforce_if(assumption)
        tail=j.get('automatic_tail_duration_min',0)//10
        for relation in [l>=release,l+1<=s,u>=s+duration+tail,u+1<=deadline,
                         s-l-1<=policy['maximum_preload_wait_min']//10,u-s-duration-tail<=policy['maximum_retrieval_wait_min']//10]:
            model.add(relation).only_enforce_if(assumption)
        if not policy['timer_allowed']:model.add(s==l+1).only_enforce_if(assumption)
        for name,t,opid in [('load',l,li),('unload',u,ui)]:
            iv=model.new_fixed_size_interval_var(t,1,nid+':'+name);rooms[assets[aid]['room_id']].append(iv)
            for mid,i in indices.items():
                b=model.new_bool_var(nid+name+mid);model.add(opid==i).only_enforce_if(b);model.add(opid!=i).only_enforce_if(b.Not())
                person[mid].append(model.new_optional_fixed_size_interval_var(t,1,b,nid+name+mid))
        size=model.new_int_var(1,horizon+1,nid+':hold_size');model.add(size==u+1-l)
        machine[aid].append(model.new_interval_var(l,size,u+1,nid+':hold'))
        hp=hardware(assets[aid],j['kind']);energy=batch_energy(j,policy,hp)
        watts=math.ceil(energy.get('power_kw',hp['power_kw'])*1000-1e-8)
        power_intervals.append(model.new_fixed_size_interval_var(s,duration,nid+':power'));power_W.append(watts)
        # Preserve dates/offsets; never reduce a next-day target modulo 24h.
        target=targets.get((aid,j['date'],nid),targets.get((aid,j['date'],None),j['preferred_start_min']))
        dev=model.new_int_var(0,horizon*4,nid+':target_deviation');model.add_abs_equality(dev,s-target//10)
        pl=model.new_int_var(0,horizon,nid+':preload');rt=model.new_int_var(0,horizon,nid+':retrieval')
        model.add(pl==s-l-1);model.add(rt==u-s-duration-tail)
        coords=pref.get(aid,{}).get('coordinates',{})
        mw=1+round(9*coords.get('routine_stability',0.5));hw=1+round(9*coords.get('manual_burden',0.5))
        denom=max(1,deadline-release);count=sum(x['asset_id']==aid and not x.get('automatic_parent_need_id') for x in p['jobs'])
        norm=max(1,round(1000000/denom/max(1,count)))
        costs.extend([norm*mw*dev,norm*hw*pl,norm*hw*rt])
        variables[nid]=(j,l,s,u,li,ui,ids,energy,target,mw,hw)
    for nid,(j,l,*_) in variables.items():
        parent=j.get('depends_on_need_id')
        if parent:model.add(l>=variables[parent][3]+1)
    # EV charging is optimized jointly with program power, on fixed connections.
    evdevice=next((d for d in world['devices'] if d['kind']=='ev'),None);evvars=[];evstates=[]
    if evdevice:
        ep=evdevice['parameters'];scale=1000000
        state=[model.new_int_var(0,round(ep['capacity_kwh']*scale),'EV_energy:'+str(t)) for t in range(horizon+1)]
        model.add(state[0]==round(ep['initial_energy_kwh']*scale));target=round(ep['target_soc']*ep['capacity_kwh']*scale)
        trips={x['absolute_departure_min']//10:x for x in p['EV']['journeys']}
        for t in range(horizon):
            connected=any(c['start_min']<=t*10 and (t+1)*10<=c['end_min'] for c in p['EV']['connections'])
            b=model.new_bool_var('EV_charge:'+str(t));evvars.append(b)
            if not connected:model.add(b==0)
            used=round(trips[t]['traction_kWh']*scale) if t in trips else 0
            if t in trips:
                model.add(state[t]>=target);model.add(state[t]-used>=round(ep['minimum_soc']*ep['capacity_kwh']*scale))
            charge=round(ep['charger_kw']*ep['efficiency']/6*scale)
            room=model.new_int_var(0,round(ep['capacity_kwh']*scale),'EV_room:'+str(t))
            model.add_max_equality(room,[0,target-state[t]+used])
            inc=model.new_int_var(0,charge,'EV_increment:'+str(t));model.add_min_equality(inc,[charge*b,room])
            model.add(state[t+1]==state[t]-used+inc)
            power_intervals.append(model.new_optional_fixed_size_interval_var(t,1,b,'EV_power:'+str(t)));power_W.append(math.ceil(ep['charger_kw']*1000))
            costs.append((t+1)*b) # Earlier readiness; not VPP/tariff aware.
        evstates=state
    for groups in (person,rooms,machine):
        for intervals in groups.values():model.add_no_overlap(intervals)
    supply=world.get('electrical',{}).get('supply_W')
    if supply:model.add_cumulative(power_intervals,power_W,math.floor(supply))
    model.minimize(sum(costs))
    solver=cp_model.CpSolver();solver.parameters.num_search_workers=1
    solver.parameters.random_seed=stream(seed,'A',p['household_id']);solver.parameters.max_deterministic_time=deterministic_time
    status=solver.solve(model);name=solver.status_name(status)
    result=dict(schema='eb.unified.A.v1',household_id=p['household_id'],solver_status=name,
        input_sha256=digest({k:v for k,v in p.items() if k!='legacy_comparator'}),portrait_sha256=digest(portrait),
        events_prices_B_or_answers_used=False,physical_status='not_computed',A=None,service_ledger=[],causes=causes,
        operator_allocation_basis='explicit_normal_assignment_else_qualified_residents;experimental_baseline_allocation;not_B_consent',
        objective_weights_origin='experimental_separate_routine_and_handling_coordinates;per_service_normalization')
    result['preference_target_ledger']=target_ledger(p,portrait,status in (cp_model.FEASIBLE,cp_model.OPTIMAL))
    result['input_lineage']=p.get('input_lineage',{})
    if target_context is not None:
        result['conditional_target_context']=target_context
        result['conditional_target_mode']=target_mode
    if status not in (cp_model.FEASIBLE,cp_model.OPTIMAL):
        result['status']='infeasible' if status==cp_model.INFEASIBLE and not causes else 'unknown'
        result['unsat_core']=[assumptions.get(i,str(i)) for i in solver.sufficient_assumptions_for_infeasibility()] if status==cp_model.INFEASIBLE else []
        return result
    tasks=[];ops=[]
    for nid,(j,l,s,u,li,ui,ids,energy,target,mw,hw) in variables.items():
        a,z,load,unload=solver.value(s)*10,(solver.value(s)+j['policy']['duration_min']//10)*10,solver.value(l)*10,solver.value(u)*10
        task_energy=energy or (dict(power_kw=hardware(assets[j['asset_id']],j['kind'])['power_kw'])
                              if j.get('automatic_parent_need_id') or j.get('automatic_child_need_id') else {})
        tasks.append(dict(task_id=nid,need_id=nid,asset_id=j['asset_id'],kind=j['kind'],start_min=a,end_min=z,**task_energy,
            **({'depends_on_need_id':j['depends_on_need_id']} if j.get('depends_on_need_id') else {})))
        for kind,t,mid in ([] if j.get('automatic_parent_need_id') else [('load',load,ids[solver.value(li)]),('unload',unload,ids[solver.value(ui)])]):
            ops.append(dict(operation_id=nid+':'+kind,need_id=nid,asset_id=j['asset_id'],operator_id=mid,
                room_id=assets[j['asset_id']]['room_id'],kind=kind,start_min=t,end_min=t+10,duration_min=10))
        result['service_ledger'].append(dict(need_id=nid,target_min=target,actual_start_min=a,
            deviation_min=a-target,preload_wait_min=None if j.get('automatic_parent_need_id') else a-load-10,
            retrieval_wait_min=None if j.get('automatic_parent_need_id') else unload-z-j.get('automatic_tail_duration_min',0),
            machine_weight=mw,handling_weight=hw,target_realized=a==target,
            deviation_reason=None if a==target else 'joint_resource_and_preference_objective;not_a_proof_that_target_alone_is_infeasible',
            **(dict(automatic_parent_need_id=j['automatic_parent_need_id'],target_origin='parent_target_plus_fixed_wash_duration;not_independent_draw',
                    own_handling=False,independent_preference_weight=False) if j.get('automatic_parent_need_id') else {})))
    controls=[r for r in p['controls'] if r['kind']!='ev_charge_window'];steps=[];thermal_preferences=[]
    policies={x['asset_id']:x for x in p.get('thermostat_policies',[])}
    for row in controls:
        if row['kind']!='ac_setpoint':continue
        wanted=pref.get(row['asset_id'],{}).get('cooling_preferred_C');policy=policies.get(row['asset_id'])
        if wanted is None or policy is None or row['cooling_setpoint_C']!=policy['cooling_setpoint_C']:continue
        if row['heating_setpoint_C']+row.get('heating_and_cooling_deadband_C',0)<=wanted<=40 and wanted>=15:
            row['cooling_setpoint_C']=wanted
            if 'value_C' in row:row['value_C']=wanted
            thermal_preferences.append(dict(asset_id=row['asset_id'],cooling_preference_used_C=wanted,
                actual_room_temperature=None,heating_preference_used=False))
    if evdevice:
        for t,b in enumerate(evvars):
            if not solver.value(b):continue
            connection=next(c for c in p['EV']['connections'] if c['start_min']<=t*10<(t+1)*10<=c['end_min'])
            before=solver.value(evstates[t]);after=solver.value(evstates[t+1]);amount=(after-before)/1000000
            if amount<=0:continue
            controls.append(dict(asset_id=evdevice['asset_id'],kind='ev_charge_window',need_id=connection['need_id'],
                start_min=t*10,end_min=(t+1)*10,stop_at_target_soc=evdevice['parameters']['target_soc'],
                _unified_id=connection['need_id']+':charge:'+str(t)))
            steps.append(dict(need_id=connection['need_id'],start_min=t*10,end_min=(t+1)*10,
                grid_kWh=amount/evdevice['parameters']['efficiency']))
    result.update(status='feasible',A=dict(tasks=tasks,operations=sorted(ops+p['fixed_operations'],key=lambda x:x['start_min']),
        controls=sorted(controls,key=lambda r:(r['asset_id'],r['start_min']))),ev_charging_steps=steps,
        physical_ev_connections=copy.deepcopy(p['EV']['connections']),
        optimal=status==cp_model.OPTIMAL,objective=solver.objective_value,best_bound=solver.best_objective_bound)
    result['thermal_preference_mapping']=thermal_preferences
    result['context_only_preferences']=['water_heater','ev_adjustment_consent','unknown_heating_or_off_preferences']
    result['thermal_service_status']='required_but_not_physically_computed'
    return result
