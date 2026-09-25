"""Independent 66-question and actor-card semantic audit of frozen A/B/C."""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

from export_profiles_csv import A_PATH, B_PATH, C_PATH, F_PATH, HERE, LOCKED_SHA256, Q_PATH, read, sha


def area_bin(area):
    if area < 50: return "lt50"
    if area < 90: return "50_89"
    if area < 120: return "90_119"
    if area < 160: return "120_159"
    return "ge160"


def main():
    actual = {"A_family": sha(A_PATH), "B_profile": sha(B_PATH), "C_building": sha(C_PATH),
              "F_shared_whole_area": sha(F_PATH)}
    if actual != LOCKED_SHA256: raise ValueError("frozen input version changed")
    a = {x["role_id"]: x for x in read(A_PATH)["records"]}
    b = {x["role_id"]: x for x in read(B_PATH)["profiles"]}
    c = {x["role_id"]: x for x in read(C_PATH)["records"]}
    f_map = {x["role_id"]: x for x in read(F_PATH)["records"]}
    codebook = read(Q_PATH)
    questions = {x["id"]: x for x in codebook["questions"]}
    if len(questions) != 66: raise ValueError("questionnaire is not 66 questions")
    master_csv = {}
    with (HERE / "households_300.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        master_csv = {x["role_id"]: x for x in csv.DictReader(handle)}
    failures = []
    answer_status = Counter()
    shared_candidates = []
    card_coverage = Counter()
    for rid in sorted(b):
        row = b[rid]
        qa = row["questionnaire_answers"]
        if set(qa) != set(questions): failures.append((rid, "question_id_set"))
        if len(row["members"]) != row["family_size"]: failures.append((rid, "member_count"))
        if any(value is not None for value in row["participant_feedback"].values()): failures.append((rid, "prefilled_feedback"))
        if row["event_specific_presence"] is not None: failures.append((rid, "prefilled_event_presence"))
        for qid, question in questions.items():
            cell = qa[qid]
            required_when = question.get("required_when", {})
            needed = required_when.get("selected_device")
            show = required_when.get("show_when") or question.get("show_when")
            applicable = ((not needed or needed in row["device_ownership"]) and
                          (not show or qa[show["question_id"]]["value"] == show["value"]))
            expected_status = "answered" if applicable else "not_applicable"
            if cell["response_status"] != expected_status: failures.append((rid, f"{qid}_status"))
            if applicable and cell["value"] is None: failures.append((rid, f"{qid}_empty"))
            if not applicable and cell["value"] is not None: failures.append((rid, f"{qid}_skip_has_value"))
            if cell["response_status"] == "answered":
                options = {o["value"] for o in question.get("options", [])}
                values = cell["value"] if isinstance(cell["value"], list) else [cell["value"]]
                if options and not all(v in options for v in values): failures.append((rid, f"{qid}_outside_options"))
            answer_status[(qid, cell["response_status"])] += 1
        member_answer = qa["M_MEMBERS"]["value"]
        if len(member_answer) != len(row["members"]): failures.append((rid, "M_MEMBERS_count"))
        for m, qm in zip(row["members"], member_answer):
            for key in ("age_band", "life_roles", "routine", "comfort", "task", "participation", "needs_priority",
                        "cost_importance", "grid_importance", "control"):
                if m[key] != qm[key]: failures.append((rid, f"M_MEMBERS_{key}"))
        if qa["B02"]["value"] != (str(row["family_size"]) if row["family_size"] <= 5 else "6_plus"):
            failures.append((rid, "B02_size"))
        if qa["B05"]["value"] != row["device_ownership"]: failures.append((rid, "B05_device_order"))
        if qa["X_REGION"]["value"] != row["province"] or qa["X_CITY"]["value"] != row["city"]:
            failures.append((rid, "location"))
        if qa["P_COST"]["value"] != str(row["attitude_design"]["expanded_cost_level"]):
            failures.append((rid, "P_COST"))
        if qa["P_COMFORT"]["value"] != str(row["attitude_design"]["expanded_comfort_level"]):
            failures.append((rid, "P_COMFORT"))
        if qa["A_EB_CONTROL"]["value"] != row["attitude_design"]["control_condition"]:
            failures.append((rid, "A_EB_CONTROL"))
        for device in row["device_ownership"]:
            if qa[f"X_COUNT_{device}"]["value"] is None or qa[f"X_FREQ_{device}"]["value"] is None:
                failures.append((rid, f"{device}_count_freq"))
        whole = a[rid]["dwelling"]["physical_whole_dwelling_building_area_m2"]
        if whole is None:
            if not a[rid]["dwelling"]["housing_form_design"].startswith("shared"):
                failures.append((rid, "unknown_whole_nonshared"))
            item = c[rid]
            full_net = item["source_selected_unit_zone_area_m2"] * item["xy_scale"] ** 2
            candidate_gross = full_net / item["h6_to_net_conditioned_area_ratio"]
            if (rid not in f_map or
                    abs(candidate_gross - f_map[rid]["whole_dwelling_building_area_design_m2"]) > 1e-4 or
                    f_map[rid]["frozen_C_idf_sha256"] != item["idf_sha256"] or
                    qa["X_AREA"]["value"] != f_map[rid]["whole_dwelling_building_area_category_design"] or
                    row["dwelling_interface"]["whole_dwelling_building_area_design_m2"] != f_map[rid]["whole_dwelling_building_area_design_m2"]):
                failures.append((rid, "F_whole_area_binding_or_question"))
            shared_candidates.append({"role_id": rid, "B_X_AREA_raw_code": qa["X_AREA"]["value"],
                "A_allocated_gross_area_m2": a[rid]["dwelling"]["design_total_building_area_m2"],
                "C_source_selected_unit_zone_area_m2": item["source_selected_unit_zone_area_m2"],
                "C_xy_scale": item["xy_scale"], "candidate_whole_net_area_m2": round(full_net, 6),
                "C_household_share_net_to_gross_ratio": item["h6_to_net_conditioned_area_ratio"],
                "candidate_whole_gross_area_m2": round(candidate_gross, 6),
                "candidate_X_AREA_code": area_bin(candidate_gross),
                "candidate_differs_from_B": area_bin(candidate_gross) != qa["X_AREA"]["value"],
                "candidate_status": "ACCEPTED_EXPERIMENTAL_F_VERIFIED_FULL_SOURCE_UNIT_AND_0P95_RATIO"})
        elif qa["X_AREA"]["value"] != area_bin(whole):
            failures.append((rid, "X_AREA_independent_bin"))
        card = master_csv[rid]["actor_card_full"]
        if rid not in card or row["city"] not in card: failures.append((rid, "actor_card_identity"))
        if "尚无真人回答" not in card or "事件当天" not in card: failures.append((rid, "actor_card_evidence_boundary"))
        for m in row["members"]:
            if m["member_id"] not in card or f"{m['age_years_design']}岁" not in card:
                failures.append((rid, "actor_card_member"))
        for device in row["device_ownership"]:
            if row["ordinary_operation_conditions"][device] not in card:
                failures.append((rid, f"actor_card_{device}_condition"))
        card_coverage["full_card_accepted"] += 1
    if failures: raise ValueError(f"semantic audit failed: {failures[:20]} (total {len(failures)})")
    candidate_counts = Counter(x["candidate_X_AREA_code"] for x in shared_candidates)
    report = {"status": "fixed_profile_semantic_pass", "profile_sha256": actual["B_profile"],
        "questionnaire_sha256": sha(Q_PATH), "households": 300, "question_ids": 66,
        "household_question_pairs": 19800, "codebook_value_and_skip_checks": "pass",
        "member_preference_and_identity_checks": "pass", "full_actor_card_coverage": card_coverage["full_card_accepted"],
        "human_feedback_filled": 0, "event_presence_filled": 0,
        "shared_X_AREA_question_expects_whole_dwellings": len(shared_candidates),
        "shared_X_AREA_experimental_whole_design_bins": dict(candidate_counts),
        "shared_X_AREA_binding_failures": sum(x["candidate_differs_from_B"] for x in shared_candidates),
        "F_sidecar_sha256": actual["F_shared_whole_area"],
        "whole_area_population_observation_count": 0,
    }
    (HERE / "SEMANTIC_AUDIT.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    candidate_path = HERE / "shared_area_resolution_27.csv"
    with candidate_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(shared_candidates[0]), lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(shared_candidates)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__": main()
