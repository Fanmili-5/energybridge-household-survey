"""Concise reviewer report on reached nodes, whole holds and unified EV impact."""
import sys,collections
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *
def main():
    a=read(OUT/'ACCEPTANCE.json');d=read(OUT/'DESIGN_REVIEW.json');r=read(OUT/'REGRESSION_RESULTS.json');t=read(OUT/'THERMAL_EVENT_VALIDATION.json');v=read(OUT/'PHASE_EV_REVIEW.json');sig=rules_id()
    assert a['accepted']and d['passed']and r['passed']and t['passed']and v['passed']
    assert all(x['rules_sha256']==sig and x.get('bindings_sha256',sha(OUT/'PAIR_BINDINGS10000.json'))==sha(OUT/'PAIR_BINDINGS10000.json')for x in(a,d,r,t,v))
    rows={x['household_id']:x for x in read(OUT/'PAIR_BINDINGS10000.json')['records']}
    def case(hid,date):return read(OUT/next(x['path']for x in rows[hid]['rounds']if x['date']==date))
    laundry=case('ordinary-v6-0454','2025-10-08')['B']['program_request_plans'][0]
    dose=case('ordinary-v6-0001','2025-03-22')['B']['program_request_plans'][0]
    pp=case('ordinary-v6-0001','2025-09-30');ev=pp['VPP_response_reference']['EV_continuous_impact'];c=v['counts'];ac=a['counts']
    thermal=collections.Counter()
    for result in t['records']:
        pair=read(OUT/result['pair_path'])
        for req in pair['proposal']['requested_device_strengths']:
            if req['device_family']not in('ac','water_heater'):continue
            selected=req['input_state_plan']['event'];delta=sum(x['native_delta_kw']for x in result['native_event_readbacks']if x['event_id']==selected['event_id']and x['asset_id']in req['asset_ids'])
            relation='unchanged'if abs(delta)<1e-6 else'aligned'if(delta>0)==(selected['direction']=='up')else'opposing';thermal[relation]+=1
    bases={k.split(':',1)[1]:v for k,v in c.items()if k.startswith('program_basis:')}
    text=f"""# A46/B56：本轮三处修改与专项复核

已修改生成逻辑并重生成1000户、整批10000组，保留A46。相对B55，{c['B55_program_or_handling_changed_cases']}组的实际程序/装取指令发生变化。所有已配设备的每日任务和需求、原100组相同B载荷及同源50户保留；50户A/B/C/D/E/F仍为5/15/16/5/4/5。{ac['constraint_conflict_cases']}组给定约束冲突照留，不预设接受或评分，也不以B优于A筛选。

## 1. 回退节点必须真正到达

只对实际到达原日程节点的请求记录`life_node_request`，保存来源和准确分钟；不再把剂量截断点冒充远处节点。没有可达节点时明确记录`dose_boundary_request`，它是给定的技术剂量测试，不声称由真实生活访问或VPP收益推动。无法满足合同的请求保留并明确不可行。

0001户2025-03-22仍可提出+{dose['actual_shift_min']}分钟的技术请求，但现在为{dose['request_basis']}，selected_node为空，不再称为到达次日08:40服务节点。此类干预不是现实家庭偏好/频率的证据。

整批{c['program_plans']}条程序请求：{bases}。{c['exact_life_nodes']}条生活节点的来源、实际分钟及原始指令逐一核对；保持原取出时刻不再单独充当任意移时的理由。技术剂量请求与生活节点、实际方向和约束失败分开。

## 2. 占用覆盖装载到取出

候选检查同一机器其他批次的[装载开始,取出结束)，包含等待启动、洗烘链和完成后等待；单设备相对A的可行性与联合B冲突分开记录。

0454户2025-10-08：上一批17:30—17:40取出；第二批原来17:20装载导致重叠，现在装载{laundry['B_load_min']//60:02d}:{laundry['B_load_min']%60:02d}、程序{laundry['B_start_min']//60:02d}:{laundry['B_start_min']%60:02d}启动，准确接在设备清空后，未新增操作/帮手。整批{c['full_hold_feasible_claims']}条可行声明均无其他A批次完整占用冲突；其余请求按实际约束评估，失败不删。

## 3. EV连续电量进入主影响摘要

事件、前后两小时、主日和跨日至4320分钟的已知负荷摘要均使用同一条连续SOC充电轨迹。恢复电量、恢复时间及出发缺口同时展示；旧的逐连接A状态投影仍仅为单连接上界指标，不能代替连续B电量。

0001户2025-09-30：原先尾部少充约7.170度的表面差异，现在明确显示后续原连接额外补电{ev['after_request_extra_grid_kWh']:.3f}度，至尾部EV总电量差{ev['periods']['to_tail']['delta_grid_kWh']:.3f}度，{ev['common_SOC_restored_min']}分钟恢复共同SOC；出发目标不足仍记录，不因后来补上就变成成功。

整批10000组摘要、分类与连续轨迹逐一绑定和复算；修正{c['legacy_EV_tail_energy_discrepancy_corrected_cases']}组旧EV尾部能量不一致。B55的全部EV许可/插拔保持。连续参考中目标不足{c.get('EV_B_target_unmet_departures',0)}次、最低储备不足{c.get('EV_B_minimum_reserve_unmet_departures',0)}次、无法完成行程{c.get('EV_B_unexecutable_departures',0)}次，原失败照留。

## 复核结论

这三处生成与摘要缺口已修复：10000组原始指令/多轴分档、40000候选完整性、每日需求和同源50户核对通过，{r['count']}项回归通过。{t['cases']}组预先指定的配对B热控回放与本版输入绑定；选定热控方向按控制器聚合为{dict(thermal)}，无效/反向结果保留。代码、数据、审计、版本和复现入口一致。

保留的范围限制：EV为固定功率/效率的条件参考；热控回放隔离B控制变化，仍缺完整组合负荷/热增益和舒适度验证。因此本结论是本轮生成规则及影响摘要专项通过，不能扩写成整批B完整物理或人类接受已通过。没有新增A46需要重做的证据。

方法及命令：`../METHODS.md`；审计：`../ACCEPTANCE.json`、`../PHASE_EV_REVIEW.json`、`../DESIGN_REVIEW.json`、`../THERMAL_EVENT_VALIDATION.json`、`../REGRESSION_RESULTS.json`；具体案例：`阶段与连续电量案例.json`。
"""
    (OUT/'review/设备独立强度复核.md').write_text(text);print({'report_written':True,'cases':10000,'regressions':r['count'],'paired_thermal_cases':t['cases']})
if __name__=='__main__':main()
