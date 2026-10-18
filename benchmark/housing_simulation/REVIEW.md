# 住房与仿真生成主线审查记录

审查日期：2026-10-19。发布版本：3.0.0。审查范围覆盖来源、输入、外壳、家庭装配、负荷、设备、气流、配对仿真及独立复现。

## 1. 本次方法修订

| 缺口 | 落实的替代或补充 | 可核对位置 |
| --- | --- | --- |
| 人体采用统一功率、杂项无人比例和隐式烹饪缺乏充分参数依据 | 官方成人活动表与辐射默认；显式体量比例、待机及烹饪；中国住宅论文照明参考 | `loads.py`、`kernel/compiler.py`、`ASSUMPTIONS.json` |
| 几何适用域不清、顺序安装可导致假阴性 | 广州八型来源约束与口径映射；清空包络联合MILP、合法床位分配枚举，区分不可行与未完成 | `geometry_reference.py`、`geometry_references.json`、`installation.py` |
| 规定流量不能表示风压/浮力不确定性 | 原生AFN结构替代、全部方向流量与逐区质量闭合 | `kernel/pressure_network.py`、`robustness.airflow_balance` |
| 参数/结构及数值配置缺少统一检验 | 先登记Morris与六案例前史、尾期、步长比较，保留全部失败和符号变化 | `STUDY_PLAN.json`、`robustness.py`、`ROBUSTNESS_RESULTS.json` |
| 文献支持与项目设计易混淆 | 来源阅读层级、支持/不支持命题、规则、字段、代码符号和设计理由逐项对应 | `SOURCES.json`、`RULES.json`、`FIELD_MAP.json`、`DESIGN_DECISIONS.md` |

## 2. 验证证据

50项公开测试覆盖原有41项构造/执行边界，以及活动散热、烹饪并集、贪心失败的旋转正例、包络负例、求解未完成、来源域、Morris设计、效应漂移负例及质量闭合负例。真实引擎证据由`VALIDATION.json`、`REFERENCE_RESULTS.json`与`ROBUSTNESS_RESULTS.json`登记；原始SQL及日志随运行目录和CI artifact保留。开发期间发现新增烹饪时段与B洗衣装载冲突，已修订公开场景日历；未放宽执行门槛或根据节能方向调整参数。

## 3. 适用结论

独立生成流程由显式输入列表决定规模，不读取原1000户；完整家庭世界仍要求上游提供成员、设备、日历、共享住户和服务。来源有界参考和数值验证不建立全国代表性或住宅实测有效性。新增输入域、气象及设备须重新验证；未覆盖的材料参数、儿童特定体量和人口联合分布不因本次通过而得到校准。各项保留设定的理由与边界见`DESIGN_DECISIONS.md`。
