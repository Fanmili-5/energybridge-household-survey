# 第三方来源

- EnergyBridge：<https://github.com/Agentic-Intelligence-Lab/EnergyBridge>，固定提交记录在 `UPSTREAM_TRACKED_FILES.json`。本仓库的构建脚本验证该提交的文件哈希，不修改作者检出目录。使用其代码及派生 IDF 时须核对作者的授权；本仓库不替上游授予许可。
- EnergyPlus 24.1：安装脚本从官方发布下载；遵循其自身许可。
- 气象：<https://climate.onebuilding.org/>，每个站点的完整下载链接和文件校验值保存在 `simulation_resources/catalog.json`。首次运行按来源下载，不在 Git 中再次分发 EPW/DDY 原文件；须遵循相应源数据的使用条件。
- 行政名称：<https://github.com/modood/Administrative-divisions-of-China>，2023-06-30 快照。来源项目使用 WTFPL v2；许可全文见 `simulation_resources/administrative/LICENSE`。这里只用于省市输入联动，不是现行行政区划权威证明。
- Playwright、Python 第三方依赖等分别遵循其自身许可。

本仓库没有为所有来源统一声明一个开源许可证。
