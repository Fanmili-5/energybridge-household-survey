"""New opt-in entry point; A sources, portraits, and online release are read-only."""
import copy
import datetime as dt
import importlib.metadata
import time
import resource
import sys
from pathlib import Path
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from ..common import read,save,sha,digest,seal,bound
from ..model import apply
from .contract import config,code_hash,dates
from .candidates import generate_day
from .selection import assign,concepts,equivalent_frame


def _job(args):
    item,cfg=args
    start=time.perf_counter()
    ledger=None
    try:
        c=read(item['context_path']);profile=read(item['portrait_path']) if item.get('portrait_path') else None
        from .opportunities import declare,coverage
        ledger=declare(c,cfg)  # Before the generator can reveal its catalogue.
        result=generate_day(c,cfg,profile)
        result['input_opportunities']=ledger
        result['independent_opportunity_coverage']=coverage(ledger,result)
        from .independent import audit
        failures=[]
        for row in result.get('rows',[]):
            errors=audit(c,c['A'],apply(c['A'],row['patches']))
            if errors:failures.append(dict(id=row['id'],errors=errors))
        result['independent_engineering_errors']=failures
        result['telemetry']=dict(wall_seconds=time.perf_counter()-start,
            worker_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024),
            rss_scope='worker_lifetime_high_watermark;not_per_job_allocation',
            request_records=result.get('raw_requests',0),materializations=result.get('materialized_requests',0),
            oracle_calls=result.get('oracle_calls',0))
        if failures:result['status']='independent_engineering_failure;catalogue_retained_not_selected'
        return result
    except Exception as error:
        result=dict(status='engineering_exception',rows=[],engineering_diagnostics=[dict(error=type(error).__name__+':'+str(error))],
                    A_input_unchanged=True,physical_status='not_computed',
                    input_opportunity_status='preserved' if ledger is not None else 'source_not_readable;unknown_not_zero')
        if ledger is not None:
            result['input_opportunities']=ledger
            result['independent_opportunity_coverage']=coverage(ledger,result)
        return result


def service_context(c):
    """Judgment facts independent of calendar labels and opaque case IDs."""
    rows=[]
    for n in c['needs']:
        if n.get('release_min',0)>=2880 or n.get('deadline_min',0)<=0:continue
        row={k:n[k] for k in ('kind','release_min','deadline_min','quantity','unit','required_departure_soc','target_C') if k in n}
        rows.append(row)
    return sorted(rows,key=lambda r:digest(r))


