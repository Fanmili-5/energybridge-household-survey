"""Participant-confirmed ordinary plan -> EB offer -> human decision, before execution."""
from copy import deepcopy
import math
import json
from common import digest, profile_text

VERSION = "eb.plan_pair_pilot.v0.2"
DEVICES = {
    "ac": "空调", "washer": "洗衣机", "dishwasher": "洗碗机", "dryer": "烘干机",
    "electric_water_heater": "电热水器", "home_ev": "家用电动车充电",
}
TASKS = {"washer", "dishwasher", "dryer"}
EDITABLE = TASKS | {"ac"}
CONTEXT = {
    "id": "summer_evening_plan_pair_v2", "decision_h": 16,
    "event": {"id": "evening_peak", "trigger_h": 18, "end_h": 19},
    "facts": [
        "请设想一个夏季傍晚：现在是 16:00，希望在 18:00—19:00 减少集中用电。",
        "按您家拥有的电器，选择在这个情境下原本会怎样安排；并不要求它是今天真实发生的事。",
        "空调调整仅在 18:00—19:00 生效，之后恢复原设定；其他任务须在您选择的时间范围内完成。",
        "电价假设全天 0.60 元/度，无额外补偿。把任务移到其他时段，不等于节省了电费。",
        "本轮只比较用电安排，尚未运行两份方案的配对仿真，不展示节电量、节省金额或室温预测。",
        "电热水器和电动车充电本轮保持原安排；暂不参与调整。",
    ],
    "tariff": {"cny_per_kwh": 0.6, "compensation_cny": 0},
    "weather": {"source": "hypothetical_summer_context", "temperature_c": None},
    "building": {"binding_status": "not_bound_for_planning_pilot"},
    "execution_status": "not_run", "forecast_status": "not_run",
}

def number(v, lo, hi):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not lo <= v <= hi:
        raise ValueError("原安排的时间或温度不在允许范围内")
    return float(v)

def ordinary_plan(profile, raw):
    inventory = profile["B05"]
    owned = inventory["value"] if inventory["response_status"] == "answered" else None
    if not isinstance(owned, list) or not owned or any(d not in DEVICES for d in owned):
        raise ValueError("请先明确家中有哪些电器；没有这些设备时，本轮不生成调整方案")
    if not isinstance(raw, dict) or set(raw) != set(owned):
        raise ValueError("原安排必须与勾选的家庭电器一致")
    records = {}
    for d in DEVICES:
        if d not in owned:
            continue
        r = raw[d]
        if not isinstance(r, dict):
            raise ValueError("电器安排格式无效")
        if d not in EDITABLE:
            if r != {"mode": "unchanged"}:
                raise ValueError("本轮暂不调整热水器或电动车充电")
            records[d] = dict(r)
            continue
        if type(r.get("active")) is not bool:
            raise ValueError("请确认这台电器在本次情境中是否使用")
        if not r["active"]:
            if set(r) != {"active"}:
                raise ValueError("不使用的设备不应附带任务")
            records[d] = {"active": False}
        elif d == "ac":
            if set(r) != {"active", "setpoint"}:
                raise ValueError("空调原安排字段无效")
            records[d] = {"active": True, "setpoint": number(r["setpoint"], 20, 30)}
        else:
            if set(r) != {"active", "start_h", "duration_h", "earliest_h", "deadline_h"}:
                raise ValueError("请补全任务的原开始时间、时长、最早开始与最晚完成时间")
            v = {k: number(r[k], 0.5 if k == "duration_h" else 16, 4 if k == "duration_h" else 24)
                 for k in ("start_h", "duration_h", "earliest_h", "deadline_h")}
            if not v["earliest_h"] <= v["start_h"] <= v["deadline_h"] - v["duration_h"]:
                raise ValueError(f"{DEVICES[d]}的原安排无法在所选时间范围内完成，请检查")
            records[d] = {"active": True, **v}
    # Each explicitly scheduled task is independent. No unreported washer/dryer dependency is invented.
    # The UI asks to leave dependent drying out of this bounded pilot.
    if not any(r.get("active") for d, r in records.items() if d in EDITABLE):
        raise ValueError("至少需要一台本次使用且可调整的电器；不使用时无需评价调整方案")
    return {"devices": records, "confirmation_scope": "ordinary_arrangement_for_this_hypothetical_event"}

