# 复现流程

## 三个缺额：静态验收与可选物理流程

本轮只验收计划设计；以下命令不启动EnergyPlus，不需要新B结果。仓库根目录执行：

```bash
python -B -m unittest benchmark.ab_generation.test_gap_review benchmark.ab_generation.test_static_sampling -v
python -B -m benchmark.ab_generation.static_sampling recheck --require-coverage --out outputs/final-static-check
python -B -m benchmark.ab_generation.validation.gap_supplement.recompute --out outputs/gap-static-check
python -B -m benchmark.ab_generation.audit_design
```

完整缺额诊断也只读取公开冻结A：

```bash
python -B -m benchmark.ab_generation.gap_review diagnose --out outputs/gap-diagnosis
```

新版最终静态样本已封存于 `validation/gap_supplement/final_sample`。上述 `recheck`只回放固定去重目录和已选计划，不生成新候选、不运行引擎。十层10/10达标，203个未覆盖交互仍列明；不等于物理后果已验证。Python3.9.6和3.14.3各156项检查通过。

需要独立重建全目录时，使用公开三个A上下文，仅标准库即可：

```bash
python -B -m benchmark.ab_generation.static_sampling build --out outputs/final-static-rebuild
```

输出目录必须不存在；该命令按原配置枚举全部候选和联合，再做同一定义的指令规范化与分层，耗时高于固定回放，不使用EnergyPlus、住房包或真实住户数据。固定样本构建使用Python3.14.3；跨版本以封存JSON、选择身份和覆盖表比较，不承诺gzip容器字节或所有新生成浮点累计跨运行时完全一致。`--generated-index`可接收已封存生成结果的“情境ID/变体ID→路径”映射，逐项核对A和完整规则绑定；它复用候选，不是按B后果替换候选。

后续若选择验证物理后果，可显式依次使用 `gap_review reference`、`gap_review prepare`、`joint_tail frame`、`joint_tail execute`，各命令的 `--help` 给出参数。它们不是本轮必跑步骤；A/A先导源码及身份分别由 `A_BUILD_SOURCE.json` 与 `A_BUILD_IDENTITY.json` 保存，旧冬季物理准入失败原样保留。任何后续B执行前须另行封存最终选择、代码身份、计划与种子，不能按结果重抽。

GitHub push/PR只运行静态检查。原完整回放与物理工作流保留为显式 `workflow_dispatch` 选项，默认关闭；不在本轮触发。历史六档可复现，新版本显式使用24档与32768预算。规则与当前缺额见 [GAP_METHOD.md](GAP_METHOD.md)、[GAP_VALIDATION.md](GAP_VALIDATION.md)。

本版生成上下文/结果为v3，明确[完整A离线信息条件](OFFLINE_EXPERIMENT.md)及[合成提案目的](DESIGN.md)。旧v1/v2上下文须重建或重新只读导入；历史结果保持原版本。先执行`python -B -m benchmark.ab_generation.audit_design`，核对公开来源、参数与授权登记。手工分阶段运行`reference-life`时必须提供`--audit BASELINE_AUDIT`；完整复现命令自动传入并核对基线审查。

## 1. 公开示例

环境：Python 3.9或以上，标准库。无需现有1000户、许可调查、天气文件或API。仓库根目录运行：

```bash
python -B -m unittest benchmark.ab_generation.test_generation benchmark.ab_generation.test_life benchmark.ab_generation.test_review benchmark.ab_generation.test_sampling benchmark.ab_generation.test_opportunity -v
python -B -m benchmark.ab_generation generate \
  --input benchmark/ab_generation/examples/batch.json \
  --rules benchmark/ab_generation/examples/rules.json \
  --out outputs/ab-example
python -B -m benchmark.ab_generation verify outputs/ab-example
```

同输入、规则和代码在相同Python/zlib运行环境产生相同内容及清单。依赖身份使用规范JSON摘要，不依赖gzip重压缩字节跨运行时相同。不同Python/zlib版本的gzip容器字节可能变化；比较规范JSON而不是据此判断方法改变。

## 2. 生活到A及完整公开物理流程

在仓库根目录先生成A：

