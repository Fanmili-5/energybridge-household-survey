"""Seal actual complete results; keep service failures and human labels separate."""
import argparse
import collections
import gzip
import hashlib
from concurrent.futures import ProcessPoolExecutor
from core import *

def verify_case(item):
    row,case,review,label=item;folder=ROOT/'results'/label/row['household_id']/case['date'];q=read(ROOT/case['path']);errors=[];files=[]
    if sha(folder/'PHYSICAL_SUMMARY.json')!=review['sha256']:errors.append('SUMMARY_HASH')
    summary=read(folder/'PHYSICAL_SUMMARY.json')
    if summary['source_pair_sha256']!=case['source_pair_sha256']:errors.append('SOURCE_PAIR_ASSOCIATION')
    if summary['human_acceptance']is not None:errors.append('INFERRED_HUMAN_LABEL')
    for side in ('A','B'):
        f=folder/side;r=read(f/'RESULT.json');inputs=read(f/'INPUT.json.gz')
        if not r['engine_completed']or r['errors']:errors.append(side+'_ENGINE_FAILURE')
        for name,key in [('TRACE.json.gz','trace_sha256'),('INPUT.json.gz','input_sha256')]:
            if sha(f/name)!=r[key]:errors.append(side+'_'+name+'_HASH')
        raw=gzip.decompress((f/'model.idf.gz').read_bytes())
        if hashlib.sha256(raw).hexdigest()!=r['idf_sha256']:errors.append(side+'_IDF_HASH')
        request_hash=digest({k:q[side][k]for k in ('tasks','operations','controls')})
        if request_hash!=q['schedule_hashes'][side]or request_hash!=inputs['source_schedule_hash']:errors.append(side+'_REQUEST_CHANGED')
        if inputs['source_pair_sha256']!=case['source_pair_sha256']:errors.append(side+'_PAIR_ASSOCIATION')
        if inputs['schedules_modified']or summary[side]['human_acceptance']is not None:errors.append(side+'_SCHEDULE_OR_LABEL')
        if r.get('raw_SQL_archive_retained'):
            sql=f/'out/eplusout.sql.gz'
            if sha(sql)!=r['raw_SQL_compressed_sha256']:errors.append(side+'_SQL_ARCHIVE_HASH')
    for f in sorted(folder.rglob('*')):
        if f.is_file()and'.tmp.'not in f.name:files.append({'path':str(f.relative_to(ROOT)),'sha256':sha(f),'bytes':f.stat().st_size})
    return {'case_id':case['case_id'],'errors':errors,'files':files,'source_constraint_conflict':bool(q['assessment_B']['constraint_flags']),
            'identical_requests':summary['recovery']['status']=='no_executable_request_difference'}

