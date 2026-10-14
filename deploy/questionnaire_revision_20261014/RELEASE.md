# 2026-10-14 原50户问卷改版

已发布入口：[50户角色问卷](https://47.85.194.154/household50)。版本 `eb.household50.questionnaire.20261014.1`，逐户任务来源为已验收的V27原50户、每户原10个日期，共500组A/B。改版继续使用原成熟前端。

本次按Ze Qing建议保留“生活与用电影响”，新增填写者**本人**年龄与性别（选填、无默认值），明确与扮演角色资料分开。主时间轴使用短动作名称，相同连续控制仅在展示时合并；逐台A/B默认展示前两段，其他动作及截断时段的完整信息可展开。原始任务、设备参数、完整时间、A/B和物理后果均不改变。需求及影响文本仍完整保留，后续可根据真人试读再压缩。

导出升级到 `eb.joint_b.local_test_export.v6`，本人资料单独保存为 `respondent: {age_years, gender}`，不写入角色画像、模型输入或可见角色快照。性别允许女、男、其他、不愿透露或未填；年龄允许1至120的整数或未填。未填是null，与明确不愿透露分开。采用/不采用、四项可空小数评分与理由仍保留；当前答案仍在输出侧。

[核验汇总](CHECKS.json)：500组任务的六类内嵌JSON与V27源逐户相等；454个发布文件hash一致；学校原V27验收输入未改动；云端50个页面、保存/读回、重试幂等、来源/会话校验通过。一个实际浏览器工程导出与两种导出函数对照检查通过；第二次浏览器下载超时，不计为成功导出。配对HTTP记录仅在隔离临时数据库中核验。公网HTTPS及脚本hash、简略动作、影响展示、本人资料跨情境保留均通过。

旧50户数据库已一致性备份并逐库比对行数与内容hash，旧发布目录和数据根保留。新版使用独立数据根；测试记录未写入线上库。只切换50户服务，原真实家庭自报入口与旧joint-b服务未变更。

发布包签名：`e9992e7aaf4fc433e3a0b8de72b0672e92a1ed82cbd2dcd2eb963c965f70f9b6`。来源V27验收输入签名：`7f925a3a307b9d6e44017ca5ef045a77c521224780a287428d0acebed6c80d76`。这两个签名分别绑定已验收任务世界和本次问卷展示版本，不互相替代。

本次仍是工程试填/角色试读入口，保存回执明确此范围；没有预设真人回答，改版验收不构成真人有效性证据或正式benchmark准入。未启动1000户全量EP，也未重新运行原50户EP。公开仓库只同步源码、展示修改器和无逐户数据的核验汇总；受控任务包、IDF/SQL、浏览器导出、答卷及服务器备份不上传。

## 复现改版与测试

在具备授权的受控V27原50户前端包上创建新目录，禁止原地覆盖已验收输入：

```bash
python3 deploy/questionnaire_revision_20261014/revise_frontend.py --source /authorized/V27/frontend_release --output /new/questionnaire_release
python3 deploy/questionnaire_revision_20261014/test_respondent.py -v
node deploy/questionnaire_revision_20261014/test_export.cjs /new/questionnaire_release/households/<household_id> /private/browser_engineering_fixture.json
python3 deploy/questionnaire_revision_20261014/verify_protocol.py --release /new/questionnaire_release --fixture /private/browser_engineering_fixture.json
```

导出/HTTP检查的fixture必须是对应版本的工程记录；不使用真人答卷作为公开fixture。`preview.py`是只读本地预览，拒绝POST；`verify_protocol.py`创建隔离临时数据目录，退出后清理；它不是向已部署站点提交的脚本。
