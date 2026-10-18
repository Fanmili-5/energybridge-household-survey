# 复现流程

## 1. 公开示例

环境：Python 3.9或以上，标准库。无需现有1000户、许可调查、天气文件或API。仓库根目录运行：

```bash
python -B -m unittest benchmark.ab_generation.test_generation benchmark.ab_generation.test_life benchmark.ab_generation.test_review -v
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

完整策略复核及冬季制热探针：

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

仿真后使用住房模块 `audit`生成审查，再用 `report-physics --input JOB --compiled COMPILED --runs RUNS --audit AUDIT --imported outputs/ab-import --out REPORT_DIRECTORY`回读后果。旧版可传 `--reference-stage PATH_TO_AC84_STAGE`比较共有A通道；新生活流程使用 `--reference-runs BASELINE_RUNS`核对完整当前A轨迹。报告不触发重选或修复。

## 5. 结果解读及版本变更

`SUMMARY.json`报告全批候选、缺失机会及指定分配，`MANIFEST.json`登记规则、代码、输入身份和输出文件。它不是物理验收或偏好统计报告。物理运行是否完成、服务是否满足、设备温度/SOC/费用后果与人类评价必须分开汇报。

A、生活资源、模型或天气改变时重新获取当前A参考；规则、事件或选择策略改变时重建候选及B；B改变时重算下游后果。禁止因负节约、未达标或可能被拒绝而覆盖旧结果。1000户正式仿真保持暂缓，当前任务不操作线上问卷。
