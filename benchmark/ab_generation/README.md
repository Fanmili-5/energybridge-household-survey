# A/B策略生成

本模块实现固定日常方案A后的干预候选构造：核验家庭与A的版本，读取当前A的运行参考，在原生活资源内枚举程序移时、人工装取、温控及EV请求，并在最终配对仿真前选择B。输入批次和实验配置决定规模，代码没有固定家庭数量、家庭ID或历史目录。

## 系统边界

当前版本为 `eb.ab_generation.frozen_A.v1`，对应三条主线中的策略生成部分。A仍由既有家庭生活生成器提供；本模块冻结和核验A，不重新推断家庭偏好或重建全年生活。新生成的B是方法实验候选，不替换已发布数据或线上问卷。

| 阶段 | 实现 | 产物 |
|---|---|---|
| A与生活资源冻结 | 原始输入、日历、设备、需求、A命令及当前A运行绑定校验 | 规范化案例、运行参考和来源哈希 |
| 机会识别 | 完整程序链、原人工窗口、实际占用、A设备运行及原EV充电 | 原生设备机会、缺失与不可用原因 |
| 候选构造 | 程序移时×人工策略；温差×时长×方向；原连接内EV延迟 | 单设备候选、静态问题及有限的跨设备联合请求 |
| 事前选择 | 最小命令变化、已知负荷费用、已知负荷VPP贡献三种规则 | 三份方法对照B；不作为三套真人标签集 |
| 物理接口 | 将选定B与原A、需求及VPP绑定，导出住房模块作业 | `physics_job.json`及显式资源目录 |

温控候选的费用与VPP贡献不以名义功率伪装成预测；相应数值保持未知。已知负荷排序只比较程序设备和EV的命令负荷剖面。静态通过不等于完整服务、温度、SOC或VPP达标，最终后果交由配对仿真计算。

## 快速开始

Python 3.9或以上，候选生成仅使用标准库。在仓库根目录运行：

```bash
python -B -m unittest benchmark.ab_generation.test_generation -v
python -B -m benchmark.ab_generation generate \
  --input benchmark/ab_generation/examples/batch.json \
  --rules benchmark/ab_generation/examples/rules.json \
  --out outputs/ab-public-example
python -B -m benchmark.ab_generation verify outputs/ab-public-example
```

输出目录必须不存在。三个公开合成案例分别检查正常构造、A=B控制和缺少当前热状态参考；其温度与负荷参考为接口测试输入，不是实测或EnergyPlus结果。

## 技术文档

- [构造方法](METHOD.md)：输入、依据、算法、人为参数及方法边界。
- [接口规范](INPUTS.md)：对象、单位、依赖、选择状态与输出。
- [复现指南](REPRODUCE.md)：公开示例、受控50户导入及物理交接。
- [验证记录](VALIDATION.md)：软件检查、全批次检查及物理验证的不同范围。
- [来源注册](SOURCES.json)：三篇文献的作用和继承的实现证据。

现有家庭、1000户主数据及生产A/B不因本模块运行而更新。原B和既有指定失败作为独立对照保留；原失败请求不重新挑选成成功请求。所有输出均没有预填人类接受标签。
