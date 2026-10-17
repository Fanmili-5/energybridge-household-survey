"""Independent10min actuator readback of every saved pair and all four input candidates.

This verifier samples channel values instead of using executable.commands or its
interval-merging implementation. It validates requests, never physical success.
"""
import sys,collections,json,hashlib
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *
from event_proposals import make
from events import for_case

def sampled(plan,end=None):
    rows=[];grid={}
    for kind,fields in [('tasks',['kind','asset_id']),('operations',['kind','asset_id','operator_id','room_id'])]:
        for x in plan[kind]:
            if end is not None and x['start_min']>=end:continue
            rows.append([kind,*[x[k]for k in fields],x['start_min'],min(x['end_min'],end)if end is not None else x['end_min']])
    for x in plan['controls']:
        keys={'ac_setpoint':['heating_setpoint_C','cooling_setpoint_C','fan_operating_mode'],'tank_setpoint':['value_C'],'ev_charge_window':['stop_at_target_soc']}[x['kind']]
        value=tuple(float(x[k])+0. for k in keys);stop=min(x['end_min'],end)if end is not None else x['end_min']
        for t in range(x['start_min'],stop,10):
            key=(x['kind'],x['asset_id'],t)
            if key in grid:raise ValueError('OVERLAPPING_CONTROL:'+str(key))
            grid[key]=value
    rows.extend(['controls',*key,*v]for key,v in grid.items());rows.sort(key=str)
    return hashlib.sha256(json.dumps(rows,separators=(',',':')).encode()).hexdigest(),grid

def part(plan,aids):return {key:[x for x in plan[key]if x['asset_id']in aids]for key in ['tasks','operations','controls']}

