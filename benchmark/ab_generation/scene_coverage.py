"""Capacity-aware event-scene completion around unchanged daily A plans.

Scenes vary an explicit external one-hour event, never household habits or
native appliance primitives. Original preselection coverage targets stay fixed.
"""
import argparse, copy, hashlib, json, math, time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from .cohort_coverage import load, write_gzip, simple_tokens, catalogues_with_extras
from .candidate_completion import CompletionContext, qualified
from .common import digest
from .eb_alignment import bind_household
from .generate_native import record_raw_cells
from .generate_cohort import save
from .unified.candidates import prepare, catalogue_domains, request
from .unified.contract import config

SCHEMA = 'eb.event_scene_coverage.v1'
GRID = tuple(range(960, 1201, 10))
_WORK = None

def event_configuration(original, start):
    if type(start) is not int or start not in GRID:
        raise ValueError('EVENT_NOT_IN_DECLARED_EVENING_GRID')
    cfg = copy.deepcopy(original)
    cfg['event_policy'] = 'evening_scene_grid_v1'
    cfg['event'] = {**cfg['event'], 'event_id': f'evening-{start}-{start+60}',
                    'start_min': start, 'end_min': start+60}
    return config(cfg)

def scene_context(ctx, index, date, start):
    base = load(ctx.root / f'{index:04}' / (date+'_A.json.gz'))
    bound = bind_household(base['context'], ctx.cases[index], ctx.pre['source_sha256'])
    cfg = event_configuration(ctx.cfg, start)
    bound['events'] = [copy.deepcopy(cfg['event'])]
    bound['reference']['binding']['context_sha256'] = digest({k:v for k,v in bound.items() if k!='reference'})
    c = prepare(bound, cfg)
    if digest(bound['A']) != digest(base['context']['A']):
        raise ValueError('EVENT_SCENE_CHANGED_BASELINE_A')
    return base, bound, c, cfg

def root_catalogue(c, cfg):
    g = catalogue_domains(c, cfg)
    d = record_raw_cells(dict(factors=g['descriptors'],native_domains=g['values'],rows=[]))
    return g, d['declared_raw_root_cells']

def complete_cell(c, cfg, g, cell):
    factor = cell['factor']
    desc = next(d for d in g['descriptors'][factor] if d['label']==cell['label'])
    values = [g['values'][factor][j] for j in desc['ids']
              if not g['values'][factor][j].get('_intrinsic_issues')]
    for primary in values:
        row = request(c, [primary], cfg, None)
        if qualified(row):
            return row
    # A shifted dryer may require the existing same-load washer to move too.
    # Search literal original candidates; no fabricated manual operations.
    if cell['family'] not in ('washer', 'dryer'):
        return None
    other = 'washer' if cell['family']=='dryer' else 'dryer'
    companions = {r['id']:r for vs in g['values'] for r in vs if r and r['family']==other}
    companions.update({r['id']:r for r in g['support_domain'] if r['family']==other})
    for primary in values:
        for companion in sorted(companions.values(), key=lambda r:r['id']):
            row = request(c, [primary, companion], cfg, None)
            if qualified(row):
                return row
    return None

def init_worker(batch, households, native, targets, out, dates_per_cell):
    global _WORK
    _WORK = (CompletionContext(batch,households,native), targets, Path(out), dates_per_cell)

