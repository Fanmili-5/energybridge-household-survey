"""Independent six-function and life-revision contract checks."""
from collections import Counter,defaultdict
from itertools import combinations
F=('AC','WM','DR','DW','WH','EV')
K={'AC':'space_ac_available','WM':'washer_available','DR':'dryer_available','DW':'dishwasher_available','WH':'water_heater_available','EV':'home_vehicle_charging'}
MODE={'AC':'bounded_temperature_setpoint','WM':'non_interruptible_whole_cycle','DR':'non_interruptible_whole_cycle','DW':'non_interruptible_whole_cycle','WH':'electric_storage_temperature_and_preheat','EV':'single_contiguous_charge_session'}
ROLE_COUNTS={'A':{4:55,5:55,6:56},'B':{4:66,5:66,6:66},'C':{4:42,5:42,6:41},'D':{4:50,5:50,6:51},'E':{4:52,5:52,6:52},'F':{4:68,5:68,6:68}}
def need(x,msg):
    if not x:raise ValueError(msg)
def overlap(a,b,x,y):return max(a,x)<min(b,y)
def check_revision(c,old):
    h=c['household'];p=c['household_provenance'];ids={m['id'] for m in h['members']};adult={m['id'] for m in h['members'] if m['age_band'][0]>=18};es=h['calendar']['weekly_events'];enabled=h['controlled_function_ids'];ci=h['control_inventory']
    need(c['schema_version']=='household_step1_v7','wrong v7 schema')
    need(h['equipment_before_control_configuration']==old['household']['equipment'],'source reference inventory altered before intervention')
    need(set(ci)==set(F) and len(set(enabled))==len(enabled) and set(enabled)<=set(F),'control universe includes non-target devices')
    need(4<=len(enabled)<=6 and h['controlled_function_count']==len(enabled),'per-household 4-6 control functions')
    need({f for f in ci if ci[f]['enabled']}==set(enabled),'enabled function list mismatch')
    need(h['control_configuration_scope']['background_devices_counted'] is False,'background appliance counted')
    need(h['control_configuration_scope']['physical_model_execution_complete'] is False and h['control_configuration_scope']['layout_and_installation_are_reference_conditions'] is True,'reference design promoted to physical admission')
    if c['benchmark_role'] in 'AB':need('AC' in enabled,'A/B thermal role lacks AC control')
    if c['benchmark_role']=='F':need('EV' in enabled,'F role lacks EV control')
    ledger={x['function']:x for x in h['control_configuration_interventions']}
    for f in F:
        q=h['equipment'][K[f]];a=ci[f];before=old['household']['equipment'][K[f]];raw=c['devices'][K[f]]
        need(a['device_key']==K[f] and q['control_enabled']==a['enabled'],'function/device binding')
        if f not in enabled:
            need(not a['coverage_counted'],'disabled function counted')
            for key,v in before.items():need(q[key]==v,'disabled device modified')
            for key,value in old['household_provenance'].items():
                if key.startswith('equipment.'+K[f]+'.'):need(p[key]==value,'disabled-device source provenance changed')
            continue
        need(q['present'] and q['energy_carrier']=='electricity' and q['control_mode']==MODE[f],'incompatible hardware counted as control coverage')
        need(a['source_presence']==raw and a['source_reference_before']==before,'control evidence/source binding')
        need(a['physical_execution_verified'] is False,'stage1 claims physical execution')
        changed=any(q.get(field)!=before.get(field) for field in ('present','energy_carrier','appliance_type','thermal_storage_model','storage_capacity_litres'))
        if changed:need(f in ledger and ledger[f]['before']==before and ledger[f]['source_fact']==raw and ledger[f]['after']==q,'unlogged reference equipment intervention')
        if not before['present']:need(p['equipment.'+K[f]+'.present']['status']=='benchmark_installed','installed device relabelled source observation')
        if q['energy_carrier']!=before.get('energy_carrier'):need(p['equipment.'+K[f]+'.energy_carrier']['status'] in ('benchmark_assigned','benchmark_intervention'),'fuel replacement relabelled observed')
        if f=='WH':
            need(q['appliance_type']=='reference_electric_storage_water_heater' and q['thermal_storage_model']=='explicit_reference_tank' and q['storage_capacity_litres']>0 and q['reference_heater_kw']>0 and q['storage_shift_eligible'],'gas/instant/undefined heater counted as storage control')
            need(all(p['equipment.'+K[f]+'.'+field]['status']=='benchmark_intervention' for field in ('appliance_type','thermal_storage_model','storage_capacity_litres','reference_heater_kw','storage_shift_eligible')),'reference tank parameters relabelled observed')
    if 'EV' in enabled:
        need(h['ev'].get('vehicle_user_member_id') in adult and h['ev']['controlled'],'EV user and control contract')
        need(h['reference_installation_conditions']['EV_parking_and_charging_access']=='explicit reference accessible parking connection','EV installation lacks reference access')
    assets=defaultdict(list)
    for f in enabled:assets[ci[f]['reference_asset_id']].append(f)
    for asset,fs in assets.items():
        if len(fs)>1:
            need(set(fs)=={'WM','DR'} and any(x['asset_id']==asset and set(x['functions'])=={'WM','DR'} and x['max_parallel_functions']==1 and x['precedence']=='wash_before_dry' for x in h['shared_control_asset_constraints']),'shared washer/dryer asset constraint missing')
    relation=c.get('care_context',{}).get('value')
    if relation:
        a=next(m['id'] for m in h['members'] if m.get('source_person_key')==relation['adult_caregiver_key']);child=next(m['id'] for m in h['members'] if m.get('source_person_key')==relation['child_key'])
        need(any(x['caregiver_id']==a and x['child_id']==child and x['scope']=='source_last_week' for x in h['observed_care_links']),'observed care link not propagated for this role')
        need(any(x['caregiver_id']==a and x['child_id']==child and x['source_care_link'] for x in h['care_arrangements']),'source care label missing outside E')
        need(p['care.observed_links']['status']==c['care_context']['status'],'source care provenance lost')
    for e in es:
        if e['kind']=='escort':
            need(e['required_turnaround_buffer_minutes']>=15 and e['preparation_interval']==[e['start']-15,e['start']] and e['settling_interval']==[e['end'],e['end']+15],'missing handoff buffer')
            for other in es:
                if other is e or other['member_id']!=e['member_id']:continue
                if other['location']=='away' or other['kind'] in ('work','study','bathing'):
                    need(not overlap(e['start']-15,e['end']+15,other['start'],other['end']),'handoff buffer overlaps another commitment')
            for d in h['routine']['daily_services']:
                for meal in d['meals']:
                    if e['member_id'] in meal['participants']:need(not overlap(e['start']-15,e['end']+15,d['day']*1440+meal['start'],d['day']*1440+meal['end']),'meal in handoff buffer')
        if e['kind']=='family_outing':
            need(5*1440<=e['start']<e['end']<=7*1440 and e['experimental'],'weekend outing provenance/bounds')
            need(e['member_id'] in e['participants'] and set(e['supervising_adult_ids'])<=adult and bool(e['supervising_adult_ids']),'family outing lacks supervising adult')
            for mid in e['participants']:need(any(z['member_id']==mid and z.get('group_id')==e['group_id'] and z['start']==e['start'] and z['end']==e['end'] for z in es),'family outing cohort not jointly present')
    bp=h['question_coverage_blueprint'];need(len(bp['slots'])==10 and not bp['actual_questions_generated'],'coverage blueprint treated as generated questionnaire')
    exposure=Counter(f for x in bp['slots'] for f in x['focus_functions'])
    need(set(exposure)==set(enabled) and min(exposure.values())>=2,'planned function exposure missing')
    need(sum(x['kind']=='single_function' for x in bp['slots'])==len(enabled),'single-function diagnostic slots missing')
    need(sum(x['kind']=='joint_function' for x in bp['slots'])==10-len(enabled),'joint-function slots missing')
    return True
