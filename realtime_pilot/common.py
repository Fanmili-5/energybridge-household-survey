"""Local pilot contract. No labels or household facts are imputed."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
from questionnaire_persona import build_questions

ROOT = Path(__file__).resolve().parent
STUDY = ROOT.parent
UPSTREAM = STUDY / "upstream_2b17ae6"
CODEBOOK = json.loads((STUDY / "QUESTIONNAIRE_CODEBOOK.json").read_text())
QUESTIONS = {q["id"]: q for q in CODEBOOK["questions"]}
PROFILE_IDS = CODEBOOK["profile_defaults"]
RATING_IDS = ["R01", "R02", "R03", "R04", "R05", "R06", "R07"]
VERSION = "eb.realtime_pilot.v0.1"
SPECIAL = {"dont_know", "declined", "skipped", "not_applicable", "cannot_judge"}
PROPOSAL_PROFILE_QUESTIONS = build_questions(QUESTIONS)
QUESTION_LOOKUP = {**QUESTIONS, **{q["id"]: q for q in PROPOSAL_PROFILE_QUESTIONS}}
SCENARIO = {
    "id": "tianjin_prototype_july01_ac_washer_v1",
    "binding_mode": "shared_explicit_simulated_scenario",
    "title": "夏季傍晚的空调与洗衣安排",
    "description": "请假设您家处在下面的模拟情境中，按全家人的取舍评价。住宅采用研究用原型，并非您家住宅的重建。",
    "facts": [
        "采用天津典型气象文件的 7 月 1 日天气，不代表今天的实际天气。",
        "模型只有一个居住热区；展示的是该居住区域的室温，不区分卧室和客厅。",
        "本轮只允许调整空调和洗衣机；住宅模型中的其他背景用电保留，不代表您家拥有这些设备。",
        "情境设定家人在傍晚居家；初始空调设定为 25.5℃，之后由控制器调整。",
        "洗衣任务持续 2 小时，允许在 16:00—22:00 内安排，原计划 18:00 开始。",
        "目标是在 18:00—19:00 减少集中用电时段的负担，并兼顾家庭需要。",
        "电价假设为全天 0.60 元/度、无额外补偿；这是研究设定，不是您家实际电价。",
        "假设采用系统给出的方案，查看模拟结果后再评价；生成方案不代表您已同意采用。",
    ],
    "tariff": {"id": "study_flat_060_v1", "cny_per_kwh": 0.6, "compensation_cny": 0},
    "event": {"id": "pilot_event", "trigger_h": 18.0, "end_h": 19.0, "day": 1},
    "assessment_stage": "service_closed",
    "assessment_cutoff": "simulation day 1 24:00; washer deadline 22:00",
    "calibration_status": "unvalidated_research_prototype_not_individual_home",
}

def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()

def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    os.replace(tmp, path)

def normalize_answers(raw, ids, questions=None):
    if not isinstance(raw, dict) or set(raw) - set(ids):
        raise ValueError("包含未定义的题目")
    out = {}
    for qid in ids:
        q = (questions or QUESTIONS)[qid]
        v = raw.get(qid)
        if v is None or v == "" or v == []:
            out[qid] = {"value": None, "response_status": "skipped"}
            continue
        if q["type"] == "member_list":
            from member_questionnaire import normalize_members
            out[qid] = {"value": normalize_members(v, q), "response_status": "answered"}
            continue
        if q["type"] == "text":
            if not isinstance(v, str) or len(v) > 1000:
                raise ValueError("反馈须为 1000 字以内的文字")
            trimmed=v.strip()
            out[qid] = {"value": trimmed or None, "response_status": "answered" if trimmed else "skipped"}
            continue
        allowed = [o["value"] for o in q["options"]]
        values = v if q["type"] == "multi_choice" else [v]
        if not isinstance(values, list) or any(type(x) is bool or x not in allowed for x in values):
            raise ValueError(f"{qid} 选项无效")
        if q["type"] == "multi_choice":
            if len(values) != len(set(values)) or (set(values) & (SPECIAL | {"none"}) and len(values) > 1):
                raise ValueError(f"{qid} 的“以上都没有／说不清”不能与其他选项并选")
        if len(values) == 1 and values[0] in SPECIAL:
            out[qid] = {"value": None, "response_status": values[0]}
        else:
            out[qid] = {"value": v, "response_status": "answered"}
    return out

def answer_text(qid, cell):
    if cell["response_status"] != "answered":
        return {"dont_know": "说不清", "declined": "不愿回答", "skipped": "未回答"}.get(cell["response_status"], cell["response_status"])
    labels = {o["value"]: o["label"] for o in QUESTION_LOOKUP[qid].get("options", [])}
    value = cell["value"]
    return "、".join(labels.get(x, str(x)) for x in value) if isinstance(value, list) else labels.get(value, str(value))

def profile_text(profile):
    return "\n".join(f"{QUESTION_LOOKUP[k]['prompt']} 回答：{answer_text(k, cell)}" for k, cell in profile.items() if k in QUESTION_LOOKUP)

def make_persona(profile):
    # All physical values below are declared scenario assumptions, never inferred from attitudes.
    return {
        "id": "pilot_shared_physical_context", "schema_version": "2.0", "tags": {},
        "survey_profile": profile,
        "schedule": {"wake_h": 7, "leaves_home_h": 9, "returns_home_h": 17,
                     "sleep_h": 23, "occupancy_pattern": "commuter",
                     "weekend_leaves_h": 9, "weekend_returns_h": 17},
        "appliances": {
            "ac": {"present": True, "setpoint_preferred_min_c": 24, "setpoint_preferred_max_c": 26, "temp_tolerance_c": 1, "mode": "cooling"},
            "washer": {"present": True, "earliest_h": 16, "latest_h": 22, "preferred_h": 18,
                       "duration_h": 2, "power_kw": 1.5, "shiftable": True, "dr_adjustable": True},
            "dishwasher": {"present": False}, "dryer": {"present": False},
            "water_heater": {"present": False}, "ev": {"present": False},
        },
        "llm_prompts": {"system_prompt": profile_text(profile), "agent_context": "Direct questionnaire responses; no hidden persona."},
        "meta": {"persona_type": "questionnaire_pilot", "physical_facts_source": "declared_shared_scenario"},
    }

def training_candidate(job, rating):
    fields = {"R01": "score", "R02": "comfort_score", "R03": "cost_score", "R04": "service_score", "R05": "vpp_score", "R06": "energy_score", "R07": "comment"}
    target = {fields[k]: c["value"] for k, c in rating["answers"].items() if c["response_status"] == "answered"}
    return {
        "schema_version": VERSION, "task": "outcome_rating",
        "household_id": job["household_id"], "respondent_id": job["respondent_id"],
        "case_id": job["id"], "profile_version": job["profile_hash"], "display_hash": job["result"]["display_hash"],
        "feedback_basis": "shown_simulation", "assessment_stage": SCENARIO["assessment_stage"],
        "data_origin": job["data_origin"], "target_source": rating["target_source"],
        "profile_snapshot": job["profile"], "has_supervised_answer": bool(target),
        "training_release": False,
        "release_reason": "pilot_only; physical validity, sampling, and human-response QA pending",
        "messages": [
            {"role": "system", "content": "依据给定家庭资料，模拟该家庭对展示的能源安排和模拟结果的评价。分数范围 1—5；缺失项不补分。"},
            {"role": "user", "content": json.dumps({"household_answers": profile_text(job["profile"]), "scenario": job.get("scenario", SCENARIO), "display": job["result"]["display"]}, ensure_ascii=False)},
            {"role": "assistant", "content": json.dumps(target, ensure_ascii=False)},
        ],
        "response_status": {k: v["response_status"] for k, v in rating["answers"].items()},
    }
