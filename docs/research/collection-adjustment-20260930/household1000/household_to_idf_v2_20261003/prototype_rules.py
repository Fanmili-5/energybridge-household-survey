#!/usr/bin/env python3
"""Hash-bound assembly prototypes, without inheriting old household personas.

This is an engineering eligibility policy. A catalog label is not a measured
building locality/vintage, and admitted assembly transport is not calibration.
Only the independent single-storey-apartment writer is supported at present.
"""
from __future__ import annotations

import argparse
from collections import Counter, OrderedDict
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
import re
import statistics

HERE = Path(__file__).resolve().parent
_CODE_SHA_AT_IMPORT = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_CACHE_LIMIT = 8
_JSON_CACHE, _PARSE_CACHE, _ASSEMBLY_CACHE = OrderedDict(), OrderedDict(), OrderedDict()
FROZEN_LEGACY_REPO = Path("/Users/fanmili/studytest/energybridge-household-survey")
CATALOG_REL = "docs/research/long-horizon-plan/execution/prelaunch_rigor_20260924/household_300_resolution_20260925/v2_trial_20260926/C_idf/building_300.json"
CATALOG_SHA256 = "bb063fb494fd5d1ca8faaeafafab1444fe9f1fe6cd54b09ee5657e19dc957c0d"
WEATHER_CATALOG_REL = "simulation_resources/catalog.json"
SCHEMA = "eb.prototype_rules.v2.1"
USE_SCOPE = "assemblies_and_height_only"
TARGET_KEYS = ("geometry_family", "building_form", "construction_year", "city", "province", "feature_evidence")
FEATURE_KEYS = ("building_form", "construction_year", "city", "province")
MATERIAL_TYPES = {"material", "material:nomass", "material:airgap", "windowmaterial:simpleglazingsystem", "windowmaterial:glazing", "windowmaterial:gas"}
FORM_MAP = {"Low-rise apartment": "low_rise_apartment", "High-rise apartment(slab type)": "high_rise_slab_apartment", "Terraced house": "terraced_house"}
APARTMENT_BRANCH = "verified_DeST_90zone_apartment"
TERRACED_BRANCH = "existing_DeST_terraced_5plus_derivative"
DEFAULT_POLICY = {"mode": "feature_match", "use_scope": USE_SCOPE, "max_vintage_label_difference_years": 0, "require_symmetric_internal_wall": True}


