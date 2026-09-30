"""Create an immutable private engineering release from one built role page."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile

from unified_live_server import ASSETS, encoded, field_json


HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build(site_dir, output, experience_only=False, previous_release=None):
    os.umask(0o077)
    site_dir, output = Path(site_dir).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError("Release path must be new and immutable")
    page = (site_dir / "index.html").read_text()
    cases = field_json(page, "joint-cases-data")
    hashes = field_json(page, "source-hashes-data")
    role_ids = sorted({case["identity"]["role_id"] for case in cases})
    if not role_ids or len(cases) != 10 * len(role_ids) or len(hashes) != len(cases):
        raise ValueError("Ten bound cases per household required")
    for role_id in role_ids:
        rounds = [case["identity"]["round_index"] for case in cases
                  if case["identity"]["role_id"] == role_id]
        if len(rounds) != 10 or set(rounds) != set(range(1, 11)):
            raise ValueError("Each household needs exactly ten rounds")
    for case, digest in zip(cases, hashes):
        if hashlib.sha256(encoded(case)).hexdigest() != digest:
            raise ValueError("Rendered source case/hash mismatch")
        if experience_only and (case.get("physical", {}).get("status") not in {"partial", "complete"}
                                or not case.get("audit", {}).get("physical_binding")):
            raise ValueError("Experience release requires bound actual results for every round")
    if len(role_ids) > 1 and previous_release is None:
        raise ValueError("Cumulative release must name the previous release")
    if previous_release is not None:
        previous = Path(previous_release).resolve()
        old_page = (previous / "site/index.html").read_text()
        old_cases = field_json(old_page, "joint-cases-data")
        stable = lambda case: {key: value for key, value in case.items()
                               if key not in {"audit", "bindings"}}
        old = {case["identity"]["case_id"]: stable(case) for case in old_cases}
        new = {case["identity"]["case_id"]: stable(case) for case in cases}
        if not old or any(new.get(case_id) != value for case_id, value in old.items()):
            raise ValueError("Cumulative release dropped or changed an existing household's source/results")
    output.mkdir(mode=0o700, parents=True)
    (output / "site").mkdir(mode=0o700)
    for name in sorted(ASSETS | {"index.html"}):
        shutil.copyfile(site_dir / name, output / "site" / name)
    for name in ("unified_live_server.py", "verify_unified_release.py", "unified-live.service.template", "unified-live-nginx.conf.template"):
        shutil.copyfile(HERE / name, output / name)
    files = {str(path.relative_to(output)): sha(path) for path in sorted(output.rglob("*")) if path.is_file()}
    manifest = {"schema": "eb.joint_b.engineering_release.v1",
                "mode": "experience_only" if experience_only else "engineering_only",
                "human_collection_release": False, "training_release": False,
                "role_id": role_ids[0] if len(role_ids) == 1 else None,
                "role_ids": role_ids, "cases": len(cases), "files": files}
    (output / "RELEASE.json").write_bytes(encoded(manifest))
    archive = output.with_suffix(".tar.gz")
    with tarfile.open(archive, "w:gz") as tar:
        for path in sorted(output.rglob("*")):
            if path.is_file():
                tar.add(path, arcname=str(path.relative_to(output)), recursive=False)
    return {"release": str(output), "archive": str(archive), "archive_sha256": sha(archive),
            "manifest_sha256": sha(output / "RELEASE.json"), "role_ids": role_ids,
            "cases": len(cases)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--site-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--experience-only", action="store_true")
    parser.add_argument("--previous-release", type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.site_dir, args.output, args.experience_only,
                           args.previous_release), ensure_ascii=False, indent=2))
