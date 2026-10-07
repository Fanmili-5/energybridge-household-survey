#!/usr/bin/env python3
"""Rebuild the household-to-IDF source ledger without running simulations.

Reads selected ASSEMBLY_BINDING/WEATHER_MATCH metadata, public aggregate source
caches, source templates and installed engine files. It never opens .dta files,
rewrites production code, changes run results, or changes LATEST. Local hashes
prove current byte identity, not authenticity of an official download.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_REPO = next(path for path in HERE.parents if path.name == "energybridge-household-survey")
H1000_REL = Path("docs/research/collection-adjustment-20260930/household1000")
PROTOTYPE_REL = Path("docs/research/long-horizon-plan/execution/prelaunch_rigor_20260924/household_300_resolution_20260925/v2_trial_20260926/C_idf/building_300.json")
ENGINE = Path("/Applications/EnergyPlus-24-1-0/energyplus")
DOC_ROOT = "https://bigladdersoftware.com/epx/docs/24-1/"


def read_json(path):
    return json.loads(Path(path).read_text())


def sha(path):
    if Path(path).suffix.lower() == ".dta":
        raise ValueError("source-ledger builder does not open survey microdata")
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_ref(path, expected=None):
    path = Path(path).absolute()
    result = {"path": str(path), "exists": path.is_file(), "expected_sha256": expected}
    if result["exists"]:
        result.update(sha256=sha(path), bytes=path.stat().st_size,
                      hash_status="matches_recorded_hash" if expected else "computed_local_bytes")
        if expected and result["sha256"] != expected:
            result["hash_status"] = "recorded_hash_mismatch"
    else:
        result.update(sha256=None, bytes=None, hash_status="missing_cache_unknown")
    return result


def url_ref(url, supports, limits, cache_status):
    return {"url": url, "supports": supports, "does_not_support": limits, "cache_status": cache_status}


def build(repo, pilot):
    repo = Path(repo).resolve()
    h1000 = repo / H1000_REL
    evidence = h1000 / "evidence_contract_20261001"
    bridge = h1000 / "chfs_census_bridge_20261003"
    stage = h1000 / "household_to_idf_20261003"
    run = stage / pilot
    input_lock = read_json(run / "INPUT_LOCK.json")
    experiment_manifest = read_json(run / "MANIFEST.json")
    prototype_catalog = repo / PROTOTYPE_REL
    weather_catalog = repo / "simulation_resources/catalog.json"
    constraints = read_json(evidence / "CITY_AUTHORITY_CONSTRAINTS_V2.json")
    prototypes = {record["role_id"]: record for record in read_json(prototype_catalog)["records"]}
    bindings = sorted((run / "cases").glob("*/ASSEMBLY_BINDING.json"))
    if not bindings:
        raise ValueError("no actual ASSEMBLY_BINDING.json files found in requested pilot")
    sources = []
    source_ids = set()
    links = []
    selected_prototypes = {}
    selected_weather = {}

    def add(source_id, kind, status, files, urls, supports, limits, **extra):
        if source_id in source_ids:
            raise ValueError("duplicate ledger source id: " + source_id)
        source_ids.add(source_id)
        entry = {"source_id": source_id, "kind": kind, "evidence_status": status,
                 "local_files": files, "source_urls": urls, "supports": supports,
                 "limitations": limits, **extra}
        sources.append(entry)
        return entry

    add("PROTOTYPE_CATALOG", "previous_derived_engineering_catalog", "derived_not_observed",
        [file_ref(prototype_catalog, input_lock["prototype_catalog_sha256"])], [], ["candidate identifiers and source/parent byte bindings"],
        ["old synthetic role geography/area is not current household observation or sampling weight"])
    add("WEATHER_CATALOG", "engineering_resource_registry", "derived_provider_inventory",
        [file_ref(weather_catalog, input_lock["resource_catalog_sha256"])], [url_ref("https://climate.onebuilding.org/WMO_Region_2_Asia/CHN_China/index.html", ["provider download inventory"], ["household sites, calibrated climate equivalence"], "directory viewed; HTML not cached in this stage")],
        ["weather resource paths, ids and recorded provider URLs"], ["verified registry status is narrower than current full-year weather admission"])
    for binding_path in bindings:
        binding = read_json(binding_path)
        weather_path = binding_path.parent / "WEATHER_MATCH.json"
        weather = read_json(weather_path)
        selected = weather.get("selected")
        if selected is None:
            raise ValueError("assembled case has no selected weather: " + str(binding_path.parent))
        selected_prototypes.setdefault(binding["prototype_id"], binding)
        selected_weather.setdefault(selected["id"], selected)
        links.append({"case_id": binding_path.parent.name,
                      "assembly_binding": file_ref(binding_path),
                      "weather_match": file_ref(weather_path),
                      "prototype_id": binding["prototype_id"], "weather_id": selected["id"],
                      "calibrated": binding.get("calibrated"),
                      "site_evidence": weather.get("target", {}).get("coordinate_evidence"),
                      "material_rows_sha256_recorded": binding.get("material_rows_sha256")})
    for prototype_id, binding in sorted(selected_prototypes.items()):
        record = prototypes[prototype_id]
        current_checks = {key: record.get(key) == binding.get(key) for key in
                          ("source_idf_path", "source_idf_sha256", "parent_idf_path", "parent_idf_sha256", "source_accdb_sha256")}
        for label in ("source", "parent"):
            source_path = Path(binding[label + "_idf_path"])
            add("DEST_" + label.upper() + "_IDF_" + prototype_id,
                "converted_thermal_source" if label == "source" else "parent_source_reused_or_derived",
                "engineering_template_uncalibrated", [file_ref(source_path, binding[label + "_idf_sha256"])],
                [url_ref("https://svr.dest.net.cn/api/v1/load_model_file", ["DeST catalog model retrieval endpoint recorded by local manifest"], ["measured source dwelling, national stock representativeness, local standard compliance"], "download lineage inherited from source manifest; underlying measured-building origin unknown")],
                ["traceable thermal assembly source bytes"],
                ["catalog city/year is a prototype key, not observed household origin",
                 "underlying original local building measurements unknown",
                 "construction names citing JGJ134-2001-Shanghai do not prove standard compliance",
                 "template uncalibrated; cross-city construction transfer remains explicit research design"],
                prototype_id=prototype_id, catalog_key=binding["prototype_catalog_key"],
                source_height_m=binding.get("source_height_m"),
                source_and_parent_same_path=binding["source_idf_path"] == binding["parent_idf_path"],
                catalog_binding_checks=current_checks, construction_map=binding["construction_map"])
        source_dir = Path(binding["source_idf_path"]).parent
        manifest_path = source_dir / "manifest.json"
        manifest = read_json(manifest_path) if manifest_path.exists() else {}
        files = [file_ref(manifest_path)]
        files.extend(file_ref(path, manifest.get("source_accdb_sha256")) for path in sorted(source_dir.glob("*.accdb")))
        files.extend(file_ref(path, manifest.get("archive_sha256")) for path in sorted(source_dir.glob("*.accdb.7z")))
        add("DEST_RAW_LINEAGE_" + prototype_id, "private_model_source_lineage", "source_bytes_only",
            files, [url_ref("https://github.com/hongyuanjia/destep", ["converter implementation repository; source manifest pins commit 1d93a51c5dd6a48e0a108d9646f00a496f23d1ec"], ["physical calibration, actual household membership or licensing of original DeST archive"], "repository URL inherited; converter executable environment currently not available")],
            ["archive → accdb → converted IDF recorded byte chain"],
            ["original local measured building and DeST data redistribution terms unknown",
             "cached archive/accdb are private research sources, not public household data"],
            conversion=manifest.get("conversion"), original_source_runtime_checked=manifest.get("runtime_checked"),
            underlying_local_building_origin="unknown", original_redistribution_permission="unknown")
    readers = {(binding["source_reader_path"], binding["source_reader_sha256"]) for binding in selected_prototypes.values()}
    for index, (reader, expected) in enumerate(sorted(readers), 1):
        add("LEGACY_ASSEMBLY_READER_" + str(index), "engineering_code_dependency", "implementation",
            [file_ref(reader, expected)], [], ["IDF parsing and source assembly extraction"],
            ["helper reuse does not inherit all old pipeline physics, devices or validation claims"])
    for identifier, selected in sorted(selected_weather.items()):
        epw = Path(selected["epw_absolute_path"])
        source_path = epw.parent / "source.json"
        source = read_json(source_path) if source_path.exists() else {}
        add("WEATHER_" + identifier, "provider_typical_year_weather", "matched_engineering_candidate",
            [file_ref(epw, selected["epw_sha256"]), file_ref(selected["ddy_absolute_path"], selected["ddy_sha256"]), file_ref(source_path)],
            [url_ref(selected["source_url"], ["provider archive source for this EPW/DDY"], ["2021 measured household weather, observed household address, climate-equivalence certification"], "EPW/DDY/source manifest locally cached; original ZIP byte hash recorded, ZIP cache existence not asserted")],
            ["station-coincident designed-site weather input with full-year engineering file QC"],
            ["TMYx source-period label is not a single measured year", "dwelling site was designed equal to station, not sampled from household geography"],
            station_id=identifier, province=selected["province"], city=selected["city"],
            series=selected["series"], location=selected["epw_location"],
            archive_sha256_recorded=source.get("archive_sha256"),
            annual_quality_status=selected["annual_quality"]["status"], climate_equivalence_certified=False)
    engine_version = subprocess.run([str(ENGINE), "--version"], check=True, capture_output=True, text=True).stdout.strip()
    add("ENERGYPLUS_ENGINE", "installed_simulation_engine", "local_runtime_identity",
        [file_ref(ENGINE), file_ref(ENGINE.parent / "Energy+.idd"), file_ref(ENGINE.parent / "Energy+.schema.epJSON")],
        [url_ref("https://github.com/NREL/EnergyPlus/releases/tag/v24.1.0", ["official 24.1 release lineage"], ["identity of user's local installer or calibration of this study"], "release URL listed; local installer origin/hash not supplied")],
        ["engine executable identity, version and input schema"],
        ["binary hash establishes local reproducibility only; official byte identity and installer provenance not independently authenticated"],
        version_command=[str(ENGINE), "--version"], version_output=engine_version)
    docs = [
        ("ENERGYPLUS_EPW_DICTIONARY", "auxiliary-programs/energyplus-weather-file-epw-data-dictionary.html", "AuxiliaryPrograms.pdf", ["EPW header/time fields and missing/range semantics", "DST header control", "undisturbed ground-temperature limitation"], ["1600Wh/m2 cap or distance/elevation policies"]),
        ("ENERGYPLUS_GEOMETRY", "input-output-reference/group-thermal-zone-description-geometry.html", "InputOutputReference.pdf", ["Floor surfaces, explicit floor-area precedence, enclosed volume, surface boundary semantics"], ["natural-room functional allocation, gross-to-net ratio, calibrated template"]),
        ("ENERGYPLUS_LOCATION", "input-output-reference/group-location-climate-weather-file-access.html", "InputOutputReference.pdf", ["weather LOCATION overrides Site:Location in 24.1", "latitude/longitude/timezone/elevation fields"], ["latest-version Keep Site Location feature in 24.1", "station-target climate equivalence"]),
        ("ENERGYPLUS_EIO", "output-details-and-examples/eplusout-eio.html", "OutputDetailsAndExamples.pdf", ["actual engine location, area/volume/surface audit outputs"], ["scientific physical calibration or actual household representativeness"]),
    ]
    for identifier, url_path, pdf_name, supports, limits in docs:
        add(identifier, "primary_software_documentation", "documented_semantics",
            [file_ref(ENGINE.parent / "Documentation" / pdf_name)],
            [url_ref(DOC_ROOT + url_path, supports, limits, "HTML reviewed in 2026-10-03 weather review, not saved; corresponding installed 24.1 PDF cached; byte equivalence to hosted HTML unknown")], supports, limits,
            document_version="24.1", host_role="BigLadder-hosted EnergyPlus documentation")
    plan = constraints["indicator_authority"]
    add("NBS_CENSUS2020_PLAN", "official_statistical_indicator_document", "fact_definition",
        [file_ref(evidence / plan["file"], plan["sha256"])],
        [url_ref(plan["url"], ["H5 ordinary-dwelling skip scope; H6 building area and shared-household share; H7 natural rooms"], ["inverse1.33 is an official gross-to-usable measurement", "H7 is bedrooms or EnergyPlus zones"], "official source PDF cached; current bytes verified")],
        ["housing indicator meanings and conditional housing scope"],
        ["using-area→building-area fallback1.33 does not validate the inverse engineering ratio", "public statistical definitions do not identify each household plan or functional room allocation"],
        pages_1based=plan["pages_1based"], page26_H6_H7_independently_read=True)
    for identifier, table in sorted(constraints["tables"].items()):
        add("NBS_TABLE_" + identifier, "official_public_aggregate_statistics", "fact_aggregate_margin",
            [file_ref(evidence / table["file"], table["sha256"])],
            [url_ref(table["url"], [table["title"], table["frame"]], ["fully observed province×size×generation×housing joint", "actual city-specific household address/weather"], "raw aggregate spreadsheet cached; byte hash verified; title/frame inherited from reviewed constraints")],
            [table["title"]], ["marginal aggregate, not household microdata or a complete joint distribution"], frame=table["frame"], title=table["title"])
    inherited = read_json(bridge / "SOURCE_LEDGER.json")
    for entry in inherited["entries"]:
        if not entry.get("source_id", "").startswith("NBS_") or not entry.get("url"):
            continue
        add(entry["source_id"], "official_statistical_explanation", "inherited_document_review",
            [file_ref(entry["local_path"], entry.get("sha256"))],
            [url_ref(entry["url"], entry.get("supports", []), ["exact CHFS→census membership equivalence"], "local HTML cache verified; prior bridge review inherited")],
            entry.get("supports", []), ["does not fill missing source residence or complete family graph"])
    contracts = [
        ("GENERATION_BRIDGE_CONTRACT", bridge / "GENERATION_BRIDGE_CONTRACT.json", ["upstream census/CHFS bridge scope and missingness contract"], ["source strata do not identify current city; proxy is not exact census membership"]),
        ("BASE_GENERATION_CONTRACT", h1000 / "chfs_admission_20261003/GENERATION_SOURCE_CONTRACT.json", ["base generation field/temporal/asset boundaries"], ["not a source of observed IDF geometry or actual location"]),
        ("BRIDGE_SOURCE_LEDGER", bridge / "SOURCE_LEDGER.json", ["upstream source provenance and page/rule bindings"], ["inherited CHFS metadata only; no .dta re-read or hash in this ledger pass"]),
        ("TARGET1000_ALLOCATION", evidence / "POPULATION_ALLOCATION_CANDIDATE_V2.json", ["frozen1000 province×size×generation slots under IPF/MILP assumptions"], ["candidate allocation not complete roles; no household-city distribution or H5/H7 assignment"]),
        ("CITY_AUTHORITY_CONSTRAINTS", evidence / "CITY_AUTHORITY_CONSTRAINTS_V2.json", ["reviewed official aggregate margins and indicator meanings"], ["ordinary dwelling housing margins are conditional, not all-city household joint"]),
        ("WEATHER_RULES_IMPLEMENTATION", stage / "weather_rules.py", ["explicit engineering geography/file/plausibility gates; defaults stored in registry QC"], ["not an official climate-equivalence standard"]),
        ("WEATHER_REGISTRY_QC", stage / "WEATHER_REGISTRY_QC.json", ["aggregate full-year QC of246 catalog verified entries under current policy"], ["217 rejected by current combined policy does not prove217 files universally corrupted"]),
        ("WEATHER_VERIFICATION", stage / "WEATHER_VERIFICATION.json", ["13/13 independent rule-behavior tests"], ["not EnergyPlus runtime, household calibration or national representativeness"]),
        ("LEDGER_BUILDER", Path(__file__), ["repeatable selection/hash/source-ledger construction"], ["no independent authentication of official local file bytes"]),
    ]
    for identifier, path, supports, limits in contracts:
        add(identifier, "derived_contract_or_engineering_artifact", "implementation_or_declared_assumption",
            [file_ref(path)], [], supports, limits)
    add("FINAL_EXPERIMENT_SOURCE_LOCK", "frozen_experiment_provenance", "frozen_source_binding",
        [file_ref(run / name, experiment_manifest["files"].get(name)) for name in
         ("INPUT_LOCK.json", "EXPERIMENT_INPUTS.json", "SUMMARY.json")] + [file_ref(run / "MANIFEST.json")],
        [], ["final experiment input/catalog/code identity"],
        ["runtime outcomes are recorded in the final batch; this ledger pass does not rerun EnergyPlus"],
        experiment_directory=str(run), experiment_id=input_lock.get("experiment_id", pilot))
    for filename, expected in sorted(input_lock["code"].items()):
        physical_dependency = filename in {"run_stage.py", "household_model.py", "idf_builder.py", "weather_rules.py"}
        files = [file_ref(run / "code" / filename, expected)]
        current = file_ref(stage / filename, expected if physical_dependency else None)
        files.append(current)
        current_matches_snapshot = current.get("sha256") == expected
        add("FINAL_CODE_" + filename, "frozen_engineering_implementation", "final_snapshot_bytes",
            files,
            [], ["frozen/current physical implementation byte identity" if physical_dependency else "archived and current independent audit/analysis tool byte identity"],
            ["engineering code is an implementation source, not observed household evidence"],
            snapshot_directory=str(run / "code"),
            physical_execution_dependency=physical_dependency,
            current_matches_frozen_snapshot=current_matches_snapshot,
            post_run_audit_revision=not physical_dependency and not current_matches_snapshot,
            post_run_audit_utility_note="archive glob captured an earlier independent audit-tool draft; current post-run audit version is separately hashed, not a substituted physical execution dependency" if not physical_dependency and not current_matches_snapshot else None)
    for name in ("INDEPENDENT_GEOMETRY_CHECK.json", "INDEPENDENT_SOURCE_CHECK.json", "REGRESSION_CHECK.json"):
        add("POST_RUN_QA_" + name, "independent_post_run_audit_report", "recorded_independent_audit",
            [file_ref(run / name)], [], ["post-run validation evidence, paired with current independent audit tool bytes"],
            ["this source-ledger pass does not rerun those tests or EnergyPlus; archived tool drafts are historical"])
    qc = read_json(stage / "WEATHER_REGISTRY_QC.json")
    rule_bindings = [
        {"rule": "city_only_population_and_scope", "source_ids": ["GENERATION_BRIDGE_CONTRACT", "NBS_TABLE_A0108a", "NBS_TABLE_A0109a"], "status": "statistical target and declared eligibility; city site still missing for1000 slots"},
        {"rule": "H5_H6_H7_and_area_semantics", "source_ids": ["NBS_CENSUS2020_PLAN", "GENERATION_BRIDGE_CONTRACT"], "status": "fact definitions; functional layout and gross-to-zone ratio are engineering choices"},
        {"rule": "1000_province_size_generation_allocation", "source_ids": ["TARGET1000_ALLOCATION", "CITY_AUTHORITY_CONSTRAINTS"], "status": "modeled completion and integer calibration, not fully observed joint"},
        {"rule": "thermal_source_assemblies", "source_ids": ["PROTOTYPE_CATALOG"] + ["DEST_SOURCE_IDF_" + p for p in sorted(selected_prototypes)], "status": "uncalibrated engineering source transfer"},
        {"rule": "weather_target_and_file_admission", "source_ids": ["WEATHER_RULES_IMPLEMENTATION", "WEATHER_CATALOG", "ENERGYPLUS_EPW_DICTIONARY", "ENERGYPLUS_LOCATION", "WEATHER_REGISTRY_QC"], "status": "documented format plus explicitly declared engineering thresholds; climate equivalence unknown"},
        {"rule": "geometry_boundary_and_runtime_output_semantics", "source_ids": ["ENERGYPLUS_ENGINE", "ENERGYPLUS_GEOMETRY", "ENERGYPLUS_EIO"], "status": "software semantics; scientific physical validation remains separate"},
    ]
    integrity = [file for entry in sources for file in entry["local_files"] if file["hash_status"] == "recorded_hash_mismatch"]
    return {"schema": "household_to_idf.source_ledger.v1", "snapshot_date_HKT": "2026-10-03",
            "scope": "factual/statistical and engineering sources separated; source selection extracted from actual pilot bindings",
            "selection_snapshot": {"pilot": str(run), "assembly_filename": "ASSEMBLY_BINDING.json", "weather_filename": "WEATHER_MATCH.json", "assembled_case_count": len(bindings), "prototype_ids": sorted(selected_prototypes), "weather_ids": sorted(selected_weather)},
            "sources": sources, "case_source_links": links, "rule_evidence_bindings": rule_bindings,
            "weather_qc_summary": {"verified_entries": qc["station_count"], "passed_current_policy": qc["passed_file_quality_count"], "rejected_current_policy": qc["failed_file_quality_count"], "rejection_reason_station_counts": qc["rejection_reason_station_counts"], "reasons_overlap": True, "rejection_is_not_universal_corruption_claim": True, "policy": qc["policy"]},
            "integrity": {"recorded_hash_mismatch_count": len(integrity), "recorded_hash_mismatches": integrity,
                          "physical_execution_modules_current_match_frozen": all(entry["current_matches_frozen_snapshot"] for entry in sources if entry.get("physical_execution_dependency")),
                          "post_run_audit_tool_revisions": [entry["source_id"] for entry in sources if entry.get("post_run_audit_revision")],
                          "local_byte_hash_is_not_official_origin_authentication": True},
            "unknowns": ["actual household city/coordinates and1000 slot housing eligibility", "exact CHFS to census membership equivalence", "full factual household functional room graph", "underlying local original DeST measured-building origin and calibration", "standard texts implied by construction labels", "template physical transfer validity", "station-to-household climate equivalence", "official local installer byte authentication", "hosted technical HTML byte cache/equivalence to installed PDFs", "original DeST source redistribution permission"],
            "raw_microdata_read_this_pass": False, "simulations_run_this_pass": False, "run_results_modified": False,
            "build_command": ["python", str(Path(__file__).resolve()), "--repo", str(repo), "--pilot", pilot]}


def support_markdown(ledger):
    summary = ledger["weather_qc_summary"]
    return """# 来源支撑与剩余缺口

