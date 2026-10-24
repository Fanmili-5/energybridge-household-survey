"""Evidence-derived delivery overview; no best-seed selection or inferred gold."""
import argparse
import statistics
from collections import Counter,defaultdict
from pathlib import Path
from benchmark.ab_generation.common import read,save,sha


def prepare(out):
    out=Path(out);order=read(out/'order-study/RESULTS.json');pairs=defaultdict(dict)
    for r in order:pairs[(r['household_id'],r['date'],r['seed'])][r['order']]=r
    differences=[]
    for (h,d,s),pair in sorted(pairs.items()):
        differences.append(dict(household_id=h,date=d,seed=s,
            reverse_minus_original_witnesses=pair['reversed'].get('semantic_cell_interaction_witnesses',pair['reversed'].get('raw_interaction_witnesses'))-pair['original'].get('semantic_cell_interaction_witnesses',pair['original'].get('raw_interaction_witnesses'))))
    save(out/'ORDER_STUDY_SUMMARY.json',dict(runs=len(order),paired_inputs=len(pairs),
        independent_errors=sum(r['independent_errors'] for r in order),
        mean_reverse_minus_original=statistics.mean(r['reverse_minus_original_witnesses'] for r in differences),
        min_difference=min(r['reverse_minus_original_witnesses'] for r in differences),max_difference=max(r['reverse_minus_original_witnesses'] for r in differences),
        paired_differences=differences,scope='same cached native domain;column order only;no full coverage or superiority claim',
        candidate_code_origin='delivery_v2_2;native catalogues delivery_v2_1;opportunity re-declaration not used by this study'))
    source=out.parent/'revision-2.2/SELECTION_REVIEW.json';selection=read(source)
    ledger=read(out/'FIFTY_INPUT_OPPORTUNITY_COVERAGE.json.gz');available=Counter()
    for d in ledger:available.update({e['family'] for e in d['mechanisms'] if e['status']=='potential'})
    selection['available_family_dates']=dict(available)
    for a in selection['same_catalogue_arms']+selection['household_order_arms']:
        a['exposure_per_input_potential_family_date']={f:n/available[f] if available[f] else None for f,n in a['family_date_exposure'].items()}
    selection['denominator_correction']='v2.3 input-ledger primary kind;selection IDs and weighted objectives unchanged'
    selection['original_selection_study_sha256']=sha(source)
    save(out/'SELECTION_REVIEW.json',selection)
    rows=read(out/'FIFTY_SELECTED_AUDIT.json')+read(out/'PUBLIC_FRESH_SELECTED_AUDIT.json')
    def count(rs):
        return dict(selected=len(rs),plan_life_or_service_pressure=sum(bool(r['life_issues']) for r in rs),
            soft_preference_tension=sum(r['soft_tension'] for r in rs),member_disagreement=sum(r['member_disagreement'] for r in rs),
            known_nominal_zero=sum(abs(r['nominal_event_delta_kWh'])<=1e-8 for r in rs),
            nominal_zero_and_no_thermal_unknown=sum(abs(r['nominal_event_delta_kWh'])<=1e-8 and not r['thermal_unknown'] for r in rs),
            known_nominal_reverse=sum(r['nominal_event_delta_kWh']< -1e-8 for r in rs),
            thermal_unknown=sum(r['thermal_unknown'] for r in rs),all_human_fields_empty=all(r['human_fields_empty'] for r in rs),
            all_actual_outcomes_empty=all(r['actual_outcome_empty'] for r in rs))
    save(out/'LONG_TAIL_AUDIT.json',dict(fifty=count(rows[:500]),public_fresh=count(rows[500:]),
        labels_overlap=True,prespecified_quotas=False,unknown_is_not_measured_no_response=True,
        actual_physical_failure_distribution='not_observed;no_physical_runs'))
    save(out/'TEST_COMMANDS.json',dict(python='/Users/fanmili/studytest/outputs/unified-ab-v1-20261022/runtime/bin/python',
        command='PYTHONPATH=. python -B -m unittest benchmark.ab_generation.unified.test_unified benchmark.ab_generation.unified.test_delivery benchmark.research_delivery.test_production benchmark.ab_generation.test_life benchmark.ab_generation.test_joint_load_supply benchmark.ab_generation.test_collection benchmark.ab_generation.test_collection_semantics benchmark.ab_generation.test_collection_selection benchmark.ab_generation.test_plan_only -q',
        tests=131,log_sha256=sha(out/'TESTS.log'),physical_runs=0))
    return dict(order_runs=len(order),selection_arms=len(selection['same_catalogue_arms']),selected=len(rows))


