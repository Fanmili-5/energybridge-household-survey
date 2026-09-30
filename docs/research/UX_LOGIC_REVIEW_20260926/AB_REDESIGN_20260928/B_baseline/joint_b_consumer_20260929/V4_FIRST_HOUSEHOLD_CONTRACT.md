# V4 首户增量接入合同（cityrole-0021）

本地页面继续使用 `unified_pipeline.py`、`template.html` 和统一 A/B 渲染器。来源 A/B 为 `A_proposals/rich_device_revision_20260930/formal_lifestyle_v4_semantic_v1/FORMAL_3000_SOURCE_LOCK_SEMANTIC_V1.json` 中 `cityrole-0021` 的十轮；消费者已逐轮验证原命令可转为统一 case，原始 `presentation_order` 为奇数轮 A/B、偶数轮 B/A。不能用旧重庆 `cityrole-0012` 的结果或模拟值替代。

E 的稳定交付入口固定为 `E_execution_delivery_20260930/native_physics_adapter_v1/v4_semantic_household_releases/cityrole-0021/RELEASE_MANIFEST.json`。消费者需要以下最小内容；缺项只会显示“未计算”，不能填零或推断达标：

1. `schema`、`role_id=cityrole-0021`、`source_lock_sha256`、`source_annual_sha256`、`source_profile_sha256`，以及十轮唯一的 `round_index`、`proposal_id`、`date` 和 `source_proposal_sha256`。所有文件引用同时给绝对路径和 SHA-256。
2. 一份共享 A 的实际执行回执和 10 份 B 回执：各自 IDF、EPW、trace/参数、EnergyPlus 版本、原始 SQL、读回文件的 SHA-256；每轮显式引用同一共享 A，不得复制成十次不同 A。每个结果写 `status`、实际时步数、Severe/Fatal 数、计量核对状态及未解决警告。
3. 可展示数值逐通道给出 A/B 双侧 `status`、`value`、`unit`、`meter_boundary`、`source_output_key`、`start_abs_min`、`end_abs_min` 和结果文件 SHA-256。事件内购电、整户购电、设备电量、空调用电、模型室温、费用各有独立边界；只交付实际读回并核实边界的项。室温还需房间/zone ID 和采样时窗，空调设定温度不能代替室温。费用无明示费率与计费规则时保持未知。
4. 每轮 B 与原提案的命令/日期/事件窗口及完整 A/B 计划哈希一致；A/B 数值只在相同计量边界、单位和时窗下比较。VPP 达标只在整户净购电事件窗的 A/B 实际值与目标都齐全且可比时给结论。物理质量门未通过的通道不进参与者页，保留在私有审计。

发布只从经哈希核验的 `cityrole-0021` 十轮页面打包，公开文件白名单仍为 `index.html`、`style.css`、`candidate.css`、`joint-view.css`、`plan-view.js`、`source-draft.js`、`household-view.js`、`joint-view.js`；私有 SQL、IDF、EPW、trace、源家庭材料、密钥和 SQLite 不进入静态资源。新入口为仅体验模式：回答和问题报告均不提交、不下载、不写库，服务端拒绝 POST；旧库不改动。根核对本地候选后再切换 `/joint-b/`，保留前一 release 与 unit 备份供回滚。
