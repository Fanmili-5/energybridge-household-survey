# 第二主线的可公开依据

有来源表示可以核对采用了什么，不表示一篇论文验证了全部规则。固定版本、阅读状态、SHA和公开路径见[SOURCES.json](SOURCES.json)；当前设计见[DESIGN.md](DESIGN.md)。

| 论点 | 来源与位置 | 支持范围与局限 |
|---|---|---|
| A应独立于优化提案；提案、同意、执行和反馈分开 | [原EB adaptive harness](https://github.com/Agentic-Intelligence-Lab/EnergyBridge/blob/2b17ae63e613da776c93e900f5dace50d63a88a8/docs/ADAPTIVE_HARNESS_ARCHITECTURE.md)的Consent及Stage-aware causal memory节 | 原系统设计要求；本项目实现新的确定性A和假设应用B，不复现完整agent闭环 |
| 先判断提案，后看选择对应结果；动作和说明须有方法出处 | [原中文问卷](https://github.com/Agentic-Intelligence-Lab/EnergyBridge/blob/2b17ae63e613da776c93e900f5dace50d63a88a8/human_survey_materials/questionnaires/roleplay_vpp_feedback_zh.md)、[呈现协议](https://github.com/Agentic-Intelligence-Lab/EnergyBridge/blob/2b17ae63e613da776c93e900f5dace50d63a88a8/human_survey_materials/questionnaires/strategy_presentation_protocol.md) | 合成B不能贴成原EB输出，也不能补写说服说明冒充原方法能力；线上问卷本次不接入 |
| 人员活动与设备事件/热环境分层 | [Chen等作者稿](https://arxiv.org/abs/2111.01881)的event schedules与ResStock integration；[正式身份](https://research-hub.nlr.gov/en/publications/stochastic-simulation-of-occupant-driven-energy-use-in-a-bottom-u-2/) | 结构依据；2021作者稿v2与2022正式文献分别登记，未移植Markov模型、美国分布或其验证结果 |
| 费用与生活安排需要分维度考虑 | [El Makroum等机构记录](https://repositum.tuwien.at/handle/20.500.12708/228812)，时间使用与负荷调度方法；先前已阅PDF SHA登记 | 机制依据；确切权重、剂量和三排序均自设。此次机构记录可访问，出版社403、项目下载未成功，不冒称重新取得全文 |
| 情境因素与主观参与判断分开测量 | [Wen等正式PDF](https://pure.hw.ac.uk/ws/portalfiles/portal/147868180/1-s2.0-S030626192500340X-main.pdf)第3节factorial stated-preference design | 研究设计依据；英国项目选择不直接验证中国家庭24小时提案，也不提供本项目接受率/角色比例 |
| 装取链、原连接和控制习惯的项目沿革 | [九项历史源登记](SOURCES.json)、[原设计稿](provenance/REUSABLE_AB_CONTRACT.json) | 六份此前仅本地的原文已补公开路径；属于项目规则，历史代码不能作为新入口执行 |
| 电耗、温度与服务后果须执行后核对 | [住房来源](../housing_simulation/SOURCES.json)、EnergyPlus24.1原生输出、完整A/B时间轴 | 数值依据；名义功率不是增量响应，仿真不等于现场校准 |
| 证据、反例和结论范围分别记录 | [Scientific Agent Skills](https://arxiv.org/abs/2609.00065)，当前记录2026-09-02 v2 | 复核流程来源，不是能源模型、许可或人类有效性的证据 |

逐参数值、人工选择及未校准状态见[PARAMETERS.md](PARAMETERS.md)。来源可见性不自动产生再许可或住户同意，见[AUTHORIZATION.json](AUTHORIZATION.json)。

参考文献：

1. Chen, J., Adhikari, R., Wilson, E., Robertson, J., Fontanini, A., Polly, B., & Olawale, O. (2022). Stochastic simulation of occupant-driven energy use in a bottom-up residential building stock model. *Applied Energy, 325*, 119890. [DOI](https://doi.org/10.1016/j.apenergy.2022.119890).
2. El Makroum, R., Zwickl-Bernhard, S., Kranzl, L., & Auer, H. (2026). Load scheduling optimization for user-centric residential demand response leveraging time use surveys. *Applied Energy, 403(B)*, 127080. [DOI](https://doi.org/10.1016/j.apenergy.2025.127080).
3. Wen, C., Steadman, S., Rafaq, M. S., Vatougiou, P., & Deakin, M. (2025). Can reduction of local carbon emissions motivate participation in demand-side flexibility programs? Evidence from the United Kingdom. *Applied Energy, 388*, 125610. [DOI](https://doi.org/10.1016/j.apenergy.2025.125610).
4. Kassis, T., Agarwal, V., He, Y., Patel, D., & Brueckner, A. M. (2026). Scientific Agent Skills: A Library of Procedural Knowledge for Research Agents. [DOI](https://doi.org/10.48550/arXiv.2609.00065). 最新记录于2026-10-19核对，仅用于复核流程归属。