完整逐来源字节、URL与规则绑定见 [SOURCE_LEDGER.json](SOURCE_LEDGER.json)，可用 `build_source_ledger.py --pilot PILOT_NAME` 重建。选择依据为实际 `ASSEMBLY_BINDING.json` / `WEATHER_MATCH.json`，不会修改运行结果或LATEST。

| 层次 | 当前有据内容 | 仍不能推出 |
| --- | --- | --- |
| 统计事实 | 普查原文H5/H6/H7与城市家庭户边际；cachedPDF/表及桥接合同hash | 完整省×人数×代际×住房联合、1000户现实城市与地址 |
| 生成桥接 | 冻结1000slot与IPF/MILP假设、成员/住房代理及缺失边界 | 完全观察家庭、精确普查成员与逐户自然间功能图 |
| 模板工程 | 实际所选DeST源/parent IDF、archive/accdb/manifest字节、legacy reader | 当地实测建筑原型、JGJ文字标签对应标准合规、住房校准 |
| 天气工程 | 实际所选EPW/DDY/source URL/hash与全年QC；设计坐标等于站点 | 真实户地址、同城微气候代表性、家庭观测年份天气 |
| 运行引擎 | 实际binary/IDD/schema/PDF hash与24.1版本；官方软件语义 | 模型校准、真实全户用电、源安装包官方字节认证 |
| 规则验证 | [WEATHER_VERIFICATION.json](WEATHER_VERIFICATION.json)记录13/13规则正反例 | EnergyPlus运行或科学有效性 |

