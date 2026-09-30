"""Verify every byte of one private engineering release."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from unified_live_server import ASSETS, encoded, field_json


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(directory, expected_manifest_sha):
    root = Path(directory).resolve()
    manifest_path = root / "RELEASE.json"
    if sha(manifest_path) != expected_manifest_sha:
        raise ValueError("Release manifest SHA mismatch")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema") != "eb.joint_b.engineering_release.v1" or manifest.get("mode") not in {"engineering_only", "experience_only"} or manifest.get("human_collection_release") is not False or manifest.get("training_release") is not False:
        raise ValueError("Not an engineering release")
    actual = {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()}
    expected = set(manifest["files"]) | {"RELEASE.json"}
    if actual != expected:
        raise ValueError("Release file set differs")
    for name, digest in manifest["files"].items():
        if sha(root / name) != digest:
            raise ValueError("Release file SHA mismatch: " + name)
    if {"site/" + name for name in ASSETS | {"index.html"}} - actual:
        raise ValueError("Page assets incomplete")
    page = (root / "site/index.html").read_text()
    cases, hashes = field_json(page, "joint-cases-data"), field_json(page, "source-hashes-data")
    if len(cases) != len(hashes) or len(cases) != manifest["cases"]:
        raise ValueError("Case count mismatch")
    role_ids = manifest.get("role_ids") or [manifest["role_id"]]
    if sorted(role_ids) != sorted({case["identity"]["role_id"] for case in cases}) or len(cases) != 10 * len(role_ids):
        raise ValueError("Release household count differs")
    if len({case["identity"]["case_id"] for case in cases}) != len(cases):
        raise ValueError("Duplicate case in release")
    for role_id in role_ids:
        if {case["identity"]["round_index"] for case in cases
                if case["identity"]["role_id"] == role_id} != set(range(1, 11)):
            raise ValueError("Household release rounds incomplete")
    for case, digest in zip(cases, hashes):
        if case["identity"]["role_id"] not in role_ids or hashlib.sha256(encoded(case)).hexdigest() != digest:
            raise ValueError("Case identity or hash mismatch")
        if manifest["mode"] == "experience_only" and (case.get("physical", {}).get("status") not in {"partial", "complete"}
                                                       or not case.get("audit", {}).get("physical_binding")):
            raise ValueError("Unbound or incomplete experience case")
    return {"verified": True, "role_ids": role_ids, "cases": len(cases), "files": len(actual)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--sha256", required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.directory, args.sha256), ensure_ascii=False))
