"""Short version-bound outcome report; never infer physical success or acceptance."""
import sys
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *
def main():
    a=read(A_STAGE/'CIRCULATION_REVIEW.json');b=read(OUT/'ACCEPTANCE.json');f=read(OUT/'FOUR_POINT_REVIEW.json');r=read(OUT/'RESOURCE_REGRESSION_RESULTS.json')
    if not all(x['accepted']for x in(a,b,f))or not r['passed']or f['rules_sha256']!=rules_id():raise ValueError('REVIEW_NOT_CURRENT_ACCEPTED')
    cc=f['counts'];ac=a['counts']
    examples=read(OUT/'review/四项修改前后具体案例.json')
    link=lambda cid:'['+cid.replace('ordinary-v6-','').replace('__',' / ')+'](../'+examples[cid]['path']+')'
    c3=link('ordinary-v6-0003__2025-09-28');c283=link('ordinary-v6-0283__2025-02-03');c328=link('ordinary-v6-0328__2025-01-31')
    text=f"""# A44/B45第3、4项生成验收

1000户、10000组已重生成并完成静态与生成设计复核。50户仍按5/15/16/5/4/5直接引用同批主数据。家庭、住房、设备、原十个日期保留。

| 修改 | 核验结果 |
|---|---|
| A循环风跟随真实房间活动 | {ac['AC_asset_days']}个空调资产日均为60分钟、真实有人。原18:30—19:30整段{a['old1830_to1930_asset_days']}→{a['current1830_to1930_asset_days']}，该分布只报告，不设均匀或每天不同门槛。逐日保存给定习惯、活动锚点和可解释回退。 |
| B温控跨连续许可片段 | {cc.get('thermal_adjustments_cross_original_fragments',0)}次调整跨过原数据分段；真实无许可缺口仍保留。{c3}本轮高档18:00—20:00覆盖事件60分钟，旧B只有30分钟；风机模式、原分段基础设定及2℃最小死区保留。 |
| 联合程序核对全部窗口 | {cc.get('joint_low_medium_programs_read_back',0)}次低/中档联合程序全量读回；未发现局部事件判断覆盖联合结果。{c283}、{c328}本轮均从18:40正确推迟到19:00；真实无机会仍可不调整。 |

控制片段继续拆成10分钟后，温控时段、房间、实际指令与分配前机会评分保持一致；插入真实许可缺口则不会跨越。实际返家活动推迟会带动A循环风，完全相同活动允许重复。以上是因果/表示不变性回归，不以B结果好坏筛数据。

本轮B保留{b['given_constraint_conflict_cases_kept']}组给定约束冲突、{b['no_command_change_reference_cases']}组无指令变化。联合路径仍有{f['current_known_focus_positive_other_negative'].get('joint_all_events',0)}组在已知程序/EV参考中一窗改善、另一窗恶化，均为预设反向或过度请求，照实保留；该参考不含HVAC/水箱反馈。完整热电、热水、舒适与人类接受/拒绝、评分均待测；4个原生HVAC功能探针不等于全量物理验收。旧在线问卷与答案仍保持历史绑定。

复现：`python scripts/generation_rhythm.py A|B <phase>`。A design-review含循环风独立读回，B design-review含温控连续性与全部事件联合读回。旧版本、封存、错误尝试与修复记录保留。
"""
    (OUT/'review/四项修改验收简表.md').write_text(text);print({'short_acceptance_note_written':True})
if __name__=='__main__':main()
