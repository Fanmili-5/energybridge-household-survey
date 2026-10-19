# 第三方来源

- EnergyBridge：<https://github.com/Agentic-Intelligence-Lab/EnergyBridge>，固定提交记录在 `UPSTREAM_TRACKED_FILES.json`。本仓库的构建脚本验证该提交的文件哈希，不修改作者检出目录。使用其代码及派生 IDF 时须核对作者的授权；本仓库不替上游授予许可。
- EnergyPlus 24.1：安装脚本从官方发布下载；住房生成模块保留官方PTHP示例的组件与性能曲线子集，以及官方schema的IDF字段序列。版本、源文件哈希与可重复提取命令见`benchmark/housing_simulation/SOURCES.json`及`export_resources.py`；许可全文保存在`benchmark/housing_simulation/resources/ENERGYPLUS_LICENSE.txt`。
- 气象：<https://climate.onebuilding.org/>，每个站点的完整下载链接和文件校验值保存在 `simulation_resources/catalog.json`。首次运行按来源下载，不在 Git 中再次分发 EPW/DDY 原文件；须遵循相应源数据的使用条件。
- 行政名称：<https://github.com/modood/Administrative-divisions-of-China>，2023-06-30 快照。来源项目使用 WTFPL v2；许可全文见 `simulation_resources/administrative/LICENSE`。这里只用于省市输入联动，不是现行行政区划权威证明。
- Playwright、Python 第三方依赖等分别遵循其自身许可。
- PsychroLib 2.5.0：<https://github.com/psychrometrics/psychrolib>，Meyer与Thevenard，JOSS 2019，DOI10.21105/joss.01137。家庭1000参考检查所附 `psychrolib_reference.py` 保留原实现归属，旁附 `PSYCHROLIB_LICENSE.txt`（MIT；Copyright 2018–2020 The PsychroLib Contributors）；它只支持湿空气数值核验，不授予住宅或设备性能验证。

本仓库没有为所有来源统一声明一个开源许可证。

第二主线的原EB设计引用、项目历史规则原文、论文采用范围及公开路径见`benchmark/ab_generation/EVIDENCE.md`和`SOURCES.json`。该次更新未新增直接复制原EB源文件或论文全文。`AUTHORIZATION.json`分别登记源码/输入发布范围、模型设备权限、住户同意和未核验的许可/伦理事项；公开可追溯不等于统一开放许可或实地执行授权。

家庭六类偏好方法模块的第三方依据为固定提交的EnergyBridge角色/实验材料、Energy Consumers Australia的June2026调查、Statnett/NTNU的iFlex动态电价问卷、荷兰Hassles and Habits调查及奥尔堡大学/ERC的eCAPE。作者/机构、直接数据链接、版本、采样和许可边界见[`benchmark/household_archetypes/SOURCES.json`](benchmark/household_archetypes/SOURCES.json)，下载地址与SHA256见[输入锁](benchmark/household_archetypes/INPUTS.lock.json)。本仓库新增公开的是本项目研究脚本、分析计划和聚合结果，不再分发第三方原始个人答卷；使用原件须遵守各来源条款。多源外部支持不构成对EB六类及人口比例的共同验证，也不产生问卷答案。


当前参考基准的输入边界见`benchmark/DATASET_CARD.md`。生成源码包含既有PsychroLib参考实现，保留其原版权及MIT许可；源目录相邻许可文件按`benchmark/generation/SOURCE_CATALOG.json`一并保留。当前代码可见性不为所有研究输入统一授予新许可。
