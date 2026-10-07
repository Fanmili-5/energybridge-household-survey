#!/usr/bin/env python3
"""Build the implemented-results entrypoint from the actual immutable batches."""
import json
from pathlib import Path
from household_model import save,sha

HERE=Path(__file__).resolve().parent
GEN=HERE.parent/'generation_model_20261003'


def read(p):return json.loads(Path(p).read_text())
def link(label,path):return '['+label+']('+str(Path(path).resolve())+')'


def main():
    s=read(HERE/'population_contexts_v1/SUMMARY.json');a=read(HERE/'annual_witnesses_v1/SUMMARY.json')
    b=read(HERE/'context_verification_v1/CONTEXT_BINDING_VERIFICATION.json')
    q=read(HERE/'DOWNSTREAM_QUALIFICATION.json');g=read(GEN/'final_v2/PROFILES_QC.json')
    ar=read(HERE/'ANNUAL_READBACK_VERIFICATION_FINAL.json')
    geo=read(HERE/'population_contexts_v1/INDEPENDENT_GEOMETRY_CHECK.json')
    source=read(HERE/'population_contexts_v1/INDEPENDENT_SOURCE_CHECK.json')
    warning=read(HERE/'ANNUAL_WARNING_REVIEW.json')
    assert g['pass'] and b['pass'] and ar['pass'] and geo['status']==source['status']=='pass'
    text=f'''# 家庭→IDF V2：已实现结果与后续接口

日期：2026-10-03。本次从固定的1000个中国内地城市家庭户名额重新生成家庭与住房，再逐户编译。排除镇和乡村，未把原300角色复制成1000，也未为了仿真成功改变家庭和住房。

## 实际完成

| 项目 | 冻结V1 | 本次V2实际产物 |
|---|---|---|
| 1000户成员与住房骨架 | 只有人口名额，尚未生成 | 1000候选、2506匿名常住成员；948普通、52非普通 |
| 宏观与语义核验 | 来源桥接与示例验证 | 生成774项独立检查；同种子逐字节重现；8批模型比较及10个语义反例 |
| 逐户物理输入 | 28控制，6个示例家庭住房输入 | 1000固定输入全编译、全保留，1000份生成绑定检查 |
| IDF静态准入 | 13示例 | {s['IDF_ready']}条件化IDF；{s['blocked']}明确拒绝 |
| 实际源组/天气 | 1源组、3EPW | 已准入113内容来源组、30个EPW；计划115源组、31工程气候context |
| 天气可用资源 | 原严格QC只覆盖14省 | 新增62原始文件全通过原QC；合计91通过/217拒绝，31省均有候选 |
| 年度见证 | 13示例 | {a['actual_annual_runs']}真实年度运行，{a['passed']}完成8760小时；Severe/Fatal为0；41案例有warning，80日志标记含重复摘要 |
| 实际居住城市绑定 | 0 | 0：当前是单独的工程气候暴露，1000原profile城市仍未知 |
| 人员/设备/HVAC和可收集问卷 | 未完成 | 接口合同和逐户状态已保存；完整运营模型与可收集问卷仍为0 |

实验批次：`{s['experiment_id']}` 与 `{a['experiment_id']}`。755个IDF全部通过独立几何读取和源材料精确读取；1000个输入全部完成家庭/住房/名额/版本绑定核验。117个年度见证按已准入省份、内容源组与4个输入极值确定性选择，选择锁在运行前保存；并非全1000年度运行，也不是全国能耗估计。

## 可直接查阅的数据与生成逻辑

- {link('1000户冻结家庭与住房候选',GEN/'final_v2/FAMILY_HOUSING_CANDIDATES.json')}：`slot_id`、成员、实际占据代数、关系设计、H5/H6/H7、共享范围、睡位及逐字段依据；无原调查户ID或回答标签。
- {link('生成模型卡',GEN/'MODEL_CARD.md')}与{link('独立774项核验',GEN/'final_v2/PROFILES_QC.json')}：说明七普边际、CHFS条件参考、关联补全与设计先验。
- {link('每一步做法和支撑材料',HERE/'METHOD_AND_SUPPORT.md')}：从人口口径、成员、住房、天气、原型、几何、年度运行到演员接口。
- {link('全1000输入计划',HERE/'context_input_plan_v2/EXPERIMENT_INPUTS.json')}与{link('逐户选择锁',HERE/'context_input_plan_v2/CONTEXT_PLAN.json')}：生成事实不变，工程site与未知真实residence分开。
- {link('1000编译结果与病例目录',HERE/'population_contexts_v1/SUMMARY.json')}：每户有INPUT、STATUS和决策链；接纳户另有LAYOUT、构造来源、原型/天气匹配、独立几何、对象来源和IDF。
- {link('全部绑定和拒绝读回',HERE/'context_verification_v1/CONTEXT_BINDING_VERIFICATION.json')}与{link('当前逐户资格表',HERE/'DOWNSTREAM_QUALIFICATION.json')}：后续consumer以`current_state`为当前状态；旧人口allocation.status仅是历史元数据。

家庭与住房生成文件SHA256：`{g['candidate_sha256']}`。完整来源、代码和输出字节见本版本SOURCE_LEDGER与PACKAGE_MANIFEST，旧冻结V1仍保留。

## 245个拒绝如何解释

下表按优先级给每户一个互斥摘要；原STATUS保留全部重叠原因。

| 当前能力缺口 | 户数 |
|---|---:|
| 非普通住所，普查普通住房H6/H7不适用 | {q['exclusive_refusal_summary']['nonordinary_outside_supported_writer']} |
| 普通住宅合住，独占/共享模型尚未支持 | {q['exclusive_refusal_summary']['ordinary_shared_scope_outside_supported_writer']} |
| 其余城市单层住房，ground+roof组合尚未支持 | {q['exclusive_refusal_summary']['urban_single_storey_house_outside_supported_writer']} |
| 其余户内多层住房，垂直分区与连接尚未支持 | {q['exclusive_refusal_summary']['household_multistorey_outside_supported_writer']} |
| 现声明矩形及床位规则容量不足 | {q['exclusive_refusal_summary']['declared_rectangular_layout_capacity_failure']} |

37户容量失败的原型匹配都已eligible；这是布局能力限制，记录中的`stage_reached=template_admission`是writer调用之前的阶段标签，不能解释成源模板准入失败。非普通H6/H7不适用导致普通writer同时列出这些字段的拒绝码，不把它解释成缺失调查数据。

所有58个城市单层候选、35个跃层候选、52个非普通候选仍在原1000框架中；其中部分普通合住已在第二行优先计数。当前西藏唯一名额为跃层候选，因此没有准入IDF；其同省天气资源已经有候选。这是住房支持缺口，不能借用其他省家庭补成西藏“覆盖”。

## 本次真正修复的工程问题

之前能绕过几何检查的单墙平移，现在由独立有向边闭合、共面、法向、开口宿主与互指检查拒绝；它成为每个`idf_ready`的必经门槛。巨整数、NaN、无穷和非法JSON在写任何IDF之前形成明确整批拒绝。语义或支持不足逐户记失败并继续，不删名额。

原型使用实际源/父内容分组，300别名不再当300个独立来源；自动选择、已知特征、未知设计和跨城/年代运输都有显式、签名绑定的证据。源父材料闭包和内墙对称不可通过“允许运输”跳过。楼层位置还与已生成总层数核对，两层使用顶层实验，三层及以上才使用中间层实验。

117个年度SQL读取逐条检查温度数值、每zone的8760个唯一年度TimeIndex、完整2007非闰年日历、天气运行环境及实际生效站点；NULL、重复小时和SQL异常有真实负例。运行异常会记录failed并保留分母。静态批锁定9bdd版run_stage，年度锁定0c92运行读回加强版；{link('静态等价证明',HERE/'CORE_STATIC_EQUIVALENCE.json')}证明编译路径与IDF字节未变。

核心控制28例为13接纳/15拒绝；605验证、44准入回归、11运行异常回归均通过。原型95项检查、天气62文件和9控制均通过。这些是各自工程门槛的结果，不是人体回答、地方热工校准或全国细节代表性验证。

## 年度结果的使用边界

{link('年度选择与运行摘要',HERE/'annual_witnesses_v1/SUMMARY.json')}与{link('独立年度读回',HERE/'ANNUAL_READBACK_VERIFICATION_FINAL.json')}保留所有实际输出。当前1000资格分为245静态拒绝、638未做年度运行、76年度完成且没有warning标记、41年度完成且有warning标记。不能把最后三类统一标成已物理校准。

80是日志正则marker计数，含recurring重复摘要；引擎完成摘要合计51次warning，其中湿球试值饱和压越界42次、湿球不收敛5次、经度/民用时区差4次。{link('警告诊断与官方公式复现',HERE/'ANNUAL_WARNING_REVIEW.md')}逐案按实际EPW路径及SHA分类，9个涉及湿空气警告的EPW均已作15分钟时点公式扫描。湿球迭代/饱和压警告涉及中间湿空气计算量，不能把其-512°C等数值误当真实室温；实际输出温度范围为-19.74至39.82°C，仍有限且完整。乌鲁木齐UTC+8经度差警告按原气象元数据保留，不通过改为UTC+6消警告。下一阶段引入HVAC、潜热或舒适度前，仍需数值版本对照或明确适用范围；公式诊断不能代替热工实测校准。

现阶段为空载free-floating热工空壳：尚无人员得热、设备功率、控制权、在家日程、HVAC和计量范围。不能据此制造电费/节电问卷方案或将仿真变化当人类接受标签。{link('下游接口',HERE/'DOWNSTREAM_INTERFACE.json')}与{link('问卷benchmark合同',HERE/'BENCHMARK_CONTRACT.json')}已列明同一家庭事实、A/B初始状态、显示payload、真人原始回答、四状态采纳编码（若收集采纳）和分组分割所需记录。

## 下一步所需的实际工作

1. 在这份冻结1000框架上扩展城市单层ground+roof、户内多层及共享范围writer；容量备选布局保留原面积与自然间，不因失败重抽大房子。
2. 以城市111/112分配证据补实际居住地；当前单一省级气候暴露不能代替真实城市分布。补成员年龄/关系先验及面积联合模型的外部核验与敏感性。现模型有37个成员参考单源、516个面积参考小源池及0.198–3.159均值校准scale，均已披露。
3. 绑定人员、设备、时间、控制权、HVAC和电表范围后，再生成同状态A/B方案及演员显示卡，冻结人类任务、标签口径和actor/role/scenario/source/weather划分，进行真实认知访谈与采集。

各步骤支撑已列入METHOD_AND_SUPPORT，审查流程的Scientific Agent Skills引用亦在该文件方法引用中。`collection_release=false`、`training_release=false`。
'''
    (HERE/'README.md').write_text(text)
    save(HERE/'CURRENT.json',{'schema':'eb.household_to_idf.current.v2','static_experiment_id':s['experiment_id'],
        'annual_experiment_id':a['experiment_id'],'report':'README.md','method':'METHOD_AND_SUPPORT.md',
        'profiles_path':str(GEN/'final_v2/FAMILY_HOUSING_CANDIDATES.json'),'profiles_sha256':g['candidate_sha256'],
        'cohort_cases':1000,'family_housing_generated':1000,'static_conditional_IDFs':s['IDF_ready'],'refused_cases':s['blocked'],
        'annual_runs':a['actual_annual_runs'],'annual_engine_pass':a['passed'],'annual_cases_with_warning_markers':41,
        'raw_warning_marker_count_including_recurring_summaries':a['severity'].get('warning',0),
        'engine_completed_summary_warning_occurrences':warning['warning_counts']['completed_summary_warning_occurrences'],
        'warning_review':'ANNUAL_WARNING_REVIEW.md',
        'actual_household_city_IDFs':0,'complete_operational_roles':0,'collectable_questionnaires':0,
        'readiness':'DOWNSTREAM_QUALIFICATION.json','downstream_contract':'DOWNSTREAM_INTERFACE.json',
        'benchmark_contract':'BENCHMARK_CONTRACT.json','binding_verification':'context_verification_v1/CONTEXT_BINDING_VERIFICATION.json',
        'annual_readback':'ANNUAL_READBACK_VERIFICATION_FINAL.json','source_ledger':'SOURCE_LEDGER.json',
        'package_manifest':'PACKAGE_MANIFEST.json','package_verification':'PACKAGE_VERIFICATION.json',
        'population_city_allocation_performed':False,'national_detailed_joint_representativeness_verified':False,
        'empirical_energy_or_human_validity_verified':False,'collection_release':False,'training_release':False})
    print(json.dumps({'report':str(HERE/'README.md'),'current':str(HERE/'CURRENT.json')},ensure_ascii=False))


if __name__=='__main__':main()
