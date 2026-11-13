"""Same-role coverage over pre-selection raw EB root cells.

No physics outcomes or human feedback enter this review. A missing witness is
unknown, never a certificate of physical infeasibility or resident refusal.
"""
from collections import Counter,defaultdict
from pathlib import Path
import gzip,hashlib,json

def load(path):
    with gzip.open(path,'rt') if str(path).endswith('.gz') else open(path) as stream:return json.load(stream)
def write_gzip(path,value):
    with gzip.open(path,'wt',encoding='utf-8') as stream:json.dump(value,stream,ensure_ascii=False,separators=(',',':'))
_TOKEN_CACHE={}
def simple_tokens(row):
    from benchmark.ab_generation.unified.selection import concepts
    if row['id'] not in _TOKEN_CACHE:_TOKEN_CACHE[row['id']]={t for t in concepts(row,'exact_witnessed_v1')['tokens'] if not t.startswith('detail.')}
    return _TOKEN_CACHE[row['id']]

def catalogues_with_extras(folder):
    days=load(folder/'CATALOGUES.json.gz')
    extra_path=folder/'COVERAGE_EXTRA_CANDIDATES.json.gz'
    if extra_path.exists():
        for extra in load(extra_path):
            day=next(d for d in days if d['date']==extra['date'])
            known={row['id'] for row in day['rows']}
            day['rows'].extend(row for row in extra['rows'] if row['id'] not in known)
    return days

def scan(root):
    root=Path(root);status=load(root/'RESULT.json')
    if not status['native_plan_generation_passed']:raise ValueError('FULL_NATIVE_BATCH_NOT_COMPLETE')
    rows=load(root/'STATUS.json')['rows'];raw=defaultdict(lambda:defaultdict(set));pool=defaultdict(lambda:defaultdict(set));chosen=defaultdict(lambda:defaultdict(Counter))
    slots={};base_counts=defaultdict(Counter);required={};examples=defaultdict(lambda:defaultdict(list));intrinsic=Counter()
    for house in rows:
        i=house['index'];role=house['role'];country=house['country'];folder=root/str(i).zfill(4)
        catalogues=catalogues_with_extras(folder)
        for day in catalogues:
            for cell in day['declared_raw_root_cells']:
                key=cell['key']
                if not cell['admissible_raw_alternatives']:
                    intrinsic[role]+=1;continue
                raw[role][key].add(country)
                if sum(x['country']==country for x in examples[role][key])<3:examples[role][key].append(dict(index=i,date=day['date'],factor=cell['factor'],country=country))
            for row in day['rows']:
                if not row['native_execution']['passed']:raise ValueError('NONQUALIFIED_POOL_WITNESS')
                for cell in row['raw_root_cells']:pool[role][cell].add(country)
        for p in sorted(folder.glob('*_PAIR.json.gz')):
            if p.name.endswith('_INITIAL_PAIR.json.gz'):continue
            pair=load(p);row=pair['selected_proposal'];slot=(i,pair['date'])
            slots[slot]=dict(index=i,role=role,country=country,path=p,row=row)
            base_counts[i].update(simple_tokens(row))
            for cell in row['raw_root_cells']:chosen[role][cell][country]+=1
        required[i]=set(base_counts[i])
        if (i+1)%100==0:print(json.dumps(dict(phase='cohort_scan',households=i+1)),flush=True)
    return dict(rows=rows,raw=raw,pool=pool,chosen=chosen,slots=slots,base_counts=base_counts,required=required,examples=examples,intrinsic=intrinsic)

def country_count(counter):return sum(v>0 for v in counter.values())

def can_swap(state,slot,new):
    old=slot['row'];i=slot['index'];role=slot['role'];country=slot['country']
    oldcells=set(old['raw_root_cells']);newcells=set(new['raw_root_cells']);gain=0
    for cell in oldcells|newcells:
        current=state['chosen'][role][cell];changed=Counter(current)
        changed[country]-=cell in oldcells;changed[country]+=cell in newcells
        goal=min(2,len(state['raw'][role][cell]))
        before_score=min(goal,country_count(current));after_score=min(goal,country_count(changed))
        if after_score<before_score:return False
        gain+=after_score-before_score
    if gain<=0:return False
    before=simple_tokens(old);after=simple_tokens(new)
    counts=state['base_counts'][i]
    if any(counts[t]-(t in before)+(t in after)<=0 for t in state['required'][i]):return False
    return True

def adopt(state,slot,new):
    old=slot['row'];i=slot['index'];role=slot['role'];country=slot['country']
    state['base_counts'][i].subtract(simple_tokens(old));state['base_counts'][i].update(simple_tokens(new))
    for cell in old['raw_root_cells']:state['chosen'][role][cell][country]-=1
    for cell in new['raw_root_cells']:state['chosen'][role][cell][country]+=1
    slot['row']=new

