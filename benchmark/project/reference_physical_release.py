"""New UI91 formal information set, bound to all frozen new A/B physics receipts.

Derive new case packets; never edit a previous release or copy previous answers.
The selected parent's plans, context and profiles remain identical. Engineering
failures remain in diagnostics; formal collection requires computable outcomes.
Logged replenishment creates a new parent before this step, never a success filter.
"""
import argparse
import copy
import json
import math
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from benchmark.ab_generation.common import read,save,sha,digest,verify
from .questionnaire import COLLECTOR,HERE

CONDITION='role_judgment_with_version_bound_physics'


def require_computed_consequences(rows):
    """Formal collection requires computable estimates, never favorable outcomes."""
    if len(rows)!=500 or len({r['case_id'] for r in rows})!=500:
        raise ValueError('EXACT_COMPLETE500_REQUIRED')
    missing=[r['case_id'] for r in rows if r.get('status')!='computed' or not isinstance(r.get('actual_outcomes'),dict)]
    if missing:raise ValueError('FORMAL_COLLECTION_REQUIRES_COMPUTED_CONSEQUENCES:'+str(len(missing)))
    for row in rows:
        a=row['actual_outcomes']
        try:
            energy=a['metered_energy']['primary_24h'];cost=a['simulated_facility_cost']['intervals']['primary_24h']
            assert cost['status']=='complete' and a['simulated_facility_cost']['currency']=='CNY'
            assert a['events'] and all(type(e['target_met'])is bool for e in a['events'])
            assert a['temperature_outcomes']
            values=[r[k]for r in (energy,cost)for k in ('A','B','B_minus_A')]
            values += [e[k]for e in a['events']for k in ('A_kWh','B_kWh','aligned_response_kw')]
            values += [t[s][k]for t in a['temperature_outcomes']for s in ('A','B')for k in ('minimum_C','mean_C','maximum_C')]
            assert all(type(v)in (int,float)and math.isfinite(v)for v in values)
        except (KeyError,TypeError,AssertionError):raise ValueError('FORMAL_CORE_CONSEQUENCES_INCOMPLETE:'+row['case_id'])from None


