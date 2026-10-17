"""Concise, version-bound reviewer readback; no full-physics acceptance claim."""
import sys
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *
def main():
    a=read(OUT/'ACCEPTANCE.json');r=read(OUT/'COMMAND_AND_VPP_REVIEW.json');t=read(OUT/'THERMAL_FLEX_REVIEW.json');g=read(OUT/'COMMAND_REGRESSION.json');samples=read(OUT/'review/实际指令与多窗口案例.json')
    if not all([a['accepted'],r['accepted'],t['accepted'],g['passed']])or any(z['rules_sha256']!=rules_id()for z in [a,r,t,g]):raise ValueError('UNMATCHED_REVIEW')
    c=r['counts'];shapes=r['multi_window_factor_counts']
    lines=['# A46/B48：实际指令与多窗口VPP验收','','A46、1000户家庭/住房/设备、原10000日期与每日需求保持。重生成B48；50户按5/15/16/5/4/5直接引用同批文件。','',
           '| 修改 | 全量复核结果 |','|---|---|',
           f"| 实际差异与强度 | 独立逐10分钟读回10000组及{c['dose_candidates_independently_read_back']}个四档候选；无指令变化{c['no_command_change_cases']}组，四档全等于A共{c.get('all_four_doses_equal_A_cases',0)}组。标签、等价档位、实际跨设备组合和11371个事件时序均与执行指令一致。 |",
           f"| 提前温控 | {c['actual_preconditioning_requests']}次准备阶段有真实指令变化；{c.get('unchanged_preparation_requests_kept',0)}次准备阶段没有变化，明确保留且不计实际覆盖。真实提前温控涉及{c['actual_preconditioning_cases']}组；不据此声称实际电量或热储能增加。 |",
           f"| VPP多窗口 | {c['multi_event_cases']}组双事件：同向同目标{shapes['same+equal']}、同向不同目标{shapes['same+unequal']}、异向同目标{shapes['mixed+equal']}、异向不同目标{shapes['mixed+unequal']}。窗口/通知及单窗口原方向和目标保留；站点日期相同的请求完全相同。 |",'',
           '旧问题使用原B47的VPP和分配作为固定输入回归：原13组虚假差异的四档均正确识别为A，原41次零变化准备阶段均正确标注。不会为补差异追加温差、开机或EV插拔。','',
           '| 新版实际案例 | 请求或处理 |','|---|---|']
    for name in ['true_noop','zero_preparation','multi_same_equal','multi_same_unequal','multi_mixed_equal','multi_mixed_unequal']:
        x=samples[name];detail='按实际指令标为无变化'if name=='true_noop'else'准备阶段明确未改变；事件阶段单独记录'if name=='zero_preparation'else'；'.join(f"{e['start_min']//60:02d}:{e['start_min']%60:02d}—{e['end_min']//60:02d}:{e['end_min']%60:02d} {e['direction']} {e['target_kw']}kW"for e in x['events'])
        lines.append(f"| [{x['case_id']}](../{x['path']}) | {detail} |")
    lines += ['',f"B保留{a['given_constraint_conflict_cases_kept']}组给定约束冲突；不按B达标、优于A或演员答案筛选。VPP组合是外生覆盖设定，不是电网实测分布。合理稳定习惯和A所有已配电器每日使用继续保留。",'',
              '本轮通过的是生成输入、实际指令、排程、覆盖和版本一致性。实际物理响应、连续B电量、热水、舒适及人类接受仍待验收。新问卷未发布，历史结果不改绑。', '',
              '复现入口：`python scripts/generation_commands.py B <phase>`；顺序见本阶段METHODS.md。预演、回归诊断、旧版本和源码保留。']
    (OUT/'review/实际指令与多窗口验收.md').write_text('\n'.join(lines)+'\n');(OUT/'review/本轮修改简明说明.md').write_text('\n'.join(lines)+'\n');print({'acceptance_note_written':True})
if __name__=='__main__':main()
