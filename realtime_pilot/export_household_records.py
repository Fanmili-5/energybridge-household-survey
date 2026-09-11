"""Export submitted household evidence, independently of planning or feedback success."""
import argparse
import json
import sqlite3
from pathlib import Path
from common import ROOT, digest, write_json


def records(data_dir, include_engineering=False):
    database=Path(data_dir)/'state.sqlite3'
    if not database.exists():
        raise FileNotFoundError('Household export requires the authoritative state.sqlite3')
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
        # Read the intake and job links from the same SQLite snapshot.
        db.execute('BEGIN')
        saved=list(db.execute("SELECT j.payload,d.payload FROM jobs j JOIN documents d ON d.job_id=j.id WHERE d.name='household_record.json' ORDER BY j.created,j.id"))
        exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='household_submissions'").fetchone()
        intakes=[json.loads(r[0]) for r in db.execute('SELECT payload FROM household_submissions ORDER BY created,id')] if exists else []
    jobs=[(json.loads(j),json.loads(r)) for j,r in saved]
    linked={}
    for job,record in jobs:
        if digest(record)!=job.get('household_record_hash'):
            raise ValueError('Household record hash mismatch: '+job['id'])
        if job.get('household_submission_id'):
            linked.setdefault(job['household_submission_id'],[]).append(job)
    intake_ids={i['id'] for i in intakes}
    if set(linked)-intake_ids:raise ValueError('A job references a missing household submission')
    for intake in intakes:
        if intake.get('data_origin')!='local_pilot_self_reported_human' and not include_engineering:continue
        record=intake['household_record'];checksum=digest(record)
        if checksum!=intake.get('household_record_hash'):raise ValueError('Household intake hash mismatch: '+intake['id'])
        cases=linked.get(intake['id'],[])
        if any(j['household_record_hash']!=checksum for j in cases):raise ValueError('Linked job differs from frozen household intake')
        yield {'schema_version':'eb.household_collection_export.v2','submission_id':intake['id'],
               'case_ids':[j['id'] for j in cases],'household_id':record['household_id'],
               'job_statuses':{j['id']:j['status'] for j in cases},
               'data_origin':intake['data_origin'],'decision_saved':any(j.get('decision_saved') for j in cases),
               'created_at':intake['created_at'],'research_consent':intake.get('research_consent'),
               'research_notice_version':intake.get('research_notice_version'),
               'household_record_hash':checksum,'household_record':record,'training_release':False}
    # Legacy engineering/direct submissions retain their original case records.
    for job,record in jobs:
        if job.get('household_submission_id'):continue
        if job.get('data_origin')!='local_pilot_self_reported_human' and not include_engineering:continue
        yield {'schema_version':'eb.household_collection_export.v2','case_id':job['id'],'case_ids':[job['id']],
               'submission_id':None,'household_id':record['household_id'],'job_status':job['status'],
               'data_origin':job.get('data_origin'),'decision_saved':bool(job.get('decision_saved')),
               'household_record_hash':digest(record),'household_record':record,'training_release':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path,default=ROOT/'data/web')
    parser.add_argument('--include-engineering',action='store_true')
    parser.add_argument('--output',type=Path,default=ROOT/'exports/household_records_review.jsonl')
    args=parser.parse_args()
    rows=list(records(args.data_dir,args.include_engineering))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(''.join(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n' for row in rows))
    report={'rows':len(rows),'file':str(args.output),'training_release':False,
            'includes_submissions_without_feedback':True,'includes_submissions_without_jobs':True,'linked_jobs_collapsed_per_submission':True,
            'deduplicated':False,'identity_scope':'browser_session_proxy_not_verified_unique_household',
            'purpose':'household_profile_review_not_supervised_labels'}
    write_json(args.output.with_suffix('.manifest.json'),report)
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
