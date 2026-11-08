"""Source pool to household, life calendar, controls, service contracts and cards."""
from pathlib import Path
from collections import Counter,defaultdict
from itertools import combinations
from .quotas import largest_remainder
from copy import deepcopy
import hashlib,json,platform,sys,traceback
from .engine import load_engine,bind_sources,initialize,build_final,check_case,digest
from .quotas import plan
from .allocation import allocate
from ..required_controls import validate_household,allowed_masks,FUNCTIONS

def code_identity():
    root=Path(__file__).resolve().parent
    files=[p for p in root.rglob('*.py') if '__pycache__' not in p.parts]
    files.extend(p for p in (root/'RULES.json',root/'ROLES.json') if p.exists())
    files.extend((root/'_engine').rglob('*.json'))
    files.extend((root.parent/'required_controls.py',root.parent/'SOURCES.json'))
    return {str(p.relative_to(root.parent)):digest(p) for p in sorted(files)}

def runtime_versions():
    import numpy,scipy,pyreadstat,pandas
    return {m.__name__:m.__version__ for m in (numpy,scipy,pyreadstat,pandas)}

DEFAULT_COVERAGE={'country_all_masks':True,'role_minimum_pattern_count':2,'cell_function_minimum':2,'nonfull_function_minimum':20,'nonfull_pair_minimum':10}
def read_rows(p):
    with Path(p).open() as f:return [json.loads(s) for s in f if s.strip()]
