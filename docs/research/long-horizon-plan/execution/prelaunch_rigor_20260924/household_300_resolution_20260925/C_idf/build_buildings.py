#!/usr/bin/env python3
"""Materialize 300 explicitly synthetic DeST household IDFs from A's role contract.

The census-like H6 area remains a separate field. A declared experimental
factor maps it to modeled net area; common space is allocated by the official
shared-home counting rule. DeST source constructions/windows/adjacency remain.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
import math
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[6]
EVIDENCE = HERE.parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from scale_destep_highs_physics import VERTEX_COUNT, VERTEX_START, parse_idf  # noqa: E402
from ac_proxy import append_ac_proxy  # noqa: E402
from control_adapter import append_controls  # noqa: E402

FAMILY = HERE.parent / "A_structure/family_300.json"
STOCK = EVIDENCE / "building_stock_300_candidate_v1.json"
AUDIT = HERE / "source_unit_audit_300.json"
TERRACED = ROOT / "artifacts/private_research/dest_role_idfs_300_5room_terraced_alt_20260925"
OUTPUT = HERE / "idfs"
RATIO = 1/1.33  # inverse of NBS 2020 H6 fallback for usable -> building area; experimental here
RATIO_RANGE = [0.70, 0.85]
SHARED_RATIO = 0.95  # separate experimental morphology choice; H6 is an attributed share, not a whole flat
SHARED_RATIO_RANGE = [0.85, 1.0]
AIRBOUNDARY_ACH = 3.0


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def render(rows: list[list[str]], header: str) -> str:
    return header + "\n\n" + "\n\n".join(",\n  ".join(r) + ";" for r in rows) + "\n"


def role_mode(room: str, housing_form: str) -> str:
    if housing_form == "shared_dwelling_private_rooms_with_allocated_common_area" and room in ("one_room", "two_rooms"):
        return "shared_flat_private_rooms"
    if housing_form != "independent_dwelling":
        raise ValueError(f"unsupported family housing form and H7 rooms: {housing_form}/{room}")
    if room in ("one_room", "two_rooms"):
        return "self_contained_openplan"
    if room == "three_rooms":
        return "self_contained_source_three_room"
    if room == "four_rooms":
        return "self_contained_four_room_thermally_aggregated"
    if room == "five_or_more_rooms":
        return "terraced_five_room_inferred"
    raise ValueError(room)


def scale_geometry(rows: list[list[str]], factor: float) -> dict:
    if not math.isfinite(factor) or factor <= 0:
        raise ValueError("invalid XY scale")
    counts = Counter(r[0].lower() for r in rows)
    before = sum(float(r[10]) for r in rows if r[0].lower() == "zone")
    for row in rows:
        kind = row[0].lower()
        if kind == "zone":
            row[3] = f"{float(row[3])*factor:.9f}"
            row[4] = f"{float(row[4])*factor:.9f}"
            row[9] = f"{float(row[9])*factor*factor:.9f}"
            row[10] = f"{float(row[10])*factor*factor:.9f}"
        elif kind in VERTEX_START:
            first, n_at = VERTEX_START[kind], VERTEX_COUNT[kind]
            if len(row) != first + 3 * int(row[n_at]):
                raise ValueError(f"invalid source polygon: {row[1]}")
            for i in range(first, len(row), 3):
                row[i] = f"{float(row[i])*factor:.9f}"
                row[i+1] = f"{float(row[i+1])*factor:.9f}"
        elif "shading" in kind or kind == "internalmass":
            raise ValueError(f"unhandled geometric source object: {kind}")
    after = sum(float(r[10]) for r in rows if r[0].lower() == "zone")
    if not math.isclose(after, before*factor*factor, rel_tol=1e-9, abs_tol=1e-5):
        raise AssertionError("zone area scaling failed")
    if Counter(r[0].lower() for r in rows) != counts:
        raise AssertionError("source object inventory changed")
    return {"source_whole_model_zone_area_m2": round(before, 6),
            "scaled_whole_model_zone_area_m2": round(after, 6),
            "source_object_inventory": dict(counts)}


def source_selected_rows(rows: list[list[str]], zones: list[str]) -> dict[str, list[str]]:
    result = {r[1]: r for r in rows if r[0].lower() == "zone" and r[1] in zones}
    if set(result) != set(zones):
        raise ValueError("source household zone missing")
    return result


def airboundary(rows: list[list[str]], audit: dict, room: str, *,
                shared_private_studio: bool = False) -> dict:
    surfaces = {r[1]: r for r in rows if r[0].lower() == "buildingsurface:detailed"}
    windows = {r[4] for r in rows if r[0].lower() == "fenestrationsurface:detailed"}
    pairs = list(audit["openable_reciprocal_windowless_study_living_wall_pairs"])
    if room == "one_room" and not shared_private_studio:
        pairs += audit["openable_reciprocal_windowless_secondary_living_wall_pairs"]
    if not pairs:
        raise ValueError("no source-partition evidence for open plan")
    construction = "EB_Open_Plan_AirBoundary"
    rows.append(["Construction:AirBoundary", construction,
                 "SimpleMixing", f"{AIRBOUNDARY_ACH:g}", ""])
    changed = []
    for names in pairs:
        if len(names) != 2:
            raise ValueError("partition pair malformed")
        a, b = (surfaces[name] for name in names)
        if (a[7] != b[1] or b[7] != a[1] or a[1] in windows or b[1] in windows or
                a[6].lower() != "surface" or b[6].lower() != "surface"):
            raise ValueError("partition lost reciprocal/windowless property")
        a[3] = b[3] = construction
        changed.extend(names)
    return {"method": "replace_source_windowless_reciprocal_intra_home_partitions_with_air_boundary",
            "surface_names": sorted(changed), "pair_count": len(pairs),
            "mixing_ach": AIRBOUNDARY_ACH,
            "air_mixing_range_for_sensitivity_ach": [0.5, 5.0],
            "source_exterior_and_party_surfaces_changed": False,
            "evidence_identity": "experimental_openplan_derivative"}


def virtual_fourth_room(rows: list[list[str]], audit: dict) -> dict:
    functions = audit["source_room_functions"]
    living = next(z for z, f in functions.items() if f == "起居室")
    zone = source_selected_rows(rows, [living])[living]
    area = float(zone[10])
    height = float(zone[9]) / area
    new_room_area = area * 0.30
    residual_living_area = area - new_room_area
    wall_area_both_faces = 2 * height * math.sqrt(new_room_area)
    surfaces = [r for r in rows if r[0].lower() == "buildingsurface:detailed" and
                r[4] == living and r[6].lower() == "surface"]
    if not surfaces:
        raise ValueError("source living zone lacks interior construction")
    construction = surfaces[0][3]
    rows.append(["InternalMass", "EB_Inferred_Fourth_Room_Partition", construction,
                 living, "", f"{wall_area_both_faces:.9f}"])
    source_surfaces = {r[1] for r in rows if r[0].lower() == "buildingsurface:detailed" and r[4] == living}
    living_windows = sum(r[4] in source_surfaces for r in rows if r[0].lower() == "fenestrationsurface:detailed")
    return {"method": "source_living_zone_area_allocation_plus_two_sided_internal_wall_mass",
            "source_living_zone": living, "fourth_enclosed_room_design_area_m2": round(new_room_area, 6),
            "remaining_living_design_area_m2": round(residual_living_area, 6),
            "interior_partition_exposed_surface_m2": round(wall_area_both_faces, 6),
            "source_living_window_count": living_windows,
            "new_room_and_living_are_one_thermal_zone": True,
            "window_assignment_between_two_rooms": "not_resolved_by_lumped_thermal_zone",
            "evidence_identity": "experimental_space_allocation_and_thermal_aggregation"}


def bind_people(rows: list[list[str]], zones: list[str], family_size: int) -> dict:
    zone_rows = source_selected_rows(rows, zones)
    areas = {z: float(row[10]) for z, row in zone_rows.items()}
    total = sum(areas.values())
    people = [r for r in rows if r[0].lower() == "people" and r[2] in zones]
    if len(people) != len(zones) or {r[2] for r in people} != set(zones):
        raise ValueError("People objects not one-per-controlled-zone")
    for person in people:
        person[4:8] = ["People", f"{family_size*areas[person[2]]/total:.12f}", "", ""]
    actual = sum(float(r[5]) for r in people)
    if abs(actual-family_size) > 1e-8:
        raise AssertionError("bound occupant count differs from role")
    return {"role_people_nominal": round(actual, 9),
            "method": "selected_private_or_home_zones_area_proportional_nominal_people",
            "schedules": "source_DeST_not_observed_role_routines",
            "evidence_identity": "experimental_role_headcount_binding"}


def set_weather(rows: list[list[str]], epw: Path, expected_sha: str) -> dict:
    if digest(epw) != expected_sha:
        raise ValueError("EPW hash mismatch")
    loc = epw.open(encoding="utf-8").readline().strip().split(",")
    if len(loc) < 10 or loc[0] != "LOCATION" or loc[3] != "CHN":
        raise ValueError("not a recognized China EPW LOCATION line")
    sites = [r for r in rows if r[0].lower() == "site:location"]
    if len(sites) != 1:
        raise ValueError("source Site:Location count differs")
    sites[0][1:6] = ["EB_" + loc[1].replace(" ", "_"), *loc[6:10]]
    return {"station_name": loc[1], "latitude": float(loc[6]),
            "longitude": float(loc[7]), "timezone": float(loc[8]),
            "elevation_m": float(loc[9])}


def build_one(family: dict, stock: dict, audit: dict) -> tuple[str, dict]:
    role = family["role_id"]
    if (stock["role_id"] != role or audit["role_id"] != role or
            stock["home_city"] != family["location"]["city"] or
            audit["home_city"] != family["location"]["city"] or
            stock["household_size"] != family["family_size"]):
        raise ValueError("cross-team role, city, or size mismatch")
    h6 = float(family["dwelling"]["design_total_building_area_m2"])
    housing_form = family["dwelling"]["housing_form_design"]
    expected_area_basis = ("synthetic_H6_like_household_attributed_building_area_in_shared_dwelling"
                           if housing_form == "shared_dwelling_private_rooms_with_allocated_common_area" else
                           "synthetic_H6_like_whole_dwelling_building_area")
    if family["dwelling"]["area_basis"] != expected_area_basis:
        raise ValueError("unexpected A area semantic")
    room = family["dwelling"]["room_count_census_h7_category"]
    mode = role_mode(room, housing_form)
    if room == "five_or_more_rooms":
        base = TERRACED / f"{stock['virtual_building_id']}-terraced-alt.idf"
        base_manifest = json.loads(base.with_suffix(".manifest.json").read_text())
        if digest(base) != base_manifest["output_idf_sha256"] or base_manifest["role_id"] != role:
            raise ValueError("terraced parent identity/hash mismatch")
        unit_zones = base_manifest["selected_zones"]
        selected = unit_zones.copy()
        source_idf_sha = base_manifest["source_idf_sha256"]
        source_accdb_sha = base_manifest["source_accdb_sha256"]
        source_catalog = base_manifest["alternative_source_catalog_key"]
        source_branch = "existing_DeST_terraced_5plus_derivative"
        base_path = str(base)
        base_sha = digest(base)
        source_floor = "two_storey_terraced_inferred_unit"
        reported_source_path = str(ROOT / "artifacts/private_research/dest_terraced_5room_counterparts_20260925" /
                                   base_manifest["source_file_id"] /
                                   (base_manifest["source_file_id"] + "_projection_corrected.idf"))
        if digest(Path(reported_source_path)) != source_idf_sha:
            raise ValueError("terraced corrected source IDF hash mismatch")
    else:
        base = Path(audit["source_idf_path"])
        if digest(base) != audit["source_idf_sha256"]:
            raise ValueError("DeST source IDF hash mismatch")
        unit_zones = audit["selected_zones"]
        functions = audit["source_room_functions"]
        if mode == "shared_flat_private_rooms":
            # The one-room household exclusively uses the source master room.
            # Other function rooms can belong to co-resident households, and
            # the kitchen plus one bath are allocated equally across three.
            private_functions = (["主卧室"] if room == "one_room"
                                 else ["主卧室", "次卧室"])
            selected = [z for z in unit_zones if functions[z] in private_functions]
            if len(selected) != len(private_functions):
                raise ValueError("shared private-room function mismatch")
        else:
            selected = unit_zones.copy()
        source_idf_sha = audit["source_idf_sha256"]
        source_accdb_sha = audit["source_accdb_sha256"]
        source_catalog = audit["source_catalog_key"]
        source_branch = "verified_DeST_90zone_apartment"
        base_path = str(base)
        base_sha = digest(base)
        source_floor = stock["source_unit_floor"]
        reported_source_path = audit["source_idf_path"]
    rows = parse_idf(base.read_text())
    zone_rows = source_selected_rows(rows, unit_zones)
    unit_area = sum(float(z[10]) for z in zone_rows.values())
    if mode == "shared_flat_private_rooms":
        private = sum(float(zone_rows[z][10]) for z in selected)
        functions = audit["source_room_functions"]
        if room == "one_room":
            bathrooms = [z for z in unit_zones if functions[z] == "洗手间"]
            if len(bathrooms) != 2:
                raise ValueError("one-room co-living requires two source bathrooms")
            common_zones = [z for z in unit_zones if functions[z] == "厨房"] + bathrooms[:1]
        else:
            common_zones = [z for z in unit_zones if functions[z] in ("起居室", "厨房", "洗手间")]
        source_common = sum(float(zone_rows[z][10]) for z in common_zones)
        number_sharing = 3 if room == "one_room" else 2
        base_accounted = private + source_common / number_sharing
        area_rule = {"source_private_room_area_m2": round(private, 6),
                     "source_common_area_m2": round(source_common, 6),
                     "source_shared_common_zone_names": common_zones,
                     "other_source_zones_assigned_to_co_residents": sorted(set(unit_zones)-set(selected)-set(common_zones)),
                     "other_households_in_flat": number_sharing-1,
                     "shared_common_area_fraction": 1/number_sharing,
                     "h6_shared_area_rule": "private_rooms_plus_equal_share_of_declared_common_zones",
                     "official_definition": "NBS_2020_H6_shared_dwellings_equal_common_area_share"}
    else:
        base_accounted = unit_area
        area_rule = {"source_selected_full_unit_zone_area_m2": round(unit_area, 6),
                     "h6_shared_area_rule": None}
    area_ratio = SHARED_RATIO if mode == "shared_flat_private_rooms" else RATIO
    area_ratio_range = SHARED_RATIO_RANGE if mode == "shared_flat_private_rooms" else RATIO_RANGE
    target_net = area_ratio*h6
    factor = math.sqrt(target_net/base_accounted)
    geometry = scale_geometry(rows, factor)
    scaled_zones = source_selected_rows(rows, unit_zones)
    selected_net = sum(float(scaled_zones[z][10]) for z in selected)
    if mode == "shared_flat_private_rooms":
        common_scaled = area_rule["source_common_area_m2"]*factor*factor
        accounted = selected_net + common_scaled/(area_rule["other_households_in_flat"]+1)
    else:
        common_scaled = 0.0
        accounted = selected_net
    if not math.isclose(accounted, target_net, abs_tol=1e-5):
        raise AssertionError(f"H6-to-model area design mapping did not close: {role}")
    transform = None
    if mode == "self_contained_openplan":
        transform = airboundary(rows, audit, room)
    elif mode == "self_contained_four_room_thermally_aggregated":
        transform = virtual_fourth_room(rows, audit)
    elif mode == "terraced_five_room_inferred":
        transform = {"method": "four_source_bedrooms_plus_one_large_source_empty_room",
                     "evidence_identity": "matched_source_function_interpretation",
                     "small_empty_rooms_remain_unassigned_storage": 2,
                     "source_fifth_room_actual_function": "空房间"}
    people = bind_people(rows, selected, family["family_size"])
    weather = set_weather(rows, Path(audit["weather_epw_path"]), audit["weather_epw_sha256"])
    thermostat_zones = {r[2] for r in rows if r[0].lower() == "zonecontrol:thermostat"}
    ideal_names = {r[1] for r in rows if r[0].lower() == "zonehvac:idealloadsairsystem"}
    ac_zones = [z for z in selected if z in thermostat_zones and z + " Ideal Loads" in ideal_names]
    if not ac_zones:
        raise ValueError("no controllable household AC thermal zone")
    controls = append_controls(rows, ac_zones)
    ac = append_ac_proxy(rows, ac_zones)
    rows = [r for r in rows if r[0].lower() != "output:sqlite"]
    rows.append(["Output:SQLite", "SimpleAndTabular"])
    for z in selected:
        rows.append(["Output:Variable", z, "Zone Mean Air Temperature", "Hourly"])
        rows.append(["Output:Variable", z, "Zone People Occupant Count", "Hourly"])
        if z in ac_zones:
            rows.append(["Output:Variable", z + " Ideal Loads",
                         "Zone Ideal Loads Supply Air Total Cooling Energy", "Hourly"])
    runperiods = [r for r in rows if r[0].lower() == "runperiod"]
    if len(runperiods) != 1:
        raise ValueError("one RunPeriod required")
    runperiods[0][2:7] = ["7", "15", "", "7", "15"]
    header = (f"! Experimental DeST-derived household {role}; city {audit['home_city']}.\n"
              f"! Parent IDF SHA-256 {base_sha}; A H6-like building area {h6:.3f} m2.\n"
              f"! Model accounted net area ratio {area_ratio}; mode {mode}; XY scale {factor:.9f}.\n"
              "! AC electricity is EnergyPlus EMS IdealLoads / experimental COP; not equipment calibration.\n"
              "! DeST source schedules and nonselected zones are not observed household behavior.")
    body = render(rows, header)
    zone_window_hosts = {r[1]: r[4] for r in rows if r[0].lower() == "buildingsurface:detailed"}
    selected_windows = sum(zone_window_hosts.get(r[4]) in selected for r in rows
                           if r[0].lower() == "fenestrationsurface:detailed")
    constructions = Counter(r[3] for r in rows if r[0].lower() == "buildingsurface:detailed" and r[4] in selected)
    report = {
        "role_id": role, "virtual_building_id": stock["virtual_building_id"],
        "home_city": audit["home_city"], "home_province": stock["home_province"],
        "family_size": family["family_size"], "h7_room_category": room,
        "housing_mode": mode, "housing_mode_evidence": "experimental_rule_conditional_on_H7_and_H6_design_area",
        "h6_design_building_area_m2": h6, "h6_area_basis": expected_area_basis,
        "h6_area_evidence": family["dwelling"]["numeric_area_evidence"],
        "previous_frozen_room_category": stock["rooms_census_category"],
        "h6_to_net_conditioned_area_ratio": area_ratio,
        "ratio_evidence": ("experimental_shared_attributed_area_morphology_ratio_not_observed"
                           if mode == "shared_flat_private_rooms" else
                           "experimental_inverse_of_NBS_2020_H6_usable_area_to_building_area_fallback_1p33_not_household_observation"),
        "h6_to_net_ratio_sensitivity": area_ratio_range,
        "idf_household_accounted_net_area_m2": round(accounted, 6),
        "idf_selected_controlled_zone_area_m2": round(selected_net, 6),
        "idf_common_area_allocated_m2": round(common_scaled/(3 if room == "one_room" else 2) if
                                           mode == "shared_flat_private_rooms" else 0, 6),
        "area_rule": area_rule, "xy_scale": round(factor, 9),
        "source_selected_unit_zone_area_m2": round(unit_area, 6),
        "source_idf_path": reported_source_path, "source_idf_sha256": source_idf_sha,
        "source_accdb_sha256": source_accdb_sha, "source_catalog_key": source_catalog,
        "source_branch": source_branch, "parent_idf_path": base_path,
        "parent_idf_sha256": base_sha, "source_unit_floor": source_floor,
        "source_unit_group": stock["source_unit_group"],
        "source_unit_exposure": stock["source_unit_exposure"],
        "selected_unit_zones": unit_zones, "household_owned_zones": selected,
        "ac_controllable_zones": ac_zones,
        "owned_but_unconditioned_source_zones": sorted(set(selected)-set(ac_zones)),
        "selected_window_count": selected_windows,
        "selected_zone_surface_constructions": dict(constructions),
        "geometry_transform": transform, "geometry_summary": geometry,
        "occupancy_binding": people, "ac_meter": ac, "controls": controls,
        "weather_epw_path": audit["weather_epw_path"],
        "weather_epw_sha256": audit["weather_epw_sha256"],
        "weather_station_key": audit["weather_station"],
        "weather_home_city_distance_km": audit["weather_distance_km"],
        "site_location": weather,
        "idf_sha256": sha256(body.encode()).hexdigest(),
        "energyplus_version": "24.1.0",
        "default_runperiod": "July 15 one day; configurable by paired runner",
        "device_energy_ports": "EB_controller_injects_devices_later; no_source_default_appliance_assigned_to_role",
        "evidence_identity": "source_calibrated_envelope_weather_plus_experimental_geometry_and_HVAC_proxy",
        "physical_calibration": False, "human_response_observed": False,
    }
    return body, report


def build_all(*, write: bool = True) -> dict:
    families = json.loads(FAMILY.read_text())
    stock = json.loads(STOCK.read_text())
    audit = json.loads(AUDIT.read_text())
    if families["n"] != 300 or len(stock["records"]) != 300 or not audit["all_checks_pass"]:
        raise ValueError("incomplete A/DeST input")
    fs = {r["role_id"]: r for r in families["records"]}
    ss = {r["role_id"]: r for r in stock["records"]}
    aa = {r["role_id"]: r for r in audit["cases"]}
    expected = [f"cityrole-{i:04d}" for i in range(1, 301)]
    if any(sorted(d) != expected for d in (fs, ss, aa)):
        raise ValueError("role keys are not exactly 1..300")
    if write:
        OUTPUT.mkdir(exist_ok=True)
    records = []
    for role in expected:
        body, result = build_one(fs[role], ss[role], aa[role])
        output = OUTPUT / (role + ".idf")
        result["idf_path"] = str(output)
        if write:
            if output.exists():
                if digest(output) != result["idf_sha256"]:
                    raise FileExistsError(f"existing IDF changed: {output}")
            else:
                output.write_text(body)
        records.append(result)
    report = {"schema_version": "eb.building_300.dest.v1", "n": len(records),
              "family_sha256": digest(FAMILY), "source_stock_sha256": digest(STOCK),
              "source_unit_audit_sha256": digest(AUDIT),
              "mode_counts": dict(Counter(r["housing_mode"] for r in records)),
              "all_role_id_stable": True,
              "area_mapping_evidence": "independent_inverse_NBS_2020_H6_1p33_fallback_0.70_to_0.85;shared_experimental_0.95_sensitivity_0.85_to_1.0",
              "observed_dwelling_area_count": 0,
              "eb_device_injection_complete": False,
              "records": records}
    if write:
        (HERE / "building_300.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


if __name__ == "__main__":
    output = build_all(write="--dry-run" not in sys.argv)
    print(json.dumps({"n": output["n"], "mode_counts": output["mode_counts"],
                      "area_range_m2": [min(r["h6_design_building_area_m2"] for r in output["records"]),
                                        max(r["h6_design_building_area_m2"] for r in output["records"])],
                      "xy_scale_range": [min(r["xy_scale"] for r in output["records"]),
                                         max(r["xy_scale"] for r in output["records"])]},
                     ensure_ascii=False))
