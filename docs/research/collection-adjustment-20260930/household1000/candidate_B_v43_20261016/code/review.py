"""Independent readback: lineage, actual commands, retained failures, subset parity."""
import collections
from common import *
from assess import assess,integrity
from temporal import event_relations
from event_proposals import tank_description
from proposals import command_signature
from events import for_case,response_reference

def independent_signals(p):
    for aid,signal in p['HVAC_signals_B'].items():
        if set(map(len,signal.values()))!={576}:return False
        commands=[x for x in p['B']['controls']if x['kind']=='ac_setpoint'and x['asset_id']==aid]
        for i in range(576):
            t=-1440+i*10;active=[x for x in commands if x['start_min']<=t<x['end_min']]
            if len(active)>1:return False
            c=active[0]if active else None
            expected={'available':int(c is not None),'fan_mode':c.get('fan_operating_mode',0)if c else 0,'heat_sp':c['heating_setpoint_C']if c else 5.,'cool_sp':c['cooling_setpoint_C']if c else 50.}
            if any(signal[k][i]!=v for k,v in expected.items()):return False
    return True

def controls(w,c):
    results=[]
    def test(name,edit,predicate):
        plan=copy.deepcopy(c['A']);edit(plan);result=assess(w,c,plan);results.append({'name':name,'rejected_or_flagged':predicate(result)})
    def fake(p):p['operations'].append({**p['operations'][0],'operation_id':'fake','kind':'EV_plug','need_id':'invented_service'})
    # This structural corruption is checked without attempting execution.
    p=copy.deepcopy(c['A']);fake(p);results.append({'name':'extra_plug_without_service','rejected_or_flagged':bool(integrity(w,c,p))})
    def past(p):
        x=next(x for x in p['controls']if x['start_min']<480);x['start_min']-=10
    test('change_common_past',past,lambda x:'PREDECISION_HISTORY_CHANGED'in x['integrity_errors'])
    if any(x['kind']=='dryer'for x in c['A']['tasks']):
        p=copy.deepcopy(c['A']);next(x for x in p['tasks']if x['kind']=='dryer')['start_min']+=10
        results.append({'name':'broken_wash_dry_dependency','rejected_or_flagged':'BROKEN_AUTOMATIC_WASH_DRY_CHAIN'in integrity(w,c,p)})
    ev=next((x for x in c['A']['controls']if x['kind']=='ev_charge_window'and x['start_min']>=480 and not x.get('automatic_segment_count')),None)
    if ev:
        def empty_charge(p):
            x=next(x for x in p['controls']if x==ev);x['end_min']=x['start_min']+10;x['actual_charge_end_min']=x['end_min'];x['last_step_power_fraction']=1.
        test('real_connection_insufficient_energy_is_kept',empty_charge,lambda x:not x['integrity_errors']and any(f['code']=='EV_TARGET_ENERGY_IMPOSSIBLE_IN_WINDOW'for f in x['constraint_flags']))
    return results