def build(inputs,out,configuration=None,workers=1):
    inputs=Path(inputs).resolve();out=Path(out).resolve();batch=read(inputs);cfg=config(configuration)
    if batch['schema']!='eb.unified.inputs.v1' or batch['mode'] not in ('audit_frozen','fresh_generation'):
        raise ValueError('UNKNOWN_UNIFIED_INPUT_MODE')
    records=copy.deepcopy(batch['records'])
    for r in records:
        for k in ('context_path','portrait_path'):
            if r.get(k) and not Path(r[k]).is_absolute():r[k]=str(bound(inputs.parent,r[k]).resolve())
    keys=[(r['household_id'],r['date']) for r in records]
    if len(set(keys))!=len(keys):raise ValueError('DUPLICATE_HOUSEHOLD_DATE')
    if any(n!=10 for n in Counter(h for h,d in keys).values()):raise ValueError('TEN_INPUT_DATES_PER_HOUSEHOLD')
    sources={str(inputs):sha(inputs)}
    for r in records:
        if batch['mode']=='fresh_generation':
            context=read(r['context_path']);portrait=read(r['portrait_path'])
            if context.get('source',{}).get('mode')!='fresh_generation' or context['source'].get('portrait_sha256')!=digest(portrait):
                raise ValueError('FRESH_A_PORTRAIT_BINDING_MISMATCH')
        for key in ('context_path','portrait_path'):
            if not r.get(key):continue
            p=Path(r[key]).resolve()
            if out==p or out.is_relative_to(p.parent):raise ValueError('OUTPUT_INSIDE_FROZEN_SOURCE')
            sources[str(p)]=sha(p)
    out.mkdir(parents=True,exist_ok=False)
    runtime={k:importlib.metadata.version(k) for k in ('ortools','numpy','scipy')}
    frozen_code=code_hash()
    save(out/'PRE_GENERATION.json',dict(schema=cfg['schema'],mode=batch['mode'],configuration=cfg,
        source_sha256=sources,code_sha256=frozen_code,runtime=runtime,
        A_rewritten=False,physical_runs=0,online_changed=False,population1000_started=False,
        actual_outcomes_or_human_answers_used=False))
    jobs=[(r,cfg) for r in records];summaries=[];allrows=[];errors=[];frame_aliases={}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for item,result in zip(records,pool.map(_job,jobs,buffersize=max(1,workers*2))):
            c=read(item['context_path']);sc=service_context(c)
            for row in result.get('rows',[]):row['service_context']=sc
            name='catalogues/'+digest([item['household_id'],item['date']])[:24]+'.json.gz'
            save(out/name,result)
            eligible=result.get('rows',[]) if result['status']=='candidate_catalogue' else []
            frame,aliases=equivalent_frame(eligible,cfg);allrows.extend(frame);frame_aliases.update(aliases)
            coverage=result.get('coverage',{}).get('coverage',[])
            summary=dict(household_id=item['household_id'],date=item['date'],path=name,status=result['status'],
                eligible=len(eligible),native=result.get('native_alternatives',0),raw=result.get('raw_requests',0),
                interaction_targets=len(coverage),interaction_status=dict(Counter(r['status'] for r in coverage)),
                witnessed=sum(r['witness_row'] is not None for r in coverage),
                engineering=len(result.get('engineering_diagnostics',[])),
                unrelated=len(result.get('relevance_diagnostics',[])),oracle_calls=result.get('oracle_calls',0))
            summary['independent_engineering_errors']=len(result.get('independent_engineering_errors',[]))
            summary['telemetry']=result.get('telemetry',{})
            oc=result.get('independent_opportunity_coverage',{})
            summary['mechanism_opportunities']={k:oc.get(k) for k in ('potential','witnessed','selected')}
            summaries.append(summary)
            if not eligible:errors.append(summary)
            save(out/'PROGRESS.json',summaries)
            print(item['household_id'],item['date'],'eligible',summary['eligible'],'witnessed',summary['witnessed'],'/',len(coverage),flush=True)
    selection=assign(allrows,cfg);save(out/'SELECTION.json',selection)
    save(out/'EQUIVALENT_ALIASES.json.gz',frame_aliases)
    selected=set(selection['selected_ids']);materials=[]
    for item in records:
        c=read(item['context_path']);profile=read(item['portrait_path']) if item.get('portrait_path') else None
        candidates=[r for r in allrows if r['household_id']==item['household_id'] and r['date']==item['date'] and r['id'] in selected]
        for row in candidates:
            b=apply(c['A'],row['patches'])
            materials.append(dict(household_id=item['household_id'],date=item['date'],id=row['id'],
                A=c['A'],B=b,household_profile=profile,proposal=row,
                participant_family_text=__import__('benchmark.family_generation.portrait_v3',fromlist=['render']).render(profile) if profile else None,
                binding=dict(full_A_sha256=digest(c['A']),full_B_sha256=digest(b),context_sha256=digest(c),portrait_sha256=digest(profile)),
                presentation='proposal_before_outcomes;not_executed;confirmation_required',
                physical_outcomes=None,human_acceptance=None,human_score=None,human_reason=None,
                physical_status='not_computed;old_results_not_reused'))
            from .materials import project
            materials[-1]['questionnaire_context']=project(c,profile,row,b)
    save(out/'MATERIALS.json.gz',materials);save(out/'GENERATION.json',summaries)
    changed=[p for p,s in sources.items() if sha(p)!=s]
    if changed:raise ValueError('FROZEN_SOURCE_CHANGED:'+str(changed))
    if code_hash()!=frozen_code:raise ValueError('CODE_CHANGED_DURING_GENERATION;KEEP_DIAGNOSTICS_AND_RERUN_NEW_VERSION')
    report=dict(schema='eb.unified.validation.v1',households=len({h for h,d in keys}),slots=len(records),
        slots_with_candidates=sum(r['eligible']>0 for r in summaries),selected=len(materials),
        engineering_diagnostics=sum(r['engineering'] for r in summaries),
        interaction_targets=sum(r['interaction_targets'] for r in summaries),
        witnessed=sum(r['witnessed'] for r in summaries),
        unknown_or_unexplored=sum(r['interaction_status'].get('unknown',0)+r['interaction_status'].get('unexplored',0) for r in summaries),
        unresolved_slots=errors,source_files_verified=len(sources),source_files_changed=changed,
        physical_runs=0,online_changed=False,population1000_started=False,main_updated=False,
        scientific_claim='finite_grammar_engineering_and_coverage_only;human_and_physical_validity_unverified')
    save(out/'REPORT.json',report);seal(out,dict(schema=cfg['schema'],code_sha256=code_hash(),physical_runs=0))
    return report


def fresh_life(spec,world,portrait,out,cfg=None):
    from .a_solver import compile_life,solve
    cfg=config(cfg);problem=compile_life(spec,world);result=solve(problem,portrait,seed=cfg['seed'],deterministic_time=cfg['A_deterministic_time'],target_mode=cfg['A_target_context_mode'])
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    save(out/'PROBLEM.json.gz',{k:v for k,v in problem.items() if k!='legacy_comparator'})
    save(out/'LEGACY_COMPARATOR.json.gz',problem['legacy_comparator']);save(out/'A.json.gz',result)
    seal(out,dict(schema='eb.unified.fresh_A.v1',source='life_inputs_only',physical_runs=0))
    return result


