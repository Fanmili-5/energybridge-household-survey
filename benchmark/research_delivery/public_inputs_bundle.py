"""Build a provenance-bound public replay preflight, without declaring release.

The final release still requires complete scientific acceptance and a fresh
freeze. This helper does not update claim gates or silently use early A caches.
"""
import argparse
from collections import defaultdict
from pathlib import Path
import shutil
import zipfile

from benchmark.ab_generation.common import read,save,sha,bound


def build(source_root,archive,review,raw_source,out,configuration):
    source_root,archive,review,raw_source,out=map(lambda p:Path(p).resolve(),(source_root,archive,review,raw_source,out))
    out.mkdir(parents=True,exist_ok=False);code_pins={}
    with zipfile.ZipFile(archive) as source:
        for name in source.namelist():
            if name.endswith('/'):continue
            target=bound(out,name);target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(source.read(name));code_pins[name]=dict(sha256=sha(target),origin='frozen_source_archive')
    # Transitive Python imports and static family/house/role rules are included;
    # generated private validation folders are not copied as public inputs.
    files=set((source_root/'benchmark').rglob('*.py'))
    # ui91.build invokes this local Node verifier. Python import discovery
    # alone cannot include that runtime dependency; no private UI cases copied.
    files.add(source_root/'benchmark/project/verify_refined_display.js')
    files.add(source_root/'benchmark/research_delivery/verify_offline_ui91.js')
    # Optional original automatic-cycle contract is data read at runtime, not
    # a Python import. Include its pinned source so relocation cannot fall
    # back to the original private checkout for a capability declaration.
    automatic_source=source_root/'benchmark/ab_generation/unified/AUTOMATIC_REFERENCE_SOURCE.json'
    if automatic_source.exists():
        record=read(automatic_source)
        original_rule=bound(automatic_source.parent,record['bundled_source'])
        if sha(original_rule)!=record['source_sha256']:
            raise ValueError('AUTOMATIC_REFERENCE_EVIDENCE_CHANGED_BEFORE_PACKAGING')
        files.update((automatic_source,original_rule))
    for folder in ('family_generation','housing','reference_worlds','project'):
        base=source_root/'benchmark'/folder
        files.update(p for p in base.glob('*') if p.is_file() and p.suffix in ('.json','.md','.txt'))
    for file in sorted(files):
        if '__pycache__' in file.parts:continue
        relative=str(file.relative_to(source_root));target=out/relative
        if target.exists() and 'research_delivery' not in file.parts:continue
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(file,target)
        code_pins[relative]=dict(sha256=sha(target),origin='explicit_transitive_or_review_dependency')
    if automatic_source.exists():
        packaged_source=out/automatic_source.relative_to(source_root)
        if sha(packaged_source)!=sha(automatic_source):
            raise ValueError('AUTOMATIC_REFERENCE_ARCHIVE_SOURCE_VERSION_MISMATCH')
        evidence=bound(packaged_source.parent,read(packaged_source)['bundled_source'])
        if sha(evidence)!=read(packaged_source)['source_sha256']:
            raise ValueError('AUTOMATIC_REFERENCE_EVIDENCE_MISSING_FROM_PACKAGE')
    for file in (source_root/'benchmark/research_delivery').glob('*.md'):
        target=out/file.relative_to(source_root);shutil.copy2(file,target)
        code_pins[str(file.relative_to(source_root))]=dict(sha256=sha(target),origin='review_method_document')
    notices=[source_root/name for name in ('THIRD_PARTY.md','CITATION.cff','UPSTREAM_TRACKED_FILES.json')]
    notices += [p for p in (source_root/'benchmark').rglob('*') if p.is_file() and
                (p.name.startswith(('LICENSE','NOTICE','COPYING')) or '_LICENSE.' in p.name)]
    for file in sorted(set(notices)):
        if not file.exists():continue
        target=out/file.relative_to(source_root);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(file,target)
        code_pins[str(file.relative_to(source_root))]=dict(sha256=sha(target),origin='existing_attribution_or_license_notice;no_new_rights_grant')
    protocol=read(review/'PROTOCOL.json');sources={r['household_id']:r for r in protocol['inputs']}
    dates=defaultdict(list)
    for r in read(review/'NEW_A_B_INPUTS.json')['records']:dates[r['household_id']].append(r['date'])
    if len(sources)!=6 or dates.keys()!=sources.keys():raise ValueError('PUBLIC_SIX_CLASS_ROSTER_MISMATCH')
    records=[];data_root=out/'data';data_root.mkdir()
    for hid,source in sorted(sources.items()):
        paths=dict(life=raw_source/hid/'LIFE_INPUT.json',world=raw_source/hid/'resource_worlds.json',
                   portrait=Path(source['portrait_path']),expected_problem=Path(source['problem_path']),expected_A=review/hid/'A.json.gz')
        for key,pin in [('portrait','portrait_sha256'),('expected_problem','problem_sha256')]:
            if sha(paths[key])!=source[pin]:raise ValueError('FROZEN_TARGET_REVIEW_INPUT_CHANGED')
        record=dict(household_id=hid,dates=sorted(dates[hid]),expected_seed=protocol['seed'])
        if len(record['dates'])!=10:raise ValueError('PUBLIC_DATE_COUNT_CHANGED')
        for key,path in paths.items():
            suffix='.json.gz' if path.name.endswith('.json.gz') else '.json'
            target=data_root/hid/(key+suffix);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
            record[key]=dict(path=str(target.relative_to(data_root)),sha256=sha(target))
        records.append(record)
    save(data_root/'PUBLIC_REPLAY.json',dict(schema='eb.public_life_replay.v1',households=records,
        source_scope='six public synthetic scenarios;frozen_v3_portraits;not_private_fifty',
        frozen_target_review_protocol_sha256=sha(review/'PROTOCOL.json'),profile_sampling_rerun=False))
    cfg=read(configuration);save(data_root/'FULL_CONFIG.json',cfg)
    save(data_root/'SMOKE_CONFIG.json',{**cfg,'rows_per_unit':1,'queries_per_row':2,'selection_nodes':50})
    lock=source_root/'benchmark/ab_generation/unified/requirements-lock.txt';shutil.copy2(lock,out/'requirements-lock.txt')
    code_pins['requirements-lock.txt']=dict(sha256=sha(out/'requirements-lock.txt'),origin='locked_runtime_requirements')
    save(out/'PACKAGE_SOURCES.json',dict(code=code_pins,source_archive_sha256=sha(archive),
        release_ready=False,goal_complete=False,scientific_acceptance_not_inferred_from_packaging=True,
        data_manifest_sha256=sha(data_root/'PUBLIC_REPLAY.json')))
    (out/'README.md').write_text('''# 公开复现入口预检包（不是最终科研交付）

本包固定六类公开合成情境的家庭v3画像及原始生活/设备资料。画像是已有基线，
本入口不重新采样画像；家庭v3代码与规则另附。可重放输入不包含原50户的完整私有资料、
真人答案或本轮新A/B的物理后果。源码附带少量旧验证摘要和清单，属于历史背景，
不能作为新题的后果或当前验收结论；文件和适用边界见benchmark/research_delivery/REPRODUCE.md。

在requirements-lock.txt对应环境中运行：

```sh
PYTHONPATH=. python -B -m benchmark.research_delivery.public_replay --inputs data/PUBLIC_REPLAY.json --config data/FULL_CONFIG.json --out compilation-check --stage compile
PYTHONPATH=. python -B -m benchmark.research_delivery.public_replay --inputs data/PUBLIC_REPLAY.json --config data/SMOKE_CONFIG.json --out one-house-new-A-B --household project-demo-000001 --workers 1
```

第一条重新编译六户生活需求并逐项对照，不解A、不生成B。第二条从固定第一户的原始生活输入
重新生成十天A，再构造B并选题。SMOKE降低的是搜索预算，未缩小原数值域；未知及缺额保留，
不能用烟雾验证冒充正式覆盖。使用FULL_CONFIG且省略household可重放六户60日期。

完整54次A检查可用`--stage A --all-fixed-seeds`，不使用期望A缓存代替求解。
所有期望问题/计划仅在本次计算后读取用于核对，不作为求解输入；输入缺失、A失败、对照差异均保留。
所有路径相对PUBLIC_REPLAY.json所在目录解析。当前包不自动运行仿真、改线上、启动1000户或合入main。

THIRD_PARTY.md及相邻许可文件沿用原声明，不为所有来源统一授予新许可。
根CITATION.cff保留原仓库的历史引用条目，不表示本预检包已发布为该版本；本包源代码与输入版本以
PACKAGE_SOURCES.json及数据清单为准。历史授权记录不替代当前“不提交、不部署、不仿真”的操作边界。

本命令只构造预检包，不执行或判定科研验收。当前各阶段状态见benchmark/research_delivery/DELIVERY_STATUS.md；
是否交付须另核对对应版本的选题、50户验收、来源封存及异目录重放证据，不能由打包成功推断。
''')
    return dict(package=str(out),households=len(records),date_slots=sum(len(r['dates']) for r in records),
                source_files=len(code_pins),release_ready=False)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('source-root','archive','review','raw-source','out','configuration'):p.add_argument('--'+name,required=True)
    a=p.parse_args();print(build(a.source_root,a.archive,a.review,a.raw_source,a.out,a.configuration))
