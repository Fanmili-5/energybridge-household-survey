"""Concise version-bound acceptance note with actual full-data examples."""
import sys
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *
def main():
    a=read(A_STAGE/'THERMAL_CONTEXT_REVIEW.json');b=read(OUT/'ACCEPTANCE.json');f=read(OUT/'THERMAL_FLEX_REVIEW.json');r=read(OUT/'THERMAL_FLEX_REGRESSION.json');samples=read(OUT/'review/三项修正实际案例.json')
    if not all(z['accepted']for z in(a,b,f))or not r['passed']or f['rules_sha256']!=rules_id():raise ValueError('NOT_MATCHED_ACCEPTANCE')
    link=lambda k:'['+samples[k]['case_id'].replace('ordinary-v6-','').replace('__',' / ')+'](../'+samples[k]['path']+')'
    ac=a['counts'];bc=f['counts']
    text=f"""# A46/B47第3、4项三处修改验收

1000户、10000组已重生成，50户按原5/15/16/5/4/5引用同批主数据。家庭、住房、设备、成员活动、原日期及其他电器A安排保持一致；所有已配电器每日使用。

| 修改 | 全量核验与案例 |
|---|---|
| A短离房保持温控 | {ac['justified_closed_gaps']}个符合条件的短离房缺口保持温控，共{ac['held_minutes']}分钟。0001/03-15的19:40—19:50洗澡期间不再停机。必须同一成员返回、期间仍在家、间隔不超过给定20分钟；真实长外出保留。每日60分钟循环风仍只取实际有人时隙。 |
| 反向暂停如实标记 | {bc['up_pause_cases_explicitly_adverse']}组、{bc.get('up_pause_actions_explicitly_adverse',0)}次增负荷事件中的暂停明确标为down动作与预设反向请求。例{link('up_pause_kept')}；坏方案保留，不声称实际kW。 |
| 提前温控独立于A开机窗口 | {bc['preconditioning_cases']}组含提前温控请求，其中{bc['up_cases_with_permission_beyond_A']}组增负荷候选实际新增A窗口外许可。例{link('up_before_return')}。由真实后续房间使用、独立硬件范围和最多提前120分钟支持，需用户同意，不新增人在场或EV操作。 |

低档提前量与事件不重叠时如实保留A，不补造开机动作。控制指令分段、全部VPP窗口、现有洗烘依赖、同一操作人及50户同源均完成读回。B保留{b['given_constraint_conflict_cases_kept']}组约束冲突、{b['no_command_change_reference_cases']}组无指令变化，不按B优于A或演员答案筛选。

20分钟短离房阈值、20/40/60/120分钟提前量是明确实验设定，不是人口调查或实测偏好。接受/拒绝、评分、实际响应与舒适结果仍为空。4个A及2个新B HVAC功能探针不等于全量A/B物理验收；原生围护层次、额定曲线和低温制冷警告仍待后续物理复核。

复现入口：`python scripts/generation_thermal.py A|B <phase>`；旧版本与入口、生成源码、数据绑定、预演及失败记录均保留。当前本地指针只在匹配A/B封存和全量哈希验证后更新，旧线上问卷与答案保持历史绑定。
"""
    (OUT/'review/四项修改验收简表.md').write_text(text);print({'short_acceptance_note_written':True})
if __name__=='__main__':main()
