"""Concise final review grounded in current whole-population and paired evidence."""
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
    dish=case('ordinary-v6-0048','2025-04-02');dishobs=next(x for x in dish['proposal']['actual_device_strengths']if x['device_family']=='dishwasher')
    ev=case('ordinary-v6-0001','2025-09-30')['EV_continuous_reference']
    tank=next(x for x in t['records']if x['household_id']=='ordinary-v6-1000'and x['date']=='2025-07-23');tankref=next(x for x in tank['native_event_readbacks']if'water_heater'in x['asset_id'])
    shifts=a['actual_program_shift_minutes']['dishwasher'];late=sum(value for key,value in shifts.items()if int(key)>0);early=sum(value for key,value in shifts.items()if int(key)<0)
    thermal=collections.Counter()
    for result in t['records']:
        pair=read(OUT/result['pair_path'])
        for req in pair['proposal']['requested_device_strengths']:
            if req['device_family']not in('ac','water_heater'):continue
            selected=req['input_state_plan']['event'];delta=sum(x['native_delta_kw']for x in result['native_event_readbacks']if x['event_id']==selected['event_id']and x['asset_id']in req['asset_ids'])
            relation='unchanged'if abs(delta)<1e-6 else'aligned'if(delta>0)==(selected['direction']=='up')else'opposing';thermal[relation]+=1
    c=v['counts'];ac=a['counts'];dc=d['counts']
    ev_extra=sum(z['grid_kWh']for z in ev['B']['charging_steps']if z['start_min']>=ev['last_changed_permission_end_min'])-sum(z['grid_kWh']for z in ev['A']['charging_steps']if z['start_min']>=ev['last_changed_permission_end_min'])
    text=f'''# A46/B55：第3、4项修改与复核

已重生成1000户、整批10000组。A46及家庭/设备/日期化生活日程保持；所有已配设备的每日需求、任务和人工操作身份保留。原100组相同B载荷不变；50户按5/15/16/5/4/5直接引用同批主数据。没有预设评分/接受标签，{ac['constraint_conflict_cases']}组给定约束冲突继续保留。

## 热控：修正真实生成逻辑

准备、事件和回到A分别记录，削峰准备不再沿用事件的降负荷方向。事件内优先锚定原生A实际活动时段；准备/事件之外的A控制已逐步核对，恢复指令相同不代表物理状态瞬间恢复。

1000号2025-07-23：事件19—20点，准备18—19点已从错误降温改为蓄热。配对参考中水箱事件平均功率差为{tankref['native_delta_kw']:.3f}kW；旧B54同模型为约+0.221kW。准备、事件和恢复的水温及能量均保存。该例改善不是整批筛选条件。

整批阶段/恢复原始指令审计通过；预先声明的{t['cases']}组B热控回放成功。按实际控制器聚合，选定事件方向为{dict(thermal)}，反向/未变化均照留。回放隔离同A历史/人员条件下的B控制，缺失热增益、完整组合负荷和舒适度仍在范围外，不能宣称整批B物理验收完成。

## 移时：取消统一最晚回退

使用家庭稳定的三类给定策略：真实装载就绪后运行、保留已有取物访问、在下次服务/使用前完成。装载和取出独立排程；若A已经最早，则依据下一次原有访问/操作者返回或交付节点形成请求，不再以最近的非零10分钟为目标。实际节点来自原日程和可行候选；仅明确的服务压力分支继续施压边界。没有随机分钟噪声、额外操作或为了有效而筛选方案。

洗碗的500次程序调整，当前延后{late}次、提前{early}次（旧B54延后490、提前10）。所有洗衣/洗碗的服务边界请求中，{c['service_boundary_at_latest']}/{c['service_boundary_programs']}取到剂量范围最晚点，已摆脱全部统一取最晚点；比例变化本身不是验收目标。0048号2025-04-02当前实际程序/装取轴为{dishobs['actual_strength_axes']}，实际由19:30装载就绪确定19:40启动，仍保留21:30取出；请求明确没有18—19点的VPP机会，没有伪称贡献。

## EV：保持原许可，新增连续电量与恢复验证

整批{c['EV_installed_cases']}组有EV；{c['EV_changed_request_cases']}组改变EV许可。B54原EV许可及插拔保持，所需目标不变。每组从共同A决策前状态连续推进，按原行程消耗；后续原许可内按真实剩余电量恢复，不在连接时重置SOC，不把十个日期串联。

状态统计：{ {k:v for k,v in c.items()if k.startswith('EV_recovery:')} }。B轨迹中出发目标不足{c.get('EV_B_target_unmet_departures',0)}次、行程后最低储备不足{c.get('EV_B_minimum_reserve_unmet_departures',0)}次、连行程耗能都不足{c.get('EV_B_unexecutable_departures',0)}次，均独立报告；没有凑失败数量。

0001号2025-09-30当前恢复状态为{ev['recovery_status']}，原请求结束后回到共同SOC的时间为相对当日零点{ev['common_SOC_restored_after_request_min']}分钟。后续原连接中的额外电网充电为{ev_extra:.3f}kWh。完整充电步、原行程、出发/行程后SOC和缺口均保存，后续恢复不会消除原来的失败记录。

独立复核已核对电量守恒、逐次充放电连接、原许可/日程边界，以及A轨迹与封存年度账本的一致性。模型是固定充电功率/效率的条件参考，非实测电池或人类接受。

## 验收结论与范围

整批原始指令/设备多轴、40000候选完整性、每日需求/身份及同源50均通过；{r['count']}项回归通过。{dc['EV_energy_bound_shortfall_requests']}条目标电量上界不足请求保留。没有新增A46需重做的证据；本轮修复的B规则与连续EV参考已有代码和数据，但完整B组合物理、热舒适/热水服务和人类偏好尚不能写成通过。

证据：`../ACCEPTANCE.json`、`../PHASE_EV_REVIEW.json`、`../DESIGN_REVIEW.json`、`../THERMAL_EVENT_VALIDATION.json`、`../REGRESSION_RESULTS.json`、`阶段与连续电量案例.json`。正式方法及复现命令见`../METHODS.md`。
'''
    (OUT/'review/设备独立强度复核.md').write_text(text);print({'report_written':True,'cases':10000,'regressions':r['count'],'paired_thermal_cases':t['cases']})
if __name__=='__main__':main()
