"""Seal accepted inputs and review evidence without changing current pointers."""
import sys
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *
def main():
    verify_inputs();accept=read(OUT/'ACCEPTANCE.json');design=read(OUT/'DESIGN_REVIEW.json');sig=rules_id()
    if not accept['accepted']or not design['accepted']or accept['rules_sha256']!=sig:raise ValueError('STAGE_NOT_ACCEPTED')
    if (OUT/'FINAL_SEAL.json').exists():raise ValueError('SEAL_EXISTS')
    isA=OUT.name.startswith('normal_A');binding='A_BINDINGS10000.json'if isA else'PAIR_BINDINGS10000.json';bs=read(OUT/binding)
    if not isA:
        for filename,key in(('A_REAUDIT.json','accepted'),('REGRESSION_RESULTS.json','passed'),('FOUR_POINT_REVIEW.json','accepted')):
            if not read(OUT/filename)[key]:raise ValueError('ADDITIONAL_REVIEW_NOT_ACCEPTED:'+filename)
        if read(OUT/'FOUR_POINT_REVIEW.json')['rules_sha256']!=sig:raise ValueError('FOUR_POINT_REVIEW_WRONG_VERSION')
        import runpy
        runpy.run_path(str(OUT/'tools/write_acceptance_note.py'),run_name='__main__')
        save(OUT/'REVIEW_EXPORT_MANIFEST.json',{'files':{str(p.relative_to(OUT)):sha(p)for p in(OUT/'review').iterdir()if p.is_file()},'scope':'static requests and independent four-point readback;no physical success or human labels'})
    if bs['rules_sha256']!=sig or accept['bindings_sha256']!=sha(OUT/binding):raise ValueError('BINDING_MISMATCH')
    if len(bs['records'])!=1000 or bs['cases']!=10000:raise ValueError('NOT_FULL1000_10000')
    if not read(OUT/'REGRESSION_RESULTS.json')['passed']:raise ValueError('REGRESSIONS_NOT_PASSED')
    if read(OUT/'RESOURCE_REGRESSION_RESULTS.json')['rules_sha256']!=sig or not read(OUT/'RESOURCE_REGRESSION_RESULTS.json')['passed']:raise ValueError('RESOURCE_REGRESSIONS_NOT_PASSED')
    if not read(OUT/'THERMAL_FLEX_REVIEW.json')['accepted']or read(OUT/'THERMAL_FLEX_REVIEW.json')['rules_sha256']!=sig:raise ValueError('THERMAL_FLEX_REVIEW_NOT_ACCEPTED')
    if not read(OUT/'THERMAL_FLEX_REGRESSION.json')['passed']or read(OUT/'THERMAL_FLEX_REGRESSION.json')['rules_sha256']!=sig:raise ValueError('THERMAL_FLEX_REGRESSION_NOT_ACCEPTED')
    if not read(OUT/'B_THERMAL_FUNCTIONAL_CHECK.json')['completed']:raise ValueError('B_THERMAL_FUNCTIONAL_PROBES_FAILED')
    history=[]
    for folder in sorted((OUT/'runs').iterdir()):
        rows=[read(p)for p in(folder/'records').glob('*.json')]
        archive=folder/'COMPRESSED_TRIAL_OUTPUTS.jsonl'
        history.append({'run':folder.name,'written_households':len(rows),'generation_errors':sum(not r['passed']for r in rows),'accepted':folder.name==sig[:16],
            'compressed_trial_outputs_manifest':str(archive.relative_to(OUT))if archive.exists()else None,'compressed_trial_manifest_sha256':sha(archive)if archive.exists()else None,'source_snapshot_preserved':(folder/'source_snapshot').exists()})
    save(OUT/'DEVELOPMENT_HISTORY.json',{'runs':history,'failed_generator_trials_not_silently_discarded':True,'valid_B_failures_are_data_not_generation_errors':True})
    files=list((OUT/'code').glob('*.py'))+list((OUT/'tools').glob('*.py'))+list((OUT/'review').glob('*'))
    files+=list((OUT/'trials').rglob('*'))
    for earlier in(OUT/'runs').iterdir():
        if earlier.name!=sig[:16]:
            files+=list((earlier/'review_snapshot').glob('*'))+list((earlier/'source_snapshot').glob('*'))+list((earlier/'records').glob('*.json'))
    files+=list((OUT/'runs'/sig[:16]/'source_snapshot').glob('*'))+list((OUT/'runs'/sig[:16]/'regeneration').glob('*.json'))+list((OUT/'runs'/sig[:16]/'records').glob('*.json'))
    files+=[p for p in OUT.glob('*.json')if p.name!='FINAL_SEAL.json']+[OUT/'METHODS.md']
    # Bind actual probe compiler inputs/results as diagnostics, never as full physics.
    files+=list((OUT/'thermal_probe').glob('*/INPUT.json'))+list((OUT/'thermal_probe').glob('*/RESULT.json'))
    save(OUT/'FINAL_SEAL.json',{'schema':'eb.staged_inputs_seal.v40'if isA else'eb.staged_inputs_seal.v47','rules_sha256':sig,'stage_files':{str(p.relative_to(OUT)):sha(p)for p in files if p.is_file()},'scope':'full1000/10000 input generation,static and causal-design checks;not full physical or human acceptance','physical_acceptance':False,'collection_released':False,'run':'runs/'+sig[:16],'python':sys.version})
    print({'sealed_stage':OUT.name,'rules_sha256':sig,'current_pointers_published':False,'stage_files':len(files)})
if __name__=='__main__':main()
