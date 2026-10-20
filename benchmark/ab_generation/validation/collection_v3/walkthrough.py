"""Render the actual selected ten days; no hand-selected substitutions or engine."""
import argparse
from pathlib import Path
from benchmark.ab_generation.common import read,save,sha


NAMES={'washer':'洗衣','dryer':'烘干','dishwasher':'洗碗','ac':'空调','ev':'EV充电','water_heater':'热水箱'}
ISSUES={'OPERATOR_UNAVAILABLE':'操作碰到原生活安排/不便时段','OPERATOR_DOUBLE_BOOKED':'同一人被安排同时操作',
    'ROOM_DOUBLE_BOOKED':'操作空间同时占用','MACHINE_WINDOW_VIOLATED':'超出原机器便利窗口',
    'SERVICE_DEADLINE_MISSED':'计划交付逾期','PRELOAD_WAIT_EXCEEDED':'装载后等待过长',
    'RETRIEVAL_WAIT_EXCEEDED':'程序结束后等待取出过长','CHARGE_EXCEEDS_ORIGINAL_CONNECTION':'名义补能不足',
    'SITE_CAPACITY_NOT_CERTIFIED':'保守功率包络未获认证','SITE_KNOWN_PROFILE_EXCEEDS_SUPPLY':'已知计划功率超限'}


def clock(t):
    day,minute=divmod(t,1440)
    return ('' if day==0 else '次日' if day==1 else str(day)+'日后')+f'{minute//60:02d}:{minute%60:02d}'


def interval(r):return clock(r['start_min'])+'—'+clock(r['end_min'])


def ac_value(s):
    return '停冷回退' if s['mode']=='cooling_stop_fallback' else f"允许温控，制冷设定{s['cooling_setpoint_C']:g}℃"