def executable(original):
    if 'eb_ordinary_plan' in original:
        return deepcopy(original['eb_ordinary_plan'])
    plan = {"appliances": {}}
    for d, r in original["devices"].items():
        if r.get("active"):
            if d == "ac":
                plan["setpoint"] = r["setpoint"]
            elif d in TASKS:
                plan["appliances"][d + "_start_h"] = r["start_h"]
    return plan

def validate_offer(original, plan):
    expected = executable(original)
    if not isinstance(plan, dict) or set(plan) != set(expected):
        raise ValueError("方案增加或遗漏了可执行控制字段")
    if not isinstance(plan["appliances"], dict) or set(plan["appliances"]) != set(expected["appliances"]):
        raise ValueError("方案增加、遗漏或调整了不适用的电器任务")
    if "setpoint" in plan:
        number(plan["setpoint"], 20, 30)
    for d, r in original["devices"].items():
        if d in TASKS and r.get("active"):
            number(plan["appliances"][d + "_start_h"], r["earliest_h"], r["deadline_h"] - r["duration_h"])
    return deepcopy(plan)

def at(h):
    m = round(h * 60)
    return f"{m // 60:02d}:{m % 60:02d}"

def pair_display(original, proposal, baseline_source):
    validate_offer(original, proposal)
    rows = []
    for d, r in original["devices"].items():
        changed = False
        if d not in EDITABLE:
            before = after = "保持原安排（本轮不调整）"
        elif not r["active"]:
            before = after = "本次不使用"
        elif d == "ac":
            before = f"18:00—19:00 设为 {r['setpoint']:g}℃"
            after = f"18:00—19:00 设为 {proposal['setpoint']:g}℃；19:00 恢复 {r['setpoint']:g}℃"
            changed = proposal["setpoint"] != r["setpoint"]
        else:
            start = proposal["appliances"][d + "_start_h"]
            before = f"{at(r['start_h'])}—{at(r['start_h'] + r['duration_h'])}"
            after = f"{at(start)}—{at(start + r['duration_h'])}；最晚 {at(r['deadline_h'])} 完成"
            changed = start != r["start_h"]
        rows.append({"device_id": d, "device": DEVICES[d], "original": before, "proposal": after,
                     "changed": changed, "change": "有调整" if changed else "不变"})
    return {"title": "您确认的原安排与 EB 建议", "context": CONTEXT,
            "baseline_source": baseline_source, "rows": rows,
            "has_changes": any(r["changed"] for r in rows),
            "question": "在这个情境下，您是否同意用 EB 建议替换原安排？",
            "notice": "尚未执行或进行配对仿真；调整时间和设定值不代表已验证节电或舒适效果。"}

SCORE_FIELDS = ("score", "comfort_score", "energy_score", "vpp_score")
FEEDBACK_VERSION = "eb.binary_decision_four_scores_reason.v3"

def decision_record(job, payload):
    result = job["result"]
    if job.get("flow") == "paired_ep_v1":
        from paired_contract import VERSION as paired_version
        if result.get("schema_version") != paired_version:
            raise ValueError("这是旧版评价情境，请新建案例使用当前评分题目；历史回答保持原样")
    for k in ("display_hash", "original_plan_hash", "proposal_plan_hash"):
        if payload.get(k) != result[k]:
            raise ValueError("两份方案或展示版本已变化，请重新打开")
    choice = payload.get("choice")
    if choice not in {"accept", "reject"}:
        raise ValueError("请选择是否同意调整")
    scores = {key: payload.get(key) for key in SCORE_FIELDS}
    required=result.get("feedback_contract",{}).get("required_scores",[])
    if any(scores.get(key) is None for key in required):
        raise ValueError("请完成整体、舒适、用电费用和响应安排四项评分")
    for value in scores.values():
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or not 1 <= value <= 5):
            raise ValueError("评分须为 1—5 之间的数值，可填小数；未评分可留空")
    reason = payload.get("comment", "")
    if not isinstance(reason, str) or len(reason) > 1000:
        raise ValueError("反馈须为 1000 字以内")
    reason = reason.strip()
    if result.get("feedback_contract", {}).get("required_comment") and not reason:
        raise ValueError("请简要填写同意或不同意的最主要原因")
    return {"feedback_version": FEEDBACK_VERSION, "choice": choice, "comment": reason or None,
            **scores, "score_status": {k: "skipped" if v is None else "answered" for k, v in scores.items()},
            "comment_status": "answered" if reason else "skipped",
            "selected_plan": "proposal" if choice == "accept" else "original" if choice == "reject" else None,
            "pending_resolution": False,
            "execution_status": "not_run",
            **{k: payload[k] for k in ("display_hash", "original_plan_hash", "proposal_plan_hash")},
            "target_source": "engineering_test" if job["data_origin"] == "synthetic_engineering_test" else "household_representative_self_report"}

