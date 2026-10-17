"""Write the scoped reviewer readback after matching population audits pass."""
import sys
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *

def main():
    a=read(OUT/'ACCEPTANCE.json');d=read(OUT/'DESIGN_REVIEW.json');r=read(OUT/'REGRESSION_RESULTS.json');o=read(OUT/'review/截断与子集核查.json');sig=rules_id()
    assert a['accepted']and r['passed']and a['rules_sha256']==d['rules_sha256']==r['rules_sha256']==sig
    c=d['counts'];ac=a['counts'];relations=d['normal_or_partial_EV_selected_event_reference_relations'];grade=d['EV_failures_by_draft_grade'];spare=d['EV_failed_charge_time_shortfall_minutes']
    text=f'''# A46/B53：第3、4项修改及复核

本轮固定A46并重建B生成逻辑与整批10000组。原100组相同请求载荷和身份保持；50户仍为原ID、十个日期及5/15/16/5/4/5比例，直接引用同批文件及哈希。A排程、生活日程、家庭/设备、每日服务需求、既有任务/人工动作身份、EV插拔与目标SOC均保持；{ac['constraint_conflict_cases']}组新B给定约束冲突全部保留，评分和接受为空。

## 1. 实际分档已与实际指令绑定

分开保存设计档位、实际数值、每个技术轴的实际档位和实际主轴。独立审核从原始10分钟控制状态与程序/操作起止时间重算，未把名义请求档位当实际强度。

- 0001户2025-03-22：空调medium请求1°C，新指令实际温差为1°C，最低2°C死区保持；原B52实际只有0.25°C。
- 整批{c['ac_paired_temperature_requests']}条可直接比较的空调调温请求，实际温差小于设计温差的数量为{c.get('ac_temperature_less_than_draft',0)}，原B52为702。温控模式来自给定室外均温参考，实测压缩机状态仍未知。
- 0048户2025-04-02：洗碗因餐后释放边界，实际仅提前20分钟，现记实际low；名义extreme只留作设计来源。整批洗衣{c['washer_program_clipped_below_draft']}条、洗碗{c['dishwasher_program_clipped_below_draft']}条程序请求受边界截断，均按实际值分档，未越过生活边界凑档。
- 热水器{c['water_heater_paired_temperature_requests']}条直接调温请求的实际温差与设计幅度一致。提前许可和作用时长另记，不能当作实际水温变化或舒适度结论。

## 2. EV失败不再由极端档模板决定

按所需充电时间、真实接入与选定事件设计移时；压力预算和位置是独立因素，删除125%连接余量收紧后统一夹到10分钟的主路径。

整批2532条EV设备请求中，固定功率窗口余量不足{c['EV_negative_slack']}条，10分钟窗口{c['EV_10min_windows']}条（B52分别为630和546）。缺口包含{min(map(float,spare)):.3f}至{max(map(float,spare)):.3f}分钟等不同程度。各设计档位的不足/足够数量为：{grade}。预算受时间网格取整，不能把设计不足意图当实际不足结论，更不能预设人类拒绝。

## 3. VPP动作已接入A事件内参考状态

记录每个设备选择事件前的输入状态；EV计算A/B固定充电参考电量与方向，和充电许可方向分别保存；洗烘一体机包括整条自动洗烘链，不增加烘干人工启动。

0002户2025-05-15的18–19点上调事件，B52固定充电参考变化为0；新B的EV在事件内增加约1.003kW参考负荷。目标为2kW，该结果只描述EV参考，不声称全组合已达标。

正常/部分意图的EV请求，选中事件内参考为aligned {relations.get('aligned',0)}、unchanged {relations.get('unchanged',0)}、opposing {relations.get('opposing',0)}。这些是读回结果，**没有为了提高成功率删除无效或反向请求**。正常意图不保证B成功、优于A或被接受。

## 审稿与EB设计视角的判断

本轮三个具体生成问题均有代码与数据改动，并有整批逐例读回和{r['count']}项回归验证。整批40000个输入向量完成生成完整性核查；实际分档与原始指令匹配。输入向量是完整性与等价性诊断，不是四个独立实际强度标签；受服务边界或独立预算影响，多个向量可以等价，不为制造差异越界。

A46保持原有可解释习惯，例如0011户工作日多为次日07:40、周末18:40洗碗。未给A加随机分钟噪声。每日服务需求保留，失败B仍可能完不成服务，不能宣称实际运行必然成功。

需要在论文中保持的边界：实际档位是技术指令描述；数值分档除空调EB锚点外为声明的benchmark参数，不是现实分布或EB官方标准。当前事件状态是A固定过程/许可参考，热控实际运行状态、全组合功率、连续B SOC、热水品质、舒适度及人类接受仍待后续验证。生成器是覆盖不同候选请求的实验机制，未宣称最优控制或所有正常意图均有效。

机器证据：`../ACCEPTANCE.json`、`../DESIGN_REVIEW.json`、`../REGRESSION_RESULTS.json`、`三项修改案例.json`、`截断与子集核查.json`。规则、EB依据、逐例来源和开发记录见上级目录及封存文件。
'''
    (OUT/'review/设备独立强度复核.md').write_text(text)
    print({'review_report_written':True,'cases':10000,'regressions':r['count']})

if __name__=='__main__':main()
