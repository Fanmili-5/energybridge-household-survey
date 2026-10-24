"""Render current evidence without inheriting historical counts or release claims.

This is a reporting adapter, not a substitute for independent acceptance or
the requirement-by-requirement completion review. Missing inputs remain open.
"""
import argparse
from collections import Counter
from pathlib import Path
from benchmark.ab_generation.common import read,save,sha


def tail_counts(rows):
    return dict(selected=len(rows),
        life_or_service_pressure=sum(bool(r['life_issues']) for r in rows),
        soft_preference_tension=sum(bool(r['soft_tension']) for r in rows),
        member_disagreement=sum(bool(r['member_disagreement']) for r in rows),
        nominal_zero=sum(abs(r['nominal_event_delta_kWh'])<=1e-8 for r in rows),
        nominal_reverse=sum(r['nominal_event_delta_kWh']< -1e-8 for r in rows),
        thermal_unknown=sum(bool(r['thermal_unknown']) for r in rows),
        answers_empty=all(r['human_fields_empty'] for r in rows),
        actual_outcomes_empty=all(r['actual_outcome_empty'] for r in rows),
        categories_overlap=True,actual_no_response_or_physical_failure_observed=False)


def cohort_summary(report,selected,expected,ledger=None):
    op=report['opportunities'];numeric=report['numeric_exploration']
    tails=tail_counts(selected)
    checks=dict(date_accounting=report['complete_date_accounting'] is True,
        declared_slots=report['expected_date_slots']==expected,
        selected_slots=len(selected)==expected,
        independent_engineering=report['engineering_check_pass'] is True,
        independent_all_candidate_causal=report['independent_all_candidate_causal_pass'] is True,
        frozen_sources=report['source_check']['passed'] is True,
        answers_empty=tails['answers_empty'],actual_outcomes_empty=tails['actual_outcomes_empty'])
    unknown_reasons=None
    if ledger is not None:
        entries=[e for day in ledger for e in day['mechanisms']]
        unknown_reasons=dict(Counter(e['reason'] for e in entries if e['status']=='unknown'))
        checks['ledger_counts_consistent']=(sum(unknown_reasons.values())==op['input_mechanism_evidence_unknown'] and
            sum(e['status']=='potential' for e in entries)==op['potential'])
    return dict(expected_slots=expected,checks=checks,engineering_checks_passed=all(checks.values()),
        mechanism_potential=op['potential'],mechanism_witnessed=op['witnessed'],
        mechanism_selected=op['selected'],mechanism_gaps=op['gaps'],
        input_evidence_unknown=op['input_mechanism_evidence_unknown'],
        unknown_input_reasons=unknown_reasons,
        known_potential_mechanisms_closed=not op['gaps'] and op['witnessed']==op['potential'],
        family_exposure=op['family_exposure'],joint_order=op['selected_joint_order'],
        semantic_repeat_excess=op['semantic_repeat_excess'],
        semantic_cells=report['semantic_coverage'],numeric_grid=numeric['by_strength'],
        checked_candidates=numeric['all_candidate_cases'],checked_components=numeric['all_candidate_components'],
        long_tails=tails,full_grid_coverage_claimed=False,behavioral_or_physical_validity_claimed=False)


def selection_summary(rows,invariance):
    names=[r['arm'] for r in rows]
    duplicates=[k for k,n in Counter(names).items() if n>1]
    return dict(arms=len(rows),duplicate_arm_names=duplicates,
        all_dates_accounted=bool(rows) and not duplicates and all(r['date_accounting_pass'] for r in rows),
        all_answers_and_outcomes_empty=bool(rows) and all(r['answer_and_actual_fields_empty'] for r in rows),
        rows=rows,invariance=invariance,
        denominator='fixed_candidate_bank;not_independent_input_opportunities_or_numeric_grid',
        inference='descriptive;no_population_or_human_effect_claim')


