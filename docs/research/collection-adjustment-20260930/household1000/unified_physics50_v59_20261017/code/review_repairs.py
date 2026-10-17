"""Reviewer evidence on all500 cases and the original named counterexamples."""
from core import *
import collections

PARENT=BASE/'unified_physics_v58_20261017'

def summaries(stage):
    bindings=read(stage/'PHYSICAL_BINDINGS50.json')if(stage/'PHYSICAL_BINDINGS50.json').exists()else read(stage/'results/pilot50/REVIEW.json')
    return {r['case_id']:read(stage/r['path'])for r in bindings['records']}

def extremes(data):
    rows=list(data.values())
    initial_saturated=[d['case_id']for d in rows if any(v['A']>=99.999 for k,v in d['specified_initial_state']['channels'].items()if k.startswith('Zone Air Relative Humidity|'))]
    occupied_hot=[d['case_id']for d in rows if any(e['A_occupied_temperature_range_C']and e['A_occupied_temperature_range_C'][1]>40 for e in d['temperature_exposure'])]
    return {'A_initial_RH100_cases':len(initial_saturated),'A_initial_RH100_case_ids':initial_saturated,
            'A_occupied_over40C_cases':len(occupied_hot),'A_occupied_over40C_case_ids':occupied_hot,
            'A_max_occupied_temperature_C':max(e['A_occupied_temperature_range_C'][1]for d in rows for e in d['temperature_exposure']if e['A_occupied_temperature_range_C'])}

