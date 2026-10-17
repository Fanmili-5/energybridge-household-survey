"""Bind a small, input-selected readability pilot to frozen V18 cases.

Only source profile, date and predeclared proposal mechanism are read for
selection. No physical outcomes, human answers or fabricated participant IDs.
This is a readability instrument, not a powered role-effect experiment.
"""
import collections
import hashlib
import json
from pathlib import Path
import sys

REPAIR = Path(__file__).resolve().parents[1]
STAGE = REPAIR.parent / "profile_conditioned_production_20261008_v18"
sys.path.insert(0, str(STAGE / "code"))
from common import read, save, sha, rank, school_guard


def tags(world):
    ages = [m["age_years"] for m in world["members"]]
    n, g = world["N"], world["G"]
    k = len({t for d in world["parameter_pack"]["devices"] for t in d["types"]})
    out = {f"K{k}", "N1" if n == 1 else "N2to4" if n <= 4 else "N5plus",
           "G1" if g == 1 else "G2" if g == 2 else "G3plus"}
    if min(ages) < 6: out.add("child_care")
    if max(ages) >= 75: out.add("older75plus")
    if any(m["age_years"] >= 18 and m["employment_status"] == "unknown" for m in world["members"]): out.add("adult_employment_unknown")
    if any(m["age_years"] >= 18 and m["current_work_source_proxy"] == 2 for m in world["members"]): out.add("changed_work_code2")
    return out


def quiz(world, pair):
    questions = []
    def add(code, prompt, expected, source):
        questions.append({"question_id": code, "prompt": prompt,
                          "expected_given_fact": expected, "source_field": source,
                          "raw_actor_answer": None, "scored_correct": None})
    add("household", "这户有几位常住成员、几代？非同住协助者是否计入？",
        {"N": world["N"], "G": world["G"], "nonresident_counts_as_resident": False}, "world.N,G;operating_context")
    add("living_day", "这题的完整一天从何时到何时？跨午夜是否重置设备状态？",
        {"start": pair["date"] + " 08:00", "end": "次日08:00", "midnight_resets_state": False}, "pair.primary_evaluation_min")
    add("unknown", "角色中哪些成年成员就业未知？这些成员的给定活动能否当作实测职业？",
        {"unknown_adult_member_labels": ["成员"+m["local_id"] for m in world["members"] if m["age_years"] >= 18 and m["employment_status"] == "unknown"],
         "given_activity_is_observed_job": False}, "world.members.employment_evidence/reference_activity_role")
    add("negotiation", "某人有人工操作可用时间，是否就代表已经同意额外协助？",
        {"availability_means_consent": False}, "world.service_semantics.negotiable_conditions")
    laundry = [n for n in pair["needs_A"] if n["kind"] == "washer" and n["release_min"] < 1440]
    if laundry:
        n = laundry[0]
        add("laundry", "洗涤结束、衣物可穿和人工取用是否同一件事？本题程序与取用各有什么期限？",
            {"wash_end_means_wearable": n["wearable_clothes_ready_at_program_end"],
             "chain_end_means_wearable": n["wearable_clothes_ready_after_required_chain"],
             "program_deadline_abs_min": n["deadline_min"], "retrieval_deadline_abs_min": n["delivery_deadline_min"]}, "pair.needs_A[washer]")
    ev = [n for n in pair["needs_A"] if n["kind"] == "ev" and n["release_min"] < 1440]
    if ev:
        n = ev[0]
        add("vehicle", "谁负责插拔、谁承担驾驶服务？本题85%目标是否对应次晨实际给定出行？目标未达是否必然无法完成行程？",
            {"handling_operator_id": world["given_transport_contract"]["handling_operator_id"],
             "driver_is_resident": False, "target_SOC": .85,
             "next_access_is_actual_trip": n["next_access_is_actual_trip"],
             "target_failed_implies_trip_failed": False}, "world.given_transport_contract;pair.needs_A[ev]")
    if any("ac" in d["types"] for d in world["parameter_pack"]["devices"]):
        add("comfort", "27℃给定控制边界或模型空气温度，能否直接当作角色个人舒适阈值/评价？",
            {"given_control_bound_is_personal_comfort": False, "air_temperature_is_subjective_comfort": False}, "world.service_semantics")
    return questions