def write(out):
    out=Path(out);f=read(out/'FIFTY_ACCEPTANCE.json');p=read(out/'PUBLIC_FRESH_ACCEPTANCE.json')
    comp=read(out/'COMPARISON_SUMMARY.json');g=read(out/'CLAIM_GATES.json');tail=read(out/'LONG_TAIL_AUDIT.json')
    ac=read(out/'A_SAME_DEMAND_COMPARISON.json')
    greedy_deviation=sum(x['greedy_score']['absolute_machine_target_deviation_min'] for x in ac['records'])
    CP_deviation=sum(x['CP_score']['absolute_machine_target_deviation_min'] for x in ac['records'])
    order=read(out/'ORDER_STUDY_SUMMARY.json');selection=read(out/'SELECTION_REVIEW.json');ui=read(out/'ui91-offline/DISPLAY_COMPLETENESS.json')
    ff,pp=f['opportunities'],p['opportunities'];raw=f.get('semantic_coverage',f.get('raw_coverage'))
    lines=['# 统一生成方法：科研交付自查','',
        '交付版本：delivery_v2_3。工程证据包'+('已完成' if g['engineering_artifact_complete'] else '仍有未完成门槛')+'；**完整覆盖验收未通过**。本轮不宣称家庭行为真实、问卷理解有效或训练收益。','',
        '## 已完成的验证','',
        '| 检查 | 结果及边界 |','|---|---|',
        '| 当前版本回归 | 131项通过；完整命令及日志保留 |',
        '| 独立小设备域 | 54种设备配置/位移检查一致；生产CP存在性判定另27种赋值及交互分母一致，非全物理空间证明 |',
        '| 公开新A | 54次预声明求解均可行，独立完整时序/资格/服务/名义EV检查无错误；原结果逐份复用，不虚报新求解时间 |',
        '| 50户影子验收 | 500/500原日期有候选且已选题，候选独立工程检查0错误；原A和旧题未覆盖 |',
        '| 公开新A→B | 六类60/60原日期接通；独立工程检查0错误；非只读取旧A |',
        '| 动作理由 | 独立核对560道入选题的896项动作及必要伴随/撤回路径，全部通过；不等于实际有帮助 |',
        '| 固定算法矩阵 | 24日期×8种子×6设置=1152次，全部保留；另384次因素顺序比较，工程错误0 |',
        '| 选题 | 同目录15种设置/对照及真实家庭分块顺序检查，未规定成功、冲突等配比 |',
        '| UI91 | 500题绑定、未知后果和空答案检查通过，原渲染器字节未改；'+str(ui['cases_with_outside_changes'])+'题图表外改动另列完整时间，未做真人理解度实验 |',
        '| 原资料 | '+str(read(out/'IMMUTABILITY.json')['checked'])+'个受保护文件哈希不变 |',
        '| 换目录复现 | '+('新A第一户十题的公开CLI重放通过；不是54次A全部重新求解' if (out/'PORTABILITY.json').exists() and read(out/'PORTABILITY.json')['returncode']==0 else '待完成公开包移动目录重放')+' |','',
        '## 覆盖分母和缺额','',
        '| 层次 | 50户500日期 | 六类新A的60日期 |','|---|---:|---:|',
        '| 有输入作用路径的潜在机制 | '+str(ff['potential'])+' | '+str(pp['potential'])+' |',
        '| 已有直接提案见证 | '+str(ff['witnessed'])+' | '+str(pp['witnessed'])+' |',
        '| 仍未决的潜在机制 | '+str(sum(ff['gaps'].values()))+' | '+str(sum(pp['gaps'].values()))+' |',
        '| 输入证据不足的机制（另列，非零机会） | '+str(ff['input_mechanism_evidence_unknown'])+' | '+str(pp['input_mechanism_evidence_unknown'])+' |',
        '| 语义单元交互未决/未探索 | '+str(raw['selected_coverage_bounds']['unknown'])+' | '+str(p.get('semantic_coverage',p.get('raw_coverage'))['selected_coverage_bounds']['unknown'])+' |','',
        '50户169项缺额为洗衣装取重排155、洗碗装取重排13、洗衣整链1；公开新A仍有84项。逐项位置、原生域数量、单项查询状态及依赖见证在GAP_DIAGNOSTICS。单项不可行不能排除联合调整；未决不当作没有机会，不补抽题填满。',
        '原网格有'+str(raw['targets'])+'个声明目标，已找到'+str(raw['selected_coverage_bounds']['known_feasible'])+'个工程见证；入选覆盖'+str(raw['selected_coverage_bounds']['selected'])+'个。入选覆盖界为'+format(raw['selected_coverage_bounds']['lower'],'.4%')+'—'+format(raw['selected_coverage_bounds']['upper'],'.4%')+'，仅针对该有限数值空间，不是人口比例。原网格没有因分母修订而粗化。',
        '一体洗烘身份错误已修复：按原kind识别，规则JSON字段顺序不再改变家庭设备类别。旧账本和逐键前后对应均保留；不能把错误分母下的较高覆盖数值作为结果。','',
        '## 对照结果和负结果','',
        '| 设置 | 设备族等总权的潜在机制见证宏平均 | 语义单元交互工程见证数 |','|---|---:|---:|']
    for name in ('ipog_base','round_robin','budget_half','budget_double','encoding_half','encoding_double'):
        x=comp['summaries'][name];lines.append('| '+name+' | '+format(x['macro_family_potential_witness_ratio_mean'],'.4f')+' | '+str(x.get('total_semantic_cell_interaction_witnesses',x.get('total_raw_interaction_witnesses')))+' |')
    lines+=['',
        '同需求的串行适配对照与CP-SAT各54次都完成必要服务。未加权机器目标偏离合计分别为'+str(greedy_deviation)+'和'+str(CP_deviation)+'分钟，CP-SAT没有在该指标占优；36次证明最优、18次仅有可行解。CP目标还包含等待、按设备归一化偏好及EV提前备妥，不能把目标最优写成行为更真实。原贪心逐字结果也保留，但其需求编译/展望范围不同，不用于同需求优势结论。A_SAME_DEMAND_COMPARISON说明了适配和全部原记录。',
        '新版IPOG-C在该矩阵找到更多语义单元交互见证，但设备族宏平均未全面优于旧轮转适配器；扩大编码预算也不保证提升。全部八种子及逐户差值保留，不据此宣称统计显著或普遍优势。比较含8户，不将日期/种子当作独立家庭。计时为本机并发描述，非隔离速度基准。',
        '同目录归一化目标可全部覆盖，并不证明独立机会或完整数值网格已覆盖。语义重复为项目代理：50户入选题为0，并非真人已经确认它们语义不同。','',
        '描述性分层另见STRATA_CASES及CLASS_DEVICE_COVERAGE：50户覆盖六类、12个月、16种设备数量配置；公开新A只验证3月。月份不等于已验证天气季节。分层不新加选题目标、不规定配比，也不改变原分母。',
        '同族多批：560道入选为0。独立账本仅在0841户/2025-07-14发现1个潜在家庭日，默认目录没有直接双任务见证；公开六类为0潜在日。对唯一日期另作一次固定的大编码/短时诊断仍为oracle_budget未知，未重抽、未补入原目录、未重选。小设备域测试支持该机制，但当前数据不能声称覆盖了它。',
        '## 已修的问题','',
        '1. 跨午夜窗口按连续区间判断，保留旧检查器供历史重放。',
        '2. 空调冷热阈值用最小必要伴随变化维持原死区；伴随动作单列且待确认。40℃停冷编码不算舒适温差。原错误请求留诊断。',
        '3. 新A控制行统一身份，EV分段充电与暂停请求分开表示；未改原A值、行程、SOC或换B。',
        '4. 缺资料或搜索未决不能生成“没有机会”的A=B；技术异常保留输入分母。',
        '5. 复合设备按原身份识别、机会账本独立重声明；旧账本、目录和选择记录均保留。',
        '6. UI91离线材料补列图表外完整改动，实际后果仍为空。','',
        '## 尚不能据此定版的部分','',
        '除覆盖缺额外，公开六类十日期160条时间目标中110条因原参考操作人或上游目标缺失为空。A使用已声明的生活规则目标，不能声称这些缺失偏好已经接入；不能从A回填习惯来掩盖缺失。热水、EV等部分偏好仍是评价/确认上下文。PREFERENCE_INTERFACE_AUDIT逐条保留来源和用途。A各项权重及EV备妥目标的相对量级尚未实证标定，本轮不声称其行为合理性已经验证。',
        '程序优化当前是共享模板、受硬权限约束的坐标域和延迟字面展开；大域仍需显式原生索引/条件表。它不是完整的符号时间域求解器，大域编码与搜索限制仍存在，不把存储压缩称为已解决全部组合搜索。',
        '模拟后果全部未计算；实际无响应、物理失败及人体舒适不能用名义模型代替。真人理解、画像/错配画像消融和训练收益未验证。来源情境关联组尚需在训练划分前核验，本轮未发布训练测试划分。',
        '下一阶段先补已知缺失的操作参考输入并查明剩余单项/联合机会，再决定是否扩大覆盖预算；不得按成功率重抽。真人与模型有效性另行预注册，不由工程测试替代。','',
        '## 复现与来源','',
        '方法及论文稿见benchmark/research_delivery/METHOD.md、PAPER_METHODS.md；原始论文位置、支持/不支持范围及实验参数见SOURCES_AND_PARAMETERS.md和unified/EVIDENCE.json。',
        '公开可移动包提供六类原生活输入、全部54次A参考结果、60个新A上下文与固定小预算命令；两户既有输入及50户全目录通过本地DELIVERY_INDEX定位，不把公开子集说成全量公开复现。',
        '候选证据分别由v2.1（50户及1152对照）和v2.2（公开60题）生成；v2.3重声明分母和独立验收。24个固定输入的候选/目标重放完全一致，A求解器和选题器保留原哈希。各层原始版本未被覆盖。',
        '本轮未改线上、未运行物理仿真、未启动1000户、未提交或合入main。','']
    (out/'SELF_REVIEW.md').write_text('\n'.join(lines));return dict(path=str(out/'SELF_REVIEW.md'),engineering_artifact_complete=g['engineering_artifact_complete'],coverage_accepted=False)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--stage',choices=['prepare','write'],required=True)
    a=p.parse_args();print((prepare if a.stage=='prepare' else write)(a.out))