def finite_tree(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("nonfinite_number")
    if isinstance(value, dict):
        for item in value.values(): finite_tree(item)
    elif isinstance(value, (list, tuple)):
        for item in value: finite_tree(item)


def canonical(value):
    finite_tree(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def load_json(path):
    raw = Path(path).read_bytes()
    key = (hashlib.sha256(raw).hexdigest(), _CODE_SHA_AT_IMPORT, "finite_json_v2.1")
    if key in _JSON_CACHE:
        _JSON_CACHE.move_to_end(key)
        return deepcopy(_JSON_CACHE[key])
    def bad(value): raise ValueError("nonfinite_json_constant:" + value)
    obj = json.loads(raw.decode("utf-8"), parse_constant=bad)
    finite_tree(obj)
    _JSON_CACHE[key] = deepcopy(obj)
    if len(_JSON_CACHE) > _CACHE_LIMIT: _JSON_CACHE.popitem(last=False)
    return obj


def _parsed_bytes(raw, actual_sha):
    key = (actual_sha, _CODE_SHA_AT_IMPORT, "idf_tokenizer_v2.1")
    if key not in _PARSE_CACHE:
        # Immutable cached rows; no caller can mutate another case's parser view.
        _PARSE_CACHE[key] = tuple(tuple(row) for row in parse_idf(raw.decode("utf-8")))
        if len(_PARSE_CACHE) > _CACHE_LIMIT: _PARSE_CACHE.popitem(last=False)
    else: _PARSE_CACHE.move_to_end(key)
    return [list(row) for row in _PARSE_CACHE[key]]


def _assembly_view(rows, actual_parent_sha, owned):
    key = (actual_parent_sha, _CODE_SHA_AT_IMPORT, "assembly_height_policy_v2.1", tuple(owned))
    if key not in _ASSEMBLY_CACHE:
        _ASSEMBLY_CACHE[key] = inspect_assemblies(rows, owned)
        if len(_ASSEMBLY_CACHE) > _CACHE_LIMIT: _ASSEMBLY_CACHE.popitem(last=False)
    else: _ASSEMBLY_CACHE.move_to_end(key)
    return deepcopy(_ASSEMBLY_CACHE[key])


def target_signature(target):
    """Bind authorization to the entire explicit target, including evidence."""
    if not isinstance(target, dict) or set(TARGET_KEYS) - set(target):
        raise ValueError("target_fields_missing")
    return fingerprint(target)


def source_group_id(source_sha256, parent_sha256):
    return "prototype_" + fingerprint({"source_sha256": source_sha256, "parent_sha256": parent_sha256})[:20]


def _path(repo, value):
    p = Path(value)
    if not p.is_absolute(): p = Path(repo) / p
    elif not p.is_relative_to(Path(repo).resolve()) and p.is_relative_to(FROZEN_LEGACY_REPO):
        # Only the known frozen catalog prefix is relocatable. Arbitrary
        # external paths never become implicit sources in a new checkout.
        p = Path(repo) / p.relative_to(FROZEN_LEGACY_REPO)
    p = p.resolve()
    if not p.is_relative_to(Path(repo).resolve()):
        raise ValueError("source_path_outside_repo")
    return p


def _relative(repo, value):
    return str(_path(repo, value).relative_to(Path(repo).resolve()))


def parse_idf(text):
    """Tokenize standard comma/semicolon IDF syntax with comments and quotes."""
    rows, row, field = [], [], []
    quoted = False
    comment = False
    i = 0
    while i < len(text):
        c = text[i]
        if comment:
            if c in "\r\n": comment = False; field.append(" ")
        elif c == '"':
            if quoted and i + 1 < len(text) and text[i + 1] == '"':
                field.append('"'); i += 1
            else: quoted = not quoted
        elif c == "!" and not quoted: comment = True
        elif c in ",;" and not quoted:
            row.append("".join(field).strip()); field = []
            if c == ";":
                if row[0]: rows.append(row)
                row = []
        else: field.append(c)
        i += 1
    if quoted or row or "".join(field).strip(): raise ValueError("incomplete_idf_object")
    return rows


def _number(value, positive=False):
    n = float(value)
    if not math.isfinite(n) or (positive and n <= 0): raise ValueError("invalid_source_number")
    return n


def _physical_fields(row):
    """Normalize numeric spelling; preserve layer sequence and material type."""
    out = [row[0].casefold()]
    for s in row[2:]:
        try:
            d = Decimal(s)
            if not d.is_finite() or not math.isfinite(float(d)): raise ValueError("nonfinite_material_number")
            out.append(str(d.normalize()))
        except InvalidOperation: out.append(s.casefold())
    return out


def _majority(values):
    c = Counter(values)
    if not c: raise ValueError("missing_required_assembly")
    return min(c, key=lambda k: (-c[k], k))


def inspect_assemblies(rows, owned):
    """Reproduce the assembly/height binder inputs, retaining all frequencies."""
    if not isinstance(owned, list) or not owned or len(owned) != len(set(owned)):
        raise ValueError("invalid_owned_zone_list")
    zset = set(owned)
    zones = [r for r in rows if r[0].casefold() == "zone" and r[1] in zset]
    if len(zones) != len(zset): raise ValueError("owned_zone_not_found_or_duplicate")
    heights = [_number(z[9], True) / _number(z[10], True) for z in zones]
    if max(heights) - min(heights) >= .01: raise ValueError("selected_zone_height_inconsistent")
    surfaces = [r for r in rows if r[0].casefold() == "buildingsurface:detailed" and r[4] in zset]
    names = {r[1] for r in surfaces}
    def constructions(kind, boundary=None):
        return [r[3] for r in surfaces if r[2].casefold() in kind and (boundary is None or r[6].casefold() == boundary)]
    external = constructions({"wall"}, "outdoors")
    internal = constructions({"wall"}, "surface")
    floor = constructions({"floor"}); ground = constructions({"floor"}, "ground")
    ceiling = constructions({"ceiling", "roof"}); selected_roof = constructions({"roof"}, "outdoors")
    windows = [r[3] for r in rows if r[0].casefold() == "fenestrationsurface:detailed" and r[4] in names]
    full_roof = [r[3] for r in rows if r[0].casefold() == "buildingsurface:detailed" and r[2].casefold() == "roof" and r[6].casefold() == "outdoors"]
    freq = {"external_wall": external, "internal_wall": internal, "floor": ground or floor, "ceiling": selected_roof or ceiling, "window": windows, "roof": full_roof}
    observed = {"external_wall": external, "internal_wall": internal, "all_floor": floor, "ground_floor": ground, "all_ceiling_or_roof": ceiling, "selected_unit_outdoor_roof": selected_roof, "window": windows, "full_parent_outdoor_roof": full_roof}
    chosen = {k: _majority(v) for k, v in freq.items()}
    # Construction/material namespaces are resolved separately, case insensitively.
    cons, mats = {}, {}
    for r in rows:
        typ = r[0].casefold()
        if typ == "construction": table = cons
        elif typ in MATERIAL_TYPES: table = mats
        else: continue
        key = r[1].casefold()
        if key in table: raise ValueError("duplicate_assembly_object_name:" + r[1])
        table[key] = r
    library_cons, library_mats, summaries = {}, {}, {}
    for name in sorted(set(n for values in observed.values() for n in values)):
        row = cons.get(name.casefold())
        if row is None: raise ValueError("construction_not_found:" + name)
        layers = [s for s in row[2:] if s]
        if not layers: raise ValueError("empty_construction:" + name)
        layer_info = []
        for layer in layers:
            material = mats.get(layer.casefold())
            if material is None: raise ValueError("material_not_found_or_unsupported:" + layer)
            phys = _physical_fields(material)
            library_mats[material[1]] = {"object_type": material[0], "fields": material[2:], "physical_fingerprint": fingerprint(phys)}
            layer_info.append({"name": material[1], "object_type": material[0], "physical_fingerprint": fingerprint(phys)})
        fprints = [x["physical_fingerprint"] for x in layer_info]
        summaries[name] = {"outside_to_inside_layers": layer_info, "physically_symmetric": fprints == list(reversed(fprints)), "ordered_layer_fingerprint": fingerprint(fprints)}
        library_cons[name] = {"object_type": row[0], "outside_to_inside_layers": layers}
    return {
        "height_m": statistics.median(heights), "selected_zone_heights_m": dict(zip([z[1] for z in zones], heights)),
        "selected_zone_height_range_m": max(heights)-min(heights), "height_tolerance_m": .01,
        "constructions": chosen, "construction_frequencies": {k: dict(sorted(Counter(v).items())) for k, v in freq.items()},
        "observed_construction_frequencies": {k: dict(sorted(Counter(v).items())) for k, v in observed.items()},
        "selection_rule": "highest_surface_object_count_then_lexical_construction_name; roof_from_full_parent",
        "frequency_basis": "surface_or_window_object_count_not_area_weighted",
        "construction_details": summaries, "material_library": {"constructions": library_cons, "materials": library_mats},
        "internal_wall_symmetric": summaries[chosen["internal_wall"]]["physically_symmetric"],
        "selected_source_ground_surface_count": len(ground), "selected_source_roof_surface_count": len(selected_roof),
        "topology_inherited": False, "operations_inherited": False, "equipment_inherited": False,
    }


def _site(rows):
    found = [r for r in rows if r[0].casefold() == "site:location"]
    if len(found) != 1: return {"status": "unknown", "reason": "site_location_not_unique"}
    r = found[0]
    try:
        return {"status": "source_numeric_metadata_unverified", "name": r[1], "latitude": _number(r[2]), "longitude": _number(r[3]), "timezone": _number(r[4]), "altitude_m": _number(r[5]), "not_used_as_weather_or_current_home_evidence": True}
    except (ValueError, IndexError): return {"status": "unknown", "reason": "site_location_invalid"}


def verify_catalog_row(row, repo, parse_cache=None):
    cache = {} if parse_cache is None else parse_cache
    out = {"passed": False, "reject_reasons": []}
    try:
        for field in ("source_idf_path", "parent_idf_path"):
            path = _path(repo, row[field]); expected = row[field.replace("_path", "_sha256")]
            raw = path.read_bytes()
            actual = hashlib.sha256(raw).hexdigest()
            out[field.replace("_path", "_verification")] = {"path": _relative(repo, path), "expected_sha256": expected, "actual_sha256": actual, "passed": actual == expected}
            if actual != expected: raise ValueError(field + "_hash_mismatch")
            if actual not in cache: cache[actual] = _parsed_bytes(raw, actual)
        rows = cache[row["parent_idf_sha256"]]
        summary = _assembly_view(rows, row["parent_idf_sha256"], row["household_owned_zones"])
        out.update({"passed": True, "assembly_summary": summary, "source_site_location": _site(cache[row["source_idf_sha256"]]), "parent_site_location": _site(rows), "source_energyplus_versions": [r[1] for r in cache[row["source_idf_sha256"]] if r[0].casefold() == "version"]})
    except (OSError, ValueError, KeyError, IndexError, TypeError, ZeroDivisionError) as exc:
        out["reject_reasons"].append(str(exc))
    return out


def _label_metadata(key, weather):
    parts = key.rsplit("_", 2)
    if len(parts) != 3 or parts[0] not in FORM_MAP or not parts[2].isdigit():
        return {"status": "unknown", "catalog_key": key}
    form, city, year = parts
    normalized = lambda x: re.sub("[^a-z0-9]", "", str(x).casefold())
    station_candidates = [w for w in weather if normalized(w.get("station_roman", w.get("station_name", ""))) == normalized(city)]
    provinces = sorted({w.get("province") for w in station_candidates if w.get("province")})
    # A station may belong to a larger admin city (Anda -> Suihua). Only add
    # a Chinese name when its actual romanization equals the source token.
    import pypinyin
    aliases = {city}
    alias_evidence = []
    if len(provinces) == 1:
        for w in station_candidates:
            chinese = w.get("city")
            if not chinese: continue
            roman = "".join(pypinyin.lazy_pinyin(chinese)).lower().replace("ü", "v")
            if normalized(roman) != normalized(city): continue
            aliases.add(chinese)
            alias_evidence.append({"catalog_weather_id": w["id"], "chinese_admin_city": chinese, "computed_city_roman": roman, "source_city_token": city, "tool": "pypinyin", "tool_version": pypinyin.__version__, "scope": "same_label_translation_not_observed_building_locality"})
    return {"status": "catalog_labels_only", "building_form": FORM_MAP[form], "catalog_city_token": city, "catalog_vintage_year": int(year), "vintage_semantics": "model_label_not_observed_construction_year", "city_semantics": "source_catalog_token_not_measured_household_location", "city_aliases": sorted(aliases), "city_alias_evidence": alias_evidence, "province_label": provinces[0] if len(provinces) == 1 else None, "province_mapping_semantics": "unique_same_station_roman_label_in_weather_catalog_not_building_geocoding", "weather_geography_candidates": [{"id": w["id"], "province": w.get("province"), "admin_city": w.get("city"), "station_roman": w.get("station_roman", w.get("station_name"))} for w in station_candidates]}


def _sanitized_row(row, repo):
    allowed = ("role_id", "source_catalog_key", "source_branch", "source_idf_path", "source_idf_sha256", "parent_idf_path", "parent_idf_sha256", "source_accdb_sha256", "source_unit_floor", "source_unit_group", "source_unit_exposure", "household_owned_zones")
    out = {k: row.get(k) for k in allowed}
    for k in ("source_idf_path", "parent_idf_path"): out[k] = _relative(repo, out[k])
    return out


def build_registry(repo):
    repo = Path(repo).resolve()
    catalog_path = repo / CATALOG_REL
    if sha(catalog_path) != CATALOG_SHA256: raise ValueError("frozen_catalog_hash_mismatch")
    data = load_json(catalog_path); weather_path = repo / WEATHER_CATALOG_REL
    weather = load_json(weather_path)["weather"]
    groups, cache = {}, {}
    for row in sorted(data["records"], key=lambda r: r["role_id"]):
        gid = source_group_id(row["source_idf_sha256"], row["parent_idf_sha256"])
        if gid not in groups:
            verification = verify_catalog_row(row, repo, cache)
            source_path = _path(repo, row["source_idf_path"])
            manifest_path = source_path.parent / "manifest.json"
            manifest = load_json(manifest_path) if manifest_path.exists() else None
            groups[gid] = {"source_group_id": gid, "source_catalog_key": row["source_catalog_key"], "source_branch": row["source_branch"], "source_idf_path": _relative(repo, row["source_idf_path"]), "source_idf_sha256": row["source_idf_sha256"], "parent_idf_path": _relative(repo, row["parent_idf_path"]), "parent_idf_sha256": row["parent_idf_sha256"], "source_metadata": _label_metadata(row["source_catalog_key"], weather), "source_site_location": verification.get("source_site_location"), "source_energyplus_versions": verification.get("source_energyplus_versions"), "source_manifest": {"path": _relative(repo, manifest_path), "sha256": sha(manifest_path), "content": manifest} if manifest else {"status": "unknown"}, "measured_locality_verified": False, "physical_calibration_verified": False, "redistribution_permission_verified": False, "variants": []}
        verification = verify_catalog_row(row, repo, cache)
        groups[gid]["variants"].append({"role_key": row["role_id"], "selected_catalog_row": _sanitized_row(row, repo), "source_verification": {k: v for k, v in verification.items() if k != "assembly_summary"}, "assembly_summary": verification.get("assembly_summary"), "assembly_fingerprint": fingerprint(verification.get("assembly_summary"))})
    for group in groups.values():
        group["representative_role_key"] = group["variants"][0]["role_key"]
        group["role_alias_count"] = len(group["variants"])
        group["verified_variant_count"] = sum(v["source_verification"]["passed"] for v in group["variants"])
    counts = Counter(g["source_branch"] for g in groups.values())
    return {"schema_version": SCHEMA, "catalog": {"path": CATALOG_REL, "sha256": CATALOG_SHA256}, "weather_geography_lookup": {"path": WEATHER_CATALOG_REL, "sha256": sha(weather_path), "scope": "metadata relation only; no weather quality or local building verification"}, "source_group_rule": "ordered_pair(source_idf_sha256,parent_idf_sha256); not role count; not proof of independent measured buildings", "summary": {"catalog_role_keys": len(data["records"]), "source_groups": len(groups), "source_files": len({g['source_idf_sha256'] for g in groups.values()}), "parent_files": len({g['parent_idf_sha256'] for g in groups.values()}), "branch_group_counts": dict(counts), "verified_variants": sum(g["verified_variant_count"] for g in groups.values()), "asymmetric_internal_wall_variants": sum(not v["assembly_summary"]["internal_wall_symmetric"] for g in groups.values() for v in g["variants"] if v["assembly_summary"])}, "groups": dict(sorted(groups.items())), "default_policy": DEFAULT_POLICY, "scientific_scope": "hash-verified engineering assembly/height sources; no Chinese population representation, household-specific calibration or inherited topology"}


def group_from_key(key, registry=None):
    """Map role alias, unique catalog label or group id to one source group."""
    if not isinstance(key, str) or not key.strip(): raise ValueError("prototype_key_invalid")
    registry = load_json(HERE / "PROTOTYPE_REGISTRY.json") if registry is None else registry
    groups = registry["groups"]
    if key in groups: return key
    hits = [gid for gid, g in groups.items() if key == g["source_catalog_key"] or any(v["role_key"] == key for v in g["variants"])]
    if len(hits) != 1: raise ValueError("prototype_key_unknown_or_ambiguous")
    return hits[0]


def _normalize_label(value):
    if not isinstance(value, str): return value
    value = value.strip().casefold()
    # Chinese province suffixes are formatting only; never city/admin remapping.
    if value.endswith("省") or value.endswith("市"): value = value[:-1]
    return value


def _feature_evidence_ok(e):
    return isinstance(e, dict) and isinstance(e.get("kind"), str) and bool(e["kind"].strip()) and isinstance(e.get("evidence_id"), str) and bool(e["evidence_id"].strip())


def _bound_evidence(evidence, kind, gid, signature, list_key, actual):
    if not isinstance(evidence, dict): return [kind + "_evidence_missing"]
    errors = []
    bindings = {"kind": kind, "source_group_id": gid, "target_signature": signature, "use_scope": USE_SCOPE}
    for k, value in bindings.items():
        if evidence.get(k) != value: errors.append(kind + "_" + k + "_mismatch")
    for k in ("evidence_id", "rationale"):
        if not isinstance(evidence.get(k), str) or not evidence[k].strip(): errors.append(kind + "_" + k + "_missing")
    allowed = evidence.get(list_key)
    if not isinstance(allowed, list) or any(not isinstance(x, str) for x in allowed) or len(allowed) != len(set(allowed)) or set(allowed) != set(actual):
        errors.append(kind + "_" + list_key + "_must_exactly_cover_actual_axes")
    return errors


def _evaluate(gid, group, variant, target, policy, signature):
    meta = group["source_metadata"]
    reasons, unknown, mismatch = [], [], []
    for feature in FEATURE_KEYS:
        value = target[feature]
        if value is None: unknown.append("target." + feature)
        elif not _feature_evidence_ok(target["feature_evidence"].get(feature)):
            reasons.append("target_feature_evidence_missing:" + feature)
    if meta.get("status") != "catalog_labels_only": reasons.append("source_label_metadata_unknown")
    if target["building_form"] is not None and target["building_form"] != meta.get("building_form"): mismatch.append("building_form")
    difference = None
    if target["construction_year"] is not None:
        difference = abs(target["construction_year"] - meta.get("catalog_vintage_year", target["construction_year"]))
        if difference > policy["max_vintage_label_difference_years"]: mismatch.append("construction_year")
    if target["city"] is not None and _normalize_label(target["city"]) not in {_normalize_label(c) for c in meta.get("city_aliases", [])}: mismatch.append("city")
    if meta.get("province_label") is None: unknown.append("source.province_label")
    elif target["province"] is not None and _normalize_label(target["province"]) != _normalize_label(meta["province_label"]): mismatch.append("province")
    if group["source_branch"] == TERRACED_BRANCH: mismatch.append("source_branch")
    elif group["source_branch"] != APARTMENT_BRANCH: reasons.append("unsupported_source_branch")
    if target["building_form"] == "terraced_house": reasons.append("target_form_not_supported_by_single_storey_apartment_writer")
    if unknown:
        if policy["mode"] not in ("declared_design", "transport"): reasons.extend("unknown_feature:" + u for u in unknown)
        else: reasons.extend(_bound_evidence(policy.get("design_evidence"), "conditional_template_design", gid, signature, "accepted_unknown_features", unknown))
    elif policy["mode"] == "declared_design":
        reasons.extend(_bound_evidence(policy.get("design_evidence"), "conditional_template_design", gid, signature, "accepted_unknown_features", []))
    if mismatch:
        reasons.extend(_bound_evidence(policy.get("transport_evidence"), "engineering_transport_design", gid, signature, "allowed_mismatches", mismatch))
    elif policy["mode"] == "transport":
        reasons.extend(_bound_evidence(policy.get("transport_evidence"), "engineering_transport_design", gid, signature, "allowed_mismatches", []))
    if not variant["source_verification"]["passed"]: reasons.extend("source_verification:" + r for r in variant["source_verification"]["reject_reasons"])
    summary = variant.get("assembly_summary")
    if summary and policy["require_symmetric_internal_wall"] and not summary["internal_wall_symmetric"]: reasons.append("asymmetric_internal_wall_not_supported_by_current_writer")
    # Exact known labels outrank unknown/transported features; height is not used
    # to invent a target requirement. Role-alias frequency never changes ranking.
    score = [len(mismatch), len(unknown), difference if difference is not None else 10000]
    return {"source_group_id": gid, "role_key": variant["role_key"], "eligible": not reasons, "rank_score": score, "mismatch_axes": sorted(mismatch), "unknown_features": sorted(unknown), "reject_reasons": sorted(set(reasons)), "vintage_label_difference_years": difference}


def describe_target_conditions(prototype_key, target, registry=None, max_vintage_label_difference_years=0):
    """Expose exact unknown/mismatch axes for an explicit experiment author.

    This diagnostic makes no admission and creates no permission/evidence.
    """
    registry = load_json(HERE / "PROTOTYPE_REGISTRY.json") if registry is None else registry
    gid = group_from_key(prototype_key, registry)
    group = registry["groups"][gid]
    variant = next((v for v in group["variants"] if v["role_key"] == prototype_key), group["variants"][0])
    signature = target_signature(target)
    item = _evaluate(gid, group, variant, target, DEFAULT_POLICY | {"max_vintage_label_difference_years": max_vintage_label_difference_years}, signature)
    return {"source_group_id": gid, "target_signature": signature, "unknown_features": item["unknown_features"], "mismatch_axes": item["mismatch_axes"], "source_metadata": group["source_metadata"], "authorization_created": False}


def resolve_prototype(request, repo, registry=None):
    """Return eligibility, selected sanitized row, complete ranking and reasons.

    A supplied prototype_key is still checked against the frozen catalog and
    current source bytes. No request/evidence is fabricated by this function.
    """
    result = {"schema_version": SCHEMA, "eligible": False, "status": "rejected", "selected_catalog_row": None, "selected_group_id": None, "selected_role_key": None, "source_verification": None, "assembly_summary": None, "ranking": [], "reject_reasons": [], "geometry_compatibility_certified": False, "topology_inherited": False, "physical_calibration_verified": False}
    try:
        finite_tree(request)
        if not isinstance(request, dict): raise ValueError("prototype_request_must_be_object")
        target = request.get("target")
        signature = target_signature(target)
        result["target_signature"] = signature
        if target["geometry_family"] != "single_storey_apartment": raise ValueError("unsupported_target_geometry_family")
        if not isinstance(target["feature_evidence"], dict): raise ValueError("feature_evidence_must_be_object")
        if target["building_form"] not in (*FORM_MAP.values(), None): raise ValueError("target_building_form_invalid")
        year = target["construction_year"]
        if year is not None and (isinstance(year, bool) or not isinstance(year, int) or not 1800 <= year <= 2200): raise ValueError("target_construction_year_invalid")
        for name in ("city", "province"):
            if target[name] is not None and (not isinstance(target[name], str) or not target[name].strip()): raise ValueError("target_" + name + "_invalid")
        if not isinstance(request.get("policy"), dict): raise ValueError("prototype_policy_missing")
        policy = DEFAULT_POLICY | request["policy"]
        if policy["mode"] not in ("feature_match", "declared_design", "transport"): raise ValueError("unknown_prototype_mode")
        if policy["use_scope"] != USE_SCOPE: raise ValueError("unsupported_use_scope")
        delta = policy["max_vintage_label_difference_years"]
        if isinstance(delta, bool) or not isinstance(delta, int) or delta < 0: raise ValueError("vintage_difference_policy_invalid")
        # This cannot be relaxed until the writer emits reversed paired walls.
        if policy["require_symmetric_internal_wall"] is not True: raise ValueError("symmetric_wall_policy_cannot_be_disabled_for_current_writer")
        repo = Path(repo).resolve(); current_catalog = repo / CATALOG_REL
        if sha(current_catalog) != CATALOG_SHA256: raise ValueError("frozen_catalog_hash_mismatch")
        catalog_rows = {r["role_id"]: r for r in load_json(current_catalog)["records"]}
        registry = load_json(HERE / "PROTOTYPE_REGISTRY.json") if registry is None else registry
        if registry.get("schema_version") != SCHEMA or registry.get("catalog", {}).get("sha256") != CATALOG_SHA256: raise ValueError("registry_catalog_binding_mismatch")
        groups = registry["groups"]
        weather_path = repo / WEATHER_CATALOG_REL
        if sha(weather_path) != registry.get("weather_geography_lookup", {}).get("sha256"):
            raise ValueError("registry_geographic_lookup_hash_mismatch")
        weather_rows = load_json(weather_path)["weather"]
        if request.get("prototype_key") is not None:
            key = request["prototype_key"]
            if not isinstance(key, str) or not key.strip(): raise ValueError("prototype_key_invalid")
            gids = [group_from_key(key, registry)]
        else:
            if policy["mode"] != "feature_match": raise ValueError("explicit_source_key_required_for_design_or_transport")
            gids = sorted(groups)
            key = None
        evaluated = []
        for gid in gids:
            group = groups[gid]
            variant = next((v for v in group["variants"] if v["role_key"] == key), group["variants"][0])
            if gid != source_group_id(group["source_idf_sha256"], group["parent_idf_sha256"]): raise ValueError("registry_source_group_fingerprint_mismatch")
            row = catalog_rows.get(variant["role_key"])
            if row is None or _sanitized_row(row, repo) != variant["selected_catalog_row"]: raise ValueError("registry_variant_catalog_row_mismatch")
            if source_group_id(row["source_idf_sha256"], row["parent_idf_sha256"]) != gid: raise ValueError("registry_variant_source_group_mismatch")
            if group["source_catalog_key"] != row["source_catalog_key"] or group["source_branch"] != row["source_branch"] or group["source_metadata"] != _label_metadata(row["source_catalog_key"], weather_rows):
                raise ValueError("registry_source_metadata_mismatch")
            item = _evaluate(gid, group, variant, target, policy, signature)
            evaluated.append((item, group, variant, row))
        evaluated.sort(key=lambda t: (not t[0]["eligible"], t[0]["rank_score"], t[0]["source_group_id"], t[0]["role_key"]))
        result["ranking"] = [x[0] for x in evaluated]
        candidates = [x for x in evaluated if x[0]["eligible"]]
        if not candidates:
            result["reject_reasons"] = sorted(set(r for x in evaluated for r in x[0]["reject_reasons"])) or ["no_eligible_prototype"]
            return result
        chosen, group, variant, row = candidates[0]
        # Always recompute closure, frequency choices, height and symmetry from
        # selected actual bytes; a modified cached summary cannot bypass gates.
        verification = verify_catalog_row(row, repo)
        if not verification["passed"]:
            result["source_verification"] = verification
            result["reject_reasons"] = ["current_source_verification:" + r for r in verification["reject_reasons"]]
            return result
        summary = verification.pop("assembly_summary")
        if fingerprint(summary) != variant["assembly_fingerprint"] or summary != variant["assembly_summary"]: raise ValueError("registry_assembly_summary_mismatch")
        if not summary["internal_wall_symmetric"]: raise ValueError("asymmetric_internal_wall_not_supported_by_current_writer")
        rank = chosen["rank_score"]
        tied = [x[0]["source_group_id"] for x in candidates if x[0]["rank_score"] == rank]
        sanitized = _sanitized_row(row, repo)
        for pathkey in ("source_idf_path", "parent_idf_path"): sanitized[pathkey] = str(_path(repo, sanitized[pathkey]))
        status = "transport_design_admitted" if chosen["mismatch_axes"] or policy["mode"] == "transport" else "conditional_design_admitted" if policy["mode"] == "declared_design" or chosen["unknown_features"] else "catalog_feature_candidate_admitted"
        result.update({"eligible": True, "status": status, "selected_catalog_row": sanitized, "selected_group_id": chosen["source_group_id"], "selected_role_key": chosen["role_key"], "source_verification": verification, "assembly_summary": summary, "source_metadata": group["source_metadata"], "mismatch_axes": chosen["mismatch_axes"], "unknown_features": chosen["unknown_features"], "tie_group_ids": tied, "tie_rule": "lexical_source_group_id_then_role_key_after_equal_feature_score", "tie_present": len(tied) > 1, "use_scope": USE_SCOPE, "match_basis": "engineering_catalog_label_eligibility_not_measured_housing_fit", "prototype_request": request})
    except (ValueError, KeyError, TypeError, OSError, IndexError) as exc:
        result["reject_reasons"] = sorted(set(result["reject_reasons"] + [str(exc)]))
    return result


def transport_admission(request, repo, registry=None):
    """Same gate with explicit transport mode; never grants authorization."""
    if not isinstance(request, dict) or not isinstance(request.get("policy"), dict) or request["policy"].get("mode") != "transport":
        return {"eligible": False, "status": "rejected", "reject_reasons": ["transport_mode_required"]}
    return resolve_prototype(request, repo, registry)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, required=True)
    ap.add_argument("--build-registry", action="store_true")
    ap.add_argument("--request", type=Path)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    if args.build_registry: out = build_registry(args.repo)
    elif args.request: out = resolve_prototype(load_json(args.request), args.repo)
    else: ap.error("choose --build-registry or --request")
    encoded = json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.out: args.out.write_text(encoded, encoding="utf-8")
    else: print(encoded, end="")


if __name__ == "__main__": main()