def fresh_context(problem,result,date,portrait,cfg):
    """Adapt only newly generated life/A to the existing collection contract."""
    from ..collection_thermal import AC_CONTRACT
    from ..information import information_set
    from ..sampling import command_hash
    if result['status']!='feasible':raise ValueError('FRESH_A_NOT_EXECUTABLE')
    base=(dt.date.fromisoformat(date)-dt.date.fromisoformat(problem['anchor'])).days*1440
    def shift(row):return {**copy.deepcopy(row),'start_min':row['start_min']-base,'end_min':row['end_min']-base}
    A={k:[shift(r) for r in rows] for k,rows in result['A'].items()}
    # A row patch uses one identity namespace for the heterogeneous controls
    # collection. Non-EV rows also need identities; no command value/time changes.
    for row in A['controls']:
        row.setdefault('_unified_id','control:'+digest(row)[:24])
    devices=copy.deepcopy(problem['world']['devices'])
    for d in devices:d.setdefault('types',[d['kind']])
    windows={};occupancy={};reservations=[]
    for day in problem['days'].values():
        for mid,ws in day['operator_windows'].items():windows.setdefault(mid,[]).extend([[a-base,z-base] for a,z in ws])
        for cal in day['calendars'].values():
            for e in cal:
                if e['location']=='home':occupancy.setdefault(e['room_id'],[]).append([day['base_min']+e['start_min']-base,day['base_min']+e['end_min']-base])
        reservations.extend({**r,'start_min':day['base_min']+r['start_min']-base,'end_min':day['base_min']+r['end_min']-base} for r in day['reservations'])
    needs=[]
    for j in problem['jobs']:
        n={k:copy.deepcopy(v) for k,v in j.items() if k not in ('policy','preferred_start_min','date')}
        n.update({k:copy.deepcopy(j['policy'][k]) for k in ('duration_min','maximum_preload_wait_min','maximum_retrieval_wait_min','timer_allowed','machine_windows_min')})
        if j.get('automatic_child_need_id'):
            n.update(wash_only_delivery='auto combo wash then dry',wearable_clothes_ready_at_program_end=False)
        if j.get('automatic_parent_need_id'):
            n.update(upstream_need_id=j['automatic_parent_need_id'],batch_id=j['automatic_parent_need_id'])
        n['release_min']-=base;n['deadline_min']-=base;needs.append(n)
    needs.extend({**n,'release_min':n['release_min']-base,'deadline_min':n['deadline_min']-base}
        for n in problem['nonprogram_requirements'])
    authority=dict(schema='eb.ab_authority.v1',immutable_operator_ids=[],origin='source_qualification;proposal_not_execution_consent',assets={})
    for d in devices:
        authority['assets'][d['asset_id']]=dict(target_control_authorized=d.get('target_control_authorized',False),
            authorized_operator_ids=[m['member_id'] for m in problem['world']['members'] if d['asset_id'] in m['can_operate_asset_ids'] and m['household_id'] in d['using_household_ids']])
    c=dict(schema='eb.ab_generation.context.v3',household_id=problem['household_id'],case_id=problem['household_id']+'__'+date+'__unified-v1',
        date=date,decision_min=480,horizon_min=[480,1920],A=A,devices=devices,needs=needs,
        operator_windows=windows,occupancy=occupancy,reservations=reservations,authority=authority,
        events=[copy.deepcopy(cfg['event'])],tariff=[],event_meter_scope='modeled_controlled_equipment',assignment=dict(mode='fresh_candidates'),
        source=dict(mode='fresh_generation',A_source_sha256=result['input_sha256'],portrait_sha256=digest(portrait),physical_outputs_used=False))
    c['physical_ev_connections']=[shift(r) for r in result.get('physical_ev_connections',[])]
    if result.get('conditional_target_context'):
        targets=result['conditional_target_context']
        c['source']['conditional_target_context_sha256']=targets['sha256']
        c['baseline_target_context']=dict(version=targets['version'],
            rows=[copy.deepcopy(r) for r in targets['rows'] if r['source_date']==date],
            absolute_minute_anchor=problem['anchor'],
            meaning='conditional_household_soft_targets;not_personal_habit_or_execution_consent')
    if problem['world'].get('electrical'):
        source=problem['world']['electrical']
        c['electrical']=dict(schema='eb.ab_site_capacity.v1',
            **{k:copy.deepcopy(source[k]) for k in ('supply_W','background_upper_W','capacity_mode')},
            scope='whole_physical_dwelling_including_shared_context')
    c['reference']=dict(binding=dict(A_commands_sha256=command_hash(A),context_sha256=digest(c)),thermal={},
        ev_charging_steps=[shift(s) for s in result['ev_charging_steps']],
        information_set=information_set('offline_unexecuted_A_plan',480,[480,1920]),
        ac_control_contract=copy.deepcopy(AC_CONTRACT),
        baseline_admission=dict(status='CP_SAT_plan_only;not_physical_validation'))
    return c


def produce(life_batch,portraits,out,cfg=None,workers=1,date_manifest=None):
    """One production entry; freeze all dates/portraits before solving any A."""
    from benchmark.research_delivery.production import produce as uniform_production
    return uniform_production(life_batch,portraits,out,cfg,date_manifest,workers)
