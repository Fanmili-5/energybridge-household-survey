"""Export the10000 actual A plans and household-level diversity, not synthetic answers."""
import collections
import csv
from common import *

def table(path,rows):
    with path.open('w',encoding='utf-8-sig',newline='')as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)

def clock(minute):
    day=minute//1440;prefix='前日'if day<0 else '当日'if day==0 else '次日'if day==1 else str(day)+'日后'
    return prefix+f'{minute%1440//60:02d}:{minute%60:02d}'

def main():
    review=read(OUT/'ACCEPTANCE.json')
    if not review['accepted']or review['rules_sha256']!=rules_id():raise ValueError('CURRENT_A_NOT_ACCEPTED')
    folder=OUT/'review';folder.mkdir(exist_ok=True);rows=[];families=[]
    for r in read(OUT/'A_BINDINGS10000.json')['records']:
        year=read(OUT/r['annual_A_path']);w=read(OUT/r['A_world_path'])
        families.append({'家庭ID':r['household_id'],'类别':r['type'],'人数':w['N'],
            '原洗衣每周频次代理':w['source_V33_routine']['wash_count_reference_per_week'],
            '新全年洗衣批次':sum(t['kind']=='washer'and (ANCHOR+dt.timedelta(days=t['start_min']//1440)).year==2025 for t in year['tasks']),
            '原单批参考kg':w['routine']['laundry_batch_kg'],'十天实质情境数':r['unique_substantive_days'],
            '洗衣延后尝试数':r['deferred_laundry_count'],'原世界SHA256':r['master_world_sha256'],'A全年文件':r['annual_A_path']})
        for c in r['cases']:
            case=read(OUT/c['path']);date=dt.date.fromisoformat(c['date']);base=origin(date);d=year['days'][c['date']];ns=d['needs']
            ids={n['need_id']for n in ns};tasks=[t for t in year['tasks']if t['need_id']in ids];operations=[o for o in year['operations']if o['need_id']in ids]
            task_text='；'.join(t['kind']+' '+clock(t['start_min']-base)+'—'+clock(t['end_min']-base)for t in tasks)
            rows.append({'家庭ID':r['household_id'],'类别':r['type'],'日期':c['date'],'人数':w['N'],'日类型':d['activity']['day_type'],
                '天气参考最高℃':round(d['weather']['maximum_C'],1),'洗衣批次':sum(n['kind']=='washer'for n in ns),
                '洗衣kg':d['textiles']['washed_kg'],'积累待洗kg':d['textiles']['after_kg'],
                '洗碗次数':sum(n['kind']=='dishwasher'for n in ns),'洗浴人数':sum(n['kind']=='water_heater'for n in ns),
                '空调模式':','.join(sorted({n['mode']for n in ns if n['kind']=='ac'})),
                '空调房间小时':round(sum(n['quantity']for n in ns if n['kind']=='ac')/60,2),
                '出行耗电kWh':d['activity']['transport']['traction_kWh']if d['activity']['transport']else 0.,
                '程序时间':task_text,'人工操作次数':len(operations),'操作人':','.join(sorted({o['operator_id']for o in operations})),
                'A文件':c['path'],'A文件SHA256':c['sha256']})
    table(folder/'10000天A方案核对表.csv',rows);table(folder/'1000户A变化与频次.csv',families)
    save(folder/'50户A筛选清单.json',read(OUT/'SUBSET50.json'))
    examples=[]
    chosen=['ordinary-v6-0001','ordinary-v6-0031','ordinary-v6-0334','ordinary-v6-0661']
    for hid in chosen:examples.append({'household':next(r for r in families if r['家庭ID']==hid),'ten_days':[r for r in rows if r['家庭ID']==hid]})
    save(folder/'四户十天示例.json',examples)
    summary={'households':1000,'cases':len(rows),'daily_dishwasher_days':sum(r['洗碗次数']for r in rows),'daily_bathing_person_days':sum(r['洗浴人数']for r in rows),
             'laundry_batches':sum(r['洗衣批次']for r in rows),'no_minute_jitter_or_forced_skips':True,
             'unique_substantive_days_distribution':dict(collections.Counter(r['十天实质情境数']for r in families)),
             'subset50_type_counts':read(OUT/'SUBSET50.json')['type_counts'],'EP_started':0,'new_B_generated':False,
             'schedules_have_passed_resource_checks':True,'physical_delivery_validated':False}
    save(OUT/'DELIVERY_SUMMARY.json',summary);print(canonical(summary))

if __name__=='__main__':main()
