"""Complete household -> native A/B -> coverage -> sealed material recipe.

All stages take explicit files. It creates no physical outcomes or human labels.
The pinned native1000 repair recipe is reproduced in the same stage order.
"""
import argparse,hashlib,json,os,subprocess,sys,time,math
from pathlib import Path
from .common import digest
from .generate_cohort import save
from .generate_native import implementation
from .cohort_coverage import load
from ..household_stage1.required_controls import validate_household

def validate_households(path,expected_sha=None):
    raw=Path(path).read_bytes();sha=hashlib.sha256(raw).hexdigest()
    if expected_sha and sha!=expected_sha:raise ValueError('HOUSEHOLD_INPUT_SHA256_MISMATCH')
    cases=[json.loads(line) for line in raw.splitlines() if line.strip()]
    if not cases or len({c['case_id'] for c in cases})!=len(cases):raise ValueError('HOUSEHOLD_IDS_EMPTY_OR_DUPLICATED')
    keys=[(c['source']['dataset'],c['source']['household_key']) for c in cases]
    if len(set(keys))!=len(keys):raise ValueError('HOUSEHOLD_SOURCE_RECORD_REUSED')
    for case in cases:validate_household(case)
    return sha,len(cases)

def compare_plans(batch,reference):
    def index(root):
        rows=[json.loads(line) for line in (Path(root)/'PAIR_INDEX.jsonl').read_text().splitlines() if line.strip()]
        out={(r['case_id'],r['date']):(r['A_sha256'],r['B_sha256']) for r in rows}
        if len(out)!=len(rows):raise ValueError('PAIR_INDEX_DUPLICATE_CASE_DATE')
        return out
    actual,expected=index(batch),index(reference)
    keys_equal=set(actual)==set(expected);common=set(actual)&set(expected)
    a=sum(actual[k][0]==expected[k][0] for k in common);b=sum(actual[k][1]==expected[k][1] for k in common)
    return dict(schema='eb.native_plan_reproduction.v1',actual_pairs=len(actual),reference_pairs=len(expected),
        case_date_keys_equal=keys_equal,A_hashes_equal=a,B_hashes_equal=b,
        all_current_A_B_plans_equal=keys_equal and a==len(actual) and b==len(actual),
        scope='actual plans only;not gzip bytes,metadata identity,physics or labels')

