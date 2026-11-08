"""Render evidence labels and a complete reference household without inventing facts."""
from pathlib import Path
import json
from .pipeline import read_rows

NAMES={'AC':'空调','WM':'洗衣','DR':'烘干','DW':'洗碗','WH':'储水电热水','EV':'电动车充电'}
DAYS=['周一','周二','周三','周四','周五','周六','周日']
def compact(value):return json.dumps(value,ensure_ascii=False,sort_keys=True)
def clock(value):
    day,minute=divmod(int(value),1440)
    return (f'第{day+1}日 ' if day else '')+f'{minute//60:02d}:{minute%60:02d}'
def card(c):
    h=c['household'];p=c['household_provenance']
    fixture=c['source']['dataset']=='SYNTHETIC'
    lines=[f'## {c["case_id"]} / {c["source"]["country"]} / {c["benchmark_role"]}类',
      '**公开虚构演示：本卡没有真实同户调查事实。**' if fixture else '历史调查支持的参考家庭；不是原调查家庭实际一周的重建。',
      '角色与态度【EB实验条件】：'+compact(c['card']),
      '原始事实按字段保留来源与状态；具体成员补全、参考周、控制接入与舒适参数均按 household_provenance 标注。',
      '源标识：'+compact(c['source']),
      '原调查家庭人数：'+compact(c['household_size']),
      '原调查住房/匹配信息：'+compact(c['dwelling']),
      '原调查在家状态及原范围：'+compact(c['known_presence']),
      '运行住房【匹配或实验补全】：'+compact(h['dwelling']),
      '决策与控制授权【实验】：'+compact(h['decision_authorization']),
      '态度【EB角色条件，非调查预测】：'+compact(h['attitudes']),
      '温度约束【实验参数】：'+compact(h['comfort']),'','### 全体成员','']
    for m in h['members']:
        relevant={k:v for k,v in p.items() if k.startswith('members.'+m['id']+'.')}
        lines+=['- '+compact(m),'  来源状态：'+compact(relevant)]
    lines+=['','### 六类电器与服务','']
    keys={'AC':'space_ac_available','WM':'washer_available','DR':'dryer_available','DW':'dishwasher_available','WH':'water_heater_available','EV':'home_vehicle_charging'}
    for f,key in keys.items():
        lines+=['- '+NAMES[f]+'：原调查 '+compact(c['devices'][key])+'；参考设备 '+compact(h['equipment'][key])+'；控制 '+compact(h['control_inventory'][f])]
    lines+=['完整服务合同【后续事件必须满足，目前未调度】：'+compact(h['service_contracts']),
      '同一物理设备/前置任务约束：'+compact(h['shared_control_asset_constraints']),
      'EV参数与连续补能要求【实验】：'+compact(h.get('ev')),
      '照护与外部支持【来源按逐字段标记】：'+compact(h['care_arrangements']),
      '每周洗衣需求/使用解释：'+compact(h['routine']['laundry_cycles_per_week']),
      '参考周信息规则【实验】：'+compact(h['routine']['information_contract'])]
    for d in range(7):
        lines+=['',f'### {DAYS[d]}参考安排【实验】','']
        for e in h['calendar']['weekly_events']:
            if d*1440<=e['start']<(d+1)*1440:
                lines+=['- '+e['member_id']+' '+clock(e['start']-d*1440)+'—'+clock(e['end']-d*1440)+' '+e['kind']+' / '+e['location']+'；'+compact(e)]
        lines+=['餐食、洗浴、手动操作与服务机会：'+compact(h['routine']['daily_services'][d])]
    lines+=['','### 完整字段来源台账','', '```json',json.dumps(p,ensure_ascii=False,indent=2,sort_keys=True),'```',
      '参考日程/服务机会不等于电器开关计划；覆盖蓝图不等于实际题目。实际A/B、仿真和真人回答均为0。','']
    return '\n'.join(lines)
def render(run):
    run=Path(run);rows=read_rows(run/'household_cases.jsonl');target=run/'HOUSEHOLD_CARDS.md'
    if target.exists():raise ValueError('CARD_OUTPUT_EXISTS; refusing overwrite')
    target.write_text('# 完整家庭卡\n\n'+'\n\n---\n\n'.join(card(c) for c in rows))
    print(json.dumps({'cards':len(rows),'path':str(target)},ensure_ascii=False))
    return target