def seal(label,workers):
    manifest=read(ROOT/'INPUT_MANIFEST.json');runs=read(ROOT/'results'/label/'RUN_BINDINGS.json');review=read(ROOT/'results'/label/'REVIEW.json')
    if label!='all':raise ValueError('ONLY_FULL_DATASET_CAN_BE_SEALED')
    expected={c['case_id']for r in manifest['records']for c in r['cases']};actual=[r['case_id']for r in runs['records']]
    if len(expected)!=10000 or len(actual)!=10000 or set(actual)!=expected:raise ValueError('FULL_CASE_SET')
    if not runs['passed']or not review['passed']or len(review['records'])!=10000:raise ValueError('PHYSICAL_OR_REVIEW_ERRORS')
    if runs['input_manifest_sha256']!=sha(ROOT/'INPUT_MANIFEST.json'):raise ValueError('RUN_INPUT_REVISION')
    config=read(ROOT/'results'/label/'RUN_CONFIG.json')
    if config['physics_sha256']!=physics_hash():raise ValueError('PHYSICS_SOURCE_CHANGED')
    for filename in ('INITIALIZATION_REVIEW.json','CROSS_PLATFORM_REVIEW.json','REGRESSION_RESULTS.json'):
        if not read(ROOT/filename)['passed']:raise ValueError('VALIDATION_NOT_PASSED:'+filename)
    pilot=read(ROOT/'results/pilot50/REVIEW.json')
    if not pilot['passed']or pilot['counts']['cases']!=500:raise ValueError('PILOT50_NOT_ACCEPTED')
    cases={r['case_id']:r for r in review['records']};audits=[]
    jobs=[(r,c,cases[c['case_id']],label)for r in manifest['records']for c in r['cases']]
    with ProcessPoolExecutor(max_workers=workers)as pool:
        for v in pool.map(verify_case,jobs,chunksize=2):
            audits.append(v)
            if len(audits)%500==0:print(canonical({'sealed_case_checks':len(audits),'errors':sum(bool(x['errors'])for x in audits)}),flush=True)
    errors=[{'case_id':r['case_id'],'errors':r['errors']}for r in audits if r['errors']]
    if errors:
        save(ROOT/'SEAL_ERRORS.json',errors);raise ValueError('ARTIFACT_ERRORS:'+str(len(errors)))
    if sum(r['identical_requests']for r in audits)!=100:raise ValueError('FIXED_IDENTICAL100_CHANGED')
    typed=collections.Counter(r['type']for r in manifest['records']if r['household_id']in manifest['subset50_ids'])
    if dict(typed)!={'A':5,'B':15,'C':16,'D':5,'E':4,'F':5}:raise ValueError('SAME_MASTER50_PROPORTIONS')
    bindings={'schema':VERSION,'households':1000,'pairs':10000,'all10000_one_dataset':True,
              'A_stage':'normal_A_v46_20261017','B_stage':'candidate_B_v57_20261017',
              'input_manifest_sha256':sha(ROOT/'INPUT_MANIFEST.json'),'physics_sha256':physics_hash(),
              'records':review['records'],'raw_artifact_root':str(ROOT/'results/all'),
              'raw_artifact_storage':'compute_server;local mirrors must declare availability',
              'human_labels_created':0,'schedules_modified':False}
    save(ROOT/'PHYSICAL_BINDINGS10000.json',bindings)
    save(ROOT/'PHYSICAL_BINDINGS50.json',{'schema':VERSION,'same_master':True,'type_counts':dict(typed),
        'master_bindings_sha256':sha(ROOT/'PHYSICAL_BINDINGS10000.json'),
        'records':[r for r in review['records']if r['household_id']in manifest['subset50_ids']]})
    acceptance={'schema':VERSION,'accepted':True,'scope':'complete paired numerical reference replay and artifact consistency;not all B service success,field calibration or human acceptance',
                'households':1000,'pairs':10000,'engine_runs':20000,'source_requests_unchanged':True,
                'identical_command_cases':100,'source_B_constraint_conflict_cases':sum(r['source_constraint_conflict']for r in audits),
                'same_master50_type_counts':dict(typed),'full_metering_verified':True,'common_predecision_states_verified':True,
                'weather_based_mains':True,'reference_ACH':config['reference_ACH'],'all_failures_retained':True,
                'physical_counts':review['counts'],'whole_VPP_event_relations':review['whole_VPP_event_relations'],
                'human_acceptance_labels_created':0,'questionnaire_released':False,'errors':[],
                'bindings_sha256':sha(ROOT/'PHYSICAL_BINDINGS10000.json'),'physics_sha256':physics_hash()}
    save(ROOT/'ACCEPTANCE.json',acceptance)
    c=review['counts'];events=review['whole_VPP_event_relations']
    lines=['# 第5项：A46/B57完整参考仿真复核','',
           '1000户、10000组A/B均已完成数值回放及独立读回。A46/B57原排程不变，同源50户仍为5/15/16/5/4/5户，整批数据没有评测拆分。','',
           '| 项目 | 本轮实际产物 |','|---|---|',
           '| 住房与IDF | 沿用1000户住房；派生编译修正隔墙两侧材料顺序，绑定同一住房、天气和设备 |',
           '| 仿真 | 20000次A/B运行，全量电表、程序/EV对账、IDF指令读回、共同历史验证 |',
           '| 热环境 | 电器和背景散热、明确0.35ACH参考换气、天气关联进水温度 |',
           '| 状态与恢复 | 温度、辐射温度、湿度、热罐节点和SOC连续跟踪；无午夜状态重置 |','',
           f"源B的约束冲突保留{acceptance['source_B_constraint_conflict_cases']}组；新增物理读回的失败和未恢复不触发删样或修排程。",
           f"全组合VPP事件读回：{canonical(events)}。这描述响应方向，不是用户接受率。",
           f"恢复状态计数：{canonical({k:v for k,v in c.items()if 'horizon'in k or 'difference'in k})}。",
           f"A未启动批次{c.get('A_unexecuted_batches',0)}；B未启动批次{c.get('B_unexecuted_batches',0)}；B出发目标电量不足{c.get('B_EV_target_shortfall_departures',0)}次。",
           f"A/B供电边界越限案例分别为{c.get('A_supply_violation_cases',0)}/{c.get('B_supply_violation_cases',0)}；越限结果属于受约束请求的开放回放，不声称真实断路器可无条件交付。",'',
           '判定范围：这是EB设备参数、构造住房、给定生活任务和明确气象/换气条件下的可复现参考模型。它支持比较A/B物理后果，不能据此声称逐户实测校准、全国节能比例或真实接受偏好。热罐沿用EB一节点，未模拟动态开窗、门缝气流或室内空气质量。',
           '本轮未发布问卷、未生成接受标签、未生成未绑定电价条件的电费或VPP激励收益。第6项需把这些同版本后果接入清楚、中性的前端。','',
           '依据：`ACCEPTANCE.json`、`PHYSICAL_BINDINGS10000.json`、`INITIALIZATION_REVIEW.json`、`CROSS_PLATFORM_REVIEW.json`、`REGRESSION_RESULTS.json`及`METHODS.md`。','']
    (ROOT/'REPORT.md').write_text('\n'.join(lines))
    output_files=[f for audit in audits for f in audit['files']]
    for directory in ('code','tools','inputs','results/pilot50','results/initialization28','results/initialization56'):
        if not (ROOT/directory).exists():continue
        for path in sorted((ROOT/directory).rglob('*')):
            if path.is_file()and not path.name.startswith('._')and'__pycache__'not in path.parts:
                output_files.append({'path':str(path.relative_to(ROOT)),'sha256':sha(path),'bytes':path.stat().st_size})
    top=['INPUT_MANIFEST.json','METHODS.md','INITIALIZATION_REVIEW.json','CROSS_PLATFORM_REVIEW.json','REGRESSION_RESULTS.json',
         'PHYSICAL_BINDINGS10000.json','PHYSICAL_BINDINGS50.json','ACCEPTANCE.json','REPORT.md',
         'results/all/RUN_CONFIG.json','results/all/RUN_BINDINGS.json','results/all/REVIEW.json','results/pilot50/REVIEW.json']
    top +=[name for name in ('REMOTE_ENVIRONMENT.json','TRANSPORT_METADATA_QUARANTINE.json','PHYSICS_CONTRACT.json')if(ROOT/name).exists()]
    for rel in top:
        path=ROOT/rel;output_files.append({'path':rel,'sha256':sha(path),'bytes':path.stat().st_size})
    unique={r['path']:r for r in output_files};output_files=[unique[p]for p in sorted(unique)]
    save(ROOT/'FILE_MANIFEST.json.gz',{'schema':VERSION,'files':output_files,'source_files':manifest['source_files']})
    save(ROOT/'FINAL_SEAL.json',{'schema':VERSION,'accepted':True,'manifest_sha256':sha(ROOT/'FILE_MANIFEST.json.gz'),
        'physical_bindings_sha256':sha(ROOT/'PHYSICAL_BINDINGS10000.json'),'input_manifest_sha256':sha(ROOT/'INPUT_MANIFEST.json'),
        'physics_sha256':physics_hash(),'source_code_sha256':code_hash(),'files':len(output_files),'artifact_root':str(ROOT)})
    print(canonical(acceptance))

def verify():
    seal=read(ROOT/'FINAL_SEAL.json')
    if sha(ROOT/'FILE_MANIFEST.json.gz')!=seal['manifest_sha256']:raise ValueError('MANIFEST_CHANGED')
    failures=[];rows=read(ROOT/'FILE_MANIFEST.json.gz')['files']
    for row in rows:
        path=ROOT/row['path']
        if not path.is_file()or sha(path)!=row['sha256']:failures.append(row['path'])
    report={'schema':VERSION,'passed':not failures,'checked_files':len(rows),'errors':failures,'seal_sha256':sha(ROOT/'FINAL_SEAL.json'),'verified_artifact_root':str(ROOT)}
    save(ROOT/'FINAL_VERIFICATION.json',report);print(canonical(report))
    if failures:raise SystemExit(2)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['seal','verify']);p.add_argument('--workers',type=int,default=8);args=p.parse_args()
    if args.phase=='seal':seal('all',args.workers)
    else:verify()