def main():
    bindings=read(OUT/'PAIR_BINDINGS10000.json');arows={r['household_id']:r for r in read(A_STAGE/'A_BINDINGS10000.json')['records']};oldstage=BASE/'candidate_B_v47_20261017';oldrows={r['household_id']:r for r in read(oldstage/'PAIR_BINDINGS10000.json')['records']};assignments=read(OUT/'INPUT_COVERAGE_PLAN.json')['assignments']
    bad=[];counts=collections.Counter();doses=collections.Counter();shapes=collections.Counter();direction_pairs=collections.Counter();goal_pairs=collections.Counter();examples={};station_requests={};actual_pre_cases=set();proposed_pre_cases=set()
    for ri,row in enumerate(bindings['records']):
        src=arows[row['household_id']];w=read(A_STAGE/src['A_world_path']);sources={x['case_id']:x for x in src['cases']};oldcases={x['case_id']:x for x in oldrows[row['household_id']]['rounds']}
        for index,rr in enumerate(row['rounds']):
            p=read(OUT/rr['path']);q=p['proposal'];c=read(A_STAGE/sources[p['case_id']]['path']);old=read(oldstage/oldcases[p['case_id']]['path']);counts['cases']+=1
            a,ag=sampled(p['A']);b,bg=sampled(p['B']);same=a==b
            if same:counts['no_command_change_cases']+=1;examples.setdefault('true_noop',{'case_id':p['case_id'],'path':rr['path'],'proposal':q})
            if q['actual_command_intensity']!=('unchanged'if same else q['intensity_design']):bad.append([p['case_id'],'FALSE_ACTUAL_INTENSITY_LABEL'])
            if same!=q['same_command_as_A']:bad.append([p['case_id'],'SAMPLED_COMMAND_DIFFERENCE_MISMATCH'])
            if p['A']!=c['A']or p['needs_A']!=p['needs_B']or p['needs_A']!=c['needs_A']:bad.append([p['case_id'],'A_OR_DEMAND_CHANGED'])
            if p['assessment_B']['integrity_errors']:bad.append([p['case_id'],'GENERATION_ERROR'])
            counts['constraint_conflicts_kept']+=bool(p['assessment_B']['constraint_flags'])
            if p['physical_results']is not None or any(v is not None for v in p['human_response'].values())or p['selection_or_regeneration_based_on_B_outcome']:bad.append([p['case_id'],'OUTCOME_FILTER_OR_FABRICATED_LABEL'])
            av=[o for o in p['A']['operations']if o['kind'].startswith('EV_')];bv=[o for o in p['B']['operations']if o['kind'].startswith('EV_')]
            if av!=bv:bad.append([p['case_id'],'EV_VISIT_CHANGED_OR_FILLER'])
            families=[]
            for family in ['ac','washer','dishwasher','ev','water_heater']:
                aids={d['asset_id']for d in w['parameter_pack']['devices']if family in d['types']}
                if sampled(part(p['A'],aids))[0]!=sampled(part(p['B'],aids))[0]:families.append(family)
            if set(families)!=set(q['portfolio_families']):bad.append([p['case_id'],'SAMPLED_PORTFOLIO_MISMATCH'])
            c['VPP_events']=for_case(w,c);c['input_design_assignment']=assignments[p['case_id']];candidate=[]
            def observe(level,plan):candidate.append(sampled(plan)[0])
            replay,replayed_q=make(w,c,index,candidate_observer=observe);counts['dose_candidates_independently_read_back']+=len(candidate)
            requested=LEVELS.index(q['requested_intensity_design']);equiv=[LEVELS[i]for i,sig in enumerate(candidate)if sig==candidate[requested]]
            if len(set(candidate))!=q['actual_unique_dose_count']or equiv!=q['equivalent_design_levels']or q['intensity_design']!=equiv[0]:bad.append([p['case_id'],'SAMPLED_DOSE_EQUIVALENCE_MISMATCH'])
            if sampled(replay)[0]!=b or replayed_q!=q:bad.append([p['case_id'],'INPUT_REPLAY_MISMATCH'])
            doses[len(set(candidate))]+=1
            if len(set(candidate))==1 and candidate[0]==a:counts['all_four_doses_equal_A_cases']+=1
            es=p['VPP_events'];key=(es[0]['station_key'],p['date'])
            if station_requests.setdefault(key,es)!=es:bad.append([p['case_id'],'HOUSEHOLD_DEPENDENT_VPP'])
            if es!=c['VPP_events']:bad.append([p['case_id'],'VPP_INPUT_REPLAY_MISMATCH'])
            window_fields=['event_id','station_key','date','notification_min','start_min','end_min','source_template_id']
            if [[e[k]for k in window_fields]for e in es]!=[[e[k]for k in window_fields]for e in old['VPP_events']]:bad.append([p['case_id'],'EB_WINDOWS_CHANGED'])
            if len(es)==1:
                counts['single_event_cases']+=1
                if any(es[0][k]!=old['VPP_events'][0][k]for k in ['direction','target_kw']):bad.append([p['case_id'],'SINGLE_WINDOW_FACTOR_CHANGED'])
            else:
                counts['multi_event_cases']+=1;directions=tuple(e['direction']for e in es);goals=tuple(e['target_kw']for e in es);shape=('mixed'if len(set(directions))>1 else'same','unequal'if len(set(goals))>1 else'equal');shapes[shape]+=1;direction_pairs[directions]+=1;goal_pairs[goals]+=1
                examples.setdefault('multi_'+'_'.join(shape),{'case_id':p['case_id'],'path':rr['path'],'events':es,'proposal':q,'known_load_reference':p['VPP_response_reference']})
            for e,rel in zip(es,p['event_relations']):
                before=sampled(p['A'],e['start_min'])[0]==sampled(p['B'],e['start_min'])[0];until=sampled(p['A'],e['end_min'])[0]==sampled(p['B'],e['end_min'])[0]
                expected='no_command_change'if same else'only_after_event'if until else'first_changes_during_event'if before else'changes_before_event'
                counts['event_chronologies_independently_read_back']+=1
                if expected!=rel['requested_command_relation']or until!=rel['commands_identical_through_event_end']:bad.append([p['case_id'],'SAMPLED_EVENT_CHRONOLOGY_MISMATCH'])
            for ch in q['changes']:
                if ch['device_family']!='ac':continue
                pc=ch.get('preconditioning')
                if not pc:
                    if ch['control_action_direction']=='unchanged':
                        counts['unchanged_thermal_actions_kept']+=1
                        if ch['affected_asset_ids']or ch['deliberate_reverse_direction']:bad.append([p['case_id'],'NOOP_REPORTED_AS_REAL_ADVERSE_ACTION'])
                    continue
                proposed_pre_cases.add(p['case_id']);actual_pre=False
                for phase in pc['phases']:
                    a0,b0=phase['start_min'],phase['end_min'];actual=[]
                    for aid,claimed in phase['actual_minutes_by_asset'].items():
                        expected=[t for t in range(a0,b0,10)if ag.get(('ac_setpoint',aid,t))!=bg.get(('ac_setpoint',aid,t))]
                        if expected!=claimed:bad.append([p['case_id'],'FALSE_PHASE_CHANGED_MINUTES'])
                        added=[t for t in expected if ('ac_setpoint',aid,t)not in ag]
                        if len(added)*10!=phase['A_permission_added_minutes_by_asset'][aid]:bad.append([p['case_id'],'FALSE_PHASE_NEW_PERMISSION'])
                        actual.extend(expected)
                    changed=bool(actual)
                    if changed!=phase['is_actual_command_change']or (phase['control_action_direction']=='unchanged')==changed:bad.append([p['case_id'],'FALSE_PHASE_CHANGE_LABEL'])
                    if phase['phase']!='event_relaxation':
                        actual_pre=changed
                        counts['actual_preconditioning_requests'if changed else'unchanged_preparation_requests_kept']+=1
                        if not changed:examples.setdefault('zero_preparation',{'case_id':p['case_id'],'path':rr['path'],'change':ch})
                if actual_pre!=pc['preparation_command_changed']:bad.append([p['case_id'],'FALSE_PRECONDITIONING_COVERAGE'])
                if actual_pre:actual_pre_cases.add(p['case_id'])
        if(ri+1)%100==0:print({'command_review_households':ri+1,'errors':len(bad)},flush=True)
    subset=read(OUT/'SUBSET50.json');lookup={x['household_id']:x for x in bindings['records']};masterids={x['household_id']for x in read(MASTER/'SUBSET50.json')['records']}
    if {x['household_id']for x in subset['records']}!=masterids or any(x!=lookup[x['household_id']]for x in subset['records']):bad.append(['SUBSET_NOT_EXACT_MAIN_RECORDS'])
    if set(shapes)!={(a,b)for a in ['same','mixed']for b in ['equal','unequal']}:bad.append(['MISSING_PREDECLARED_VPP_FACTOR_CELL'])
    counts.update(actual_preconditioning_cases=len(actual_pre_cases),proposed_preconditioning_cases=len(proposed_pre_cases),unique_station_dates=len(station_requests))
    report={'accepted':not bad and counts['cases']==10000,'rules_sha256':rules_id(),'counts':dict(counts),'actual_unique_dose_counts':dict(doses),'multi_window_factor_counts':{'+'.join(k):v for k,v in shapes.items()},'ordered_direction_counts':{'→'.join(k):v for k,v in direction_pairs.items()},'ordered_goal_kW_counts':{'→'.join(map(str,k)):v for k,v in goal_pairs.items()},'errors':bad,'subset50_exact_main_records':True,'subset50_type_counts':subset['type_counts'],'independent_method':'10min actuator-channel sampling;no interval-normalization helper imported;all40000 candidates replayed from frozen inputs','full_physical_acceptance':False,'human_acceptance_known':False,'source_A_unchanged':True,'B_outcome_selection':False}
    save(OUT/'COMMAND_AND_VPP_REVIEW.json',report);save(OUT/'review/实际指令与多窗口案例.json',examples);print(canonical(report))
    if not report['accepted']:raise SystemExit(2)
if __name__=='__main__':main()
