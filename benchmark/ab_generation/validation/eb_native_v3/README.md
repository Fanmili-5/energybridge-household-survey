# 六类原生动作V3：规则和试跑范围

冻结EB提交：2b17ae63e613da776c93e900f5dace50d63a88a8。公开[规则](RULESET.json)、[聚合验证](VALIDATION.json)、[原函数等价核对](UPSTREAM_EQUIVALENCE.json)和[旧10000题静态审计](LEGACY_10000_ACTION_AUDIT.json)。家庭记录、候选目录、逐户选题、实际日程与答卷不随Git发布。

49户×10题，共490组；980份完整A/B通过原校验器，并完成程序设备、热水器指令窗口与EV原生回放。空调实际检查时点、温度精度和Agent范围通过。102/102适用空调目标至少涉及两个国家；178/178初始池冻结联合目标覆盖。完整LLM/规划器/同意流程未执行。房间与热水热后果尚未计算，不能将“原生电器回放”当成EnergyPlus全链路验收。

现有服务器记录包含125项相关测试通过。发布前另在现有项目环境重跑当前相关测试，结果见[发布检查](PUBLICATION_CHECKS.json)；原生源缺失时测试跳过必须另外计数。

## 公开检查

在仓库根目录、已配置当前[依赖](../../unified/requirements-lock.txt)的环境：

```bash
python -B -m unittest benchmark.ab_generation.test_eb_agent_contract benchmark.ab_generation.test_eb_alignment benchmark.ab_generation.test_daily_problem benchmark.ab_generation.test_daily_services benchmark.ab_generation.test_v9_episode_contract benchmark.ab_generation.unified.test_household_entry benchmark.ab_generation.unified.test_selection_execution_gate -v
python -B -m benchmark.ab_generation.verify_package
```

需要回放的测试使用固定原EB的appliance_sim.py，路径可用EB_NATIVE_SOURCE设置；新版动作函数的固定来源和哈希见[来源锁](../../upstream_eb_agent_contract.provenance.json)。检查不生成真人答案。

V3试跑的目录扩充、跨角色CP-SAT选题和原生日历队列仍由服务器编排，尚无脱离受控输入与内部脚本的一键公开490题重建命令。本目录是规则、生产守卫代码及聚合证据发布，不是可分发的完整训练集。全量覆盖分母、10000题重生成、同版本IDF后果和UI91发放仍需验收。
