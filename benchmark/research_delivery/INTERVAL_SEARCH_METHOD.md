# 原动作域内的区间约束传播（delivery_v2_5增量）

本修订在现有IPOG-C存在性查询之前传播必要工程约束。原A、原生动作、10分钟网格、候选含义和覆盖分母均保留。配置 `oracle_propagation: interval_v1` 显式启用；旧源快照保留重放路径。

## 依据与实现范围

Mackworth, *Consistency in Networks of Relations*, Artificial Intelligence 8(1):99–118, 1977，DOI `10.1016/0004-3702(77)90007-8`，讨论搜索前消除局部不一致以及约束操作与搜索结合。核读作者PDF摘要、第6节及第7.1节（原页103–107相关内容），第6节AC-3在106页。

原文：[作者PDF](https://www.cs.ubc.ca/~mack/Publications/AI77.pdf)；[作者书目](https://www.cs.ubc.ca/~mack/Publications/b2hd-AI77.html)。文献支持局部一致性传播这个技术工具。本实现是面向设备占用和洗烘依赖的反复扫描传播器；行为分布、样本配比、家庭接受意愿和实验预算不由该论文支持。本项目的区间快捷判定由下述必要条件及独立穷举核对。

## 查询及安全剪枝

每个任务的原生备选包含设备占用区间 `[load_start, unload_end)`。一个查询同时指定描述因素、允许的原生动作索引，以及可选的联合阶数。

1. 因素条件与原生索引条件取交集。缓存和快速联合见证均必须满足所有条件，不能用别的已找到方案回答当前查询。
2. 对固定不变批次，移除占用区间相交的备选；原洗衣取出结束晚于烘干装入开始的备选也移除。
3. 同设备两个可变批次，若备选i的结束不晚于j域中最晚开始，或i的开始不早于j域中最早结束，则有二元占用支持；否则该备选不能出现在任何满足此查询的完整方案中。
4. 洗烘先后关系有方向：烘干装入必须不早于洗衣域内至少一个取出结束；洗衣结束必须允许至少一个烘干装入。反复传播到域不再缩小。
5. 全方案至少一个直接事件动作；只有一个因素仍可提供直接事件动作时，该因素必须承担此作用。给定联合阶数时，依据必改/可改因素数传播零值和非零值。
6. 人员是否方便、期限压力、舒适损失、偏好、执行确认、削峰方向及实际后果均不参与这些剪枝。缩减后的非空域继续进入原字面检查及CP-SAT；局部支持不等于全屋联合可行。

**空域证明只属于当前查询的声明原生域。** “单设备且其余不变”查询不可行，不代表允许其他设备必要配合时仍不可行。查询超时仍为未知。被剪枝值及全部原生域可从原目录、查询条件和传播规则重放；不更改原机会分母。

设U为因素数、D为域大小总和，一轮扫描上界约O(U×D)，朴素反复扫描最坏可达O(U×D²)，额外域存储O(D)。这减少无效字面展开，不提供完整大域符号编码或多项式全局求解保证。

## 搜索次序

新增模式先按设备族轮转检查机制，再探索联合阶数与细节交互；保留全部种子和预算日志。轮转是计算资源次序，不是正式题型配比。空调增加描述字段不增加设备族轮转次数中的单次机会。仍须用固定输入比较次序与预算影响，不能据定向缺口查询宣称500道正式题覆盖已经改善。

## 验证边界

独立枚举2744组小域/联合阶数/依赖条件，检验没有合法完整赋值被剪掉；另测固定批次、固定上游和互相矛盾的查询条件。169项缺口使用冻结目录、原种子和原计算预算逐项对照；两户缺口优先，同一域比较无传播与区间传播，所有结果保留。

同类多批的唯一潜在家庭日单独留存查询。首次查询失败、追加明确“两个任务均直接关联事件”的诊断，分别记录，不能用子域不可行宣称全域不可行，也不将诊断直接补入正式选题目录。

这轮见证证明的是计划及事件作用路径，不是受访者接受、仿真成功或真人行为有效。完成正式覆盖验收还需要在冻结新版规则后重新生成相应候选、选题和独立账本，并检查长尾保留、去重与原资料哈希。

## delivery_v2_6：传播后分支搜索

`interval_forward_v1`在每次赋值后重新传播占用、物料及事件根约束，选择剩余原生值最少的因素继续分支。默认每查询1024个分支节点，可配置；完整字面物化仍受原预算限制。值次序是原值、不变、直接事件路径及条件支持的确定性次序，不读取收益或接受标签。该次序属于本项目实验设置。预算耗尽保留unknown；局部传播后的空域仅证明当前查询无工程支持。

技术依据另见Haralick与Elliott的[作者托管IJCAI1979原文](https://www.haralick.org/DV/conferences/increasing_tree_search_efficiency_for_constraint_satisfaction_problems.pdf)，核读原页356—358及第2节；讨论前向检查和优先选择剩余标签少的变量。1980年扩展期刊版DOI `10.1016/0004-3702(80)90051-X`本轮仅核对出版元信息与摘要，不声称核读全文。我们的反复区间传播比单纯已赋值对未来变量的前向检查更强，属于成熟搜索思想的专用实现。1024分支节点与1024笛卡尔积遍历不是相同CPU工作量，必须同时报告耗时与节点数。

另用2744个小域/依赖/联合阶数组合，比较完整搜索结果集与独立字面不等式枚举，检查没有丢解或重复；独立测试预算耗尽不能报告不可行。生产入口还对实际存在的同类任务对发起查询，其他因素先保持原值，必要时检查联合扩展；该查询不是十题配比。

**仍有已知缺口：**0696/0756以外的0653部分洗碗装取重排，旧原生网格使用人员日历和房间预约过滤装取时刻；它会遗漏可供判断的生活冲突。区间搜索不能恢复从未进入原生域的值。该问题必须单独修订生成域，保留原域和前后对应；不能把缺少事件根写成家庭无机会。

## delivery_v2_7：机制联合扩展和独立释放界

启用`mechanism_joint_extension`时，每个机制先要求目标本身具有直接事件路径；单项失败后，用相同原生值和预算允许其他任务提供必要配合。查询全部保留，支持角色不能计为目标直接根，不按后果或预计接受度挑解。

`opportunity_bounds=precedence_v1`从原需求与完整服务链推导放松下界：释放→装入→完整程序→取出→下游装入。计算忽略便利、期限、资源和同意，只保留必要时序。下界不早于19:00且原A也不在事件内时，任务无法成为直接事件根。已经装入、已经运行及尚未执行的取出分别处理，不能把原等待时间固定为不可改变。缺少上游证据或依赖成环时不给排除证书。

数值来自本户原时间与时长，不是论文给出的行为阈值。机会账本保持原key并保留`pre_bound_status`、证书和前后对应，原数值网格不缩减。独立放松网格枚举核对了公开六类36项：18:00释放→装入10分钟→洗衣60分钟→取出10分钟→烘干装入10分钟，最早19:30启动烘干。结论只涉及直接事件作用，必要依赖角色仍需另行检查。
# Revision 2.8: keep calendar-conflict handling proposals

`handling_calendar_domain=include_life_conflicts` is an explicit native-domain
revision. For each existing machine template it enumerates the original
10-minute load/retrieval coordinates inside the original release, preload,
retrieval, deadline and horizon envelope. Operator calendar and room bookings
are evaluated on the resulting proposal, rather than used to exclude coordinates.
Qualification, immutable operators, executed operations, timer capability and
physical order remain unchanged. It creates neither a helper nor consent.

This revision intentionally expands the old convenience-filtered domain.
Reports must preserve old native IDs, publish additions and compare the same
input/A hashes. It must not be described as an algorithm-only comparison with
an unchanged domain. Pure search comparisons use one fixed domain on both arms.

Invariant template digests are cached once per machine template. Oracle root
membership uses sets and query restrictions avoid constructing two full-domain
sets for a singleton query. These are representation optimizations, not new
behavioral assumptions or changes to search/value ordering. Complete coordinate
metadata is still enumerated: this implementation is not a fully symbolic CSP.

The rule separating calendar inconvenience from engineering feasibility comes
from the declared benchmark task. Prior device-flexibility papers motivate
separate flexibility and burden; they do not provide this domain's empirical
frequency, acceptance labels or a required conflict proportion. No such claim
is made. Independent small-grid enumeration, immutable-permission tests,
frozen counterexamples and before/after domain records check the implementation.
