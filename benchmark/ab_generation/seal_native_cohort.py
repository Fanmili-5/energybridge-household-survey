"""Seal a current native A/B batch after coverage reselection; no release."""
from pathlib import Path
import argparse,gzip,hashlib,json,time
from .cohort_coverage import load,write_gzip
from .common import digest
from .generate_cohort import summarize,aggregate,save

def seal(root,households,generator_code=None):
    root=Path(root);households=Path(households);pre=load(root/'PRE_RUN.json');raw=households.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=pre['source_sha256']:raise ValueError('SOURCE_MANIFEST_CHANGED')
    code=Path(generator_code) if generator_code else Path(__file__).resolve().parent
    for name,sha in pre['implementation'].items():
        if hashlib.sha256((code/name).read_bytes()).hexdigest()!=sha:raise ValueError('GENERATOR_SNAPSHOT_CHANGED:'+name)
    cases=[json.loads(line) for line in raw.splitlines() if line.strip()]
    cases.sort(key=lambda c:(c['household']['country'],c['household']['role_id'],c['case_id']))
    if len(cases)!=pre['target_households']:raise ValueError('SOURCE_COUNT_CHANGED')
    rows=[];index_rows=[];changed=0
    for i,case in enumerate(cases):
        folder=root/str(i).zfill(4);dates=set();selected=[];pairs=[]
        for p in sorted(folder.glob('*_PAIR.json.gz')):
            if p.name.endswith('_INITIAL_PAIR.json.gz'):continue
            pair=load(p)
            if pair['date'] in dates or pair['source_household_sha256']!=digest(case):raise ValueError('PAIR_LINEAGE_OR_DATE_ERROR')
            dates.add(pair['date']);selected.append(pair['selected_proposal']['id'])
            if pair['A_sha256']!=digest(pair['A']) or pair['B_sha256']!=digest(pair['B']):raise ValueError('PLAN_HASH_ERROR')
            if pair['physical_outcomes'] is not None or pair['human_answers'] is not None:raise ValueError('NATIVE_BATCH_CONTAINS_INHERITED_OUTCOMES')
            if not pair['native_B_acceptance']['passed'] or pair['native_B_acceptance']['hard_errors']:raise ValueError('B_NATIVE_FAILED')
            if any(not pair['paper_v1_execution'][side]['passed'] for side in ['A','B']):raise ValueError('ORIGINAL_EXECUTION_FAILED')
            baseline=load(folder/(pair['date']+'_A.json.gz'))
            if baseline['context']['A']!=pair['A']:raise ValueError('A_CHANGED_DURING_SELECTION')
            old=folder/(pair['date']+'_INITIAL_PAIR.json.gz')
            if old.exists() and load(old)['B_sha256']!=pair['B_sha256']:changed+=1
            pairs.append(dict(date=pair['date'],path=p.name,A_sha256=pair['A_sha256'],B_sha256=pair['B_sha256']))
        if dates!=set(pre['dates']):raise ValueError('ONE_PAIR_PER_FROZEN_DATE_NOT_ESTABLISHED')
        row=summarize(case,folder,i);rows.append(row);index_rows.extend(row.pop('pair_index'))
        current=load(folder/'RESULT.json')
        if not (folder/'RESULT_INITIAL.json').exists():save(folder/'RESULT_INITIAL.json',current)
        current.update(pairs=pairs,current_selection_receipt='SELECTION_CURRENT.json.gz')
        save(folder/'RESULT.json',current)
        write_gzip(folder/'SELECTION_CURRENT.json.gz',dict(schema='eb.current_native_selection.v1',selected_ids=selected,initial_receipt='SELECTION.json.gz',cohort_review='../COHORT_COVERAGE_REVIEW.json',physical_or_human_outcomes_used=False))
    for name in ['RESULT.json','STATUS.json','PAIR_INDEX.jsonl']:
        path=root/name;backup=root/(path.stem+'_BEFORE_COHORT'+path.suffix)
        if path.exists() and not backup.exists():backup.write_bytes(path.read_bytes())
    with (root/'PAIR_INDEX.jsonl').open('w') as stream:
        for row in sorted(index_rows,key=lambda v:(v['index'],v['date'])):stream.write(json.dumps(row,ensure_ascii=False)+'\n')
    summary=dict(completed=len(rows),passed=len(rows),failed=0,pairs=len(index_rows))
    result=aggregate(rows,len(cases),True,True,summary)
    result.update(cohort_refined=True,unique_reselected_pairs=changed,original_generation_result='RESULT_BEFORE_COHORT.json')
    if (root/'COHORT_COVERAGE_REVIEW.json').exists():result['raw_cell_coverage']=load(root/'COHORT_COVERAGE_REVIEW.json')['final']
    save(root/'STATUS.json',dict(summary=summary,rows=rows));save(root/'RESULT.json',result)
    manifest=dict(schema='eb.sealed_native_plan_batch.v1',households=len(cases),pairs=len(index_rows),source_sha256=pre['source_sha256'],pair_index_sha256=hashlib.sha256((root/'PAIR_INDEX.jsonl').read_bytes()).hexdigest(),result_sha256=hashlib.sha256((root/'RESULT.json').read_bytes()).hexdigest(),generator_snapshot_checked=True,current_pair_hashes_checked=True,unique_reselected_pairs=changed,physics_qualification_not_inherited=True,formal_questionnaire_release=False,human_answers_generated=False)
    save(root/'DATASET_MANIFEST.json',manifest)
    return manifest

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--batch',required=True,type=Path);parser.add_argument('--households',required=True,type=Path);parser.add_argument('--generator-code',type=Path)
    args=parser.parse_args();print(json.dumps(seal(args.batch,args.households,args.generator_code)))
if __name__=='__main__':main()