def main():
    school_guard()
    dest = REPAIR / "pilot_materials_v18"
    source = read(STAGE / "SELECTION50.json")["records"]
    frontend = {h['household_id']:h for h in read(STAGE / 'frontend_release/INDEX50.json')['households']}
    choices = []
    for h in source:
        world = read(STAGE / h["world_path"])
        choices.append((h, world, tags(world)))
    selected, covered = [], set()
    for _ in range(8):
        h, w, ts = max(choices, key=lambda item: (len(item[2]-covered), -rank(item[0]["household_id"], "v18-readability-pilot")))
        selected.append((h, w, ts));covered |= ts
        choices = [item for item in choices if item[0]["household_id"] != h["household_id"]]
    used_mechanisms, cases, slots = set(), [], []
    for i, (h, w, ts) in enumerate(selected, 1):
        candidate_pairs = [(r, read(STAGE / r["pair_path"])) for r in h["rounds"]]
        household_cases = []
        for _ in range(2):
            r, pair = max(candidate_pairs, key=lambda item: (item[1]["design_condition"] not in used_mechanisms, -rank(item[1]["case_id"], "v18-readability-case")))
            candidate_pairs = [item for item in candidate_pairs if item[1]["case_id"] != pair["case_id"]]
            used_mechanisms.add(pair["design_condition"])
            consumer_path = f"consumers/{h['household_id']}/{r['round_index']:02d}.json"
            task = {"case_id": pair["case_id"], "household_id": h["household_id"], "round_index": r["round_index"],
                    "world_path": h["world_path"], "world_sha256": sha(STAGE / h["world_path"]),
                    "pair_path": r["pair_path"], "pair_sha256": sha(STAGE / r["pair_path"]),
                    "consumer_path": consumer_path, "consumer_sha256": sha(STAGE / consumer_path),
                    "frontend_case_sha256": frontend[h['household_id']]['case_hashes'][r['round_index']-1],
                    "route": "/household50-" + h["household_id"] + "/", "human_answers": 0}
            q = quiz(w, pair)
            public_path = "actor_questions/" + pair["case_id"].replace(":", "_") + ".json"
            key_path = "private_fact_keys/" + pair["case_id"].replace(":", "_") + ".json"
            save(dest / public_path, {**task, "questions": [{k:v for k,v in x.items() if k not in ("expected_given_fact","source_field","scored_correct")} for x in q]})
            save(dest / key_path, {**task, "fact_keys": q, "adoption_answer_key_exists": False})
            task.update(actor_question_path=public_path, private_fact_key_path=key_path)
            cases.append(task);household_cases.append(pair["case_id"])
        slots.append({"actor_slot": f"READABILITY-{i:02d}", "anonymous_actor_id": None,
                      "household_id": h["household_id"], "case_order": household_cases,
                      "consent_or_enrollment_obtained": False, "legal_history_at_first_case": [],
                      "budget_cost_observed": None})
    # Two independent duplicate role slots are declared before any answers.
    for original in slots[:2]:
        slots.append({**original, "actor_slot": original["actor_slot"]+"-REPEAT", "independent_actor_required": True})
    save(dest / "PILOT_PLAN.json", {"schema": "eb.input_bound_readability_pilot.v1", "stage": STAGE.name,
         "selected_roles": 8, "unique_cases": len(cases), "planned_actor_slots": len(slots),
         "planned_AB_answers": sum(len(x["case_order"]) for x in slots),
         "household_feature_tags": sorted(covered), "predeclared_mechanisms_covered": sorted(used_mechanisms),
         "selection_inputs": "original50 profiles and predeclared proposal mechanisms only",
         "physical_or_human_outcomes_consulted": False, "slots_are_not_actual_participants": True,
         "fact_questions_after_raw_AB_answer": True,
         "fact_questions_after_all_slot_raw_AB_answers": True,
         "all_pilot_roles_quarantined_from_final_holdout_if_used_for_material_revision": True,
         "powered_role_effect_experiment": False, "human_answers": 0, "cases": cases, "slots": slots})
    save(dest / "PILOT_MATERIALS_REVIEW.json", {"unique_cases": len(cases), "public_questionnaires": len(cases),
         "private_fact_keys": len(cases), "binding_checks": True, "expected_adoption_labels": 0,
         "actual_participants": 0, "actual_answers": 0,
         "planned_AB_answers": sum(len(x["case_order"]) for x in slots)})
    print(read(dest / "PILOT_MATERIALS_REVIEW.json"), flush=True)


if __name__ == "__main__":
    main()
