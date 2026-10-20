"""CLI for the independent-day, plan-only collection pilot. No engine/UI calls."""
import argparse
import copy
import datetime as dt
import itertools
import json
from collections import Counter
from pathlib import Path
from .common import bound,code_hash,digest,read,save,seal,sha,verify
from .collection_assignment import assign
from .collection_candidates import generate_day
from .collection_design import amplitude_axes,design,event_status,issues,report_counts,tags,working_context
from .energy import task_power
from .generate import event_energy
from .model import apply, overlap
from .power import ev_profile
from .collection_admission import engineering_issues
from .collection_thermal import AC_CONTRACT, describe as describe_ac, state as ac_state
from .collection_relevance import explain, asset_reasons
from .sampling import command_hash

HERE=Path(__file__).parent


def prepare_source(input_path,out):
    """Reproduce the existing public families/life A without invoking old B/EP."""
    from benchmark.project.pipeline import configuration,prepare_families
    from benchmark.family_generation.core import generate
    from benchmark.family_generation.connect import connect
    c,source=configuration(input_path);out=Path(out);out.mkdir(parents=True,exist_ok=False)
    save(out/'INPUT.json',c)
    generated=prepare_families(c,source,out)
    generate(generated,out/'families');connect(out/'families',out/'connected')
    seal(out,{'schema':'eb.collection.public_A_source.v1','new_engine_runs':0,
              'B_generated':False,'source_input_sha256':sha(input_path)})
    return {'source':str(out),'households':read(out/'families/SUMMARY.json')['constructed'],'new_engine_runs':0}


def _task_profile(c,plan):
    devices={d['asset_id']:d for d in c['devices']};event=c['events'][0]
    return [{**t,'power_kw':task_power(t,devices[t['asset_id']]['parameters'])} for t in plan['tasks']
            if t['start_min']<event['end_min'] and t['end_min']>event['start_min']]


