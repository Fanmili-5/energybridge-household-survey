"""Create immutable judgment inputs from a sealed native batch; no simulations."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
from .common import canonical, digest, read, save
from .question_inputs import compile_question

NAMES = {"AC":"空调","WM":"洗衣","DR":"烘干","DW":"洗碗",
         "WH":"热水服务","EV":"电动车充电"}

def clock(value):
    day, minute = divmod(int(value),1440)
    return ("次日" if day == 1 else f"第{day+1}日" if day else "") + f"{minute//60:02}:{minute%60:02}"

def render_question(material):
    v=material["input"];h=v["household"];s=v["situation"]
    lines=[f'## {h["country"]} · {h["role"]} · {s["date"]}',
           "参考任务情境；物理后果未计算，本页仅用于核查家庭与方案。",
           f'家庭成员：'+ "；".join(f'{m["id"]}，{m["reference_age"]}岁，{m["activity"]}' for m in h["members"]),
           "本题可控："+ "、".join(e["name"] for e in h["equipment"] if e["controlled"]),
           "温度偏好："+canonical(h["comfort_preferences"]),
           s["task_statement"],
           "响应事件："+clock(s["event"]["start_min"])+"—"+clock(s["event"]["end_min"]),
           "","任务条件："]
    lines += ["", "当日生活安排："]
    for e in s["member_schedule"]:
        lines.append(f'- {e["member"]} {clock(e["start_min"])}—{clock(e["end_min"])}：{e["kind"]}，{e["location"]}。')
    for m in s["meals"]:
        lines.append(f'- {m["kind"]} {clock(m["start"])}—{clock(m["end"])}：{m["location"]}，成员'+"、".join(m.get("participants",[]))+"。")
    for m in s["bathing_services"]:
        lines.append(f'- {m["member_id"]} 洗浴 {clock(m["start"])}—{clock(m["end"])}'+("，由"+m["assistant_id"]+"协助。" if m.get("assistant_id") else "。"))
    for c in s.get("care",[]):
        lines.append("- 照护安排："+canonical(c))
    lines += ["", "程序任务："]
    for t in s["tasks"]:
        dep="；须接在同批"+NAMES[t["ready_after_function"]]+"结束之后" if t.get("ready_after_function") else ""
        lines.append(f'- {NAMES[t["function"]]}：{clock(t["ready_min"])}后可安排，{clock(t["deadline_min"])}前完成，完整程序{t["duration_min"]}分钟{dep}。')
    for arm in ("A","B"):
        lines+=["",f"### 方案{arm}"]
        p=v["plans"][arm]
        for t in p["programmes"]:
            lines.append(f'- {NAMES[t["function"]]}：{clock(t["start_min"])}—{clock(t["end_min"])}，完整程序。')
        for r in p["controls"]:
            f=r["function"]
            if f=="EV":
                text=f'许可{clock(r["permitted_start_min"])}—{clock(r["permitted_end_min"])}充电，达到{r["stop_at_soc"]*100:g}%即停止；该窗口不是实际充电时长。'
            elif f=="AC":
                text=f'{clock(r["start_min"])}—{clock(r["end_min"])}设为{r["cooling_setpoint_C"]:g}°C；这是设定值。'
            else:
                text=f'加热许可{clock(r["heating_permitted_start_min"])}—{clock(r["heating_permitted_end_min"])}，目标{r["tank_setpoint_C"]:g}°C。'
            lines.append("- "+NAMES[f]+"："+text)
    return "\n".join(lines)

def build(households,batch,out,expected_household_sha256=None):
    households=Path(households);batch=Path(batch);out=Path(out)
    raw=households.read_bytes();source_sha=hashlib.sha256(raw).hexdigest()
    if expected_household_sha256 and source_sha!=expected_household_sha256:
        raise ValueError("HOUSEHOLD_SOURCE_CHANGED")
    cases={c["case_id"]:c for c in (json.loads(s) for s in raw.splitlines() if s.strip())}
    parent_raw=(batch/"PAIR_INDEX.jsonl").read_bytes()
    indexes=[json.loads(s) for s in parent_raw.splitlines() if s.strip()]
    out.mkdir(parents=True,exist_ok=False)
    rows=[];counts=Counter();samples={};plan_same=Counter()
    for i in indexes:
        pair=read(batch/i["relative_path"])
        if hashlib.sha256((batch/i["relative_path"]).read_bytes()).hexdigest()!=i["pair_file_sha256"]:
            raise ValueError("PARENT_PAIR_FILE_CHANGED")
        context_document=read(batch/i["context_relative_path"])
        c=cases[i["case_id"]]
        material=compile_question(c,context_document,pair,i)
        for arm in ("A","B"):
            if material["lineage"]["parent"][arm+"_sha256"]!=i[arm+"_sha256"]:
                raise ValueError("PLAN_CHANGED_IN_PROJECTION")
            plan_same[arm]+=1
        rel=f'inputs/{material["question_id"][:2]}/{material["question_id"]}.json.gz'
        if (out/rel).exists():
            raise ValueError("DUPLICATE_QUESTION_INPUT")
        save(out/rel,material)
        h=material["input"]["household"]
        row={**{k:i[k] for k in ("index","case_id","date","pair_id","scenario_sha256",
                                  "A_sha256","B_sha256","event","context_sha256")},
             "question_id":material["question_id"],
             "input_without_consequences_sha256":material["input_without_consequences_sha256"],
             "task_context_sha256":material["lineage"]["task_context_sha256"],
             "input_relative_path":rel,
             "input_file_sha256":hashlib.sha256((out/rel).read_bytes()).hexdigest(),
             "parent_pair_relative_path":i["relative_path"],
             "parent_context_relative_path":i["context_relative_path"]}
        rows.append(row)
        key=(h["country"],c["household"]["role_id"])
        samples.setdefault(key,material)
        counts["questions"]+=1
        if "_SCENE" in i["context_relative_path"]:counts["scene_contexts"]+=1
        if (counts["questions"]%2000)==0:
            print(canonical(dict(questions=counts["questions"])),flush=True)
    index_path=out/"QUESTION_INDEX.jsonl"
    index_path.write_text("".join(canonical(r)+"\n" for r in rows))
    result=dict(schema="eb.question_input_package.v1",households=len(cases),questions=len(rows),
        source_household_sha256=source_sha,parent_pair_index_sha256=hashlib.sha256(parent_raw).hexdigest(),
        question_index_sha256=hashlib.sha256(index_path.read_bytes()).hexdigest(),
        parent_batch=str(batch),parent_households=str(households),
        A_plans_unchanged=plan_same["A"],B_plans_unchanged=plan_same["B"],
        scene_contexts=counts["scene_contexts"],country_role_preview_cells=len(samples),
        physics_executed=False,physical_outcomes=None,human_answers=None,
        collection_ready=False,task_semantics="eb.shared_daily_tasks.v4",
        purpose="frozen inputs for paired physics and later human-facing UI91 projection")
    save(out/"MANIFEST.json",result)
    (out/"PRIVATE_REVIEW48.md").write_text("# 家庭与A/B核查样例\n\n"+"\n\n---\n\n".join(render_question(x) for x in samples.values())+"\n")
    if hashlib.sha256(households.read_bytes()).hexdigest()!=source_sha or (batch/"PAIR_INDEX.jsonl").read_bytes()!=parent_raw:
        raise ValueError("PARENT_SOURCE_MUTATED")
    print(canonical(result),flush=True)
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--households",required=True,type=Path)
    p.add_argument("--batch",required=True,type=Path)
    p.add_argument("--out",required=True,type=Path)
    p.add_argument("--expected-household-sha256")
    a=p.parse_args()
    build(a.households,a.batch,a.out,a.expected_household_sha256)

if __name__=="__main__":
    main()
