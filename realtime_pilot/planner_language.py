"""Versioned English rendering at EB's input boundary; source answers stay intact.

This is a closed-choice questionnaire renderer, not a general machine translator.
City names are proper nouns retained verbatim; the matched station also has an
English name. Unmapped question wording/options fail explicitly before planning.
"""
from copy import deepcopy
import json
from pathlib import Path
from common import digest, file_hash
from survey_time import clock_label

CATALOG_PATH = Path(__file__).with_name('planner_english_catalog.json')
CATALOG = json.loads(CATALOG_PATH.read_text())
VERSION = CATALOG['version']


def english_question(question, specification=None):
    spec = specification or CATALOG['questions'].get(question['id'])
    if spec is None or spec['source_prompt'] != question['prompt']:
        raise ValueError('English questionnaire mapping needs review: '+question['id'])
    result = deepcopy(question)
    result['prompt'] = spec['prompt_en']
    for option in result.get('options', []):
        mapped = spec['options'].get(option['value'])
        if mapped is None or mapped['source_label'] != option['label']:
            raise ValueError('English option mapping needs review: '+question['id'])
        option['label'] = mapped['label_en']
    if question['type'] == 'member_list':
        result['fields'] = [english_question({**f, 'type':f.get('type','single_choice')}, spec['fields'].get(f['id'])) for f in question['fields']]
    return result


def english_answer(cell, question):
    if cell['response_status'] != 'answered':
        return None
    value = cell['value']
    if question['type'] == 'text':
        if question['id'] != 'X_CITY':
            raise ValueError('Free-text translation is not configured: '+question['id'])
        return 'City name as reported (proper noun): '+str(value)
    if question['type'] == 'temperature_range':
        return ' to '.join(str(value).split('_'))+' degrees C'
    if question['type'] == 'member_list':
        from member_questionnaire import reported_members
        members = reported_members(value, question)
        return '\n'.join(f"Member {i}: "+'; '.join(
            f"{f['question']}: {f['label'].replace('、', '; ') if f['label'] is not None else 'Not reported'}"
            for f in member['reported_fields'].values()) for i,member in enumerate(members,1))
    labels = {o['value']:o['label'] for o in question['options']}
    return '; '.join(labels[v] for v in value) if isinstance(value,list) else labels[value]


def planner_household(source, request):
    """Copy only language-bearing views; retain codes, numbers, source hashes."""
    from paired_contract import QUESTIONS
    questions = request.get('questionnaire_snapshot', QUESTIONS)
    translated = {q['id']:english_question(q) for q in questions if not q.get('research_only')}
    profile = request['profile']
    result = deepcopy(source)
    rows = {}
    for group in ('household_information','stated_attitudes'):
        for row in result['observable_profile'][group]:
            qid = row['question_id']
            row['question'] = translated[qid]['prompt']
            row['answer'] = english_answer(profile[qid], translated[qid])
            rows[qid] = row
    for answer in result['onboarding']['answers']:
        qid = answer['id']
        if qid == 'SIMULATION_ENVIRONMENT':
            context = json.loads(answer['answer'])
            context['assumptions'] = [CATALOG['environment_assumptions'][x] for x in context['assumptions']]
            context['station_name'] = source['simulation_environment']['weather']['station_name']
            answer['question'] = 'Matched simulation environment (system-selected research approximation, not measurements of this home)'
            answer['answer'] = json.dumps(context, ensure_ascii=False)
        else:
            answer['question'] = rows[qid]['question']
            answer['answer'] = rows[qid]['answer']
    for cell in result.get('reported_preferences', {}).values():
        cell['answer'] = rows[cell['question_id']]['answer']
    if 'M_MEMBERS' in translated and profile['M_MEMBERS']['response_status']=='answered':
        from member_questionnaire import reported_members
        result['reported_members'] = reported_members(profile['M_MEMBERS']['value'],translated['M_MEMBERS'])
        for member in result['reported_members']:
            for field in member['reported_fields'].values():
                if field['label'] is not None:field['label']=field['label'].replace('、','; ')
    deadlines = {}
    for device,record in request['original_plan']['devices'].items():
        if device in ('washer','dishwasher','dryer') and record.get('active'):
            day = 'following day' if record['deadline_h'] < record['earliest_h'] else 'same day'
            deadlines[device] = (f"Finish by {clock_label(record['deadline_h'])} ({day}); "
                f"may start from {clock_label(record['earliest_h'])}; duration {round(record['duration_h']*60)} minutes")
    for day in result['calendar']['days']:
        day['summary'] = 'Household-reported usual appliance times and task windows; not a measured daily schedule.'
        day['constraints']['appliance_deadlines'] = deepcopy(deadlines)
    result['display_name'] = 'Respondent household'
    result['llm_prompts']['agent_context'] = ('One real respondent reports on behalf of the household. Consider their own facts and attitudes; do not assign a preset household type or infer unreported members, scoring weights or authorization.\n'+json.dumps(result['observable_profile'],ensure_ascii=False))
    result['planner_language'] = {
        'version':VERSION, 'language':'en', 'source_language':'zh',
        'source_household_config_hash':digest(source),
        'catalog_sha256':file_hash(CATALOG_PATH),
        'free_text_policy':'City proper nouns retained verbatim; no general free-text translation. Human feedback remains in its original language.',
        'source_record_mutated':False,
    }
    return result
