"""Reusable scene-coverage repair of a sealed native daily-plan batch.

The existing household and daily-A generators remain the parent stage.
Four explicit stages produce a separate batch without mutating the parent.
"""
import argparse,hashlib,json,math,os,subprocess,sys,time,shutil
from pathlib import Path
from .generate_cohort import save
from .generate_native import implementation
from .cohort_coverage import load

def run(args):
    for name in ('batch','households','native_source','out'):
        setattr(args,name,Path(getattr(args,name)).resolve())
    if not 1<=args.workers<=8 or not 1<=args.dates_per_cell<=10:
        raise ValueError('INVALID_SCENE_SEARCH_BUDGET')
    if not math.isfinite(args.deterministic_time) or args.deterministic_time<=0:
        raise ValueError('INVALID_SCENE_SOLVER_BUDGET')
    if not 1<=args.max_changed_per_household<=10:
        raise ValueError('INVALID_CHANGED_QUESTION_CAP')
    root=args.out;root.mkdir(parents=True,exist_ok=False)
    code=Path(__file__).resolve().parents[2];frozen=implementation()
    source=hashlib.sha256(args.households.read_bytes()).hexdigest()
    parent=load(args.batch/'DATASET_MANIFEST.json')
    if source!=parent['source_sha256']:raise ValueError('PARENT_HOUSEHOLD_INPUT_MISMATCH')
    steps=[];started=time.monotonic()
    save(root/'PIPELINE_PRE_RUN.json',dict(schema='eb.scene_generation_recipe.v1',implementation=frozen,
        arguments={k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()},
        household_sha256=source,parent_manifest_sha256=hashlib.sha256((args.batch/'DATASET_MANIFEST.json').read_bytes()).hexdigest(),
        no_household_or_A_regeneration=True,no_native_action_addition=True,old_batch_not_overwritten=True))
    def phase(name,module,arguments):
        if shutil.disk_usage(root).free<args.min_free_gib*2**30:raise ValueError('SCENE_DISK_FLOOR')
        cmd=[sys.executable,'-B','-m',module,*map(str,arguments)]
        log=root/(name+'.log');t=time.monotonic();print(json.dumps(dict(phase=name,status='running')),flush=True)
        with log.open('w') as f:
            p=subprocess.run(cmd,cwd=code,env={**os.environ,'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1'},stdout=f,stderr=subprocess.STDOUT)
        steps.append(dict(phase=name,command=cmd,returncode=p.returncode,log=log.name,seconds=round(time.monotonic()-t,3)))
        save(root/'STAGES.json',steps)
        if p.returncode:raise RuntimeError('SCENE_PHASE_FAILED:'+name)
    try:
        discovery=root/'discovery'
        common=['--batch',args.batch,'--households',args.households,'--native-source',args.native_source]
        phase('01_scene_discovery','benchmark.ab_generation.scene_coverage',
            ['discover',*common,'--out',discovery,'--workers',args.workers,'--dates-per-cell',args.dates_per_cell])
        phase('02_joint_allocation','benchmark.ab_generation.scene_coverage',
            ['allocate','--batch',args.batch,'--out',discovery,'--deterministic-time',args.deterministic_time,
             '--max-changed-per-household',args.max_changed_per_household])
        allocation=load(discovery/'ALLOCATION_RESULT.json')
        if allocation['status'] not in ('FEASIBLE','OPTIMAL'):raise RuntimeError('SCENE_ALLOCATION_UNRESOLVED:'+allocation['status'])
        phase('03_matched_event_panel','benchmark.ab_generation.scene_balance',
            [*common,'--discovered',discovery,'--workers',args.workers,'--max-changes',args.max_changed_per_household])
        phase('04_materialize_and_replay','benchmark.ab_generation.scene_release',
            ['materialize',*common,'--discovered',discovery,'--out',root/'native','--workers',args.workers])
        if implementation()!=frozen:raise ValueError('SCENE_RECIPE_CODE_CHANGED')
        if hashlib.sha256(args.households.read_bytes()).hexdigest()!=source:raise ValueError('SCENE_RECIPE_INPUT_CHANGED')
        result=dict(schema='eb.scene_generation_recipe.result.v1',status='native_scene_generation_qualified',
            manifest=load(root/'native/DATASET_MANIFEST.json'),seconds=round(time.monotonic()-started,2),
            physical_benchmark_complete=False,human_answers_generated=False,formal_questionnaire_release=False)
        save(root/'PIPELINE_RESULT.json',result);return result
    except Exception as e:
        save(root/'PIPELINE_FAILURE.json',dict(schema='eb.scene_generation_recipe.failure.v1',error_type=type(e).__name__,
            error=str(e),completed_stages=steps,not_a_release=True,original_input_batch_preserved=True))
        raise

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('batch','households','native-source','out'):p.add_argument('--'+n,required=True,type=Path)
    p.add_argument('--workers',type=int,default=8);p.add_argument('--dates-per-cell',type=int,default=3)
    p.add_argument('--deterministic-time',type=float,default=60)
    p.add_argument('--max-changed-per-household',type=int,default=4)
    p.add_argument('--min-free-gib',type=float,default=.5)
    a=p.parse_args()
    if not math.isfinite(a.min_free_gib) or a.min_free_gib<0:p.error('invalid resource floor')
    print(json.dumps(run(a)),flush=True)
if __name__=='__main__':main()
