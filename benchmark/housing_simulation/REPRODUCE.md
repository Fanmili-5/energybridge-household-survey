# 构建与复现指南

## 1. 环境固定

参考运行使用Python3.12–3.14、`requirements.txt`中的固定版本依赖，以及EnergyPlus `24.1.0-9d7789a3ac`。原生Access提取使用可选的`requirements-native.txt`；公开端到端实例不需要Access解析器。

```bash
python -m venv .venv-housing
source .venv-housing/bin/activate
python -m pip install -r benchmark/housing_simulation/requirements.txt
python -B -m unittest benchmark.housing_simulation.test_pipeline benchmark.housing_simulation.test_assembly benchmark.housing_simulation.test_review
python -B -m benchmark.housing_simulation.verify_package
```

从[EnergyPlus官方发行页](https://github.com/NatLabRockies/EnergyPlus/releases/tag/v24.1.0)安装对应平台归档，并与发行页`sha256sums.txt`核对。Linux Ubuntu22.04 x86_64归档SHA-256为`5a1d30c3bd1a304741c495a683c7d6ffd8c07d00dd06783e543b50a631c29017`；其他平台使用各自校验和。执行器另外记录并校验实际引擎二进制哈希，校验`--version`输出。

## 2. 公开端到端实例

在仓库根目录执行；`--energyplus-dir`指向包含`energyplus`与`WeatherData/`的解压目录。

```bash
python -B -m benchmark.housing_simulation reproduce \
  --energyplus-dir /path/to/EnergyPlus-24-1-0 \
  --out /tmp/housing-public-001
python -B -m benchmark.housing_simulation verify /tmp/housing-public-001
```

该命令只读取本模块的公开配置、组件资源和引擎发行包，不读取历史家庭目录。默认EPW为发行包内`USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw`，文件SHA-256为`3cc3dc0c7bcc93e7203e8d9aab657d384315f5a0c86cdede23f792d437a0309f`。替换天气须同时提供`--weather`与`--weather-metadata`；元数据结构见[weather_source.template.json](examples/weather_source.template.json)。模板占位值必须替换为实际提供方、数据集、发行版本、URL及文件SHA-256，可选站号也须与实际LOCATION一致。仅替换文件且沿用默认Chicago登记会在构造前拒绝。更换后构成新的气象配置，不能直接对照默认实例数值。

```bash
python -B -m benchmark.housing_simulation reproduce \
  --energyplus-dir /path/to/EnergyPlus-24-1-0 \
  --weather /path/to/registered.epw \
  --weather-metadata /path/to/weather_source.json \
  --out /tmp/housing-custom-weather
```

公开住宅分别为50 m²单人住宅、90 m²三人家庭，以及本户分配60 m²、含一名邻户居民的共享住宅。每个场景含六类可控设备、非空日历、洗衣—干衣依赖、热水需求、EV接插和行程。A/B在2025-07-15按公开请求改变运行时点和控制；前史7天，案例日起评价9天。中间层参考材料及设备数值属于公开工程测试设定，不作为中国住宅总体的实证样本。

成功标准是顶层及`audit/MANIFEST.json`中的`passed=true`。检查包括完整时间轴、设施电表闭合、程序电耗、服务取出、EV能量、热水供给、通知前轨迹及恢复状态。原始SQL与日志均在`runs/`下保留。

## 3. 自定义家庭批次

准备外壳配置和家庭契约；字段分别见`INPUTS.md`第4、5节。复制公开输入并修改家庭、成员、设备及案例列表即可改变规模，无固定1000户或固定案例标识要求。

```bash
python -B -m benchmark.housing_simulation build-shell \
  --input /path/to/shell_batch.json --out /tmp/housing-shells
python -B -m benchmark.housing_simulation assemble \
  --input /path/to/world_batch.json --shells /tmp/housing-shells \
  --weather /path/to/weather.epw --out /tmp/housing-worlds
python -B -m benchmark.housing_simulation compile \
  --input /tmp/housing-worlds/physics_job.json --out /tmp/housing-compiled
```

获取实际平台引擎的SHA-256：

```bash
python -c 'import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' /path/to/EnergyPlus-24-1-0/energyplus
```

将打印值作为下列`--engine-sha256`参数。该值应与本次资源登记一致，不从其他平台复制。

```bash
python -B -m benchmark.housing_simulation run \
  --compiled /tmp/housing-compiled --out /tmp/housing-runs \
  --engine /path/to/EnergyPlus-24-1-0/energyplus \
  --engine-sha256 ACTUAL_BINARY_SHA256
python -B -m benchmark.housing_simulation audit \
  --compiled /tmp/housing-compiled --runs /tmp/housing-runs --out /tmp/housing-audit
```

外壳输出的`_inputs/shell.json`与同目录材料快照可重新提交`build-shell`；世界输出保存`assembly_input.json`，可配合保存的外壳与天气重新提交`assemble`。每次使用新输出目录。保留所有拒绝家庭及失败案例；不得仅以进入编译队列的案例数代替原始分母。上游必须提供所有共享住户的完整名册、日历和资产使用权。

## 4. 中国建筑原型与气象接入

建筑原件从[DeST典型建筑库](https://www.dest.net.cn/dxjzk)取得，依据目录元数据建立同城、建筑类型及年代参照。来源登记与原件提取格式见`INPUTS.md`第2、3节；具体读取表、构造闭包、SHGC近似及气象身份规则见`METHOD.md`第2、3节。

```bash
python -B -m benchmark.housing_simulation match \
  --request /path/to/request.json --catalog /path/to/catalog.json
python -m pip install -r benchmark/housing_simulation/requirements-native.txt
python -B -m benchmark.housing_simulation extract-native \
  --input /path/to/native_reference.json --out /tmp/housing-native
```

将提取的`assembly.json`放入自定义外壳配置的资源根目录，以`{path,sha256}`引用，再依次执行第3节。EPW应固定提供方、站点、版本、经纬度、时区及文件SHA-256；原生提取使用站号、5 km坐标阈值及字节哈希联合核验。CSWD、TMYx等不同资源的来源、生成时期和典型年用途分别登记，不以实际家庭地址或目录名称替代天气身份。

## 5. 官方组件资源重建

包内`resources/heat_pump.json`为官方PTHP示例的Zone1组件及性能曲线子集，`schema_fields.json`为官方schema的IDF字段序列。无需运行引擎即可编译模型。重建命令如下：

```bash
python -B -m benchmark.housing_simulation.export_resources \
  --energyplus-dir /path/to/EnergyPlus-24-1-0 --out /tmp/housing-official-resources
```

命令核验官方IDF和schema源文件哈希，再确定性提取，输出每个文件的SHA-256。与包内同名文件比较应相同；官方许可随资源保留。源哈希与链接见`SOURCES.json`。

## 6. 独立性与复现判定

可仅复制`benchmark/__init__.py`及`benchmark/housing_simulation/`到空目录，再执行第1、2节；持续集成采用该方式运行物理实例。`SOURCE_MAP.json`中的历史路径仅记录代码出处，不参与运行资源解析。`verify_package`另行检查来源标识、代码符号、文档锚点及Schema字段映射的闭合。

相同输入和环境下，外壳、家庭世界、配对请求和IDF应重复生成相同字节。SQL内部记录、引擎日志时间与绝对作业路径不要求字节相同；物理轨迹按`VALIDATION.md`中数值条件比较。不同平台分别登记引擎与依赖版本，不预先声称全部浮点轨迹逐字节相同。
