"""Public questions aligned to EB persona generation, not controller-inferred traits."""
from copy import deepcopy

QUESTIONNAIRE_VERSION = "eb.persona_questionnaire.v1"
SOURCE = {
    "commit": "2b17ae63e613da776c93e900f5dace50d63a88a8",
    "definitions": "energybridge/roleplay/generator.py::_TAG_DESCRIPTIONS",
    "allowed_values": "energybridge/roleplay/schema.py::VALID_TAGS",
    "adaptation": "Chinese participant selections; qualitative descriptions, no inferred numeric defaults",
}

def question(qid, prompt, options, *, group, dimension=None, multi=False):
    return {"id": qid, "prompt": prompt, "type": "multi_choice" if multi else "single_choice",
            "group": group, "eb_dimension": dimension,
            "options": [{"value": value, "label": label} for value, label in options]}

ATTITUDES = [
    question("A_EB_COMFORT", "关于室内温度和空调调整，哪一种最接近您家的想法？", [
        ("temp_tolerant", "家人对冷热变化比较适应，可以接受较宽的室温变化"),
        ("normal_comfort", "希望室温舒适，通常能接受一定的小幅变化"),
        ("temp_sensitive", "家人对冷热比较敏感，希望室温保持在较小的范围内"),
        ("low_control_tolerance", "更希望自己管理空调，不喜欢系统自动调整")], group="attitude", dimension="comfort"),
    question("A_EB_TASK", "关于洗衣、洗碗等电器的运行时间，哪一种最接近您家平时的想法？", [
        ("flexible", "运行时间比较灵活，可以根据需要调整"),
        ("semi_rigid", "有可接受的时间范围，可以在这个范围内调整"),
        ("rigid", "通常需要按固定时间运行，不希望改变")], group="attitude", dimension="task"),
    question("A_EB_PRICE", "面对节电或调整用电的建议，哪一种最接近您家的想法？", [
        ("price_sensitive", "节省电费很有吸引力，会积极考虑"),
        ("needs_explanation", "对节省电费感兴趣，但要先把具体收益解释清楚"),
        ("low_incentive", "节省电费的吸引力较小，更在意舒适和生活便利"),
        ("event_fatigue", "频繁提出调整会让人厌烦，需要充分的理由才愿意配合")], group="attitude", dimension="price"),
    question("A_EB_CONTROL", "让系统协助安排家里的电器，哪一种最接近您家的态度？", [
        ("high_trust_auto", "比较信任系统，愿意让它自动安排"),
        ("suggestion_first", "希望系统先给建议，再讨论是否采用"),
        ("confirm_required", "每次调整前都必须得到我们明确确认"),
        ("privacy_sensitive", "最在意用电隐私，不愿向系统提供详细用电信息"),
        ("low_auto_accept", "总体上不太愿意接受系统自动控制")], group="attitude", dimension="control"),
]

def build_questions(old):
    facts = []
    for qid in ("B02", "B04", "B05"):
        q = deepcopy(old[qid])
        q["group"] = "household_fact"
        q["options"] = [o for o in q["options"] if o["value"] not in {"dont_know", "declined", "skipped"}]
        facts.append(q)
    facts += [
        question("F_EVENING", "平时 18:00—22:00，您家通常有人在家吗？", [
            ("mostly_home", "大部分时间有人"), ("partly_home", "部分时间有人"),
            ("mostly_away", "大部分时间没人"), ("varies", "每天不太固定")], group="household_fact"),
        question("F_REGULARITY", "您家成员的外出、回家和休息时间通常规律吗？", [
            ("regular", "大体固定"), ("partly_regular", "部分成员或部分日期固定"),
            ("irregular", "变化较多")], group="household_fact"),
        question("F_LATE_USE", "您家是否经常有人在深夜（零点以后）仍在活动并使用电器？", [
            ("often", "经常"), ("sometimes", "偶尔"), ("rarely", "很少或没有")], group="household_fact"),
        question("F_ROUTINES", "您家平时有哪些需要保持安静或稳定室温的日常活动？（可多选）", [
            ("work_study", "居家工作或学习"), ("rest_sleep", "休息或睡眠"),
            ("care", "照护家人"), ("none", "没有特别需要")], group="household_fact", multi=True),
    ]
    return facts + deepcopy(ATTITUDES)

def components(profile, questions):
    """Keep factual classification inputs independent of attitudes and decisions."""
    lookup = {q["id"]: q for q in questions}
    facts, attitudes, members, preferences = {}, {}, {}, {}
    for qid, cell in profile.items():
        q = lookup.get(qid)
        if not q:
            continue
        if q.get("research_only"):
            continue
        if q.get('environment_input'):
            continue
        if q["type"] == "member_list":
            members = deepcopy(cell)
            continue
        if q['group']=='stated_preference':
            preferences[q['eb_dimension']]={**deepcopy(cell),'question_id':qid,'provenance':'household_representative_selection'}
            continue
        if q["group"] == "household_fact":
            facts[qid] = deepcopy(cell)
        else:
            attitudes[q["eb_dimension"]] = {
                **deepcopy(cell), "question_id": qid,
                "source_field": "tags." + q["eb_dimension"],
                "provenance": "household_representative_selection",
            }
    return {"questionnaire_version": QUESTIONNAIRE_VERSION, "alignment_source": SOURCE,
            "household_information": facts, "eb_attitudes": attitudes,
            **({"reported_members": members} if members else {}),
            **({"stated_preferences": preferences} if preferences else {}),
            "classification": {"status": "not_fitted", "household_type": None,
                               "input_question_ids": list(facts), "features": deepcopy(facts),
                               "uses_attitudes": False, "uses_decisions": False},
            "unmeasured_eb_fields": ["tags.grid_value", "preferences.scoring_weights",
                                     "preferences.vpp_override_prob", "preferences.temp_preferred_min",
                                     "preferences.temp_preferred_max", "preferences.temp_tolerance_c"]}

def visible_profile(profile, questions):
    """Only public question and answer text goes to EB; synthetic hidden role tags do not."""
    out = {"household_information": [], "stated_attitudes": []}
    for q in questions:
        if q.get("research_only"):continue
        cell = profile.get(q["id"])
        if not cell:
            continue
        if q['type']=='member_list':
            from member_questionnaire import member_text
            out['household_information'].append({'question_id':q['id'],'question':q['prompt'],
                'answer':member_text(cell['value'],q) if cell['response_status']=='answered' else None,
                'response_status':cell['response_status'],'source':'household_representative_report'})
            continue
        labels = {o["value"]: o["label"] for o in q["options"]}
        value = cell["value"]
        answer = (str(value) if q.get('type')=='text' else "、".join(labels[v] for v in value) if isinstance(value, list) else labels.get(value)) if cell["response_status"] == "answered" else None
        if q.get('type')=='temperature_range' and cell['response_status']=='answered':
            answer='—'.join(str(value).split('_'))+'℃'
        key = "household_information" if q["group"] in ("household_fact","simulation_environment") else "stated_attitudes"
        out[key].append({"question_id": q["id"], "question": q["prompt"], "answer": answer,
                         "response_status": cell["response_status"]})
    out["interpretation"] = "These are public self-reports, not assigned persona traits. General attitudes do not authorize this event. Household type is not assigned. Do not infer numeric tolerances, scoring weights, or response probabilities."
    if any(q['type']=='member_list' for q in questions):
        out['interpretation'] += " Member descriptions are reported by one respondent; unfilled attitudes remain unknown. The final feedback is that respondent's judgment considering household needs, not independent member votes or unanimous consent. Do not infer which member is the respondent."
    return out