def report(state):
    public={};private={}
    for role,cells in state['raw'].items():
        details=[]
        for key,countries in cells.items():
            want=min(2,len(countries));have=country_count(state['chosen'][role][key]);seen=len(state['pool'][role].get(key,set()))
            details.append(dict(key=key,raw_countries=sorted(countries),witness_countries=sorted(state['pool'][role].get(key,set())),
                selected_countries=sorted(k for k,v in state['chosen'][role][key].items() if v>0),target_countries=want,
                selected_goal_met=have>=want,pool_goal_met=seen>=want,examples=state['examples'][role][key]))
        private[role]=details
        public[role]=dict(declared_raw_cells=len(details),selected_at_least_one=sum(bool(x['selected_countries']) for x in details),
            selected_country_goals_met=sum(x['selected_goal_met'] for x in details),materialized_country_goals_met=sum(x['pool_goal_met'] for x in details),
            cells_without_materialized_witness=sum(not x['witness_countries'] for x in details),
            source_intrinsic_exclusion_instances=state['intrinsic'][role])
    return public,private

def all_known_goals_met(state):
    return all(country_count(state['chosen'][role][key])>=min(2,len(countries),len(state['pool'][role].get(key,set()))) for role,cells in state['raw'].items() for key,countries in cells.items())

def review(root,apply=False,native_source=None):
    root=Path(root);state=scan(root);initial,_=report(state);changes=[]
    if apply:
        if native_source is None:raise ValueError('NATIVE_SOURCE_REQUIRED_FOR_RESELECTION')
        # Deterministic monotone refinement: preserve each household's original
        # family/trade coverage and never lose a country from an attained cell.
        for _ in range(3):
            if all_known_goals_met(state):break
            updated=0
            for house in state['rows']:
                folder=root/str(house['index']).zfill(4)
                for day in catalogues_with_extras(folder):
                    slot=state['slots'][(house['index'],day['date'])]
                    for candidate in sorted(day['rows'],key=lambda r:r['id']):
                        if candidate['id']==slot['row']['id'] or not can_swap(state,slot,candidate):continue
                        before=slot['row']['id'];adopt(state,slot,candidate)
                        changes.append(dict(index=house['index'],date=day['date'],before=before,after=candidate['id']))
                        updated+=1
                if all_known_goals_met(state):break
            if not updated:break
        # Store only final changes, with fresh original-source execution proof.
        from benchmark.ab_generation.model import apply as patch
        from benchmark.ab_generation.eb_alignment import audit
        from benchmark.ab_generation.paper_v1_native_replay import replay
        for slot in state['slots'].values():
            original=load(slot['path']);row=slot['row']
            if row['id']==original['selected_proposal']['id']:continue
            folder=slot['path'].parent;date=original['date'];e=load(folder/(date+'_A.json.gz'));context=e['context']
            b=patch(context['A'],row['patches']);native=audit(context,b,row['components'],side='B')
            if not native['passed']:raise ValueError('COHORT_RESELECTION_NATIVE_ERROR')
            proof=replay(e['problem'],context,b,native_source)
            backup=folder/(date+'_INITIAL_PAIR.json.gz')
            if not backup.exists():backup.write_bytes(slot['path'].read_bytes())
            from benchmark.ab_generation.common import digest
            original.update(B=b,B_sha256=digest(b),selected_proposal=row,native_B_acceptance=native)
            original['paper_v1_execution']['B']=proof
            original['cohort_selection']=dict(protocol='same_role_raw_cells_country_coverage.v1',physics_or_human_answers_used=False)
            write_gzip(slot['path'],original)
            case_result=load(folder/'RESULT.json')
            initial_result=folder/'RESULT_INITIAL.json'
            if not initial_result.exists():initial_result.write_text(json.dumps(case_result,ensure_ascii=False,indent=2))
            for p in case_result['pairs']:
                if p['date']==date:p['B_sha256']=original['B_sha256']
            case_result['cohort_refined']=True
            (folder/'RESULT.json').write_text(json.dumps(case_result,ensure_ascii=False,indent=2))
    final,private=report(state)
    result=dict(schema='eb.same_role_raw_cell_review.v1',denominator='pre-selection raw root cells with intrinsic checks;not selected examples or materialized pool',
        country_goal='two per role/cell when raw support spans at least two countries;otherwise one',
        initial=initial,final=final,reselected_slots=len({(x['index'],x['date']) for x in changes}),selection_history=changes,
        all_declared_goals_met=all(v['selected_country_goals_met']==v['declared_raw_cells'] for v in final.values()),
        unmaterialized_is_unknown_not_infeasible=True,original_household_base_coverage_preserved=True,
        physics_or_human_answers_used=False)
    write_gzip(root/'COHORT_COVERAGE_LEDGER.json.gz',private)
    (root/'COHORT_COVERAGE_REVIEW.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    return result

def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch',required=True,type=Path)
    parser.add_argument('--apply',action='store_true',help='reselect; preserve previous pair and replay changed B')
    parser.add_argument('--native-source')
    args=parser.parse_args()
    answer=review(args.batch,args.apply,args.native_source)
    print(json.dumps({k:v for k,v in answer.items() if k!='selection_history'}))
if __name__=='__main__':main()