天气246站中29通过、217按当前工程策略拒绝；3项country代码、200项关键缺失、214项辐射阈值计数有重叠。拒绝不是“所有217源文件损坏”的结论。地理、海拔、太阳时、辐射cap及dew误差阈值是明示研究策略，不是假称官方规范。

模板原始地方测量来源、实际家庭地理、JGJ标准原文和气候等价仍unknown；新模块保留这些缺口。源码来源、统计来源、引擎来源各有不同支撑范围。

final_v5归档glob包含当时独立审计工具草稿。事后审计工具当前版本及报告另记hash；不同版本字节都保留，不当作物理执行代码的替换。真正执行的run_stage/household_model/idf_builder/weather_rules四模块要求current/frozen同sha。
""".replace("PILOT_NAME", Path(ledger["selection_snapshot"]["pilot"]).name).replace("246站中29通过、217", f"{summary['verified_entries']}站中{summary['passed_current_policy']}通过、{summary['rejected_current_policy']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    parser.add_argument("--pilot", default="final_v5")
    parser.add_argument("--output", type=Path, default=HERE / "SOURCE_LEDGER.json")
    args = parser.parse_args()
    ledger = build(args.repo, args.pilot)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(ledger, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    (args.output.parent / "SOURCE_SUPPORT.md").write_text(support_markdown(ledger))
    print(json.dumps({"output": str(args.output), "source_count": len(ledger["sources"]), "selection_snapshot": ledger["selection_snapshot"], "integrity": ledger["integrity"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