def candidate(job, decision):
    result = job["result"]
    target = {"decision": decision["choice"], **{k: decision[k] for k in SCORE_FIELDS if decision.get(k) is not None}}
    if decision["comment"]:
        target["comment"] = decision["comment"]
    public_answers = profile_text(job["profile"])
    if job.get("flow") == "paired_ep_v1":
        from questionnaire_persona import visible_profile
        public_answers = visible_profile(job["profile"], job["questionnaire_snapshot"])
        config=result.get("household_config",job.get("household_config"))
        if config:
            if config['observable_profile']!=public_answers:raise ValueError('Household evidence differs from questionnaire snapshot')
            public_answers=deepcopy(config['observable_profile'])
    return {"schema_version": result.get("schema_version", VERSION), "task": "plan_judgement", "case_id": job["id"],
            "flow": job.get("flow", "planning_only_legacy"),
            "simulation_status": result.get("simulation_status", "not_run"),
            "prediction": result.get("prediction"), "provenance": result.get("provenance"),
            "scenario": job.get("scenario"),
            "feedback_version": decision.get("feedback_version"),
            "score_status": decision.get("score_status"),
            "questionnaire_version": job.get("questionnaire_version", "legacy_energy_attitude_questions"),
            "household_config": result.get("household_config",job.get("household_config")),
            "household_config_hash": result.get("household_config_hash",job.get("household_config_hash")),
            "questionnaire_hash": job.get("questionnaire_hash"),
            "submission_hash": job.get("submission_hash"),
            "household_submission_id": job.get("household_submission_id"),
            "questionnaire_snapshot": job.get("questionnaire_snapshot"),
            "profile_components": job.get("profile_components"),
            "household_id": job["household_id"], "respondent_id": job["respondent_id"],
            **({"household_record":deepcopy(job["household_record"]),"household_record_hash":job["household_record_hash"]} if job.get("household_record") else {}),
            "profile_snapshot": job["profile"], "data_origin": job["data_origin"],
            "target_source": decision["target_source"], "has_supervised_answer": True,
            "original_plan": job["original_plan"], "proposal_plan": result["proposal_plan"],
            **({"baseline_plan":deepcopy(result["baseline_plan"]),"baseline_plan_hash":result["baseline_plan_hash"]} if result.get('baseline_plan') else {}),
            **{k: result[k] for k in ("display_hash", "original_plan_hash", "proposal_plan_hash")},
            "feedback_basis": "shown_plan_pair_and_ep_prediction" if job.get("flow")=="paired_ep_v1" else "shown_plan_pair", "assessment_stage": result.get("assessment_stage", "before_execution"),
            "assessment_cutoff_sim_h": result.get("assessment_cutoff_sim_h"),
            "feedback_completeness": "four_scores" if all(decision.get(k) is not None for k in SCORE_FIELDS) else "partial_scores",
            "training_release": False, "execution_status": "not_run",
            "split_group": job["household_id"],
            "messages": [
                {"role": "system", "content": "代表给定家庭判断是否接受本次能源安排调整。依据家庭资料、原安排和展示的建议（含已提供的模拟运行结果），返回 decision（accept/reject）、score（整体）、comfort_score（舒适）、energy_score（用电与费用满意度）、vpp_score（本次需求响应处理满意度，含安排调整和自主决定体验）及有依据的 comment。评分为 1—5，越高越适合该家庭；整体分独立评价，不从其他分数计算。缺失评分不补分；不得虚构执行结果。"},
                {"role": "user", "content": json.dumps({"household_answers": public_answers,
                    "display": result["display"].get("participant_view", result["display"])}, ensure_ascii=False)},
                {"role": "assistant", "content": json.dumps(target, ensure_ascii=False)},
            ]}
