"""Combine ten-round physical sidecars without inventing or replacing results."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from formal_source_consumer import sha
from joint_contract import require


def combine(paths, output):
    paths = [Path(path).resolve() for path in paths]
    require(paths and len(set(paths)) == len(paths), "Distinct household sidecars required")
    entries, refs, roles = [], [], set()
    for path in paths:
        source = json.loads(path.read_text())
        require(source.get("schema") == "eb.joint_b.physical_sidecar.v1" and
                source.get("engineering_fixture_only") is False and
                len(source.get("entries", [])) == 10,
                "A household needs ten real physical entries")
        role_ids = {entry["case_id"].split("/", 1)[0] for entry in source["entries"]}
        rounds = {int(entry["case_id"].rsplit("/", 1)[-1]) for entry in source["entries"]}
        require(len(role_ids) == 1 and rounds == set(range(1, 11)) and
                all(entry["physical"]["status"] in {"partial", "complete"}
                    for entry in source["entries"]),
                "Household sidecar has incomplete identity or results")
        role_id = next(iter(role_ids))
        require(role_id not in roles, "Duplicate household sidecar")
        roles.add(role_id)
        refs.append({"path": str(path), "sha256": sha(path)})
        entries.extend(source["entries"])
    combined = {"schema": "eb.joint_b.physical_sidecar.v1",
                "engineering_fixture_only": False,
                "source_sidecars": refs,
                "entries": sorted(entries, key=lambda entry: entry["case_id"])}
    output = Path(output).resolve()
    require(not output.exists(), "Combined sidecar output must be new")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(combined, ensure_ascii=False, sort_keys=True,
                                 separators=(",", ":")) + "\n")
    return {"path": str(output), "sha256": sha(output),
            "role_ids": sorted(roles), "entries": len(entries)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sidecar", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(combine(args.sidecar, args.output), ensure_ascii=False, indent=2))