def review(c,row,config=None):
    """Materialize original FULL A; independently integrate known event profiles."""
    b=apply(c['A'],row['patches'])
    actual,gate,power=issues(c,row['patches'],row['program_needs'])
    identities=[(p['collection'],r[p['identity']]) for p in row['patches'] if p['type']=='rows' for r in p['rows']]
    if len(identities)!=len(set(identities)):
        actual.append('OVERLAPPING_PATCH_IDENTITIES')
    # Recompute shortage from the patched permission windows, not a candidate's
    # stored prediction. This is nominal energy feasibility, not observed SOC.
    for component in row['components']:
        if component['family']!='ev':continue
        aid=component['asset_id'];nid=component['service_need_id']
        steps=[s for s in c['reference']['ev_charging_steps'] if s['need_id']==nid and s['start_min']>=c['decision_min']]
        original=[r for r in c['A']['controls'] if r['kind']=='ev_charge_window' and r['asset_id']==aid and r['need_id']==nid]
        windows=[r for r in b['controls'] if r['kind']=='ev_charge_window' and r['asset_id']==aid and r['need_id']==nid]
        rating=next(d['parameters']['charger_kw'] for d in c['devices'] if d['asset_id']==aid)
        anchor=min(s['start_min'] for s in steps);end=min(max(r['end_min'] for r in original),c['horizon_min'][1])
        capacity=sum(rating/6 for t in range(anchor,end,10) if any(w['start_min']<=t and t+10<=w['end_min'] for w in windows))
        if sum(s['grid_kWh'] for s in steps)>capacity+1e-8:
            actual.append('CHARGE_EXCEEDS_ORIGINAL_CONNECTION')
    actual=sorted(set(actual))
    event=c['events'][0]
    before=_task_profile(c,c['A'])+ev_profile(c,c['A'])
    after=_task_profile(c,b)+ev_profile(c,b)
    known=event_energy(before,event)-event_energy(after,event)
    failures=[]
    config=design(config)
    component_patches=[p for component in row['components'] for p in component['patches']]
    if component_patches!=row['patches']:failures.append('COMPONENT_PATCH_BINDING_MISMATCH')
    relevance=explain(c,row['components'],event)
    if not relevance['passed'] or relevance!=row['event_relevance']:
        failures.append('EVENT_RELEVANCE_MISMATCH')
    if relevance['passed'] and asset_reasons(c,row['components'],relevance)!=row['asset_change_reasons']:
        failures.append('ASSET_REASON_MISMATCH')
    for component in row['components']:
        if component['event_relevance']!=relevance['components'].get(component['id']):
            failures.append('COMPONENT_REASON_MISMATCH')
        if component['family']=='ac':
            ac=describe_ac(c,component['asset_id'],component['patches'],component['magnitude']['axis'],event,config['ac_delta_C'])
            if ac!=component['magnitude'].get('ac_intervention'):
                failures.append('AC_COMMAND_SEMANTICS_OR_AMPLITUDE_MISMATCH')
    if row['features']['intensity']!='not_aggregated_use_amplitude_axes':
        failures.append('FALSE_WHOLE_B_INTENSITY')
    if row['features']['amplitude_axes']!=amplitude_axes(row['components']):
        failures.append('AMPLITUDE_AXIS_PROFILE_MISMATCH')
    if gate:failures.append('IMMUTABLE_GATE')
    logic=engineering_issues(c,b,row['program_needs'],actual)
    if logic or row.get('engineering_issues',[])!=logic:
        failures.append('COLLECTION_ENGINEERING_ADMISSION_FAILED')
    if actual!=row['issues']:failures.append('FULL_PLAN_ISSUE_MISMATCH')
    if abs(known-row['known_event_reduction_kWh'])>1e-8:failures.append('EVENT_PROFILE_INTEGRATION_MISMATCH')
    if row['actual_outcomes'] is not None or row['human_acceptance'] is not None:failures.append('INVENTED_OUTCOME')
    if tags(row)!=row['tags']:failures.append('COVERAGE_TAG_MISMATCH')
    actual_changed=[];thermal_changed=False
    for d in c['devices']:
        aid=d['asset_id']
        a={k:[r for r in c['A'][k] if r['asset_id']==aid] for k in ('tasks','operations','controls')}
        z={k:[r for r in b[k] if r['asset_id']==aid] for k in ('tasks','operations','controls')}
        if command_hash(a)!=command_hash(z):
            actual_changed.append(aid)
            if set(d['types'])&{'ac','water_heater'}:thermal_changed=True
    expected_admission='diagnostic' if actual else 'control' if not actual_changed else 'plan_valid'
    manual=any(a!=z for a,z in zip(sorted(c['A']['operations'],key=lambda r:r['operation_id']),sorted(b['operations'],key=lambda r:r['operation_id'])))
    expected={'device_count':str(len(actual_changed)),'admission':expected_admission,
              'event':event_status(known,thermal_changed),'manual':'changed' if manual else 'unchanged'}
    if any(row['features'][k]!=v for k,v in expected.items()) or sorted(actual_changed)!=row['changed_assets']:
        failures.append('LITERAL_PLAN_FEATURE_MISMATCH')
    if (row['case_id'],row['household_id'],row['date'])!=(c['case_id'],c['household_id'],c['date']):
        failures.append('CASE_IDENTITY_MISMATCH')
    if command_hash(b)==command_hash(c['A']) and row['features']['device_count']!='0':failures.append('FALSE_CHANGED_DEVICE_COUNT')
    if command_hash(apply(working_context(c)['A'],row['patches']))!=row['working_B_sha256']:
        failures.append('PATCH_BINDING_MISMATCH')
    return {'passed':not failures,'failed_checks':failures,'expected_issues':row['issues'],
        'engineering_issues':logic,
        'recomputed_issues':actual,'known_event_reduction_kWh':known,'power_status':power['status'],
        'A_commands_sha256':command_hash(c['A']),'B_commands_sha256':command_hash(b),
        'scope':'full_A_static_and_independent_analytic_event_integration;not_physical_execution'},b