```bash
python -B -m benchmark.ab_generation build-life \
  --input benchmark/ab_generation/examples/life/life_batch.json \
  --out outputs/life-A
python -B -m benchmark.ab_generation verify outputs/life-A
```

该命令只依赖标准库，不读取历史家庭、事件或电价。空间资源及生活安排均为公开的声明式输入，参数含义见 `LIFE_METHOD.md`和 `LIFE_RULES.json`。

物理集成使用Python 3.12或以上；安装住房模块固定依赖并准备官方EnergyPlus24.1后，执行：

```bash
python -m pip install -r benchmark/housing_simulation/requirements.txt
python -B -m benchmark.ab_generation reproduce-life \
  --energyplus-dir /path/to/EnergyPlus-24-1-0 --out outputs/life-AB
python -B -m benchmark.ab_generation verify outputs/life-AB
```

该流程重新生成空间绑定、整月A、A=B基线和当前A参考，并分别执行三种B规则及完整后果回读。默认三个公开家庭及芝加哥典型年天气仅用于数值集成，不代表中国家庭校准。所有规模来自配置。

完整策略复核及冬季制热探针使用专门的长日历输入，沿用住房v3的112日前史、5分钟求解、10分钟行为/报告和9日尾期：

```bash
python -B -m benchmark.ab_generation reproduce-strategies \
  --energyplus-dir /path/to/EnergyPlus-24-1-0 --out outputs/strategy-review
python -B -m benchmark.ab_generation verify outputs/strategy-review
python -B -m benchmark.ab_generation reproduce-strategies \
  --input benchmark/ab_generation/examples/strategy_review/winter_life_batch.json \
  --experiments benchmark/ab_generation/examples/strategy_review/winter_experiments.json \
  --plan benchmark/ab_generation/examples/strategy_review/winter_plan.json \
  --energyplus-dir /path/to/EnergyPlus-24-1-0 --out outputs/winter-review
```

计划在B执行前保存为 `REVIEW_PLAN.json`。完整计划包括同A三策略、四类设备、联合和明确预设的EV出发目标失败；若该失败没被检出，或还出现其他失败，复核不算通过。每组保存编译、运行、审查和完整报告。冬季个体温度偏好明确未知，检查范围限于原生制热证据与执行。CI使用固定官方Linux引擎重跑这两项公开流程。

使用自有家庭时通过 `--input`、`--world-contracts`、`--shell-config`和 `--experiments`提供相应输入；分阶段接口及资源文件哈希规则见 `LIFE_INPUTS.md`。原始家庭或新生成A不能仅因增加了模板字段就复用旧轨迹。

## 3. 当前50户只读导入

需要持有已授权的AC84家庭包、500个配对输入、每案A臂 `INPUT.json.gz`、`RESULT.json`、`TRACE_ARCHIVE.json`和 `TRACE.json.xz`。导入器按明确的旧格式读取，不启动旧生成器，也不读取B仿真结果。

```bash
python -B -m benchmark.ab_generation import-current \
  --stage PATH_TO_AC84_STAGE \
  --tariff PATH_TO_EXPLICIT_TARIFF_JSON \
  --tariff-sha256 bee328abc9c397a275cfb59df92c66d749678cf2536b70dc7b15efac07b5014d \
  --out outputs/ab-import
python -B -m benchmark.ab_generation verify outputs/ab-import
python -B -m benchmark.ab_generation generate \
  --input outputs/ab-import/BATCH.json \
  --rules benchmark/ab_generation/examples/rules.json \
  --out outputs/ab-candidates
python -B -m benchmark.ab_generation verify outputs/ab-candidates
```

`--limit N`仅用于明确标记的小批检查。不传时按输入清单全部导入，代码不固定50户或500组。电价参数可省略，此时费用排序明确不可用。当前适配器接受原实验的 `daily_periods` 格式，每段字段为 `start_min,end_min,CNY_per_kWh`；它不是实时电价抓取器。既有电价是共用实验情境，不是每户真实电价。

