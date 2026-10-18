# 复现与版本固定

本包无需先生成某个固定规模的家庭库。先选择所需的执行层，准备该层输入，再按下面顺序运行。每一步写到新目录；原始资料和已完成案例不会被覆盖。

## 环境

Python3.10+。几何层使用SciPy和Shapely：

```bash
python -m pip install -r benchmark/housing_simulation/requirements.txt
```

原生Access提取另需`access_parser_c`及其依赖，来源版本见`requirements-native.txt`：

```bash
python -m pip install -r benchmark/housing_simulation/requirements-native.txt
```

只有执行`run`需要安装EnergyPlus24.1.0-9d7789a3ac；schema与引擎应来自同一官方发布。记录Python版本、依赖版本、操作系统和引擎实际SHA256。可用Python计算文件SHA：

```bash
python -c 'import hashlib,pathlib; print(hashlib.sha256(pathlib.Path("/path/to/energyplus").read_bytes()).hexdigest())'
```

公开示例与测试命令见[README](README.md)。测试材料为人工构造，不需要CHFS、CRECS、既有家庭或答卷。

## 取得来源与建立参考输入

1. 从[DeST作者模型库](https://www.dest.net.cn/dxjzk)取得所需城市、楼型、标准年代原件，记录下载请求及实际字节哈希。现有项目提取入口使用作者`https://svr.dest.net.cn/api/v1/load_model_file`，请求字段为`data.building_type/location/year`；返回资源与服务可用性须在实际运行时核对。
2. 从原始分发源取得EPW，保留下载URL、文件头、站号、坐标、时期和哈希。CSWD的来源记录见[手册](https://bigladdersoftware.com/epx/docs/24-1/auxiliary-programs/references.html)，补充TMYx见[提供方](https://climate.onebuilding.org/sources/default.html)。先完成全年质量检查，再把文件登记为候选。
3. 按[输入契约](INPUTS.md)准备单份原生来源记录，并执行：

```bash
python -B -m benchmark.housing_simulation extract-native \
  --input /path/to/native_entry.json --out /tmp/native-reference
```

该步实际读取源ENVIRONMENT和使用中的构造表，拒绝哈希、城市或气象身份冲突。`assembly.json`可供外壳生成；`reference.json`保留源标量与证据。原生平面没有因此逐户复制。第三方原件、转换资料与天气按各自条件保留，本包不统一授予再分发许可。

## 构造住房

将`examples/shell_batch.json`复制为实验配置，改为自己的来源assembly路径及SHA、层高、尺寸语法、住房条件与明确的`boundary_policy`。当前支持`midfloor_north_south_reference`；不支持的边界应增加新的实现分支和验证，不能仅换标签。

```bash
python -B -m benchmark.housing_simulation build-shell \
  --input /path/to/shell_job.json --out /tmp/reference-shells
python -B -m benchmark.housing_simulation verify /tmp/reference-shells
```

检查所有条目，包括rejected；不删除失败家庭改变分母。此阶段得到外壳，完整家庭还要由上游补齐成员到房间、床位、照护、设备安装和访问权限等证据。设备布置和日程不是本外壳命令自动猜测的字段。

## 成对编译和执行

把完整家庭世界与第二条策略主线的A/B请求导出为[输入契约](INPUTS.md)规定的household/pair包。`physics_job.json`选择任意明确的pairs列表，并冻结schema、设备模板、天气和环境配置。

```bash
python -B -m benchmark.housing_simulation compile \
  --input /path/to/physics_job.json --out /tmp/compiled-pairs
python -B -m benchmark.housing_simulation run \
  --compiled /tmp/compiled-pairs --out /tmp/physical-runs \
  --engine /path/to/energyplus --engine-sha256 YOUR_ENGINE_SHA256
python -B -m benchmark.housing_simulation verify /tmp/physical-runs
```

`compile`只编译，不启动引擎。两臂使用同一组资源；每对由隔离进程加载资源根，避免多任务共享缓存。`run`核字节与引擎版本后逐臂运行；返回非零不丢弃失败记录。每步MANIFEST保留全部输出哈希，实际运行区间、前史和日历映射在INPUT中。原始SQL和警告保留，TRACE只取目标日期及尾期，不将预热混入评价。

当前编译内核只支持既定2024/2025/2026参考日程覆盖。更改源日历、时步、服务协议或设备种类属于新内核版本，不能仅更换配置日期便宣称已支持。

## 不含既有家庭的完整演示

`make-demo`读取自备官方schema和EPW，创建一户完全人工的无居民、无目标设备世界和A=B请求。可按README从输入生成一直跑到SQL回读；它证明工程链可独立执行，不验证有电器家庭或人类偏好。

## 固定和重放

- 冻结源原件/EPW、请求、配置、候选顺序、包版本、依赖和引擎。当前匹配与几何选择是确定规则，不额外抽样；相同输入、代码与环境是复现条件。
- 每次变化形成新输出目录，保留旧成功、失败、日志和警告。改变上游世界或请求后重新编译；跨输入复用必须另行提供完整模型身份与回执证据。
- 同环境可检查IDF字节。跨Python/平台的浮点汇总格式或引擎数值可能不同，应明确容差、比较对象和预先固定规则；不将“几乎相同”伪装成字节一致。
- 本包的`verify`核文件身份；完整研究还需要计量闭合、共同状态、服务恢复和敏感性等领域验收，随后才进入后果展示与人类评价。

旧规模实例的审计记录留在原研究目录，作为应用证据。它们不作为运行本包的依赖，也不被提升为通用方法的全部验证。