def _projection(c,row,b,check):
    lo,hi=c['horizon_min']
    def clip(plan):
        return {k:[{**r,'start_min':max(lo,r['start_min']),'end_min':min(hi,r['end_min'])} if k=='controls' else r
            for r in plan[k] if r['end_min']>lo and r['start_min']<hi] for k in ('tasks','operations','controls')}
    display={}
    for side,plan in [('A',c['A']),('B',b)]:
        display[side]=[{'asset_id':r['asset_id'],'start_min':max(lo,r['start_min']),'end_min':min(hi,r['end_min']),
            **ac_state(r,c['reference'].get('ac_control_contract'))} for r in plan['controls']
            if r['kind']=='ac_setpoint' and overlap(r['start_min'],r['end_min'],lo,hi)]
    return {'id':row['id'],'household_id':c['household_id'],'date':c['date'],'events':c['events'],
        'A':clip(c['A']),'B':clip(b),'components':row['components'],'features':row['features'],
        'issues':row['issues'],'known_event_reduction_kWh':row['known_event_reduction_kWh'],
        'engineering_issues':row.get('engineering_issues',[]),
        'event_relevance':row['event_relevance'],'asset_change_reasons':row['asset_change_reasons'],
        'ac_control_display':display,'whole_B_intensity':None,
        'unknown_thermal_response':row['unknown_thermal_response'],'full_plan_audit':check,
        'presentation_scope_min':[lo,hi],'full_A_and_B_retained_in_build':True,
        'physical_status':'not_run','actual_cost':None,'actual_temperature':None,
        'actual_outcomes':None,'human_acceptance':None,'independent_daily_counterfactual':True}


def _coverage(rows,selected,assignment,daily):
    result={'schema':'eb.collection.coverage.v3','catalogue':report_counts(rows),'selected':report_counts(selected),
        'catalogue_unique':len(rows),'selected_count':len(selected),
        'all_evaluated_diagnostics_retained':True,'diagnostics_catalogue':sum(bool(r['issues']) for r in rows),
        'diagnostics_selected':sum(bool(r['issues']) for r in selected),
        'engineering_diagnostics_retained':sum(r['engineering_diagnostics_retained'] for r in daily),
        'relevance_diagnostics_retained':sum(r['relevance_diagnostics_retained'] for r in daily),
        'category_proportions_prescribed':False,'admission_labels_rewarded':False,
        'goals':assignment['coverage'],'required_deficits':assignment['required_deficits'],
        'near_duplicate_excess':assignment['near_duplicate_excess'],'interactions':[],
        'generation_limits':[{'household_id':x['household_id'],'date':x['date'],
            **{k:x[k] for k in ('joint_subset_required','joint_subset_observed','joint_subset_attempted','joint_search_status','retimed_handling_search','gaps')}} for x in daily],
        'physical_failure_prevalence':'unknown;not_executed','actual_nonresponse_prevalence':'unknown;not_executed',
        'population_representativeness_claim':False,'new_engine_runs':0}
    axes=['device_count','admission','event','manual','thermal_direction','service_slack']
    for a,b in itertools.combinations(axes,2):
        available=Counter((r['features'][a],r['features'][b]) for r in rows)
        hits=Counter((r['features'][a],r['features'][b]) for r in selected)
        for levels,count in sorted(available.items()):
            result['interactions'].append({'axes':[a,b],'levels':list(levels),'catalogue_unique':count,'selected':hits[levels]})
    # An entire amplitude vector is descriptive metadata, not one giant factor.
    # Count each named device axis separately and only where it applies.
    dose_axes=sorted({x.rsplit('=',1)[0] for r in rows for x in r['features']['amplitude_axes']})
    for dose_axis in dose_axes:
        for base_axis in ('device_count','event','manual'):
            def cells(pool):
                out=Counter()
                for r in pool:
                    for token in r['features']['amplitude_axes']:
                        name,level=token.rsplit('=',1)
                        if name==dose_axis:out[(r['features'][base_axis],level)]+=1
                return out
            available,hits=cells(rows),cells(selected)
            for levels,count in sorted(available.items()):
                result['interactions'].append({'axes':[base_axis,'amplitude.'+dose_axis],
                    'levels':list(levels),'catalogue_unique':count,'selected':hits[levels],
                    'applicability':'only_candidates_containing_this_device_axis'})
    result['amplitude_profile_is_coverage_factor']=False
    result['interaction_cells']=len(result['interactions'])
    result['interaction_deficits']=sum(not r['selected'] for r in result['interactions'])
    return result


