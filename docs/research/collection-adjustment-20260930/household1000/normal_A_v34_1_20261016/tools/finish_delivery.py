"""Seal repair journals and clear review labels without changing A generator bytes."""
import csv
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from common import *

folder=OUT/'review';p=folder/'10000天A方案核对表.csv'
with p.open(encoding='utf-8-sig',newline='')as f:rows=list(csv.DictReader(f))
rename={'空调房间小时':'空调计划运行设备小时','出行耗电kWh':'给定出行电量kWh','洗浴人数':'目标热水器服务人数','人工操作次数':'本批任务关联操作数（含跨日）','程序时间':'本批程序时间（可跨日）'}
rows=[{rename.get(k,k):v for k,v in r.items()}for r in rows]
with p.open('w',encoding='utf-8-sig',newline='')as f:
    wr=csv.DictWriter(f,fieldnames=list(rows[0]));wr.writeheader();wr.writerows(rows)
(OUT/'METHODS_AND_REPAIR.md').write_text('''# A复核修正V34.1

1000户与原十日期保持。以V34实际年度A为父版本，只修正既有车辆连接内的充电时段，避免EV、固定家电程序与背景负荷叠加超过给定入户容量。必要时保持连接自动暂停后续充；不增加插拔操作，不扩大电容量，不修改家庭、设备、需求、行程或家电程序。

REPAIR_SUMMARY.json记录71户、全年9703次连接的自动充电安排调整，其中2次需要自动分段。每户重生成日志与初次失败尝试保留。A_BINDINGS10000.json统一绑定新年度A、10000个案例、未改变的资源世界和HVAC组件。50户引用完全相同的主记录。

每天使用所有已配设备仍是给定benchmark条件。参考天气选择制冷、制热和送风，不能替代室温计算。固定负荷容量检查不涵盖空调、水箱和非额定峰值的完整物理结果；完整EnergyPlus组装与仿真仍待进行。

表中空调小时按设备实例相加，不是压缩机实测运行时长；给定出行电量是电池侧任务，不是电网耗电；目标热水器服务人数只统计本模型已配设备；操作数包含跨日同批任务。没有真人接受度答案。

静态复现入口为scripts/normal_a.py；源代码与输入锁、两次运行、1000户日志、年度及案例散列封存。继承的HVAC组件逐字保持V34文件，可溯源其已有schema校验；不冒充本阶段新增物理仿真。
''')
sig=rules_id();run=OUT/'runs'/sig[:16]
manifest={'files':{str(p.relative_to(OUT)):sha(p)for p in folder.iterdir()if p.is_file()},'rules_sha256':sig}
save(OUT/'REVIEW_EXPORT_MANIFEST.json',manifest)
seal=read(OUT/'FINAL_SEAL.json')
files=[OUT/'REPAIR_SUMMARY.json',OUT/'METHODS_AND_REPAIR.md',OUT/'REVIEW_EXPORT_MANIFEST.json',Path(__file__)]+list(folder.iterdir())+list((run/'regeneration').glob('*.json'))+list((run/'source_snapshot').iterdir())
seal['stage_files'].update({str(p.relative_to(OUT)):sha(p)for p in files if p.is_file()});seal['repair_parent']='normal_A_v34_20261016';seal['reference_world_and_hardware_unchanged']=True
save(OUT/'FINAL_SEAL.json',seal)
pointer=read(BASE/'CURRENT_NORMAL_A_INPUTS.json');pointer['seal_sha256']=sha(OUT/'FINAL_SEAL.json');pointer['schema']='eb.current_normal_A.v34.1';pointer['repair_summary_sha256']=sha(OUT/'REPAIR_SUMMARY.json');pointer['review_exports_manifest_sha256']=sha(OUT/'REVIEW_EXPORT_MANIFEST.json')
save(BASE/'CURRENT_NORMAL_A_INPUTS.json',pointer);save(REPO/'docs/household1000/CURRENT_NORMAL_A.json',pointer)
print({'repair_journals_sealed':1000,'review_rows':len(rows),'seal_sha256':pointer['seal_sha256']})
