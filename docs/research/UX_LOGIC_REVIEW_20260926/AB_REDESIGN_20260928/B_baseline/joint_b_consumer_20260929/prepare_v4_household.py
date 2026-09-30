"""Build one V4 source-bound household with the existing unified consumer."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

from formal_source_consumer import sha
from joint_contract import require
from unified_pipeline import build


HERE = Path(__file__).resolve().parent
LOCK = HERE.parents[1] / "A_proposals/rich_device_revision_20260930/formal_lifestyle_v4_semantic_v1/FORMAL_3000_SOURCE_LOCK_SEMANTIC_V1.json"
PROPOSAL_SCHEMA = "rich-formal-lifestyle-v4-preoutcome-source-lock"


def prepare_many(role_ids: list[str], output: Path, physical_sidecar: Optional[Path] = None) -> dict:
    output = output.resolve()
    role_ids = sorted(set(role_ids))
    require(role_ids and all(role_id.startswith("cityrole-") for role_id in role_ids),
            "At least one V4 household must be selected")
    lock_sha = sha(LOCK)
    lock = json.loads(LOCK.read_text())
    households = lock["households"]
    proposals = lock["proposals"]
    require(len(households) == 300 and len(proposals) == 3000 and
            len({h["role_id"] for h in households}) == 300,
            "V4 source population is incomplete")
    for role_id in role_ids:
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
    sidecar = physical_sidecar.resolve() if physical_sidecar else None
    result = build(manifest_path, role_ids, output / "site", sidecar, sha(sidecar) if sidecar else None)
    require(result["roles"] == len(role_ids) and result["cases"] == 10 * len(role_ids),
            "V4 household build incomplete")
    return {"role_ids": role_ids, "source_lock_sha256": lock_sha,
            "manifest": str(manifest_path), "manifest_sha256": sha(manifest_path),
            "site": result["combined_site"] or str(output / "site" / role_ids[0]), **result}


def prepare(role_id: str, output: Path) -> dict:
    return prepare_many([role_id], output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--physical-sidecar", type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare_many(args.role, args.output, args.physical_sidecar),
                     ensure_ascii=False, indent=2))
