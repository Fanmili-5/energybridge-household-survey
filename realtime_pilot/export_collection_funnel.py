"""Audit every saved household from intake through a verified SFT candidate."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sqlite3
import statistics

from common import ROOT, write_json
from export_candidates import verify_candidate
from paired_contract import QUESTIONNAIRE_VERSION, VERSION as PAIRED_VERSION
from proposal_contract import FEEDBACK_VERSION
from simulation_environment import inspect_profile


def _counts(values):
    return dict(sorted(Counter(str(v) for v in values if v not in (None, '')).items()))


def _score_summary(values):
    clean=[float(value) for value in values if isinstance(value,(int,float)) and not isinstance(value,bool)]
    if not clean:return {'n':0}
    return {'n':len(clean),'min':min(clean),'max':max(clean),'mean':round(statistics.fmean(clean),3)}


def _length_bucket(value):
    n=len(value.strip()) if isinstance(value,str) else 0
    if n==0:return 'empty'
    if n<10:return '1_9'
    if n<30:return '10_29'
    if n<100:return '30_99'
    return '100_plus'


def build_report(data_dir, include_engineering=False):
    database=Path(data_dir)/'state.sqlite3'
    if not database.exists():raise FileNotFoundError('Collection audit requires state.sqlite3')
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.execute('BEGIN')
        intakes=[json.loads(row[0]) for row in db.execute('SELECT payload FROM household_submissions ORDER BY created,id')]
        jobs=[json.loads(row[0]) for row in db.execute('SELECT payload FROM jobs ORDER BY created,id')]
        documents=defaultdict(dict)
        for jid,name,payload in db.execute('SELECT job_id,name,payload FROM documents'):
            documents[jid][name]=json.loads(payload)
    if not include_engineering:
        intakes=[row for row in intakes if row.get('data_origin')=='local_pilot_self_reported_human']
    intake_ids={row['id'] for row in intakes};intake_by_id={row['id']:row for row in intakes}
    jobs=[row for row in jobs if row.get('household_submission_id') in intake_ids]
    by_intake=defaultdict(list)
    for row in jobs:by_intake[row['household_submission_id']].append(row)
    stages=Counter();dropoff=Counter();regions=[];buildings=[];months=[];devices=[]
    decisions=[];scores=defaultdict(list);comment_lengths=[];change_states=[];fallback_states=[];failure_reasons=[];failure_stages=[];failure_types=[];candidate_failures=[]
    for intake in intakes:
        stages['intake_saved']+=1
        frozen_ready=((intake.get('household_record') or {}).get('environment_readiness') or {}).get('status')=='ready'
        current_ready=inspect_profile(intake['profile']).get('status')=='ready'
        if frozen_ready:stages['environment_ready_at_intake']+=1
        if current_ready:stages['environment_ready_current_catalog']+=1
        linked=by_intake.get(intake['id'],[])
        if linked:stages['generation_attempted']+=1
        complete=[j for j in linked if j.get('status')=='complete']
        if complete:stages['paired_simulation_complete']+=1
        feedback=[j for j in linked if j.get('decision_saved') and 'decision.json' in documents[j['id']]]
        if feedback:stages['human_feedback_saved']+=1
        candidates=[j for j in feedback if 'sft_candidate.json' in documents[j['id']]]
        if candidates:stages['candidate_saved']+=1
        verified=[];current=[]
        for candidate_job in candidates:
            row=documents[candidate_job['id']]['sft_candidate.json']
            try:
                verify_candidate(row,candidate_job,documents[candidate_job['id']],intake_by_id.get(intake['id']),Path(data_dir)/candidate_job['id'])
                verified.append(candidate_job)
                if (row.get('schema_version')==PAIRED_VERSION and row.get('questionnaire_version')==QUESTIONNAIRE_VERSION
                        and row.get('feedback_version')==FEEDBACK_VERSION):current.append(candidate_job)
            except Exception as exc:
                candidate_failures.append(type(exc).__name__)
        if verified:stages['candidate_evidence_verified']+=1
        if current:stages['current_version_eligible']+=1
        if current and intake.get('data_origin')=='local_pilot_self_reported_human':stages['human_export_eligible']+=1
        if not linked:dropoff['saved_without_generation']+=1
        elif not complete:dropoff['generation_not_completed']+=1
        elif not feedback:dropoff['completed_awaiting_feedback']+=1
        else:dropoff['feedback_complete']+=1
        raw=intake.get('raw_answers') or {}
        regions.append(raw.get('X_REGION'));buildings.append(raw.get('X_BUILDING'))
        context=intake.get('questionnaire_context') or {}
        date=context.get('date')
        month=(date[5:7] if isinstance(date,str) and len(date)>=7 else context.get('month'))
        months.append(month)
        devices.extend(raw.get('B05') or [])
    for job in jobs:
        docs=documents[job['id']]
        decision=docs.get('decision.json')
        if decision:
            decisions.append(decision.get('choice'))
            for key in ('score','comfort_score','energy_score','vpp_score'):scores[key].append(decision.get(key))
            comment_lengths.append(_length_bucket(decision.get('comment')))
        outcome=docs.get('outcome.json')
        if outcome:
            view=(outcome.get('display') or {}).get('participant_view') or outcome.get('display') or {}
            change_states.append(bool(view.get('has_changes')))
            native=(outcome.get('provenance') or {}).get('native_plan_outcomes') or []
            fallback_states.append(any(row.get('fallback_used') for row in native))
        if job.get('status') not in ('complete','queued','running'):
            failure_reasons.append(job.get('status','unknown'))
            failure_stages.append(job.get('failure_stage','unknown'))
            failure_types.append(job.get('failure_type','unknown'))
    statuses=Counter(j.get('status','unknown') for j in jobs)
    report={
        'schema_version':'eb.collection_funnel.v3',
        'data_origin':'human_and_engineering' if include_engineering else 'local_pilot_self_reported_human',
        'unit':'unique_household_submission',
        'stages':dict(stages),
        'dropoff':dict(dropoff),
        'case_statuses':dict(sorted(statuses.items())),
        'cases':len(jobs),
        'coverage':{'province':_counts(regions),'building_type':_counts(buildings),'assigned_month':_counts(months),'selected_device':_counts(devices)},
        'label_quality':{'decision':_counts(decisions),'scores':{key:_score_summary(scores[key]) for key in ('score','comfort_score','energy_score','vpp_score')},
                         'comment_length':_counts(comment_lengths)},
        'simulation_quality':{'display_has_changes':_counts(change_states),'native_fallback_used':_counts(fallback_states),
                              'incomplete_status_reason':_counts(failure_reasons),'failure_stage':_counts(failure_stages),
                              'failure_type':_counts(failure_types),'candidate_verification_failure':_counts(candidate_failures)},
        'training_release':False,
        'notes':['A household is counted once per stage even when it has retries.',
                 'environment_ready_at_intake is frozen with the household; environment_ready_current_catalog is a present-day recheck.',
                 'candidate_saved means a file exists; candidate_evidence_verified also checks source records and native artifact hashes.',
                 'human_export_eligible is still a review candidate, not a training release.']}
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-dir',type=Path,default=ROOT/'data/web')
    p.add_argument('--include-engineering',action='store_true')
    p.add_argument('--output',type=Path)
    a=p.parse_args();report=build_report(a.data_dir,a.include_engineering)
    if a.output:write_json(a.output,report)
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
