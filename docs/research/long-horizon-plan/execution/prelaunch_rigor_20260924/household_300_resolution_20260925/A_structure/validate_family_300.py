#!/usr/bin/env python3
"""Independent checks of the materialized 300 synthetic families."""

from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
source = json.loads((ROOT / "collection_cohort_300_design_v1.json").read_text())["records"]
generated = json.loads((HERE / "family_300.json").read_text())["records"]
assert len(generated) == 300
assert [r["role_id"] for r in generated] == [f"cityrole-{i:04}" for i in range(1, 301)]
src_by_id = {r["role_id"]: r for r in source}
area_old, area_new = defaultdict(Counter), defaultdict(Counter)
room_old, room_new = defaultdict(Counter), defaultdict(Counter)
age_gap_failures = []
for r in generated:
    rid = r["role_id"]
    original = src_by_id[rid]
    assert r["family_size"] == len(r["members"]) == original["household"]["family_size"]
    assert r["generation_category"] == original["household"]["generation_category"]
    assert r["location"]["province"] == original["residence"]["province"]
    assert r["location"]["city"] == original["residence"]["city"]
    assert r["dwelling"]["previous_census_h7_room_category"] == original["residence"]["census_room_count_category"]
    assert r["older_member_present"] == any(m["age_years_design"] >= 60 for m in r["members"])
    assert len({m["member_id"] for m in r["members"]}) == r["family_size"]
    assert all("_or_" not in m["relationship_to_reference_adult"] for m in r["members"])
    assert sum(m["relationship_to_reference_adult"] == "spouse" for m in r["members"]) <= 1
    assert abs(r["dwelling"]["design_total_building_area_m2"] - r["dwelling"]["design_per_capita_building_area_m2"] * r["family_size"]) < 1e-9
    area = r["dwelling"]["design_total_building_area_m2"]
    if area < 30:
        assert r["dwelling"]["housing_form_design"] == "shared_dwelling_private_rooms_with_allocated_common_area"
        assert r["dwelling"]["physical_whole_dwelling_building_area_m2"] is None
    else:
        assert r["dwelling"]["physical_whole_dwelling_building_area_m2"] == area
    reference = next(m for m in r["members"] if m["relationship_to_reference_adult"] == "reference_adult")
    assert sum(m["relationship_to_reference_adult"] == "reference_adult" for m in r["members"]) == 1
    by_member_id = {m["member_id"]: m for m in r["members"]}
    for m in r["members"]:
        rel = m["relationship_to_reference_adult"]
        age = m["age_years_design"]
        assert len(set(m["parent_member_ids"])) == len(m["parent_member_ids"])
        for parent_id in m["parent_member_ids"]:
            assert parent_id in by_member_id and parent_id != m["member_id"]
            parent_age = by_member_id[parent_id]["age_years_design"]
            if parent_age - age < 18:
                age_gap_failures.append(f"{rid}:{parent_id}->{m['member_id']}:parent_link")
        partner_id = m["partner_member_id"]
        if partner_id is not None:
            assert partner_id in by_member_id and partner_id != m["member_id"]
            if by_member_id[partner_id]["partner_member_id"] != m["member_id"]:
                age_gap_failures.append(f"{rid}:{m['member_id']}:asymmetric_partner")
            if abs(by_member_id[partner_id]["age_years_design"] - age) > 12:
                age_gap_failures.append(f"{rid}:{m['member_id']}:partner_gap")
        if rel == "child" and not m["parent_member_ids"]:
            age_gap_failures.append(f"{rid}:{m['member_id']}:unlinked_child")
        if rel == "sibling" and r["generation_category"] == 3:
            if m["parent_member_ids"] != reference["parent_member_ids"]:
                age_gap_failures.append(f"{rid}:{m['member_id']}:sibling_parent_mismatch")
        if rel == "child" and reference["age_years_design"] - age < 18:
            age_gap_failures.append(f"{rid}:{m['member_id']}:child")
        if rel == "parent_of_reference_adult" and age - reference["age_years_design"] < 18:
            age_gap_failures.append(f"{rid}:{m['member_id']}:parent")
        if rel == "spouse" and abs(age - reference["age_years_design"]) > 12:
            age_gap_failures.append(f"{rid}:{m['member_id']}:spouse")
        if rel == "sibling" and abs(age - reference["age_years_design"]) > 15:
            age_gap_failures.append(f"{rid}:{m['member_id']}:sibling")
        if rel == "spouse_of_child" and abs(age - r["members"][1]["age_years_design"]) > 10:
            age_gap_failures.append(f"{rid}:{m['member_id']}:child_spouse")
    if r["generation_category"] == 2:
        parent, child = r["members"][:2]
        if parent["age_years_design"] - child["age_years_design"] < 18:
            age_gap_failures.append(rid)
    elif r["generation_category"] == 3:
        grand, parent, child = r["members"][:3]
        if grand["age_years_design"] - parent["age_years_design"] < 18 or parent["age_years_design"] - child["age_years_design"] < 18:
            age_gap_failures.append(rid)
    area_old[r["location"]["province"]][original["residence"]["per_capita_area_bin_m2"]] += 1
    area_new[r["location"]["province"]][r["dwelling"]["per_capita_building_area_census_h6_bin_m2"]] += 1
    key = (r["location"]["province"], r["generation_category"])
    room_old[key][original["residence"]["census_room_count_category"]] += 1
    room_new[key][r["dwelling"]["room_count_census_h7_category"]] += 1
assert not age_gap_failures, age_gap_failures
assert area_old == area_new
assert room_old == room_new
print(json.dumps({"families": len(generated), "members": sum(r["family_size"] for r in generated),
                  "age_gap_failures": len(age_gap_failures), "province_area_quota_differences": 0,
                  "province_generation_room_quota_differences": 0,
                  "min_area_m2": min(r["dwelling"]["design_total_building_area_m2"] for r in generated),
                  "max_area_m2": max(r["dwelling"]["design_total_building_area_m2"] for r in generated)},
                 ensure_ascii=False))
