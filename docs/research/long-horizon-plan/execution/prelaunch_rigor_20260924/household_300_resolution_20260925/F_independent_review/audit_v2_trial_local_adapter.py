#!/usr/bin/env python3
"""Read back the isolated v2 role adapter against reviewed files and gate."""

import csv
import hashlib
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRIAL = ROOT / "v2_trial_20260926"
E = TRIAL / "E_collection_release"
F = ROOT / "F_independent_review"
sys.path.insert(0, str(E))
from run_v2_local_preview import V2RoleStudy


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    gate_path = F / "V2_TRIAL_ROLE_TECHNICAL_PREVIEW_GATE.json"
    rows = list(csv.DictReader((E / "public_role_package/devices_300.csv").open(encoding="utf-8-sig")))
    issues = []
    with tempfile.TemporaryDirectory(prefix="eb-f-v2-adapter-") as temp:
        study = V2RoleStudy(temp, casebank_dir=TRIAL / "G_casebank/accepted_public",
                            public_dir=E / "public_role_package", release_gate_path=gate_path)
        if not study.ready or study.load_error is not None or len(study.profiles) != 300 or len(study.cases) != 3000:
            issues.append("study_not_ready_or_wrong_coverage")
        ac_rows = [row for row in rows if row["device"] == "ac"]
        for row in ac_rows:
            role = row["role_id"]
            shown = [device for device in study.profile(role)["devices"] if device["device"] == "ac"]
            if len(shown) != 1:
                issues.append(f"ac_device_row:{role}")
                continue
            device = shown[0]
            if (device["owned_unit_count"] != row["eb_controlled_unit_count"] or
                    device["synthetic_owned_unit_count"] != row["owned_unit_count"] or
                    device["display_unit_count_semantics"] != "D_ACTUAL_EB_CONTROLLABLE_AC_UNITS"):
                issues.append(f"ac_count_projection:{role}")
        gate = json.loads(gate_path.read_text())
        revoked = dict(gate, revoked=True)
        copied = Path(temp) / "revoked_gate.json"
        copied.write_text(json.dumps(revoked))
        study.release_gate_path = copied
        if study.ready:
            issues.append("revocation_not_enforced")
    report = {
        "schema_version": "eb.F_v2_trial_local_adapter_readback.v1",
        "role_adapter_sha256": sha(E / "run_v2_local_preview.py"),
        "technical_gate_sha256": sha(gate_path),
        "public_devices_sha256": sha(E / "public_role_package/devices_300.csv"),
        "roles": 300,
        "cases": 3000,
        "ac_roles_checked": len(ac_rows),
        "special_owned_two_controlled_one_roles": [role for role in ("cityrole-0025", "cityrole-0249")
                                                     if any(row["role_id"] == role and row["owned_unit_count"] == "2"
                                                            and row["eb_controlled_unit_count"] == "1" for row in ac_rows)],
        "revoked_gate_checked": True,
        "human_collection_authorized": False,
        "failure_count": len(issues),
        "failures": issues,
    }
    out = F / "v2_trial_local_adapter_readback.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"ac_roles_checked": len(ac_rows), "failure_count": len(issues), "failures": issues[:5]}, ensure_ascii=False))
    raise SystemExit(bool(issues))


if __name__ == "__main__":
    main()
