"""Optional real-household context, retained independently of the EB projection."""
from copy import deepcopy
from questionnaire_persona import question
from common import digest


def extra(qid, prompt, options, section, *, multi=False, device=None, text=False):
    q=question(qid,prompt,options,group='research_context',multi=multi)
    q.update(required=False,research_only=True,research_section=section)
    if text:q['type']='text'
    if device:q['device']=device
    return q

PROVINCES='北京 天津 河北 山西 内蒙古 辽宁 吉林 黑龙江 上海 江苏 浙江 安徽 福建 江西 山东 河南 湖北 湖南 广东 广西 海南 重庆 四川 贵州 云南 西藏 陕西 甘肃 青海 宁夏 新疆 香港 澳门 台湾'.split()
HOUSING=[
 extra('X_REGION','您家常住在哪个省级地区？',[(p,p) for p in PROVINCES]+[('outside_china','中国以外')],'housing'),
 extra('X_CITY','常住城市（无需详细地址）',[],'housing',text=True),
 extra('X_BUILDING','住房的建筑形式更接近哪一种？',[('apartment','楼房中的一套住宅'),('detached','独立住宅'),('rowhouse','联排住宅'),('other','其他住房')],'housing'),
 extra('X_TENURE','目前的居住方式是？',[('owned','自有住房'),('rented','整套租住'),('shared','与他人合租'),('other','其他安排')],'housing'),
 extra('X_AREA','您家这套住房面积大致为？（合租按整套住房）',[('lt50','不足50㎡'),('50_89','50—不足90㎡'),('90_119','90—不足120㎡'),('120_159','120—不足160㎡'),('ge160','160㎡及以上')],'housing'),
 extra('X_AREA_BASIS','以上面积采用哪种口径？',[('gross','建筑面积（包含公摊）'),('usable','套内可使用面积（不含公摊）')],'housing'),
 extra('X_FLOOR','这套住宅位于楼房的什么位置？',[('ground','底层'),('middle','中间层'),('top','顶层')],'housing'),
 extra('X_BUILDING_AGE','住宅大致建于哪个时期？',[('before2000','2000年前'),('2000_2009','2000—2009年'),('2010_2019','2010—2019年'),('since2020','2020年及以后')],'housing'),
]
for q in HOUSING:
    if q['id'] in ('X_REGION','X_CITY','X_BUILDING','X_AREA','X_AREA_BASIS','X_FLOOR'):
        q.update(environment_input=True,research_only=False,group='simulation_environment',required=False)
    if q['id']=='X_FLOOR':q['show_when']={'question_id':'X_BUILDING','value':'apartment'}
    if q['id']=='X_CITY':
        from simulation_environment import catalog
        resource_catalog=catalog()
        ready=[r for r in resource_catalog['weather'] if r['status']=='verified' and r['city']]
        q['cities_by_region']=resource_catalog.get('administrative_cities') or {province:list(dict.fromkeys(r['city'] for r in ready if r['province']==province)) for province in PROVINCES}
        q['help']='城市选项随省份变化。同城有气象站时优先使用；否则采用省内代表站，并在下方注明。列表以2023年地区资料为基础，可自行填写未列出的城市。'
    if q['id']=='X_AREA_BASIS':q['help']='模型按面积区间代表值生成；建筑面积暂按80%估计室内面积。这是统一研究假设。'