def main():
    before=summaries(PARENT);after=summaries(ROOT)
    if len(after)!=500 or set(after)!=set(before):raise ValueError('SAME_ORIGINAL500_CASES')
    manifest=read(ROOT/'INPUT_MANIFEST.json');unchanged=[]
    for row in manifest['records']:
        if sha(ROOT/row['path'])!=sha(PARENT/row['path']):raise ValueError('HOUSEHOLD_CHANGED')
        for c in row['cases']:
            if sha(ROOT/c['path'])!=sha(PARENT/c['path']):raise ValueError('PAIR_CHANGED')
            if after[c['case_id']]['source_pair_sha256']!=before[c['case_id']]['source_pair_sha256']:raise ValueError('PAIR_ASSOCIATION_CHANGED')
            unchanged.append(c['case_id'])
    examples=[]
    ids=['ordinary-v6-0181__2025-05-21','ordinary-v6-0375__2025-07-17','ordinary-v6-0828__2025-07-17','ordinary-v6-0101__2025-07-09','ordinary-v6-0398__2025-12-26']
    for cid in ids:
        a,b=before[cid],after[cid]
        examples.append({'case_id':cid,'source_pair_sha256':b['source_pair_sha256'],
            'old_A_occupied_temperature_ranges':{r['room']:r['A_occupied_temperature_range_C']for r in a['temperature_exposure']},
            'new_A_occupied_temperature_ranges':{r['room']:r['A_occupied_temperature_range_C']for r in b['temperature_exposure']},
            'old_max_initial_RH_percent':max(v['A']for k,v in a['specified_initial_state']['channels'].items()if k.startswith('Zone Air Relative Humidity|')),
            'new_max_initial_RH_percent':max(v['A']for k,v in b['specified_initial_state']['channels'].items()if k.startswith('Zone Air Relative Humidity|')),
            'new_electricity_comparison':b['electricity_comparison'],
            'new_B_service_outcomes':b['B']['service_outcomes'],
            'new_simulation_uncertainty':b['simulation_uncertainty']})
    failed=[d for d in after.values()if not d['electricity_comparison']['equal_service_and_recovery_verified']]
    if any(d['electricity_comparison']['equal_service_net_reduction_kWh']is not None for d in failed):raise ValueError('SERVICE_FAILURE_AS_SAVINGS')
    history=read(ROOT/'INITIALIZATION_REVIEW.json');air=read(ROOT/'AIRFLOW_SENSITIVITY_REVIEW.json')
    report={'schema':VERSION,'passed':True,'review_scope':'same500 actual physics,service consequences and bounded sensitivity;not field calibration',
        'physics_sha256':physics_hash(),'cases':500,'unchanged_source_cases':len(unchanged),'household_packs_unchanged':50,
        'A_B_requests_modified':False,'all_B_failures_retained':True,'evaluation_inclusion_changed':False,'human_labels_created':0,
        'parent_extremes':extremes(before),'new_extremes':extremes(after),
        'same_service_energy_interpretations':dict(collections.Counter(d['electricity_comparison']['interpretation']for d in after.values())),
        'noncomparable_cases_have_no_savings_value':True,
        'history_diagnostics':{'cases':history['cases'],'absolute_pointwise_outliers':sum(not r['within_predeclared_bounds']for r in history['records']),
            'distinct_effective_history_cases':history['distinct_effective_history_cases'],
            'robust_distinct_history_cases':history['robust_distinct_history_cases'],
            'conditional_comparisons_robust':history['conditional_comparisons_robust'],
            'max_occupied_contrast_sensitivity_C':max(r['contrast_sensitivity']['occupied_air_temperature_contrast_sensitivity_C']for r in history['records']),
            'max_energy_contrast_sensitivity_kWh':max(r['contrast_sensitivity']['energy_contrast_sensitivity_kWh']for r in history['records'])},
        'airflow_diagnostics':{'cases':air['cases'],'comparisons':air['comparisons'],'conditional_comparisons_robust':air['conditional_comparisons_robust']},
        'examples':examples,'remaining_scope':'declared reference ventilation/door policy,typical-year weather,EB single-node tank,no empirical building calibration;all sensitivity exceptions remain explicit'}
    save(ROOT/'THERMAL_REPAIR_REVIEW.json',report)
    old=report['parent_extremes'];new=report['new_extremes'];h=report['history_diagnostics']
    lines=['# 50户500组：三项修改后的复核','',
        'A46/B57排程、原50户和全部500组保留。V58封存不动，本版独立生成完整新物理结果；1000户继续暂缓。','',
        f"1. 失败与节能：全观察期记录堵塞、未取出和SOC不足。0181户5月21日的后续8批洗烘未执行如实保留，其少用电不再生成等服务节能值。全部500组仍在同一批，接受/拒绝未预填。",'',
        f"2. 热环境：已把原门洞接入房间间空气交换，补齐厨卫/烘干排风，单独计入背景风机。原初态饱和湿度案例{old['A_initial_RH100_cases']}组→{new['A_initial_RH100_cases']}组；有人占用时超过40℃案例{old['A_occupied_over40C_cases']}组→{new['A_occupied_over40C_cases']}组。参数在新结果前声明，未裁剪温湿度。",'',
        f"3. 初态敏感性：原50户第1/第6日期共100组，112/224天历史逐组比较A/B差值和VPP判断；{h['conditional_comparisons_robust']}/100在预先声明的差值界限内，最大占用温差敏感性{h['max_occupied_contrast_sensitivity_C']:.4f}℃。门洞交换量0.5/2倍共100次比较，有{air['conditional_comparisons_robust']}/100在同一界限内。超界和未单独验证情形均明确标注，不删样或改阈值。",'',
        '可支持的结论：公开住房、通风、设备、天气和初态条件下的A/B物理后果比较。门状态与交换量仍是参考条件，不是中国家庭实测；不能据此声称普遍真实节能或逐户绝对温湿度预测精度。具体旧/新案例及全部诊断见同名JSON、REVIEW_CASES50.json及各组PHYSICAL_SUMMARY.json。','']
    (ROOT/'THERMAL_REPAIR_REVIEW.md').write_text('\n'.join(lines))
    print(canonical({k:v for k,v in report.items()if k not in('examples','parent_extremes','new_extremes')}))

if __name__=='__main__':main()
