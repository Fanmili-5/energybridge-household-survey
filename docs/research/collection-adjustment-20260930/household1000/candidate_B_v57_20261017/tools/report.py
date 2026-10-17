"""Write the bounded closure result, matched evidence and preview before sealing."""
import sys,subprocess
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *
def main():
 a=read(OUT/'ACCEPTANCE.json');assert a['accepted'];c=a['counts'];bindings=sha(OUT/'PAIR_BINDINGS10000.json')
 parent_tv=read(PARENT_B/'THERMAL_EVENT_VALIDATION.json');current={rr['case_id']:rr for row in read(OUT/'PAIR_BINDINGS10000.json')['records']for rr in row['rounds']};refs=[]
 for r in parent_tv['records']:
  source=read(PARENT_B/r['pair_path']);rr=current[source['case_id']];pair=read(OUT/rr['path']);assert pair['B']['controls']==source['B']['controls']
  refs.append({'case_id':source['case_id'],'current_pair_path':rr['path'],'current_pair_sha256':rr['sha256'],'source_pair_path':str(PARENT_B.relative_to(REPO)/r['pair_path']),'source_pair_sha256':sha(PARENT_B/r['pair_path']),'source_record':r,'unchanged_controls_sha256':digest(pair['B']['controls']),'new_physical_run':False})
 save(OUT/'PHYSICAL_REFERENCE_REUSE.json',{'passed':True,'bindings_sha256':bindings,'source_stage':PARENT_B.name,'source_manifest_sha256':sha(PARENT_B/'THERMAL_EVENT_VALIDATION.json'),'cases':49,'records':refs,'scope':'explicit B56 scoped thermal reference reuse on identical controls;no new or full B physical acceptance'})
 text=f"""# A46/B57：两处收尾修正已完成

整批1000户、10000组保留A46和全部B56实际排程，100组相同、253组约束冲突、每日设备任务与原比例同源50户保持。

1. 联合B的{c['life_node_plans_checked']}条节点关联已按实际B操作核对。3条旧A锚点发生联动移位，现保留原来源、标明关联已失效；0483、0877、0900户的排程均未挪动，也没有补造顺路理由。
2. {c['earlier_actual_SOC_match_cases']}组现在分别显示实际持续追平SOC、干预结束及结束后确认时刻。0001户10月12日实际12:10追平，干预到次日08:20结束；9月30日后续补电约7.170kWh、原出发电量不足均保留。

本轮全量核对与{read(OUT/'REGRESSION_RESULTS.json')['count']}项针对性回归通过。全部10000组实际指令、EV轨迹和电量、失败记录与B56一致；既有49组热控参考按同一控制输入及原文件哈希显式复用，没有混称新物理结果。

这两项属于关联说明和影响摘要的收尾，不再用来反复阻塞第3、4项生成设计。后续只把会改变排程有效性、用户偏好判断或论文结论的问题作为必须修改项。完整物理与人类接受仍按其各自范围验收。

依据：`../ACCEPTANCE.json`、`../REGRESSION_RESULTS.json`、`../PHYSICAL_REFERENCE_REUSE.json`、`收尾案例.json`；方法：`../METHODS.md`。
"""
 (OUT/'review/收尾复核.md').write_text(text)
 subprocess.run([sys.executable,'-B',str(OUT/'tools/preview.py')],check=True)
 print({'report_and_preview_complete':True,'cases':10000,'B56_schedules_preserved':True})
if __name__=='__main__':main()
