# 双户累加体验候选（尚未上线）

- 本地页面：`http://127.0.0.1:8879/joint-b/`，家庭下拉可分别查看 `cityrole-0021` 与 `cityrole-0022`，每户 10 轮。
- 归档：`/private/tmp/joint-b-v4-0021-0022-release-candidate.tar.gz`，SHA-256 `37b08cf4e7611256cc56c359a0d7276e010fc9259b662413b1cdf7803c28d9e1`。`RELEASE.json` SHA-256 `0d81e545f5b5919e7efedb507d3f8cedefb89540652d8f98e7c2c98f46038df7`；验证器通过 2 户、20 轮、13 个文件。
- 新增 E 来源 `cityrole-0022/RELEASE_MANIFEST.json` SHA-256 `c830cd00a05d65202b79af742933b9608a0364fa9667a27f826cb12604eb8bcc`，`SITE_DATA.json` SHA-256 `98d7f8f5d1f1956edc3be328a06aa85f1bb0c1be574756f6c4a467323675a760`。十轮原始来源、A/B 配对、物理质量门与计量边界逐轮核验。0021 使用原已上线的物理 sidecar；合并 sidecar 校验两个原 sidecar 全部条目，SHA-256 `6a3a829a78cb0224d1165c3e19165dcae7b1a14f2e5413a7064f3ac29d60937d`。
- 累加门禁：打包时与已上线 0021 release 比较旧户的来源、安排、结果及左右映射；仅打包 0022 被拒。无实际结果或十轮不全也拒绝。公开首页无本机路径、SQL、IDF、EPW或原始读回文件引用。
- 0022 模型结果：第 1、2、4、7、10 轮达到购电削减目标，其余 5 轮未达；充电目标 B 相对 A 额外未达第 1、2、4、7、10 轮。热水需求 A/B 每轮各有一次未完全满足，出行用电需求均无缺口。费用未知、室温模型未校准，事件内削减不等于后续持续节电。
- 本地 UI 已逐轮核验第二户 10 轮均无展示错误；服务 health 为 `experience_only`、20 cases，回答 POST 405。尚未上传或切换服务器，下一次公开发布需核对这个精确包及线上回退点。
