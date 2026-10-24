"""Portable public smoke package plus content-bound local evidence index."""
import argparse
import os
import json
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from benchmark.ab_generation.common import read,save,sha,digest,seal
from benchmark.ab_generation.unified.contract import code_hash


def build(out,prior,python,name='reproducible-package'):
    out,prior=Path(out).resolve(),Path(prior).resolve();package=out/name
    freeze=read(out/'GENERATOR_FREEZE.json')
    if code_hash()!=freeze['code_hash']:raise ValueError('GENERATOR_CHANGED_AFTER_FREEZE')
    package.mkdir(exist_ok=False)
    with zipfile.ZipFile(out/'GENERATOR_SOURCE.zip') as z:z.extractall(package)
    # Transitive import modules outside the four frozen source folders (for
    # example housing helpers) are needed even for a read-only public smoke.
    source_root=Path(__file__).parents[2];dependency_pins={}
    for p in (source_root/'benchmark').rglob('*.py'):
        relative=p.relative_to(source_root);destination=package/relative
        if '__pycache__' in p.parts or relative.parts[1]=='research_delivery' or destination.exists():continue
        destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,destination)
        dependency_pins[str(relative)]=sha(p)
    source=Path(__file__).parent;target=package/'benchmark/research_delivery'
    shutil.copytree(source,target,ignore=shutil.ignore_patterns('__pycache__'),dirs_exist_ok=True)
    save(package/'DEPENDENCIES.json',dependency_pins)
    records=read(prior/'public-inputs-v6/INPUTS.json')['records'];copied=[]
    for r in records:
        h,d=r['household_id'],r['date'];cp=package/'data/contexts'/(h+'__'+d+'.json.gz');pp=package/'data/portraits'/(h+'.json')
        cp.parent.mkdir(parents=True,exist_ok=True);pp.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(r['context_path'],cp);shutil.copy2(r['portrait_path'],pp)
        copied.append({**r,'context_path':'contexts/'+cp.name,'portrait_path':'portraits/'+pp.name})
    save(package/'data/INPUTS.json',dict(schema='eb.unified.inputs.v1',mode='audit_frozen',records=copied))
    # Also ship the full public life-input -> new-A route, not only old A.
    fresh=[]
    for r in read(out/'fresh-public/INPUTS.json')['records']:
        h,d=r['household_id'],r['date'];cp=package/'data/new-A-contexts'/(h+'__'+d+'.json.gz')
        cp.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(r['context_path'],cp)
        fresh.append({**r,'context_path':'new-A-contexts/'+cp.name,'portrait_path':'portraits/'+h+'.json'})
    save(package/'data/NEW_A_INPUTS.json',dict(schema='eb.unified.inputs.v1',mode='fresh_generation',records=fresh))
    replay_source=package/'data/replay-source';replay_records=[]
    for r in copied:
        replay_records.append({**r,'context_path':'../../'+r['context_path'],'portrait_path':'../../'+r['portrait_path']})
    save(replay_source/'public-inputs-v6/INPUTS.json',dict(schema='eb.unified.inputs.v1',mode='audit_frozen',records=replay_records))
    for h in sorted({r['household_id'] for r in copied}):
        src=prior/'public-A-source/connected/life_inputs'/h
        dest=replay_source/'public-A-source/connected/life_inputs'/h;dest.mkdir(parents=True,exist_ok=True)
        for n in ('LIFE_INPUT.json','resource_worlds.json'):shutil.copy2(src/n,dest/n)
    shutil.copytree(out/'fresh-public/A',package/'data/expected-public-A')
    hid='project-demo-000001';smoke=[r for r in fresh if r['household_id']==hid]
    save(package/'data/SMOKE_INPUTS.json',dict(schema='eb.unified.inputs.v1',mode='fresh_generation',records=smoke))
    save(package/'data/SMOKE_CONFIG.json',dict(rows_per_unit=1,queries_per_row=2,oracle_native_encoding_budget=128,selection_nodes=50,seed=20261022))
    shutil.copy2(out/'PROTOCOL.json',package/'PROTOCOL.json');shutil.copy2(out/'GENERATOR_FREEZE.json',package/'GENERATOR_FREEZE.json')
    shutil.copy2(out/'BASELINE_SOURCE.zip',package/'BASELINE_SOURCE.zip')
    lock=source_root/'benchmark/ab_generation/unified/requirements-lock.txt'
    shutil.copy2(lock,package/'requirements-lock.txt')
    shutil.copy2(lock,package/'benchmark/ab_generation/unified/requirements-lock.txt')
    dependency_pins['benchmark/ab_generation/unified/requirements-lock.txt']=sha(lock)
    save(package/'DEPENDENCIES.json',dependency_pins)
    reports=['CLAIM_GATES.json','COMPARISON_SUMMARY.json','FIFTY_ACCEPTANCE.json','FIFTY_SLOT_CHECK.csv',
             'FIFTY_MECHANISM_COVERAGE.csv','EXHAUSTIVE.json','RECIPE_EQUIVALENCE.json','IMMUTABILITY.json',
             'TESTS.log','TESTS-v5.log','REGRESSION.log','PRODUCTION_ORACLE_CHECK.json','A_REUSE_PROOF.json','REUSED_BASELINE_EVIDENCE.json',
             'INDEPENDENT_A_CHECK.json','COMPATIBILITY_REPLAY.json','EMPTY_DOMAIN_CHECK.json','EVIDENCE_LINEAGE.json',
             'SELF_REVIEW.md','SELECTION_REVIEW.json','ORDER_STUDY_SUMMARY.json','TEST_COMMANDS.json',
             'A_SAME_DEMAND_COMPARISON.json','INDEPENDENT_CAUSAL_CHECK.json','LONG_TAIL_AUDIT.json',
             'PREFERENCE_INTERFACE_AUDIT.json','FIFTY_RAW_COVERAGE.json','PUBLIC_FRESH_ACCEPTANCE.json',
             'FIFTY_SEMANTIC_COVERAGE.json','FIFTY_NUMERIC_EXPLORATION.json','FIFTY_COVERAGE_LAYERS.json.gz',
             'PUBLIC_FRESH_SEMANTIC_COVERAGE.json','PUBLIC_FRESH_NUMERIC_EXPLORATION.json','PUBLIC_FRESH_COVERAGE_LAYERS.json.gz',
             'FIFTY_GAP_DIAGNOSTICS.json','PUBLIC_FRESH_GAP_DIAGNOSTICS.json','TWO_HOUSE_TEN_DAY.md']
    for n in reports:
        if (out/n).exists():shutil.copy2(out/n,package/n)
    # These are full records, not summaries silently replacing unsuccessful runs.
    # Explicitly traverse linked, immutable earlier-component evidence too.
    trees=[out]+[p for p in out.iterdir() if p.is_symlink() and p.is_dir()]
    evidence={str(p.relative_to(out)):sha(p) for tree in trees for p in tree.rglob('*') if p.is_file() and
              not p.is_relative_to(package) and p.name not in ('DELIVERY_INDEX.json',) and p.suffix not in ('.log',)}
    save(out/'DELIVERY_INDEX.json',dict(schema='eb.research_delivery.index.v2',files=evidence,
        full_catalogues_retained_in=['fifty/catalogues','comparisons/catalogues'],
        public_portable_package=name,physical_runs=0,online_changed=False,main_updated=False))
    shutil.copy2(out/'DELIVERY_INDEX.json',package/'LOCAL_EVIDENCE_INDEX.json')
    (package/'README.md').write_text('''# 统一生成方法：可复现研究包

核心方法见 benchmark/research_delivery/METHOD.md。当前主张和未通过的门槛见 CLAIM_GATES.json（如存在）。
公开六类输入是合成实验情境；本包不包含真人答案，不代表真实人口分布。

## 复现

使用Python 3.14及requirements-lock.txt锁定环境。原运行库与平台见GENERATOR_FREEZE.json。

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
PYTHONPATH=. .venv/bin/python -B -m unittest benchmark.ab_generation.unified.test_delivery benchmark.ab_generation.unified.test_unified -q
PYTHONPATH=. .venv/bin/python -B -m benchmark.ab_generation.unified build --inputs data/SMOKE_INPUTS.json --config data/SMOKE_CONFIG.json --out replay-smoke --workers 1
```

INPUTS.json给出六类60个旧A审计日期；NEW_A_INPUTS.json为完整新A路线的60日期；SMOKE_INPUTS.json固定新A第一户十个原日期，计算预算较小，不代表完整覆盖验收。
相对输入路径按输入清单所在目录解析，可整体移动目录。复现比较计划、候选及选择；计时、内存和绝对输出路径允许不同。
配置、种子和求解器版本属于方法的一部分，不保证跨求解器版本逐字节相同。

完整公开A求解对照（54次，较慢）从原生活输入重新编译，不使用expected-public-A缓存：

```sh
mkdir replay-public
cp PROTOCOL.json replay-public/PROTOCOL.json
PYTHONPATH=. .venv/bin/python -B -m benchmark.research_delivery.fresh_parallel --out replay-public --prior data/replay-source --workers 2
```

data/expected-public-A保存全部预声明种子的参考结果，不是择优结果。公开小包可重放六类路线；含两户既有输入的24日期完整算法比较及50户影子目录通过LOCAL_EVIDENCE_INDEX定位本地完整交付，不把公开子集冒充全量公开复现。

LOCAL_EVIDENCE_INDEX.json索引本地完整50户和全部对照记录；较大的候选目录与诊断留在原交付根目录，不由汇总替代。
旧版本重放使用BASELINE_SOURCE.zip对应代码。当前入口明确不执行仿真、部署或合并main。
''')
    # Actually move the complete package and run its public CLI from there.
    with tempfile.TemporaryDirectory(prefix='eb-portable-') as temporary:
        moved=Path(temporary)/'moved package';shutil.copytree(package,moved)
        guard=Path(temporary)/'guard';guard.mkdir()
        (guard/'sitecustomize.py').write_text('''import os, sys, json
blocked_root=os.path.realpath(os.environ['EB_BLOCK_WORKSPACE'])
allowed_runtime=os.path.realpath(os.environ['EB_ALLOW_RUNTIME'])
log=os.environ['EB_GUARD_LOG']
def within(path,root):return path==root or path.startswith(root+os.sep)
def check(event,args):
    if event!='open' or not args or not isinstance(args[0],(str,bytes)):return
    p=os.path.realpath(os.fsdecode(args[0]))
    if within(p,blocked_root) and not within(p,allowed_runtime):
        with open(log,'a') as f:f.write(p+'\\n')
        raise PermissionError('PORTABILITY_FORBIDS_ORIGINAL_WORKSPACE:'+p)
sys.addaudithook(check)
''')
        env={**os.environ,'PYTHONPATH':str(guard)+os.pathsep+str(moved),
            'EB_BLOCK_WORKSPACE':str(source_root.parent),'EB_ALLOW_RUNTIME':str(Path(python).absolute().parents[1]),
            'EB_GUARD_LOG':str(guard/'blocked.log')}
        cmd=[str(python),'-B','-m','benchmark.ab_generation.unified','build',
             '--inputs','data/SMOKE_INPUTS.json','--config','data/SMOKE_CONFIG.json',
             '--out','replay-smoke','--workers','1']
        run=subprocess.run(cmd,cwd=moved,env=env,capture_output=True,text=True)
        report=read(moved/'replay-smoke/REPORT.json') if (moved/'replay-smoke/REPORT.json').exists() else None
        blocked=(guard/'blocked.log').read_text().splitlines() if (guard/'blocked.log').exists() else []
        passed=run.returncode==0 and report is not None and report['selected']==10 and not report['unresolved_slots'] and not blocked
        repeated=None;repeat_result=None
        if passed:
            again=Path(temporary)/'second relocation';shutil.copytree(package,again)
            second_env={**env,'PYTHONPATH':str(guard)+os.pathsep+str(again)}
            second=subprocess.run(cmd,cwd=again,env=second_env,capture_output=True,text=True)
            def plans(root):return {m['id']:digest({'A':m['A'],'B':m['B']}) for m in read(root/'replay-smoke/MATERIALS.json.gz')}
            repeated=second.returncode==0 and plans(moved)==plans(again)
            repeat_result=dict(process_returncode=second.returncode,stderr=second.stderr[-2000:],exact_selected_plans_and_ids=repeated)
            blocked=(guard/'blocked.log').read_text().splitlines() if (guard/'blocked.log').exists() else []
            passed=bool(repeated) and not blocked
        save(out/'PORTABILITY.json',dict(returncode=0 if passed else 1,process_returncode=run.returncode,report=report,stdout=run.stdout[-2000:],stderr=run.stderr[-3000:],
            copied_to_unrelated_directory=True,relative_paths_used=True,python_runtime=str(python),
            original_workspace_data_access_blocked=True,blocked_attempts=blocked,
            second_relocation=repeat_result,
            scope='directory portability with existing locked runtime;not clean-machine installation or all54 A rerun'))
        if not passed:raise ValueError('PORTABLE_REPLAY_FAILED:'+run.stderr[-2000:]+str(blocked[:5]))
        shutil.copy2(out/'PORTABILITY.json',package/'PORTABILITY.json')
    # Close the portability gate, then refresh the report and index included in
    # the bundle. The bundle must not retain its pre-smoke status as final.
    from .report import claim_gates
    from .overview import write
    claim_gates(out);write(out)
    for n in reports:
        if (out/n).exists():shutil.copy2(out/n,package/n)
    evidence={str(p.relative_to(out)):sha(p) for tree in trees for p in tree.rglob('*') if p.is_file() and
              not p.is_relative_to(package) and p.name not in ('DELIVERY_INDEX.json',) and p.suffix not in ('.log',)}
    save(out/'DELIVERY_INDEX.json',dict(schema='eb.research_delivery.index.v2',files=evidence,
        full_catalogues_retained_in=['fifty/catalogues','comparisons/catalogues','fresh-public/collection/catalogues'],
        public_portable_package=name,physical_runs=0,online_changed=False,main_updated=False))
    shutil.copy2(out/'DELIVERY_INDEX.json',package/'LOCAL_EVIDENCE_INDEX.json')
    seal(package,dict(schema='eb.public_repro_package.v2',core_code_sha256=code_hash(),physical_runs=0))
    with zipfile.ZipFile(out/(name+'.zip'),'w',zipfile.ZIP_DEFLATED) as z:
        for p in package.rglob('*'):
            if p.is_file():z.write(p,str(p.relative_to(package)))
    return dict(package=str(package),archive_sha256=sha(out/(name+'.zip')),portability=read(out/'PORTABILITY.json'))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--prior',required=True);p.add_argument('--python',required=True);p.add_argument('--name',default='reproducible-package')
    a=p.parse_args();print(build(a.out,a.prior,a.python,a.name))