def discover_house(house):
    ctx, targets, out, dates_per_cell = _WORK
    index, role = house['index'], house['role']
    keys = set(targets.get(role, []))
    seen = defaultdict(set); rows = {}; scans = []; declared = set()
    if not keys:
        return dict(index=index, rows=0, scans=0)
    families = {json.loads(k)[0] for k in keys}
    for date in sorted(ctx.pre['dates']):
        base = load(ctx.root/f'{index:04}'/(date+'_A.json.gz'))
        A = base['context']['A']
        starts = set()
        if families == {'water_heater'}:
            # Targeted search for preparation inside the event before normal A
            # heating starts. This is an ordering heuristic, not a new action.
            for r in A['controls']:
                if r['kind']=='tank_setpoint' and 0<=r['start_min']<1440:
                    starts.update(r['start_min']-delta for delta in (10,20,30))
        else:
            for r in A['tasks']:
                if r['kind'] in families and 0<=r['start_min']<1440:
                    starts.update(s for s in GRID if r['start_min']-120<=s<=r['end_min']+60)
        starts &= set(GRID)
        starts.discard(1080)
        for start in sorted(starts,key=lambda s:(abs(s-1080),s)):
            needed={k for k in keys if len(seen[k])<dates_per_cell and date not in seen[k]}
            if not needed:
                break
            base,bound,c,cfg=scene_context(ctx,index,date,start)
            g, raw = root_catalogue(c,cfg)
            declared.update(x['key'] for x in raw if x['admissible_raw_alternatives'])
            matching=[x for x in raw if x['key'] in needed and x['admissible_raw_alternatives']]
            successes=[]
            for cell in matching:
                row=complete_cell(c,cfg,g,cell)
                if row is None:continue
                record_raw_cells(dict(factors=g['descriptors'],native_domains=g['values'],rows=[row]))
                if cell['key'] not in row['raw_root_cells']:raise ValueError('WRONG_SCENE_CELL')
                scene_id=digest([ctx.pre['source_sha256'],index,date,cfg['event']])
                row['scene_event']=cfg['event'];row['scene_id']=scene_id
                row['scene_policy']='evening_scene_grid_v1'
                rows[row['id']]=row;seen[cell['key']].add(date);successes.append(cell['key'])
            scans.append(dict(date=date,event_start_min=start,matching=len(matching),qualified=len(successes)))
        if all(len(seen[k])>=dates_per_cell for k in keys):break
    payload=dict(index=index,role=role,country=house['country'],rows=sorted(rows.values(),key=lambda r:r['id']),
                 searches=scans,declared_extension_raw_cells=sorted(declared),
                 target_support={k:sorted(v) for k,v in seen.items() if v},unknown_not_infeasible=True)
    write_gzip(out/f'{index:04}.json.gz',payload)
    return dict(index=index,country=house['country'],role=role,rows=len(rows),scans=len(scans),
                cells=sum(bool(v) for v in seen.values()),date_slots=len({r['date'] for r in rows.values()}))

def discover(batch,households,native,out,workers=8,dates_per_cell=3):
    root=Path(out);root.mkdir(parents=True,exist_ok=False);(root/'candidates').mkdir()
    ctx=CompletionContext(batch,households,native)
    ledger=load(Path(batch)/'COHORT_COVERAGE_LEDGER.json.gz')
    targets={role:[c['key'] for c in cells if not c['selected_countries']] for role,cells in ledger.items()}
    protocol=dict(schema=SCHEMA,stage='pre_run',source_sha256=ctx.pre['source_sha256'],
        parent_batch=str(Path(batch).resolve()),target_ledger_sha256=hashlib.sha256((Path(batch)/'COHORT_COVERAGE_LEDGER.json.gz').read_bytes()).hexdigest(),
        targets=targets,allowed_event_start_min=list(GRID),event_duration_min=60,
        target_dates_per_cell_per_household=dates_per_cell,workers=workers,solver_seed=ctx.cfg['seed'],
        household_and_A_unchanged=True,native_action_grammar_unchanged=True,
        search='deterministic bounded root completion across existing dates and external event grid',
        event_scope='experimental evening scenarios;not observed grid-event distribution',
        physical_or_human_outcomes_used=False)
    save(root/'PRE_RUN.json',protocol)
    houses=[h for h in ctx.status if targets.get(h['role'])]
    logs=[]
    with ProcessPoolExecutor(max_workers=workers,initializer=init_worker,
            initargs=(batch,households,native,targets,root/'candidates',dates_per_cell)) as pool:
        for result in pool.map(discover_house,houses):
            logs.append(result)
            if len(logs)%10==0:print(json.dumps(dict(stage='scene_discovery',done=len(logs),total=len(houses),candidate_rows=sum(x['rows'] for x in logs))),flush=True)
    ctx.verify_source()
    save(root/'DISCOVERY.json',dict(schema=SCHEMA,households=logs,complete=True,
        rows=sum(x['rows'] for x in logs),unresolved_is_not_infeasible=True))
    return root

