#!/usr/bin/env python3
"""Export F-reviewed G case metadata without paths, geometry or human answers."""
from __future__ import annotations

from collections import Counter
import csv
from hashlib import sha256
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = HERE / "public_case_tables"
F_ACCEPT = ROOT / "F_independent_review" / "G_SIMULATION_ACCEPTANCE.json"


def sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def load(path: Path):
    return json.loads(path.read_text())


def family_zh(value: str) -> str:
    return {"no_contrast": "当日无方案动作差异",
            "ac_setpoint": "空调设定点调整",
            "device_time_shift": "设备运行移时",
            "ac_plus_device_shift": "空调设定点与设备移时"}[value]


def contrast_zh(day: dict) -> str:
    value = day["semantic_contrast"]
    if value["status"] == "meaningful":
        return family_zh(day["plan_family_id"])
    return {"common_initialization_day": "首日共同背景，无方案差异",
            "no_legal_today_plan_change": "当日无合法方案改变"}.get(
                value["reason"], "当日方案动作相同")


def fmt(value: float | int) -> str:
    return f"{value:.6f}"


def main() -> None:
    gate = load(F_ACCEPT)
    if (gate["status"] != "APPROVED_FOR_ACCEPTED_OFFLINE_SIMULATION_PROJECTION_ONLY" or
        gate["human_collection_approved"] is not False or
        gate["roles"] != 300 or gate["days"] != 3000):
        raise ValueError("F G simulation acceptance absent or wrong scope")
    for filename, expected in gate["G_source_file_sha256"].items():
        if sha(HERE/filename) != expected:
            raise ValueError(f"F-reviewed G source changed: {filename}")
    bank = load(HERE/"casebank_pending.json")
    projection = load(HERE/"display_payloads_pending.json")
    if (bank["status"] != "pending_independent_review" or
        bank["participant_feedback"] is not None or
        len(bank["records"]) != 300 or len(projection) != 3000):
        raise ValueError("frozen casebank/feedback/coverage differs")
    columns = ["case_id", "role_id", "day_index", "simulated_calendar_day",
               "city", "province", "plan_family_id", "plan_family_zh",
               "action_contrast_status", "contrast_basis", "difference_reason_zh",
               "baseline_owned_device_kwh", "candidate_owned_device_kwh",
               "baseline_selected_ac_proxy_kwh", "candidate_selected_ac_proxy_kwh",
               "baseline_attributable_kwh", "candidate_attributable_kwh",
               "candidate_minus_baseline_attributable_kwh",
               "baseline_all_owned_room_24h_mean_c", "candidate_all_owned_room_24h_mean_c",
               "simulated_outdoor_min_c", "simulated_outdoor_max_c",
               "weather_kind", "metric_scope", "temperature_scope", "feedback_rows"]
    rows = []
    counts = Counter()
    for record in bank["records"]:
        role = record["role_id"]
        for day in record["days"]:
            cid = day["case_id"]
            shown = projection[cid]
            a = shown["plans"]["A"]
            b = shown["plans"]["B"]
            ma, mb = a["metrics"], b["metrics"]
            for slot, value in (("A", a), ("B", b)):
                if (value["controlled_device_kwh"] != value["metrics"]["attributable_kwh"] or
                    value["task_completion"] != "未建模任务完成；仅模拟设备日程和代理电量"):
                    raise ValueError(f"{cid}.{slot}: unreviewed metric or task claim")
            if day["semantic_contrast"]["source"] != "pending_independent_day_evidence":
                raise ValueError(f"{cid}: unexpected contrast source")
            # Frozen G display has city/province and actual CSWD typical-year
            # extrema. It is reviewed separately by F and has no local path.
            rows.append({"case_id": cid, "role_id": role,
                         "day_index": str(day["day_index"]),
                         "simulated_calendar_day": f"07-{13+day['day_index']:02d}",
                         "city": "", "province": "",
                         "plan_family_id": day["plan_family_id"],
                         "plan_family_zh": family_zh(day["plan_family_id"]),
                         "action_contrast_status": day["semantic_contrast"]["status"],
                         "contrast_basis": day["semantic_contrast"].get("basis") or "",
                         "difference_reason_zh": contrast_zh(day),
                         "baseline_owned_device_kwh": fmt(sum(ma["device_kwh"].values())),
                         "candidate_owned_device_kwh": fmt(sum(mb["device_kwh"].values())),
                         "baseline_selected_ac_proxy_kwh": fmt(ma["ac_proxy_kwh"]),
                         "candidate_selected_ac_proxy_kwh": fmt(mb["ac_proxy_kwh"]),
                         "baseline_attributable_kwh": fmt(ma["attributable_kwh"]),
                         "candidate_attributable_kwh": fmt(mb["attributable_kwh"]),
                         "candidate_minus_baseline_attributable_kwh": fmt(
                             round(mb["attributable_kwh"]-ma["attributable_kwh"], 6)),
                         "baseline_all_owned_room_24h_mean_c": f"{a['indoor_temperature_c']:.2f}",
                         "candidate_all_owned_room_24h_mean_c": f"{b['indoor_temperature_c']:.2f}",
                         "simulated_outdoor_min_c": "", "simulated_outdoor_max_c": "",
                         "weather_kind": "CSWD typical-year simulated scenario",
                         "metric_scope": "owned devices plus selected AC COP3 proxy; not full household bill",
                         "temperature_scope": "all owned rooms × all 24 hours equally weighted; not comfort score",
                         "feedback_rows": "0"})
            counts[day["plan_family_id"]] += 1
    raw_by_id = {x["case_id"]: x for x in (json.loads(line) for line in
                 (HERE/"display_payload_3000.jsonl").read_text().splitlines())}
    if len(raw_by_id) != 3000:
        raise ValueError("frozen G raw display coverage differs")
    for row in rows:
        raw = raw_by_id[row["case_id"]]
        row["city"] = raw["city"]
        row["province"] = raw["province"]
        row["simulated_outdoor_min_c"] = f"{raw['weather']['min_c']:.2f}"
        row["simulated_outdoor_max_c"] = f"{raw['weather']['max_c']:.2f}"
    if (len(rows) != 3000 or len({x["case_id"] for x in rows}) != 3000 or
        counts != Counter({"no_contrast": 723, "ac_plus_device_shift": 1081,
                           "device_time_shift": 852, "ac_setpoint": 344})):
        raise ValueError("public case table coverage or family counts differ")
    OUT.mkdir(exist_ok=True)
    path = OUT/"cases_3000.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    body = path.read_text(encoding="utf-8-sig")
    if any(x in body for x in ("/Users/", "/private/", "file://", "R3-", "EB_PRIVATE_")):
        raise ValueError("local path or source geometry leaked to public table")
    manifest = {"schema_version": "eb.G_public_case_metadata.v1",
                "status": "public_candidate_metadata_pending_F_table_review",
                "table": "cases_3000.csv", "table_sha256": sha(path),
                "rows": len(rows), "roles": 300,
                "family_counts": dict(counts),
                "meaningful_day_count": 2277, "equivalent_day_count": 723,
                "F_simulation_acceptance_sha256": sha(F_ACCEPT),
                "G_source_sha256": gate["G_source_file_sha256"],
                "source_public_role_table": "E_collection_release/public_role_package/households_300.csv",
                "metric_boundary": "experimental owned-device electricity plus selected-AC COP3 proxy; no tariff, whole-home bill, task success, measured comfort or human feedback",
                "temperature_boundary": "24-hour mean of all owned rooms with each room and hour equally weighted; includes rooms without selected AC",
                "participant_feedback_rows": 0,
                "human_collection_approved": False,
                "export_source_sha256": sha(Path(__file__))}
    (OUT/"MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps({"rows": len(rows), "roles": 300,
                      "family_counts": dict(counts),
                      "table_sha256": manifest["table_sha256"],
                      "manifest_sha256": sha(OUT/"MANIFEST.json")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
