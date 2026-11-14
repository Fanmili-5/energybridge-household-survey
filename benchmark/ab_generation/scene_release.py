"""Materialize and independently replay a scene-aware1000x10 plan batch."""
import argparse,copy,hashlib,json,os,shutil,time
from pathlib import Path
from collections import Counter,defaultdict
from concurrent.futures import ProcessPoolExecutor
from .common import digest
from .cohort_coverage import load,write_gzip,simple_tokens
from .generate_cohort import save,summarize,aggregate
from .generate_native import implementation
from .scene_coverage import CompletionContext,scene_context
from .model import apply
from .eb_alignment import audit
from .paper_v1_native_replay import replay

_WORK=None

def init(batch,households,native,allocation,out):
    global _WORK
    ctx=CompletionContext(batch,households,native)
    chosen={(d['index'],d['row']['date']):d['row'] for d in load(allocation)}
    _WORK=(ctx,chosen,Path(out))

def materialize_house(house):
    ctx,chosen,out=_WORK;index=house['index'];folder=out/f'{index:04}';folder.mkdir()
    oldfolder=ctx.root/f'{index:04}';case=ctx.cases[index]
    previous_tokens=set();final_tokens=set();changes=[];pairs=[];scene_counts=Counter()
    for date in sorted(ctx.pre['dates']):
        old=load(oldfolder/(date+'_PAIR.json.gz'));row=chosen.get((index,date),old['selected_proposal'])
        previous_tokens.update(simple_tokens(old['selected_proposal']));final_tokens.update(simple_tokens(row))
        base=load(oldfolder/(date+'_A.json.gz'))
        if row.get('scene_event'):
            e,bound,c,cfg=scene_context(ctx,index,date,row['scene_event']['start_min'])
            event=cfg['event']
            if row['scene_event']!=event:raise ValueError('ROW_EVENT_CONTEXT_MISMATCH')
            current=copy.deepcopy(e);current['context']=bound;current['scene_configuration']=cfg
            context_name=date+'_SCENE.json.gz';write_gzip(folder/context_name,current)
        else:
            bound=base['context'];event=ctx.cfg['event'];context_name=date+'_A.json.gz'
        A=base['context']['A'];B=apply(A,row['patches'])
        if A!=old['A'] or digest(A)!=old['A_sha256']:raise ValueError('FULL_SOURCE_A_CHANGED')
        native=audit(bound,B,row['components'],side='B')
        if not native['passed'] or native['hard_errors']:raise ValueError('FINAL_B_NATIVE_REJECTED')
        proofs={side:replay(base['problem'],bound,plan,ctx.native) for side,plan in [('A',A),('B',B)]}
        if any(not p['passed'] for p in proofs.values()):raise ValueError('ORIGINAL_NATIVE_REPLAY_FAILED')
        scenario=dict(source_household_sha256=digest(case),date=date,event=event,A_sha256=digest(A))
        pair=copy.deepcopy(old)
        pair.update(schema='eb.paper_v1.native_verified_pair.v3',A=A,B=B,A_sha256=digest(A),B_sha256=digest(B),
            selected_proposal=row,native_B_acceptance=native,paper_v1_execution=proofs,
            event=event,scenario_sha256=digest(scenario),context_sha256=digest(bound),
            context_relative_path=f'{index:04}/'+context_name,
            scene_policy=row.get('scene_policy','fixed_18_19_v1'),
            scene_purpose=row.get('scene_purpose','coverage_completion' if row.get('scene_event') else 'reference'),
            parent_pair_binding=dict(A_sha256=old['A_sha256'],B_sha256=old['B_sha256']),
            physical_outcomes=None,human_answers=None,formal_questionnaire_release=False)
        pair['pair_id']=digest([pair['scenario_sha256'],pair['B_sha256']])
        pair.pop('cohort_selection',None)
        pair['selection_protocol']='capacity_aware_scene_coverage_with_matched_event_panel.v1'
        name=date+'_PAIR.json.gz';write_gzip(folder/name,pair)
        shutil.copyfile(oldfolder/(date+'_A.json.gz'),folder/(date+'_A.json.gz'))
        changed=(row['id']!=old['selected_proposal']['id'])
        if changed:changes.append(dict(date=date,old=old['selected_proposal']['id'],new=row['id'],
            old_B_sha256=old['B_sha256'],B_sha256=pair['B_sha256'],event=event))
        scene_counts[event['start_min']]+=1
        pairs.append(dict(date=date,path=name,A_sha256=pair['A_sha256'],B_sha256=pair['B_sha256'],
            pair_id=pair['pair_id'],scenario_sha256=pair['scenario_sha256'],event=event,
            context_relative_path=pair['context_relative_path'],context_sha256=pair['context_sha256']))
    if previous_tokens-final_tokens:raise ValueError('HOUSEHOLD_BASIC_COVERAGE_LOST:'+str(sorted(previous_tokens-final_tokens)))
    if len(pairs)!=10 or len({p['date'] for p in pairs})!=10:raise ValueError('TEN_DISTINCT_DAILY_QUESTIONS_REQUIRED')
    save(folder/'RESULT.json',dict(schema='eb.scene_daily_plan_result.v1',status='native_plan_qualification_passed',
        pairs=pairs,source_household_unchanged=True,A_unchanged=True,old_basic_tokens_preserved=True,
        changes=changes,event_counts=dict(scene_counts),physical_outcomes_computed=False))
    row=summarize(case,folder,index)
    extra={p['date']:p for p in pairs}
    for item in row['pair_index']:
        p=extra[item['date']]
        item.update({k:p[k] for k in ['pair_id','scenario_sha256','event','context_relative_path','context_sha256']})
    row.update(changed_questions=len(changes),event_counts=dict(scene_counts),old_basic_tokens_preserved=True)
    return row

