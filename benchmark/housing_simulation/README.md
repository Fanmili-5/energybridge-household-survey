# 住房与仿真场景生成

本模块提供 benchmark 物理环境的独立构造流程：建筑参数参照、面积约束外壳、家庭世界自动装配、A/B 模型编译、EnergyPlus 执行与物理审计。输入规模由住宅与案例列表确定；运行不需要历史家庭样本、已有物理包或生产批次目录。

`assemble` 将外壳与显式家庭契约转换为完整物理输入，绑定全部居住成员、床位、设施、设备、房间使用权、操作权限、逐日位置、服务依赖及控制。`reproduce` 以公开配置连续执行全部阶段，无须手工编写内部家庭物理包。

## 运行

在仓库根目录执行，使用 Python 3.12–3.14 和 [EnergyPlus 24.1.0](https://github.com/NatLabRockies/EnergyPlus/releases/tag/v24.1.0)。

```bash
python -m venv .venv-housing
source .venv-housing/bin/activate
python -m pip install -r benchmark/housing_simulation/requirements.txt
python -B -m benchmark.housing_simulation reproduce \
  --energyplus-dir /path/to/EnergyPlus-24-1-0 \
  --out /tmp/housing-reproduction
```

默认天气取自该引擎发行包的 Chicago TMY3 文件。公开实例包括单人住宅、三人家庭及包含一名邻户居民的共享住宅，均装配洗衣机、干衣机、洗碗机、热泵、储水式电热水器和 EV。三对 A/B 的程序时间及控制不同。该实例用于验证生成与执行流程；中国建筑参数与气象资源的使用见[构造方法](METHOD.md)和[复现指南](REPRODUCE.md)。

成功执行后，`MANIFEST.json` 的 `passed` 为 `true`，并生成下列目录。命令失败时返回非零退出码，已产生的失败记录保留。

| 目录 | 内容 |
| --- | --- |
| `shells/` | 面积账目、参考布局、外壳 IDF |
| `worlds/` | 成员与安装绑定、完整家庭物理包、A/B 请求、编译作业 |
| `compiled/` | 每臂 IDF、执行计划、设备计量映射与输入回执 |
| `runs/` | 原始引擎日志、SQL、10 min 轨迹与运行结果 |
| `audit/` | 计量闭合、程序电耗、服务完成、EV、热水、共同前史和恢复检查 |

## 接口与实现

| 命令 | 实现 | 职责 |
| --- | --- | --- |
| `match` / `extract-native` | `pipeline.py`、`kernel/native_bundle.py` | 确定性参照选择、原件与气象身份核验、构造提取 |
| `build-shell` | `kernel/geometry.py`、`kernel/shell.py`、`geometry_reference.py` | 面积约束、使用权份额和多热区外壳 |
| `assemble` | `assembly.py`、`installation.py`、`WORLD.schema.json` | 家庭契约校验、空间装配、逐日场景与基线执行检查 |
| `compile` | `components.py`、`kernel/compiler.py`、`kernel/execution.py` | 设备实例化、A/B 请求覆盖、物理执行语义 |
| `run` / `audit` | `pipeline.py`、`validation.py` | 固定引擎执行、SQL 回读及物理审计 |
| `reproduce` / `verify` | `validation.py`、`pipeline.py` | 公开端到端复现、阶段产物完整性检查 |

| `study` | `robustness.py`、`STUDY_PLAN.json` | 六案例Morris筛查、气流结构及数值收敛 |

## 技术文件

- [构造方法](METHOD.md)：算法、物理模型、外部依据与项目设定。
- [数据接口规范](INPUTS.md)：必需字段、单位、状态及阶段契约。
- [构建与复现指南](REPRODUCE.md)：公开实例、自定义批次与原生资源接入。
- [验证规范](VALIDATION.md)、[实际结果](RESULTS.md)与[验证记录](VALIDATION.json)：检查条件和实际覆盖范围。
- [证据边界与追踪矩阵](EVIDENCE.md)：逐阶段输入、来源、项目规则、实现及验收对应关系。
- [固定参数登记](ASSUMPTIONS.json)与[输入字段映射](FIELD_MAP.json)：参数性质及Schema字段覆盖。
- [注册验证计划](STUDY_PLAN.json)、[协议修订记录](STUDY_PLAN_HISTORY.json)与[敏感性/收敛结果](ROBUSTNESS_RESULTS.json)：参数域、判据、全部配置及实际结果。
- [整体审查记录](REVIEW.md)：本次发现、修订及验证范围。
- [来源登记](SOURCES.json)、[规则与依据映射](RULES.json)、[代码来源映射](SOURCE_MAP.json)：证据支持范围及实现定位。
- [公开家庭输入](examples/world_batch.json)与[机器可读输入规范](WORLD.schema.json)。

## 支持范围

外壳为单层矩形参考公寓，采用中间层与南北暴露边界。家庭装配支持全部共享住户名册、每个睡眠组一张参考床、矩形设施与落地设备安装、壁挂宽度预算、声明的接线与管线条件、一个储水箱及一辆 EV；每个热区至多一个独立控制的热泵。设施电表覆盖整个物理住宅，包含共享邻户；不自动折算为目标家庭分表。物理模型覆盖声明的人员与设备负荷；原型频率、设备拥有率、照护行为、住宅实测参数和人类接受标签不由该流程估计。

无法满足床位、安装、访问权限、供电或基线执行约束的住宅保留为 `rejected`。参考规则的适用边界及未建模条件在方法与验证文件中逐项声明。

中国资料用于DeST构造参照、广州户型有界约束和照明参考。活动散热、清空包络、整数规划与压力网络采用公开方法；面积换算、安装网格、日历和参数域等项目设定保留明确理由及边界，见[证据追踪](EVIDENCE.md#5-本次方法替代与保留设定)。

项目设定逐项理由、替换方式与未覆盖限制见[设计决策登记](DESIGN_DECISIONS.md)。

版本3.0.0保留`WORLD` v2的结构兼容性，但更新负荷和安装语义：活动散热替代统一功率，杂项默认待机为零，烹饪必须显式声明，联合布局替代顺序放置。既有作业重跑属于新模型配置，不能沿用旧版能量结论。公开前史更新为112天，求解步长按本版收敛结果登记。
