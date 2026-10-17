"""Build a review from the regenerated complete-occupancy summaries."""
from regenerate import *


def main():
    b=read(ROOT/'SUMMARY_BINDINGS50.json');summaries={r['case_id']:read(ROOT/r['path'])for r in b['records']}
    coverage=read(ROOT/'COVERAGE50.json');diagnosis=read(SOURCE/'DIAGNOSIS0490.json')
    shifted=summaries['ordinary-v6-0490__2025-03-01'];room=next(r for r in shifted['thermal_impacts']['rooms']if r['room']=='WASHROOM')
    cold=summaries['ordinary-v6-0490__2025-01-01'];coldroom=next(r for r in cold['thermal_impacts']['rooms']if r['room']=='WASHROOM')
    own=room['primary']['B']['other_arm_empty_exposure'];sensitive=coverage['sensitive_case_ids']
    lines=['# 50户500组：完整温度暴露与跨季节验证复核（摘要V62）','',
      '本轮以物理V61重跑结果实际重生成500份影响摘要和500份逐室温度时间序列。原A46/B57指令和B失败保持；50户仍按同一主数据5/15/16/5/4/5户。1000户继续暂缓。','',
      '## 已补齐的实际占用暴露','',
      'A、B各自给出所有实际停留的起止时刻、时长、空气/辐射温度和湿度范围、描述性温度分布及人时；新增或错开的停留单列“另一方案此房间无人”暴露。保留共同占用温差，并另给各自有人时同一时刻的B−A温差时长。后者描述参考物理状态，不冒充同一个人在两套方案中的主观舒适差。','',
      f"0490户3月1日：B在卫生间17:00的新增停留已进入完整暴露；本例另一方案该房间无人时的B停留共{own['occupied_minutes']}分钟。现在可以读出这些时段的温度及持续时间，不再只给共同有人时的温差。",'',
      '绝对温度分箱和0.2/0.5/1/2℃温差分档只描述物理分布；按10分钟报告区间近似计时，未赋予舒适、接受或拒绝标签。逐室主期08:00至次日08:00与后续观察期分别统计。','',
      '## 0490冬季低温已核实并修复模型边界','',
      f"1月1日，旧模型把小卫生间排风的补气直接取自约−13℃室外，叠加烘干/浴室排风与隐私关门，B最低为{diagnosis['old_occupied_air_ranges']['B'][0]:.2f}℃。改为沿原门洞、由入口/走廊补风的原生质量守恒模型后，原指令下本版B有人时最低为{coldroom['primary']['B']['occupied_air_temperature_range_C'][0]:.2f}℃；没有增加供热、温度截断、开门操作或移动排程。",'',
      '所有500组均用同一修订模型重跑，避免只修个别异常。补风路径仍是明确给定的参考设计，尚无现场压差或温度校准，故不能把新值称为真实住户实测温度。详见[物理原因与全批复核](../unified_physics50_v61_20261017/REVIEW50.md)。','',
      '## 敏感性范围与实际结果','',
      '| 项目 | 本轮实际覆盖 |','|---|---:|',
      '| 完整占用温度摘要/时间序列 | 500/500 |',
      '| 跨冬春夏秋及极端案例并集 | 200组 |',
      '| 不同有效前史 | 179组112/224天；21组7天/实际可用前史 |',
      '| 门洞交换0.5/2倍 | 200组、400次 |',
      '| 渗透0.175/0.7ACH | 16个极端案例、32次 |',
      '| 有效对照总数 | 632次 |',
      '| 尚未逐例做敏感性实验 | 300组 |','',
      f"选择原因覆盖计数：{json.dumps(coverage['season_reason_counts'],ensure_ascii=False,sort_keys=True)}。6个家庭×季节没有已有日期，逐项列入COVERAGE50.json，不假称每户四季齐全。",'',
      f"{len(sensitive)}个案例、{coverage['sensitive_comparisons']}次对照达到敏感标记；原样保留，范围随各例实际完成的因素显示。绝对温度变化与A/B差值变化分别记录：本轮{len(coverage['absolute_occupied_temperature_sensitive_case_ids'])}个已测试案例在至少一个因素下的有人时绝对空气温度变化超过0.2℃；这限制精确的实测温度宣称，不等于相同数量的B失败或拒绝。不能用A/B差值较稳定替代绝对温度已验证。",'',
      '这些是单因素、主24小时的实际情景范围，不是置信区间、保证边界或全恢复期验证。全部500组仍是同一批benchmark数据；实验覆盖范围不构成数据拆分。','',
      '## 修改后复核结论','',
      '本轮两处缺口已实际处理：完整记录两方案各自停留的温度暴露，并扩展到非夏季和已知极端工况的敏感性验证；发现的局部室外补风边界问题已在模型中修复并重跑全批。电量变化、任务交付/失败、状态恢复与温度影响继续分开展示，不自动推断等舒适节能、B成功或接受标签。','',
      '论文仍需限定为给定EB设备、住房、气象和补风条件的参考情境；300个未测日期、联合参数扰动、整个后续恢复期及现场绝对精度尚无本轮验证证据。这些范围限制不靠挪动排程或删掉敏感案例消除。','',
      '[500组索引](SUMMARY_BINDINGS50.json) · [独立读回](VERIFICATION50.json) · [覆盖范围](COVERAGE50.json) · [摘要规则](SUMMARY_POLICY.json)','']
    (ROOT/'REVIEW50.md').write_text('\n'.join(lines));print(json.dumps({'report_written':True,'cases':500,'sensitivity_cases':200}))


if __name__=='__main__':main()