def main():
    verify_inputs();b=read(OUT/'PAIR_BINDINGS10000.json');sig=rules_id();fail=[];counts=collections.Counter();intensities=collections.Counter();cross=collections.Counter();flags=collections.Counter();types=collections.defaultdict(collections.Counter)
    lookup={r['household_id']:r for r in read(A_STAGE/'A_BINDINGS10000.json')['records']};cases=0;feasible=0;fallback=0;negative=[];deltas=collections.Counter();doses=collections.Counter();directions=collections.Counter();collapsed=0;nochange=0;recoveries=0;reserve_miss=0;trip_reserve_impossible=0;portfolios=collections.Counter();event_counts=collections.Counter();response_signs=collections.Counter();station_events={};vppbad=0
    for ix,row in enumerate(b['records']):
        src=lookup[row['household_id']];w=read(A_STAGE/src['A_world_path'])
        if row['A_record_sha256']!=digest(src):fail.append([row['household_id'],'A_RECORD_CHANGED'])
        sourcecases={x['case_id']:x for x in src['cases']}
        if set(sourcecases)!={x['case_id']for x in row['rounds']}:fail.append([row['household_id'],'DATES_CHANGED'])
        for r in row['rounds']:
            path=OUT/r['path'];p=read(path);c=read(A_STAGE/sourcecases[r['case_id']]['path']);cases+=1
            if sha(path)!=r['sha256']or sha(A_STAGE/sourcecases[r['case_id']]['path'])!=sourcecases[r['case_id']]['sha256']:fail.append([p['case_id'],'PAIR_OR_SOURCE_BYTES_CHANGED'])
            content=copy.deepcopy(p);claimed=content.pop('pair_content_sha256')
            if claimed!=digest(content):fail.append([p['case_id'],'PAIR_CONTENT_CHANGED'])
            if p['A']!=c['A']or p['A_frozen_sha256']!=digest(c['A'])or p['needs_A']!=c['needs_A']or p['needs_B']!=c['needs_A']or p['days']!=c['days']:fail.append([p['case_id'],'FAMILY_NEEDS_OR_A_CHANGED'])
            if p['A_source']['case_sha256']!=sourcecases[r['case_id']]['sha256']or p['source_world_content_sha256']!=w['world_content_sha256']or p['parameter_pack_sha256']!=w['parameter_pack_sha256']:fail.append([p['case_id'],'SOURCE_BINDING'])
            a=assess(w,c,p['A']);z=assess(w,c,p['B'])
            if a!=p['assessment_A']or z!=p['assessment_B']or a['constraint_flags']or a['integrity_errors']or z['integrity_errors']:fail.append([p['case_id'],'ASSESSMENT_MISMATCH'])
            if p['event_relations']!=event_relations(c,p['B'],p['VPP_events']):fail.append([p['case_id'],'EVENT_RELATION_MISMATCH'])
            for change in p['proposal']['changes']:
                if change['device_family']=='water_heater':
                    event=next(e for e in p['VPP_events']if e['event_id']==change['selected_event_id'])
                    old=next(x for x in p['A']['controls']if x['kind']=='tank_setpoint'and x['asset_id']==change['asset_id']and [x['start_min'],x['end_min']]==change['window_A_min'])
                    parts=[x for x in p['B']['controls']if x['kind']=='tank_setpoint'and x['asset_id']==change['asset_id']and [x['start_min'],x['end_min']]in change['segments_B_min']]
                    if change['description']!=tank_description(p['B'],old,parts,event,p['proposal']['realized_mechanism']=='hotwater_target'):fail.append([p['case_id'],'TANK_DESCRIPTION_MISMATCH'])
            if not independent_signals(p):fail.append([p['case_id'],'B_SIGNAL_NOT_REQUEST'])
            if p['HVAC_signals_A']!=c['HVAC_signals']or p['human_response']!={'accepted':None,'scores':None,'reason':None}or p['physical_results']is not None or p['selection_or_regeneration_based_on_B_outcome']:fail.append([p['case_id'],'FABRICATED_LABEL_RESULT_OR_FILTER'])
            expected_events=for_case(w,c)
            if p['VPP_events']!=expected_events or p['VPP_response_reference']!=response_reference(w,c,p['B'],expected_events,z):fail.append([p['case_id'],'VPP_SOURCE_OR_RESPONSE_MISMATCH'])
            for ev in expected_events:
                key=(ev['station_key'],ev['date']);current=station_events.setdefault(key,expected_events)
                if current!=expected_events:fail.append([p['case_id'],'GRID_EVENT_DEPENDS_ON_HOUSEHOLD'])
            event_counts[expected_events[0]['direction']]+=1;event_counts['multi_event_cases']+=len(expected_events)>1
            for v in p['VPP_response_reference']['events']:
                val=v['requested_known_response_average_kw'];response_signs['positive'if val>1e-7 else'negative'if val< -1e-7 else'zero']+=1
                if v['whole_portfolio_target_met']is not None:fail.append([p['case_id'],'FABRICATED_VPP_PHYSICAL_SUCCESS'])
            proposal=p['proposal']
            actual_families=[]
            for family in ('ac','washer','dishwasher','ev','water_heater'):
                aids={d['asset_id']for d in w['parameter_pack']['devices']if family in d['types']}
                def portion(plan):return {key:[x for x in plan[key]if x['asset_id']in aids]for key in('tasks','operations','controls')}
                if command_signature(portion(p['A']))!=command_signature(portion(p['B'])):actual_families.append(family)
            if set(actual_families)!=set(proposal['portfolio_families']):fail.append([p['case_id'],'FALSE_CROSS_DEVICE_COVERAGE'])
            if not proposal['VPP_conditioned_generation']or proposal['focus_VPP_event_id']not in {e['event_id']for e in expected_events}:fail.append([p['case_id'],'B_NOT_BOUND_TO_VPP'])
            if proposal['realized_mechanism']=='coordinated':portfolios[tuple(proposal['portfolio_families'])]+=1
            equivalents=[k for k,v in proposal['dose_signatures_by_design_level'].items()if v==command_signature(p['B'])]
            if set(equivalents)!=set(proposal['equivalent_design_levels'])or proposal['intensity_design']!=next(l for l in LEVELS if l in equivalents):fail.append([p['case_id'],'FALSE_INTENSITY_EQUIVALENCE'])
            if proposal['same_command_as_A']!=(command_signature(p['B'])==command_signature(p['A'])):fail.append([p['case_id'],'FALSE_COMMAND_CHANGE'])
            source_ops={o['operation_id']:o for o in p['B']['operations']}
            for o in z['conditional_recovery_reference']['realized_operations']:
                if o['operation_id']not in source_ops or any(o[k]!=source_ops[o['operation_id']][k]for k in('operator_id','kind','need_id','asset_id')):fail.append([p['case_id'],'RECOVERY_ADDED_HELPER_OR_OPERATION'])
            m=proposal['realized_mechanism'];l=proposal['intensity_design'];counts[m]+=1;intensities[l]+=1;cross[(m,l)]+=1;types[row['type']][m]+=1
            doses[proposal['actual_unique_dose_count']]+=1;collapsed+=len(proposal['equivalent_design_levels'])>1;nochange+=proposal['same_command_as_A']
            recoveries+=bool(z['conditional_recovery_reference']['operation_adjustments'])
            for e in z['EV_window_upper_bounds']:
                reserve_miss+=e['given85_reserve_target_unmet'];trip_reserve_impossible+=e['trip_plus_given_min_reserve_impossible_even_at_upper_bound']
            for change in proposal['changes']:
                if 'program_start_A_min'in change:directions['advance'if change['delta_minutes']<0 else'delay'if change['delta_minutes']>0 else'unchanged']+=1
            flags.update(set(f['code']for f in z['constraint_flags']));feasible+=z['given_constraints_feasible'];fallback+=proposal['requested_mechanism']!=m
            for change in proposal['changes']:
                if 'delta_C'in change:deltas['warmer_setpoint'if change['delta_C']>0 else'cooler_setpoint'if change['delta_C']<0 else'fan_or_pause']+=1
            if not negative and any(x['kind']=='dryer'for x in c['A']['tasks'])and any(x['kind']=='ev_charge_window'and x['start_min']>=480 for x in c['A']['controls']):negative=controls(w,c)
        if(ix+1)%100==0:print({'B_households_read_back':ix+1,'failures':len(fail)},flush=True)
    subset=read(OUT/'SUBSET50.json');allrows={r['household_id']:r for r in b['records']};ids={r['household_id']for r in read(MASTER/'SUBSET50.json')['records']}
    subsetok=ids=={r['household_id']for r in subset['records']}and all(r==allrows[r['household_id']]for r in subset['records'])
    if not subsetok:fail.append(['SUBSET_NOT_IDENTICAL_MASTER_RECORDS'])
    coverageok=set(counts)==set(MECHANISMS)and set(intensities)==set(LEVELS)
    accepted=not fail and cases==10000 and len(b['records'])==1000 and coverageok and 0<feasible<cases and nochange<cases/2 and event_counts['down']>0 and event_counts['up']>0 and any(len(k)>=2 and'ac'not in k for k in portfolios)and any(len(k)>=3 for k in portfolios)and directions['advance']>0 and directions['delay']>0 and negative and all(x['rejected_or_flagged']for x in negative)
    accepted=accepted and b['rules_sha256']==sig and read(OUT/'A_REAUDIT.json')['accepted']and read(OUT/'REGRESSION_RESULTS.json')['passed']
    report={'schema':'eb.alternative_static_acceptance.v43','accepted':bool(accepted),'households':len(b['records']),'cases':cases,'failures':fail,
            'rules_sha256':sig,'bindings_sha256':sha(OUT/'PAIR_BINDINGS10000.json'),'mechanisms':dict(counts),'intensity_design':dict(intensities),
            'mechanism_by_intensity':{m:{l:cross[(m,l)]for l in LEVELS}for m in MECHANISMS},'mechanism_by_type':dict(types),'mechanism_fallback_count':fallback,
            'given_constraints_feasible_cases':feasible,'given_constraint_conflict_cases_kept':cases-feasible,'constraint_flag_case_counts':dict(flags),
            'actual_unique_dose_count_distribution':dict(doses),'collapsed_equivalent_level_cases':collapsed,'no_command_change_reference_cases':nochange,
            'program_direction_counts':dict(directions),'cases_with_conditional_same_operator_recovery':recoveries,'EV_reserve_target_miss_connections':reserve_miss,'EV_trip_plus_min_reserve_impossible_upper_bound_connections':trip_reserve_impossible,
            'thermal_direction_counts':dict(deltas),'negative_controls':negative,'subset50_identical_master_records':subsetok,'subset50_type_counts':subset['type_counts'],
            'VPP_case_direction_counts':dict(event_counts),'unique_station_dates':len(station_events),'requested_known_load_response_signs':dict(response_signs),
            'coordinated_portfolio_counts':{'+'.join(k):v for k,v in portfolios.items()},'VPP_physical_success_labels_generated':0,
            'actual_acceptance_labels_generated':0,'B_better_than_A_filter':False,'full_physical_acceptance':False,'questionnaire_released':False}
    save(OUT/'ACCEPTANCE.json',report);print(canonical(report))
    if not accepted:raise SystemExit(2)

if __name__=='__main__':main()
