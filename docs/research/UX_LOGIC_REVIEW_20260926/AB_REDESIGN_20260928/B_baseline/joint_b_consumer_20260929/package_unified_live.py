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


def build(site_dir, output):
    os.umask(0o077)
    site_dir, output = Path(site_dir).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError("Release path must be new and immutable")
    page = (site_dir / "index.html").read_text()
    cases = field_json(page, "joint-cases-data")
    hashes = field_json(page, "source-hashes-data")
    role_ids = {case["identity"]["role_id"] for case in cases}
    if len(role_ids) != 1 or len(cases) != 10 or len(hashes) != 10:
        raise ValueError("One role with ten bound cases required")
    for case, digest in zip(cases, hashes):
        if hashlib.sha256(encoded(case)).hexdigest() != digest:
            raise ValueError("Rendered source case/hash mismatch")
    output.mkdir(mode=0o700, parents=True)
    (output / "site").mkdir(mode=0o700)
    for name in sorted(ASSETS | {"index.html"}):
        shutil.copyfile(site_dir / name, output / "site" / name)
    for name in ("unified_live_server.py", "verify_unified_release.py", "unified-live.service.template", "unified-live-nginx.conf.template"):
        shutil.copyfile(HERE / name, output / name)
    files = {str(path.relative_to(output)): sha(path) for path in sorted(output.rglob("*")) if path.is_file()}
    manifest = {"schema": "eb.joint_b.engineering_release.v1", "mode": "engineering_only",
                "human_collection_release": False, "training_release": False,
                "role_id": next(iter(role_ids)), "cases": 10, "files": files}
    (output / "RELEASE.json").write_bytes(encoded(manifest))
    archive = output.with_suffix(".tar.gz")
    with tarfile.open(archive, "w:gz") as tar:
        for path in sorted(output.rglob("*")):
            if path.is_file():
                tar.add(path, arcname=str(path.relative_to(output)), recursive=False)
    return {"release": str(output), "archive": str(archive), "archive_sha256": sha(archive),
            "manifest_sha256": sha(output / "RELEASE.json"), "role_id": manifest["role_id"], "cases": 10}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--site-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.site_dir, args.output), ensure_ascii=False, indent=2))
