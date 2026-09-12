"""Export inspectable pilot JSONL, never a training release."""
import argparse
import json
import sqlite3
from pathlib import Path
from common import ROOT, write_json, digest
from proposal_contract import FEEDBACK_VERSION, candidate, decision_record
from paired_contract import VERSION as PAIRED_VERSION

def verify_candidate(row, job, documents, intake=None):
    """Verify the stored evidence, never recompute or improve a human answer."""
    if job.get('status') != 'complete' or row.get('case_id') != job.get('id'):
        raise ValueError('Candidate does not refer to a completed case')
    result=documents.get('outcome.json')
    decision=documents.get('decision.json')
    if not result or not decision or job.get('result') != result:
        raise ValueError('Missing or inconsistent saved outcome/decision')
    for name in ('display','original_plan','proposal_plan','baseline_plan','household_config'):
        if name in result and digest(result[name]) != result.get(name+'_hash'):
            raise ValueError('Saved outcome hash mismatch: '+name)
    if digest(job['questionnaire_snapshot']) != job.get('questionnaire_hash'):
        raise ValueError('Questionnaire snapshot hash mismatch')
    if job.get('household_record'):
        record=job['household_record']
        if record['normalized_answers'] != job['profile'] or record['questionnaire_snapshot'] != job['questionnaire_snapshot']:
            raise ValueError('Planning profile differs from frozen household answers or questions')
        if digest(job['household_record']) != job.get('household_record_hash'):
            raise ValueError('Household record hash mismatch')
        if documents.get('household_record.json') != job['household_record']:
            raise ValueError('Saved household document mismatch')
    if job.get('household_submission_id'):
        if not intake or intake['id'] != job['household_submission_id']:
            raise ValueError('Missing linked household intake')
        if intake['household_record'] != job['household_record'] or intake['household_record_hash'] != job['household_record_hash']:
            raise ValueError('Linked intake differs from evaluated household')
        if job['data_origin']=='local_pilot_self_reported_human' and intake.get('research_consent') is not True:
            raise ValueError('Human intake lacks participation confirmation')
    canonical=decision_record(job,decision)
    saved_answer={k:v for k,v in decision.items() if k not in ('decision_hash','submitted_at')}
    if canonical != saved_answer or digest(canonical) != decision.get('decision_hash'):
        raise ValueError('Feedback differs from saved display or scoring contract')
    if candidate(job,decision) != row:
        raise ValueError('Candidate differs from source household, shown result or human feedback')
    return row

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--include-engineering", action="store_true", help="Include explicitly labelled test answers for format inspection only")
    p.add_argument("--task", choices=["plan_judgement", "outcome_rating"], default="plan_judgement")
    p.add_argument("--data-dir",type=Path,default=ROOT/"data/web")
    p.add_argument("--output",type=Path)
    args=p.parse_args()
    output=args.output or ROOT/"exports"/(args.task+"_"+("engineering_and_pilot_review.jsonl" if args.include_engineering else "human_pilot_review.jsonl"))
    output.parent.mkdir(parents=True,exist_ok=True)
    rows=[]
    excluded=0
    excluded_reasons={}
    sources={}
    database=args.data_dir/'state.sqlite3'
    if database.exists():
        with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
            db.execute('BEGIN')
            candidates=[json.loads(r[0]) for r in db.execute("SELECT payload FROM documents WHERE name='sft_candidate.json' ORDER BY job_id")]
            for row in candidates:
                jid=row['case_id']
                saved=db.execute('SELECT payload FROM jobs WHERE id=?',(jid,)).fetchone()
                if saved is None:raise ValueError('Missing candidate job: '+jid)
                job=json.loads(saved[0])
                docs={name:json.loads(payload) for name,payload in db.execute('SELECT name,payload FROM documents WHERE job_id=?',(jid,))}
                intake=None
                if job.get('household_submission_id'):
                    found=db.execute('SELECT payload FROM household_submissions WHERE id=?',(job['household_submission_id'],)).fetchone()
                    if found:intake=json.loads(found[0])
                sources[jid]=(job,docs,intake)
    else:
        candidates=[json.loads(path.read_text()) for path in sorted(args.data_dir.glob('*/sft_candidate.json'))]
        if candidates:raise ValueError('Verified candidate export requires authoritative state.sqlite3; file copies alone cannot verify intake links')
    for row in candidates:
        if row.get("task") != args.task or (args.task == "plan_judgement" and (row.get("feedback_version") != FEEDBACK_VERSION or row.get("flow") != "paired_ep_v1" or row.get("schema_version") != PAIRED_VERSION)):
            excluded+=1
            excluded_reasons['different_task_or_version']=excluded_reasons.get('different_task_or_version',0)+1
            continue
        if row.get("target_source")!="household_representative_self_report" and not args.include_engineering:
            excluded+=1
            excluded_reasons['engineering']=excluded_reasons.get('engineering',0)+1
            continue
        if not row.get("has_supervised_answer", True):
            excluded+=1
            excluded_reasons['no_supervised_answer']=excluded_reasons.get('no_supervised_answer',0)+1
            continue
        assert row["training_release"] is False
        if args.task == 'plan_judgement':verify_candidate(row,*sources[row['case_id']])
        rows.append(row)
    output.write_text("".join(json.dumps(r,ensure_ascii=False,allow_nan=False)+"\n" for r in rows))
    report={"file":str(output),"task":args.task,"rows":len(rows),"excluded":excluded,"training_release":False,
            "purpose":"verified_data_handoff_not_training_or_evaluation","engineering_rows":sum(r["target_source"]=="engineering_test" for r in rows),
            "source_links_verified":args.task=='plan_judgement',"excluded_reasons":excluded_reasons,
            "selection_by_acceptance_savings_or_fallback":False,
            "identity_scope":"browser_session_proxy_not_verified_unique_household"}
    write_json(output.with_suffix(".manifest.json"),report)
    print(json.dumps(report,ensure_ascii=False))

if __name__=="__main__":
    main()
