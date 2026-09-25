"""Make a path-free public projection of the validated fixed-role CSV package.

No DeST/CSWD raw assets, simulation results, test feedback, or source records
are copied. The local full package remains the audit source.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "public_role_package"
PRIVATE_MANIFEST = HERE / "PACKAGE_MANIFEST.json"

TABLES = (
    "households_300.csv", "members_300.csv", "member_links_300.csv",
    "member_windows_300.csv", "devices_300.csv", "question_answers_300.csv",
    "provenance_300.csv",
)
PRIVATE_COLUMNS = {
    "households_300.csv": {"idf_repo_path", "weather_epw_repo_path"},
}
FORBIDDEN_TEXT = ("/Users/", "\\Users\\", "private_research", "runtime_inputs/", "eplusout.", "process.log")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def build():
    source = json.loads(PRIVATE_MANIFEST.read_text(encoding="utf-8"))
    if source["status"] != "FIXED_PROFILE_EXPORT_SEMANTIC_PASS_D_RESULTS_PENDING":
        raise ValueError("private profile package has no accepted fixed-profile status")
    if source["role_ids"] != 300 or source["simulation_results_exported"] or source["participant_responses_exported"]:
        raise ValueError("public projection requires 300 fixed roles and no outcomes")
    OUT.mkdir(exist_ok=True)
    published = {}
    for name in TABLES:
        original = HERE / name
        if digest(original) != source["tables"][name]["sha256"]:
            raise ValueError(f"private CSV changed: {name}")
        header, body = rows(original)
        keep = [key for key in header if key not in PRIVATE_COLUMNS.get(name, set())]
        if len(keep) == len(header) and name in PRIVATE_COLUMNS:
            raise ValueError(f"expected private columns absent: {name}")
        dest = OUT / name
        with dest.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=keep, lineterminator="\r\n")
            writer.writeheader()
            for row in body:
                writer.writerow({key: row[key] for key in keep})
        content = dest.read_text(encoding="utf-8-sig")
        if any(token in content for token in FORBIDDEN_TEXT):
            raise ValueError(f"private path or runtime marker leaked: {name}")
        reheader, reread = rows(dest)
        if reheader != keep or len(reread) != len(body) or any(
                actual != {key: old[key] for key in keep} for actual, old in zip(reread, body)):
            raise ValueError(f"public CSV roundtrip failed: {name}")
        published[name] = {"rows": len(body), "sha256": digest(dest), "removed_columns": sorted(PRIVATE_COLUMNS.get(name, set()))}
    master = rows(OUT / "households_300.csv")[1]
    role_ids = [f"cityrole-{i:04d}" for i in range(1, 301)]
    if [row["role_id"] for row in master] != role_ids:
        raise ValueError("public roles must be 300 unique stable IDs in order")
    if not all(row["city"] and row["province"] and row["virtual_building_id"] and
               row["source_catalog_key"] and row["weather_station_key"] and row["idf_sha256"] and
               row["weather_epw_sha256"] for row in master):
        raise ValueError("location, prototype, weather, or content fingerprints were lost")
    if any(row["participant_feedback_status"] != "NOT_COLLECTED" or
           row["simulation_result_status"] != "NOT_EXPORTED_PENDING_D_ACCEPTANCE" for row in master):
        raise ValueError("unaccepted outcomes appeared in public package")
    manifest = {
        "schema_version": "eb.public_synthetic_fixed_roles.v1",
        "status": "PUBLIC_CANDIDATE_FIXED_ROLES_ONLY_NOT_COLLECTION_READY",
        "source_input_sha256": source["source_sha256"],
        "local_full_package_manifest_sha256": digest(PRIVATE_MANIFEST),
        "source_ids_preserved_in": "provenance_300.csv",
        "building_and_weather_identifiers_preserved": True,
        "relative_or_absolute_model_and_weather_paths_exported": False,
        "raw_model_or_weather_assets_exported": False,
        "zones_with_source_model_internal_names_exported": False,
        "participant_feedback_rows": 0,
        "accepted_ten_day_results": 0,
        "tables": published,
    }
    (OUT / "PUBLIC_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": manifest["status"], "roles": 300,
                      "tables": {name: info["rows"] for name, info in published.items()}}, ensure_ascii=False))


if __name__ == "__main__": build()