def build(source_project,config_path,out,progress=None):
    from benchmark.project.context import plan_context
    source=Path(source_project);config=design(read(config_path));out=Path(out)
    if not config['households']:raise ValueError('EXPLICIT_PILOT_HOUSEHOLD_FRAME_REQUIRED')
    verify(source/'families')
    source_records={r['household_id']:r for r in read(source/'families/SUMMARY.json')['records'] if r['status']=='family_constructed'}
    if not set(config['households'])<=source_records.keys():raise ValueError('SOURCE_HOUSEHOLD_MISSING')
    out.mkdir(parents=True,exist_ok=False);save(out/'DESIGN.json',config)
    emit=progress or (lambda x:print(x,flush=True))
    # Seal A-side sources before constructing any B. Do not load old generated,
    # selected, questionnaire, IDF or physical-result files from the source root.
    sources={};households=[]
    for hid in sorted(config['households']):
        root=source/'connected/life_A'/hid;manifest=verify(root)
        path=bound(root,manifest['records'][0]['path'])
        family=read(bound(source/'families',source_records[hid]['path']))
        sources[hid]={'family_sha256':sha(bound(source/'families',source_records[hid]['path'])),
            'life_payload_sha256':sha(path),'world_sha256':sha(root/'WORLD_INPUT.json')}
        households.append({'household_id':hid,'evidence_kind':family['evidence_kind'],'facts':family['facts'],
            'archetype':family['archetype'],'archetype_is_experimental':True,'devices':family['world']['devices']})
    generation_code=code_hash()
    save(out/'PRE_GENERATION.json',{'schema':'eb.collection.pre_generation.v1','design_sha256':digest(config),
        'sources':sources,'code_sha256':generation_code,'B_generated_yet':False,'B_outcomes_available':False,
        'human_answers_available':False,'online_questionnaire_changed':False,'master1000_started':False})
    save(out/'HOUSEHOLDS.json',households)
    all_rows=[];daily=[];contexts={};original_life={}
    tariff=read(source/'INPUT.json')['tariff']
    for hid in sorted(config['households']):
        root=source/'connected/life_A'/hid;manifest=read(root/'MANIFEST.json')
        life=read(bound(root,manifest['records'][0]['path']));world=read(root/'WORLD_INPUT.json')['households'][0]
        life_before=digest(life);original_life[hid]=life_before
        for offset in range(config['days']):
            date=(dt.date.fromisoformat(config['first_date'])+dt.timedelta(days=offset)).isoformat()
            if date not in life['days']:raise ValueError('DATE_NOT_IN_FROZEN_A:'+date)
            case=hid+'-'+date
            c=plan_context(life,world,{'date':date,'case_id':case,'events':[config['event']],'tariff':tariff},sources[hid]['family_sha256'])
            # Explicit project encoding declaration; original A commands/hashes
            # remain byte-identical. Never infer this contract for arbitrary imports.
            c['reference']['ac_control_contract']=copy.deepcopy(AC_CONTRACT)
            emit('生成 '+case)
            result=generate_day(c,config);contexts[case]=c
            save(out/'contexts'/(case+'.json.gz'),c);save(out/'catalogues'/(case+'.json.gz'),result)
            all_rows.extend(result['rows']);daily.append({'household_id':hid,'date':date,
                **{k:v for k,v in result.items() if k not in ('rows','quarantined_requests','engineering_diagnostics','relevance_diagnostics','control_record')},
                'quarantine_count':len(result['quarantined_requests']),
                'quarantine_reasons':dict(Counter(i for r in result['quarantined_requests'] for i in r['gate_issues']))})
        if digest(life)!=life_before:raise ValueError('SOURCE_A_MUTATED')
    save(out/'GENERATION.json',daily)
    emit('联合分配十天案例；不读取B后果或人类答案')
    assignment=assign(all_rows,config);save(out/'ASSIGNMENT.json',assignment)
    by_id={r['id']:r for r in all_rows};selected=[by_id[i] for i in assignment['selected_ids']]
    samples=[];audits=[]
    for row in selected:
        c=contexts[row['case_id']];check,b=review(c,row,config);audits.append({'id':row['id'],**check})
        if not check['passed']:raise ValueError('FULL_PLAN_REVIEW_FAILED:'+row['id']+':'+','.join(check['failed_checks']))
        save(out/'pairs'/(row['id']+'.json'),{'A':c['A'],'B':b,'row':row,'review':check})
        samples.append(_projection(c,row,b,check))
    coverage=_coverage(all_rows,selected,assignment,daily)
    save(out/'PUBLIC_SAMPLES.json',samples);save(out/'COVERAGE.json',coverage)
    audit={'schema':'eb.collection.review.v1','passed':all(x['passed'] for x in audits),'records':audits,
        'same_frozen_A_preserved':True,'source_life_payloads':original_life,'new_engine_runs':0,
        'acceptance_labels_generated':0,'online_questionnaire_changed':False,'master1000_started':False}
    save(out/'REVIEW.json',audit)
    summary={'schema':'eb.collection.pilot.v3','households':len(config['households']),'days_per_household':10,
        'selected':len(selected),'catalogue_unique':len(all_rows),'diagnostics_retained':coverage['diagnostics_catalogue'],
        'diagnostics_selected':coverage['diagnostics_selected'],'required_deficits':coverage['required_deficits'],
        'engineering_diagnostics_retained':coverage['engineering_diagnostics_retained'],
        'relevance_diagnostics_retained':coverage['relevance_diagnostics_retained'],
        'engineering_errors_selected':sum(bool(x['engineering_issues']) for x in audits),
        'category_proportions_prescribed':False,'admission_labels_rewarded':False,
        'interaction_deficits':coverage['interaction_deficits'],'interaction_cells':coverage['interaction_cells'],
        'near_duplicate_excess':coverage['near_duplicate_excess'],'full_plan_review_passed':audit['passed'],
        'coverage_contract_passed':coverage['required_deficits']==0,'physical_status':'not_run','new_engine_runs':0,
        'online_questionnaire_changed':False,'master1000_started':False,'solver':assignment['solver']}
    if code_hash()!=generation_code:raise ValueError('GENERATOR_CODE_CHANGED_DURING_BUILD;retain_development_run')
    save(out/'SUMMARY.json',summary);seal(out,{'schema':summary['schema'],'code_sha256':generation_code,
        'pre_generation_sha256':sha(out/'PRE_GENERATION.json'),'summary_sha256':sha(out/'SUMMARY.json')})
    return summary


