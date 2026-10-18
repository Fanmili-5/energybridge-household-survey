# 构建与复现指南

## 1. 环境准备

所有命令在仓库根目录执行。Python 版本要求为 3.10 或更高版本。

```bash
python -m pip install -r benchmark/housing_simulation/requirements.txt
```

原生 Access 提取依赖单独安装：

```bash
python -m pip install -r benchmark/housing_simulation/requirements-native.txt
```

`requirements-native.txt`固定 Access 解析器提交和辅助依赖。几何依赖按声明的版本范围安装，实际安装版本应随实验环境记录。数值执行要求 EnergyPlus `24.1.0-9d7789a3ac`，schema 与二进制应来自同一官方发布。

实验环境记录至少包括 Python 版本、依赖版本、操作系统、CPU 架构、引擎版本和二进制哈希。

## 2. 资源准备

### 2.1 建筑原件

原生建筑模型从 [DeST 作者模型库](https://www.dest.net.cn/dxjzk)取得，登记建筑类型、城市、目录年代、下载来源和原件 SHA-256。现有获取接口为 `https://svr.dest.net.cn/api/v1/load_model_file`，请求包含 `data.building_type`、`location` 和 `year`；执行时须记录实际响应及资源身份。

### 2.2 气象文件

EPW 登记项包括下载 URL、数据集类型、时期、LOCATION、站号、坐标、时区和内容哈希。CSWD 来源见 [EnergyPlus 手册](https://bigladdersoftware.com/epx/docs/24-1/auxiliary-programs/references.html)，TMYx 方法见[提供方说明](https://climate.onebuilding.org/sources/default.html)。

资源登记阶段完成全年时间序列、缺值和气象量质量检查。原生提取阶段另执行站号、坐标和字节核验。原件和 EPW 按各自使用条件准备，公共源码包不包含这些文件。

### 2.3 哈希生成

```bash
python -c 'import hashlib,pathlib; print(hashlib.sha256(pathlib.Path("/path/to/resource").read_bytes()).hexdigest())'
```

资源哈希写入对应配置。压缩资源按压缩后的实际字节登记。

## 3. 原型匹配与参数提取

按[接口规范](INPUTS.md)准备匹配请求及已准入候选目录：

```bash
python -B -m benchmark.housing_simulation match \
  --request /path/to/match_request.json \
  --catalog /path/to/reference_catalog.json \
  > outputs/reference-selection.json
```

上述标准输出重定向要求 `outputs` 目录已存在。原型选择记录和候选目录应纳入实验输入版本。

对选定原件执行参数提取：

```bash
python -B -m benchmark.housing_simulation extract-native \
  --input /path/to/native_entry.json \
  --out outputs/native-reference
```

输出 `reference.json`、`assembly.json` 及阶段清单。原件、环境或气象身份不满足条件时，执行返回非零状态。

## 4. 参考外壳构建

外壳作业指定构造参数文件及哈希、住宅条件、候选尺寸语法、层高和边界策略。配置结构见 [shell_batch.json](examples/shell_batch.json)。

```bash
python -B -m benchmark.housing_simulation build-shell \
  --input /path/to/shell_job.json \
  --out outputs/reference-shells
python -B -m benchmark.housing_simulation verify outputs/reference-shells
```

验收时检查整个输入列表，包括 `rejected` 条目。外壳产物的验收对象为几何、面积和围护结构；完整家庭世界的成员、床位、照护、设备安装、供电和控制权限须经集成阶段绑定。

## 5. 配对模型编译与执行

### 5.1 输入装配

按[家庭世界集成接口](INPUTS.md)准备家庭包和 A/B 请求，生成 `physics_job.json`。作业应固定以下输入：家庭包、配对请求、EPW、官方 schema 字段表、源设备对象和热环境配置。

当前独立包不提供一般家庭画像到完整物理家庭包的自动装配器。带设备运行依赖已完成集成的上游包；公共工程示例提供最小结构参考。

### 5.2 编译

```bash
python -B -m benchmark.housing_simulation compile \
  --input /path/to/physics_job.json \
  --out outputs/compiled-pairs
```

编译阶段不启动 EnergyPlus。每对使用独立编译进程，资源根目录与配置显式传入。各臂的 `INPUT.json.gz` 保存实际前史、运行区间、请求终点、执行计划和计量映射。

### 5.3 执行与回读

```bash
python -B -m benchmark.housing_simulation run \
  --compiled outputs/compiled-pairs \
  --out outputs/physical-runs \
  --engine /path/to/energyplus \
  --engine-sha256 ENGINE_BINARY_SHA256
python -B -m benchmark.housing_simulation verify outputs/physical-runs
```

执行器保存两臂状态、原始 SQL、引擎日志和时间序列。轨迹回读排除预热期；评价区间及电量范围在回执中明确登记。失败条目保留在批次记录中。

## 6. 公共集成测试实例

公共实例以合成材料、参考几何和无居民、无目标可控设备、A=B 的运行条件构建，不依赖研究家庭库。schema 与 EPW 由运行环境提供。

```bash
python -B -m benchmark.housing_simulation make-demo \
  --schema /path/to/Energy+.schema.epJSON \
  --weather /path/to/reference.epw \
  --out outputs/demo-inputs
python -B -m benchmark.housing_simulation compile \
  --input outputs/demo-inputs/physics_job.json \
  --out outputs/demo-models
python -B -m benchmark.housing_simulation run \
  --compiled outputs/demo-models \
  --out outputs/demo-runs \
  --engine /path/to/energyplus \
  --engine-sha256 ENGINE_BINARY_SHA256
```

该实例覆盖输入构建、成对编译、引擎执行和 SQL 回读。其验证结论限定为工程集成，不扩展到目标设备性能或家庭服务有效性。

## 7. 版本固定与复现判定

一个可复现运行应保存代码版本、依赖环境、资源原件哈希、候选目录和次序、全部配置、实际模型、引擎哈希、日志及执行回执。匹配和几何使用确定性选择规则；当前实现不额外抽取家庭或随机变更住房条件。

输入修订创建新输出目录。家庭、外壳、设备、占用、请求、天气、引擎或运行配置变更后，受影响模型需要重新编译和执行。历史产物只在完整身份和回执匹配时具备复用依据。

同环境编译可按 IDF 字节判定一致性。跨环境比较应固定数值对象、容差和统计规则，分别报告文本差异与物理输出差异。领域验收项目及当前验证覆盖见[验证规范](VALIDATION.md)。
