# 源码核查、准备输入与学校执行

## 干净GitHub checkout可以核查什么

```bash
python3 scripts/household1000.py status
python3 scripts/household1000.py stages
python3 scripts/household1000.py check-source
python3 scripts/household1000.py doctor
```

`check-source`核公开源码字节，`doctor`如实列未包含的受控输入；都不启动仿真或模型。它们不是科研准入或完整原始数据重生成验证。

## 在已准备合法输入的学校工作区

```bash
python3 scripts/household1000.py doctor --workspace /path/to/prepared/energybridge-household-survey
python3 scripts/household1000.py check-bindings --workspace /path/to/prepared/energybridge-household-survey --scope pilot50
python3 scripts/household1000.py check-bindings --workspace /path/to/prepared/energybridge-household-survey --scope static1000
```

此检查读世界和配对，不修改封存版本：核家庭/人数/日期、文件hash、共同需求、参数绑定和A先冻结；B冲突不会被当人类拒绝。它不检查未运行情境的EnergyPlus后果。

研究执行入口在`PIPELINE.json`逐步列出。完整生成须按`INPUTS.md`准备前置阶段与依赖，使用新版本目录；封存输入上的生成/编译/前端构建通常有防覆盖门槛。原V17 runner只读取授权的`SELECTION50.json`并核范围，不提供默认全1000执行。当前GitHub更新没有新增运行、正式采集、训练或付费调用。

源码保留了学校路径和历史阶段依赖，以便核对实际产生结果的版本。移植机器时需在新版本配置或转换路径并重新核输入/hash，不能把历史硬路径当通用默认。原始输入缺失时保持缺失，不伪造家庭、后果或答案。已生成20,000份IDF留在学校；这次同步不重新运行它们。

## 前端和反馈

V17 `build_site.py`读核查后的500对后果，向去案例模板的六段JSON填入同版本角色与情境；`prepare_frontend.py`沿用原渲染/保存逻辑并隔离技术分组。`serve50.py`为工程环境提供入口。正式actor身份、允许历史、反馈预算及评测切分见`RESEARCH_GATES.md`，尚未完成；不能将工程保存文件改名当真人数据。

## 验证记录

本次发布的验证记录见`PUBLICATION_CHECK.json`及`RELEASE_MANIFEST.json`。其中源码/链接/读取检查与学校私有输入绑定检查分别记录；未把一次只读检查升级为物理校准、真人有效性或算法成绩。
