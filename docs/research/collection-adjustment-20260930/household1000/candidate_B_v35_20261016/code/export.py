"""Chinese reviewer-facing evidence, without fabricated costs or acceptance."""
import collections
import csv
from common import *

ZH={'thermal_setpoint':'空调设定温度','thermal_pause':'空调暂停','program_timer':'程序预约时间','handling_shift':'装取与程序一起调整',
    'ev_delay':'原连接内延后充电','ev_short_window':'缩短充电许可','hotwater_preheat':'热水预热时间','hotwater_target':'热水储水设定',
    'coordinated':'多设备组合','reverse_direction':'反向温控调整','low':'小幅','medium':'中幅','high':'大幅','extreme':'极端'}
FLAGS={'OPERATOR_UNAVAILABLE':'请求时操作者无空闲','ASSET_STILL_OCCUPIED':'设备仍被上一批占用','OPERATOR_DOUBLE_BOOKED':'同一人操作冲突',
       'FACILITY_DOUBLE_BOOKED':'共用空间操作冲突','FACILITY_RESERVED':'与既定设施预约冲突','SERVICE_DEADLINE_MISSED':'超过既定服务截止',
       'EV_TARGET_ENERGY_IMPOSSIBLE_IN_WINDOW':'充电窗口不足以达到既定电量','GIVEN_PRELOAD_BOUND_EXCEEDED':'超过既定预装等待上限',
       'GIVEN_RETRIEVAL_WAIT_EXCEEDED':'超过既定取出等待上限','REQUESTED_KNOWN_POWER_EXCEEDS_INLET':'仅已知负荷已超过入户容量',
       'PROGRAM_BEFORE_LOADING':'程序先于装载完成','RETRIEVAL_BEFORE_COMPLETION':'取出请求早于程序完成','LOAD_BEFORE_SERVICE_RELEASE':'早于任务可用时间装载',
       'CONTEXT_HORIZON_EXCEEDED':'请求超过已提供日程范围','CHARGE_OUTSIDE_REAL_CONNECTION':'超出真实车辆连接'}

def clock(m):
    day=m//1440;t=m%1440
    return(f'次日'if day==1 else f'第{day+1}日'if day>1 else f'前{-day}日'if day<0 else'当日')+f'{t//60:02d}:{t%60:02d}'

def description(p):
    parts=[]
    for x in p['proposal']['changes']:
        if 'program_start_A_min'in x:time=f"A {clock(x['program_start_A_min'])}→B {clock(x['program_start_B_min'])}；程序结束{clock(x['completion_A_min'])}→{clock(x['completion_B_min'])}"
        elif 'window_A_min'in x:time=f"A {clock(x['window_A_min'][0])}–{clock(x['window_A_min'][1])}→B {clock(x['window_B_min'][0])}–{clock(x['window_B_min'][1])}"
        else:time=f"{clock(x['start_min'])}–{clock(x['end_min'])}"
        parts.append(x['description']+'（'+time+'）')
    return '；'.join(parts)

def main():
    a=read(OUT/'ACCEPTANCE.json');b=read(OUT/'PAIR_BINDINGS10000.json');review=OUT/'review';review.mkdir(exist_ok=True)
    fields=['家庭ID','日期','类型','调整机制','设计强度','A与B具体差异','给定约束是否可执行','给定约束冲突','已知请求负荷峰值下界kW','用户接受与否','费用舒适度及完整执行结果','文件','SHA256']
    examples={};subset_ids={r['household_id']for r in read(OUT/'SUBSET50.json')['records']}
    with (review/'10000天AB调整核对表.csv').open('w',newline='',encoding='utf-8-sig')as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        for r in b['records']:
            for case in r['rounds']:
                p=read(OUT/case['path']);codes=sorted(set(x['code']for x in p['assessment_B']['constraint_flags']))
                writer.writerow(dict(zip(fields,[r['household_id'],p['date'],r['type'],ZH[case['mechanism']],ZH[case['intensity']],description(p),
                    '是（仅已列明约束）'if not codes else'存在冲突，保留该B','；'.join(FLAGS.get(x,x)for x in codes),
                    round(p['assessment_B']['requested_known_load_peak_lower_bound_kw'],4),'待问卷','待完整仿真',case['path'],case['sha256']])))
                tags=[]
                if not codes and case['intensity']=='low':tags.append('小幅且给定约束可执行')
                if not codes and case['intensity']=='extreme':tags.append('极端但不能据此代填拒绝')
                if case['mechanism']=='reverse_direction':tags.append('保留反向温控，效果待仿真')
                for code,label in [('SERVICE_DEADLINE_MISSED','错过真实服务截止'),('EV_TARGET_ENERGY_IMPOSSIBLE_IN_WINDOW','充电目标无法在窗口内满足'),('OPERATOR_UNAVAILABLE','请求与操作者日程冲突')]:
                    if code in codes:tags.append(label)
                for tag in tags:
                    if tag not in examples and r['household_id']in subset_ids:examples[tag]=p
    rows=['# B方案核对示例','',
          '本批以1000户主数据为基础，50户直接引用相同文件。强度和机制是预先设计的覆盖条件，不代表现实频率；接受/拒绝均待填写。',
          '','A已先修正已知负荷叠加超过入户容量的充电安排；家庭、需求、行程和插拔操作保留。空调和水箱的真实耗电、室温、出水温度仍待完整仿真。','',
          '| 情形 | 家庭/日期 | A→B | 已知影响 |','|---|---|---|---|']
    for tag,p in examples.items():
        codes=sorted(set(x['code']for x in p['assessment_B']['constraint_flags']))
        rows.append(f"| {tag} | {p['household_id']} / {p['date']} | {description(p)} | {'；'.join(FLAGS.get(x,x)for x in codes)if codes else'已列明约束可执行；态度与物理结果待测'} |")
    rows+=['','总计：'+str(a['cases'])+'组；给定约束可执行'+str(a['given_constraints_feasible_cases'])+'组；保留约束冲突'+str(a['given_constraint_conflict_cases_kept'])+'组。',
           '','这些冲突是对“请求方案”的判断。执行记录不虚构操作者、上门服务或自动同意；无法装载时不把程序记作已运行。']
    (review/'B方案简明示例.md').write_text('\n'.join(rows)+'\n')
    save(review/'示例完整数据.json',{tag:p for tag,p in examples.items()})
    save(review/'覆盖与验收统计.json',a)
    save(review/'50户同源筛选清单.json',read(OUT/'SUBSET50.json'))
    save(OUT/'REVIEW_EXPORT_MANIFEST.json',{'files':{rel(p):sha(p)for p in sorted(review.iterdir())if p.is_file()},'scope':'static proposals and given constraints;not questionnaire or physical results'})
    print({'examples':len(examples),'cases_exported':a['cases']})

if __name__=='__main__':main()