def build(proposal_release,results,out,diagnostic_preview=False):
    proposal_release,results,out=map(lambda p:Path(p).resolve(),(proposal_release,results,out))
    sys.path.insert(0,str(COLLECTOR));from release import Release
    parent=Release(proposal_release,verify_code=False);verify(results)
    physics=read(results/'RESULT_INDEX500.json');rows={r['case_id']:r for r in physics['records']}
    if set(rows)!=set(parent.records) or len(rows)!=500:raise ValueError('EXACT_COMPLETE500_REQUIRED')
    if any(r['status'] in ('not_computed','input_prepared','unsupported_world') for r in rows.values()):raise ValueError('ALL500_MUST_BE_ATTEMPTED')
    if not diagnostic_preview:require_computed_consequences(list(rows.values()))
    shutil.copytree(proposal_release,out);public=out/'public';index=read(out/'INDEX50.json')
    index['cases'].sort(key=lambda r:(r['household_id'],r['date'],r['case_id']))
    for row in index['cases']:
        path=public/row['path'];case=read(path);r=rows[row['case_id']]
        if r['source_frozen_pair_sha256']!=case['bindings']['source_pair_sha256'] or any(r[s+'_commands_sha256']!=case['bindings'][s+'_commands_sha256'] for s in ('A','B')):raise ValueError('PHYSICS_PLAN_BINDING_MISMATCH')
        review={k:r.get(k) for k in ('status','actual_outcomes','reason','audit_status','failed_checks','source_frozen_pair_sha256','receipts','engine_warnings','model_scope','native_numerical_convergence','weather_input_quality')}
        if r['status']=='computed' and r['actual_outcomes']['simulated_facility_cost']['currency']!='CNY':raise ValueError('CURRENCY_UNDECLARED')
        case.update(physical_review=review,outcome_status=r['status'],impact=r['actual_outcomes'],
                    VPP_results=r['actual_outcomes']['events'] if r['status']=='computed' else None)
        case['bindings'].update(outcome_status=r['status'],label_condition=CONDITION,
            parent_proposal_case_sha256=row['sha256'],physics_result_manifest_sha256=sha(results/'MANIFEST.json'))
        case['schema']='eb.reference_benchmark.case.v2'
        save(path,case);row['sha256']=sha(path)
    view=public/'view.js';source=view.read_text();a=source.index('  // UI91 presentation over frozen proposal data.');b=source.index('  function displayed(',a)
    source=source[:a]+(HERE/'refined91/pending_nodes.js').read_text()+'\n'+source[b:]
    source=source.replace('const physical_review=physicalReviews?.cases[c.case_id];','const physical_review=c.physical_review||physicalReviews?.cases[c.case_id];')
    source=source.replace('暂停制冷请求（实际运行未计算）','暂停制冷请求')
    source=source.replace('实际后果尚未计算，不要求推测。','本题未获得可用配对后果，请依据已列计划判断，不猜测未知后果。')
    view.write_text(source)
    css=public/'view.css';css.write_text(css.read_text()+'\n#impacts > .cost-scope, #impacts > .cost-warning {grid-column:1 / -1;}\n.outcome-prose .money-comparison .compare-value {font-size:17px;line-height:1.75;font-weight:500;}\n')
    html=public/'index.html';html.write_text(html.read_text().replace('实际用电、费用、室温和VPP达标情况尚未计算，请根据提议安排判断。',
        '按本题列出的A/B配对仿真估算判断；失败、未知与未达标均照实保留。' if diagnostic_preview else
        '本版本每题均提供A/B配对仿真估算；任务未完成和VPP未达标照实保留，请按本户需要判断是否接受。'))
    entry=public/'entry.html';entry.write_text((COLLECTOR/'entry.html').read_text().replace('方案为参考仿真，不会改变现实电器的设置。',
        '方案与后果为参考模型估算，不会改变现实电器的设置。'+('诊断预览中未通过工程准入的后果标为未知。'if diagnostic_preview else'本版本每题均有可用的配对估算，节电、达标与家庭是否接受分别判断。')+'旧版答卷独立保留，不会作为本版答案。'))
    instructions=read(out/'ANSWER_INSTRUCTIONS.json');instructions.update(collection_condition='按给定家庭、A/B计划及本题已列的配对仿真估算作答；未知和失败不补造后果，不把VPP达标当作接受答案。',objective_outcomes='物理估算、工程/服务失败和VPP达标按同一冻结A/B版本单独记录；不预设家庭接受或评分。')
    instructions['scores']['comfort_score']['meaning']='室温与生活变化是否适合这户家庭'
    instructions['scores']['energy_score']['meaning']='用电时段与费用变化是否适合这户家庭';save(out/'ANSWER_INSTRUCTIONS.json',instructions)
    save(public/'index.json',index)
    for name in ('DISPLAY_MODELS.json','DISPLAY_MODELS50.json'):(out/name).unlink(missing_ok=True)
    run=subprocess.run(['node',str(HERE/'verify_refined_display.js'),str(out)],capture_output=True,text=True)
    if run.returncode:raise ValueError(run.stderr[-5000:])
    save(out/'DISPLAY_MODELS50.json',read(out/'DISPLAY_MODELS.json'))
    index['ui_assets_sha256']={p.name:sha(p) for p in public.iterdir() if p.is_file()};save(out/'INDEX50.json',index)
    save(out/'PHYSICS_BINDING.json',{'result_manifest_sha256':sha(results/'MANIFEST.json'),'result_index_sha256':sha(results/'RESULT_INDEX500.json'),
        'records':[{k:r[k] for k in ('case_id','status','source_frozen_pair_sha256','A_commands_sha256','B_commands_sha256')} for r in rows.values()],
        'frozen_plans_modified':False,'parent_case_packets_preserved':True,'old_answers_copied':False})
    m=copy.deepcopy(parent.manifest);m.update(schema='eb.reference_benchmark.release.v2',cohort_id='reference50-v4-ui91-physics-complete-20261020' if physics.get('engineering_replenishment')else'reference50-v4-ui91-physics-20261020',
        physical_stage='all500_frozen_new_AB_attempted',impact_stage='version_bound_physics_with_failures_retained',
        outcome_status='case_specific',physical_statuses=dict(Counter(r['status'] for r in rows.values())),
        formal_collection_ready=not diagnostic_preview and all(r['status']=='computed' for r in rows.values()),
        collection_condition=CONDITION,score_interpretation='family_role_judgment_with_disclosed_paired_model_estimates',
        source_case_bytes_modified=True,source_case_definition='new derived UI91 information packets;original proposal packets preserved;A/B commands unchanged',
        frozen_A_B_commands_modified=False,all_source_cases_retained=True,new_EP_runs=physics['engine_arms_in_this_bound_run'],production_deployed=False)
    m['engineering_replenishment']=physics.get('engineering_replenishment')
    m['native_attempts_during_preparation']=physics.get('native_attempts_during_preparation')
    m['source_pins'].update(parent_proposal_release_sha256=parent.signature,result_manifest_sha256=sha(results/'MANIFEST.json'),physical_release_builder_sha256=sha(Path(__file__)))
    m['implementation_files']={p.name:sha(p) for p in sorted(COLLECTOR.iterdir()) if p.is_file() and p.suffix!='.pyc'}
    (out/'FORMAL_RELEASE.json').unlink();m['files']={str(p.relative_to(out)):sha(p) for p in sorted(out.rglob('*')) if p.is_file()}
    m['release_sha256']=digest({k:v for k,v in m.items() if k!='release_sha256'});save(out/'FORMAL_RELEASE.json',m)
    release=Release(out)
    for cid,row in release.records.items():
        _,case=release.case(cid,row['household_id']);original=read(proposal_release/'public'/row['path'])
        if any(case[k]!=original[k] for k in ('plans','changes','context','collection_life_lines','VPP_requests')):raise ValueError('FROZEN_PRESENTATION_PLAN_CHANGED')
    return {'release_sha256':release.signature,'cases':500,'statuses':m['physical_statuses'],'new_EP_runs':m['new_EP_runs'],'answers_copied':False}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--proposal-release',required=True);p.add_argument('--results',required=True);p.add_argument('--out',required=True);p.add_argument('--diagnostic-preview',action='store_true');a=p.parse_args()
    print(json.dumps(build(a.proposal_release,a.results,a.out,a.diagnostic_preview),ensure_ascii=False))
