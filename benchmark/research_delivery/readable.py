"""Chinese two-household walkthrough derived from the exact selected patches."""
import argparse
from pathlib import Path
from benchmark.ab_generation.common import read
from benchmark.ab_generation.unified.validation import PAIR,clock


NAMES={'washer':'洗衣','dryer':'烘干','dishwasher':'洗碗','ac':'空调','water_heater':'热水箱','ev':'车辆充电','load':'装入','unload':'取出'}


def build(out,collection=None):
    out=Path(out);materials=read((Path(collection) if collection else out/'fifty')/'MATERIALS.json.gz')
    lines=['# 两户十天：原A与独立新版B','',
        '原家庭事实、日程和原A不变；下列B来自封存的新版候选和选择记录，不是人工编排。固定VPP为18:00—19:00。',
        '每题独立对照当天A；完整未来A仅供声明的离线实验。所有B均为待确认提案，没有执行同意、真人答案或对应物理结果。',
        '40℃若出现，表示原路径的停冷回退编码，不是家庭舒适温度。表内阈值不是实测室温。','']
    for hid in PAIR:
        lines+=['## '+hid,'','十天使用同一份已冻结v3画像；新画像不是旧A的因果来源。','',
            '| 日期 | A→B的完整修改 | 入选所呈现的取舍 |','|---|---|---|']
        for m in sorted((x for x in materials if x['household_id']==hid),key=lambda x:x['date']):
            row=m['proposal'];details=[]
            for c in row['components']:
                changes=[];label=NAMES[c['family']]
                if c['family']=='ev':
                    pause=c['magnitude'].get('permission_pause_interval_min')
                    if pause is None:
                        p=next((p for p in c['patches'] if p['type']=='control_pause'),None)
                        if p:pause=[p['start_min'],p['end_min']]
                    if pause:changes.append('B请求暂停允许充电'+clock(pause[0])+'—'+clock(pause[1]))
                    changes.append('连接、出行及目标SOC不变；名义补能缺额'+str(round(c['magnitude'].get('energy_shortfall_kWh',0),3))+'kWh')
                else:
                    for p in c['patches']:
                        if p['type']=='rows':
                            originals={x[p['identity']]:x for x in m['A'][p['collection']]}
                            for b in p['rows']:
                                a=originals[b[p['identity']]]
                                if (a['start_min'],a['end_min'])!=(b['start_min'],b['end_min']):
                                    changes.append(NAMES.get(b.get('kind'),'程序')+' '+clock(a['start_min'])+'—'+clock(a['end_min'])+'→'+clock(b['start_min'])+'—'+clock(b['end_min']))
                        elif p['type']=='control_interval':
                            a=next(x for x in m['A']['controls'] if x['asset_id']==p['asset_id'] and x['kind']==p['kind'] and x['start_min']<=p['start_min']<x['end_min'])
                            v=[]
                            for k,value in p['values'].items():
                                if k=='value_C' and p['kind']=='ac_setpoint':continue
                                if value==a.get(k):continue
                                axis={'cooling_setpoint_C':'制冷阈值','heating_setpoint_C':'加热阈值','value_C':'储水设温'}.get(k,k)
                                if k=='cooling_setpoint_C' and value==40:v.append('请求停冷回退（40℃编码）')
                                elif k=='cooling_setpoint_C' and a[k]==40:v.append('从停冷回退改为制冷阈值'+str(value)+'℃')
                                else:v.append(axis+str(a.get(k))+'→'+str(value)+'℃')
                            if v:changes.append(clock(p['start_min'])+'—'+clock(p['end_min'])+'：'+'、'.join(v))
                if c['magnitude'].get('companion_setpoint_changes'):changes.append('伴随轴为保持原冷热间距所必需，另需确认')
                role=c['event_relevance']['role'];changes.append('事件内直接作用路径' if role=='direct_event_request' else '有撤回见证的必要依赖')
                details.append(label+'：'+'；'.join(changes))
            trade=[str(row['independent_units'])+'个独立任务联合' if row['independent_units']>1 else '单任务提案']
            if row['issues']:trade.append('计划冲突/服务压力：'+','.join(row['issues']))
            if any(j['soft_preference_tension'] for j in row['judgment_context']):trade.append('存在软偏好张力')
            if any(j.get('member_opinions_differ') for j in row['judgment_context']):trade.append('成员意见有差异')
            trade.append('已知程序及名义充电模型的事件电量差='+str(round(row['known_event_reduction_kWh'],4))+'kWh（正值为减少）')
            if row['unknown_thermal_response']:trade.append('热控实际响应未知，不能把前述名义量当作全屋效果')
            trade.append('物理后果未计算；执行仍待确认')
            lines.append('| '+m['date']+' | '+'<br>'.join(details)+' | '+'；'.join(trade)+' |')
        lines+=['']
    lines+=['选择依据是同一候选目录下的归一化覆盖与重复代价，不是最大化节省或预测接受。全部原候选、诊断和选择记录均保留。',
        '表中工程完整不代表家庭应接受：例如操作不便、期限受损或授权待确认都可构成有价值的拒绝理由，但生成器不预写该答案。','']
    (out/'TWO_HOUSE_TEN_DAY.md').write_text('\n'.join(lines));return dict(households=2,slots=sum(m['household_id'] in PAIR for m in materials))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--collection');a=p.parse_args();print(build(a.out,a.collection))