CONTEXT=[
 extra('X_INCOME','前面填写的同住家人，月总收入大致为？（人民币；其他币种可大致折算）',[('lt5000','不足5000元'),('5000_9999','5000—不足10000元'),('10000_19999','10000—不足20000元'),('20000_29999','20000—不足30000元'),('ge30000','30000元及以上')],'context'),
 extra('X_BILL','最近一个月，这些同住家人合计承担的电费大致为？（人民币；其他币种可大致折算）',[('lt100','不足100元'),('100_299','100—不足300元'),('300_599','300—不足600元'),('600_999','600—不足1000元'),('ge1000','1000元及以上')],'context'),
 extra('X_TARIFF','您家平时使用哪种电价？',[('flat','单一时段电价'),('tou','峰谷分时电价'),('other','其他计费方式')],'context'),
 extra('X_EXTRA_DEVICES','除前面的模拟设备外，您家还有哪些设备？（可多选）',[('refrigerator','冰箱'),('electric_heating','电采暖 / 热泵'),('gas_water_heater','燃气热水器'),('pv','屋顶光伏'),('battery','家庭储能'),('other','其他用能设备'),('none','没有上述设备')],'context',multi=True),
 extra('X_PROTECTED','希望用电调整尽量不要打扰哪些活动？（可多选）',[('work_study','居家工作 / 学习'),('sleep','睡眠休息'),('care','照顾家人'),('meal','做饭用餐'),('hot_water','洗澡用热水'),('none','没有特别要求')],'context',multi=True),
 extra('X_SMART','您家以前使用过定时或自动控制电器吗？',[('often','经常使用'),('sometimes','偶尔使用'),('never','没有使用过')],'context'),
 extra('X_DR','您家以前参与过错峰用电或需求响应活动吗？',[('yes','参加过'),('no','没有参加过')],'context'),
 extra('X_RESTORE','假设自动安排影响原来的生活习惯，您家更倾向怎样做？',[('prefer_keep','保留自动安排'),('prefer_consider','先看影响再决定'),('prefer_restore','改回原安排')],'context'),
]
INVENTORY=[]
for device,label in [('ac','空调'),('washer','洗衣机'),('dishwasher','洗碗机'),('dryer','烘干机'),('home_ev','可在家充电的电动汽车（含插混，不含电动自行车）'),('electric_water_heater','电热水器')]:
    unit='辆' if device=='home_ev' else '台'
    frequency_prompt=f'在本次指定月份，通常一周有几天在家为电动汽车充电？（含插混，不含电动自行车）' if device=='home_ev' else f'在本次指定月份，通常一周有几天使用{label}？'
    INVENTORY.extend([
        extra('X_COUNT_'+device,f'家里有几{unit}{label}？',[('1',f'1{unit}'),('2',f'2{unit}'),('3_plus',f'3{unit}及以上')],'inventory',device=device),
        extra('X_FREQ_'+device,frequency_prompt,[('days_0','0天'),('days_1','1天'),('days_2_3','2—3天'),('days_4_6','4—6天'),('days_7','每天（7天）')],'inventory',device=device),
    ])
QUESTIONS=HOUSING+CONTEXT+INVENTORY


def build_record(profile, questions, *, household_id, raw_answers, questionnaire_version, submitted_at):
    """Snapshot-first research record. No inferred member attitudes or EP parameters."""
    research={q['id']:{**deepcopy(profile[q['id']]),'question':q['prompt'],'options':deepcopy(q['options'])}
              for q in questions if q.get('research_only')}
    members=deepcopy(profile.get('M_MEMBERS',{}))
    values=members.get('value') or []
    ages={k:sum(m.get('age_band')==k for m in values) for k in ('under18','adult','older')}
    ages['unreported']=sum(not m.get('age_band') for m in values)
    return {'schema_version':'eb.real_household_record.v1','household_id':household_id,
        'identity_scope':'browser_session_proxy_not_verified_unique_household',
        'submitted_at':submitted_at,'questionnaire_version':questionnaire_version,
        'questionnaire_snapshot':deepcopy(questions),'questionnaire_hash':digest(questions),
        'raw_answers':deepcopy(raw_answers),'normalized_answers':deepcopy(profile),
        'reported_members':members,'research_context':research,
        'reported_housing':{q['id']:deepcopy(profile[q['id']]) for q in questions if q.get('environment_input')},
        'derived_facts':{'member_count':len(values),'reported_age_counts':ages,'source_question_id':'M_MEMBERS','rule_version':'count_reported_members_v1'},
        'analysis_features':{'status':'candidate_not_fitted','uses_event_feedback':False,
            'research_answers':{k:deepcopy(v) for k,v in profile.items() if k in research or k=='M_MEMBERS' or any(q['id']==k and q.get('environment_input') for q in questions)}},
        'environment_readiness':__import__('simulation_environment').inspect_profile(profile),
        'eb_projection':{'version':'eb.real_household_projection.v2',
            'included_question_ids':[q['id'] for q in questions if not q.get('research_only')],
            'research_only_question_ids':list(research),
            'simulation_binding':'housing_fields_resolved_per_job; inspect environment_readiness',
            'notes':'Environment fields select registered research weather and geometry; raw answers are preserved. Other research-only answers do not change physical parameters. No synthetic member weights or votes.'}}
