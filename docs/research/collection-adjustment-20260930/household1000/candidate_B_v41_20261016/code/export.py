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
  elif 'window_A_min'in x:detail+=f"；{list(map(clock,x['window_A_min']))}→{list(map(clock,x['window_B_min']))}"
  else:detail+=f"；{clock(x['start_min'])}–{clock(x['end_min'])}"
  out.append(detail)
 return '；'.join(out)
def main():
 a=read(OUT/'ACCEPTANCE.json');review=OUT/'review';review.mkdir(exist_ok=True)
 if not a['accepted']or a['rules_sha256']!=rules_id():raise ValueError('B39_NOT_ACCEPTED')
 fields=['家庭ID','日期','类别','VPP请求','焦点事件','机制','请求档位','实际档位','等价档位','计划组合','实际改变设备','与A相同指令','具体调整','原请求约束冲突','事件内已知负荷响应参考kW','事件后2小时已知额外电量kWh','每个事件首次指令差异时序','完整物理及态度','文件','SHA256'];examples={};count=0;refs=collections.Counter()
 with (review/'10000组VPP与AB核对表.csv').open('w',newline='',encoding='utf-8-sig')as f:
  writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
  for r in read(OUT/'PAIR_BINDINGS10000.json')['records']:
   for rr in r['rounds']:
    p=read(OUT/rr['path']);q=p['proposal'];z=p['assessment_B'];flags=sorted({x['code']for x in z['constraint_flags']});events=p['VPP_events'];v=p['VPP_response_reference']['events'];count+=1
    request='；'.join(e['event_id']+' '+clock(e['start_min'])+'–'+clock(e['end_min'])+('削峰'if e['direction']=='down'else'增加负荷')+str(e['target_kw'])+'kW'for e in events)
    writer.writerow(dict(zip(fields,[r['household_id'],p['date'],r['type'],request,q['focus_VPP_event_id'],ZH[q['realized_mechanism']],ZH[q['requested_intensity_design']],ZH[q['intensity_design']],','.join(q['equivalent_design_levels']),'+'.join(q['requested_portfolio_families']),'+'.join(q['portfolio_families']),q['same_command_as_A'],differences(p),';'.join(flags),';'.join(str(round(x['requested_known_response_average_kw'],4))for x in v),';'.join(str(round(x['requested_post2h_extra_kWh'],4))for x in v),';'.join(x['event_id']+':'+x['requested_command_relation']for x in p['event_relations']),'HVAC/热水/完整用电及接受评分待测',rr['path'],rr['sha256']])))
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
 rows=['# 本轮生成修改结果','','1000户主数据、10000组，50户按5/15/16/5/4/5逐条引用同批文件。V40从稳定家庭习惯重建全年生活日程、连续需求与A；没有读取旧全年A。V41在A冻结后接入VPP。','',
  'VPP使用EB原事件标准化器和7日变时段配置，按站点与日期分配，一天一至两次事件。通知统一08:00；请求方向支持削峰/增加负荷。0.5/1/2kW目标与方向覆盖是明确的研究设定；不声称真实电网请求或补贴。','',
  '每户两次组合候选，先按A输入机会分配机制、日期、事件和组合，再构造B。组合统计只计实际改变指令的设备类别；同一洗烘机自动洗→烘不是两个独立组合选择。不按可行性、收益或演员答案筛选；无变化、晚响应及失败均保留。热水说明由最终许可片段和真实后续许可生成。','',
  '| 示例 | 案例 | 实际改变设备 |','|---|---|---|']
 for tag,p in examples.items():rows.append('|'+tag+'|'+p['case_id']+'|'+'+'.join(p['proposal']['portfolio_families'])+'|')
 ad=read(A_STAGE/'DESIGN_REVIEW.json');bd=read(OUT/'DESIGN_REVIEW.json');probes=read(A_STAGE/'THERMAL_FUNCTIONAL_CHECK.json')
 rows +=['',f"家庭晚餐参考时点18:00：A38的{ad['previous_A38_dinner_minutes_counts'].get('1080',0)}组→A40的{ad['dinner_minutes_counts'].get('1080',0)}组。家庭习惯是给定的实验场景因素，日期变化来自日程与资源约束，不是人口频率推断或随机挪分钟。",'',f"4个真实壳体冷热控制功能探针完成；存在继承的围护层次/额定曲线及低温制冷警告。它们不代表全量物理、舒适或热水验收。",'',f"重点组合当前实际数量：洗碗＋洗衣{bd['actual_coordinated_portfolio_counts'].get('dishwasher+washer',0)}组，洗碗＋热水{bd['actual_coordinated_portfolio_counts'].get('dishwasher+water_heater',0)}组。是否足够单独统计，需要按最终论文评测口径确定。",'','静态约束满足'+str(a['given_constraints_feasible_cases'])+'组；约束冲突'+str(a['given_constraint_conflict_cases_kept'])+'组全部保留。接受/拒绝、评分和理由均未填写。','',
  '事件内和事件前后能量仅展示已知程序负荷及同一连接起点下的EV参考；不含HVAC/水箱热反馈，不可称完整削峰、收益或净节能。完整物理结果和新版问卷仍待处理。']
 (review/'本轮修改简明说明.md').write_text('\n'.join(rows)+'\n');save(OUT/'REVIEW_EXPORT_MANIFEST.json',{'files':{rel(p):sha(p)for p in review.iterdir()if p.is_file()},'scope':'static VPP-conditioned requests;known-load references;no physical success or human labels'})
 print({'cases_exported':count,'examples':len(examples)})
if __name__=='__main__':main()
