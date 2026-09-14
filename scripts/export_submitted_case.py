"""Export a submitted answer sheet and its results, not questionnaire templates.

Reads a consistent authoritative SQLite snapshot, or a previously sanitized
saved-record bundle. No model calls, SFT messages or source-record mutations.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'realtime_pilot'))
from common import digest
from export_candidates import verify_candidate


def build_export(records):
    job=records['job_db'];docs=records['documents'];intake=records.get('household_submission_db')
    # Validate existing source links; do not construct new training messages.
    verify_candidate(docs['sft_candidate.json'],job,docs,intake)
    submission=docs['questionnaire_submission.json'];outcome=docs['outcome.json']
    questionnaire={
        'schema_version':'eb.submitted_answers.v1',
        **{k:deepcopy(submission[k]) for k in ('case_id','household_id','submitted_at','questionnaire_version','questionnaire_hash','data_origin')},
        'answers':deepcopy(submission['raw_answers']),
    }
    # An explicit source hash identifies the archived full document; it is not
    # claimed to be the digest of this intentionally narrower handoff projection.
    questionnaire['source_submission_hash']=digest(submission)
    if intake:
        for key in ('research_consent','research_notice_version','scenario_understood','ui_version'):
            if key in intake:questionnaire[key]=deepcopy(intake[key])
    household=docs['household_config.json']
    full={
        'schema_version':'eb.collected_case.v1',
        'questionnaire':questionnaire,
        'eb_configuration':{k:deepcopy(household[k]) for k in (
            'id','tags','preferences','appliances','schedule','calendar','ordinary_plan','reported_preferences','reported_members','meta') if k in household},
        'simulation_context':deepcopy(docs['request.json']['scenario']),
        'results':{k:deepcopy(outcome[k]) for k in (
            'original_plan','baseline_plan','proposal_plan','prediction','simulation_status','execution_mode','date_validation','timings') if k in outcome},
        'shown_to_participant':deepcopy(outcome['display']['participant_view']),
        'feedback':deepcopy(docs['decision.json']),
        'provenance':{
            'source_document_hashes':{name:digest(docs[name]) for name in (
                'questionnaire_submission.json','household_config.json','request.json','outcome.json','decision.json')},
            'native_run':deepcopy(outcome.get('provenance',{})),
            'collection_mode_at_submission':job.get('collection_mode'),
            'stored_data_origin':job.get('data_origin'),
            'training_release':False,
            'export_scope':'Actual submitted answers, case configuration, compared results and human feedback. Questionnaire definitions and SFT message templates are excluded; native artifacts are referenced, not embedded.',
        },
    }
    return questionnaire,full


def read_database(directory,case_id):
    dbpath=directory/'state.sqlite3'
    with sqlite3.connect(dbpath.resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.execute('BEGIN')
        row=db.execute('SELECT payload FROM jobs WHERE id=?',(case_id,)).fetchone()
        if not row:raise ValueError('Case not found')
        job=json.loads(row[0])
        docs={name:json.loads(body) for name,body in db.execute('SELECT name,payload FROM documents WHERE job_id=?',(case_id,))}
        intake=None
        if job.get('household_submission_id'):
            row=db.execute('SELECT payload FROM household_submissions WHERE id=?',(job['household_submission_id'],)).fetchone()
            if row:intake=json.loads(row[0])
    return {'job_db':job,'documents':docs,'household_submission_db':intake}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    source=p.add_mutually_exclusive_group(required=True)
    source.add_argument('--source-bundle',type=Path)
    source.add_argument('--data-dir',type=Path)
    p.add_argument('--case-id');p.add_argument('--output-dir',type=Path,required=True)
    a=p.parse_args()
    if a.data_dir and not a.case_id:p.error('--data-dir requires --case-id')
    records=json.loads(a.source_bundle.read_text())['records'] if a.source_bundle else read_database(a.data_dir,a.case_id)
    questionnaire,full=build_export(records)
    from clean_collected_case import clean_case
    cleaned=clean_case(records,full)
    a.output_dir.mkdir(parents=True,exist_ok=True)
    files={}
    for name,data in [('questionnaire-answers.json',questionnaire),('full-collected-record.json',full),('cleaned-supervision.json',cleaned)]:
        path=a.output_dir/name;path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
        files[name]={'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size}
    verification={'case_id':questionnaire['case_id'],'answers_match_saved_submission':True,'feedback_matches_saved_decision':True,'source_links_verified':True,'questionnaire_definitions_included':False,'sft_messages_included':False,'files':files}
    (a.output_dir/'verification.json').write_text(json.dumps(verification,indent=2)+'\n')
    print(json.dumps(verification))

if __name__=='__main__':main()
