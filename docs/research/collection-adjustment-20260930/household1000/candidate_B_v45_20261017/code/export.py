"""VPP context, real command portfolios and explicit known-load-only references."""
import csv,collections
from common import *
ZH={'thermal_setpoint':'空调温控','thermal_pause':'空调暂停','program_timer':'程序预约','handling_shift':'装取与程序联动','ev_delay':'连接内充电时段','ev_short_window':'受限充电窗口','hotwater_preheat':'热水预热与恢复','hotwater_target':'储水温度','coordinated':'跨设备组合','reverse_direction':'反向温控','low':'小幅','medium':'中幅','high':'大幅','extreme':'极端'}
def clock(m):return ('当日'if m<1440 else'次日'if m<2880 else'service_tail')+f'{m%1440//60:02d}:{m%60:02d}'
def differences(p):
 out=[]
 for x in p['proposal']['changes']:
  detail=x['description']
  if 'program_start_A_min'in x:detail+=f"；{clock(x['program_start_A_min'])}→{clock(x['program_start_B_min'])}"
  elif 'window_A_min'in x:detail+='；'+str(list(map(clock,x['window_A_min'])))+'→'+str(list(map(clock,x['window_B_min']))if x['window_B_min']is not None else[])
  else:detail+=f"；{clock(x['start_min'])}–{clock(x['end_min'])}"
  out.append(detail)
 return '；'.join(out)
def main():
 a=read(OUT/'ACCEPTANCE.json');review=OUT/'review';review.mkdir(exist_ok=True)
 if not a['accepted']or a['rules_sha256']!=rules_id():raise ValueError('B39_NOT_ACCEPTED')
 fields=['家庭ID','日期','类别','多事件处理方式','VPP请求','焦点事件','机制','请求档位','实际档位','等价档位','计划组合','实际改变设备','与A相同指令','具体调整','原请求约束冲突','事件内已知负荷响应参考kW','事件后2小时已知额外电量kWh','每个事件首次指令差异时序','完整物理及态度','文件','SHA256'];examples={};count=0;refs=collections.Counter()
 with (review/'10000组VPP与AB核对表.csv').open('w',newline='',encoding='utf-8-sig')as f:
  writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
  for r in read(OUT/'PAIR_BINDINGS10000.json')['records']:
   for rr in r['rounds']:
    p=read(OUT/rr['path']);q=p['proposal'];z=p['assessment_B'];flags=sorted({x['code']for x in z['constraint_flags']});events=p['VPP_events'];v=p['VPP_response_reference']['events'];count+=1
    request='；'.join(e['event_id']+' '+clock(e['start_min'])+'–'+clock(e['end_min'])+('削峰'if e['direction']=='down'else'增加负荷')+str(e['target_kw'])+'kW'for e in events)
    writer.writerow(dict(zip(fields,[r['household_id'],p['date'],r['type'],q['multi_event_policy'],request,q['focus_VPP_event_id'],ZH[q['realized_mechanism']],ZH[q['requested_intensity_design']],ZH[q['intensity_design']],','.join(q['equivalent_design_levels']),'+'.join(q['requested_portfolio_families']),'+'.join(q['portfolio_families']),q['same_command_as_A'],differences(p),';'.join(flags),';'.join(str(round(x['requested_known_response_average_kw'],4))for x in v),';'.join(str(round(x['requested_post2h_extra_kWh'],4))for x in v),';'.join(x['event_id']+':'+x['requested_command_relation']for x in p['event_relations']),'HVAC/热水/完整用电及接受评分待测',rr['path'],rr['sha256']])))
    tags=[];families=q['portfolio_families']
    if q['realized_mechanism']=='coordinated'and len(families)>=2 and'ac'not in families:tags.append('非空调的跨设备组合')
    if q['realized_mechanism']=='coordinated'and len(families)>=3:tags.append('实际改变三个设备类别')
    if len(events)>1:tags.append('同日两次VPP请求')
    if events[0]['direction']=='up':tags.append('增加负荷请求')
    if q['same_command_as_A']:tags.append('如实保留A，无新增操作')
    if any(x['requested_known_response_average_kw']< -1e-7 for x in v):tags.append('已知负荷部分响应方向相反')
    if 'SERVICE_DEADLINE_MISSED'in flags:tags.append('保留真实服务期限失败')
    for tag in tags:
     if tag not in examples:examples[tag]={'case_id':p['case_id'],'VPP_events':events,'proposal':q,'assessment_B':z,'VPP_response_reference':p['VPP_response_reference'],'path':rr['path'],'sha256':rr['sha256']}
 save(review/'设计与长尾示例.json',examples);save(review/'覆盖与验收统计.json',a);save(review/'50户同源筛选清单.json',read(OUT/'SUBSET50.json'))
 ad=read(A_STAGE/'DESIGN_REVIEW.json');bd=read(OUT/'DESIGN_REVIEW.json')
 rows=['# A44/B45本轮生成复核','','1000户、10000组；50户按5/15/16/5/4/5直接引用同批文件。','',
  'A循环风改为实际房间活动驱动：起床、返家后使用或晚间活动对应稳定的给定习惯。每台每天60分钟，保留合理重复，不按日期随机挪时。','',
  'B温控从连续可用房间时段选择调整，风机和need_id分段不再截短请求；写回仍保留原风机模式、各片段设定值和真实离家缺口。联合程序的不调整判断覆盖全部相关削负荷窗口。','',
  f"约束满足{a['given_constraints_feasible_cases']}组；约束冲突{a['given_constraint_conflict_cases_kept']}组保留。无指令变化、强弱档位合并和预设不利请求照实保留；接受与评分为空。",'',
  '| 示例 | 案例 | 实际改变设备 |','|---|---|---|']
 for tag,p in examples.items():rows.append('|'+tag+'|'+p['case_id']+'|'+'+'.join(p['proposal']['portfolio_families'])+'|')
 rows+=['','VPP仅使用已保存的EB事件模板和外生站点/日期请求。全部08:00通知，目标和方向比例是研究设定。程序与EV参考不含HVAC/水箱反馈及连续B电量，不能据此声称全屋达标或净收益。','',
  '4个新A真实壳体HVAC功能探针已另存；围护层次、额定曲线和低温制冷警告仍需后续物理复核。全量A/B物理、热水和舒适验收尚未完成。旧线上问卷、物理及答案不改绑到本轮版本。']
 (review/'本轮修改简明说明.md').write_text('\n'.join(rows)+'\n');save(OUT/'REVIEW_EXPORT_MANIFEST.json',{'files':{rel(p):sha(p)for p in review.iterdir()if p.is_file()},'scope':'static VPP-conditioned requests;known-load references;no physical success or human labels'})
 print({'cases_exported':count,'examples':len(examples)})
if __name__=='__main__':main()
