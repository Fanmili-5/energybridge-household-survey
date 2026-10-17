"""Clarify review-table units and make a short, source-bound Chinese example."""
import csv
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from common import OUT,read,save,sha,rules_id

def main():
    report=read(OUT/'ACCEPTANCE.json')
    if not report['accepted']or report['rules_sha256']!=rules_id():raise ValueError('CURRENT_A_NOT_ACCEPTED')
    folder=OUT/'review';path=folder/'10000天A方案核对表.csv'
    with path.open(encoding='utf-8-sig',newline='')as stream:rows=list(csv.DictReader(stream))
    rename={'空调房间小时':'空调计划运行设备小时','出行耗电kWh':'给定出行电量kWh','洗浴人数':'目标热水器服务人数',
            '人工操作次数':'本批任务关联操作数（含跨日）','程序时间':'本批程序时间（可跨日）'}
    rows=[{rename.get(k,k):v for k,v in r.items()}for r in rows]
    with path.open('w',encoding='utf-8-sig',newline='')as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    (folder/'列定义与限制.md').write_text('''# 排程表的计量定义

空调计划运行设备小时按每台空调实例相加；同一房间两台会计两份，不能当作不重复的房间占用小时，也不是压缩机实际运行小时。

给定出行电量是交通任务的电池侧需求，不是实测耗电或电费。本批任务关联操作数按该批任务归属日期列出，包含以后日期的取出或出发前拔下。程序时间保留跨日端点。

目标热水器服务人数只统计进入本模型自有电热水器的任务；无此设备不代表该户不洗浴。所有设备每日覆盖还另外按08:00至次日08:00的实际计划运行区间检查。

模式和控制窗口由模拟条件给定。室温、热水是否达标、真实制热耗电及舒适度仍待物理仿真；表中没有真人接受度答案。
''')
    chosen=['ordinary-v6-0001','ordinary-v6-0319','ordinary-v6-0334','ordinary-v6-0661']
    bindings=read(OUT/'A_BINDINGS10000.json')['records'];text=['# 四户A方案实例','',
        '均来自同一1000户主数据；已配设备每天使用是给定benchmark条件。以下列出原十日期，不额外选好看的日期。','']
    for hid in chosen:
        r=next(r for r in bindings if r['household_id']==hid);w=read(OUT/r['A_world_path'])
        text+=['## '+hid,'',f'人数：{w["N"]}；成员年龄：'+ '、'.join(str(m['age_years'])for m in w['members'])+'。',
               '','| 日期 | 日类型 | 洗衣kg | 本批程序时间 | 空调模式 | 给定出行kWh |','| --- | --- | --- | --- | --- | --- |']
        for item in[r for r in rows if r['家庭ID']==hid]:
            text.append('| '+' | '.join(item[k]for k in('日期','日类型','洗衣kg','本批程序时间（可跨日）','空调模式','给定出行电量kWh'))+' |')
        text+=['']
    (folder/'四户A方案简明示例.md').write_text('\n'.join(text)+'\n')
    outputs=[path,folder/'1000户A变化与频次.csv',folder/'50户A筛选清单.json',folder/'四户A方案简明示例.md',folder/'列定义与限制.md',folder/'HVAC_COMPONENT_SCHEMA_REVIEW.json']
    if(folder/'WORLD_INVARIANTS_REVIEW.json').exists():outputs.append(folder/'WORLD_INVARIANTS_REVIEW.json')
    save(OUT/'REVIEW_EXPORT_MANIFEST.json',{'rules_sha256':rules_id(),'postprocessor_sha256':sha(__file__),
        'files':{str(p.relative_to(OUT)):sha(p)for p in outputs},'display_labels_clarified_without_changing_generated_A':True})
    print({'review_rows':len(rows),'examples':len(chosen),'numeric_A_data_changed':False})

if __name__=='__main__':main()
