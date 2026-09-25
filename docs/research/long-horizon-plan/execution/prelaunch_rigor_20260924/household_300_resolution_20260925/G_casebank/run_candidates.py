#!/usr/bin/env python3
"""Run fixed G offline candidates against the frozen D v3 physical baseline."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
D=ROOT/"D_integration"
F=ROOT/"F_independent_review"
sys.path.insert(0,str(D))
import run_behavior  # noqa: E402
from run_behavior import run_one  # noqa: E402
from build_runtime_inputs import sha  # noqa: E402

G_MANIFEST=HERE/"candidate_input_manifest_300.json"
D_MANIFEST=D/"behavior_input_manifest.json"
D_RUNTIME=D/"runtime_300.json"
D_FINAL=D/"final_evidence_chain.json"
G_LOCK=HERE/"POLICY_LOCK.json"
F_GATE=F/"G_OFFLINE_PRODUCTION_GATE.json"
OUT=HERE/"runtime"
METER_VERSION="eb.D.single_household_AC_meter.v3"


def frozen_sources() -> tuple[dict,dict,dict,dict]:
    gate=json.loads(F_GATE.read_text())
    expected={"D_manifest_sha256":sha(D_MANIFEST),
              "D_runtime_sha256":sha(D_RUNTIME),
              "D_final_evidence_chain_sha256":sha(D_FINAL),
              "F_final_chain_readback_sha256":sha(F/"final_chain_readback.json"),
              "G_policy_lock_sha256":sha(G_LOCK),
              "G_static_preflight_sha256":sha(HERE/"static_preflight_300.json"),
              "G_generator_source_sha256":sha(HERE/"build_candidates.py")}
    if (gate["status"]!="APPROVED_FOR_DETERMINISTIC_OFFLINE_CANDIDATE_RUNS_ONLY" or
        gate["failure_count"]!=0 or
        any(gate.get(key)!=value for key,value in expected.items())):
        raise ValueError("F G offline production gate is not current for these exact bytes")
    manifest=json.loads(G_MANIFEST.read_text())
    d_manifest=json.loads(D_MANIFEST.read_text())
    d_runtime=json.loads(D_RUNTIME.read_text())
    if (manifest["n"]!=300 or manifest["D_manifest_sha256"]!=sha(D_MANIFEST) or
        manifest["D_runtime_sha256"]!=sha(D_RUNTIME) or
        manifest["D_final_evidence_sha256"]!=sha(D_FINAL) or
        manifest["preresult_policy_lock_sha256"]!=sha(G_LOCK) or
        manifest["ac_meter_contract_version"]!=METER_VERSION or
        d_manifest["ac_meter_contract_version"]!=METER_VERSION or
        d_runtime["input_manifest_sha256"]!=sha(D_MANIFEST) or not d_runtime["all_passed"]):
        raise ValueError("G candidate manifest no longer binds frozen D/G sources")
    return manifest,d_manifest,d_runtime,gate


def one(candidate: dict, d_record: dict, baseline: dict) -> dict:
    role=candidate["role_id"]
    if (candidate["A_baseline_idf_sha256"]!=d_record["idf_sha256"] or
        candidate["weather_epw_sha256"]!=d_record["weather_epw_sha256"] or
        sha(Path(candidate["B_candidate_idf_path"]))!=candidate["B_candidate_idf_sha256"]):
        raise ValueError(f"G candidate/D input hash mismatch: {role}")
    if candidate["candidate_reuses_identical_baseline_IDF"]:
        if (candidate["B_candidate_idf_sha256"]!=d_record["idf_sha256"] or
            candidate["days_with_actual_plan_contrast"]!=0):
            raise ValueError(f"unchanged G candidate has contrast: {role}")
        result=deepcopy(baseline)
        folder=D/"runtime"/role
        provenance="reused_identical_D_baseline_SQL_and_full_cache_signature"
        execution_role=role
    else:
        execution_role=role+"__G_candidate"
        run_record=deepcopy(d_record)
        run_record.update({"role_id":execution_role,
                           "idf_path":candidate["B_candidate_idf_path"],
                           "idf_sha256":candidate["B_candidate_idf_sha256"]})
        result=run_one(run_record,reuse=True)
        folder=OUT/execution_role
        provenance="actual_new_G_candidate_EnergyPlus_run"
    if result["status"]!="runtime_and_accounting_passed" or \
       result["input_idf_sha256"]!=candidate["B_candidate_idf_sha256"]:
        raise ValueError(f"G candidate run failed: {role} {result}")
    for path in (folder/"eplusout.sql",folder/"eplusout.end",folder/"cache_signature.json"):
        if not path.is_file():raise ValueError(f"candidate runtime file missing: {role} {path}")
    result=deepcopy(result)
    result["role_id"]=role
    result["execution_role_id"]=execution_role
    result["execution_provenance"]=provenance
    result["sql_path"]=str(folder/"eplusout.sql")
    result["sql_sha256"]=sha(folder/"eplusout.sql")
    result["end_sha256"]=sha(folder/"eplusout.end")
    return result


def main() -> None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--roles",nargs="*",help="selected smoke roles; omit for all 300")
    ap.add_argument("--workers",type=int,default=6)
    args=ap.parse_args()
    manifest,d_manifest,d_runtime,gate=frozen_sources()
    candidates={r["role_id"]:r for r in manifest["records"]}
    d_records={r["role_id"]:r for r in d_manifest["records"]}
    baseline={r["role_id"]:r for r in d_runtime["records"]}
    wanted=args.roles or sorted(candidates)
    if len(wanted)!=len(set(wanted)) or any(role not in candidates for role in wanted):
        raise ValueError("requested candidate roles missing or duplicated")
    OUT.mkdir(exist_ok=True)
    run_behavior.RUNS=OUT
    results=[]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs={pool.submit(one,candidates[role],d_records[role],baseline[role]):role
              for role in wanted}
        for future in as_completed(jobs):
            role=jobs[future]
            try:result=future.result()
            except Exception as exc:result={"role_id":role,"status":"candidate_exception","error":repr(exc)}
            results.append(result)
            if len(results)%25==0 or result["status"]!="runtime_and_accounting_passed":
                print(f"{len(results)}/{len(wanted)} {role} {result['status']}",flush=True)
    results.sort(key=lambda r:r["role_id"])
    counts=dict(Counter(r["status"] for r in results))
    report={"schema_version":"eb.G_candidate_energyplus_runtime.v1",
            "status":"candidate_runtime_passed_pending_independent_day_review" if
                counts=={"runtime_and_accounting_passed":len(wanted)} else "candidate_runtime_failed",
            "all_passed":counts=={"runtime_and_accounting_passed":len(wanted)},
            "n":len(results),"status_counts":counts,
            "candidate_manifest_sha256":sha(G_MANIFEST),
            "D_manifest_sha256":sha(D_MANIFEST),
            "D_runtime_sha256":sha(D_RUNTIME),
            "D_final_evidence_sha256":sha(D_FINAL),
            "G_policy_lock_sha256":sha(G_LOCK),
            "F_offline_production_gate_sha256":sha(F_GATE),
            "runner_source_sha256":sha(Path(__file__)),
            "underlying_D_reader_source_sha256":sha(D/"run_behavior.py"),
            "execution_provenance_counts":dict(Counter(r.get("execution_provenance") for r in results)),
            "records":results}
    output=HERE/("candidate_runtime_300.json" if len(results)==300 else "candidate_runtime_sample.json")
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"n":len(results),"status_counts":counts,
                      "execution_provenance_counts":report["execution_provenance_counts"],
                      "report":str(output)},ensure_ascii=False),flush=True)


if __name__=="__main__":
    main()
