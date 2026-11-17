"""Portable judgment inputs bound to exact native plans and scene contexts."""
from copy import deepcopy
from .common import digest
from .task_context import upgrade_problem, audit_tasks
from ..household_stage1.generator.views import current_household, day_routine

FUNCTIONS = {"washer": "WM", "dryer": "DR", "dishwasher": "DW",
             "ac_setpoint": "AC", "tank_setpoint": "WH",
             "ev_charge_window": "EV"}

def plan_view(plan, case, base_plan=None):
    controlled = set(case["household"]["controlled_function_ids"])
    task_names = {r["need_id"]: FUNCTIONS[r["kind"]] for r in plan["tasks"]}
    programmes = []
    for row in sorted(plan["tasks"], key=lambda x: x["kind"]):
        fun = FUNCTIONS[row["kind"]]
        r = dict(function=fun, start_min=row["start_min"],
                 end_min=row["end_min"], controlled=fun in controlled,
                 programme="完整程序，不中断")
        if row.get("depends_on_need_id"):
            r["same_load_after"] = task_names[row["depends_on_need_id"]]
        programmes.append(r)
    controls = []
    for row in sorted(plan["controls"],
                      key=lambda x: (x["kind"], x["start_min"])):
        fun = FUNCTIONS[row["kind"]]
        if row["kind"] != "ev_charge_window" and row["start_min"] >= 1440:
            continue
        r = dict(function=fun, controlled=fun in controlled)
        if row["kind"] == "ev_charge_window":
            r.update(execution_mode=('normal_inherited' if base_plan is None or row in base_plan['controls'] else 'original_window_override_avoids_VPP'),
                     permitted_start_min=row["start_min"],
                     permitted_end_min=row["end_min"],
                     stop_at_soc=row["stop_at_target_soc"],
                     meaning="许可窗口内连续充电，达到目标电量即停止；许可窗口不等于实际充电时长")
        elif row["kind"] == "ac_setpoint":
            r.update(start_min=max(0,row["start_min"]),
                     end_min=min(1440,row["end_min"]),
                     cooling_setpoint_C=row["cooling_setpoint_C"],
                     meaning="空调设定温度，室内实际温度另由仿真给出")
        else:
            r.update(heating_permitted_start_min=row["start_min"],
                     heating_permitted_end_min=row["end_min"],
                     tank_setpoint_C=row["value_C"],
                     meaning="加热许可窗口和水箱目标温度；不表示此时段持续满功率加热")
        controls.append(r)
    return dict(programmes=programmes, controls=controls,
                scope="完整当日安排，包括本次跨夜EV尾段")

def compile_question(case, context_document, pair, index):
    context = context_document.get("context", context_document)
    if pair["source_household_sha256"] != digest(case):
        raise ValueError("HOUSEHOLD_IDENTITY_MISMATCH")
    if context["A"] != pair["A"]:
        raise ValueError("CONTEXT_A_MISMATCH")
    if context["events"] != [index["event"]]:
        raise ValueError("CONTEXT_EVENT_MISMATCH")
    if digest(context) != index["context_sha256"]:
        raise ValueError("CONTEXT_IDENTITY_MISMATCH")
    for arm in ("A", "B"):
        if digest(pair[arm]) != index[arm + "_sha256"]:
            raise ValueError("PLAN_IDENTITY_MISMATCH")
    for key in ("pair_id", "scenario_sha256", "context_sha256", "event"):
        if pair[key] != index[key]:
            raise ValueError("PAIR_INDEX_IDENTITY_MISMATCH")
    problem = upgrade_problem(context_document["problem"])
    tasks = problem["task_context"]
    if digest({k:v for k,v in tasks.items() if k!="sha256"}) != tasks["sha256"]:
        raise ValueError("TASK_CONTEXT_CONTENT_HASH_MISMATCH")
    if tasks["household_case_sha256"]!=digest(case) or tasks["date"]!=pair["date"] or tasks["household_id"]!=case["case_id"]:
        raise ValueError("TASK_CONTEXT_SOURCE_IDENTITY_MISMATCH")
    if pair.get("task_context_sha256")!=tasks["sha256"] or index.get("task_context_sha256")!=tasks["sha256"]:
        raise ValueError("SEALED_TASK_IDENTITY_MISMATCH")
    by_kind={r["kind"]:r for r in tasks["tasks"]}
    for job in problem["jobs"]:
        task=by_kind[job["kind"]]
        need=next(n for n in context["needs"] if n["need_id"]==job["need_id"])
        if job["release_min"]!=task["ready_min"] or job["task_load_id"]!=task["load_id"] or job["task_context_sha256"]!=tasks["sha256"] or need["task_context_sha256"]!=tasks["sha256"] or need["release_min"]!=task["ready_min"]:
            raise ValueError("TASK_CONTEXT_NOT_BOUND_TO_PLAN_PROBLEM")
    service_origins=deepcopy(tasks["service_origins"])
    if service_origins.get("EV"):
        service_origins["EV"].pop("parking",None)
        service_origins["EV"]["given_connection_window_min"]=deepcopy(problem["EV"]["episode"]["connection_interval"])
        service_origins["EV"]["source_parking_window_min"]=deepcopy(problem["EV"]["episode"]["source_parking_interval"])
    for arm in ("A", "B"):
        errors = audit_tasks(tasks, pair[arm])
        if errors:
            raise ValueError(arm + ":" + ",".join(errors))
    # Non-EV control tails outside the question cannot hide another intervention.
    for arm in ("A", "B"):
        tail = [r for r in pair[arm]["controls"]
                if r["kind"] != "ev_charge_window" and r["start_min"] >= 1440]
        if arm == "A":
            baseline_tail = tail
        elif sorted(tail,key=digest) != sorted(baseline_tail,key=digest):
            raise ValueError("UNSHOWN_NON_EV_TAIL_CHANGE")
    daily = day_routine(case, pair["date"])
    input_view = dict(
        household=current_household(case),
        situation={
            **daily, "event": deepcopy(index["event"]),
            "tasks": [{k:v for k,v in t.items()} for t in tasks["tasks"]],
            "service_origins":service_origins,
            "information_perspective":tasks["information_perspective"],
            "task_statement": "本题任务在生成A/B前已按家庭生活安排固定。下列来源列明衣物和餐具所属批次及准备时间；A/B必须处理同一批次，烘干须等待同批洗衣完成。",
            "question_unit": "一个独立的单日任务情境，跨夜EV延续至本次结束",
        },
        plans={arm:plan_view(pair[arm],case,pair["A"]) for arm in ("A","B")},
        consequences=None,
    )
    base_input_hash = digest(input_view)
    identity = {k:deepcopy(index[k]) for k in
                ("pair_id","scenario_sha256","A_sha256","B_sha256",
                 "event","context_sha256")}
    question_id = digest(dict(parent=identity, input_sha256=base_input_hash,
                              task_context_sha256=tasks["sha256"]))
    return dict(
        schema="eb.question_judgment_input.v2", question_id=question_id,
        input=input_view, input_without_consequences_sha256=base_input_hash,
        lineage=dict(parent=identity,
                     household_case_sha256=digest(case),
                     task_context_sha256=tasks["sha256"],
                     parent_context_relative_path=index["context_relative_path"],
                     source_observations_and_legacy_cards_excluded_from_input=True,
                     generator_judgment_and_coverage_fields_excluded_from_input=True),
        targets=None, collection_ready=False,
    )
