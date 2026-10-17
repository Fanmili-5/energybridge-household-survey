"""Publish repair status only from a finalized and hash-checked V18 delivery."""
import hashlib
import json
from pathlib import Path
import shutil

R = Path(__file__).resolve().parents[1]
H = R.parent
N = H / "profile_conditioned_production_20261008_v18"


def read(p):
    return json.loads(p.read_text())


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def save(p, value):
    p.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def main():
    delivery, review = read(N / "DELIVERY.json"), read(N / "DELIVERY_REVIEW.json")
    for name, expected in delivery["files"].items():
        assert sha(N / name) == expected, name
    assert review["households"] == 1000 and review["pairs"] == 10000
    assert review["original50_reference_pairs_checked"] == 500
    assert review["human_answers"] == 0 and review["other950_EP_executed"] is False
    assert not read(N / "INPUT_AUDIT.json")["failures"]
    pilot = read(R / "pilot_materials_v18/PILOT_MATERIALS_REVIEW.json")
    assert pilot["actual_answers"] == 0 and pilot["expected_adoption_labels"] == 0
    board_path = R / "EXECUTION_BOARD.json"
    archive = R / "EXECUTION_BOARD_before_v18.json"
    if not archive.exists():
        shutil.copyfile(board_path, archive)
    board = read(board_path)
    board.update(production=N.name, baseline_production="roleplay_mixed_static1000_20261007_v17",
                 baseline_kept=True, finalized_delivery="../"+N.name+"/DELIVERY.json",
                 finalized_delivery_sha256=sha(N / "DELIVERY.json"),
                 current_repair_candidate="../CURRENT_REPAIR_CANDIDATE.json",
                 whole_program_scientific_completion=False,
                 scoped_reference_implementation_complete=True,
                 actual_human_answers=0)
    statuses = {
        "G1": (True, "source_decoder_aggregate_extraction_and1000_world_reference_activity_verified", ["WORLD_BUILD_REVIEW.json", "SOURCE_EMPLOYMENT_AGGREGATES.json", "INPUT_AUDIT.json"], "CHFS source/skip semantics repaired; aggregate skip data does not identify an individual synthetic member's missing cause"),
        "G2": (True, "all1000_conditioned_weekly_calendars_and_resource_windows_verified", ["WORLD_BUILD_REVIEW.json", "INPUT_AUDIT.json", "STATIC_REVIEW.json"], "coherent explicitly designed schedules; no Chinese joint diary distribution calibration"),
        "G3": (True, "service_habit_negotiability_unknown_tradeoff_and_single_active_clock_contract_verified", ["FIELD_EVIDENCE.md", "INPUT_AUDIT.json", "MATERIALS_REVIEW.json"], "given service bounds, chain delivery and EV driver/handling semantics; not measured individual preferences"),
        "G4": (True, "10000_input_only_frozen_A_mixed_B_pairs_and_no_human_labels_verified", ["STATIC_REVIEW.json", "SELECTION1000.json"], "six designed mechanisms and applicability reasons; human interpretation remains to be tested"),
        "G5": (True, "20000_IDF_bindings_original50_500pairs_and200_sensitivity_pairs_verified_with_limits", ["IDF_BINDINGS20000.json", "READBACK_all_REVIEW.json", "READBACK_sensitivity_REVIEW.json", "WEATHER_SOLVER_REVIEW.json", "STRICT_WEATHER_REFERENCE_COMPARISON.json"], "original50 reference consistency and sensitivity audit; inlet sensitivity material, AHRI/wetbulb warnings retained, strict wetbulb point agreement failed, no field calibration or other950 outcomes"),
        "G6": (False, "original_frontend_1000_cards10000_tasks500_renders_and_bound_pilot_materials_ready_human_evidence_pending", ["ACTOR_BINDINGS.json", "CONSUMER_BINDINGS.json", "MATERIALS_REVIEW.json", "HUMAN_PILOT_PROTOCOL.md"], "readability instruments and original binary questions ready; actual human readability, role effect and benchmark labels absent"),
    }
    for g in board["required_repairs"]:
        complete, status, files, limits = statuses[g["id"]]
        g.update(complete=complete, implementation_complete=True,
                 scoped_verification_complete=True, status=status,
                 completion_scope="source-aware reference construction/development audit, not empirical validation",
                 evidence=["../"+N.name+"/"+f for f in files], remaining_evidence_or_limits=limits)
        if g["id"] == "G6":
            g["scoped_verification_complete"] = False
            g["engineering_verification_complete"] = True
            g["pilot_materials"] = "pilot_materials_v18/PILOT_PLAN.json"
    work_status = {
        "E01": "source_decoding_and_admitted_frame_aggregate_extraction_complete",
        "E02": "1000_new_common_worlds_complete_reference_assumptions_explicit",
        "E03": "10000_frozen_A_continuous_episode_and_operations_complete",
        "E04": "10000_mixed_B_input_integrity_and_mechanism_coverage_complete",
        "E05": "20000_IDF_bindings_original50_runs_readback_and_sensitivity_complete_with_declared_limits",
        "E06": "1000_actor_cards10000_tasks_original50_frontend500_cases_and_export_bindings_complete",
        "E07": "bound_readability_materials_and_blank_records_complete_actual_human_evidence_pending",
        "S01": "authoritative_source_aggregates_used_joint_diary_data_unavailable_reference_claim_bounded",
    }
    for p in board["work_packages"]:
        p["status"] = work_status[p["id"]]
        p["implementation_stage"] = N.name
    board["completion_policy"]["complete_means_scoped_reference_repair_only"] = True
    board["completion_policy"]["all_six_complete_or_empirical_benchmark_claim"] = False
    board["completion_policy"]["human_evidence_cannot_be_replaced_by_engineering_or_synthetic_answers"] = True
    board["execution_scope"].update(EP_now_executed=True, EP_development_households="original selected50 only",
                                    original50_pairs=500, sensitivity_pairs=200,
                                    other950_EP="held; no outcomes substituted")
    board["reference_diagnostics"] = {k:review[k] for k in ("proposal_mechanisms", "service_goal_and_trip_counts", "known_warnings_retained_and_diagnosed", "strict_weather_point_reference_agreement", "sensitivity_maximum_AB_energy_difference_kWh")}
    save(board_path, board)
    pointer = {"stage": N.name, "delivery_path": N.name+"/DELIVERY.json",
               "delivery_sha256": sha(N/"DELIVERY.json"), "package_receipt": N.name+"/PACKAGE_RECEIPT.json",
               "execution_board": "repair_execution_20261008_v1/EXECUTION_BOARD.json",
               "baseline_static_pointer_unchanged": "CURRENT_STATIC_INPUTS.json",
               "baseline_live50_pointer_unchanged": "CURRENT_TEST50.json",
               "preview_url_when_SSH_tunnel_active": "http://127.0.0.1:18779/household50",
               "preview_mode": "original binary frontend; server read-only, existing local download mode",
               "households": 1000, "pairs": 10000, "IDF_inputs": 20000,
               "reference_EP_households": 50, "reference_EP_pairs": 500,
               "other950_EP_executed": False, "human_answers": 0,
               "collection_release": False, "training_release": False,
               "scientific_benchmark_validity_complete": False}
    save(H/"CURRENT_REPAIR_CANDIDATE.json", pointer)
    print(json.dumps({"stage": N.name, "G1_to_G5_scoped_reference_repairs_verified": True,
                      "G6_materials_ready": True, "human_evidence": "pending",
                      "original50_EP_pairs": 500, "other950_EP": "held"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
