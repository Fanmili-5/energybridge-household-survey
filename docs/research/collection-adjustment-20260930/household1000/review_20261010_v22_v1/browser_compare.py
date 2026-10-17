import hashlib,json,pathlib
here=pathlib.Path(__file__).resolve().parent
def digest(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
a=json.loads((here/"browser_records/answer_A_engineering.json").read_text())
b=json.loads((here/"browser_records/answer_B_engineering.json").read_text())
same=a["input"]==b["input"]
report={"schema":"eb.actual_browser_review.v22","date":"2026-10-10","status":"pass" if same and a["test_feedback"]!=b["test_feedback"] else "fail",
"actual_browser_exports_compared":2,"cases_checked":1,"input_unchanged_when_all_answers_changed":same,
"input_sha256":digest(a["input"]),"feedback_A":a["test_feedback"],"feedback_B":b["test_feedback"],
"human_answers":0,"formal_export_eligible":False,"engineering_records_not_human":True,
"current_production_acceptance_updated":False,"physical_outputs_pending":True,
"source_files":[{"path":"browser_records/"+n,"sha256":hashlib.sha256((here/"browser_records"/n).read_bytes()).hexdigest()} for n in ["answer_A_engineering.json","answer_B_engineering.json"]],
"browser_url":"http://127.0.0.1:18800/household50-ordinary-v6-0004/",
"scope":"one actual browser case, shared renderer; does not establish human validity or all-case physical completion"}
(here/"FRONTEND_BROWSER_REVIEW.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
print(json.dumps(report,ensure_ascii=False))
assert same and a["test_feedback"]!=b["test_feedback"]
