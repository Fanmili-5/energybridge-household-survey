# 复用与扩展合同

## 支持的来源版本

原件详情与SHA见 [SOURCES.json](../SOURCES.json)。`data_sources.example.json`按下列8个逻辑键指定文件；只读原件，生成的`source_layout`是私有工作目录中的符号链接布局，没有自动下载。

| 逻辑键 | 对应国家/用途 |
|---|---|
| CRECS2012 | 中国同户成员、住房、能源/设备信息 |
| RECS2020_v7 | 美国住宅能源微数据 |
| ENABLE_EU | 英国、西班牙、德国共同调查工具 |
| IRES2020 | 印度家庭能源与使用信息 |
| ENASIC2022 | 墨西哥家庭成员与照护 |
| ENIGH2024_hogares | 墨西哥跨户住房匹配输入之一 |
| ENIGH2024_viviendas | 墨西哥跨户住房匹配输入之一 |
| ECA2025 | 澳洲2025年6月Consumer Energy Report Card原始表 |

`prepare-sources`一次读8份。即使生成国家子集，完整原件审计路径当前仍要求8份；这属于实现限制。不能只换同名新版文件或篡改SHA来跳过字段升级审计。禁止将封存评估源/标签接入本候选池。

标准池每行含`source`(dataset/country/household_key)、`pool_id`、`block`、带value/status/fields的家庭/住房/设备/人/在家字段及来源专属补充字段。国家适配器的具体规范以`_engine/v8/adapter_v8.py`和`_engine/admitted/country_adapter.py`及对应独立raw审计为准。不要通过手填几列CSV伪装成可审计真实池。

## 运行输出

| 文件 | 含义 |
|---|---|
| CONFIG.json / QUOTAS.json | 生效配置、精确国家/角色/交叉配额 |
| selected_cohort.jsonl / ordinals.json | 控制分配前的成员/参考周基线和固定序号 |
| control_assignment.json / CONTROL_ALLOCATION.json | 冻结组合与求解状态；不存A/B优化结果 |
| household_cases.jsonl | 最终逐户JSON，含完整7天日程、控制/资产/合同/来源台账 |
| POPULATION_AUDIT.json / SELECTION_REPORT.json | 整批覆盖与拒绝记录 |
| groups.jsonl | 源户和C/D配对的split_group；下游必须按group划分 |
| MANIFEST.json | 输入/输出/代码hash、环境和验收范围 |
| HOUSEHOLD_CARDS.md | 可选，单独render生成完整中文卡；不是冻结生成结果的必要部分 |
| FAILURE.json / SELECTION_FAILURE.json | 失败原因，不能作为passed数据使用 |

MANIFEST内部哈希用于完整性检查，不是数字签名；故意同时重写manifest和数据不是其安全威胁模型。源文件原路径留在私有工作区的来源报告中，不进入公开测试收据。

## 调整参数

国家子集限当前8国；国家配额和角色配额均须非负整数并加和等于N；每国六类与C/D配对默认开启。配额矩阵可以显式提供，必须同时通过行列/整数/单元和配对检查。不能通过配置推断新国家的未实现字段适配。

种子控制源户排序、成员/参考安排与优化破平。修改N、种子或任何生活默认规则得到的是新实验批次，不能沿用旧结果或冻结名。`profile_alternatives`控制候选补全尝试次数；求解预算耗尽时保留失败，不自动降低质量要求。

### 新增国家/来源

1. 取得合法逐户数据与字典，明确同户关联、调查年/发布年、原件SHA和缺失/插补范围。
2. 实现源适配器，保留每个事实的原字段、状态、量纲和语义；运行补全独立标记。
3. 实现直接从原件重新核验的独立审计，不以生成器自身值作为正确答案。
4. 统计六类相容容量、剔除/缺口原因和覆盖可行性；修改国家代码、配置和来源清单。
5. 跑真实小批、反例、完整配额与重放；评估国家×角色混杂、抽样限制和时间规则的适用性，再发布新规则版本。

### 增加更多独立家庭

当前严格筛选池为18647条，最小国家池印度291，候选数不是各角色可用容量。不同批次可能选到同一源户；下游合并时必须以`dataset+household_key`全局去重，并将C/D和变体归组。超出现有可用容量，需新增真实源数据或明确改成同户变体实验，不能把复制户当新的独立家庭。
