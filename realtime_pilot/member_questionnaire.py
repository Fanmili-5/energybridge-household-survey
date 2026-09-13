"""Anonymous, representative-reported members; never synthetic scoring agents."""
FIELDS = [
    {"id":"age_band","prompt":"年龄段（选填）","required":False,"options":[{"value":"under18","label":"未满18岁"},{"value":"adult","label":"18—59岁"},{"value":"older","label":"60岁及以上"}]},
    {"id":"life_roles","prompt":"平时的生活状态（可多选，选填）","type":"multi_choice","required":False,"options":[{"value":"student","label":"上学"},{"value":"outside_work","label":"在外工作"},{"value":"home_work","label":"居家工作/学习"},{"value":"retired","label":"退休"},{"value":"caregiver","label":"照顾家人"},{"value":"shift","label":"轮班工作"},{"value":"preschool","label":"尚未入学"},{"value":"not_working","label":"暂未工作（非退休）"},{"value":"other","label":"其他生活状态"}]},
    {'id':'routine','prompt':'平时主要的生活节奏（选最接近的一项）','required':True,'options':[
        {'value':'out_regular','label':'通常固定时间外出工作或学习'},
        {'value':'home_regular','label':'主要在家生活，包括居家工作、学习、休息或照护'},
        {'value':'mixed','label':'部分时间在家，部分时间外出'},
        {'value':'irregular','label':'轮班或时间经常变化'}]},
    {'id':'comfort','prompt':'对室温变化的感受','required':False,'options':[
        {'value':'temp_tolerant','label':'不太敏感，能适应一定变化'},
        {'value':'normal_comfort','label':'通常能接受小幅变化'},
        {'value':'temp_sensitive','label':'比较敏感，希望温度稳定'}]},
    {'id':'task','prompt':'对电器运行时间调整的态度','required':False,'options':[
        {'value':'flexible','label':'时间比较灵活'},
        {'value':'semi_rigid','label':'可以调整，但要在可接受的时间内'},
        {'value':'rigid','label':'更希望按固定时间安排'}]},
    {'id':'participation','prompt':'平时主要怎样参与家庭用电安排？（选最接近的一项）','required':False,'options':[
        {'value':'usually_not_involved','label':'通常不参与，由其他家人安排'},
        {'value':'usually_joint','label':'通常与家人共同商量决定'},
        {'value':'usually_decides','label':'通常主要由这位成员决定'}]},
    {'id':'needs_priority','prompt':'安排用电时，家人是否通常优先考虑这位成员的需要？','required':False,'options':[
        {'value':'yes','label':'通常会优先考虑'},
        {'value':'no','label':'没有特别优先'}]},
]
# Extra member attitudes stay independent of the household's answers.
FIELDS += [
    {'id':name,'prompt':prompt,'required':False,'options':options}
    for name,prompt,options in [
        ('cost_importance','对节省电费的重视程度（选填）',[{'value':str(i),'label':label} for i,label in enumerate(['1 不重要','2 不太重要','3 一般','4 比较重要','5 非常重要'],1)]),
        ('grid_importance','不明显影响生活时，对配合错峰用电的重视程度（选填）',[{'value':str(i),'label':label} for i,label in enumerate(['1 不重要','2 不太重要','3 一般','4 比较重要','5 非常重要'],1)]),
        ('control','对系统调整电器的主要想法（选最接近的一项，选填）',[{'value':'auto','label':'满足条件可自动安排'},{'value':'suggest','label':'先了解建议和理由，再决定怎样安排'},{'value':'confirm','label':'每次改动都必须先征得明确同意'},{'value':'manual','label':'倾向自己安排'}]),
    ]
]
QUESTION = {'id':'M_MEMBERS','type':'member_list','group':'member_profile','options':[],
            'prompt':'家里每个人的日常偏好','fields':FIELDS,'max_members':20,
            'required':True,'required_fields':['routine'],
            'help':'按您平时的了解填写，无需姓名，也不用标明哪位是您。生活节奏为必填，其余了解就填；不清楚的可以直接留空。'}

def normalize_members(value, question):
    if not isinstance(value,list) or not 1<=len(value)<=question['max_members']:
        raise ValueError('请按家庭人数填写成员信息')
    fields=question['fields'];allowed_ids={f['id'] for f in fields};result=[]
    for i,member in enumerate(value,1):
        if not isinstance(member,dict) or set(member)-allowed_ids:
            raise ValueError(f'成员 {i} 包含未定义的字段')
        row={}
        for field in fields:
            v=member.get(field['id'])
            if v is None or v=='' or v==[]:
                if field['required']:raise ValueError(f"请填写成员 {i} 的{field['prompt']}")
                row[field['id']]=None
            elif field.get('type')=='multi_choice':
                if not isinstance(v,list) or any(not isinstance(x,str) or x not in {o['value'] for o in field['options']} for x in v) or len(v)!=len(set(v)):
                    raise ValueError(f"成员 {i} 的{field['prompt']}选项无效")
                row[field['id']]=v
            elif not isinstance(v,str) or v not in {o['value'] for o in field['options']}:
                raise ValueError(f"成员 {i} 的{field['prompt']}选项无效")
            else:row[field['id']]=v
        result.append(row)
    return result

def validate_count(profile):
    cell=profile.get('M_MEMBERS',{})
    if cell.get('response_status')!='answered':raise ValueError('请填写家庭成员的生活节奏')
    members=normalize_members(cell['value'],QUESTION)
    size=profile['B02']['value']
    if (size=='6_plus' and len(members)<6) or (size!='6_plus' and len(members)!=int(size)):
        raise ValueError('成员数量与家庭人数不一致，请检查成员卡片')

def reported_members(value, question):
    return [{'member_id':f'member_{i}', 'source':'household_representative_report',
             'reported_fields':{f['id']:{'value':m.get(f['id']),
                'label':('、'.join(o['label'] for o in f['options'] if o['value'] in m.get(f['id'],[])) if isinstance(m.get(f['id']),list) else next((o['label'] for o in f['options'] if o['value']==m.get(f['id'])),None)),
                'question':f['prompt'],'response_status':'answered' if m.get(f['id']) is not None else 'skipped'}
                for f in question['fields']}} for i,m in enumerate(value,1)]

def member_text(value, question):
    return '\n'.join(f"成员 {i}："+'；'.join(f"{f['question']}：{f['label'] if f['response_status']=='answered' else '未填写'}" for f in row['reported_fields'].values())
                     for i,row in enumerate(reported_members(value,question),1))