def run(args):
    for name in ('out','households','pool','household_config','data_config','reference','native_source','configuration','completion_configuration','reference_batch'):
        value=getattr(args,name,None)
        if value is not None:setattr(args,name,Path(value).resolve())
    root=Path(args.out);root.mkdir(parents=True,exist_ok=False)
    repo=Path(__file__).resolve().parents[2];frozen=implementation();started=time.monotonic();steps=[]
    env={**os.environ,'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','PYTHONDONTWRITEBYTECODE':'1'}
    def phase(name,module,arguments):
        command=[sys.executable,'-B','-m',module,*map(str,arguments)]
        print(json.dumps(dict(phase=name,status='running')),flush=True)
        log=root/(name+'.log');t=time.monotonic()
        with log.open('w') as stream:result=subprocess.run(command,cwd=repo,env=env,stdout=stream,stderr=subprocess.STDOUT)
        step=dict(phase=name,command=command,returncode=result.returncode,log=log.name,seconds=round(time.monotonic()-t,3))
        steps.append(step);save(root/'STAGES.json',steps)
        if result.returncode:raise RuntimeError('GENERATION_STAGE_FAILED:'+name+';see '+str(log))
    save(root/'PIPELINE_PRE_RUN.json',dict(schema='eb.generation_recipe.pre_run.v1',
        recipe='household_native_complete_v1',implementation=frozen,arguments={k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()},
        old_data_overwritten=False,physical_outcomes_computed=False,human_answers_generated=False))
    try:
        if args.households:
            households=Path(args.households).resolve();household_mode='provided_frozen_households;raw_sources_not_reaudited_here'
        else:
            pool=args.pool
            if args.make_example_pool:
                phase('01_example_pool','benchmark.household_stage1.generator',['make-example-pool','--out',root/'source_pool'])
                pool=root/'source_pool/candidate_pool.jsonl'
            elif pool is None:
                phase('01_source_pool','benchmark.household_stage1.generator',['prepare-sources','--data-config',args.data_config,'--out',root/'source_pool'])
                pool=root/'source_pool/candidate_pool.jsonl'
            command=['generate','--pool',Path(pool).resolve(),'--config',args.household_config,'--out',root/'households']
            if args.data_config:command+=['--data-config',args.data_config]
            phase('02_households','benchmark.household_stage1.generator',command)
            command=['verify',root/'households']
            if args.data_config:command+=['--data-config',args.data_config]
            phase('03_household_verification','benchmark.household_stage1.generator',command)
            households=root/'households/household_cases.jsonl'
            household_mode='generated_and_source_audited' if not args.make_example_pool else 'synthetic_public_example_only'
        source_sha,count=validate_households(households,args.expected_household_sha256)
        batch=root/'native';cfg=args.configuration or Path(__file__).with_name('GENERATION_REPAIR_CONFIG.json')
        command=['--households',households,'--reference',args.reference,'--native-source',args.native_source,
            '--start-date',args.start_date,'--days',args.days,'--workers',args.workers,'--configuration',cfg,
            '--min-free-gib',args.min_free_gib,'--out',batch]
        phase('04_native_generation','benchmark.ab_generation.generate_cohort',command)
        common=['--batch',batch,'--households',households,'--native-source',args.native_source]
        phase('05_raw_coverage','benchmark.ab_generation.cohort_coverage',['--batch',batch])
        save(batch/'COHORT_COVERAGE_REVIEW_INITIAL.json',load(batch/'COHORT_COVERAGE_REVIEW.json'))
        phase('06_complete_root_witnesses','benchmark.ab_generation.candidate_completion',common+['--phase','roots','--configuration',args.completion_configuration or Path(__file__).with_name('COMPLETION_CONFIG.json')])
        phase('07_cohort_selection','benchmark.ab_generation.cohort_coverage',['--batch',batch,'--apply','--from-ledger','--native-source',args.native_source])
        save(batch/'COHORT_COVERAGE_REVIEW_PASS1.json',load(batch/'COHORT_COVERAGE_REVIEW.json'))
        phase('08_complete_programme_dependencies','benchmark.ab_generation.candidate_completion',common+['--phase','programme'])
        phase('09_extra_candidate_selection','benchmark.ab_generation.cohort_coverage',['--batch',batch,'--apply','--from-ledger','--extra-only','--native-source',args.native_source])
        save(batch/'COHORT_COVERAGE_REVIEW_PASS2.json',load(batch/'COHORT_COVERAGE_REVIEW.json'))
        phase('10_joint_coverage_selection','benchmark.ab_generation.cohort_optimize',['--batch',batch,'--native-source',args.native_source,'--deterministic-time',args.cohort_deterministic_time])
        phase('11_native_seal','benchmark.ab_generation.seal_native_cohort',['--batch',batch,'--households',households])
        final=load(batch/'RESULT.json');manifest=load(batch/'DATASET_MANIFEST.json');cover=load(batch/'COHORT_COVERAGE_REVIEW.json')
        if not final['native_plan_generation_passed'] or final['summary']['pairs']!=count*args.days:raise ValueError('COMPLETE_NATIVE_BATCH_NOT_ESTABLISHED')
        if implementation()!=frozen:raise ValueError('PIPELINE_CODE_CHANGED_DURING_RUN')
        validate_households(households,source_sha)
        comparison=compare_plans(batch,args.reference_batch) if args.reference_batch else None
        if comparison:
            save(root/'REFERENCE_PLAN_COMPARISON.json',comparison)
            if not comparison['all_current_A_B_plans_equal']:raise ValueError('REFERENCE_PLAN_REPRODUCTION_MISMATCH')
        totals={key:sum(v[key] for v in cover['final'].values()) for key in ['declared_raw_cells','selected_at_least_one','selected_country_goals_met']}
        result=dict(schema='eb.complete_native_generation.result.v1',status='generation_complete_with_coverage_ledger',
            household_mode=household_mode,households=count,pairs=count*args.days,household_input_sha256=source_sha,
            native_manifest=manifest,coverage=totals,all_declared_coverage_goals_met=cover['all_declared_goals_met'],
            original_coverage_denominator_preserved=True,reference_plan_comparison=comparison,
            physical_outcomes_computed=False,human_answers_generated=False,formal_questionnaire_release=False,
            seconds=round(time.monotonic()-started,2),complete_physical_or_human_benchmark_claimed=False)
        save(root/'PHYSICS_HANDOFF.json',dict(schema='eb.native_to_physics.handoff.v1',household_input=str(households),
            source_sha256=source_sha,pair_index=str(batch/'PAIR_INDEX.jsonl'),pair_index_sha256=manifest['pair_index_sha256'],
            model_assignment_manifest=None,physical_outcomes=None,
            same_building_weather_hardware_demands_and_initial_state_required=True,
            predicted_or_real_human_answers=None,physical_qualification=False))
        result['current_native_batch']=str(batch)
        if getattr(args,'complete_scene_coverage',False):
            phase('12_scene_capacity_completion','benchmark.ab_generation.scene_pipeline',
                ['--batch',batch,'--households',households,'--native-source',args.native_source,
                 '--out',root/'scenes','--workers',args.workers,'--min-free-gib',args.min_free_gib])
            scene=load(root/'scenes/PIPELINE_RESULT.json')
            result['parent_native_coverage']=result['coverage']
            result['scene_completion']=scene
            result['native_manifest']=scene['manifest']
            c=scene['manifest']['coverage']
            result['coverage']=dict(declared_raw_cells=c['original_raw_targets'],
                selected_at_least_one=c['selected_at_least_one'],
                selected_country_goals_met=c['selected_country_goals_met'])
            result['all_original_raw_cells_selected']=c['selected_at_least_one']==c['original_raw_targets']
            result['all_declared_coverage_goals_met']=c['selected_country_goals_met']==c['original_raw_targets']
            result['current_native_batch']=str(root/'scenes/native')
            handoff=load(root/'scenes/native/PHYSICS_HANDOFF.json')
            handoff.update(household_input=str(households),pair_index=str(root/'scenes/native/PAIR_INDEX.jsonl'))
            save(root/'PHYSICS_HANDOFF.json',handoff)
            if implementation()!=frozen:raise ValueError('PIPELINE_CODE_CHANGED_DURING_SCENE_COMPLETION')
            result['seconds']=round(time.monotonic()-started,2)
        save(root/'PIPELINE_RESULT.json',result);print(json.dumps(result),flush=True);return result
    except Exception as error:
        save(root/'PIPELINE_FAILURE.json',dict(schema='eb.generation_recipe.failure.v1',status='failed',error_type=type(error).__name__,error=str(error),completed_stages=steps,output_not_a_release=True))
        raise

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',required=True,type=Path)
    parser.add_argument('--households',type=Path);parser.add_argument('--pool',type=Path)
    parser.add_argument('--household-config',type=Path);parser.add_argument('--data-config',type=Path)
    parser.add_argument('--make-example-pool',action='store_true')
    parser.add_argument('--expected-household-sha256')
    parser.add_argument('--reference',required=True,type=Path);parser.add_argument('--native-source',required=True,type=Path)
    parser.add_argument('--start-date',required=True);parser.add_argument('--days',type=int,default=10)
    parser.add_argument('--workers',type=int,default=4);parser.add_argument('--configuration',type=Path)
    parser.add_argument('--completion-configuration',type=Path);parser.add_argument('--reference-batch',type=Path)
    parser.add_argument('--complete-scene-coverage',action='store_true',help='complete frozen raw-cell targets using explicit external scenes and matched controls')
    parser.add_argument('--cohort-deterministic-time',type=float,default=2.0);parser.add_argument('--min-free-gib',type=float,default=.5)
    args=parser.parse_args()
    if args.complete_scene_coverage and args.reference_batch:parser.error('scene repair changes B;compare a frozen reference in the parent recipe separately')
    if args.days!=10:parser.error('the complete recipe currently qualifies exactly ten dates per household')
    if args.workers<1:parser.error('workers must be positive')
    if args.households and any([args.pool,args.household_config,args.data_config,args.make_example_pool]):parser.error('provided household mode cannot be mixed with source-pool generation mode')
    if not args.households and (not args.household_config or not any([args.pool,args.data_config,args.make_example_pool])):parser.error('supply frozen --households,or a household config and pool/data config/example pool')
    if args.make_example_pool and (args.pool or args.data_config):parser.error('synthetic example pool cannot mix with survey inputs')
    if not math.isfinite(args.min_free_gib) or not math.isfinite(args.cohort_deterministic_time) or args.min_free_gib<0 or args.cohort_deterministic_time<=0:parser.error('resource and solver budgets must be valid')
    run(args)
if __name__=='__main__':main()