def recheck(root):
    root=Path(root);verify(root);config=design(read(root/'DESIGN.json'))
    rows=[]
    for p in sorted((root/'catalogues').glob('*.json.gz')):rows.extend(read(p)['rows'])
    by_id={r['id']:r for r in rows};assignment=read(root/'ASSIGNMENT.json');checks=[]
    for ident in assignment['selected_ids']:
        row=by_id[ident];c=read(root/'contexts'/(row['case_id']+'.json.gz'))
        check,b=review(c,row,config);pair=read(root/'pairs'/(ident+'.json'))
        if pair['A']!=c['A'] or pair['B']!=b or pair['review']!=check:raise ValueError('PAIR_READBACK_MISMATCH')
        checks.append(check)
    selected=[by_id[i] for i in assignment['selected_ids']]
    coverage=_coverage(rows,selected,assignment,read(root/'GENERATION.json'))
    if coverage!=read(root/'COVERAGE.json'):raise ValueError('COVERAGE_READBACK_MISMATCH')
    if not all(c['passed'] for c in checks):raise ValueError('RECHECK_FAILED')
    return {'passed':True,'selected':len(checks),'coverage_contract_passed':coverage['required_deficits']==0,
            'new_engine_runs':0,'rerandomized':False}


def replay(root):
    root=Path(root);verify(root);config=design(read(root/'DESIGN.json'));rows=[]
    for p in sorted((root/'catalogues').glob('*.json.gz')):rows.extend(read(p)['rows'])
    previous=read(root/'ASSIGNMENT.json');again=assign(rows,config)
    passed=(previous['selected_ids']==again['selected_ids'] and previous['coverage']==again['coverage'])
    if not passed:raise ValueError('DETERMINISTIC_ASSIGNMENT_REPLAY_MISMATCH')
    return {'passed':passed,'selected':len(again['selected_ids']),'same_seed':True,
        'same_catalogue':True,'actual_outcomes_used':False,'new_engine_runs':0,
        'scope':'locked_runtime_replay;not_a_claim_of_identical_MILP_ties_across_unpinned_solver_versions'}


