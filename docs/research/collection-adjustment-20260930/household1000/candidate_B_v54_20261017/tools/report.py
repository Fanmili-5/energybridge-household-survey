"""Human-readable generation-design readback using current full-population evidence."""
import sys,collections
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *
def main():
    a=read(OUT/'ACCEPTANCE.json');d=read(OUT/'DESIGN_REVIEW.json');r=read(OUT/'REGRESSION_RESULTS.json');t=read(OUT/'THERMAL_EVENT_VALIDATION.json');s=read(OUT/'STATE_BINDINGS.json');sig=rules_id()
    assert a['accepted']and d['passed']and r['passed']and t['passed']and s['passed']and s['cases']==10000
    assert a['rules_sha256']==d['rules_sha256']==r['rules_sha256']==t['rules_sha256']==sig
    c=d['counts'];ac=a['counts'];ex=read(OUT/'review/四项修改案例.json')
    def actual(case,fam):return next(x for x in ex[case]['actual']if x['device_family']==fam)
    longdelay=ex.get('EV_large_delay_example');ev=longdelay['actual']if longdelay else actual('ordinary-v6-0001__2025-03-22','ev');evcase=longdelay['case_id']if longdelay else 'ordinary-v6-0001__2025-03-22';dish=next(x for x in ex['ordinary-v6-0048__2025-04-02']['requests']if x['device_family']=='dishwasher')
    ac6=[x for x in ex['ordinary-v6-0006__2025-06-16']['requests']if x['device_family']=='ac'];native_modes=[{'asset':x['asset_ids'][0],'event':x['input_state_plan']['event']['event_id'],'mode':x['input_state_plan']['event']['native_A_event_state']['mode'],'axis':x['input_state_plan']['thermal_axis_reference'],'active_min':x['input_state_plan']['event']['native_A_event_state']['active_minutes']}for x in ac6]
    rows=read(OUT/'PAIR_BINDINGS10000.json')['records'];tr=next(x for x in next(x for x in rows if x['household_id']=='ordinary-v6-0019')['rounds']if x['date']=='2025-09-03');tail=read(OUT/tr['path']);er=next(x for x in tail['proposal']['requested_device_strengths']if x['device_family']=='ev');eo=next(x for x in tail['proposal']['actual_device_strengths']if x['device_family']=='ev');event=next(x for x in tail['classification']['actual_actions']['events']if x['event_id']==er['input_state_plan']['event']['event_id']);eref=next(x for x in event['EV_event_state_reference']['devices']if x['asset_id']in er['asset_ids']);thermal_rel=collections.Counter()
    for result in t['records']:
        pair=read(OUT/result['pair_path']);selected={(aid,x['input_state_plan']['event']['event_id'])for x in pair['proposal']['requested_device_strengths']if x['device_family']in('ac','water_heater')for aid in x['asset_ids']}
        for x in result['native_event_readbacks']:
            if(x['asset_id'],x['event_id'])in selected:thermal_rel[x['native_response_relation']]+=1
    text=f'''# A46/B54：第3、4项修改与再复核

本轮保留A46，修改B生成逻辑并重生成1000户、整批10000组。原100组相同请求的身份和B载荷保持，50户按原5/15/16/5/4/5引用同批主文件。家庭背景、设备、生活日程、每日服务需求、任务/人工操作身份、EV插拔和目标SOC均未更换。没有预填接受或评分；{ac['constraint_conflict_cases']}组给定约束冲突全部保留。

## 1. VPP机会与机械移时

程序机会先检查释放、装载、操作者/房间窗口、完整洗烘链、可取出时间和截止；使用固定程序功率加权后的事件电量变化。洗衣和烘干不能只比分钟数。输入剂量可行时按选定事件目标找最小充分移动，达不到时保留有限贡献。

0048户2025-04-02的洗碗，餐具19:30才释放，18–19点上调机会现为0，未再宣称有60分钟机会。该设备当前请求类型为`{dish['input_state_plan']['behavior']}`；服务边界调整与有效VPP响应分开记录。

0017户2025-08-21的EV，若A在17点已充完，18–19点没有可下调的充电负荷，普通路径不会再把充电机械推入该下调事件。许可改变与固定充电事件参考均从实际新指令读回；有限机会、无效和反向请求仍保留。

另外修复0019户2025-09-03的充电尾段：A许可{eo['EV_window_metrics'][0]['A_window_min']}，B许可{eo['EV_window_metrics'][0]['B_window_min']}；选定下调事件的固定充电功率差为{eref['power_delta_kw']:.3f}kW。普通EV按保留原目标电量的可行计时位置选时，服务窗口压力另列；整批普通EV选定事件参考为{d['normal_or_partial_EV_selected_event_reference_relations']}。原125条普通逆向移时通过修改实际指令修复，未删除案例或改标签掩盖。

整批程序请求的实际生成依据计数为：{ {k:v for k,v in c.items()if k.startswith('program_basis:')} }。这是输入层的机会和请求依据，没有宣称这些个体可行动作在组合后必然同时可行。

## 2. 实际强度以多轴展示

程序移时与装取移时、EV窗口比例/延迟/目标电量缺口、热控温差/持续时长全部并列。没有整体实际强度档位；历史主轴字段仅保留兼容核算，退出展示与覆盖统计。整批每个展示轴已从原始指令重算核对。

{evcase}的EV，当前实际各轴为：{ev['actual_strength_axes']}。窗口比例小与长时间延迟会同时出现，不能概括成低强度。整批延迟不少于120分钟的EV请求为{c.get('EV_long_delay_120min_or_more',0)}条。

本地`多轴强度预览.html`可检索整批10000组，展示这些数值及A/B起止或温控差异；它不是已发布问卷，也不把技术分档当作用户负担或接受标签。

## 3. EV失败形成路径

实际请求路径数量为：{d['EV_path_request_counts']}；其中固定功率目标电量不足的请求数量为：{d['EV_path_shortfall_counts']}。每条记录连接原始接入、所需电量、事件/出发/计时边界、B许可和实际缺口；失败不再只出自同一种限时预算。

额外修复0224户2025-12-29的边界错误：事件18–19点结束、19:20才接入，不能把过期截止夹成接入后的10分钟窗口。现采用已声明的出发前预算回退，并单独记录有效路径、充电截止、既有拔下区间和真实出发时间。

整批{c.get('EV_energy_bound_shortfall_requests',0)}条目标电量不足请求均保留。目标SOC不足、给定下一次出行/余量约束、组合约束冲突和人类拒绝继续分开。共享EB电量和10分钟网格造成的重复数值没有人为打散；没有设定失败比例。

## 4. 热控事件内状态衔接

整批10000组都有基于A46真实房型、原生空调、分层水箱和日期化人员日程的A状态回放，读取室温/水温及所选线圈/风机/加热状态。已知A状态用于输入机会和温控轴选择，不再用当天外温均值充当真实运行模式。空闲状态仍明确标记空闲，最大剂量能否跨过A温控阈值也单列。

0006户2025-06-16当前选定事件的状态为：{native_modes}。模式依据是原生事件输出；即使外温与模式直觉不一致，也不会据外温覆盖读回。

另对预先声明的{t['cases']}个家庭/日期做同模型的B控制替换回放，直接保留事件内未变化和反向的结果。样例中被调整热控设备在选定事件的参考方向计数为{dict(thermal_rel)}；执行成功不等于VPP响应成功。它验证这些样例的指令/状态衔接，不等于整批B的功率、舒适度或热水服务全部通过。A状态模型也仍有固定15°C入水、有限历史、缺少电器/照明/烹饪热增益等范围；所选线圈/风机输出不是完整空调总表。

## 审稿人与EB设计视角的结论

本轮四项都有上游生成代码、整批数据和具体案例证据。输入层复核通过：40000个候选向量完成生成完整性核查，实际技术轴与原始指令一致，原100组和50户同源比例保持；{r['count']}项回归通过。A46的合理稳定习惯保留，未靠随机分钟噪声增加变化。

这不应在论文中写成“所有B均合理、有效、被接受”或“完整benchmark已经完成物理和人类验收”。当前生成机制用于提供不同请求及长尾；其技术分档是声明的实验参数。剩余边界是完整B状态连续性/组合物理后果、舒适度和人类接受，不能由本轮静态检查代替。

证据：`../ACCEPTANCE.json`、`../DESIGN_REVIEW.json`、`../STATE_BINDINGS.json`、`../THERMAL_EVENT_VALIDATION.json`、`../REGRESSION_RESULTS.json`、`四项修改案例.json`。完整规则与复现入口见`../METHODS.md`。
'''
    (OUT/'review/设备独立强度复核.md').write_text(text);print({'report_written':True,'cases':10000,'regressions':r['count'],'paired_thermal_cases':t['cases']})
if __name__=='__main__':main()
