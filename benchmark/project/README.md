# 三条主线 → UI91正式问卷与v69离线示例

原50户500题已准备**UI91立体房间与完整配对后果**，当前入口暂停等待核验切换。每户十个不同日期，VPP固定18:00—19:00；500题均有可用估算，80题达标、420题未达标，100题服务或恢复问题照实保留。497条原选题不变，3条按事前工程补生成流程换为原全年A的新日期切片；原失败记录、设备和全年A保留，旧答卷不迁成新版答案。1000户继续暂缓。

以下六户37案命令是独立的v69只读接口示例，仍保持后果未计算，不部署正式服务，不代表真人标签。

## 已接通

1. 固定家庭输入 → 家庭成员、关系、实验角色、设备和操作权。
2. 同一家庭 → 参考住房匹配、设备安装、完整生活安排及无事件 A。
3. 冻结 A → 不同 B 请求的联合目录 → 固定分层取样；保留无效、探索、无变化及未选请求，不按成功重抽。
4. 每个原始 A/B → v69 家庭资料、变化摘要、完整本题排程、VPP 请求和后果状态。家庭、住房、完整 A/B 的 SHA256 连续绑定。
5. 另有显式 `prepare-idf` 命令，使用同一住房/天气准备配对模型文件；**编译不运行 EnergyPlus**，也不推断物理成功。

`questionnaire` 读取已封存项目，不重新生成或挑选 B。37 份资料保留原始案例，不合并成一个“最佳 B”。同一天的多个 B 用案例 ID 选择，不伪装成不同日期。

## 直接查看既定前端

需要 Python 3.9+ 和 Node.js 22。公开资料已打包，可先检查和打开：

```bash
python -B -m benchmark.project verify-questionnaire benchmark/project/examples/questionnaire
node benchmark/project/verify_display.js benchmark/project/examples/questionnaire
python -B -m benchmark.project serve --port 18780
```

浏览器地址：`http://127.0.0.1:18780/household50-current/form`。这是回环地址的只读资料预览，沿用 v69 页面、样式、接受/拒绝、四项1—5评分及原因。输入仅用于本页交互检查，不写生产答卷、没有采集 API。可用 URL 的 `household` / `case_id` 定位其他资料；不改变正式问卷的身份分配。

生成新项目还需住房模块的依赖；以下命令均不启动仿真：

```bash
python -m pip install -r benchmark/housing_simulation/requirements.txt
python -B -m benchmark.project build --out /tmp/eb-project-new
python -B -m benchmark.project verify /tmp/eb-project-new
python -B -m benchmark.project questionnaire --project /tmp/eb-project-new --out /tmp/eb-v69-new
python -B -m benchmark.project verify-questionnaire /tmp/eb-v69-new
python -B -m benchmark.project serve --release /tmp/eb-v69-new --port 18780
```

输出目录必须为新目录。`SELECTION.json`、`COVERAGE.json`、每户目录、全部生成结果和完整 A/B 留在项目目录。`SOURCE_CODE.json` 记录构建时实现字节；问卷资料包另封存 v69 源文件摘要、可见文本与逐案来源。完整运行目录中的 gzip 是运行产物，不发布到公开 Git。

可选的配对模型准备：

```bash
python -B -m benchmark.project prepare-idf --project /tmp/eb-project-new \
  --weather /registered/USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw \
  --preparation-profile benchmark/project/examples/preparation.json --out /tmp/eb-idf-new
```

默认按固定规则为每户导出一个请求，供检查编译接口；可以用 `--sample-id` 指定原样本。没有编译成功后的换 B 或重抽。该导出子集不是问卷分层样本；全部问卷与无效目录原样保留。

## 六户离线示例的边界

- 本轮没有运行 A/B，所以**实际电量、室温、服务完成、VPP达标及物理费用全部未计算**。JSON 使用 `null` 和 `outcome_status=not_computed`，前端逐项显示“未计算”，不能写成0、成功、不达标或没有人使用。
- 没有把新材料接入正式答卷数据库；这不是新一轮正式采集准入或训练数据发布。日后若要收集基于实际后果的评价，需另做后果适配及案例/后果/答卷版本绑定，不得复用旧50户的仿真或答案补空。
- 六户只证明接口连接与保留逻辑；不证明人口代表性、完整长尾覆盖、物理有效性或真人可理解性。可选分层缺额原样公开；旧10层冻结实验与203项交互缺额仍是独立版本。
- 仅运行上述六户离线命令不修改正式服务、封存发布或答卷；1000户继续暂缓。

详见 [接口](INTERFACES.md)、[方法与依据](METHOD.md)、[覆盖与缺额](COVERAGE.md)、[自查结果](VALIDATION.json)。

## 新方法参考50户发布包（第四版）

使用 `python -B -m benchmark.project.reference_collection_release --collection /controlled/new-v4-selection --profiles-release /controlled/original-v69 --original-a /controlled/normal-A46 --out /controlled/reference50-v4`。只沿用原封存家庭背景，500题全部取自新B选择。实际物理后果保持未计算，答卷标为后果展示前的提案判断；同一对A/B后续可单独仿真并绑定摘要。新发布保留v69表单与收集协议，不能复用旧B的物理数值，也不能改写旧答卷。该命令只生成封存包，不激活线上服务。

正式50户的完整500组新配对结果已经接入UI91，见[正式方法](UI91_FORMAL_PHYSICS.md)、[全量自查](FULL500_PHYSICS_VALIDATION.json)和[上线凭据](../releases/reference50-v4-ui91-physics/ACTIVATION.json)。[早期小规模连接记录](UI91_PHYSICS_HANDOFF.md)仅保留开发历史，不代表当前完成范围。
