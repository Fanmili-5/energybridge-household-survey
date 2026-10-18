# 住房与仿真生成

这条主线说明如何把明确的家庭住房条件和A/B请求，转换为有来源记录的参考住房、EnergyPlus模型与物理轨迹。**批量大小由输入列表决定**，可以只有一户或一对方案；50户、1000户是应用实例，不是方法的前提。

流程为：家庭住房条件 → 原型匹配与参数提取 → 参考几何与住房外壳 → 绑定成员、设备和日程 → A/B成对编译 → 同引擎运行与轨迹回读。

| 要回答的问题 | 文档或代码 |
| --- | --- |
| 输入是什么、输出什么 | [输入契约](INPUTS.md) |
| 依据是什么、哪些属于我们的设定 | [方法与依据](METHOD.md)、[来源表](SOURCES.json) |
| 匹配、面积、边界、设备、前史按什么规则处理 | [方法步骤](METHOD.md)、[执行代码](pipeline.py) |
| 怎样复现 | 本页命令、[完整复现说明](REPRODUCE.md) |
| 哪些算法来自已有实现，怎样调整了接口 | [SOURCE_MAP.json](SOURCE_MAP.json) |
| 代码怎样验证 | [公开测试](test_pipeline.py)、[验证记录](VALIDATION.json) |

## 不依赖调查或既有家庭的示例

从仓库根目录运行，Python3.10及以上：

```bash
python -m pip install -r benchmark/housing_simulation/requirements.txt
python -B -m benchmark.housing_simulation match \
  --request benchmark/housing_simulation/examples/match_request.json \
  --catalog benchmark/housing_simulation/examples/synthetic_catalog.json
python -B -m benchmark.housing_simulation build-shell \
  --input benchmark/housing_simulation/examples/shell_batch.json \
  --out /tmp/housing-example-shells
python -B -m benchmark.housing_simulation verify /tmp/housing-example-shells
python -B -m unittest benchmark.housing_simulation.test_pipeline
```

示例包含3个虚构住房条件与人工材料，只演示接口、面积守恒、共享和拒绝记录，不代表中国住宅原型。输出目录须尚不存在。改输入列表即可更改规模；不可入住或不支持的条件保留在拒绝记录中。

## 用自备天气与官方引擎运行完整示例

准备EnergyPlus24.1.0-9d7789a3ac、其原始`Energy+.schema.epJSON`与一份有来源记录的EPW，然后运行：

```bash
python -B -m benchmark.housing_simulation make-demo \
  --schema /path/to/Energy+.schema.epJSON --weather /path/to/reference.epw \
  --out /tmp/housing-demo-inputs
python -B -m benchmark.housing_simulation compile \
  --input /tmp/housing-demo-inputs/physics_job.json --out /tmp/housing-demo-models
python -B -m benchmark.housing_simulation run \
  --compiled /tmp/housing-demo-models --out /tmp/housing-demo-runs \
  --engine /path/to/energyplus --engine-sha256 YOUR_ENGINE_SHA256
python -B -m benchmark.housing_simulation verify /tmp/housing-demo-runs
```

这是无居民、无目标电器、A=B的公开工程夹具；完整轨迹与原始SQL用于验证管线。实际家庭任务需要按输入契约提供成员占用、安装设备、服务任务及A/B控制，不能把空壳示例称为完整家庭benchmark。

`extract-native`可从一份绑定哈希的DeST原生Access提取实际使用的围护参数，见[复现说明](REPRODUCE.md)。原件、EPW、设备模板和答卷按各自许可自行准备，未嵌入本包。打包后的编译器保留既有设备执行和热环境算法，不再导入历史批次目录。

当前接口支持参考公寓的单层矩形走道/开间几何，以及既有参考日历和设备协议。完整家庭的床位、照护、设备空间与操作权限由上游家庭世界提供并核验。工程完成、服务完成、实测校准和人类接受分别报告。
