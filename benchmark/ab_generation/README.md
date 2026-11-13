# A/B策略生成

当前八国V9路线：按固定EB noDR规则生成完整日常A；从原EB Agent合法动作构造B候选，按覆盖约束选择每户十个不同日期、每天一个B。完整上下游见[项目方法](../../docs/METHOD.md)，当前状态见[状态表](../../docs/BENCHMARK_STATUS.json)。

## 当前入口

**统一V3检查器属于本项目新增包装，仍可重放历史试跑，但不作为论文原版的旧题库判废裁判。家庭偏好、原Agent策略与本批实验约束须分开登记；生产准入对齐仍待按本次重审针对性修订。**

- [一天题目合同](DAY_QUESTION_CONTRACT.md)、[V9生产连接](V9_PRODUCTION_CONNECTION.md)：日期、服务与源绑定。
- [六类原Agent动作](../../docs/research/EB_MAIN_AGENT_ACTION_RULES_20261111.md)、[eb_agent_contract.py](eb_agent_contract.py)：原生动作守卫。
- [eb_primary.py](eb_primary.py)、[v9_date_adapter.py](v9_date_adapter.py)：原日常A与家庭日期适配。
- [eb_primary_candidates.py](eb_primary_candidates.py)、[unified/candidates.py](unified/candidates.py)：原生修改候选与组合。
- [新版规则与490题试跑](validation/eb_native_v3/README.md)：有限覆盖、原生执行和未完成项。

原生动作守卫已接入A入口、候选因子、合并请求与导出检查。空调不添加停冷/独立制热；程序设备保留每日完整任务；EV为停车连接内连续一段，可跨夜。B可违背软偏好，真人接受标签不由算法提前决定。

**生产CLI旧默认配置与服务器V3试跑编排分开。** 不能仅运行旧默认入口就宣称重建新版490题或正式10000题。全量新版尚未完成。旧4335是V2/V3包装检查计数，不能直接判数据无效；论文冻结版重审恢复130条，4205条需核对执行映射。旧题全部保留，详见[原版重审](../../docs/research/original_eb_reaudit_20261113/REPORT.md)。本轮490题的EnergyPlus后果仍未验收。

## 检查与历史

按[试跑说明](validation/eb_native_v3/README.md)运行相关动作/服务反例测试。原生源代码缺失时部分测试会跳过，应如实报告，不能将其计作原生回放通过。

```bash
python -B -m benchmark.ab_generation.audit_design
python -B -m benchmark.ab_generation.verify_package
```

[旧十天采集方法](docs/collection/COLLECTION_METHOD.md)、[v2.10/v2.11](../research_delivery/METHOD.md)、[早期生活到A](docs/life/LIFE_METHOD.md)及[历史复现](docs/core/REPRODUCE.md)按原版本保留。其装取动作、默认配置、候选和物理后果不能自动继承到新版原Agent动作规则。当前实现测试不启动模型API、训练、EnergyPlus或采集数据库。
