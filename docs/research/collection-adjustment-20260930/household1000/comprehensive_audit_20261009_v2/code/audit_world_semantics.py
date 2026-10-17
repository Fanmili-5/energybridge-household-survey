"""Read-only review of the frozen V19 world, actions and displayed facts.

Does not import the production validator or start EnergyPlus. Counts are
descriptive witnesses, not consent labels or clinical safety judgements.
"""
import argparse,collections,concurrent.futures,hashlib,json,sys
from pathlib import Path

OUT=Path(__file__).resolve().parents[1]
STAGE=OUT.parent/'evidence_conditioned_production_20261009_v19'
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def digest(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def contains(windows,a,b):return any(lo<=a and b<=hi for lo,hi in windows)
def intersects(a,b):return max(a[0],b[0])<min(a[1],b[1])
def grid(intervals):
    result=[None]*144
    for item in intervals:
        for k in range(item['start_min']//10,item['end_min']//10):result[k]=item
    assert all(result)
    return result

def one(h):
    w=read(STAGE/h['world_path']);old=read(STAGE.parent/'profile_conditioned_production_20261008_v18'/h['world_path'])
    stats=collections.Counter();examples=collections.defaultdict(list);affected=collections.defaultdict(set);failure=[]
    def note(kind,p,side=None,detail=None):
        stats[kind]+=1;affected[kind].add(p['case_id'])
        if len(examples[kind])<5:examples[kind].append({'case_id':p['case_id'],'round_index':p['round_index'],'side':side,'detail':detail})
    if any(w[k]!=old[k] for k in ('N','G','H6','H7','layout','population_weight','province','ego_relationships','random10_date_selection')):failure.append('SOURCE_ANCHOR_CHANGED')
    if len(w['members'])!=w['N'] or len({m['generation_level'] for m in w['members']})!=w['G']:failure.append('ROSTER_NG')
    if sha(STAGE/h['world_path'])!=h['world_sha256'] or digest({k:v for k,v in w.items() if k!='world_content_sha256'})!=w['world_content_sha256']:failure.append('WORLD_HASH')
    for m in w['members']:
        if m['current_work_source_proxy'] is None and m['employment_status']!='unknown':failure.append('UNKNOWN_PROMOTED')
    for row in h['rounds']:
        p=read(STAGE/row['pair_path']);c=read(STAGE/'consumers'/w['household_id']/f"{row['round_index']:02d}.json");stats['pairs']+=1
        if sha(STAGE/row['pair_path'])!=row['pair_sha256'] or digest({k:v for k,v in p.items() if k!='pair_content_sha256'})!=p['pair_content_sha256']:failure.append([p['case_id'],'PAIR_HASH'])
        if digest(p['A'])!=p['A_frozen_before_B_sha256'] or p['needs_A']!=p['needs_B']:failure.append([p['case_id'],'FROZEN_A_OR_COMMON_NEEDS'])
        if not (p['primary_evaluation_min'][0]<=p['decision_abs_min']<p['event_window_min'][0]<p['event_window_min'][1]<=p['primary_evaluation_min'][1]):failure.append([p['case_id'],'EVENT_OUTSIDE_OBSERVATION'])
        if c['identity']['date']!=p['date'] or c['human_label_count']!=0:failure.append([p['case_id'],'CONSUMER_DATE_OR_LABEL'])
        days=p['dated_activity_days'];grids=[{mid:grid(intervals) for mid,intervals in day['member_calendars'].items()} for day in days]
        members={m['member_id']:m for m in w['members']};adult_ids=[mid for mid,m in members.items() if m['age_years']>=18];child_ids=[mid for mid,m in members.items() if m['age_years']<6]
        if days[0]['day_type']!=days[1]['day_type']:note('next_day_type_differs',p,detail=[days[0]['day_type'],days[1]['day_type']])
        for side in ('A','B'):
            plan=p[side];tasks=plan['tasks'];asset_index={d['asset_id']:d for d in p['world']['devices']}
            # Reconstruct the production's action overlay independently: EV
            # handling is outside; appliance handling is in the saved asset room.
            overlay={}
            for o in plan['operations']:
                for t in range(o['start_min'],o['end_min'],10):
                    overlay[o['operator_id'],t]='outside' if o['kind'].startswith('EV_') else 'home'
            care_slots=[];awake_departures=[]
            if child_ids:
                active_times=sorted({t for who,t in overlay if who in adult_ids and overlay[who,t]=='outside'})
                for t in active_times:
                    di,slot=t//1440,t%1440//10
                    if di>=len(days):continue
                    children=[mid for mid in child_ids if grids[di][mid][slot]['location']=='home']
                    if not children:continue
                    adult_home=[mid for mid in adult_ids if overlay.get((mid,t),grids[di][mid][slot]['location'])=='home']
                    visitors=[v for v in days[di]['external_visits'] if v['start_min']<=t%1440<v['end_min']]
                    resting=[mid for mid in children if grids[di][mid][slot]['activity'] in ('sleep_rest','day_nap')]
                    if resting and not adult_home and not visitors:care_slots.append({'abs_min':t,'children':resting,'adult_home':[]})
                    for entry in days[di]['supervision_ledger']:
                        if entry['start_min']==t%1440 and overlay.get((entry['responsible_person_id'],t))=='outside':awake_departures.append({'abs_min':t,'entry':entry})
                if care_slots:note(side+'_resting_child_presence_lost_after_EV_handling',p,side,care_slots[:4]);stats[side+'_resting_child_presence_lost_slots']+=len(care_slots)
                if awake_departures:note(side+'_specified_awake_supervisor_leaves',p,side,awake_departures[:2])
            morning_ops=[o for o in plan['operations'] if 1440<=o['start_min']<p['primary_evaluation_min'][1]]
            if morning_ops:
                note(side+'_next_morning_handling_cases',p,side,morning_ops[:2])
                stale=[o for o in morning_ops if contains(days[0]['operator_windows_min'].get(o['operator_id'],[]),o['start_min']-1440,o['end_min']-1440)!=contains(days[1]['operator_windows_min'].get(o['operator_id'],[]),o['start_min']-1440,o['end_min']-1440)]
                if stale:note(side+'_next_morning_availability_differs_from_visible_day',p,side,{'operations':stale[:2],'visible_day':days[0]['date'],'required_day':days[1]['date'],'required_day_type':days[1]['day_type']})
            early=[];late=[]
            for o in plan['operations']:
                if o['kind']!='unload':continue
                chain=[t for t in tasks if t['need_id'] in (o['need_id'],o['need_id']+':dry')]
                if chain and o['start_min']<max(t['end_min'] for t in chain):early.append({'operation':o,'program_end_min':max(t['end_min'] for t in chain)})
                need=next((n for n in p['needs_A'] if n['need_id']==o['need_id']),None)
                if need and o['end_min']>need.get('delivery_deadline_min',need['deadline_min']):late.append(o)
            if early:note(side+'_unload_before_chain_complete',p,side,early[:2])
            if late:note(side+'_retrieval_after_given_delivery_deadline',p,side,late[:2])
            lost=[]
            for task in tasks:
                same=[x for x in tasks if x['asset_id']==task['asset_id']]
                missed=[t for t in range(task['start_min'],task['end_min'],10) if next(x for x in same if x['start_min']<=t<x['end_min'])['task_id']!=task['task_id']]
                if missed:lost.append({'task_id':task['task_id'],'asset_id':task['asset_id'],'lost_minutes_under_first_match_compiler':len(missed)*10})
            if lost:note(side+'_overlap_suppresses_requested_program',p,side,lost[:3]);stats[side+'_suppressed_requested_program_minutes']+=sum(x['lost_minutes_under_first_match_compiler'] for x in lost)
        next_required=any(1440<=o['start_min']<1920 for side in ('A','B') for o in p[side]['operations'])
        text='\n'.join(c['context']['daily_need_texts'])
        if next_required and c['profile']['profile']['current_reference_date']==days[0]['date'] and days[1]['date'] not in text:
            note('next_morning_actions_without_dated_next_day_role_context',p,detail={'next_date':days[1]['date'],'next_day_type':days[1]['day_type']})
    return {'household_id':w['household_id'],'stats':dict(stats),'examples':dict(examples),'affected':{k:sorted(v) for k,v in affected.items()},'failures':failure,
            'population':{'province':w['province'],'N':w['N'],'G':w['G'],'H6':w['H6'],'H7':w['H7'],'weight':w['population_weight']}}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--allow-local-readonly',action='store_true');args=parser.parse_args()
    if sys.platform!='linux' and not args.allow_local_readonly:raise RuntimeError('Prefer school Linux for audit execution')
    selection=read(STAGE/'SELECTION1000.json');delivery=read(STAGE/'DELIVERY.json')
    manifest_failures=[name for name,value in delivery['files'].items() if sha(STAGE/name)!=value]
    assert not manifest_failures,manifest_failures
    combined=collections.Counter();examples=collections.defaultdict(list);affected=collections.defaultdict(list);failures=[];rows=[]
    with concurrent.futures.ProcessPoolExecutor(max_workers=16 if sys.platform=='linux' else 4) as pool:
        for i,r in enumerate(pool.map(one,selection['records']),1):
            rows.append(r);combined.update(r['stats']);failures.extend([[r['household_id'],x] for x in r['failures']])
            for k,v in r['examples'].items():examples[k].extend(v[:max(0,8-len(examples[k]))])
            for k,v in r['affected'].items():affected[k].extend(v)
            if i%200==0:print({'audited_households':i,'pairs':combined['pairs']},flush=True)
    population=[r['population'] for r in rows];totalw=sum(x['weight'] for x in population)
    report={'schema':'eb.independent_v19_semantic_audit.v1','platform':sys.platform,'EP_started':0,'production_modified':False,
        'delivery_sha256':sha(STAGE/'DELIVERY.json'),'manifest_files_checked':len(delivery['files']),'manifest_failures':manifest_failures,
        'households':len(rows),'counts':dict(combined),'integrity_failures':failures,'examples':dict(examples),'affected_case_ids':dict(affected),
        'N_counts':dict(collections.Counter(x['N'] for x in population)),'G_counts':dict(collections.Counter(x['G'] for x in population)),
        'population_weights_sum':totalw,'unweighted_residents':sum(x['N'] for x in population),'weighted_mean_residents':sum(x['N']*x['weight'] for x in population)/totalw,
        'semantic_failure_counts_are_not_human_rejection_labels':True,'bad_B_retention_is_not_itself_an_error':True}
    (OUT/'WORLD_SEMANTIC_AUDIT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print({k:v for k,v in report.items() if k not in ('examples','affected_case_ids')},flush=True)
if __name__=='__main__':main()
