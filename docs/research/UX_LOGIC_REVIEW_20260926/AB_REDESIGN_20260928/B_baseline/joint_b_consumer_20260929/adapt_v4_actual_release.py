"""Bind E's first actual V4 household readback to the existing consumer sidecar."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from formal_source_consumer import sha
from joint_contract import digest, require
from legacy_case_adapter import normalize_v1
from unified_pipeline import load_cases


CHANNELS = {
    "household_grid_import": "整户购电",
    "ac_coil_electricity": "空调压缩机用电",
    "ac_fan_electricity": "空调风机用电",
    "EV_connection_electricity": "电动车充电用电",
    "hot_water_electricity": "热水设备用电",
    "task_electricity": "任务设备用电",
}


def checked(ref):
    path = Path(ref["path"])
    require(path.is_file() and sha(path) == ref["sha256"],
            "E local evidence file hash mismatch: " + str(path))
    return path


def make(manifest_path, batch_manifest_path, output):
    manifest_path, batch_manifest_path, output = map(Path, (manifest_path, batch_manifest_path, output))
    m = json.loads(manifest_path.read_text())
    require(m["schema"] == "eb-v4-first-household-actual-release-manifest-v1" and
            m["role_id"] == "cityrole-0021" and m["round_count"] == 10,
            "Wrong first household physical release")
    require(m["shared_A"]["scoped_status"] == "meter_pass_repaired_return_gate_warning_retained" and
            m["shared_A"]["time_steps"] == 52560 and
            m["shared_A"]["UNRESOLVED"] == 0,
            "Shared A physical quality gate did not pass")
    require(m["display_scope"].startswith("only SITE_DATA modeled electricity"),
            "Unexpected E display scope")
    local_refs = [m[key] for key in ("source_events", "input_plan", "readback", "site_data",
                                     "B_batch_summary", "A_scoped_repair_readback")]
    for ref in local_refs:
        checked(ref)
    data = json.loads(checked(m["site_data"]).read_text())
    readback = json.loads(checked(m["readback"]).read_text())
    require(data["schema"] == "eb-v4-first-household-site-data-v1" and
            data["source_lock_sha256"] == m["source_lock_sha256"] and
            data["readback_sha256"] == m["readback"]["sha256"] and
            readback["schema"] == "eb-v4-first-house-actual-10-pairs-sql-readback-v1" and
            readback["role_id"] == data["role_id"] == m["role_id"] and
            len(data["rounds"]) == len(readback["pairs"]) == len(m["rounds"]) == 10,
            "E release/readback mismatch")

    batch = json.loads(batch_manifest_path.read_text())
    original = load_cases(batch, batch_manifest_path, [m["role_id"]])
    cases = {case["identity"]["round_index"]:
             normalize_v1(case, sha(batch_manifest_path)) for case in original}
    require(len(cases) == 10 and
            all(c["bindings"]["formal_source_lock_sha256"] == m["source_lock_sha256"] and
                c["bindings"]["annual_sha256"] == m["source_annual_sha256"] and
                c["bindings"]["active_profile_file_sha256"] == m["source_profile_sha256"]
                for c in cases.values()), "Consumer source differs from E release")
    evidence_files = [{"path": str(manifest_path.resolve()), "sha256": sha(manifest_path)}] + local_refs
    entries = []
    for r, pair, site in zip(m["rounds"], readback["pairs"], data["rounds"]):
        n = r["round_index"]
        case = cases[n]
        require(n == pair["round_index"] == site["round_index"] and
                r["proposal_id"] == pair["proposal_id"] == site["proposal_id"] == case["identity"]["case_id"] and
                r["date"] == pair["date"] == site["date"] == case["identity"]["date"] and
                r["source_proposal"]["sha256"] == pair["source_proposal_sha256"] == site["source_proposal_sha256"] and
                site["presentation_order"] == [case["display_assignment"]["left"], case["display_assignment"]["right"]],
                "E round does not match consumer A/B assignment")
        require(r["B_scoped_repair_status"] == "limited_pass" and
                r["B_repair_counts"]["UNRESOLVED"] == 0 and
                r["Severe_Fatal_B"] == [0, 0] and r["time_steps_each"] == 52560 and
                r["A_B_precontrol_max_abs_J"] == 0 and r["external_trace_precontrol_same"] is True and
                pair["A_repair_and_warning"]["scoped_meter_and_repair_gate"] == "limited_pass" and
                pair["B_repair_and_warning"]["scoped_meter_and_repair_gate"] == "limited_pass" and
                pair["precontrol_household_max_abs_J"] == 0 and
                pair["precontrol_external_trace_all_equal"] is True and
                pair["A_meter_component_max_abs_residual_J"] < 1e-6 and
                pair["B_meter_component_max_abs_residual_J"] < 1e-6,
                "E paired physical quality gate did not pass")
        require(pair["A_receipt_sha256"] == m["shared_A"]["receipt"]["sha256"] and
                pair["B_receipt_sha256"] == r["B_receipt"]["sha256"] and
                pair["A_SQL_sha256"] == m["shared_A"]["raw_SQL"]["sha256"] and
                pair["B_SQL_sha256"] == r["B_raw_SQL"]["sha256"],
                "E paired SQL/receipt hashes do not match manifest")
        event = case["vpp"]["events"][0]
        target = event["household_request"]["quantity"]
        vpp = site["VPP"]
        require(vpp["start_abs_min"] == event["start_abs_min"] and
                vpp["end_abs_min"] == event["end_abs_min"] and
                vpp["target_kWh"] == target and
                vpp["qualification"] == "modeled_not_observed_dispatch_or_permanent_saving",
                "VPP event window or target mismatch")
        channels = []
        for kind, label in CHANNELS.items():
            src = site["channels"][kind]
            a, b = src["A"], src["B"]
            require(a["status"] == b["status"] == "limited_modeled_meter_pass" and
                    a["unit"] == b["unit"] == "kWh" and
                    a["meter_boundary"] == b["meter_boundary"] and
                    a["source_output_key"] == b["source_output_key"] and
                    a["start_abs_min"] == b["start_abs_min"] == event["start_abs_min"] and
                    a["end_abs_min"] == b["end_abs_min"] == event["end_abs_min"] and
                    a["result_sha256"] == b["result_sha256"] == m["readback"]["sha256"] and
                    all(isinstance(x["value"], (int, float)) and math.isfinite(x["value"])
                        for x in (a, b)), "Physical channel is not comparable")
            channels.append({"kind": kind, "label": label, "scope": "event", "unit": "kWh",
                             "meter_boundary": a["meter_boundary"], "source_output_key": a["source_output_key"],
                             "start_abs_min": a["start_abs_min"], "end_abs_min": a["end_abs_min"],
                             "A": {"status": "computed", "value": a["value"]},
                             "B": {"status": "computed", "value": b["value"]},
                             "evidence_sha256": m["site_data"]["sha256"],
                             "evidence_status": "limited_modeled_meter_pass"})
        reduction = channels[0]["A"]["value"] - channels[0]["B"]["value"]
        require(abs(reduction - vpp["modeled_reduction_kWh"]) < 1e-8 and
                vpp["modeled_target_met"] is (reduction >= target - 1e-8),
                "VPP modeled reduction does not reconcile with household meter")
        cost = site["channels"]["energy_cost"]
        require(all(cost[side]["status"] == "unknown_not_computed" and
                    cost[side]["value"] is None for side in ("A", "B")),
                "E cost evidence unexpectedly changed")
        shortage = site["service_shortage"]
        require(shortage["A"]["EV_target_unmet_days"] == [] and
                shortage["A"]["EV_trip_unmet_kWh"] == shortage["B"]["EV_trip_unmet_kWh"] == 0 and
                shortage["A"]["hot_water_unmet_draws"] == shortage["B"]["hot_water_unmet_draws"] == [],
                "Unexpected service shortage shape; review before display")
        days = shortage["B"]["EV_target_unmet_days"]
        impacts = [
            {"status": "computed", "description":
             f"模型中本次购电减少 {reduction:.3f} kWh，目标 {target:g} kWh，"
             + ("达到目标。" if vpp["modeled_target_met"] else "未达到目标。")
             + "这不表示后续持续节电。"},
            {"status": "computed", "description":
             "模型中出行用电需求和热水需求没有缺口；费用未计算，室温模型尚未校准。"},
        ]
        physical = {"schema": "eb.joint_b.physical.v2", "status": "partial",
                    "channels": channels, "hold_reason": "费用未知；室温未校准。",
                    "whole_house_net_import": None, "VPP_target_met": vpp["modeled_target_met"]}
        entry = {"case_id": case["identity"]["case_id"],
                 "source_case_sha256": case["audit"]["source_binding"]["original_case_sha256"],
                 "source_bindings": {key: case["bindings"][key] for key in
                     ("profile_sha256", "A_plan_sha256", "B_plan_sha256", "commands_sha256", "vpp_sha256")},
                 "evidence_files": evidence_files + [r["source_proposal"]],
                 "physical": physical, "impacts": impacts,
                 "after_horizon": {"status": "computed_design_proxy",
                    "EV_new_target_shortfall_days": days,
                    "task_material_after_horizon": "unknown"}}
        entries.append(entry)
    sidecar = {"schema": "eb.joint_b.physical_sidecar.v1", "engineering_fixture_only": False,
               "source_release_manifest_sha256": sha(manifest_path),
               "source_site_data_sha256": m["site_data"]["sha256"], "entries": entries}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(sidecar, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    return {"sidecar": str(output), "sha256": sha(output), "entries": len(entries),
            "shortage_rounds": [i + 1 for i, entry in enumerate(entries)
                               if entry["after_horizon"]["EV_new_target_shortfall_days"]]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-manifest", type=Path, required=True)
    parser.add_argument("--batch-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(make(args.release_manifest, args.batch_manifest, args.output),
                     ensure_ascii=False, indent=2))