旧B逐案保存在 `legacy/`，新v2上下文保存在 `contexts/`。新导入明确权限、原A46项目程序约束及原计量口径；旧A缺少原生模式通道时记录模式不可用。既有A=B及指定失败从原命令分配元数据继承，不根据新仿真结果重新分组。旧规范目录不得原地补字段后沿用旧清单，应新建导入目录。

## 4. 历史输入配对物理验证

在生成前声明所验证的案例及选择规则。例：

```bash
python -B -m benchmark.ab_generation export-physics \
  --stage PATH_TO_AC84_STAGE \
  --annual-A-root PATH_TO_ORIGINAL_ANNUAL_A_DIRECTORY \
  --imported outputs/ab-import --generated outputs/ab-candidates \
  --case ordinary-v6-0054__2025-02-15 \
  --policy known_profile_vpp --out outputs/ab-physics-inputs
python -B -m benchmark.housing_simulation compile \
  --input outputs/ab-physics-inputs/physics_job.json \
  --out outputs/ab-compiled
python -B -m benchmark.housing_simulation run \
  --compiled outputs/ab-compiled --out outputs/ab-runs \
  --engine /path/to/energyplus --engine-sha256 ENGINE_BINARY_SHA256
python -B -m benchmark.housing_simulation verify outputs/ab-runs
```

原年度A目录内各户文件须与家庭包登记的原SHA相符，提供完整跟随期独立需求；没有文件即拒绝，不从排程反推。每房间多套独立AC的旧世界不在当前内核范围，不能用这些案例演示成功交接。

物理环境另按住房模块安装依赖。当前集成使用EnergyPlus `24.1.0-9d7789a3ac`，每案沿用原A回执的实际前史及尾期；实际尾期还随最后请求延展。不同前史/尾期的案例自动分成多个 `physics_job_history_*_tail_*.json`，清单见 `JOBS.json`；单一设置时使用 `physics_job.json`。原日历不足时拒绝，不能隐式截断或补出日程。所有新请求都重新编译，不复用旧B物理结果。

仿真后使用住房模块 `audit`生成审查，再用 `report-physics --input JOB --compiled COMPILED --runs RUNS --audit AUDIT --imported outputs/ab-import --out REPORT_DIRECTORY`回读后果。旧版可传 `--reference-stage PATH_TO_AC84_STAGE`比较共有A通道；住房v3改变模型后这项比较可能失败，此时只保留诊断，不算闭环验收；新生活流程使用 `--reference-runs BASELINE_RUNS`核对完整当前A轨迹。报告不触发重选或修复。

## 5. 结果解读及版本变更

`SUMMARY.json`报告全批候选、缺失机会及指定分配，`MANIFEST.json`登记规则、代码、输入身份和输出文件。它不是物理验收或偏好统计报告。物理运行是否完成、服务是否满足、设备温度/SOC/费用后果与人类评价必须分开汇报。

A、生活资源、模型或天气改变时重新获取当前A参考；规则、事件或选择策略改变时重建候选及B；B改变时重算下游后果。禁止因负节约、未达标或可能被拒绝而覆盖旧结果。1000户正式仿真保持暂缓，当前任务不操作线上问卷。

## 长尾样本（第二条线）

若只重建本次固定A下的入样命令，无需安装物理引擎：

```sh
python -B -m benchmark.ab_generation sample-tail \
  --contexts benchmark/ab_generation/validation/rules/frozen_contexts \
  --plan benchmark/ab_generation/examples/compatibility/rule_review_v1.json \
  --out /absolute/path/frozen-tail-sample
```

将输出所选记录的 `sample_id`、`stratum`、`B_commands_sha256` 与公开 `validation/rules/SELECTION.json` 对照。精确运行环境是Python3.14.3；跨Python版本比较命令与配额，候选预测的浮点细节及别名不作为跨版本字节一致承诺。重新跑引擎会生成新A回执，样本可随上下文哈希改变，但仍须满足同一覆盖合同。

先按本页 `reproduce-strategies` 命令生成公共合成A参考目录 `life-results`。也可显式复用同引擎、完整哈希绑定且审查通过的既有A参考；这不代表新做了A标定。采样不读取原目录中的任何已执行B。

