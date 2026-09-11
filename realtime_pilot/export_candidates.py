"""Export inspectable pilot JSONL, never a training release."""
import argparse
import json
import sqlite3
from pathlib import Path
from common import ROOT, write_json
from proposal_contract import FEEDBACK_VERSION
from paired_contract import VERSION as PAIRED_VERSION

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
    database=args.data_dir/'state.sqlite3'
    if database.exists():
        with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
            candidates=[json.loads(r[0]) for r in db.execute("SELECT payload FROM documents WHERE name='sft_candidate.json' ORDER BY job_id")]
    else:
        candidates=[json.loads(path.read_text()) for path in sorted(args.data_dir.glob('*/sft_candidate.json'))]
    for row in candidates:
        if row.get("task") != args.task or (args.task == "plan_judgement" and (row.get("feedback_version") != FEEDBACK_VERSION or row.get("flow") != "paired_ep_v1" or row.get("schema_version") != PAIRED_VERSION)):
            excluded+=1
            continue
        if row.get("target_source")!="household_representative_self_report" and not args.include_engineering:
            excluded+=1
            continue
        if not row.get("has_supervised_answer", True):
            excluded+=1
            continue
        assert row["training_release"] is False
        rows.append(row)
    output.write_text("".join(json.dumps(r,ensure_ascii=False,allow_nan=False)+"\n" for r in rows))
    report={"file":str(output),"task":args.task,"rows":len(rows),"excluded":excluded,"training_release":False,
            "purpose":"format_review_only","engineering_rows":sum(r["target_source"]=="engineering_test" for r in rows)}
    write_json(output.with_suffix(".manifest.json"),report)
    print(json.dumps(report,ensure_ascii=False))

if __name__=="__main__":
    main()