def check_population(rows):
    byrole=defaultdict(list);bycountry=defaultdict(list)
    for c in rows:byrole[c['benchmark_role']].append(c);bycountry[c['source']['country']].append(c)
    patterns=[tuple(x) for k in (4,5,6) for x in combinations(F,k)];result={'by_role':{},'by_country':{}}
    for role,cs in byrole.items():
        counts=Counter(c['household']['controlled_function_count'] for c in cs);need(dict(counts)==ROLE_COUNTS[role],'role control-cardinality quota')
        actual=Counter(tuple(c['household']['controlled_function_ids']) for c in cs)
        feasible=[x for x in patterns if (role not in 'AB' or 'AC' in x) and (role!='F' or 'EV' in x)]
        need(all(actual[x]>=2 for x in feasible),'feasible role inventory pattern coverage')
        single=Counter();pairs=Counter()
        for c in cs:
            fs=c['household']['controlled_function_ids']
            if len(fs)<6:single.update(fs);pairs.update(combinations(fs,2))
        need(all(single[f]>=20 for f in F),'non-full single-function coverage')
        need(all(pairs[x]>=10 for x in combinations(F,2)),'non-full pair-function coverage')
        allowed_states={(pair,tuple(int(f in mask) for f in pair)) for mask in feasible for pair in combinations(F,2)}
        measured_states=Counter((pair,tuple(int(f in c['household']['controlled_function_ids']) for f in pair)) for c in cs for pair in combinations(F,2))
        need(all(measured_states[x]>=2 for x in allowed_states),'role binary pair-state coverage')
        result['by_role'][role]={'cardinality_counts':dict(counts),'feasible_patterns':len(feasible),'covered_patterns':sum(actual[x]>=2 for x in feasible),'minimum_pattern_count':min(actual[x] for x in feasible),'non_full_single_min':min(single[f] for f in F),'non_full_pair_min':min(pairs[x] for x in combinations(F,2)),'allowed_binary_pair_states':len(allowed_states),'covered_binary_pair_states':sum(measured_states[x]>=2 for x in allowed_states)}
    for co,cs in bycountry.items():
        actual=Counter(tuple(c['household']['controlled_function_ids']) for c in cs)
        need(all(actual[x]>=1 for x in patterns),'country inventory pattern coverage')
        states=Counter((pair,tuple(int(f in c['household']['controlled_function_ids']) for f in pair)) for c in cs for pair in combinations(F,2))
        need(all(states[(pair,state)]>=1 for pair in combinations(F,2) for state in ((0,0),(0,1),(1,0),(1,1))),'country binary pair-state coverage')
        need({c['household']['controlled_function_count'] for c in cs}=={4,5,6},'country control-cardinality coverage')
        result['by_country'][co]={'households':len(cs),'patterns_covered':sum(actual[x]>=1 for x in patterns),'patterns_total':22,'full_pattern_requirement':True,'binary_pair_states_covered':sum(states[(pair,state)]>0 for pair in combinations(F,2) for state in ((0,0),(0,1),(1,0),(1,1))),'binary_pair_states_total':60,'GB_limit':None}
    matched=defaultdict(list)
    for c in rows:
        if 'cd_pair_id' in c:matched[c['cd_pair_id']].append(c)
    need(len(matched)==125 and all(len(v)==2 and v[0]['household']['controlled_function_ids']==v[1]['household']['controlled_function_ids'] for v in matched.values()),'C/D source pair control sets diverge')
    result['paired_cd_control_sets_equal']=125
    no_away=sum(not any(e['location']=='away' and max(e['start'],7200)<min(e['end'],10080) for e in c['household']['calendar']['weekly_events']) for c in rows)
    need(no_away<=400,'weekend still dominated by full-home default')
    strata=Counter(c['household']['weekend_design']['requested_stratum'] for c in rows);need(len(strata)==4 and min(strata.values())>=200,'weekend coverage strata missing')
    result.update(weekend_no_away_households=no_away,weekend_requested_strata=dict(strata),configured_not_realized_questionnaire_coverage=True)
    return result
