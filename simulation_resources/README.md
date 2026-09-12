# 地区天气与住宅研究原型

该目录用于真人问卷的 EnergyPlus 环境匹配；作者原始 IDF 和原始气象文件保留不动。

2026-09-12 资源验证：下载 338 个站点，其中 246 个可用；50 个住宅组合、3 个夏季日期共检查 50,700 个组合，36,872 个完成 EP 并通过，13,828 个未通过（包括启动 EP 前的资源预检查拒绝）。34 个省级地区的代表站均覆盖全部 50 个住宅组合（每组合至少一个有效日期）。失败组合保留在报告中。这是历史夏季资源检查，不表示已验证全年所有组合。摘要见 `validation_summary.json`。

- `catalog.json`：资源路径、SHA-256、匹配规则、逐组合通过验证的日期。
- `weather/`：下载的 EPW、配套 DDY 和下载来源。`national_download_report.json` 保留下载检查记录。
- `models/`：50 个等效住宅变体。单居住热区；公寓区分底层、中间层、顶层；另有独立及联排住宅。
- `administrative/`：固定的 2023 年省市区名称快照，用于填写联动，允许手动输入未列出的城市。
- `validation.json`：实际 EP 组合测试的结果，含失败记录。`verified` 仅表示技术运行通过，不表示真实住宅校准通过。

天气匹配按“同城且该住宅组合通过验证 → 省内代表站且通过验证”执行。没有合格资源时保存原答案，暂不运行；不跨省静默匹配，也不声称代表站就是最近站。

住宅尺寸采用面积区间代表值 40、70、105、140、180 平方米。若填的是建筑面积，暂按 80% 转为室内面积，并在页面与记录中说明。材料、HVAC 和热水设备继承原 EB 天津研究参数；建筑年代不据此推断材料，不把原型说成用户真实住宅。公寓/联排相邻侧墙与楼板使用等温边界；这是简化边界假设。

气象 EPW、配套设计日和地温共同接入。当前问卷在填写前从全年 365 个日期均匀分配并冻结，参与者按指定月份填写；每个案例先运行原生 baseline 验证抽中的日期，再开始规划。失败不重抽日期、不丢弃原问卷。2007 是实验日历载体，不代表用户在 2007 年的真实日程或实测天气。

来源：
- 气象文件：<https://climate.onebuilding.org/WMO_Region_2_Asia/CHN_China/index.html>；港澳台配套目录记录于每个 `source.json`。
- 行政名称：<https://github.com/modood/Administrative-divisions-of-China>（截至 2023-06-30；仓库已停止更新，不能当作最新行政代码库）。
- IDF 来源、哈希及工程改造依据：`../models/tianjin_family_eb_v1/manifest.json` 和 `catalog.json`。

维护脚本：`build_regional_resources.py` 构建几何，`expand_national_weather.py` 下载大陆资源，`add_regional_representatives.py` 配置代表站，`verify_regional_resources.py` 运行组合验证。构建/导入会产生候选状态，须完成验证才能用于问卷。保存版本时应完整保留旧目录，避免已提交案例的资源哈希失效。

公开检出后先运行 `python scripts/bootstrap_resources.py`，恢复天气、生成 IDF 并解压验证记录；校验失败即停止。`validation.json.xz` 是不含真人信息的工程测试记录。历史版本通过各自目录哈希和资源哈希恢复。