```sh
python -B -m benchmark.ab_generation sample-tail \
  --contexts /absolute/path/life-results/contexts \
  --plan benchmark/ab_generation/examples/tail/plan.json \
  --out /absolute/path/tail-sample
python -B -m benchmark.ab_generation reproduce-tail \
  --reference-root /absolute/path/life-results \
  --plan benchmark/ab_generation/examples/tail/plan.json \
  --energyplus-dir /absolute/path/EnergyPlus-24-1-0 \
  --out /absolute/path/tail-results
python -B -m benchmark.ab_generation verify /absolute/path/tail-results
```

第一条命令供仅构造样本时使用；第二条自带同样的封存采样，再执行，两个输出目录必须全新。`sample/PLAN.json`、`CATALOGUE.json.gz`、`SELECTION.json` 和全部规则变体在第一个B运行前固定。每个可执行样本单独导出、编译和运行A/B，避免同案号多B混淆；静态诊断不执行。`OBSERVATIONS.json`、各执行目录及 `RESULT.json` 保留失败与未知；`COVERAGE.md` 列验收表。验收失败返回非零状态；不得依据这些结果换种子或重抽成功B。

CI在原夏季公共复现后增跑该长尾命令，沿用同一基线，不启动1000户或线上问卷。已发布小规模回执见 `TAIL_VALIDATION.json`、`TAIL_VALIDATION.md`、`validation/tail/`；原生SQL/轨迹保存在本地封存证据和CI短期artifact，永久再生依据是公开输入、代码版本、引擎与命令。

## 当前生成规则与覆盖验收

当前规则使用新节点参考及逐设备依据。历史tail回执不改写，不能用新算法重建旧候选ID。上面的冻结帧命令比较当前`validation/rules/SELECTION.json`；原执行时选择另存`PHYSICAL_SAMPLE_SELECTION.json`，代码差异及命令/IDF等价证明见`validation/rules/EQUIVALENCE.json`。

```bash
python -B -m benchmark.ab_generation reproduce-tail \
  --reference-root /absolute/path/life-results \
  --plan benchmark/ab_generation/examples/rule_review/plan.json \
  --energyplus-dir /path/to/EnergyPlus-24-1-0 --out /absolute/path/rule-results
python -B -m benchmark.ab_generation reproduce-tail \
  --reference-root /absolute/path/winter-results \
  --plan benchmark/ab_generation/examples/rule_review/winter_plan.json \
  --energyplus-dir /path/to/EnergyPlus-24-1-0 --out /absolute/path/rule-winter-results
python -B -m benchmark.ab_generation reproduce-strategies \
  --experiments benchmark/ab_generation/examples/rule_review/weekend_experiments.json \
  --plan benchmark/ab_generation/examples/rule_review/weekend_plan.json \
  --energyplus-dir /path/to/EnergyPlus-24-1-0 --out /absolute/path/rule-weekend-results
```

各输出目录必须全新。先按既有夏季、冬季命令生成基线参考；新参考自动含原生水箱节点。每个长尾计划在第一个B执行前封存。验收失败时保留整批，不换种子、不调配额补成功样本。当前30个新引擎臂的来源、版本及范围见[RULES_VALIDATION.md](RULES_VALIDATION.md)。

## 合入后自查：只重算原封存结果

```bash
python -B -m benchmark.ab_generation.validation.self_check.recompute \
  --out /absolute/path/ab-self-check
```

无需引擎或历史私有数据。校验原选择回执与样本集合，再按逐目标依据重算覆盖；没有重新取样、修改B或覆盖原物理结果。当前夏季目标出现次数由9修正为10，原无效/部分/失败样本及验收结论不变。生成不变性与新增回归见[SELF_CHECK.md](SELF_CHECK.md)。

## 新联合目录正式长尾验收

当前入口、22层事前计划及公开冻结A重放见[JOINT_TAIL_METHOD.md](JOINT_TAIL_METHOD.md)。精确取样重放使用`joint_tail frame-frozen`及`validation/joint_tail/frozen_inputs`；物理重跑先生成新A、再用`frame`封存并`execute`，不要求新引擎A的哈希和样本ID与旧平台相同。历史回放须显式旧规则，不能把不同生成器的旧样本数量当作本轮结果。
