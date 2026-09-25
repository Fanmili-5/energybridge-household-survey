#!/usr/bin/env python3
"""Materialize the frozen 300 synthetic family structures.

The census bins are source-calibrated quotas. Pairing, exact ages and square
metres are transparent design choices, never observed household microdata.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from bisect import bisect_right
import hashlib
import json
from pathlib import Path
import statistics
import sys

import pandas as pd

HERE = Path(__file__).resolve().parent
PARENT = HERE.parent.parent
COHORT = PARENT / "collection_cohort_300_design_v1.json"
CITY = PARENT / "city_housing_300_joint_candidate_v4_independent_city.json"
PAIR = PARENT / "area_room_coupling_300_sensitivity_v2.json"
GATE = PARENT / "AREA_EVIDENCE_GATE_300_20260925.json"
RANK = PARENT / "area_rank_transport_300_candidate_v3.json"
OUT = HERE / "family_300.json"
AUDIT = HERE / "distribution_and_anomalies.json"
ROOMS = {"one_room": 1, "two_rooms": 2, "three_rooms": 3,
         "four_rooms": 4, "five_or_more_rooms": 5}
# Two original size×one-room cells had no CHNS urban sample cell with n>=10.
# Exchange H7 categories within the same province×generation quota to make
# the families roleplayable without changing any published marginal quota.
ROOM_REPAIRS = (("cityrole-0024", "cityrole-0267"),
                ("cityrole-0140", "cityrole-0089"))
BANDS = {"0_17": (0, 17), "18_29": (18, 29), "20_59": (20, 59),
         "30_49": (30, 49), "35_59": (35, 59), "50_59": (50, 59),
         "20_34": (20, 34), "18_59": (18, 59), "0_59": (0, 59),
         "60_64": (60, 64), "65_79": (65, 79), "80_plus": (80, 95)}
sys.path.insert(0, str(PARENT))
from couple_area_rooms_300_sensitivity import minimum_cost_assignment  # noqa: E402
from audit_chns_2015_joint_probe import FILES as CHNS_FILES, RAW as CHNS_RAW, md5 as chns_md5, prepare as chns_prepare  # noqa: E402
from build_area_rank_transport_300_candidate import SEED as RANK_SEED  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def draw(role_id: str, label: str, low: int, high: int) -> int:
    h = hashlib.sha256(f"family300-v1:{role_id}:{label}".encode()).digest()
    return low + int.from_bytes(h[:8], "big") % (high - low + 1)


def area_per_person(label: str) -> float:
    if label == "8及以下":
        return 8.0  # boundary scenario, not an estimated bin mean
    if label == "70及以上":
        return 75.0  # declared open-tail design point, not a census estimate
    a, b = map(int, label.split("-"))
    return (a + b) / 2


def member(source: dict, age: int, relationship: str, index: int) -> dict:
    lo, hi = BANDS[source["age_band"]]
    if not lo <= age <= hi:
        raise ValueError(f"age outside source band: {source} -> {age}")
    return {"member_id": f"m{index:02}", "relationship_to_reference_adult": relationship,
            "age_years_design": age, "source_age_band": source["age_band"],
            "source_role_template": source["role"],
            "age_band_evidence": source["age_evidence"],
            "age_years_evidence": "experimental_constrained_age_for_roleplay",
            "relationship_evidence": "experimental_family_template"}


def make_people(role_id: str, hh: dict) -> list[dict]:
    src = hh["members"]
    roles = [m["role"] for m in src]
    gen = hh["generation_category"]
    result = []
    if len(src) == 1:
        band = src[0]["age_band"]
        lo, hi = BANDS[band]
        age = draw(role_id, "single", lo, min(hi, 88))
        return [member(src[0], age, "reference_adult", 1)]
    if gen == 1:
        if roles[0] == "older_spouse_1":
            lo, hi = BANDS[src[0]["age_band"]]
            a = draw(role_id, "older_spouse", lo, min(hi, 88))
            b = max(lo, min(hi, a + draw(role_id, "spouse_gap", -3, 3)))
            return [member(src[0], a, "reference_adult", 1),
                    member(src[1], b, "spouse", 2)]
        base = draw(role_id, "same_generation", 29, 47)
        for i, s in enumerate(src):
            age = base if i == 0 else base + draw(role_id, f"same_gen_{i}", -5, 5)
            result.append(member(s, age, "reference_adult" if i == 0 else
                                 ("spouse" if i == 1 else "sibling"), i + 1))
        return result
    if gen == 2:
        elder = roles[0] == "older_parent"
        adult_child = roles[1] == "adult_child"
        if elder:
            lo, hi = BANDS[src[0]["age_band"]]
            parent_age = draw(role_id, "elder", lo, min(hi, 87))
            child_age = max(20, min(59, parent_age - draw(role_id, "elder_gap", 25, 33)))
        elif adult_child:
            parent_age = draw(role_id, "parent_adult_child", 51, 58)
            child_age = draw(role_id, "adult_child", 19, 28)
        else:
            parent_age = draw(role_id, "parent_minor_child", 36, 50)
            child_age = draw(role_id, "minor_child", 5, min(17, parent_age - 19))
        result = [member(src[0], parent_age, "reference_adult", 1),
                  member(src[1], child_age, "child", 2)]
        for i, s in enumerate(src[2:], 3):
            if s["role"] in ("adult_child_or_partner", "adult_relative"):
                age = max(20 if elder else 18, min(59, child_age + draw(role_id, f"extra_{i}", -3, 4)))
                relationship = "spouse_of_child" if i == 4 else "child"
            elif s["role"] == "parent_or_child":
                if i % 2:
                    age = min(59, parent_age + draw(role_id, f"extra_{i}", -4, 4))
                    relationship = "spouse"
                else:
                    age = max(0, min(17, child_age + draw(role_id, f"extra_{i}", -4, 4)))
                    relationship = "child"
            else:
                raise ValueError((role_id, s))
            result.append(member(s, age, relationship, i))
        return result
    if gen == 3:
        adult_child = src[2]["age_band"] == "18_29"
        child_age = draw(role_id, "three_gen_child", 18, 20) if adult_child else draw(role_id, "three_gen_child", 7, 13)
        parent_age = draw(role_id, "three_gen_parent", max(34, child_age + 19), 40)
        grand_band = src[0]["age_band"]
        lo, hi = BANDS[grand_band]
        grand_age = draw(role_id, "three_gen_grand", max(lo, parent_age + 18), min(hi, 88))
        result = [member(src[0], grand_age, "parent_of_reference_adult", 1),
                  member(src[1], parent_age, "reference_adult", 2),
                  member(src[2], child_age, "child", 3)]
        for i, s in enumerate(src[3:], 4):
            if s["role"] == "additional_child":
                age = max(0, min(17, child_age + draw(role_id, f"extra_{i}", -5, 0)))
                relationship = "child"
            else:
                age = max(30, min(49, parent_age + draw(role_id, f"extra_{i}", -4, 4)))
                relationship = "spouse" if not any(m["relationship_to_reference_adult"] == "spouse" for m in result) else "sibling"
                if relationship == "sibling":
                    age = min(age, grand_age - 18)
            result.append(member(s, age, relationship, i))
        return result
    raise ValueError((role_id, gen))


def link_people(people: list[dict], generations: int) -> None:
    by_id = {m["member_id"]: m for m in people}
    for m in people:
        m["parent_member_ids"] = []
        m["partner_member_id"] = None
    if generations == 3:
        by_id["m02"]["parent_member_ids"] = ["m01"]
    for m in people:
        rel = m["relationship_to_reference_adult"]
        if rel == "child":
            m["parent_member_ids"] = ["m02" if generations == 3 else "m01"]
        elif rel == "sibling" and generations == 3:
            m["parent_member_ids"] = ["m01"]
        elif rel == "spouse":
            reference_id = "m02" if generations == 3 else "m01"
            m["partner_member_id"] = reference_id
            by_id[reference_id]["partner_member_id"] = m["member_id"]
        elif rel == "spouse_of_child":
            m["partner_member_id"] = "m02"
            by_id["m02"]["partner_member_id"] = m["member_id"]


def recompute_room_swap_ranks(rank_rows: list[dict], selected_room: dict[str, str]) -> tuple[list[dict], dict]:
    """Recompute the four changed size×room conditional ranks from raw CHNS."""
    changed = [r for r in rank_rows if r["rooms_census_category"] != selected_room[r["role_id"]]]
    if len(changed) != 4:
        raise ValueError(f"expected four room-swapped roles, got {len(changed)}")
    for filename, expected in CHNS_FILES.items():
        if chns_md5(CHNS_RAW / filename) != expected:
            raise ValueError(f"CHNS raw hash changed: {filename}")
    usable, _ = chns_prepare(pd.read_sas(CHNS_RAW / "asset_12.sas7bdat"),
                             pd.read_sas(CHNS_RAW / "rst_12.sas7bdat"))
    if len(usable) != 2198:
        raise ValueError("CHNS selected household count changed")
    usable = usable.copy()
    usable["per_capita_usable_m2"] = usable.L16 / usable.resident_count
    all_values = sorted(float(x) for x in usable.per_capita_usable_m2)
    room_group = {"one_room": "1", "two_rooms": "2", "three_rooms": "3",
                  "four_rooms": "4", "five_or_more_rooms": "5+"}
    audit = {}
    updated = [dict(r) for r in rank_rows]
    for r in updated:
        rid = r["role_id"]
        if selected_room[rid] == r["rooms_census_category"]:
            continue
        size = r["household_size"]
        sg = str(size) if size <= 4 else "5+"
        rg = room_group[selected_room[rid]]
        pool = usable.loc[(usable.resident_group == sg) & (usable.room_group == rg),
                          ["HHID", "per_capita_usable_m2"]]
        if len(pool) < 10:
            raise ValueError(f"revised CHNS conditional cell too small: {rid}: {len(pool)}")
        pool = sorted(pool.itertuples(index=False, name=None))
        h = hashlib.sha256(f"{RANK_SEED}:{rid}".encode()).digest()
        index = int.from_bytes(h[:8], "big") % len(pool)
        value = float(pool[index][1])
        lower = bisect_right(all_values, value - 1e-9)
        upper = bisect_right(all_values, value)
        percentile = round((lower + upper) / (2 * len(all_values)), 4)
        audit[rid] = {"previous_room": r["rooms_census_category"],
                      "recomputed_room": selected_room[rid],
                      "size_group": sg, "CHNS_cell_n": len(pool),
                      "previous_conditional_rank": r["chns_relative_rank_percentile"],
                      "recomputed_conditional_rank": percentile,
                      "CHNS_reference_status": "same_size_room_cell_n10"}
        r["rooms_census_category"] = selected_room[rid]
        r["chns_relative_rank_percentile"] = percentile
        r["chns_reference_status"] = "same_size_room_cell_n10"
    return updated, audit


def obvious_room_area_conflict(row: dict, label: str) -> bool:
    area = area_per_person(label) * row["household_size"]
    room = ROOMS[row["rooms_census_category"]]
    # Conservative geometry sanity bounds for this roleplay design, not
    # observed housing-code limits or inferred population support.
    return (room == 1 and area > 110) or (room == 2 and area < 20) or (
        room == 3 and area < 35) or (room == 4 and area < 45) or (
        room >= 5 and area < 60) or area > 350


def constrained_rank_assignment(rank_rows: list[dict]) -> tuple[dict[str, str], list[dict]]:
    """Minimum-cost rank assignment with fixed province bins and sanity bounds.

    Ranks are CHNS conditional ranks. No CHNS m2 value or 1.33 factor enters.
    """
    by_province = defaultdict(list)
    for row in rank_rows:
        by_province[row["province"]].append(row)
    selected = {}
    repairs = []
    for province in sorted(by_province):
        group = sorted(by_province[province], key=lambda r: r["role_id"])
        sorted_bins = sorted([r["rank_transport_v3_h6_per_capita_bin"] for r in group], key=area_per_person)
        reference_quantile = {}
        for label in set(sorted_bins):
            places = [i for i, b in enumerate(sorted_bins) if b == label]
            reference_quantile[label] = (sum(places) / len(places) + .5) / len(group)
        cost = [[10**9 if obvious_room_area_conflict(row, label) else
                 round(10**6 * (row["chns_relative_rank_percentile"] - reference_quantile[label]) ** 2)
                 for label in sorted_bins] for row in group]
        allocation = minimum_cost_assignment(cost)
        for i, row in enumerate(group):
            label = sorted_bins[allocation[i]]
            if obvious_room_area_conflict(row, label):
                raise ValueError(f"no feasible constrained assignment in {province}")
            selected[row["role_id"]] = label
            prior = row["rank_transport_v3_h6_per_capita_bin"]
            if prior != label:
                repairs.append({"province": province, "role_id": row["role_id"],
                                "rank_transport_v3_bin": prior, "selected_bin": label,
                                "rank_percentile": row["chns_relative_rank_percentile"],
                                "reason": "minimum_cost_assignment_with_room_area_sanity_constraints"})
    return selected, repairs


def build() -> tuple[dict, dict]:
    cohort, cities, pairing, gate, rank = [json.loads(p.read_text()) for p in (COHORT, CITY, PAIR, GATE, RANK)]
    city = {r["role_id"]: r for r in cities["assignments"]}
    paired = {r["role_id"]: r for r in pairing["records"]}
    gates = {r["role_id"]: r for r in gate["records"]}
    rows = cohort["records"]
    original_room = {r["role_id"]: r["residence"]["census_room_count_category"] for r in rows}
    selected_room = dict(original_room)
    room_repairs = []
    row_by_id = {r["role_id"]: r for r in rows}
    for left, right in ROOM_REPAIRS:
        a, b = row_by_id[left], row_by_id[right]
        if ((a["residence"]["province"], a["household"]["generation_category"]) !=
                (b["residence"]["province"], b["household"]["generation_category"])):
            raise ValueError("room repair crosses census quota stratum")
        if original_room[left] != "one_room" or original_room[right] == "one_room":
            raise ValueError("unexpected room-repair inputs")
        selected_room[left], selected_room[right] = original_room[right], original_room[left]
        room_repairs.append({"role_id_a": left, "role_id_b": right,
                             "province": a["residence"]["province"],
                             "generation_category": a["household"]["generation_category"],
                             "previous_room_a": original_room[left], "new_room_a": selected_room[left],
                             "previous_room_b": original_room[right], "new_room_b": selected_room[right],
                             "reason": "replace_two_sparse_size_x_one_room_design_combinations_with_same_stratum_room_exchange"})
    original_rank_by_id = {r["role_id"]: r for r in rank["records"]}
    revised_rank_rows, rank_recomputations = recompute_room_swap_ranks(rank["records"], selected_room)
    if Counter(r["chns_reference_status"] for r in revised_rank_rows) != {"same_size_room_cell_n10": 300}:
        raise ValueError("final roles do not all have n>=10 CHNS conditional cells")
    rank_by_id = {r["role_id"]: r for r in revised_rank_rows}
    selected_bins, repairs = constrained_rank_assignment(revised_rank_rows)
    expected = {f"cityrole-{i:04}" for i in range(1, 301)}
    if ({r["role_id"] for r in rows} != expected or set(city) != expected or
            set(paired) != expected or set(gates) != expected or set(rank_by_id) != expected):
        raise ValueError("stable role IDs changed")
    area_before, area_after = defaultdict(Counter), defaultdict(Counter)
    room_before, room_after = defaultdict(Counter), defaultdict(Counter)
    records = []
    for row in rows:
        rid = row["role_id"]
        hh, home, c, p, g = row["household"], row["residence"], city[rid], paired[rid], gates[rid]
        size, gen = hh["family_size"], hh["generation_category"]
        room = selected_room[rid]
        if (c["province"] != home["province"] or c["city_zh"] != home["city"]
                or c["family_size"] != size or c["generation_category"] != gen
                or c["census_room_count_category"] != original_room[rid]
                or p["original_per_capita_area_bin_m2"] != home["per_capita_area_bin_m2"]
                or p["sensitivity_per_capita_area_bin_m2"] != g["sensitivity_h6_area_bin"]
                or rank_by_id[rid]["original_h6_per_capita_bin"] != home["per_capita_area_bin_m2"]):
            raise ValueError(f"source mismatch: {rid}")
        people = make_people(rid, hh)
        link_people(people, gen)
        if len(people) != size:
            raise ValueError(f"person count mismatch: {rid}")
        older = any(m["age_years_design"] >= 60 for m in people)
        if older != hh["older_member_present"]:
            raise ValueError(f"older marker mismatch: {rid}")
        selected_bin = selected_bins[rid]
        if obvious_room_area_conflict(rank_by_id[rid], selected_bin):
            raise ValueError(f"area-room conflict remains: {rid}")
        per_capita = area_per_person(selected_bin)
        area = round(per_capita * size, 1)
        area_before[home["province"]][home["per_capita_area_bin_m2"]] += 1
        area_after[home["province"]][selected_bin] += 1
        room_before[(home["province"], gen)][room] += 1
        room_after[(c["province"], c["generation_category"])][room] += 1
        flags = []
        if selected_bin in ("8及以下", "70及以上"):
            flags.append("open_area_bin_design_point")
        if size >= 4 and room == "one_room":
            flags.append("crowded_one_h7_room_design_case")
        shared = area < 30
        if shared:
            flags.append("below_cfps2020_housing_area_soft_check_30m2")
        if area > 500:
            flags.append("above_cfps2020_housing_area_soft_check_500m2")
        records.append({
            "role_id": rid, "family_size": size, "generation_category": gen,
            "members": people, "older_member_present": older,
            "location": {"province": home["province"], "city": home["city"],
                         "administrative_city_code": home["administrative_city_code"],
                         "city_evidence": "experimental_UN_WUP2025_2020_urban_population_proxy_within_province",
                         "city_population_weight": None},
            "dwelling": {"room_count_census_h7_category": room,
                         "previous_census_h7_room_category": original_room[rid],
                         "room_count_design_minimum": ROOMS[room],
                         "room_count_definition": "Census H7: natural rooms excluding kitchen, toilet, corridor and hall; five_or_more is top-coded",
                         "room_count_evidence": "source_calibrated_NBS_2020_8_3a_province_x_generation_quota_transported_to_roles",
                         "per_capita_building_area_census_h6_bin_m2": selected_bin,
                         "original_independent_area_bin_m2": home["per_capita_area_bin_m2"],
                         "design_per_capita_building_area_m2": per_capita,
                         "design_total_building_area_m2": area,
                         "housing_form_design": "shared_dwelling_private_rooms_with_allocated_common_area" if shared else "independent_dwelling",
                         "area_basis": "synthetic_H6_like_household_attributed_building_area_in_shared_dwelling" if shared else "synthetic_H6_like_whole_dwelling_building_area",
                         "area_definition": "Synthetic H6-like building-area share attributed to this household, including common-area allocation" if shared else "Synthetic whole dwelling building area; neither usable nor conditioned area",
                         "physical_whole_dwelling_building_area_m2": None if shared else area,
                         "area_bin_evidence": "source_calibrated_NBS_2020_8_2a_province_marginal_quota",
                         "area_pairing_evidence": "experimental_CHNS_2015_conditional_relative_rank_transport_with_room_area_constraint" if room == original_room[rid] else "experimental_CHNS_2015_recomputed_conditional_rank_after_room_quota_repair",
                         "numeric_area_evidence": "experimental_bin_midpoint_or_declared_open_bin_point",
                         "observed_dwelling_area_m2": None},
            "source_joint_status": {"size_x_generation": "NBS_2020_5_1a_city_conditioned_quota",
                                    "province_x_generation_x_rooms": "NBS_2020_8_3a_transported_quota",
                                    "province_x_area": "NBS_2020_8_2a_marginal_quota",
                                    "size_x_rooms_x_area": "not_observed_in_national_source"},
            "field_evidence": {"role_id": "stable_synthetic_identifier",
                               "family_size": "source_calibrated_city_size_x_generation_quota",
                               "generation_category": "source_calibrated_city_size_x_generation_quota",
                               "members_age_band": "mixed_source_marginal_and_experimental_template",
                               "members_exact_age": "experimental_constrained",
                               "members_relationship": "experimental_constrained",
                               "province": "source_calibrated_quota_transport",
                               "city": "experimental_UN_urban_population_proxy",
                               "h7_room_category": "source_calibrated_quota_experimental_role_assignment",
                               "h6_per_capita_bin": "source_calibrated_province_marginal_experimental_role_assignment",
                               "building_area_numeric": "experimental_bin_point",
                               "housing_form": "experimental_H6_shared_dwelling_interpretation" if shared else "experimental_independent_dwelling_interpretation",
                               "observed_household_microdata": "none"},
            "review_flags": flags,
        })
    if area_before != area_after or room_before != room_after:
        raise AssertionError("frozen province quotas changed")
    records.sort(key=lambda r: r["role_id"])
    def old_conflict(r: dict) -> bool:
        return obvious_room_area_conflict(original_rank_by_id[r["role_id"]], r["dwelling"]["original_independent_area_bin_m2"])
    def rank_conflict(r: dict) -> bool:
        return obvious_room_area_conflict(rank_by_id[r["role_id"]], rank_by_id[r["role_id"]]["rank_transport_v3_h6_per_capita_bin"])
    area_by_room = {}
    for room in ROOMS:
        values = [r["dwelling"]["design_total_building_area_m2"] for r in records
                  if r["dwelling"]["room_count_census_h7_category"] == room]
        area_by_room[room] = {"n": len(values), "min_m2": min(values),
                              "median_m2": statistics.median(values), "max_m2": max(values)}
    audit = {"schema_version": "eb.family_300_structure_audit.v1", "n": len(records),
             "n_members": sum(r["family_size"] for r in records),
             "n_cities": len({r["location"]["administrative_city_code"] for r in records}),
             "family_size_counts": dict(sorted(Counter(r["family_size"] for r in records).items())),
             "generation_counts": dict(sorted(Counter(r["generation_category"] for r in records).items())),
             "room_counts": dict(sorted(Counter(r["dwelling"]["room_count_census_h7_category"] for r in records).items())),
             "area_bin_counts": dict(sorted(Counter(r["dwelling"]["per_capita_building_area_census_h6_bin_m2"] for r in records).items())),
             "province_area_bin_quota_max_absolute_error": max(abs(area_before[q][k]-area_after[q][k]) for q in area_before for k in area_before[q]),
             "province_generation_room_quota_max_absolute_error": max(abs(room_before[q][k]-room_after[q][k]) for q in room_before for k in room_before[q]),
             "changed_area_bin_assignments": sum(r["dwelling"]["per_capita_building_area_census_h6_bin_m2"] != r["dwelling"]["original_independent_area_bin_m2"] for r in records),
             "changed_from_unconstrained_rank": len(repairs),
             "rank_transport_repairs": repairs,
             "room_quota_repairs": room_repairs,
             "rank_recomputations_after_room_repairs": rank_recomputations,
             "original_independent_room_area_conflicts": sum(old_conflict(r) for r in records),
             "unconstrained_rank_room_area_conflicts": sum(rank_conflict(r) for r in records),
             "n_obvious_room_area_conflicts_final": 0,
             "area_by_room": area_by_room,
             "family_size_x_room_counts": {str(size): dict(sorted(Counter(r["dwelling"]["room_count_census_h7_category"] for r in records if r["family_size"] == size).items()))
                                           for size in sorted({r["family_size"] for r in records})},
             "review_flag_counts": dict(sorted(Counter(f for r in records for f in r["review_flags"]).items())),
             "review_cases": [{"role_id": r["role_id"], "flags": r["review_flags"]} for r in records if r["review_flags"]],
             "source_diagnostic": {"rank_input_local_urban_households": 2198,
                                   "exact_size_room_reference_count_after_room_repair": 300,
                                   "pooled_room_fallback_count_after_room_repair": 0,
                                   "meaning": "CHNS conditional relative rank only; no usable-to-building area conversion or population joint claim"}}
    package = {"schema_version": "eb.family_300_structure.v1", "status": "synthetic_experimental_family_structure_for_roleplay_and_idf_matching",
               "n": len(records), "population_weight": None, "observed_family_microdata_count": 0,
               "source_sha256": {x.name: digest(x) for x in (COHORT, CITY, PAIR, GATE, RANK)},
               "CHNS_raw_md5_checked": CHNS_FILES,
               "area_assignment_selected": "conditional_CHNS_rank_transport_v3_with_same_province_constraint_repair",
               "records": records}
    return package, audit


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()
    package, audit = build()
    for path, item in ((OUT, package), (AUDIT, audit)):
        serialized = json.dumps(item, ensure_ascii=False, indent=2) + "\n"
        if args.verify:
            if path.read_text() != serialized:
                raise AssertionError(f"reproducibility failure: {path}")
        else:
            path.write_text(serialized)
    print(json.dumps({"n": audit["n"], "members": audit["n_members"],
                      "cities": audit["n_cities"], "quota_errors": [audit["province_area_bin_quota_max_absolute_error"],
                      audit["province_generation_room_quota_max_absolute_error"]],
                      "review_flag_counts": audit["review_flag_counts"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
