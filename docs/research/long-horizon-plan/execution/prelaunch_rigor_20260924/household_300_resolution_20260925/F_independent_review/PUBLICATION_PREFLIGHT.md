# F GitHub 发布与许可预检（未提交、未推送）

检查日期：2026-09-26。`origin` 为 `Fanmili-5/energybridge-household-survey`，只读 `git ls-remote` 核得本地 `main` 与远端 `main` 同在 `a49ab6c6a6ac265fa70331dc942c8f9c5b67cb5b`。工作树有既存的跟踪修改与大量未跟踪研究文件，不能整仓或整棵 `docs/research` 暂存。既有 `deploy/energybridge.service` 从服务器 `/etc/energybridge/service.env` 取环境变量，Nginx 模板对管理端和部分 API 做权限区分；推送 GitHub 本身不等于线上服务已更新。本预检未访问线上参与者数据。

## 最小公开白名单

发布执行者在最后验收后依据 [`PUBLICATION_WHITELIST_20260926.txt`](PUBLICATION_WHITELIST_20260926.txt)按**精确文件路径**逐个暂存：项目代码与测试、不会含源数据或密钥的字段字典/方案说明、300 户经核对的合成画像、3,000 日模拟案例元数据、已审工程展示三件及前端静态资源。原始材料的下载来源、引用和本地再生步骤可公开；本机绝对路径须改成可移植的相对路径或来源标识后才纳入。每个候选文件须检查 `git diff --cached --name-only` 和内容，再提交。

下列内容不进入公开白名单：

- CHNS 原始户/个人/社区/空间记录及任何可重识别的派生微数据；真人或工程试填的原始回答、访问令牌、日志与数据库；`.env`、密钥、凭据、SQLite/SQL、完整运行日志。
- DeST `.accdb` 原型和未确认再分发授权的源模型；C/D 每户衍生 `.idf`、`runtime_inputs/` 和邻户源几何、材料完整重建件，在授权明晰前也不公开。CSWD `.epw` 气象文件亦暂不公开。
- `D_integration/runtime/` 的 `eplusout.*` 和 `process.log`；`complete_households_300.json` 当前含本机绝对路径，不可原样公开。若需要公开结果，生成最小去路径、去源文件内容的摘要，并重新核对数字与指纹。

仓库 `.gitignore` 已忽略 `.env`、数据库、日志以及 `simulation_resources/weather/` 等路径，但**未覆盖** D 的 `runtime_inputs/*.idf` 与 `runtime/eplusout.sql` 等位于研究目录的文件。因此忽略规则不能代替上述白名单。现有 `examples/real-test-20260914/` 已在仓库中，不能据此推断新真人数据有发布许可。

## 官方来源许可判断

- [DeST 典型建筑库](https://www.dest.net.cn/dxjzk) 说明模型下载、使用和论文引用；[新下载目录](https://cal.dest.net.cn/building_model/building/download)列出原型。所见页面没有明确授予模型及转换 IDF 的再分发许可，需作者/权利人确认后才考虑公开原件或可重建衍生件。
- [Climate.OneBuilding 数据来源页](https://climate.onebuilding.org/sources/)列出中国 CSWD 270 站点并提供下载；所见页面没有明确的 CSWD 再分发授权。站点上其他数据集的许可不自动适用于 CSWD。
- [CHNS 数据使用协议](https://www.cpc.unc.edu/projects/china/data/datasets/DataUseAgreementCHNS_20201020.pdf) 对保密数据及其二次信息限制团队外共享，并要求保护被调查者匿名性。公开下载的户/个人数据与协议中的保密社区/空间数据应分清；本项目无需把原始 CHNS 表打包至 GitHub。
- [国家统计局服务条款](https://www.stats.gov.cn/wzgl/202302/t20230217_1912857.html)允许下载使用其发布的统计数据，引用须注明来源且符合其版权和用途条件。合成数据包应保留统计量的出处、分母与适用总体，不镜像无必要的源页/PDF。
- [EnergyPlus 软件许可](https://github.com/NatLabRockies/EnergyPlus/blob/develop/LICENSE.txt)只覆盖该软件的再分发条件，不能作为 DeST 模型或 CSWD 天气的许可依据。

此处为发布前范围判断，不替代最终按暂存文件逐件检查。最终还需记录提交哈希、远端分支，以及真实浏览器/HTTP 入口与响应导出回归的验证结果。

## 当前限定可携带包

F 对 `E_collection_release/public_role_package/` 作了独立逐文件预检（[`public_candidate_preflight.json`](public_candidate_preflight.json)）：7 个 CSV 与 1 个清单精确吻合，逐文件 SHA/行数一致，300 个唯一合成角色，未见本机路径、源模型文件或常见密钥。其 `PUBLIC_MANIFEST.json` 原状态仍是固定角色候选；正式工程案例另由 F 审 G 的 297 次新运行、3 次完全相同基线复用、3,000 日逐日证据、2,277 个当日动作差异，并核 `G_casebank/accepted_public/` 三件只在许可/工程批次状态上由已审 pending 晋级。`F_independent_review/ROLE_COLLECTION_RELEASE_GATE.json` 当前状态仅 `ROLE_TECHNICAL_PREVIEW_APPROVED` 且 `human_collection_approved=false`，允许隔离工程预览和试填。`G_casebank/public_case_tables/cases_3000.csv` 的 26 列/3,000 行逐值对应模拟原载荷，`feedback_rows` 全为计数 0，无人类选择或评分列。正式真人研究同意、认知试填和反馈仍为 0/未验收。

本轮公开文件白名单是可发布**候选**：还需检查最终暂存内容与上游文件 SHA；不把 `outputs/`、整个研究目录、实际 IDF/EPW/SQL、原始 CHNS/DeST 资产、临时测试数据库或参与者记录加入暂存。需要重建完整物理仿真的研究者应从各官方来源自行取得有权使用的模型与气象数据；本仓库仅公开方法代码、来源标识、受控模拟结果及审计边界。