def run(manifest,out):
    manifest,out=Path(manifest).resolve(),Path(out).resolve()
    manifest_sha=sha(manifest)
    spec=read(manifest)
    if spec.get('schema')!='eb.research_evidence_inputs.v1':raise ValueError('UNKNOWN_EVIDENCE_INPUT_SCHEMA')
    out.mkdir(parents=True,exist_ok=False)
    pins={str(manifest):manifest_sha,str(Path(__file__).resolve()):sha(__file__)};missing=[]
    (out/'INPUT_MANIFEST.original.json').write_bytes(manifest.read_bytes())
    (out/'REPORTER_SOURCE.py').write_bytes(Path(__file__).read_bytes())
    retained={str(manifest):'INPUT_MANIFEST.original.json',str(Path(__file__).resolve()):'REPORTER_SOURCE.py'}
    if any(sha(out/name)!=pins[source] for source,name in retained.items()):
        raise ValueError('REPORT_INPUT_SNAPSHOT_MISMATCH')
    def load(name,relative):
        path=Path(relative);path=path if path.is_absolute() else manifest.parent/path
        path=path.resolve()
        if not path.is_file():
            missing.append(dict(evidence=name,path=str(path),status='not_available;not_accepted'))
            return None
        pins[str(path)]=sha(path);return read(path)
    cohorts={}
    for name,item in spec['cohorts'].items():
        report=load(name+'.acceptance',item['acceptance']);selected=load(name+'.selected_audit',item['selected_audit'])
        ledger=load(name+'.opportunity_ledger',item['opportunity_ledger']) if item.get('opportunity_ledger') else None
        if report is not None and selected is not None:
            cohorts[name]=cohort_summary(report,selected,item['expected_slots'],ledger)
    selections={}
    for name,item in spec.get('selection_studies',{}).items():
        rows=load(name+'.selection_results',item['results']);inv=load(name+'.selection_invariance',item['invariance'])
        if rows is not None and inv is not None:selections[name]=selection_summary(rows,inv)
    additional={name:load(name,path) for name,path in spec.get('additional_evidence',{}).items()}
    result=dict(schema='eb.research_evidence_report.v1',revision=spec['revision'],
        cohorts=cohorts,selection_studies=selections,additional_evidence=additional,
        missing_evidence=missing,all_manifest_inputs_available=not missing,
        automatic_goal_completion=False,report_is_not_independent_validation=True,
        engineering_tests_do_not_establish_human_validity=True,
        full_numeric_coverage_claimed=False,physical_runs_performed_by_reporter=0,
        new_candidate_or_answer_generated=False,source_pins=pins)
    lines=['# 当前生成方法证据汇总','',
        '方法版本：'+spec['revision']+'。本表直接读取所列验收文件，不继承旧版本的数字或结论。',
        '本报告不是完成门槛本身；仍需逐项检查实验范围、来源和适用边界。','',
        '| 样本 | 日期槽位 | 入选 | 独立工程及来源检查 | 潜在机制/见证/入选机制 | 输入证据不足 |',
        '|---|---:|---:|---|---|---:|']
    for name,item in spec['cohorts'].items():
        if name not in cohorts:
            lines.append(f'| {name} | {item["expected_slots"]} | 待验收 | 缺少完整证据 | 待核对 | 未知 |');continue
        c=cohorts[name];state='通过所列检查' if c['engineering_checks_passed'] else '存在未通过项'
        lines.append(f'| {name} | {c["expected_slots"]} | {c["long_tails"]["selected"]} | {state} | {c["mechanism_potential"]}/{c["mechanism_witnessed"]}/{c["mechanism_selected"]} | {c["input_evidence_unknown"]} |')
    lines+=['','潜在机制有见证不等于完整联合空间已覆盖；输入证据不足与搜索未决分别保留。',
        '生活/服务压力、软偏好、成员分歧、名义零变化、反向变化和热响应未知可以重叠。',
        '未知不是实测无响应或物理失败；本轮没有运行物理仿真。','',
        '| 样本 | 生活/服务压力 | 软偏好张力 | 成员分歧 | 名义零变化 | 名义反向 | 热响应未知 |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for name,c in cohorts.items():
        t=c['long_tails'];values=[t[k] for k in ('life_or_service_pressure','soft_preference_tension','member_disagreement','nominal_zero','nominal_reverse','thermal_unknown')]
        lines.append('| '+name+' | '+' | '.join(map(str,values))+' |')
    for name,c in cohorts.items():
        sem=c['semantic_cells'];bound=sem['selected_coverage_bounds']
        lines+=['',f'## {name}：覆盖层次','',
            f'已独立检查{c["checked_candidates"]}个候选、{c["checked_components"]}项动作。已声明潜在机制的缺额：{c["mechanism_gaps"]}。',
            '输入证据不足原因：'+(str(c['unknown_input_reasons']) if c['unknown_input_reasons'] is not None else '本报告未载入逐项账本，不作原因推断')+'。',
            f'语义单元交互共{sem["targets"]}项；已证可行{bound["known_feasible"]}项，未决/未探索{bound["unknown"]}项，入选触及{bound["selected"]}项。',
            '以下原始数值空间上界包含未证实可行的组合，不能当作已确认机会分母。','',
            '| 交互阶数 | 语法空间上界 | 已证可行 | 入选触及 | 可行性未分类 |',
            '|---|---:|---:|---:|---:|']
        for strength,n in sorted(c['numeric_grid'].items()):
            lines.append('| '+strength+' | '+' | '.join(str(n[k]) for k in ('syntactic_upper_bound','known_feasible','selected','feasibility_unclassified'))+' |')
        detail=additional.get(name+'_input_unknown_details')
        if detail is not None:
            lines+=['',f'未知项输入定位：{detail["unknown_mechanisms"]}项机制涉及{detail["unique_asset_need_dates"]}个设备/需求日期组合；逐项输入核对 passed={detail["passed"]}。',
                '原记录的具体情况：'+str(detail['mechanism_details'])+'。',
                '晚于A片段释放的需求不等于当前服务失败；事件外有控制轨迹也不等于已观测停机。原机会分类保留。']
    for name,s in selections.items():
        lines+=['',f'## {name}：同目录选题对照','',
            '这是固定候选目录内的选题指标，不是机会分母或原始数值空间覆盖率。','',
            '| 设置 | 选题数 | 日期完整 | 目录内加权覆盖 | 语义重复余量 |',
            '|---|---:|---|---:|---:|']
        for row in s['rows']:
            lines.append(f'| {row["arm"]} | {row["selected"]} | {row["date_accounting_pass"]} | {row["weighted_coverage_fraction"]:.6f} | {row["semantic_repeat_excess"]} |')
        lines.append('无关描述字段增删是否保留权重：'+str(s['invariance']['target_definitions_and_weights_equal'])+'；此结论仅适用于已声明扰动。')
    comp=additional.get('search_comparison')
    if comp is not None and comp.get('complete'):
        lines+=['','## 同域搜索对照','',
            '| 设置 | 任务数 | 设备族等总权见证比例均值 | 语义单元见证 | 未决/未探索 |',
            '|---|---:|---:|---:|---:|']
        for name,row in comp['summaries'].items():
            ratio=row['macro_family_potential_witness_ratio_mean']
            lines.append(f'| {name} | {row["runs"]} | {ratio if ratio is not None else "未定义"} | {row["semantic_cell_witnesses"]} | {row["semantic_cell_unknown_or_unexplored"]} |')
        lines.append('全部预声明种子保留，不将日期/种子视作独立家庭；计时是本机并发描述，不作隔离速度优势主张。')
    domain=additional.get('fifty_domain_expansion')
    if domain is not None:
        lines+=['','## 新旧数值动作域及账本对应','',
            f'原始整体验证结果 all_passed={domain["all_passed"]}；该结果保留，不由后续说明覆盖。',
            f'核对{domain["slots"]}个日期：旧字面动作{domain["old_literal_commands"]}项，新字面动作{domain["new_literal_commands"]}项，旧动作删除{domain["removed_old_literal_commands"]}项。']
        bridge=additional.get('fifty_domain_ledger_reconciliation')
        if bridge is not None:
            lines.append(f'独立对应说明 passed={bridge["passed"]}：{bridge["raw_key_equality_failures"]}个日期的原生账本键不同；此前已修正账本与当前声明在全部500日期一致={bridge["prior_corrected_declarations_identical_on_all500"]}。')
            lines.append('对应说明与原始失败报告分别保存。它解释历史键差异，不将扩大的数值域写成同域算法优势，也不证明全部数值空间已覆盖。')
        elif not domain['all_passed']:
            lines.append('原始检查未通过，尚缺逐项差异解释；不能视为已完成动作域与机会账本验收。')
    ac=additional.get('A_comparison')
    if ac is not None:
        lines+=['','## 同需求A对照','',
            f'CP-SAT通过{ac["CP_passed"]}/{ac["expected"]}；串行方法通过{ac["serial_passed"]}/{ac["expected"]}。',
            f'机器目标偏离总量：CP-SAT {ac["CP_deviation_min"]}分钟，串行 {ac["serial_deviation_min"]}分钟；CP-SAT证明最优{ac["CP_optimal"]}次。',
            '目标最优不是家庭行为真实性证据；不把未显示出的优势写成已有结果。']
    lines+=['','## 尚缺的证据','']
    lines+=['- '+r['evidence']+'：'+r['path'] for r in missing] or ['本清单所列文件均可读取；这不自动证明其内容满足全部科研交付要求。']
    lines+=['','完整逐项来源哈希、未决项和详细统计见EVIDENCE_REPORT.json。真人理解、画像消融与训练收益需要另行验证。','']
    if any(sha(p)!=h for p,h in pins.items()):raise ValueError('EVIDENCE_CHANGED_DURING_REPORT')
    save(out/'RETAINED_REFERENCES.json',dict(source_map=retained,sha_verified=True,
        original_manifest_resolution_base=str(manifest.parent),
        purpose='original manifest and reporter retained;do not silently resolve relative inputs against snapshot directory'))
    save(out/'EVIDENCE_REPORT.json',result);(out/'EVIDENCE_REPORT.md').write_text('\n'.join(lines))
    return dict(cohorts=len(cohorts),selection_studies=len(selections),missing=len(missing),automatic_goal_completion=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--manifest',required=True);parser.add_argument('--out',required=True)
    args=parser.parse_args();print(run(args.manifest,args.out))