def materialize(batch,households,native,discovered,out,workers=8):
    batch=Path(batch);root=Path(out);disc=Path(discovered)
    if load(disc/'BALANCE_RESULT.json')['status']!='passed':raise ValueError('BALANCED_SCENE_PANEL_REQUIRED')
    root.mkdir(parents=True,exist_ok=False);ctx=CompletionContext(batch,households,native)
    frozen=implementation();parent_index_sha=hashlib.sha256((batch/'PAIR_INDEX.jsonl').read_bytes()).hexdigest()
    allocation=disc/'ALLOCATION_BALANCED.json.gz'
    pre=dict(schema='eb.scene_native_cohort.pre_run.v1',source_sha256=ctx.pre['source_sha256'],
        dates=ctx.pre['dates'],target_households=len(ctx.cases),target_pairs=len(ctx.cases)*10,
        parent_batch=str(batch.resolve()),parent_pair_index_sha256=parent_index_sha,
        parent_A_generation=load(batch/'PRE_RUN.json'),scene_implementation=frozen,
        allocation_sha256=hashlib.sha256(allocation.read_bytes()).hexdigest(),workers=workers,
        original_appliance_source_sha256=hashlib.sha256(Path(native).read_bytes()).hexdigest(),
        original_raw_target_ledger_sha256=hashlib.sha256((batch/'COHORT_COVERAGE_LEDGER.json.gz').read_bytes()).hexdigest())
    save(root/'PRE_RUN.json',pre);rows=[];started=time.monotonic()
    with ProcessPoolExecutor(max_workers=workers,initializer=init,
            initargs=(batch,households,native,allocation,root)) as pool:
        for row in pool.map(materialize_house,ctx.status):
            rows.append(row)
            if len(rows)%50==0:
                save(root/'PROGRESS.json',dict(households=len(rows),pairs=len(rows)*10,seconds=round(time.monotonic()-started,2)))
                print(json.dumps(dict(stage='fresh_native_replay',households=len(rows),pairs=len(rows)*10)),flush=True)
    ctx.verify_source()
    if implementation()!=frozen:raise ValueError('SCENE_IMPLEMENTATION_CHANGED_DURING_MATERIALIZATION')
    if hashlib.sha256((batch/'PAIR_INDEX.jsonl').read_bytes()).hexdigest()!=parent_index_sha:raise ValueError('PARENT_BATCH_INDEX_CHANGED')
    index_rows=[p for row in rows for p in row.pop('pair_index')]
    with (root/'PAIR_INDEX.jsonl').open('w') as f:
        for r in sorted(index_rows,key=lambda r:(r['index'],r['date'])):f.write(json.dumps(r,ensure_ascii=False)+'\n')
    summary=dict(completed=len(rows),passed=len(rows),failed=0,pairs=len(index_rows))
    result=aggregate(rows,len(ctx.cases),True,True,summary)
    result.update(schema='eb.scene_native_batch.result.v1',changed_questions=sum(r['changed_questions'] for r in rows),
        all_full_A_plans_unchanged=True,all_household_basic_tokens_preserved=True,fresh_native_replays=len(index_rows)*2,
        scene_coverage_pending_independent_verification=True,seconds=round(time.monotonic()-started,2))
    save(root/'STATUS.json',dict(summary=summary,rows=rows));save(root/'RESULT.json',result)
    return verify(root,batch,households,disc)

