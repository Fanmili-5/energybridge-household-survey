"""Short outcome note from accepted, version-matched reports and actual cases."""
import sys
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *
def main():
    a=read(A_STAGE/'ACCEPTANCE.json');b=read(OUT/'ACCEPTANCE.json');d=read(OUT/'DESIGN_REVIEW.json');f=read(OUT/'FOUR_POINT_REVIEW.json')
    if not all(x['accepted']for x in(a,b,d,f))or f['rules_sha256']!=rules_id():raise ValueError('NOT_ACCEPTED_VERSION')
    samples=read(OUT/'review/四项修改前后具体案例.json');mk=lambda cid:'['+cid.replace('ordinary-v6-','').replace('__',' / ')+'](../'+samples[cid]['path']+')'
    text=f'''# A42/B43四项修改验收

1000户、10000组已重生成，生成、排程与设计复核通过。主数据仍为V33，家庭、住房、设备及十个日期不改。50户按5/15/16/5/4/5直接引用同批文件。

| 修改 | 实际结果与案例 |
|---|---|
| A保护出行后安排午餐 | 1,148组返程恢复；全年396,000天核对通过。{mk('ordinary-v6-0001__2025-03-15')}：11:40午餐、12:10返程、12:30回家。 |
| B按已有设备与未来指令分配机制 | 不可用机制回退615→{b['mechanism_fallback_count']}组；程序预约1593→{b['mechanisms']['program_timer']}组。0001户不再先分配缺失的热水器。 |
| 空调取消日最高温模式猜测 | {mk('ordinary-v6-0251__2025-09-25')}：增负荷时制热+0.75℃、制冷−0.75℃；保留2℃死区。全量实际控制边界读回未发现方向或间隔错误。功率/舒适仍未知。 |
| 多事件增加联合生成路径 | 联合考虑全部窗口{f['counts']['joint_all_events']}组；单窗口压力{f['counts']['single_event_stress']}组。{mk('ordinary-v6-0369__2025-12-01')}保留中午充电，低档B未额外响应，结果照实保留。 |

合理稳定习惯与所有已配设备每日使用保留。A的设备指令在10,000组均与A40一致：本轮修正的是午餐覆盖返程的日程错误，没有为制造差异挪动设备时间。B保留{b['given_constraint_conflict_cases_kept']}组给定约束冲突、{b['no_command_change_reference_cases']}组无指令变化；接受/拒绝和评分仍为空。

联合路径仍有{f['current_known_focus_positive_other_negative'].get('joint_all_events',0)}组在已知程序/EV参考中出现“焦点窗口改善、另一个窗口恶化”，其中{f['current_known_focus_positive_other_negative'].get('joint_all_events_explicit_adverse_variant',0)}组为预设的明确反向或过度请求，作为长尾保留。低/中档联合路径此类参考冲突{f['current_known_focus_positive_other_negative'].get('joint_all_events_low',0)+f['current_known_focus_positive_other_negative'].get('joint_all_events_medium',0)}组。该参考不能代表HVAC、水箱或全屋实际响应。

4个新A HVAC功能探针已完成；围护层次、额定曲线和低温制冷警告仍需后续物理复核。本轮通过的是生成与静态设计验收，全量A/B物理、热水、舒适和新问卷尚未验收。旧线上问卷、物理与答案保持原绑定。

复现入口：`python scripts/generation_joint.py A|B <phase>`；B design-review会同时执行四项全量读回。阶段代码、数据绑定、规则、失败尝试及修复记录均保留，先封存匹配A/B，再发布本地指针。
'''
    (OUT/'review/四项修改验收简表.md').write_text(text)
    print({'short_acceptance_note_written':True})
if __name__=='__main__':main()
