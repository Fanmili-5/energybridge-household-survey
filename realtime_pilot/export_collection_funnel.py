"""Audit every saved household from intake through a verified SFT candidate."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sqlite3

from common import ROOT, write_json
from simulation_environment import inspect_profile


def _counts(values):
    return dict(sorted(Counter(str(v) for v in values if v not in (None, '')).items()))


def build_report(data_dir, include_engineering=False):
    database=Path(data_dir)/'state.sqlite3'
    if not database.exists():raise FileNotFoundError('Collection audit requires state.sqlite3')
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.execute('BEGIN')
        intakes=[json.loads(row[0]) for row in db.execute('SELECT payload FROM household_submissions ORDER BY created,id')]
        jobs=[json.loads(row[0]) for row in db.execute('SELECT payload FROM jobs ORDER BY created,id')]
        doc_names=defaultdict(set)
        for jid,name in db.execute('SELECT job_id,name FROM documents'):
            doc_names[jid].add(name)
    if not include_engineering:
        intakes=[row for row in intakes if row.get('data_origin')=='local_pilot_self_reported_human']
    intake_ids={row['id'] for row in intakes}
    jobs=[row for row in jobs if row.get('household_submission_id') in intake_ids]
    by_intake=defaultdict(list)
    for row in jobs:by_intake[row['household_submission_id']].append(row)
    stages=Counter();dropoff=Counter();regions=[];buildings=[];months=[];devices=[]
    for intake in intakes:
        stages['intake_saved']+=1
        ready=inspect_profile(intake['profile']).get('status')=='ready'
        if ready:stages['environment_ready']+=1
        linked=by_intake.get(intake['id'],[])
        if linked:stages['generation_attempted']+=1
        complete=[j for j in linked if j.get('status')=='complete']
        if complete:stages['paired_simulation_complete']+=1
        feedback=[j for j in linked if j.get('decision_saved') and 'decision.json' in doc_names[j['id']]]
        if feedback:stages['human_feedback_saved']+=1
        candidates=[j for j in feedback if 'sft_candidate.json' in doc_names[j['id']]]
        if candidates:stages['candidate_saved']+=1
        if not linked:dropoff['saved_without_generation']+=1
        elif not complete:dropoff['generation_not_completed']+=1
        elif not feedback:dropoff['completed_awaiting_feedback']+=1
        else:dropoff['feedback_complete']+=1
        raw=intake.get('raw_answers') or {}
        regions.append(raw.get('X_REGION'));buildings.append(raw.get('X_BUILDING'))
        month=(intake.get('questionnaire_context') or {}).get('month');months.append(month)
        devices.extend(raw.get('B05') or [])
    statuses=Counter(j.get('status','unknown') for j in jobs)
    report={
        'schema_version':'eb.collection_funnel.v1',
        'data_origin':'human_and_engineering' if include_engineering else 'local_pilot_self_reported_human',
        'unit':'unique_household_submission',
        'stages':dict(stages),
        'dropoff':dict(dropoff),
        'case_statuses':dict(sorted(statuses.items())),
        'cases':len(jobs),
        'coverage':{'province':_counts(regions),'building_type':_counts(buildings),'assigned_month':_counts(months),'selected_device':_counts(devices)},
        'training_release':False,
        'notes':['A household is counted once per stage even when it has retries.',
                 'candidate_saved checks presence and linkage only; release review remains separate.']}
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
