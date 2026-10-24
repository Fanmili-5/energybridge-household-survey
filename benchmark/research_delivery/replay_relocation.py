"""Guarded two-directory public replay preflight; no release gate side effects."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from benchmark.ab_generation.common import read,save,digest,sha

GUARD='''import os,sys
blocked=os.path.realpath(os.environ['EB_BLOCK_WORKSPACE'])
runtime=os.path.realpath(os.environ['EB_ALLOW_RUNTIME'])
log=os.environ['EB_GUARD_LOG']
def within(p,root):return p==root or p.startswith(root+os.sep)
def check(event,args):
    if event!='open' or not args or not isinstance(args[0],(str,bytes)):return
    p=os.path.realpath(os.fsdecode(args[0]))
    if within(p,blocked) and not within(p,runtime):
        with open(log,'a') as f:f.write(p+'\\n')
        raise PermissionError('PUBLIC_REPLAY_ORIGINAL_WORKSPACE_FORBIDDEN:'+p)
sys.addaudithook(check)
'''


def semantic_fingerprints(output,stage):
    output=Path(output)
    hashes={str(p.relative_to(output)):digest(read(p)) for p in output.glob('*/COMPILED_PROBLEM.json.gz')}
    if stage!='compile':
        for p in output.glob('*/A_*.json.gz'):
            answer=read(p)
            hashes[str(p.relative_to(output))]=digest({k:answer.get(k) for k in ('A','ev_charging_steps','conditional_target_context')})
    collection=output/'AB/collection'
    if stage=='both' and (collection/'MATERIALS.json.gz').exists():
        materials=read(collection/'MATERIALS.json.gz')
        hashes['selected_plans']=digest({m['id']:{'A':m['A'],'B':m['B']} for m in materials})
        hashes['all_selected_materials']=digest(sorted(materials,key=lambda m:m['id']))
        hashes['selection_record']=digest(read(collection/'SELECTION.json'))
        generation=read(collection/'GENERATION.json')
        if len({(r['household_id'],r['date']) for r in generation})!=len(generation):
            raise ValueError('REPLAY_DUPLICATE_GENERATION_DATE')
        for slot in generation:
            relative=Path(slot['path'])
            if relative.is_absolute() or '..' in relative.parts:raise ValueError('REPLAY_CATALOGUE_PATH_OUTSIDE_COLLECTION')
            catalogue=read(collection/relative)
            # Keep every literal alternative, diagnostic and unknown. Only
            # measured wall time / worker memory may vary with the machine.
            content={k:v for k,v in catalogue.items() if k!='telemetry'}
            hashes['catalogue:'+slot['household_id']+':'+slot['date']]=digest(content)
    return hashes


def verify_package_sources(package):
    package=Path(package);manifest=read(package/'PACKAGE_SOURCES.json')
    for relative,pin in manifest['code'].items():
        file=package/relative
        if not file.resolve().is_relative_to(package.resolve()) or sha(file)!=pin['sha256']:
            raise ValueError('PUBLIC_REPLAY_PACKAGE_SOURCE_CHANGED:'+relative)
    if sha(package/'data/PUBLIC_REPLAY.json')!=manifest['data_manifest_sha256']:
        raise ValueError('PUBLIC_REPLAY_PACKAGE_DATA_MANIFEST_CHANGED')
    return sha(package/'PACKAGE_SOURCES.json')


def retained_source_map(evidence,package,moved,original_output):
    """Resolve preserved manifests without rewriting their original paths."""
    evidence,package,moved,original_output=map(lambda p:Path(p).resolve(),(evidence,package,moved,original_output))
    pins={};pre=evidence/'AB/collection/PRE_GENERATION.json'
    if pre.exists():pins.update(read(pre)['source_sha256'])
    frozen=evidence/'FROZEN_REPLAY.json'
    if frozen.exists():
        replay=read(frozen);homes={r['household_id'] for r in replay['household_dates']}
        for row in replay['source_manifest']['households']:
            if row['household_id'] not in homes:continue
            for key in ('life','world','portrait','expected_problem','expected_A'):
                ref=row[key];pins[str(moved/'data'/ref['path'])]=ref['sha256']
    rows=[]
    for original,expected in sorted(pins.items()):
        old=Path(original).resolve()
        target=(evidence/old.relative_to(original_output) if old.is_relative_to(original_output) else
                package/old.relative_to(moved) if old.is_relative_to(moved) else None)
        actual=sha(target) if target is not None and target.is_file() else None
        rows.append(dict(original_path=original,retained_path=str(target) if target is not None else None,
            expected_sha256=expected,actual_sha256=actual,passed=actual==expected))
    return dict(passed=bool(rows) and all(r['passed'] for r in rows),records=rows,
        original_moved_package=str(moved),original_output_root=str(original_output),
        retained_package=str(package),retained_output_root=str(evidence),
        original_manifest_paths_unchanged=True,source_manifest_sha256=sha(package/'PACKAGE_SOURCES.json'))


def run(package,out,python,workspace,stage='compile'):
    package,out,workspace=map(lambda x:Path(x).resolve(),(package,out,workspace))
    manifest_hash=verify_package_sources(package)
    out.mkdir(parents=True,exist_ok=False);results=[]
    with tempfile.TemporaryDirectory(prefix='eb-public-route-',dir='/private/tmp') as temp:
        temporary=Path(temp);guard=temporary/'guard';guard.mkdir();(guard/'sitecustomize.py').write_text(GUARD)
        for label in ('first','second'):
            moved=temporary/(label+' moved package')
            shutil.copytree(package,moved,ignore=shutil.ignore_patterns('compilation-check','__pycache__'))
            env={**os.environ,'PYTHONPATH':str(guard)+os.pathsep+str(moved),
                'EB_BLOCK_WORKSPACE':str(workspace),'EB_ALLOW_RUNTIME':str(Path(python).absolute().parents[1]),
                'EB_GUARD_LOG':str(guard/(label+'.log'))}
            command=[str(python),'-B','-m','benchmark.research_delivery.public_replay','--inputs','data/PUBLIC_REPLAY.json',
                '--config','data/SMOKE_CONFIG.json','--out','relocation-replay','--stage',stage,'--workers','1']
            if stage!='compile':command+=['--household','project-demo-000001']
            process=subprocess.run(command,cwd=moved,env=env,capture_output=True,text=True)
            output=moved/'relocation-replay';report=read(output/'REPLAY_REPORT.json') if (output/'REPLAY_REPORT.json').exists() else None
            blocked=(guard/(label+'.log')).read_text().splitlines() if (guard/(label+'.log')).exists() else []
            evidence=out/label
            # Preserve failed runs and all unknown/candidate records too.
            if output.exists():shutil.copytree(output,evidence)
            else:evidence.mkdir()
            retained=retained_source_map(evidence,package,moved,output)
            save(out/(label+'_RETAINED_SOURCES.json'),retained)
            fingerprint_error=None
            try:hashes=semantic_fingerprints(output,stage)
            except (ValueError,KeyError,OSError) as error:
                hashes={};fingerprint_error=type(error).__name__+':'+str(error)
            passed=process.returncode==0 and report is not None and report['compilation_equal'] and report['failed_date_slots']==0 and not blocked and fingerprint_error is None and retained['passed']
            if stage=='compile':passed=passed and len(hashes)==6
            if stage in ('A','both'):
                a_results=read(output/'A_REPLAY_RESULTS.json') if (output/'A_REPLAY_RESULTS.json').exists() else []
                passed=passed and len(a_results)==1 and a_results[0].get('expected_plan_and_targets_equal') is True
            if stage=='both':passed=passed and 'selected_plans' in hashes and report['collection']['selected']==10 and sum(k.startswith('catalogue:') for k in hashes)==10
            result=dict(label=label,passed=bool(passed),process_returncode=process.returncode,report=report,
                blocked_attempts=blocked,semantic_output_hashes=hashes,stdout=process.stdout,stderr=process.stderr,
                command=command,stage=stage,fingerprint_error=fingerprint_error,
                retained_sources=label+'_RETAINED_SOURCES.json')
            results.append(result);save(out/(label+'_RUN.json'),result)
    if verify_package_sources(package)!=manifest_hash:raise ValueError('PACKAGE_CHANGED_DURING_RELOCATION')
    result=dict(passed=all(r['passed'] for r in results) and results[0]['semantic_output_hashes']==results[1]['semantic_output_hashes'],
        exact_outputs_across_two_directories=results[0]['semantic_output_hashes']==results[1]['semantic_output_hashes'],
        runs=results,source_manifest_sha256=sha(package/'PACKAGE_SOURCES.json'),
        original_workspace_blocked=True,existing_locked_runtime_used=True,clean_machine_installation_tested=False,
        scope='six public raw-life recompilations only' if stage=='compile' else 'fixed first public household;'+stage,
        profile_sampler_rerun=False,final_release_accepted=False,physical_runs=0,
        full_replay_outputs_preserved=True,all_candidate_diagnostics_unknowns_compared=stage=='both',
        excluded_catalogue_fields=['telemetry'],source_files_verified_before_and_after=True)
    save(out/'PORTABILITY_PREFLIGHT.json',result)
    return {k:v for k,v in result.items() if k!='runs'}


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('package','out','python','workspace'):p.add_argument('--'+name,required=True)
    p.add_argument('--stage',choices=['compile','A','both'],default='compile')
    a=p.parse_args();print(run(a.package,a.out,a.python,a.workspace,a.stage))
