# 第三方来源

- EnergyBridge：<https://github.com/Agentic-Intelligence-Lab/EnergyBridge>，固定提交记录在 `UPSTREAM_TRACKED_FILES.json`。本仓库的构建脚本验证该提交的文件哈希，不修改作者检出目录。使用其代码及派生 IDF 时须核对作者的授权；本仓库不替上游授予许可。
- EnergyPlus 24.1：安装脚本从官方发布下载；住房生成模块保留官方PTHP示例的组件与性能曲线子集，以及官方schema的IDF字段序列。版本、源文件哈希与可重复提取命令见`benchmark/housing_simulation/SOURCES.json`及`export_resources.py`；许可全文保存在`benchmark/housing_simulation/resources/ENERGYPLUS_LICENSE.txt`。
- 气象：<https://climate.onebuilding.org/>，每个站点的完整下载链接和文件校验值保存在 `simulation_resources/catalog.json`。首次运行按来源下载，不在 Git 中再次分发 EPW/DDY 原文件；须遵循相应源数据的使用条件。
- 行政名称：<https://github.com/modood/Administrative-divisions-of-China>，2023-06-30 快照。来源项目使用 WTFPL v2；许可全文见 `simulation_resources/administrative/LICENSE`。这里只用于省市输入联动，不是现行行政区划权威证明。
- Playwright、Python 第三方依赖等分别遵循其自身许可。
- PsychroLib 2.5.0：<https://github.com/psychrometrics/psychrolib>，Meyer与Thevenard，JOSS 2019，DOI10.21105/joss.01137。家庭1000参考检查所附 `psychrolib_reference.py` 保留原实现归属，旁附 `PSYCHROLIB_LICENSE.txt`（MIT；Copyright 2018–2020 The PsychroLib Contributors）；它只支持湿空气数值核验，不授予住宅或设备性能验证。

本仓库没有为所有来源统一声明一个开源许可证。

第二主线的原EB设计引用、项目历史规则原文、论文采用范围及公开路径见`benchmark/ab_generation/docs/core/EVIDENCE.md`和`SOURCES.json`。历史更新未新增直接复制原EB源文件或论文全文。本轮增加paper-v1-final原family_runner.py冻结快照，用于提取并执行原检查时钟相关AST；来源为c58a2a7a3189482f57b93ddd0637f2c58ce5b5d0，文件身份见benchmark/ab_generation/paper_v1_clock_source.provenance.json。保留上游归属，不为其重新授予许可。`AUTHORIZATION.json`分别登记源码/输入发布范围、模型设备权限、住户同意和未核验的许可/伦理事项；公开可追溯不等于统一开放许可或实地执行授权。

家庭六类偏好方法模块的第三方依据为固定提交的EnergyBridge角色/实验材料、Energy Consumers Australia的June2026调查、Statnett/NTNU的iFlex动态电价问卷、荷兰Hassles and Habits调查及奥尔堡大学/ERC的eCAPE。作者/机构、直接数据链接、版本、采样和许可边界见[`benchmark/household_archetypes/SOURCES.json`](benchmark/household_archetypes/SOURCES.json)，下载地址与SHA256见[输入锁](benchmark/household_archetypes/INPUTS.lock.json)。本仓库新增公开的是本项目研究脚本、分析计划和聚合结果，不再分发第三方原始个人答卷；使用原件须遵守各来源条款。多源外部支持不构成对EB六类及人口比例的共同验证，也不产生问卷答案。


当前参考基准的输入边界见`docs/DATASET.md`。生成源码包含既有PsychroLib参考实现，保留其原版权及MIT许可；源目录相邻许可文件按`benchmark/generation/SOURCE_CATALOG.json`一并保留。当前代码可见性不为所有研究输入统一授予新许可。

新家庭生成模块的新增代码、方法文档及声明的合成参考示例按其[模块MIT许可](benchmark/family_generation/LICENSE)发布；未重新许可EB、第三方调查、住房/仿真模块或受控家庭输入。公开参考池由本项目公开接口示例构造，来源逐项记录于[家庭模块SOURCES](benchmark/family_generation/SOURCES.json)。个体调查原件、真人答卷及凭据不在该模块发布范围。

独立EnergyPlus24.1湿球数值修复的补丁、头文件、纯C++测试及适用边界见[修复说明](benchmark/project/numerical_repair/v24_1/README.md)，沿用EnergyPlus已有BSD许可及其声明。三份新天气仅记录公开下载来源与哈希，不据此重新许可第三方数据；ISD/ERA5/TMYx的来源与典型年边界单列在[生产修复方法](benchmark/project/PHYSICS_REPAIR_PRODUCTION.md)。

## 八国调查支持的家庭输入（2026-11-08）

本次接入CRECS2012、RECS2020 v7、ENABLE.EU 1.0（英国/西班牙/德国）、IRES2020、ENASIC2022、ECA Consumer Energy Report Card June2025；墨西哥住房另用ENIGH2024统计匹配。调查链接、实际取用范围和原件SHA-256见[来源目录](benchmark/household_stage1/SOURCES.json)。中国原件为项目已有的CRECS2012文件，调查官网链接不代表此特定文件的下载凭据。ENABLE.EU的2019为发布年，不冒称访问年。这里的ECA June2025是源家庭输入，区别于此前六类外部证据中的June2026调查。

本次公开代码契约、方法、文件哈希和无身份聚合证据；不再分发调查原件、源户键、逐户家庭卡、完整仿真或真人答卷。各来源的使用和再分发遵守原条款，不能从“公开可访问”推断统一许可。源插补、跨户匹配和实验增配不冒称同户调查事实。新代码不为第三方数据重新授予许可。

## EB 整户参考适配

`benchmark/idf_reference` 发布本项目可复用构造/安装/编译代码、固定参数定义及公开工程示例。其完整几何与构造算法固定到 OpenStudio-HPXML `004ca3ce1cc378aac3fdecd82d950d37f01e8c3e`，使用官方 OpenStudio 3.11.0、EnergyPlus 25.2.0 和分别锁定的 EB 设备/控制来源。上游代码、引擎、原型及天气不在本次新增目录中重新分发；应按各自原许可取得，版本与来源见[模块资源说明](benchmark/idf_reference/SOURCES.md)和参数包。本次未发布家庭数据、内部验收台账或原生逐时结果，亦未为第三方构造、标准或模型重新授予许可。

## 完整生成配方的依赖与方法

`benchmark/ab_generation/generation-requirements-lock.txt`统一固定家庭到原生A/B的依赖，追加pyreadstat1.3.7（Apache-2.0）与narwhals2.28.0（MIT）；依赖使用各自许可，不在本次代码包中重新分发其二进制。CP-SAT、HiGHS、最大余数配额及IPOG-C式覆盖均保留原有方法归属，具体引用和本项目采用范围见[算法说明](benchmark/ab_generation/ALGORITHM.md)。新配方不发布调查逐户记录、完整原生批次或真人答案。