def verify(root,parent,households,discovered):
    root=Path(root);parent=Path(parent);disc=Path(discovered)
    raw=Path(households).read_bytes();pre=load(root/'PRE_RUN.json')
    if hashlib.sha256(raw).hexdigest()!=pre['source_sha256']:raise ValueError('HOUSEHOLD_MANIFEST_CHANGED')
    cases=[json.loads(l) for l in raw.splitlines() if l.strip()]
    cases.sort(key=lambda c:(c['household']['country'],c['household']['role_id'],c['case_id']))
    ledger=load(parent/'COHORT_COVERAGE_LEDGER.json.gz');selected=defaultdict(lambda:defaultdict(Counter))
    per_house=defaultdict(set);events=Counter();panel=Counter();a_equal=0;b_changed=0;replayed=0;oldtokens=defaultdict(set);tokens=defaultdict(set)
    ids=set();scene_ids=set();new_raw=defaultdict(set);changed_per_house=Counter()
    index=[json.loads(l) for l in (root/'PAIR_INDEX.jsonl').read_text().splitlines()]
    for rec in index:
        i=rec['index'];case=cases[i];h=case['household'];date=rec['date'];key=(i,date)
        if date in per_house[i]:raise ValueError('DUPLICATE_DATE')
        per_house[i].add(date);p=root/rec['relative_path'];pair=load(p)
        old=load(parent/f'{i:04}'/(date+'_PAIR.json.gz'))
        if hashlib.sha256(p.read_bytes()).hexdigest()!=rec['pair_file_sha256']:raise ValueError('PAIR_FILE_HASH_MISMATCH')
        if pair['A']!=old['A'] or digest(pair['A'])!=rec['A_sha256']:raise ValueError('A_PLAN_CHANGED')
        if digest(pair['B'])!=rec['B_sha256']:raise ValueError('B_PLAN_HASH_MISMATCH')
        if pair['source_household_sha256']!=digest(case) or pair['source_manifest_sha256']!=pre['source_sha256']:raise ValueError('PAIR_HOUSEHOLD_LINEAGE_MISMATCH')
        e=load(root/rec['context_relative_path']);c=e['context']
        if digest(c)!=rec['context_sha256'] or c['events']!=[rec['event']] or c['A']!=pair['A']:raise ValueError('SCENE_CONTEXT_OR_EVENT_MISMATCH')
        expected=digest(dict(source_household_sha256=digest(case),date=date,event=rec['event'],A_sha256=rec['A_sha256']))
        if expected!=rec['scenario_sha256'] or digest([expected,rec['B_sha256']])!=rec['pair_id']:raise ValueError('SCENE_IDENTITY_MISMATCH')
        if rec['pair_id'] in ids or expected in scene_ids:raise ValueError('DUPLICATE_QUESTION_IDENTITY')
        ids.add(rec['pair_id']);scene_ids.add(expected)
        if pair['physical_outcomes'] is not None or pair['human_answers'] is not None:raise ValueError('INHERITED_DOWNSTREAM_OUTCOME')
        if not pair['native_B_acceptance']['passed'] or pair['native_B_acceptance']['hard_errors']:raise ValueError('NATIVE_AUDIT_FAILED')
        if any(not pair['paper_v1_execution'][s]['passed'] for s in ['A','B']):raise ValueError('NATIVE_REPLAY_FAILED')
        row=pair['selected_proposal'];changed_per_house[i]+=row['id']!=old['selected_proposal']['id'];oldtokens[i].update(simple_tokens(old['selected_proposal']));tokens[i].update(simple_tokens(row))
        for cell in row['raw_root_cells']:selected[h['role_id']][cell][h['country']]+=1
        start=rec['event']['start_min'];events[start]+=1
        if start!=1080:panel[(h['country'],h['role_id'],start)]+=1
        a_equal+=1;b_changed+=rec['B_sha256']!=old['B_sha256'];replayed+=2
    if len(index)!=len(cases)*10 or len(per_house)!=len(cases):raise ValueError('BATCH_CARDINALITY_ERROR')
    if any(d!=set(pre['dates']) for d in per_house.values()):raise ValueError('HOUSEHOLD_DATE_ALLOCATION_CHANGED')
    if any(oldtokens[i]-tokens[i] for i in oldtokens):raise ValueError('BASE_COVERAGE_LOST')
    scene_support=defaultdict(lambda:defaultdict(set));explored=defaultdict(set)
    for file in sorted((disc/'candidates').glob('*.json.gz')):
        d=load(file);explored[d['role']].update(d.get('declared_extension_raw_cells',[]))
        for row in d['rows']:
            for key in row['raw_root_cells']:scene_support[d['role']][key].add(d['country'])
    for file in sorted((disc/'balanced_controls').glob('*.json.gz')):
        for d in load(file)['rows']:
            for key in d['row']['raw_root_cells']:scene_support[d['role']][key].add(d['country'])
    final={}
    for role,cells in ledger.items():
        final[role]=[]
        for oldcell in cells:
            cs=selected[role][oldcell['key']]
            entry={**oldcell,'selected_countries':sorted(c for c,n in cs.items() if n>0)}
            entry['reference_raw_countries_scope']='original18_19preselection_frame'
            entry['expanded_scene_witness_countries']=sorted(scene_support[role][oldcell['key']])
            entry['witness_countries']=sorted(set(oldcell['witness_countries'])|scene_support[role][oldcell['key']])
            entry['pool_goal_met']=len(entry['witness_countries'])>=oldcell['target_countries']
            entry['selected_goal_met']=len(entry['selected_countries'])>=oldcell['target_countries']
            if not entry['selected_countries']:raise ValueError('ORIGINAL_RAW_TARGET_UNCOVERED')
            prior=min(oldcell['target_countries'],len(oldcell['selected_countries']))
            if min(oldcell['target_countries'],len(entry['selected_countries']))<prior:raise ValueError('ATTAINED_COUNTRY_COVERAGE_LOST')
            final[role].append(entry)
        known={c['key'] for c in cells};new_raw[role].update(set(selected[role])-known)
    cap=load(disc/'BALANCE_PRE_RUN.json')['max_changed_per_household']
    if max(changed_per_house.values(),default=0)>cap:raise ValueError('HOUSEHOLD_CHANGE_BUDGET_EXCEEDED')
    quotas=load(disc/'BALANCE_RESULT.json')['quotas_per_country_role']
    groups={(c['household']['country'],c['household']['role_id']) for c in cases}
    if any(panel[(country,role,int(s))]!=q for country,role in groups for s,q in quotas.items()):raise ValueError('MATCHED_EVENT_PANEL_IMBALANCED')
    write_gzip(root/'COHORT_COVERAGE_LEDGER.json.gz',final)
    coverage=dict(original_raw_targets=sum(map(len,ledger.values())),
        selected_at_least_one=sum(bool(x['selected_countries']) for entries in final.values() for x in entries),
        selected_country_goals_met=sum(x['selected_goal_met'] for entries in final.values() for x in entries),
        selected_additional_scene_cells={role:len(v) for role,v in new_raw.items()},
        explored_scene_raw_cells={role:len(v) for role,v in explored.items()},
        explored_scene_domain_is_not_claimed_exhaustive=True,
        target_definition='frozen pre-scene raw root-cell ledger;not every possible external event or joint plan')
    manifest=dict(schema='eb.sealed_scene_native_plan_batch.v1',households=len(cases),pairs=len(index),
        source_sha256=pre['source_sha256'],pair_index_sha256=hashlib.sha256((root/'PAIR_INDEX.jsonl').read_bytes()).hexdigest(),
        current_plan_and_scenario_hashes_checked=True,all_full_A_plans_unchanged=True,all_basic_tokens_preserved=True,
        source_households_unchanged=True,A_hashes_equal=a_equal,B_hashes_changed=b_changed,
        fresh_original_native_replays=replayed,coverage=coverage,event_counts=dict(events),
        max_changed_questions_per_household=max(changed_per_house.values(),default=0),
        matched_event_counts_equal_across_all_country_role_strata=True,
        physical_qualification_not_inherited=True,formal_questionnaire_release=False,human_answers_generated=False)
    save(root/'DATASET_MANIFEST.json',manifest)
    result=load(root/'RESULT.json');result.update(scene_coverage_pending_independent_verification=False,coverage=coverage)
    save(root/'RESULT.json',result)
    save(root/'PHYSICS_HANDOFF.json',dict(schema='eb.native_to_physics.handoff.v2',
        source_sha256=pre['source_sha256'],pair_index='PAIR_INDEX.jsonl',pair_index_sha256=manifest['pair_index_sha256'],
        event_required_from_each_index_row=True,context_required_from_context_relative_path=True,
        outcome_join_requires=['pair_id','scenario_sha256','A_sha256','B_sha256','event','context_sha256'],
        forbidden='silently use fixed18-19 context for a scene-varying pair',
        same_building_weather_hardware_daily_demands_and_initial_state_for_A_and_B_required=True,
        model_assignment_manifest=None,physical_outcomes=None,human_answers=None,physical_qualification=False))
    return manifest

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase',choices=['materialize','verify'])
    for n in ('batch','households','discovered','out'):p.add_argument('--'+n,required=True,type=Path)
    p.add_argument('--native-source',type=Path);p.add_argument('--workers',type=int,default=8)
    a=p.parse_args()
    if not 1<=a.workers<=8:p.error('workers must be1..8')
    if a.phase=='materialize':
        if not a.native_source:p.error('native source required')
        r=materialize(a.batch,a.households,a.native_source,a.discovered,a.out,a.workers)
    else:r=verify(a.out,a.batch,a.households,a.discovered)
    print(json.dumps(r),flush=True)
if __name__=='__main__':main()
