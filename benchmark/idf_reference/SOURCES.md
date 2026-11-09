# 公共资源与环境

源码、固定参数和公开工程示例在本目录中。引擎、天气和第三方原型按来源锁定后放在运行工作区；第三方公开可下载不等于本项目可以重新许可或随意再分发。

## 固定来源

| 资源 | 固定版本或入口 | 使用方式 |
| --- | --- | --- |
| OpenStudio-HPXML | [004ca3ce1cc378aac3fdecd82d950d37f01e8c3e](https://github.com/NatLabRockies/OpenStudio-HPXML/tree/004ca3ce1cc378aac3fdecd82d950d37f01e8c3e) | 完整公开构造器、材料算法和命名选项；保留上游许可 |
| OpenStudio SDK | [3.11.0](https://github.com/NatLabRockies/OpenStudio/releases/tag/v3.11.0) | 精确构建号 `3.11.0+241b8abb4d` |
| 官方 EnergyPlus | [25.2.0](https://github.com/NatLabRockies/EnergyPlus/releases/tag/v25.2.0) | 精确构建号 `25.2.0-cf7368216c`；不混用旧模块引擎 |
| EB 主方法 | [2b17ae63e613da776c93e900f5dace50d63a88a8](https://github.com/Fanmili-5/EnergyBridge/tree/2b17ae63e613da776c93e900f5dace50d63a88a8) | 原主方法控制语义；设备来源分别由组件和安装定义锁定 |
| 典型年天气 | [OneBuilding TMYx](https://climate.onebuilding.org/) | 使用地点包指定的站点和 2009—2023 文件，不自行换站或换年份 |
| 英国设计依据 | [England ADL2021，含2023修订](https://assets.publishing.service.gov.uk/media/662a2e3e55e1582b6ca7e592/Approved_Document_L__Conservation_of_fuel_and_power__Volume_1_Dwellings__2021_edition_incorporating_2023_amendments.pdf) | 表4.1；England 范围 |
| 西班牙设计依据 | [CTE DB HE](https://www.codigotecnico.org/pdf/Documentos/HE/DBHE.pdf) | 使用参数包锁定的2022文本哈希及表3.1.1.a；当前网址文本若更新不能自动替换 |
| 德国设计依据 | [GEG Anlage 7](https://www.gesetze-im-internet.de/geg/anlage_7.html) | 版本以参数包中的文件哈希为准 |
| 墨西哥设计依据 | [NOM-020-ENER-2011](https://www.gob.mx/cms/uploads/attachment/file/181660/NOM_020_ENER_2011.pdf) | 表1 Mexico D.F.参考行 |
| 印度设计依据 | [政府 ENS 入口](https://hareda.gov.in/ens/) | 使用参数包锁定的 ENS2018 原文 |
| 澳大利亚参考依据 | [政府托管住宅节能指南](https://www.sutherlandshire.nsw.gov.au/__data/assets/pdf_file/0034/97990/Sutherland-Council-Mar-2025-Your-Sustainable-Home-Tips-and-Tricks-to-save-Energy-Use.pdf) | 原 PDF 未完整下载；摘录及限制写入参数包 |

中国 A1 的完整材料层与来源链保存在 `parameters/constructions/CN_A1.json`，地区包只选择这一套完整构造，不拼接其他原型的几何或设备。来源的模型、原档与公开元数据仍需按包内哈希准备；公开参考住宅不解释为调查住房。

## 一次性准备与运行路径

1. 使用 CPython 3.13.13 安装 `requirements.txt`。版本固定保留天气派生参数的严格浮点复算条件。
2. 将固定 HPXML checkout 放入 `work/p1_hpxml_004ca3ce/`。SDK、官方引擎的主机布局由 `configs/native_build_platforms_v3.json` 指定；不能只把任意 `energyplus` 加入 PATH。
3. 按地点包取得对应 EPW、设计工况和派生进水输入。核对文件哈希、站点、实际引擎地点和当地标准时间。不同天气版本形成新包。
4. 准备来源指定的完整 EB 设备与水路资源。现有生成步骤位于 `scripts/build_supply_source.py`、`build_six_joint_source.py`、`run_hpxml_component_reference.py`、`run_six_joint.py` 和相关翻译/验证模块。这些脚本沿用原运行工作区的来源引用；本次源码分发不包含其历史输出，也没有把它们改写成无依赖的一键安装器。
5. 执行 `python -m scripts.public_parameters materialize` 安装本仓库的固定物理输入，再用 `check` 查看尚缺的来源文件。缺失保持报错，不用占位文件或伪造哈希补齐。
6. 在准备完成的工作区使用 `scripts.run_shared_housing`；请求中的水路和控制策略显式声明，新的运行生成自己的数值与性能域检查。历史审批文件不随代码分发，也不能用一个布尔标记代替新请求验证。

本次公开包是现有实现的源码和参数分发，**不是已包含全部外部运行资源的冷启动镜像**。`check` 仅枚举选定目录的输入引用；完整运行还会逐层核验设备、日程资源、官方引擎和来源依赖。资源缺失时不能把仓库检出成功或软件测试通过称为原生仿真成功。

`SOURCE_LOCK.json` 记录发布源码和上游版本；`parameters/LAYOUT.json` 记录固定参数的原输入键与发布位置。它们是版本和输入定义，不是内部验收台账。第三方数据与代码继续遵守各自许可；本模块没有授予它们新的许可。