def render(root,out,hid='project-demo-000001'):
    root=Path(root);out=Path(out);samples=sorted((x for x in read(root/'PUBLIC_SAMPLES.json') if x['household_id']==hid),key=lambda r:r['date'])
    if len(samples)!=10:raise ValueError('TEN_SELECTED_DAYS_REQUIRED')
    lines=['# 同一家庭十天：第三版实际选题逐项说明','',
        '家庭ID：'+hid+'。以下十题全部读取最终固定目录与自动整数分配结果，没有手工换题。',
        'VPP固定18:00—19:00；每日B分别对照当天完整A，不继承前一题B的状态。',
        '十题由整数分配共同争取各设备各轴覆盖并减少重复；下表解释每个动作参与事件的依据，不意味着每题都是最优方案。',
        '这户为原公开合成的36岁单人家庭，设备为洗衣、洗碗、空调、热水箱、EV；没有独立烘干机。职业、收入和真实接受度不补造。',
        'A的洗衣程序18:20—19:20、洗碗程序20:10—20:50；具体装取与出行期限以各日完整A为准。',
        '空调A的40℃是停冷回退编码，不是室温或舒适目标；本接口没有已验证的原生可用性开关。状态转换与温差分开，实际运行未知。',
        '下文“计划减少/增加”只核算已知程序与EV的名义负荷；实际全屋用电、电费、室温、热水、SOC、物理成功/失败及人的接受均未计算。','']
    compact=[]
    for sample in samples:
        pair=read(root/'pairs'/(sample['id']+'.json'));row=pair['row'];c=read(root/'contexts'/(row['case_id']+'.json.gz'));a,b=pair['A'],pair['B']
        lines+=['## '+sample['date'],'','改变'+str(len(row['changed_assets']))+'台设备；独立单元'+str(row['independent_units'])+'个。','',
            '| 设备 | A→B的实际提议 | 为什么参与 |','|---|---|---|']
        changes=[]
        for comp in row['components']:
            family=comp['family'];aid=comp['asset_id'];m=comp['magnitude'];details=[]
            if family=='ac':
                ac=m['ac_intervention']
                details=[interval(p)+'：'+ac_value(p['A'])+' → '+ac_value(p['B']) for p in ac['phases']]
                details.append('事前调节'+str(ac['preconditioning_min'])+'分钟；新增允许温控'+str(ac['additional_thermostat_enabled_min'])+'分钟；停冷请求'+str(ac['cooling_stop_requested_min'])+'分钟')
                details.append('各轴：'+', '.join(k+'='+v for k,v in ac['amplitude_axes'].items() if v not in ('none','not_applicable'))+'；无整项小中大')
            elif family=='ev':
                pause=next(p for p in comp['patches'] if p['type']=='control_pause')
                end=m['original_connection_end_min']
                details=['原A允许从'+clock(pause['start_min'])+'充电；B暂停至'+clock(pause['end_min'])+'，原连接终点'+clock(end)+'不变']
                if m['energy_shortfall_kWh']>1e-8:details.append(f"名义缺能{m['energy_shortfall_kWh']:.3f}kWh；实际SOC未知")
            elif family=='water_heater':
                for p in comp['patches']:
                    old=next(r['value_C'] for r in a['controls'] if r['asset_id']==aid and r['start_min']<=p['start_min']<r['end_min'])
                    details.append(interval(p)+f"：水箱设定{old:g}→{p['values']['value_C']:g}℃（非实际水温）")
            else:
                for p in comp['patches']:
                    old={r[p['identity']]:r for r in a[p['collection']]}
                    for r in p['rows']:
                        x=old[r[p['identity']]]
                        if (x['start_min'],x['end_min'])==(r['start_min'],r['end_min']):continue
                        name=NAMES.get(r['kind'],{'load':'装载','unload':'取出'}.get(r['kind'],r['kind']))
                        details.append(name+' '+interval(x)+'→'+interval(r))
            link=comp['event_relevance']
            if link['role']=='direct_event_request':
                why='事件内温控请求，实际响应未知' if family in ('ac','water_heater') else '暂停触及VPP，保留原补能与出行要求' if family=='ev' else '原A或B机器运行触及VPP；不要求一定减少事件电量'
            else:
                why_parts=[]
                for w in link['evidence']:
                    if 'support_operation_id' in w:
                        ops={o['operation_id']:o for o in a['operations']};zops={o['operation_id']:o for o in b['operations']}
                        own,peer=ops[w['support_operation_id']],zops[w['root_operation_id']]
                        why_parts.append('事件根改动后，原操作与另一操作在'+clock(max(own['start_min'],peer['start_min']))+'—'+clock(min(own['end_min'],peer['end_min']))+'冲突；该移时消除此新增'+('人员' if w['kind'].startswith('operator') else '空间')+'冲突')
                    else:why_parts.append('消除事件根引起的已知计划回路超限；不是实测跳闸')
                why='；'.join(why_parts)
            text='；'.join(details)
            lines.append('| '+NAMES[family]+' | '+text+' | '+why+' |')
            changes.append({'device':NAMES[family],'change':text,'reason':why,'role':link['role']})
        known=row['known_event_reduction_kWh']
        result=('已知设备计划减少' if known>1e-9 else '已知设备计划增加' if known< -1e-9 else '已知设备计划净变化为0')+(f'{abs(known):.3f}kWh' if abs(known)>1e-9 else '')
        if row['unknown_thermal_response']:result+='；温控部分未知，不能当成全屋实际收益'
        stress='；'.join(ISSUES.get(i,i) for i in row['issues']) or '未发现已登记的计划约束问题；不等于物理或用户验证通过'
        lines+=['',result+'。','',stress+'。','', '原样本ID：`'+sample['id']+'`。','']
        compact.append({'date':sample['date'],'id':sample['id'],'changes':changes,'plan_assessment':stress,'known_profile_assessment':result,'actual_outcomes':None})
    lines+=['生成命令：`python -B -m benchmark.ab_generation.validation.collection_v3.walkthrough --root /path/to/pilot --out /path/to/TEN_DAY.md`。','']
    out.write_text('\n'.join(lines))
    save(out.with_suffix('.json'),{'household_id':hid,'source_samples_sha256':sha(root/'PUBLIC_SAMPLES.json'),
        'source_assignment_sha256':sha(root/'ASSIGNMENT.json'),'records':compact,'manual_substitution':False,'new_engine_runs':0})


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',required=True);p.add_argument('--out',required=True);a=p.parse_args();render(a.root,a.out)
