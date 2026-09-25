"""Promote F-reviewed G simulation payloads into the E accepted offline shape.

This writes simulation inputs only. It does not issue an F release gate, approve
human consent, collect preferences, or alter G's pending source files.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

from offline_collection_contract import stable_hash, validate_casebank

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
G = ROOT / "G_casebank"
F = ROOT / "F_independent_review"
TARGET = G / "accepted_public"
SOURCE_NAMES = ("casebank_pending.json", "contrast_index_pending.json", "display_payloads_pending.json")
ENGINEERING_BATCH = "eb.engineering.preview.g3000.20260926.v1"
ENGINEERING_NOTICE = "eb.engineering.preview.notice.v1"
ENGINEERING_TEXT = ("本页面仅用于已核验模拟案例的工程预览和功能试填。这里的选择是工程测试记录，"
                    "不构成真人研究同意或正式偏好样本；请勿输入个人信息。")


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def output_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def require_reviewed_sources():
    acceptance = load(F / "G_SIMULATION_ACCEPTANCE.json")
    if (acceptance.get("schema_version") != "eb.F_G_simulation_acceptance.v1" or
            acceptance.get("revoked") is True or
            acceptance.get("status") != "APPROVED_FOR_ACCEPTED_OFFLINE_SIMULATION_PROJECTION_ONLY" or
            acceptance.get("human_collection_approved") is not False or
            acceptance.get("roles") != 300 or acceptance.get("days") != 3000 or
            acceptance.get("meaningful_case_days") != 2277 or
            acceptance.get("equivalent_case_days") != 723):
        raise ValueError("F simulation acceptance is absent, revoked, or incomplete")
    day = load(F / "G_day_payloads_300_readback.json")
    projection = load(F / "G_projection_300_readback.json")
    if (day.get("schema_version") != "eb.F_G_day_payload_readback.v1" or
            projection.get("schema_version") != "eb.F_G_projection_readback.v1" or
            day.get("failure_count") != 0 or projection.get("failure_count") != 0 or
            day.get("case_counts", {}).get("days") != 3000 or
            day.get("case_counts", {}).get("meaningful") != 2277 or
            day.get("case_counts", {}).get("equivalent") != 723 or
            projection.get("counts", {}).get("days") != 3000):
        raise ValueError("F real-day and display readbacks are incomplete")
    if projection.get("F_day_readback_sha256") != file_sha(F / "G_day_payloads_300_readback.json"):
        raise ValueError("F projection review is not bound to F day review")
    expected = day["G_output_sha256"] | projection["G_file_sha256"]
    for name in SOURCE_NAMES + ("day_payload_3000.jsonl", "display_payload_3000.jsonl",
                                "candidate_runtime_300.json"):
        if (expected.get(name) != file_sha(G / name) or
                acceptance["G_source_file_sha256"].get(name) != file_sha(G / name)):
            raise ValueError(f"G source changed after F review: {name}")
    for name, expected_hash in acceptance["F_independent_audit_sha256"].items():
        if file_sha(F / name) != expected_hash:
            raise ValueError(f"F independent review changed after acceptance: {name}")
    if (acceptance.get("D_final_evidence_sha256") != day["D_final_evidence_sha256"] or
            acceptance.get("G_policy_lock_sha256") != file_sha(G / "POLICY_LOCK.json")):
        raise ValueError("F acceptance physical identity differs")
    return day, projection, acceptance


def promote_shape():
    day_review, projection_review, acceptance = require_reviewed_sources()
    pending_bank = load(G / SOURCE_NAMES[0])
    pending_contrast = load(G / SOURCE_NAMES[1])
    display = load(G / SOURCE_NAMES[2])
    if (pending_bank.get("status") != "pending_independent_review" or
            pending_contrast.get("status") != "pending_independent_review" or
            pending_bank.get("study_batch_id") is not None or
            pending_bank.get("consent_version") is not None or
            pending_bank.get("consent_text") is not None or
            len(display) != 3000 or len(pending_contrast.get("decisions", {})) != 3000 or
            pending_bank.get("final_evidence_sha256") != day_review["D_final_evidence_sha256"] or
            pending_contrast.get("final_evidence_sha256") != day_review["D_final_evidence_sha256"]):
        raise ValueError("pending G evidence or consent boundary changed")
    bank = copy.deepcopy(pending_bank)
    contrast = copy.deepcopy(pending_contrast)
    bank.update(status="accepted_offline", study_batch_id=ENGINEERING_BATCH,
                consent_version=ENGINEERING_NOTICE, consent_text=ENGINEERING_TEXT)
    contrast.update(schema_version="eb.accepted_day_contrast.v1", status="independently_accepted")
    for record in bank["records"]:
        for item in record["days"]:
            case_id = item["case_id"]
            semantic = item["semantic_contrast"]
            if semantic.get("source") != "pending_independent_day_evidence":
                raise ValueError(f"unexpected G day evidence state: {case_id}")
            semantic["source"] = "accepted_pre_feedback_day_evidence"
            item["case_status"] = "accepted_simulation"
            item["collectable"] = semantic["status"] == "meaningful"
            item["pair_status"] = "contrast_valid" if item["collectable"] else "no_effect_or_identical"
            decision = contrast["decisions"][case_id]
            if decision["semantic_contrast"]["evidence_hash"] != semantic["evidence_hash"]:
                raise ValueError(f"F-reviewed semantic evidence differs: {case_id}")
            decision["semantic_contrast"] = copy.deepcopy(semantic)
            for slot in ("A", "B"):
                shown = display[case_id]["plans"][slot]
                if (stable_hash(shown) != item["plans"][slot]["display_payload_hash"] or
                        stable_hash(shown["metrics"]) != item["plans"][slot]["metrics_hash"]):
                    raise ValueError(f"F-reviewed displayed plan changed: {case_id}.{slot}")
    bank["semantic_contrast_evidence_sha256"] = stable_hash(contrast)
    counts = validate_casebank(bank, accepted_contrast_index=contrast)
    if counts != {"roles": 300, "days": 3000, "collectable_days": 2277}:
        raise ValueError(f"unexpected accepted case counts: {counts}")
    if (bank["meter_version_sha256"] != acceptance["meter_identity_sha256"] or
            bank["public_role_manifest_sha256"] != acceptance["public_role_manifest_sha256"]):
        raise ValueError("F accepted meter or role package identity differs")
    return bank, contrast, display, day_review, projection_review, counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--promote", action="store_true", help="Write the reviewed three-file simulation projection")
    args = parser.parse_args()
    bank, contrast, display, day_review, projection_review, counts = promote_shape()
    outputs = {"casebank.json": bank, "accepted_contrasts.json": contrast,
               "display_payloads.json": display}
    if args.promote:
        TARGET.mkdir(exist_ok=True)
        for name, value in outputs.items():
            target = TARGET / name
            if target.exists():
                raise FileExistsError(f"accepted file already exists; refusing overwrite: {target}")
            temporary = TARGET / f".{name}.tmp"
            temporary.write_bytes(output_bytes(value))
            temporary.replace(target)
    print(json.dumps({"promotion_written": args.promote, "counts": counts,
                      "F_day_readback_sha256": file_sha(F / "G_day_payloads_300_readback.json"),
                      "F_projection_readback_sha256": file_sha(F / "G_projection_300_readback.json"),
                      "G_pending_sha256": {name: file_sha(G / name) for name in SOURCE_NAMES},
                      "accepted_sha256": {name: file_sha(TARGET / name) for name in outputs} if args.promote else
                      {name: hashlib.sha256(output_bytes(value)).hexdigest() for name, value in outputs.items()}},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
