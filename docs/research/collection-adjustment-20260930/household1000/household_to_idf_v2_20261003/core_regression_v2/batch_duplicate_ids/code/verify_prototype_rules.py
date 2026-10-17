#!/usr/bin/env python3
"""Directed source/admission verification; no annual or household microdata run."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import tempfile

import prototype_rules as rules

HERE = Path(__file__).resolve().parent
EXPERIMENT_ID = "PROTOTYPE_ADMISSION_V2_20261003"


def main(repo, out):
    registry = rules.load_json(HERE / "PROTOTYPE_REGISTRY.json")
    checks = []
    examples = {}
    def check(name, condition, observed=None):
        checks.append({"check_id": name, "passed": bool(condition), "observed": observed})
    rebuilt = rules.build_registry(repo)
    check("registry_reproduces_from_actual_sources", rebuilt == registry, {"registry_sha256": rules.sha(HERE / "PROTOTYPE_REGISTRY.json"), "rebuilt_fingerprint": rules.fingerprint(rebuilt)})
    summary = registry["summary"]
    check("300_aliases_193_groups", summary["catalog_role_keys"] == 300 and summary["source_groups"] == 193, summary)
    check("180_apartment_13_terraced_source_groups", summary["branch_group_counts"] == {rules.APARTMENT_BRANCH: 180, rules.TERRACED_BRANCH: 13})
    variants = [v for g in registry["groups"].values() for v in g["variants"]]
    check("all_300_source_parent_closure_height_checks", all(v["source_verification"]["passed"] for v in variants), {"passed": sum(v["source_verification"]["passed"] for v in variants)})
    check("all_300_selected_internal_walls_symmetric", all(v["assembly_summary"]["internal_wall_symmetric"] for v in variants), {"asymmetric": summary["asymmetric_internal_wall_variants"]})
    check("193_distinct_original_accdb_hashes", len({v["selected_catalog_row"]["source_accdb_sha256"] for v in variants}) == 193)
    forbidden = {"home_city", "home_province", "family_size", "occupancy_binding", "ac_meter", "controls", "device_energy_ports", "housing_mode", "weather_epw_path"}
    check("no_household_or_device_fields_in_binding_rows", all(not forbidden.intersection(v["selected_catalog_row"]) for v in variants))
    check("source_groups_are_not_calibrated_or_redistribution_verified", all(not g["physical_calibration_verified"] and not g["measured_locality_verified"] and not g["redistribution_permission_verified"] for g in registry["groups"].values()))
    check("every_alias_resolves_to_its_fingerprint_group", all(rules.group_from_key(v["role_key"], registry) == gid for gid,g in registry["groups"].items() for v in g["variants"]))
    chengdu = registry["groups"][rules.group_from_key("cityrole-0039", registry)]
    check("chengdu_chinese_alias_is_romanization_evidenced", "成都" in chengdu["source_metadata"]["city_aliases"] and bool(chengdu["source_metadata"]["city_alias_evidence"]))
    check("anda_admin_suihua_is_not_same_city_alias", all("绥化" not in g["source_metadata"]["city_aliases"] for g in registry["groups"].values() if g["source_metadata"]["catalog_city_token"] == "Anda"))
    check("ambiguous_yichun_province_remains_unknown", all(g["source_metadata"]["province_label"] is None for g in registry["groups"].values() if g["source_metadata"]["catalog_city_token"] == "Yichun"))

    def target(form="high_rise_slab_apartment", year=2001, city="成都市", province="四川"):
        t = {"geometry_family": "single_storey_apartment", "building_form": form, "construction_year": year, "city": city, "province": province, "feature_evidence": {}}
        for k in rules.FEATURE_KEYS:
            if t[k] is not None: t["feature_evidence"][k] = {"kind": "declared_catalog_label_condition", "evidence_id": EXPERIMENT_ID}
        return t
    def request(t=None, key="cityrole-0039", mode="feature_match", reg=registry):
        t = target() if t is None else t
        req = {"target": t, "policy": {"mode": mode, "use_scope": rules.USE_SCOPE}}
        if key is not None: req["prototype_key"] = key
        if mode != "feature_match":
            d = rules.describe_target_conditions(key, t, reg)
            common = {"source_group_id": d["source_group_id"], "target_signature": d["target_signature"], "use_scope": rules.USE_SCOPE, "evidence_id": EXPERIMENT_ID, "rationale": "declared conditional engineering test; no measured local-stock or inherited topology claim"}
            if mode == "declared_design" or d["unknown_features"]:
                req["policy"]["design_evidence"] = common | {"kind": "conditional_template_design", "accepted_unknown_features": d["unknown_features"]}
            if mode == "transport" or d["mismatch_axes"]:
                req["policy"]["transport_evidence"] = common | {"kind": "engineering_transport_design", "allowed_mismatches": d["mismatch_axes"]}
        return req
    def resolve(req, reg=registry): return rules.resolve_prototype(req, repo, reg)
    def accepts(name, req, expected_status, reg=registry):
        result = resolve(req, reg)
        check(name, result["eligible"] and result["status"] == expected_status, {"status": result["status"], "reject_reasons": result["reject_reasons"]})
        return result
    def rejects(name, req, substring=None, reg=registry):
        result = resolve(req, reg)
        check(name, not result["eligible"] and result["selected_catalog_row"] is None and (substring is None or any(substring in r for r in result["reject_reasons"])), result["reject_reasons"])
        return result

    baseline = request()
    explicit = accepts("explicit_key_feature_candidate", baseline, "catalog_feature_candidate_admitted")
    check("explicit_candidate_has_no_geometry_or_calibration_claim", not explicit["geometry_compatibility_certified"] and not explicit["physical_calibration_verified"] and not explicit["topology_inherited"])
    check("actual_chengdu_height_and_shanghai_named_assembly_retained", abs(explicit["assembly_summary"]["height_m"] - 2.8499950850289983) < 1e-12 and "Shanghai" in explicit["assembly_summary"]["constructions"]["external_wall"])
    check("ordered_layers_and_object_frequency_basis_retained", explicit["assembly_summary"]["frequency_basis"] == "surface_or_window_object_count_not_area_weighted" and bool(explicit["assembly_summary"]["observed_construction_frequencies"]) and all("outside_to_inside_layers" in v for v in explicit["assembly_summary"]["construction_details"].values()))
    accepts("explicit_declared_known_design", request(mode="declared_design"), "conditional_design_admitted")
    unknown = target(None, None, None, None)
    rejects("unknown_feature_match_is_not_guessed", request(unknown), "unknown_feature:")
    unknown_req = request(unknown, mode="declared_design")
    accepts("explicit_unknown_conditional_design", unknown_req, "conditional_design_admitted")
    examples["known_design"] = request(mode="declared_design")
    examples["unknown_design"] = unknown_req
    for key in rules.TARGET_KEYS:
        req = deepcopy(baseline); req["target"].pop(key)
        rejects("missing_target_field_" + key, req, "target_fields_missing")
    for key in rules.FEATURE_KEYS:
        req = deepcopy(baseline); req["target"]["feature_evidence"].pop(key)
        rejects("missing_known_feature_evidence_" + key, req, "target_feature_evidence_missing:" + key)
    for obj in (None, [], "legacy-prototype-key"):
        rejects("request_type_" + type(obj).__name__, obj, "prototype_request_must_be_object")
    rejects("legacy_key_without_request_not_admitted", {"prototype_key": "cityrole-0039"}, "target_fields_missing")
    req = deepcopy(baseline); req.pop("policy"); rejects("missing_policy", req, "prototype_policy_missing")
    req = deepcopy(baseline); req["policy"]["mode"] = "automatic"; rejects("unknown_mode", req, "unknown_prototype_mode")
    req = deepcopy(baseline); req["policy"]["use_scope"] = "inherit_household_topology"; rejects("topology_inheritance_scope", req, "unsupported_use_scope")
    req = deepcopy(baseline); req["policy"]["require_symmetric_internal_wall"] = False; rejects("wall_symmetry_cannot_be_relaxed", req, "symmetric_wall_policy_cannot_be_disabled")
    req = deepcopy(baseline); req["target"]["geometry_family"] = "two_storey_terraced"; rejects("unsupported_terraced_target_geometry", req, "unsupported_target_geometry_family")
    req = deepcopy(baseline); req["target"]["construction_year"] = True; rejects("boolean_year", req, "target_construction_year_invalid")
    req = deepcopy(baseline); req["target"]["construction_year"] = float("inf"); rejects("nonfinite_request", req, "nonfinite_number")
    req = deepcopy(baseline); req["prototype_key"] = "cityrole-9999"; rejects("unknown_explicit_key", req, "prototype_key_unknown_or_ambiguous")
    req = request(mode="declared_design"); req.pop("prototype_key"); rejects("design_requires_explicit_source", req, "explicit_source_key_required")
    req = deepcopy(unknown_req); req["policy"].pop("design_evidence"); rejects("unknown_cannot_be_granted_without_design_evidence", req, "conditional_template_design_evidence_missing")
    req = deepcopy(unknown_req); req["policy"]["design_evidence"]["accepted_unknown_features"] = ["target.city"]; rejects("design_unknown_axes_must_be_complete", req, "must_exactly_cover_actual_axes")
    req = deepcopy(unknown_req); req["target"]["city"] = "Chengdu"; rejects("design_target_change_breaks_binding", req, "target_signature_mismatch")
    req = deepcopy(unknown_req); req["policy"]["design_evidence"]["source_group_id"] = "prototype_wrong"; rejects("design_source_group_change_breaks_binding", req, "source_group_id_mismatch")

    stress = request(target(None, None, "伊春", "黑龙江"), mode="transport")
    transported = accepts("explicit_city_province_unknown_vintage_transport", stress, "transport_design_admitted")
    check("transport_axes_are_exact_and_no_local_stock_claim", transported.get("mismatch_axes") == ["city", "province"] and transported.get("unknown_features") == ["target.building_form", "target.construction_year"] and not transported["physical_calibration_verified"])
    examples["climate_transport"] = stress
    for slot, field, newvalue in [("transport_evidence", "source_group_id", "prototype_wrong"), ("transport_evidence", "target_signature", "0"*64), ("transport_evidence", "use_scope", "topology"), ("transport_evidence", "kind", "nonempty_string"), ("transport_evidence", "allowed_mismatches", ["city"]), ("transport_evidence", "allowed_mismatches", ["city", "province", "construction_year"]), ("transport_evidence", "evidence_id", ""), ("transport_evidence", "rationale", "")]:
        req = deepcopy(stress); req["policy"][slot][field] = newvalue
        rejects("transport_wrong_" + field + "_" + str(newvalue)[:12], req)
    req = deepcopy(stress); req["policy"].pop("transport_evidence"); rejects("cross_city_not_authorized_by_design_only", req, "engineering_transport_design_evidence_missing")
    req = deepcopy(stress); req["policy"]["transport_evidence"] = "approved"; rejects("arbitrary_transport_string_rejected", req, "engineering_transport_design_evidence_missing")
    req = request(target(year=2012)); rejects("vintage_mismatch_requires_transport", req, "engineering_transport_design_evidence_missing")
    accepts("explicit_vintage_transport", request(target(year=2012), mode="transport"), "transport_design_admitted")
    req = request(target(form="low_rise_apartment")); rejects("form_mismatch_requires_transport", req, "engineering_transport_design_evidence_missing")
    accepts("explicit_form_assembly_transport", request(target(form="low_rise_apartment"), mode="transport"), "transport_design_admitted")
    terraced = request(target("low_rise_apartment", 2018, "西安", "陕西"), key="cityrole-0029", mode="transport")
    terrace_result = accepts("terraced_assemblies_only_explicit_cross_branch_transport", terraced, "transport_design_admitted")
    check("terraced_source_cannot_claim_apartment_topology", terrace_result.get("mismatch_axes") == ["building_form", "source_branch"] and not terrace_result["geometry_compatibility_certified"] and not terrace_result["topology_inherited"])
    examples["terraced_assembly_transport"] = terraced
    req = deepcopy(terraced); req["policy"].pop("transport_evidence"); rejects("terraced_branch_not_automatic_apartment_match", req, "engineering_transport_design_evidence_missing")
    req = request(target("terraced_house",2018,"西安","陕西"),key="cityrole-0029",mode="transport"); rejects("terraced_target_form_is_outside_writer_domain", req, "target_form_not_supported")
    check("transport_wrapper_does_not_create_mode_or_evidence", not rules.transport_admission(baseline,repo,registry)["eligible"] and not rules.transport_admission({"policy":"transport"},repo,registry)["eligible"])

    auto = accepts("automatic_exact_feature_selection", request(key=None), "catalog_feature_candidate_admitted")
    check("automatic_ranks_groups_not_300_aliases", len(auto["ranking"]) == 193 and len({x["source_group_id"] for x in auto["ranking"]}) == 193)
    check("automatic_representative_alias_is_lexical", auto["selected_role_key"] == registry["groups"][auto["selected_group_id"]]["representative_role_key"])
    tie = request(target("low_rise_apartment",2014,"北京","北京"),key=None)
    tie["policy"]["max_vintage_label_difference_years"] = 4
    tied = accepts("configurable_vintage_label_tie",tie,"catalog_feature_candidate_admitted")
    check("tie_is_visible_and_deterministic", tied.get("tie_present") and tied["selected_group_id"] == min(tied["tie_group_ids"]), tied.get("tie_group_ids"))
    shuffled = deepcopy(registry); shuffled["groups"] = dict(reversed(list(shuffled["groups"].items())))
    again = resolve(tie,shuffled)
    check("ranking_invariant_to_registry_dict_order", tied["selected_group_id"] == again.get("selected_group_id") and tied["ranking"] == again["ranking"])

    gid = rules.group_from_key("cityrole-0039",registry)
    altered = deepcopy(registry); altered["groups"][gid]["source_metadata"]["city_aliases"].append("上海")
    rejects("registry_city_alias_tamper_is_rejected",baseline,"registry_source_metadata_mismatch",altered)
    altered = deepcopy(registry); altered["groups"][gid]["source_branch"] = rules.TERRACED_BRANCH
    rejects("registry_branch_tamper_is_rejected",baseline,"registry_source_metadata_mismatch",altered)
    altered = deepcopy(registry); var = next(v for v in altered["groups"][gid]["variants"] if v["role_key"] == "cityrole-0039"); var["selected_catalog_row"]["household_owned_zones"] = ["fabricated-zone"]
    rejects("registry_owned_zone_tamper_is_rejected",baseline,"registry_variant_catalog_row_mismatch",altered)
    altered = deepcopy(registry); var = next(v for v in altered["groups"][gid]["variants"] if v["role_key"] == "cityrole-0039"); var["assembly_summary"]["height_m"] = 9
    rejects("registry_height_cache_tamper_is_rejected",baseline,"registry_assembly_summary_mismatch",altered)
    altered = deepcopy(registry); var = next(v for v in altered["groups"][gid]["variants"] if v["role_key"] == "cityrole-0039"); var["assembly_summary"]["internal_wall_symmetric"] = False
    rejects("asymmetric_cached_wall_is_rejected",baseline,"asymmetric_internal_wall_not_supported",altered)

    # Actual-byte rejection using a temporary isolated repository; source files
    # in the real research tree are never modified by this audit.
    original = explicit["selected_catalog_row"]
    with tempfile.TemporaryDirectory(prefix="prototype-source-test-") as td:
        root = Path(td).resolve(); src = root/"source.idf"; parent = root/"parent.idf"
        src.write_bytes(Path(original["source_idf_path"]).read_bytes()); parent.write_bytes(Path(original["parent_idf_path"]).read_bytes())
        row = deepcopy(original); row["source_idf_path"] = str(src); row["parent_idf_path"] = str(parent)
        check("isolated_exact_source_copy_verifies", rules.verify_catalog_row(row,root)["passed"])
        src.write_text(src.read_text()+"\n! modified bytes\n")
        inspected = rules.verify_catalog_row(row,root)
        check("actual_source_byte_mutation_rejected", not inspected["passed"] and any("hash_mismatch" in r for r in inspected["reject_reasons"]))
        src.write_bytes(Path(original["source_idf_path"]).read_bytes()); parent.write_text(parent.read_text()+"\n! modified parent bytes\n")
        check("actual_parent_byte_mutation_rejected", not rules.verify_catalog_row(row,root)["passed"])
        src.unlink(); check("missing_source_rejected", not rules.verify_catalog_row(row,root)["passed"])
        try: rules._path(root, "/arbitrary-external-source.idf"); rejected=False
        except ValueError: rejected=True
        check("arbitrary_external_source_path_rejected",rejected)
        # Preserve the frozen catalog bytes, but relocate its known old repo
        # prefix. Only selected source files are needed for this explicit key.
        for rel in (rules.CATALOG_REL,rules.WEATHER_CATALOG_REL):
            dest=root/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes((repo/rel).read_bytes())
        for key in ("source_idf_path","parent_idf_path"):
            actual=Path(original[key]);rel=actual.relative_to(repo);dest=root/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(actual.read_bytes())
        relocated=rules.resolve_prototype(baseline,root,registry)
        check("frozen_absolute_catalog_relocates_with_real_source_hashes",relocated["eligible"] and Path(relocated["selected_catalog_row"]["parent_idf_path"]).is_relative_to(root),relocated["reject_reasons"])
        badjson=root/"bad.json"; badjson.write_text('{"x":1e999}')
        try: rules.load_json(badjson); rejected=False
        except ValueError: rejected=True
        check("json_overflow_token_rejected",rejected)
        cachejson=root/"cache.json";cachejson.write_text('{"nested":{"values":[1]}}')
        cached=rules.load_json(cachejson);cached['nested']['values'].append(2)
        check("json_cache_returns_independent_mutable_views",rules.load_json(cachejson)=={'nested':{'values':[1]}})
        cachejson.write_text('{"nested":{"values":[3]}}')
        check("json_cache_uses_actual_bytes_not_mtime_or_path",rules.load_json(cachejson)=={'nested':{'values':[3]}})
    cached_result=resolve(baseline);cached_result['assembly_summary']['height_m']=99;cached_result['selected_catalog_row']['household_owned_zones'].append('polluted-cache')
    clean_result=resolve(baseline)
    check("assembly_cache_returns_independent_mutable_views",clean_result['eligible'] and abs(clean_result['assembly_summary']['height_m']-2.8499950850289983)<1e-12 and 'polluted-cache' not in clean_result['selected_catalog_row']['household_owned_zones'])
    parsed = rules.parse_idf('! comment\nConstruction,"a,!;name", M; ! trailing\n')
    check("idf_quoted_delimiters_and_comments_preserved",parsed==[["Construction","a,!;name","M"]])
    try: rules.parse_idf('Construction,"broken,M;'); rejected=False
    except ValueError: rejected=True
    check("incomplete_idf_quote_rejected",rejected)
    rows = rules.parse_idf(Path(original["parent_idf_path"]).read_text())
    owned = original["household_owned_zones"]
    bad = deepcopy(rows)
    for row in bad:
        if row[0].casefold()=="zone" and row[1]==owned[0]: row[9] = str(float(row[10])*4)
    try: rules.inspect_assemblies(bad,owned); rejected=False
    except ValueError: rejected=True
    check("actual_selected_zone_height_disagreement_rejected",rejected)
    bad = deepcopy(rows)
    for row in bad:
        if row[0].casefold()=="construction" and row[1]==explicit["assembly_summary"]["constructions"]["internal_wall"]: row[2]="nonexistent-material"
    try: rules.inspect_assemblies(bad,owned); rejected=False
    except ValueError: rejected=True
    check("actual_construction_missing_layer_rejected",rejected)
    check("material_numeric_spelling_normalized",rules._physical_fields(["Material","one","Smooth","0.010","1.0"])==rules._physical_fields(["Material","two","smooth","1e-2","1"]))
    try: rules._physical_fields(["Material","huge","Smooth","1e999"]); rejected=False
    except ValueError: rejected=True
    check("material_overflow_token_rejected",rejected)
    # Produce an actual non-palindromic ordered wall construction in memory.
    bad = deepcopy(rows)
    iw = explicit["assembly_summary"]["constructions"]["internal_wall"]
    wall = next(row for row in bad if row[0].casefold()=="construction" and row[1]==iw)
    first = next(row for row in bad if row[0].casefold() in rules.MATERIAL_TYPES and row[1]==wall[2])
    copy_material = first.copy(); copy_material[1] = "DIRECTED_ASYMMETRY_FIXTURE"
    if first[0].casefold()=="material": copy_material[3] = str(float(first[3])*1.1)
    else: raise ValueError("directed wall fixture expected Material object")
    bad.append(copy_material); wall[:] = wall[:2] + [first[1],copy_material[1]]
    observed = rules.inspect_assemblies(bad,owned)
    check("ordered_nonpalindromic_material_wall_diagnosed",not observed["internal_wall_symmetric"])

    passed = sum(c["passed"] for c in checks)
    result = {"schema_version":"eb.prototype_rules.verification.v2.1", "experiment_id":EXPERIMENT_ID, "repo":str(repo), "tested_code_sha256":rules.sha(HERE/"prototype_rules.py"), "verification_code_sha256":rules.sha(Path(__file__)), "registry_sha256":rules.sha(HERE/"PROTOTYPE_REGISTRY.json"), "summary":{"checks":len(checks),"passed":passed,"failed":len(checks)-passed}, "scope":"actual source-byte/closure/height registry and directed engineering admission tests; no annual runtime, topology adaptation, statistical population fit or measured calibration proof", "checks":checks, "positive_example_requests":examples}
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps(result["summary"],ensure_ascii=False))
    for c in checks:
        if not c["passed"]: print(json.dumps(c,ensure_ascii=False))
    return 0 if passed==len(checks) else 1


if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("--repo",type=Path,required=True);ap.add_argument("--out",type=Path,default=HERE/"PROTOTYPE_VERIFICATION.json");args=ap.parse_args()
    raise SystemExit(main(args.repo.resolve(),args.out))