def save(p,x):Path(p).parent.mkdir(exist_ok=True,parents=True);Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2,sort_keys=True)+'\n')
def write_rows(p,x):Path(p).parent.mkdir(exist_ok=True,parents=True);Path(p).write_text(''.join(json.dumps(c,ensure_ascii=False,sort_keys=True)+'\n' for c in x))
def rank(config,*values):return hashlib.sha256(json.dumps([str(config['seed']),*values],ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def select(engine,pool,config,matrix,raw_sources,out):
    a=engine.a;selected=[];used=set();ordinal_map={};rejected=[]
    def source_key(row):return row['source']['dataset'],row['source']['household_key']
    def attempt(row,role,ordinal,pair=None):
        errors=[]
        if row['source']['dataset']=='ECA2025' and role=='F' and row['source_record_fields']['off_street_parking']!='Yes':return None
        for alt in range(int(config.get('profile_alternatives',4))):
            try:
                c=initialize(engine,row,role,ordinal,alt,pair);check_case(engine,c,c,raw_sources)
                c['household']['completion_design']['rejected_design_reasons']=errors
                ordinal_map[c['case_id']]=ordinal;return c
            except (ValueError,AssertionError,KeyError,TypeError,StopIteration) as e:errors.append(type(e).__name__+':'+str(e))
        rejected.append({'source_key':list(source_key(row)),'role':role,'reasons':errors});return None
    def fail(country,role,requested,got):
        save(out/'SELECTION_FAILURE.json',{'status':'selection_exhausted_under_declared_deterministic_rule','country':country,'role':role,'requested':requested,'selected':got,
           'is_proof_of_global_infeasibility':False,'source_households_duplicated':False,'rejections':rejected})
        raise ValueError(f'SOURCE_ROLE_SELECTION_SHORTFALL:{country}/{role}:{got}/{requested}; see SELECTION_FAILURE.json')
    for co in config['countries']:
        candidates=[r for r in pool if r['source']['country']==co]
        if len(candidates)<sum(matrix[co].values()):fail(co,'all',sum(matrix[co].values()),len(candidates))
        target=matrix[co];paired=0
        if config.get('pair_CD',True):
            groups=defaultdict(list)
            for row in candidates:
                sig=[(row['devices'][k]['value'],row['devices'][k]['status']) for k in a.KEY.values()]
                groups[json.dumps([row['block'],sig],ensure_ascii=False,sort_keys=True)].append(row)
            pairs=[]
            for group in groups.values():
                group=sorted(group,key=lambda r:rank(config,'pair-source',r['pool_id']));pairs.extend(zip(group[::2],group[1::2]))
            for left,right in sorted(pairs,key=lambda p:rank(config,'pair-order',co,p[0]['pool_id'],p[1]['pool_id'])):
                if paired==target['C']:break
                pair='CD-'+co+'-'+rank(config,left['pool_id'],right['pool_id'])[:16]
                c=attempt(left,'C',paired,pair);d=attempt(right,'D',paired,pair)
                if c is None or d is None:continue
                selected.extend((c,d));used.update((source_key(left),source_key(right)));paired+=1
            if paired!=target['C']:fail(co,'paired_C_D',target['C'],paired)
        roles=('E','B','A','F','D') if config.get('pair_CD',True) else ('E','B','A','F','C','D')
        for role in roles:
            needed=target[role]-(paired if role=='D' else 0);done=0
            def priority(r):
                job=r['source_person']['employment']['value']
                return int(job in a.WORK) if role in 'AF' else 0
            available=sorted((r for r in candidates if source_key(r) not in used),key=lambda r:(-priority(r),rank(config,'source-order',co,role,r['pool_id'])))
            for row in available:
                if done==needed:break
                c=attempt(row,role,done)
                if c is not None:selected.append(c);used.add(source_key(row));done+=1
            if done!=needed:fail(co,role,needed,done)
        print(json.dumps({'selected_country':co,'households':sum(c['source']['country']==co for c in selected)}),flush=True)
    selected.sort(key=lambda c:(config['countries'].index(c['source']['country']),c['benchmark_role'],c['case_id']))
    save(out/'SELECTION_REPORT.json',{'source_records_unique':len(used)==len(selected),'rejected_source_role_attempts':rejected,
      'selection_uses_later_AB_or_human_outcomes':False,'pairing_scope':'same declared block/device signature; distinct source households; no causal role-effect claim'})
    return selected,ordinal_map

def population(cases,baseline,config,country_counts,role_counts,matrix):
    if len(cases)!=config['households'] or len({c['case_id'] for c in cases})!=len(cases):raise ValueError('COHORT_ID_OR_SIZE_MISMATCH')
    if len({(c['source']['dataset'],c['source']['household_key']) for c in cases})!=len(cases):raise ValueError('SOURCE_HOUSEHOLD_REUSED')
    if Counter(c['source']['country'] for c in cases)!=Counter(country_counts) or Counter(c['benchmark_role'] for c in cases)!=Counter(role_counts):raise ValueError('COHORT_QUOTA_MISMATCH')
    cov=config['coverage'];report={'by_country':{},'by_role':{},'all_AC_present_and_controlled':True,'all_declared_coverage_targets_passed':True}
    cardinality=largest_remainder(len(cases),{'4':1,'5':1,'6':1})
    if len(cases)==1000 and config.get('v9_cardinality_compatibility',False):cardinality={'4':333,'5':333,'6':334}
    actual=Counter(str(c['household']['controlled_function_count']) for c in cases)
    if actual!=Counter(cardinality):raise ValueError('GLOBAL_CONTROL_CARDINALITY_MISMATCH')
    report['cardinality_counts']=dict(actual)
    pairs=defaultdict(list)
    for c in cases:
        validate_household(c)
        if c.get('cd_pair_id'):pairs[c['cd_pair_id']].append(c)
        original=baseline[c['case_id']]
        for k in original:
            if k not in ('household','household_provenance') and original[k]!=c[k]:raise ValueError('NORMALIZED_SOURCE_FACT_CHANGED:'+k)
        if any(k in c for k in ('human_answer','acceptance_label','observed_response')):raise ValueError('OUTCOME_IN_HOUSEHOLD_INPUT')
    for co in config['countries']:
        current=[c for c in cases if c['source']['country']==co];patterns=Counter(tuple(c['household']['controlled_function_ids']) for c in current)
        if Counter(c['benchmark_role'] for c in current)!=Counter(matrix[co]):raise ValueError('COUNTRY_ROLE_CELL_QUOTA:'+co)
        missing=[list(m) for m in allowed_masks() if not patterns[m]]
        if cov['country_all_masks'] and missing:raise ValueError('COUNTRY_CONTROL_PATTERN_MISSING:'+co)
        for r in 'ABCDEF':
            cell=[c for c in current if c['benchmark_role']==r]
            if not cell:continue
            sizes=Counter(c['household']['controlled_function_count'] for c in cell)
            if max([sizes[n] for n in (4,5,6)])-min([sizes[n] for n in (4,5,6)])>1:raise ValueError('CELL_CARDINALITY_IMBALANCE')
            exposures=Counter(f for c in cell for f in c['household']['controlled_function_ids'])
            if min(exposures[f] for f in FUNCTIONS)<cov['cell_function_minimum']:raise ValueError('CELL_FUNCTION_COVERAGE')
        report['by_country'][co]={'households':len(current),'control_patterns_covered':len(patterns),'missing_patterns':missing}
    for r in 'ABCDEF':
        current=[c for c in cases if c['benchmark_role']==r];patterns=Counter(tuple(c['household']['controlled_function_ids']) for c in current)
        if any(patterns[m]<cov['role_minimum_pattern_count'] for m in allowed_masks(r)):raise ValueError('ROLE_PATTERN_COVERAGE:'+r)
        sizes=Counter(c['household']['controlled_function_count'] for c in current)
        if max(sizes[n] for n in (4,5,6))-min(sizes[n] for n in (4,5,6))>1:raise ValueError('ROLE_CARDINALITY_IMBALANCE')
        nonfull=[c['household']['controlled_function_ids'] for c in current if c['household']['controlled_function_count']<6]
        fc=Counter(f for mask in nonfull for f in mask)
        pc=Counter(pair for mask in nonfull for pair in combinations(mask,2))
        if any(fc[f]<cov['nonfull_function_minimum'] for f in FUNCTIONS):raise ValueError('NONFULL_FUNCTION_COVERAGE:'+r)
        if any(pc[p]<cov['nonfull_pair_minimum'] for p in combinations(FUNCTIONS,2)):raise ValueError('NONFULL_PAIR_COVERAGE:'+r)
        report['by_role'][r]={'nonfull_function_minimum_actual':min(fc[f] for f in FUNCTIONS),'nonfull_pair_minimum_actual':min(pc[p] for p in combinations(FUNCTIONS,2)),'households':len(current),'patterns_covered':len(patterns),'minimum_pattern_count':min((patterns[m] for m in allowed_masks(r)),default=0)}
    if config.get('pair_CD',True):
        if len(pairs)!=role_counts['C']:raise ValueError('CD_PAIR_TOTAL')
        for p,rows in pairs.items():
            if len(rows)!=2 or {c['benchmark_role'] for c in rows}!={'C','D'} or rows[0]['matching_block']!=rows[1]['matching_block'] or rows[0]['household']['controlled_function_ids']!=rows[1]['household']['controlled_function_ids']:raise ValueError('CD_PAIR_MISMATCH:'+p)
    report['C_D_pairs']=len(pairs)
    return report

def generate(pool_file,config_file,out,data_config=None):
    out=Path(out)
    if out.exists():raise ValueError('OUTPUT_EXISTS; choose a fresh directory')
    config=json.loads(Path(config_file).read_text());config['coverage']={**DEFAULT_COVERAGE,**config.get('coverage',{})}
    country_counts,role_counts,matrix=plan(config)
    pool=read_rows(pool_file);keys=[(r['source']['dataset'],r['source']['household_key']) for r in pool]
    if len(set(keys))!=len(keys):raise ValueError('INPUT_POOL_CONTAINS_DUPLICATE_SOURCE_RECORDS')
    expected=config.get('expected_pool_sha256')
    if expected and digest(pool_file)!=expected:raise ValueError('INPUT_POOL_HASH_MISMATCH')
    synthetic=all(r.get('synthetic_fixture') is True for r in pool)
    if any(r.get('synthetic_fixture') is True for r in pool) and not synthetic:raise ValueError('SYNTHETIC_AND_SURVEY_RECORDS_MUST_NOT_MIX_IN_ONE_COHORT')
    pins_at_start=code_identity()
    if not synthetic and config.get('raw_source_audit_required',True) and data_config is None:raise ValueError('RAW_SOURCE_CONFIG_REQUIRED_FOR_FORMAL_SURVEY_COHORT')
    out.mkdir(parents=True);save(out/'CONFIG.json',config);save(out/'QUOTAS.json',{'country_counts':country_counts,'role_counts':role_counts,'country_role_quotas':matrix})
    try:
        engine=load_engine(config['seed']);sources=None
        if data_config and not synthetic:_,_,sources=bind_sources(engine,data_config,out)
        if not synthetic and config.get('raw_source_audit_required',True) and sources is None:raise ValueError('RAW_SOURCE_CONFIG_REQUIRED_FOR_FORMAL_SURVEY_COHORT')
        selected,ordinals=select(engine,pool,config,matrix,sources,out)
        write_rows(out/'selected_cohort.jsonl',selected);save(out/'ordinals.json',ordinals)
        assignments,allocation=allocate(engine,selected,config,role_counts);save(out/'control_assignment.json',assignments);save(out/'CONTROL_ALLOCATION.json',allocation)
        counter=Counter();cases=[]
        for old in selected:
            c=build_final(engine,old,assignments[old['case_id']],ordinals[old['case_id']],counter);check_case(engine,c,old,sources);validate_household(c);cases.append(c)
        pop=population(cases,{c['case_id']:c for c in selected},config,country_counts,role_counts,matrix);save(out/'POPULATION_AUDIT.json',pop)
        write_rows(out/'household_cases.jsonl',cases)
        write_rows(out/'groups.jsonl',[{'case_id':c['case_id'],'source_household_group':c['source']['dataset']+':'+c['source']['household_key'],
           'split_group':c.get('cd_pair_id') or c['source']['dataset']+':'+c['source']['household_key']} for c in cases])
        if code_identity()!=pins_at_start:raise ValueError('GENERATOR_CODE_CHANGED_DURING_RUN')
        manifest={'generator_code_sha256':pins_at_start,'runtime_versions':runtime_versions(),'schema':'eb.household.generator.run.v1','status':'passed','households':len(cases),'country_counts':country_counts,'role_counts':role_counts,
          'country_role_quotas':matrix,'seed':str(config['seed']),'synthetic_fixture_only':synthetic,'raw_sources_independently_checked':sources is not None,
          'manifest_sha256':digest(out/'household_cases.jsonl'),'pool_sha256':digest(pool_file),'actual_AB_questions':0,'actual_physical_results':0,'actual_human_answers':0,
          'required_control_functions':['AC'],'coverage_requirements':config['coverage'],'AC_present_and_controlled':len(cases),
          'acceptance_scope':'household/role/life/control/service input, not physical or human validity','python':sys.version,'platform':platform.platform(),
          'files_sha256':{p.name:digest(p) for p in out.iterdir() if p.is_file() and p.suffix in ('.json','.jsonl')}}
        save(out/'MANIFEST.json',manifest);print(json.dumps({k:v for k,v in manifest.items() if k not in ('files_sha256','country_role_quotas')},ensure_ascii=False),flush=True)
        return manifest
    except Exception as e:
        save(out/'FAILURE.json',{'status':'failed','reason':str(e),'traceback':traceback.format_exc(),'source_records_duplicated':False,'failed_run_not_formal_data':True})
        raise

def verify(run_dir,data_config=None,replay=True):
    out=Path(run_dir);manifest=json.loads((out/'MANIFEST.json').read_text());config=json.loads((out/'CONFIG.json').read_text())
    for name,pin in manifest['files_sha256'].items():
        if digest(out/name)!=pin:raise ValueError('FROZEN_RUN_FILE_CHANGED:'+name)
    if manifest.get('generator_code_sha256') and code_identity()!=manifest['generator_code_sha256']:raise ValueError('GENERATOR_VERSION_DIFFERS_FROM_FROZEN_RUN')
    cases=read_rows(out/'household_cases.jsonl');selected=read_rows(out/'selected_cohort.jsonl');base={c['case_id']:c for c in selected}
    engine=load_engine(config['seed']);sources=None
    if data_config and not manifest['synthetic_fixture_only']:_,_,sources=bind_sources(engine,data_config,out/'verification_workspace')
    if manifest['raw_sources_independently_checked'] and sources is None:raise ValueError('RAW_SOURCE_CONFIG_REQUIRED_TO_REPLAY_FULL_AUDIT')
    for c in cases:check_case(engine,c,base[c['case_id']],sources);validate_household(c)
    quota=json.loads((out/'QUOTAS.json').read_text())
    population(cases,base,config,quota['country_counts'],quota['role_counts'],quota['country_role_quotas'])
    if replay:
        assignments=json.loads((out/'control_assignment.json').read_text());ordinals=json.loads((out/'ordinals.json').read_text());counter=Counter()
        rebuilt=[build_final(engine,c,assignments[c['case_id']],ordinals[c['case_id']],counter) for c in selected]
        payload=''.join(json.dumps(c,ensure_ascii=False,sort_keys=True)+'\n' for c in rebuilt).encode()
        if hashlib.sha256(payload).hexdigest()!=manifest['manifest_sha256']:raise ValueError('CROSS_PROCESS_FINAL_REPLAY_DIFFERS')
    result={'passed':True,'households_checked':len(cases),'AC_present_and_controlled':len(cases),'raw_sources_checked':sources is not None,
      'final_replay_byte_identical':bool(replay),'synthetic_fixture_only':manifest['synthetic_fixture_only'],'actual_AB_questions':0,'actual_physical_results':0,'actual_human_answers':0}
    print(json.dumps(result),flush=True);return result
