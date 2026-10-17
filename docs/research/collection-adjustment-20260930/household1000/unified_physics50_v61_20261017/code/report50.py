"""Describe actual model repair and diagnostics, without preference labels."""
from core import *


def main():
    review=read(ROOT/'results/pilot50/REVIEW.json');sensitivity=read(ROOT/'SENSITIVITY_REVIEW.json')
    records={r['case_id']:r for r in review['records']}
    cid='ordinary-v6-0490__2025-01-01';current=read(ROOT/records[cid]['path'])
    parent=ROOT.parent/'unified_physics50_v59_20261017'
    old=read(parent/'results/pilot50/ordinary-v6-0490/2025-01-01/PHYSICAL_SUMMARY.json')
    ranges={label:{x['room']:x for x in summary['temperature_exposure']}for label,summary in [('old',old),('current',current)]}
    trace=read(ROOT/'results/pilot50/ordinary-v6-0490/2025-01-01/B/TRACE.json.gz')
    legacy=read(parent/'results/pilot50/ordinary-v6-0490/2025-01-01/B/TRACE.json.gz')
    at=lambda tr,k,m:dict(tr['channels'][k])[m]
    case_diagnostics=[r for r in sensitivity['records']if r['case_id']==cid]
    diagnosis={'case_id':cid,'old_physics_stage':parent.name,'new_physics_stage':ROOT.name,
        'source_pair_sha256':current['source_pair_sha256'],'A_B_source_schedule_hashes':{s:current[s]['source_schedule_hash']for s in('A','B')},
        'weather_station':'Wusu,Xinjiang CSWD513460;unchanged original EPW',
        'old_B_bath_time_outdoor_C':at(legacy,'Zone Outdoor Air Drybulb Temperature|WASHROOM',1110),
        'old_B_bath_time_outdoor_air_changes_per_hour':at(legacy,'Zone Combined Outdoor Air Changes per Hour|WASHROOM',1110),
        'old_occupied_air_ranges':{s:ranges['old']['WASHROOM'][s+'_occupied_temperature_range_C']for s in('A','B')},
        'new_occupied_air_ranges':{s:ranges['current']['WASHROOM'][s+'_occupied_temperature_range_C']for s in('A','B')},
        'new_B_bath_time_corridor_C':at(trace,'Zone Mean Air Temperature|CORRIDOR',1110),
        'new_B_bath_time_makeup_infiltration_kg_s':at(trace,'Zone Air Mass Balance Infiltration Mass Flow Rate|CORRIDOR',1110),
        'new_B_bath_time_exhaust_kg_s':at(trace,'Zone Air Mass Balance Exhaust Mass Flow Rate|WASHROOM',1110),
        'new_max_mass_residual_kg_s':max(current[s]['exhaust_makeup_mass_balance']['maximum_residual_kg_s']for s in('A','B')),
        'cause':'unjustified direct-outdoor makeup boundary in each small exhaust room;outdoor about-13C,scheduled dryer100cfm+bath50cfm,privacy-closed passive door and no in-room heater',
        'repair':'native zone mass conservation,exhaust at original room,makeup via existing geometry portals from entry/corridor;self-balanced base leakage plus required infiltration',
        'capacities_and_schedules_unchanged':True,'added_heating_or_temperature_clipping':False,
        'extra_door_opening_or_human_actions':False,'not_a_measured_household_temperature':True,
        'diagnostic_records':case_diagnostics}
    save(ROOT/'DIAGNOSIS0490.json',diagnosis)
    c=review['counts'];relations=review['whole_VPP_event_relations']
    lines=['# 原50户500组：补风修复与跨季节敏感性复核（物理V61）','',
      'A46/B57原始排程、程序执行失败、EV连续SOC及出发缺口逐组与V59比对；全部500组在同一修订模型下重跑。没有追加供热、移动任务、增加插拔、补救取物或筛除坏B。1000户全量仿真继续暂缓。','',
      '## 0490户冬季低温的原因与修复','',
      f"1月1日原天气站为新疆乌苏；18:30对应报告区间室外约{diagnosis['old_B_bath_time_outdoor_C']:.2f}℃。旧模型把烘干100cfm和卫生间50cfm排风的补气都直接当室外空气，叠加浴室隐私关门及当地没有房间供暖，使卫生间达到约{diagnosis['old_B_bath_time_outdoor_air_changes_per_hour']:.2f}次/小时室外换气。这个局部补风边界未表达原房型已有室内通路，会把通风导致的低温直接混进用户偏好刺激。",'',
      '本版改用原生Fan:ZoneExhaust、沿原门洞的ZoneMixing和ZoneAirMassFlowConservation；由入口/走廊承担所需补风，经室内通路流向原排风房间。原0.35ACH自平衡渗透保留，另计质量守恒所需的补风。不根据温度开关排风，不补加暖气，不把门设成B的新操作。补风通路是明确给定的参考设计；未做现场压差、门缝或住户开窗校准。','',
      '| 有人时卫生间空气温度 | 原V59最低℃ | 本版最低℃ |','|---|---:|---:|']
    for side in('A','B'):lines.append(f"| {side} | {diagnosis['old_occupied_air_ranges'][side][0]:.3f} | {diagnosis['new_occupied_air_ranges'][side][0]:.3f} |")
    lines+=['',f"该案例补风/排风质量账本最大残差{diagnosis['new_max_mass_residual_kg_s']:.3g}kg/s；这个数只验证模型内部守恒，不证明上述绝对温度是实测真值。",'',
      '依据：[EP24.1排风与平衡](https://bigladdersoftware.com/epx/docs/24-1/input-output-reference/group-fans.html#fanzoneexhaust)、[原生质量守恒](https://bigladdersoftware.com/epx/docs/24-1/engineering-reference/zone-air-mass-flow-conservation.html)。参考风量仍沿用前版NREL给定水平，不当作中国家庭实测配置。','',
      '## 实际执行的敏感性验证','',
      f"预先从既有500个日期选择200组；每户尽量取冬、春、秋季最晚已有日期与原第6个夏季日期，加入16个前版已指出的极端/敏感案例。6个家庭×季节没有已有日期，原样记录，不造新日期。选择原因计数：{canonical(sensitivity['season_reason_counts'])}。所有500组仍是同一批benchmark数据，没有评测拆分。",'',
      '| 因素 | 有效案例/对照 |','|---|---:|',
      '| 不同有效前史112/224天 | 179组；另21个早期日期用7天/实际可用前史对照，不重复相同截断前史 |',
      '| 门洞被动交换0.5倍、2倍 | 200组、400次 |',
      '| 背景渗透0.175、0.7ACH | 16个预先指定极端案例、32次 |',
      '| 案例并集/对照总数 | 200/632 |',
      '| 其余未逐例验证 | 300组，不能写作均稳健 |','',
      f"实际有{len(sensitivity['sensitive_case_ids'])}组、{sensitivity['sensitive_comparisons']}次A/B差值对照超过预定界限或改变VPP判定；全部保留。绝对温度对因素的变化与A/B温差的变化分开记录。",'',
      '敏感性按A或B实际有人时段的并集核算，并另报共同占用指标；0.2℃等界限用于诊断数值敏感性，不是个人舒适或接受阈值。对照覆盖主24小时，尚未验证全部后续恢复期，也没有联合扰动或现场校准；实际情景范围不是置信区间。','',
      '## 全批结果与复核范围','',
      f"500组均完成引擎运行、逐设备计量、IDF指令读回和初态共同性核对。B后续未执行{c.get('B_future_unexecuted_batches',0)}批、取出失败{c.get('B_failed_retrieval_batches',0)}批、EV出发目标不足{c.get('B_EV_target_shortfall_departures',0)}次，均不被删去或自动补救。",'',
      f"VPP实际窗口响应：{canonical(relations)}。不要求B顺向、达标、节能或被接受；新物理版本的结果与旧版本不混用。",'',
      '本轮可验收的是：原50户的统一参考物理回放、已执行敏感性实验和同版本影响摘要。不能据此称全500组对未知边界稳健、真实家庭绝对温度已校准或已得到人类接受标签。','',
      '完整证据：DIAGNOSIS0490.json、SENSITIVITY_SELECTION.json、SENSITIVITY_REVIEW.json、ARTIFACT_READBACK50.json、PHYSICAL_BINDINGS50.json、FINAL_SEAL50.json。开发试跑的引擎崩溃记录保留在diagnosis0490，修复后结果使用独立目录；它们与B方案的业务失败分别记录。','']
    (ROOT/'REVIEW50.md').write_text('\n'.join(lines))
    print(canonical({'diagnosis_written':True,'cases':500,'sensitivity_cases':200}),flush=True)


if __name__=='__main__':main()