def allocate(batch, discovered, *, deterministic_time=30.0, max_changed_per_household=4):
    from ortools.sat.python import cp_model
    from .cohort_coverage import state_from_ledger
    root=Path(discovered);state=state_from_ledger(batch)
    extras={};indices=set()
    for p in sorted((root/'candidates').glob('*.json.gz')):
        d=load(p)
        if d['rows']:extras[d['index']]=d['rows'];indices.add(d['index'])
    candidates=[];old_ids=set();by_house=defaultdict(list);by_slot=defaultdict(list)
    by_cell_country=defaultdict(list);by_token=defaultdict(list)
    fixed=defaultdict(Counter); old_country=defaultdict(Counter)
    for slot,s in state['slots'].items():
        for key in s['row']['raw_root_cells']:
            old_country[(s['role'],key)][s['country']]+=1
            if s['index'] not in indices:fixed[(s['role'],key)][s['country']]+=1
        old_ids.add(s['row']['id'])
    for index in sorted(indices):
        house=next(h for h in state['rows'] if h['index']==index)
        # Existing complete witnesses allow compensating changes at the same
        # household's other dates, keeping all prior basic coverage tokens.
        rows={r['id']:r for d in catalogues_with_extras(Path(batch)/f'{index:04}') for r in d['rows']}
        rows.update({r['id']:r for r in extras[index]})
        rows.update({s['row']['id']:s['row'] for s in state['slots'].values() if s['index']==index})
        for r in sorted(rows.values(),key=lambda r:r['id']):
            j=len(candidates);candidates.append((house,r));by_house[index].append(j);by_slot[(index,r['date'])].append(j)
            for key in r['raw_root_cells']:by_cell_country[(house['role'],key,house['country'])].append(j)
            for token in sorted(simple_tokens(r)):by_token[(index,token)].append(j)
    model=cp_model.CpModel();x=[model.new_bool_var('row_'+str(j)) for j in range(len(candidates))]
    for slot,js in sorted(by_slot.items()):model.add_exactly_one(x[j] for j in js)
    for index in sorted(indices):
        for token in sorted(state['required'][index]):
            model.add(sum(x[j] for j in by_token[(index,token)])>=1)
        model.add(sum(x[j] for j in by_house[index] if candidates[j][1]['id'] not in old_ids)<=max_changed_per_household)
    missing_constraints=0
    for role,entries in sorted(state['raw'].items()):
        for key,original_countries in sorted(entries.items()):
            # Preserve attained country count and fill every original raw cell.
            old_have=sum(v>0 for v in old_country[(role,key)].values())
            required=max(1,min(len(original_countries),2,old_have))
            country_hits=[]
            countries=set(original_countries)|{c for rr,k,c in by_cell_country if rr==role and k==key}
            for country in sorted(countries):
                if fixed[(role,key)][country]>0:country_hits.append(1);continue
                js=by_cell_country.get((role,key,country),[])
                if not js:continue
                hit=model.new_bool_var('cell_'+str(missing_constraints)+'_'+country);missing_constraints+=1
                model.add_max_equality(hit,[x[j] for j in js]);country_hits.append(hit)
            model.add(sum(country_hits)>=required)
    changes=sum(x[j] for j,(_,r) in enumerate(candidates) if r['id'] not in old_ids)
    scene_changes=sum(x[j] for j,(_,r) in enumerate(candidates) if r.get('scene_policy'))
    model.minimize(changes)
    solver=cp_model.CpSolver();solver.parameters.num_search_workers=1;solver.parameters.random_seed=load(root/'PRE_RUN.json').get('solver_seed',20261022) if (root/'PRE_RUN.json').exists() else 20261022
    solver.parameters.max_deterministic_time=deterministic_time
    status=solver.solve(model);name=solver.status_name(status)
    result=dict(schema=SCHEMA,stage='allocation',status=name,candidates=len(candidates),active_households=len(indices),
        original_raw_targets=sum(len(x) for x in state['raw'].values()),base_tokens_preserved=True,
        max_changed_per_household=max_changed_per_household,deterministic_time_budget=deterministic_time,
        objective='minimize changed questions subject to all original targets and per-household coverage',
        optimal=status==cp_model.OPTIMAL,global_all_possible_scenes_optimality_claimed=False)
    if status in (cp_model.FEASIBLE,cp_model.OPTIMAL):
        chosen=[(h,r) for j,(h,r) in enumerate(candidates) if solver.value(x[j])]
        result.update(changed_questions=int(solver.value(changes)),event_scene_questions=int(solver.value(scene_changes)),
            changed_households=len({h['index'] for h,r in chosen if r['id'] not in old_ids}))
        write_gzip(root/'ALLOCATION.json.gz',[dict(index=h['index'],country=h['country'],role=h['role'],row=r) for h,r in chosen])
    save(root/'ALLOCATION_RESULT.json',result);print(json.dumps(result),flush=True);return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('phase',choices=['discover','allocate'])
    p.add_argument('--batch',required=True,type=Path);p.add_argument('--out',required=True,type=Path)
    p.add_argument('--households',type=Path);p.add_argument('--native-source',type=Path)
    p.add_argument('--workers',type=int,default=8);p.add_argument('--dates-per-cell',type=int,default=3)
    p.add_argument('--deterministic-time',type=float,default=30);p.add_argument('--max-changed-per-household',type=int,default=4)
    a=p.parse_args()
    if not 1<=a.workers<=8 or not 1<=a.dates_per_cell<=10:p.error('invalid bounded search budget')
    if a.phase=='discover':
        if a.households is None or a.native_source is None:p.error('discovery requires households and native source')
        discover(a.batch,a.households,a.native_source,a.out,a.workers,a.dates_per_cell)
    else:allocate(a.batch,a.out,deterministic_time=a.deterministic_time,max_changed_per_household=a.max_changed_per_household)
if __name__=='__main__':main()
