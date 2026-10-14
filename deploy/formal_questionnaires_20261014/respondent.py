"""Optional self-report about the person filling the form, never the assigned role."""
QUESTIONNAIRE_UI_VERSION='eb.household50.questionnaire.20261014.1'
GENDERS={None,'female','male','other','prefer_not_to_say'}

def validate_respondent(value):
    if not isinstance(value,dict)or set(value)!={'age_years','gender'}:
        raise ValueError('填写者资料字段无效')
    age=value['age_years']
    if age is not None and (type(age)is not int or not 1<=age<=120):
        raise ValueError('本人年龄须为1至120的整数，或留空')
    gender=value['gender']
    if not isinstance(gender,(str,type(None)))or gender not in GENDERS:
        raise ValueError('本人性别选项无效')
    return {'age_years':age,'gender':gender}
