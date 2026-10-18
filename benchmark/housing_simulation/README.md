# 住宅模型生成与配对能源仿真

## 概述

`housing_simulation` 是家庭能源偏好 benchmark 的物理环境构造模块。模块根据住宅面积、房间数、共享条件、建筑参数参照和设备控制请求，生成参考住宅外壳及 A/B 配对 EnergyPlus 模型，并保存仿真轨迹、执行日志和文件校验清单。

模块采用配置驱动的批处理接口，住宅数量和方案数量分别由 `households`、`pairs` 输入列表确定。家庭人口抽样、态度类别及 A/B 策略生成由上游模块负责；本模块负责建筑参数处理、参考几何生成、物理模型编译与数值执行。

## 系统组成

| 组件 | 职责 | 主要产物 |
| --- | --- | --- |
| 原型匹配 | 根据地区、建筑类型和目录年代选择参数参照，记录年代差异 | 原型标识、候选数量、参照情景 |
| 原生参数提取 | 读取 DeST 实际使用的构造、材料和窗参数，核验气象站身份 | `reference.json`、`assembly.json` |
| 参考外壳生成 | 在给定面积和房间条件下生成参考平面与多热区外壳 | `layout.json`、`shell.idf`、几何元数据 |
| A/B 模型编译 | 将完整家庭世界、日程及控制请求编译为配对物理模型 | 两臂 `model.idf`、`INPUT.json.gz` |
| 仿真执行与回读 | 使用固定引擎运行模型，读取电表和热环境轨迹 | 原始 SQL、`TRACE.json.gz`、执行回执 |
| 产物核验 | 校验已登记产物的内容哈希 | 文件一致性检查结果 |

外壳生成与家庭物理编译采用独立接口。前者输出几何和围护结构；后者接收已完成成员、设备安装、操作权限及服务需求绑定的家庭世界。两者之间的家庭世界装配属于集成接口，当前版本未提供自动装配命令。

## 安装

运行环境为 Python 3.10 或更高版本。几何计算依赖 SciPy 和 Shapely；原生 Access 提取使用可选解析器；仿真执行要求 EnergyPlus `24.1.0-9d7789a3ac`。

```bash
python -m pip install -r benchmark/housing_simulation/requirements.txt
```

原生提取依赖及引擎配置见[复现指南](REPRODUCE.md)。

## 快速开始

在仓库根目录执行参考外壳示例：

```bash
python -B -m benchmark.housing_simulation build-shell \
  --input benchmark/housing_simulation/examples/shell_batch.json \
  --out outputs/housing-example
python -B -m benchmark.housing_simulation verify outputs/housing-example
```

示例包含三个合成住宅条件，覆盖开间、独立家庭住宅和共享住宅。材料与尺寸为接口测试参数。输出保留每个输入条目的成功状态或拒绝原因；输出目录须为新目录。

完整工程示例使用自行准备的官方 schema 和 EPW：

```bash
python -B -m benchmark.housing_simulation make-demo \
  --schema /path/to/Energy+.schema.epJSON \
  --weather /path/to/reference.epw \
  --out outputs/physics-demo-inputs
python -B -m benchmark.housing_simulation compile \
  --input outputs/physics-demo-inputs/physics_job.json \
  --out outputs/physics-demo-models
python -B -m benchmark.housing_simulation run \
  --compiled outputs/physics-demo-models \
  --out outputs/physics-demo-runs \
  --engine /path/to/energyplus \
  --engine-sha256 ENGINE_BINARY_SHA256
```

该示例采用无居民、无目标可控设备、A=B 的集成测试条件，用于验证输入生成、模型编译、引擎执行及 SQL 回读。带设备家庭的输入结构见[接口规范](INPUTS.md)。

## 技术文档

- [构造方法](METHOD.md)：原型选择、参数转换、面积约束、物理编译及建模假设。
- [接口规范](INPUTS.md)：字段定义、单位、路径规则、输入依赖及输出状态。
- [复现指南](REPRODUCE.md)：资源准备、执行顺序、版本固定及产物核验。
- [验证规范](VALIDATION.md)：检查范围、判定条件及已完成的验证记录。
- [来源注册表](SOURCES.json)与[源码映射](SOURCE_MAP.json)：外部依据、使用范围及算法来源。

## 适用范围

当前外壳生成器支持单层矩形参考公寓，采用中间层、南北暴露的边界条件。物理编译器支持既定参考日历及设备协议。建筑参数来源、研究者设定、数值仿真结果分别记录；模型的实测校准和最终 benchmark 的领域验收按[验证规范](VALIDATION.md)执行。
