# 可复用的家庭生成算法

输入真实调查候选户、国家/角色配额和种子，输出可追溯的完整参考家庭、七天安排、4—6类控制接入、服务合同、审计与复现文件。**每户必须配备并控制空调；F类另需EV。** 本包处理benchmark第一步，未生成实际A/B题目、IDF、仿真或真人标签；既有冻结V9的1000户不被本包替换。

这是一套**调查事实约束下的分层配额抽样 + 规则补全 + 整数覆盖分配算法**。不是让大模型自由编家庭，也不根据国家推断角色。默认角色计数来自EB的584个被分配角色实验样本，不能解释为真实人口比例。

- [完整算法与伪代码](METHODS.md)
- [18条机器可读规则](RULES.json)；[六类角色与态度](ROLES.json)
- [文献与规则对应关系](EVIDENCE_MAP.md)；[参考文献](REFERENCES.bib)
- [输入、输出与扩展合同](DATA_CONTRACT.md)
- [验收与实测结果](ACCEPTANCE.md)

## 不需要调查数据的公开演示

Python 3.10，以下命令均在本仓库根目录运行。安装到自己的隔离环境；生成器本身不联网、不下载调查文件、不调用LLM或付费服务。

```bash
python -m venv .venv-household
source .venv-household/bin/activate
python -m pip install -r benchmark/household_stage1/generator/requirements.txt
python -B -m benchmark.household_stage1.generator make-example-pool --out /tmp/eb-demo-pool
python -B -m benchmark.household_stage1.generator generate --pool /tmp/eb-demo-pool/candidate_pool.jsonl --config benchmark/household_stage1/generator/configs/pilot96.json --out /tmp/eb-demo-96
python -B -m benchmark.household_stage1.generator verify /tmp/eb-demo-96
python -B -m benchmark.household_stage1.generator render-cards /tmp/eb-demo-96
```

演示池320户全部虚构，明确标记`SYNTHETIC`，不是公开真实家庭微数据；输出96户用于检查程序和规则。小样例明确关闭完整生产组合覆盖，不能据此声称通过1000户生产标准。输出目录必须全新，不覆盖已有数据。

## 使用获得授权的八国原始数据

按 [来源清单](../SOURCES.json)自行取得准确版本，复制并填写 [data_sources.example.json](configs/data_sources.example.json) 的八个文件路径。来源访问和再分发条款分别适用；本仓库不提供原始调查或真实生成卡。

```bash
python -B -m benchmark.household_stage1.generator prepare-sources --data-config /secure/data_sources.json --out /secure/normalized-pool
python -B -m benchmark.household_stage1.generator generate --pool /secure/normalized-pool/candidate_pool.jsonl --config benchmark/household_stage1/generator/configs/production1000.json --data-config /secure/data_sources.json --out /secure/new-cohort-1000
python -B -m benchmark.household_stage1.generator verify /secure/new-cohort-1000 --data-config /secure/data_sources.json
python -B -m benchmark.household_stage1.generator render-cards /secure/new-cohort-1000
```

输出家庭卡`HOUSEHOLD_CARDS.md`与完整逐户`household_cases.jsonl`在指定目录；卡片可能包含详细历史家庭组合，应在获授权的存储范围内保管。

## 生成更多

复制`production1000.json`，修改`households`、`seed`，或使用已提供的`production1200.json`；可设置国家子集/国家配额/六类配额。候选户在每一批内不重复，C/D配对同组划分。跨批去重需要调用方合并源键台账；不同种子不能保证两批源户不重叠。

人数不是无限可扩：源池及某国某类相容户有限，配额/配对/覆盖约束不足时程序保存失败台账并停止，绝不复制源户凑数。扩大真实池需新增来源或适配器与审计；不能把同一调查户多次变体计为新独立家庭。

## 规则的依据

EB提供六类角色；在家状态、活动到需求、自动控制接受度和设备服务约束有对应一手研究。具体钟点、40小时缺省工作周、照护阈值、温度幅度、连续EV策略以及覆盖配额属于可审计的实验操作化，见规则表。它们不会因为附了文献就自动成为全球统计规律。

源事实与`household_provenance`分开保存。生活数值默认值固定在版本化内核中；改这些值要修改代码和规则、重新验收并形成新版本。目前并非所有生活参数都可仅改JSON配置。
