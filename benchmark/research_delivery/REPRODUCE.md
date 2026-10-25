# 当前公开复现入口 v2.11

当前CLI缺省读取`benchmark/ab_generation/unified/CURRENT_CONFIG.json`，开启精确任务数选题及分开的动作幅度/事件阶段。
显式`--config`保留该文件指定模式；`DEFAULT_CONFIG.json`用于旧内部API，不是当前推荐配置。
方法、来源和验收边界见METHOD.md、ACTION_CHANGE_METHOD.md及release_v2_11/。
原release_v2_10/和公开夹具FULL_CONFIG/SMOKE_CONFIG的显式v2.10配置继续保留，不能把历史重放标成v2.11。

## 环境和公开输入

本地锁定验证环境为Python 3.14.3、OR-Tools 9.15及SciPy 1.17.1；完整依赖见requirements-lock.txt。
已完成既有环境的异目录复现，未将其称为干净机器安装。CI只做下述轻量检查。

```sh
python -m pip install -r benchmark/ab_generation/unified/requirements-lock.txt
python -B -m unittest discover -s benchmark/ab_generation/unified -t . -p 'test_*.py' -v
python -B -m unittest discover -s benchmark/research_delivery -t . -p 'test_*.py' -v
```

`public_fixtures/`保存六类公开合成情境的生活、设备/住房、冻结家庭v3及十个原日期。
期望问题和A仅在重新计算后核对，不作为求解输入；该入口不重新采样画像。
原gzip期望A已无损转为UTF-8 JSON，语义摘要及原/新哈希见release_v2_10/SOURCE_BOUNDARY.json。
不包含原50户完整输入、真人回答或本轮新A/B的物理后果。

只重新编译六户需求，不求解A、不生成B：

```sh
python -B -m benchmark.research_delivery.public_replay \
  --inputs benchmark/research_delivery/public_fixtures/PUBLIC_REPLAY.json \
  --config benchmark/ab_generation/unified/CURRENT_CONFIG.json \
  --out NEW_PUBLIC_COMPILE --stage compile
```

第一户十天新A→B的低预算入口如下。此命令会做计划生成，但不运行物理仿真；本次CI不运行此命令。

```sh
python -B -m benchmark.research_delivery.public_replay \
  --inputs benchmark/research_delivery/public_fixtures/PUBLIC_REPLAY.json \
  --config benchmark/research_delivery/public_fixtures/SMOKE_CONFIG.json \
  --out NEW_PUBLIC_AB --household project-demo-000001 --workers 1
```

FULL_CONFIG.json使用完整声明的影子预算；省略household可运行六户60日期。烟雾预算不缩小动作域，
未知和缺额保留。所有输出目录必须是新目录，不覆盖旧产物，不失败重抽。

## 本地完整资料入口

```sh
python -B -m benchmark.ab_generation.unified build --inputs FROZEN_INPUTS.json --out NEW_SHADOW --workers 1
python -B -m benchmark.ab_generation.unified fresh --life-batch LIFE_BATCH.json --portraits PORTRAITS_DIR --dates GIVEN_DATES.json --out NEW_BATCH --workers 1
```

大写输入路径是授权完整资料的占位符，不是仓库自带文件。日期、画像先冻结；旧50户用只读影子模式。
新A/B不能绑定旧仿真。源码的规模由配置决定，本轮没有950/1000户性能证据，也不启动该生产。

## 验收范围

v2.11的先行两户原20题/848候选解释验收见[小规模汇总](release_v2_11/README.md)。随后已完成
[原50户500日期影子重选](release_v2_11/shadow50/README.md)：同一原候选池，95个日期改选另一份原候选，原A/B不变。
全量入口为`benchmark.research_delivery.shadow_selection`；协议须绑定原候选、实际v2.10对照选题、日期、配置、种子和核心哈希。
新注释保存在独立目录，不覆盖原候选。`axis_matrix`只作额外机器×人工组合诊断，不影响选择或补抽。
声明目标通过不代表细分组合全覆盖，更不是物理结果、真人理解度或训练有效性证据。

旧版本的本地协议绑定其核心和候选哈希；历史500日期审计使用fabcc48对应源码，不能直接把旧候选交给要求新轴的当前选择器。

v2.10先在原两户及0841固定反例的30个原日期、1298份原候选上核对修订，
再在全部50户500原日期、18,977份原候选上完成影子重选和独立工程/因果/最大匹配检查。
两次结果分别保存；公开汇总及本地复现说明见[shadow50汇总](release_v2_10/shadow50_aggregate/README.md)。逐户记录和完整协议保存在本地，不公开上传。
新增`benchmark.research_delivery.shadow_selection`只审计和重选题，不生成A/B。
完整50户输入不在公开仓库内，协议中的本地路径占位符需由获授权资料填写。
旧acb的两次异目录十天重放和500题审计继续按其原版本封存；这次不是新A/B生产或物理验收。

家庭模块源码包含历史私有夹具依赖的测试；具体依赖见family_generation/README.md，
其完整个体输入不在本次公开数据内。公开CI运行指定的算法、接口及原公共家庭测试子集，
不会调用历史50户夹具、全量比较、物理仿真、线上部署或1000户生成。
