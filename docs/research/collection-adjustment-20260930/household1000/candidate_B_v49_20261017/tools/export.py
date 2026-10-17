"""Export three-axis annotations, unchanged controls and a concise acceptance note."""
import sys,csv
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *
def main():
    report=read(OUT/'ACCEPTANCE.json')
    if not report['accepted']or report['rules_sha256']!=rules_id():raise ValueError('CLASSIFICATION_NOT_ACCEPTED')
    fields=['家庭ID','日期','类别','比较组','设计不利分支被选中','实际改变设备','实际指令档位','VPP逐事件指令或程序参考方向','逐事件已知程序响应参考kW','给定约束冲突','冲突原因','无变化原因','物理及接受状态','新文件','SHA256','原B48文件'];records=read(OUT/'PAIR_BINDINGS10000.json')['records']
    with (OUT/'review/10000组分类核对表.csv').open('w',encoding='utf-8-sig',newline='')as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        for row in records:
            for rr in row['rounds']:
                p=read(OUT/rr['path']);cl=p['classification'];a=cl['actual_actions'];cf=cl['constraint_failure'];events=a['events']
                values=[p['household_id'],p['date'],row['type'],a['comparison_group'],cl['design_intent']['unfavourable_variant_selected'],'+'.join(a['changed_device_families']),a['actual_command_intensity'],';'.join(e['event_id']+':'+e['requested_direction']+'→'+e['component_direction_summary']+'/'+e['component_request_relation']for e in events),';'.join(str(round(e['known_program_response_reference_kw'],6))for e in events),cf['has_given_constraint_conflict'],';'.join(sorted({f['code']for f in cf['flags']})),';'.join(x['basis']for x in a['no_change_reasons']),'全屋物理响应、真实执行、接受及评分待测',rr['path'],rr['sha256'],p['source_B']['case_path']]
                writer.writerow(dict(zip(fields,values)))
    counts=report['counts'];examples=read(OUT/'review/分类实际案例.json')
    lines=['# A46/B49：B分类更新验收','','本轮以原1000户、10000组A46/B48为基础，只更新分类及版本。逐案核对A、B排程、家庭/日程/每日需求、VPP、仿真参考和答案字段，均保持。50户按5/15/16/5/4/5直接引用本批主数据。','',
           '| 维度 | 含义 |','|---|---|','| 设计意图 | 保存所选机制、档位及不利设计分支来源；不是实际反向、失败或拒绝结论。 |','| 实际动作 | 从A/B原指令推导程序/人工操作提前或推迟、控制许可/设定变化和逐事件方向；控制方向不等于已测功率。 |','| 约束冲突 | 原给定资源/服务检查的冲突完整保留；不等于人类拒绝或全量物理失败。 |','',
           f"全量{counts['cases']}组通过独立读回，排程改动0。实际改变指令{counts['changed_commands_cases']}组，无变化{counts['identical_commands_cases']}组；约束冲突{counts['constraint_conflict_cases']}组。原13组程序类无变化但被标不利的案例已全部更正：保留设计意图，实际为无变化且无约束冲突。",'',
           '**500组无变化，占原10000组的5%。本轮遵守保留现有排程的要求，数量保持500。已另出NO_COMMAND_CHANGE_CASES.json，9500组改变指令另列CHANGED_COMMAND_CASES.json；没有删除、改成有变化或擅自决定后续评分是否纳入。无变化不再混入反向/失败统计。**','',
           '| 案例 | 新分类 |','|---|---|']
    descriptions={'ordinary-v6-0244__2025-10-21':'设计选中过不利分支；实际洗碗/装取均未变；无约束冲突。','ordinary-v6-0619__2025-11-18':'设计选中过不利分支；晚间洗烘已知程序参考顺向削减0.5kW，午间没有变化；无约束冲突。不是全屋实测或接受结论。','ordinary-v6-0010__2025-12-19':'实际撤回空调许可的方向逐事件记录；在增负荷事件中属于相反的控制请求，实际耗电及人类态度仍未知。','ordinary-v6-0001__2025-10-12':'原EV等给定约束冲突保留，独立于设计意图及动作方向。'}
    for case,desc in descriptions.items():lines.append(f"| [{case}](../{examples[case]['path']}) | {desc} |")
    lines += ['', '原explicit_adverse_request及程序/温控分支“坏标签”已从活动proposal字段移出；来源标记只保留在classification.design_intent和封存B48中。不能再用分支名作为真实坏方案或拒绝标签。','',
              'B48封存的40000候选及指令验收证据继续按哈希引用，本轮没有重选或重生成排程。A46所有已配电器每日使用、合理稳定习惯和已有B失败均保留。','',
              '全量物理、连续B状态、热水、舒适和人类评分仍待验证；本轮没有写入此类新结果。旧问卷及答案保持历史绑定。', '',
              '复现：python scripts/generation_classification.py B regressions → build → review → export → seal → publish → verify-pointers。publish内先执行全量封存和来源文件哈希验证。']
    (OUT/'review/B分类更新验收.md').write_text('\n'.join(lines)+'\n')
    save(OUT/'REVIEW_EXPORT_MANIFEST.json',{'files':{rel(p):sha(p)for p in(OUT/'review').iterdir()if p.is_file()},'scope':'three-axis classification and preservation,not physical/human acceptance'})
    print({'exported_cases':10000,'no_change_index':500,'changed_index':9500})
if __name__=='__main__':main()