def sensitivity(root,out):
    """Predeclared first weekday/weekend per household; never replace the pilot."""
    root=Path(root);verify(root);config=design(read(root/'DESIGN.json'));out=Path(out)
    out.mkdir(parents=True,exist_ok=False)
    variants=[('baseline',{}),('joint_half',{'joint_budget':max(1,config['joint_budget']//2)}),
        ('joint_double',{'joint_budget':config['joint_budget']*2}),
        ('alternate_quantiles',{'quantiles':[0.1,0.5,0.95]}),
        ('larger_thermal_request',{'ac_delta_C':[0.5,1,3],'tank_delta_C':[1,3,7]})]
    chosen={}
    for p in sorted((root/'contexts').glob('*.json.gz')):
        c=read(p);key=(c['household_id'],'weekend' if dt.date.fromisoformat(c['date']).weekday()>=5 else 'weekday')
        chosen.setdefault(key,c)
    generation_code=code_hash()
    save(out/'PRE_PROBE.json',{'variants':variants,'cases':[c['case_id'] for c in chosen.values()],
        'code_sha256':generation_code,'selection_changes_permitted':False,'B_outcomes_used':False})
    records=[]
    for name,overrides in variants:
        for _,c in sorted(chosen.items()):
            if code_hash()!=generation_code:raise ValueError('GENERATOR_CODE_CHANGED_DURING_PROBE')
            print('计划敏感性 '+name+' '+c['case_id'],flush=True)
            before=digest(c);result=generate_day(c,design({**config,**overrides}))
            # Audit one deterministic representative per admission/count/event
            # cell on FULL A, rather than assuming the index checked itself.
            witnesses={}
            for row in result['rows']:
                witnesses.setdefault((row['features']['admission'],row['features']['device_count'],row['features']['event']),row)
            checks=[review(c,row,design({**config,**overrides}))[0] for row in witnesses.values()]
            if digest(c)!=before or not all(x['passed'] for x in checks):raise ValueError('SENSITIVITY_PLAN_AUDIT_FAILED')
            records.append({'variant':name,'case_id':c['case_id'],'A_commands_sha256':result['A_commands_sha256'],
                'counts':report_counts(result['rows']),'catalogue_unique':len(result['rows']),
                'joint_subset_required':result['joint_subset_required'],'joint_subset_observed':result['joint_subset_observed'],
                'full_A_witnesses_reviewed':len(checks),'all_static_audits_passed':True,
                'A_unchanged':True,'physical_status':'not_run'})
    if code_hash()!=generation_code:raise ValueError('GENERATOR_CODE_CHANGED_DURING_PROBE')
    result={'schema':'eb.collection.sensitivity.v1','records':records,'cases':len(chosen),'variants':len(variants),
        'all_static_audits_passed':True,'original_selection_changed':False,'new_engine_runs':0,
        'claim':'plan_integrity_under_declared_perturbations;counts_can_change;no_physical_or_preference_robustness_claim'}
    save(out/'RESULT.json',result);seal(out,{'schema':result['schema'],'code_sha256':generation_code})
    return {k:v for k,v in result.items() if k!='records'}


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare-source');p.add_argument('--input',default='benchmark/project/examples/project.json');p.add_argument('--out',required=True)
    p=sub.add_parser('build');p.add_argument('--source-project',required=True);p.add_argument('--config',default=str(HERE/'examples/collection/design.json'));p.add_argument('--out',required=True)
    p=sub.add_parser('recheck');p.add_argument('--root',required=True)
    p=sub.add_parser('replay');p.add_argument('--root',required=True)
    p=sub.add_parser('sensitivity');p.add_argument('--root',required=True);p.add_argument('--out',required=True)
    args=parser.parse_args()
    value=(prepare_source(args.input,args.out) if args.command=='prepare-source' else
        build(args.source_project,args.config,args.out) if args.command=='build' else
        replay(args.root) if args.command=='replay' else sensitivity(args.root,args.out) if args.command=='sensitivity' else recheck(args.root))
    print(json.dumps(value,ensure_ascii=False,sort_keys=True))


if __name__=='__main__':main()
