"""Build one V4 source-bound household with the existing unified consumer."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from formal_source_consumer import sha
from joint_contract import require
from unified_pipeline import build


HERE = Path(__file__).resolve().parent
LOCK = HERE.parents[1] / "A_proposals/rich_device_revision_20260930/formal_lifestyle_v4_semantic_v1/FORMAL_3000_SOURCE_LOCK_SEMANTIC_V1.json"
PROPOSAL_SCHEMA = "rich-formal-lifestyle-v4-preoutcome-source-lock"


def prepare(role_id: str, output: Path) -> dict:
    output = output.resolve()
    lock_sha = sha(LOCK)
    lock = json.loads(LOCK.read_text())
    households = lock["households"]
    proposals = lock["proposals"]
    require(len(households) == 300 and len(proposals) == 3000 and
            len({h["role_id"] for h in households}) == 300,
            "V4 source population is incomplete")
    selected = [p for p in proposals if p["role_id"] == role_id]
    require(len(selected) == 10 and
            {p["round_index"] for p in selected} == set(range(1, 11)) and
            all(p["schema"] == PROPOSAL_SCHEMA for p in selected),
            "Household does not have ten bound V4 rounds")
    source = next((h for h in households if h["role_id"] == role_id), None)
    require(source is not None, "Household not in V4 source")
    for key in ("annual", "canonical"):
        ref = source[key]
        require(sha(Path(ref["path"])) == ref["sha256"],
                "Selected source file changed: " + key)
    require(sha(LOCK) == lock_sha, "V4 source lock changed during build")
    rows = [{"role_id": h["role_id"], "annual": h["annual"],
             "profile": h["canonical"], "ordinary_A_eligible": True,
             "selected_B_count": 10} for h in households]
    output.mkdir(parents=True, exist_ok=True)
    snapshot = {"schema": "eb.formal_source_snapshot.v2",
                "source_lock": {"path": str(LOCK), "sha256": lock_sha},
                "roles": rows, "household_count": 300,
                "eligible_A_count": 300, "selected_B_count": 3000,
                "formal_split": None}
    # The existing pipeline consumes this snapshot directly; no second renderer is introduced.
    snapshot_path = output / "source_snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    manifest = {"schema": "eb.joint_b.batch_manifest.v1",
                "adapter": "formal_source_lock",
                "source_version": "formal_lifestyle_v4_semantic_v1",
                "source_snapshot": {"path": str(snapshot_path), "sha256": sha(snapshot_path)},
                "expected": {"source_households": 300, "selected_B_slots": 3000},
                "proposal_schemas": [PROPOSAL_SCHEMA]}
    manifest_path = output / "batch_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    result = build(manifest_path, [role_id], output / "site")
    require(result["roles"] == 1 and result["cases"] == 10, "V4 household build incomplete")
    return {"role_id": role_id, "source_lock_sha256": lock_sha,
            "manifest": str(manifest_path), "manifest_sha256": sha(manifest_path),
            "site": str(output / "site" / role_id), **result}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.role, args.output), ensure_ascii=False, indent=2))
