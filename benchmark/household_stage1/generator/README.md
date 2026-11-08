# 可复用的家庭生成算法

本模块将**真实家庭调查、EB角色与样本比例、活动和电器服务规则**整合为完整生成流程，输出家庭信息、七天生活安排、4—6类可控电器及可复查的来源与验收记录。每户必须配备并控制空调，F类包含EV。

算法采用**调查约束的分层配额选户 → 角色与态度绑定 → 生活安排生成 → 整数规划分配控制组合 → 一致性验收与冻结**。各步骤的依据、参数和实现位置在规则表中逐项对应。

六类配额沿用[EB原论文附录A、表7](https://arxiv.org/html/2608.08691v1)中584份人类角色扮演调查的样本构成：A—F分别为97、116、73、88、91、119。按最大余数法扩展至1000户后为166、198、125、151、156、204；八国各125户，每国覆盖全部六类。

**家庭生成第一步已通过验收，可作为后续benchmark构造的家庭输入。** 可复用实现已验证1000户和1200户两档生成与重放，提供公开演示和真实来源两种运行方式。正式V9批次及新批次分别由各自清单标识。

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

公开演示使用320条标记为`SYNTHETIC`的合成测试输入，生成96户以检查程序和规则；覆盖要求见`pilot96.json`。1000/1200户使用各自的完整生产配置。每次运行指定全新输出目录。

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

扩量前检查各国、各类相容候选容量。满足配额、配对和覆盖要求时输出新批次；容量或求解不足时保存原因台账。扩大来源池的方法见[扩展合同](DATA_CONTRACT.md)。

## 每一步的生成依据

| 步骤 | 依据 | 实现结果 |
|---|---|---|
| 家庭背景 | 八国原始家庭调查与变量字典 | 成员、住房、设备和可用生活信息 |
| 角色和态度 | EB六类角色定义与584份调查的角色构成 | 六类语义、态度和精确配额 |
| 生活安排 | 原调查约束、EB作息锚点、活动与居住行为建模研究 | 成员相容的七天工作、通勤、上学、照护和服务机会 |
| 电器安排要求 | 设备服务建模研究、EB任务要求和本项目控制范围 | 完整周期、洗烘前置、EV停车补能、空调与热水服务约束 |
| 控制组合与验收 | 配额和组合覆盖设计、一致性检查与版本冻结 | 每户4—6类、空调必控、整批覆盖和字节重放 |

逐条参考和采用方式见[生成依据表](EVIDENCE_MAP.md)。调查字段、匹配结果和参考配置分别保存来源状态；具体钟点、温度幅度、照护阈值等由版本化规则给出。运行配置支持修改规模、国家和角色配额、种子及覆盖目标；生活规则参数的修改流程见[扩展合同](DATA_CONTRACT.md)。
