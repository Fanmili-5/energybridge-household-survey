# EnergyBridge

让模型站在具体家庭的立场，比较日常方案A与VPP调整方案B，判断是否接受、如何评分，以及为什么。

**[问卷入口](https://47.85.194.154/household50-current/) · [项目文档](docs/README.md) · [复现指南](docs/REPRODUCE.md)**

家庭与设备 → 住房和生活安排 → 日常A → 不同取舍的B → 配对仿真后果 → UI91问卷 → 人类评价。

**[最新完整构造方法](docs/METHOD.md) · [阶段状态](docs/BENCHMARK_STATUS.json) · [ACL视角复核](docs/ACL_BENCHMARK_REVIEW_20261112.md)**

八国1000户输入不变；新版1000户×10题已生成并完成20000次原版电器执行回放。美国、印度各一组新A/B通过配对物理验收，一个UI91隔离预览通过桌面/手机检查；全量物理后果与正式发放仍未完成。旧10000题保留；原4335一概判废结论已按论文版重审更正，不能据此整批删掉负面取舍题。代码更新不改变既有线上50户题集。

## 三条主线

| 主线 | 内容 | 代码与详细方法 |
|---|---|---|
| 家庭与设备 | 调查约束的家庭、EB角色态度、参考周、4—6类控制与服务合同 | [可复用生成器](benchmark/household_stage1/generator/)；[早期合成画像](benchmark/family_generation/) |
| A/B策略 | 从生活需求生成A，围绕固定VPP生成单设备/联合B，覆盖取舍并保留长尾 | [ab_generation](benchmark/ab_generation/) |
| 住房与仿真 | 按共享住房类别选择完整地区包，沿 EB 和统一编译器执行整户请求 | [当前整户适配](benchmark/idf_reference/)；[原24.1构造示例](benchmark/housing_simulation/) |

完整方法、来源、规则参数与验收结果见[方法说明](docs/METHOD.md)。[project](benchmark/project/)负责资料连接与UI91适配，[collector](benchmark/collector/)负责版本绑定、分户、回答与恢复。

## 当前版本

公开发布指针目前登记为reference50-v4-ui91-trial：既有50户的UI91界面试用版，包含合成展示值，不是八国V9正式采集版本。试用展示和回答不能作为真实仿真后果下的正式标签。八国1000户家庭输入已完成；新版A/B、IDF结果与真人问卷的完整交付仍待验收。公开版本与线上实际部署分别核验，本次不切换题集。见[数据与验收](docs/DATASET.md)。

公开仓库包含代码、合成示例、方法和聚合证据；受控原件与真人答卷按许可管理。详见[来源与许可](THIRD_PARTY.md)。

## 可复用住房与地区适配

[整户适配模块](benchmark/idf_reference/README.md)公开现有 EB 链路的住房构造、来源适配、设备安装和统一运行入口，以及八国完整参考围护包、九个示例地点包和公开工程输入。新家庭复用“模板算法＋参数包＋地点包”，生活需求和控制独立接入；支持范围、缺项处理和扩展规则见[构造方法](benchmark/idf_reference/METHOD.md)。

该模块使用固定官方 EnergyPlus 25.2 与 OpenStudio-HPXML；原24.1模块保留。源码分发不含原生引擎、天气、外部原型资源、内部验收记录或家庭日程；需按[资源说明](benchmark/idf_reference/SOURCES.md)准备共享环境。公开类别和软件测试不代表所有家庭或工况均已通过物理及数值检查。本轮另行修正A/B和热水器窗口编译，记录见[本轮报告](docs/research/AB_GENERATION_REPAIR_20261114.md)。

## 八国家庭生成第一步（V9）

[可复用生成算法与规则](benchmark/household_stage1/generator/README.md) · [数据来源与实际方法](benchmark/household_stage1/README.md) · [冻结批次摘要](benchmark/household_stage1/CURRENT.json) · [验收证据](benchmark/household_stage1/VALIDATION.json)

中国、美国、英国、西班牙、印度、墨西哥、澳大利亚、德国各125户。家庭背景由真实调查提供，角色态度沿用EB定义，六类配额按EB人类角色扮演调查样本比例分配；结合活动与服务规则生成生活安排，以整数规划分配电器组合。**空调每户必备且必控**，每户共4—6类。生成代码、逐步依据、规则参数、验收证据及扩量入口均已打包，家庭生成第一步通过，可用于后续benchmark构造。正式V9与既有50户线上资料分别管理。

## 原EB规则溯源更正（2026-11-13）

[论文冻结版重审](docs/research/original_eb_reaudit_20261113/REPORT.md)：此前统一检查器是项目新增包装，引用了八月V2/V3代码。按官方paper-v1-final重审，旧4335中130条可原样保留、4205条需要执行映射核对；旧通过部分另有169条时钟问题。原题全部保留，偏好冲突、舒适差或居民可能拒绝不作为剔除条件。

## A/B与IDF当前进展

A依据家庭生活参考联合排程；B沿论文冻结版的六类动作生成候选，以整数规划及同类覆盖重选选定每户十题。见[可复用入口](benchmark/ab_generation/README.md)和[本轮实际结果](docs/research/AB_GENERATION_REPAIR_20261114.md)。旧v2.10/v2.11的装取变化和影子重选作为[历史研究方法](benchmark/research_delivery/METHOD.md)保留，不作为新版原生动作规则。

IDF公开共享构造实现继续保留自己的源码锁；服务器35城、题窗及换城试验的[最新聚合状态](benchmark/idf_reference/VALIDATION_STATUS_20261112.json)单独登记，尚未证明新版A/B的全量物理后果。方法与完成状态统一从[完整构造说明](docs/METHOD.md)阅读。
