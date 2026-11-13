# EB 整户参考住宅适配

最新全链路说明见[项目方法](../../docs/METHOD.md)，服务器35城试验、24小时题窗与换城候选见[聚合状态](VALIDATION_STATUS_20261112.json)。本目录保留公开源码快照及来源锁；聚合状态不意味着内部扩展已全部移植，也不授予新版A/B物理准入。

本模块把住房条件解析为共享住宅类别，选择完整地区构造与地点包，再交给已有 EB 设备安装器和统一编译器。面积、层数和邻接沿固定公开算法生成；新增家庭复用规则和物理包，不逐户编辑 IDF。

这里公开当前实现、固定物理输入和工程示例。家庭生成、A/B 生成与真人偏好评价由各自模块负责。

## 输入与输出

输入分开保存：

- **住房条件**：国家、注册地点、参考空调面积及其口径、住宅类型、户内层数、共墙和上下暴露。
- **设备配置**：物理存在、是否可控、资产标识、背景服务及共用资产关系。
- **CASE**：独立的生活服务需求和控制指令，支持固定日程 v2 与逐日期 v3。

输出包括类别与参数选择、来源绑定的物理配置 ID、改造清单、IDF、整户及设备计量、室温和可计算的服务后果。生成成功、软件测试通过和原生物理/数值检查通过分别处理。

原调查事实与实验参考条件始终分开；参考面积不回写成调查面积。只有明确选用参考策略时，粗住房标签才能解析为参考情境。缺项和冲突返回缺口，运行请求不能覆盖材料或设备曲线。

## 目录与实现

| 目录或入口 | 用途 |
| --- | --- |
| `national_idf/reference_context.py` | 粗住房标签到显式参考条件的解析 |
| `national_idf/condition_housing.py` | 按面积、层数和邻接调用固定公开住宅构造器 |
| `national_idf/enclosure_class.py`、`regional_profile.py` | 类别、地区包及完整公开构造选项的选择 |
| `national_idf/reference_enclosure.py` | 按表面角色安装构造，保留几何与边界 |
| `national_idf/condition_packages.py` | 地点、围护、供水、设备与旧负荷处理的组合 |
| `national_idf/dated_case.py`、`case_commands.py` | 逐日期需求、EB 控制和连续 EV 能量账 |
| `scripts/run_shared_housing.py` | 统一入口，委托原 `reference_pipeline` 执行 |
| `parameters/` | 八国围护包、九个地点包、中国 A1 完整层构造 |
| `configs/` | 固定规则、CASE Schema、原 EB 水箱和数值协议 |
| `examples/` | 公开工程指令及不同住房输入，无家庭数据 |
| `tests/` | 参数安装和逐日期控制的软件回归 |

## 查看参数与运行软件检查

在仓库根目录进入本模块，避免与仓库其他同名 `scripts`、`tests` 包混用：

```bash
cd benchmark/idf_reference
python -m pip install -r requirements.txt
python -B -m scripts.public_parameters catalog
python -B -m unittest discover -s tests -v
```

原生链路固定 CPython **3.13.13**、OpenStudio **3.11.0+241b8abb4d** 和官方 EnergyPlus **25.2.0-cf7368216c**。旧 `benchmark/housing_simulation` 的 EnergyPlus 24.1 示例保持原样；本模块不能直接复用它的引擎、缓存或通过标记。

## 配置公共资源并运行

源码与参数分发不包含引擎二进制、第三方原型/天气原件、生成的设备资源或历史运行记录。完整原生运行需要先准备这些来源锁定的共享资源；它们按工作区准备一次，随后供多个住房和家庭复用。来源和准备顺序见 [资源说明](SOURCES.md)。

参数文件在 Git 中按用途整理。下面的命令只将 18 个固定输入放回当前编译器使用的原相对路径，不改值、不复制验收记录，也不覆盖内容不同的已有文件：

```bash
python -B -m scripts.public_parameters materialize
python -B -m scripts.public_parameters check
```

`check` 列出缺失或哈希不符的外部输入，存在缺项时返回退出码 2。它检查选定输入引用，不授予原生运行或物理准入。仅运行 `materialize` 不能替代原型、天气和设备资源的准备。

在已配置上述公共资源与官方引擎的工作区，沿用同一入口：

```bash
python -B -m scripts.run_shared_housing \
  --request examples/CN_apartment_request.json \
  --out outputs/cn-apartment \
  --housing-cache work/housing-cache \
  --package-cache work/package-cache \
  --result-cache work/result-cache
```

输出目录必须未存在且位于本模块工作区内。西班牙示例使用 `examples/ES_detached_request.json`；其他面积、楼层和地点的输入见 `examples/housing_conditions.json`。示例是公开工程指令，不是现有家庭的日程，也不因被收录就视为数值通过。

新运行保留原计量、性能域、1/2/5 分钟、14/28 天预热及 7/14 天恢复检查。原 EB 120 L、3 kW 单节点水箱保持不变。代码、参数、天气或 CASE 改变后不能套用旧结果的准入。

## 参考范围与扩展

当前类别为八国各三类参考住宅：公寓、联排/连体和独立住宅；地点为广州、上海、丹佛、伦敦、马德里、柏林、墨西哥城、孟买及悉尼。这是受控参考设计目录，不代表八国全部气候、住宅存量或任意家庭已通过验证。

公寓支持一层户内空间及已声明的共墙、底层/中间层/平屋顶顶层；联排和独立住宅的生成规则可表达 1—4 层。可表达的组合与实际通过数值检查的组合分开，不能将连续面积或层数域整体视为已验证。

新家庭复用固定包，只提供独立需求和控制。新住房条件使用同一生成算法；新地点增加共享地点包；新气候、构造或边界类别才扩展共享规则与依据。地区包保留完整热阻和蓄热信息，不从单个 U 值反推未知墙体，不外推未知设备性能。

详细构造与扩展规则见 [METHOD.md](METHOD.md)。内部验收台账、原生日志、SQL、逐时轨迹和家庭资料不在本模块中发布。

## 原EB热水器窗口交接（2026-11-14）

可选controls字段water_heater_windows_by_date与water_heater_window_encoding现在保留原EB的一段加热许可窗口；窗外编译为已有绑定支持的内部关闭值，目标温度与用水需求本身不改。它不是新增Agent停止/温度动作。指定空数组可明确关闭尾段日期，避免缺省继承。新公开路径有软件回归；两组完整配对物理试例来自另外锁定的服务器候选环境，见[本轮记录](../../docs/research/AB_GENERATION_REPAIR_20261114.md)，不冒称全部公开地点和10000题均已验收。
