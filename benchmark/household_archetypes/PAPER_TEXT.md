# 论文方法表述

## 目前即可采用：原型设计与证据

我们沿用EnergyBridge（EB）的六种预定义家庭偏好原型，覆盖费用敏感的务实通勤、居家舒适优先、作息变化与自动控制谨慎、稳定合作与自动化开放、照护优先，以及EV通勤优化等决策情境。六类作为合成评测任务的给定角色条件，不作为本研究从人口调查重新发现的互斥自然类别。

我们利用ECA、iFlex、荷兰家庭负荷移时调查和eCAPE的公开个体问卷，对原型的组成维度和部分同人特征共现进行外部核查。ECA提供费用关切、能源参与、控制顾虑及EV/充电背景；iFlex直接测量费用、舒适和自动化等灵活动机；荷兰调查连接活动规律性与自动控制自由顾虑；eCAPE补充生活作息变化及实际照护活动。核查保留各来源的版本、适用分母、条件跳题和权重，不合并不同调查的个体，不将背景或采用意愿等同于偏好或授权。

探索性聚类和共现结果支持若干原型维度，但未完整、稳定地恢复EB六类，也不确定其人口占比。角色的具体优先级组合、容忍阈值、通知/撤回要求及普通请求接受先验作为实验设定公开；这些先验不充当A/B案例答案。接受判断及评分需另行采集，客观VPP结果、节能和约束可行性分别记录。

引用分别使用[SOURCES.json](SOURCES.json)中的EB固定提交及四个原始数据源，分析脚本和汇总见[复现说明](REPRODUCE.md)。不要把我们的再分析写成原数据作者报告的EB六类，也不要将“有外部支持”改写成“六类已验证”。

## 配比政策：当前只能写为拟议

为保持与EB前序实验构成的可比较性，我们拟参考其公开实验中97/116/73/88/91/119名被分配角色参与者的构成，按最大余数法换算为1000户配额166/198/125/151/156/204。该比例是前序实验参考下的设计决定，不是家庭偏好人口比例估计。现有50户和1000户尚未按该配额迁移；当前数据的实验描述应继续报告其实际构成。

**只有实际实施并完成相容性、同源子集及版本核验后**，才能将“拟参考”“尚未迁移”改为完成时，并引用对应的新数据发布清单。方法文档定型不构成数据迁移、全量物理或真人效度验收完成。

## English draft

We retain six predefined EnergyBridge household archetypes to cover decision contexts involving monetary concerns, home comfort, variable routines and automation caution, cooperation and automation openness, caregiving, and EV-dependent mobility. These archetypes specify role conditions in a synthetic scenario benchmark rather than mutually exclusive population classes newly recovered from survey data.

We examine construct-level support using public respondent-level surveys from ECA, iFlex, the Dutch household load-shifting study, and eCAPE. We inspect native items, within-respondent co-occurrence, survey eligibility, conditional missingness, and source-specific weighting. Observations from different surveys are not joined into synthetic respondents. Exploratory clustering and linkage analyses support selected dimensions but do not establish the complete recovery, exclusivity, or population prevalence of the six EB archetypes. Joint priority profiles, numerical tolerances, notification and override requirements, and generic acceptance priors remain explicit experimental assumptions. Such priors are not used as case-level acceptance labels.

For a future release, we plan to reference the assigned-role composition of the public EB experiment, with counts of 97, 116, 73, 88, 91, and 119, and use the largest-remainder method to obtain a proposed 1,000-household allocation of 166, 198, 125, 151, 156, and 204. This allocation preserves a prior experimental composition; it is not a population prevalence estimate. The existing household data have not been reassigned under this proposal. Final experimental reporting must describe the composition and version actually used. We plan to report per-archetype, equal-archetype-weighted, and full-cohort performance to make the effect of the experimental composition visible.

## 审稿回应口径

- 为什么六类：继承EB原型用于同系列情境覆盖；不以某个外部数据的最优聚类数论证六类。
- 为什么这些比例：公开前序实验角色人数和取整规则；它是设计参考，不是代表性估计。
- 外部数据有什么用：排除凭空设定的维度，核查真实共现、重叠和缺测；不宣称全部角色完整恢复。
- E类为什么低接受：这是给定角色条件，不从“有孩子/照护/健康需求”自动推断，更不作为答案标签。
- 专家讨论如何写：可写沿用EB预定义原型；若要声明独立专家验证程序，另需可核验的流程和记录。
