"""Read-only EPW admission for an explicitly located research dwelling.

Interface: resolve_weather(target, repo) -> JSON-serializable audit dictionary.
``repo`` is the energybridge-household-survey repository root. ``target`` must
provide province, city, latitude, longitude, altitude_m, numeric UTC timezone,
and coordinate_evidence. Evidence is retained, not independently certified.
It may describe a deliberately designed site; it must not be called observed.

The default geographic thresholds are configurable ENGINEERING POLICIES, not
Chinese standards or proof that a station represents a particular household.
Only catalog-verified files in the target province are considered. Same-city
selection is the default. Cross-city substitution requires an explicit policy
opt-in and keeps its unverified climate-equivalence limitation. This module
never allocates cities to population slots, modifies resources, downloads,
reads survey microdata, injects ground temperatures, or runs EnergyPlus.
"""

from __future__ import annotations

import calendar
import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

VERSION = "household_to_idf.weather_rules.v1"
DOC_EPW = "https://bigladdersoftware.com/epx/docs/24-1/auxiliary-programs/energyplus-weather-file-epw-data-dictionary.html"
DOC_LOCATION = "https://bigladdersoftware.com/epx/docs/24-1/input-output-reference/group-location-climate-weather-file-access.html"
REQUIRED_TARGET = ("province", "city", "latitude", "longitude", "altitude_m", "timezone", "coordinate_evidence")
DEFAULT_POLICY = {
    "allow_cross_city": False,
    "max_distance_km": 50.0,
    "max_altitude_difference_m": 300.0,
    "max_timezone_difference_h": 0.0,
    "max_solar_time_offset_min": 30.0,
    "max_catalog_coordinate_difference_deg": 0.02,
    "allow_archive_minute_zero": True,
    "allow_leap_year": False,
    "max_critical_missing_values": 0,
    "require_no_daylight_saving": True,
    "max_direct_normal_wh_m2": 1600.0,
    "max_global_horizontal_wh_m2": 1600.0,
    "max_diffuse_horizontal_wh_m2": 1600.0,
    "max_dewpoint_above_dry_bulb_c": 0.5,
}
MAINLAND_PROVINCES = {
    "北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江",
    "上海", "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南",
    "湖北", "湖南", "广东", "广西", "海南", "重庆", "四川", "贵州",
    "云南", "西藏", "陕西", "甘肃", "青海", "宁夏", "新疆",
}
# Zero-based EPW column, missing threshold, minimum, maximum, strict endpoints.
# Dictionary ranges are a file-format check; they do not establish climatology.
FIELD_SPECS = {
    "dry_bulb_c": (6, 99.9, -70, 70, True),
    "dew_point_c": (7, 99.9, -70, 70, True),
    "relative_humidity_pct": (8, 999, 0, 110, False),
    "station_pressure_pa": (9, 999999, 31000, 120000, True),
    "horizontal_ir_wh_m2": (12, 9999, 0, None, False),
    "global_horizontal_wh_m2": (13, 9999, 0, None, False),
    "direct_normal_wh_m2": (14, 9999, 0, None, False),
    "diffuse_horizontal_wh_m2": (15, 9999, 0, None, False),
    "wind_direction_deg": (20, 999, 0, 360, False),
    "wind_speed_m_s": (21, 999, 0, 40, False),
    "total_sky_cover_tenths": (22, 99, 0, 10, False),
    "opaque_sky_cover_tenths": (23, 99, 0, 10, False),
}
# The conservative default rejects missing horizontal IR instead of relying on
# EnergyPlus's opaque-sky substitution. Any changed missing-value allowance is
# reported in policy and does not silently replace data.
CRITICAL_FIELDS = tuple(FIELD_SPECS)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _number(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("boolean is not a coordinate or numeric threshold")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("non-finite number")
    return result


def _province(value: Any) -> str:
    result = str(value or "").strip()
    for suffix in ("维吾尔自治区", "壮族自治区", "回族自治区", "自治区", "特别行政区", "省", "市"):
        if result.endswith(suffix):
            return result[:-len(suffix)]
    return result


def _city(value: Any) -> str:
    result = str(value or "").strip()
    return result[:-1] if result.endswith("市") else result


def _resource(repo: Path, relative: Any) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ValueError("missing resource path")
    raw = Path(relative)
    if raw.is_absolute():
        raise ValueError("resource path must be repository-relative")
    result = (repo / raw).resolve()
    if not result.is_relative_to(repo):
        raise ValueError("resource path escapes repository")
    return result


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1.0, max(0.0, a))))


def _read_location(row: list[str]) -> dict[str, Any]:
    if len(row) != 10 or row[0].strip().upper() != "LOCATION":
        raise ValueError("EPW LOCATION must contain exactly ten fields")
    result = dict(zip(("record_type", "city", "province", "country", "data_source", "wmo", "latitude", "longitude", "timezone", "altitude_m"), row))
    for key in ("latitude", "longitude", "timezone", "altitude_m"):
        result[key] = _number(result[key])
    if not (-90 <= result["latitude"] <= 90 and -180 <= result["longitude"] <= 180 and -12 <= result["timezone"] <= 12 and -1000 <= result["altitude_m"] < 9999.9):
        raise ValueError("EPW LOCATION outside 24.1 EPW dictionary bounds")
    result["engine_site_location_bounds_ok"] = -300 <= result["altitude_m"] < 8900
    return result


def _annual_quality(rows: list[list[str]], policy: Mapping[str, Any]) -> dict[str, Any]:
    expected_headers = ("LOCATION", "DESIGN CONDITIONS", "TYPICAL/EXTREME PERIODS", "GROUND TEMPERATURES", "HOLIDAYS/DAYLIGHT SAVINGS", "COMMENTS 1", "COMMENTS 2", "DATA PERIODS")
    errors: list[str] = []
    warnings: list[str] = []
    if len(rows) < 8 or tuple(row[0].strip().upper() if row else "" for row in rows[:8]) != expected_headers:
        errors.append("invalid_eight_header_records")
    data = rows[8:]
    leap = len(data) == 8784
    if len(data) not in (8760, 8784):
        errors.append("not_one_full_hourly_year")
    if leap and not policy["allow_leap_year"]:
        errors.append("leap_year_disallowed_by_engineering_policy")
    if len(rows) >= 8:
        try:
            period = rows[7]
            if int(period[1]) != 1 or int(period[2]) != 1:
                errors.append("not_one_hourly_data_period")
            if tuple(int(x.strip()) for x in period[5].split("/")) != (1, 1) or tuple(int(x.strip()) for x in period[6].split("/")) != (12, 31):
                errors.append("header_not_january_to_december")
        except (ValueError, IndexError):
            errors.append("invalid_data_period_header")
    daylight_saving = {"start": None, "end": None, "leap_years_observed": None, "header_active": None}
    try:
        holiday = rows[4]
        daylight_saving = {"start": holiday[2].strip(), "end": holiday[3].strip(), "leap_years_observed": holiday[1].strip(), "header_active": any(value.strip() not in ("0", "") for value in holiday[2:4])}
        if daylight_saving["header_active"]:
            warnings.append("daylight_saving_header_requires_explicit_RunPeriod_consistency")
            if policy["require_no_daylight_saving"]:
                errors.append("daylight_saving_active_disallowed_by_engineering_policy")
    except IndexError:
        errors.append("invalid_daylight_saving_header")
    expected = [(month, day, hour) for month in range(1, 13) for day in range(1, calendar.monthrange(2000 if leap else 2001, month)[1] + 1) for hour in range(1, 25)]
    stats = {name: {"missing": 0, "invalid": 0, "minimum": None, "maximum": None} for name in FIELD_SPECS}
    years: set[int] = set()
    minutes: Counter[int] = Counter()
    physical = {"dewpoint_exceeds_dry_bulb_by_engineering_tolerance": 0, "relative_humidity_above_100_pct": 0, "direct_normal_above_configured_limit": 0, "global_horizontal_above_configured_limit": 0, "diffuse_horizontal_above_configured_limit": 0, "direct_normal_above_epw_extraterrestrial_normal": 0}
    malformed = sequence_errors = timestamp_errors = 0
    for index, row in enumerate(data):
        if len(row) != 35:
            malformed += 1
            continue
        try:
            year, month, day, hour, minute = (int(x) for x in row[:5])
            years.add(year)
            minutes[minute] += 1
            if year < 1 or not 0 <= minute <= 60:
                timestamp_errors += 1
            if index >= len(expected) or (month, day, hour) != expected[index]:
                sequence_errors += 1
        except ValueError:
            timestamp_errors += 1
        for name, (column, missing, minimum, maximum, strict) in FIELD_SPECS.items():
            metric = stats[name]
            try:
                value = _number(row[column])
            except (TypeError, ValueError):
                metric["invalid"] += 1
                continue
            if value >= missing:
                metric["missing"] += 1
                continue
            lower_bad = value <= minimum if strict else value < minimum
            upper_bad = maximum is not None and (value >= maximum if strict else value > maximum)
            if lower_bad or upper_bad:
                metric["invalid"] += 1
            metric["minimum"] = value if metric["minimum"] is None else min(metric["minimum"], value)
            metric["maximum"] = value if metric["maximum"] is None else max(metric["maximum"], value)
        def observed(column: int, missing: float) -> float | None:
            try:
                value = _number(row[column])
                return value if value < missing else None
            except (TypeError, ValueError):
                return None
        dry, dew, rh = observed(6, 99.9), observed(7, 99.9), observed(8, 999)
        if dry is not None and dew is not None and dew > dry + policy["max_dewpoint_above_dry_bulb_c"]:
            physical["dewpoint_exceeds_dry_bulb_by_engineering_tolerance"] += 1
        if rh is not None and rh > 100:
            physical["relative_humidity_above_100_pct"] += 1
        for column, threshold, diagnostic in (
            (14, "max_direct_normal_wh_m2", "direct_normal_above_configured_limit"),
            (13, "max_global_horizontal_wh_m2", "global_horizontal_above_configured_limit"),
            (15, "max_diffuse_horizontal_wh_m2", "diffuse_horizontal_above_configured_limit"),
        ):
            radiation = observed(column, 9999)
            if radiation is not None and radiation > policy[threshold]:
                physical[diagnostic] += 1
        direct, extraterrestrial = observed(14, 9999), observed(11, 9999)
        if direct is not None and extraterrestrial is not None and direct > extraterrestrial + 1e-9:
            physical["direct_normal_above_epw_extraterrestrial_normal"] += 1
    if malformed:
        errors.append("malformed_hourly_record")
    if sequence_errors or timestamp_errors:
        errors.append("invalid_or_noncontiguous_hourly_sequence")
    if minutes[0]:
        warnings.append("archive_minute_zero_differs_from_documented_1_to_60_convention")
        if not policy["allow_archive_minute_zero"]:
            errors.append("archive_minute_zero_disallowed_by_engineering_policy")
    if len(minutes) > 1:
        errors.append("mixed_hourly_minute_conventions")
    missing_count = sum(stats[name]["missing"] for name in CRITICAL_FIELDS)
    invalid_count = sum(stats[name]["invalid"] for name in CRITICAL_FIELDS)
    if missing_count > policy["max_critical_missing_values"]:
        errors.append("critical_weather_fields_missing")
    if invalid_count:
        errors.append("critical_weather_fields_out_of_dictionary_range_or_nonfinite")
    if physical["dewpoint_exceeds_dry_bulb_by_engineering_tolerance"]:
        errors.append("dewpoint_above_dry_bulb_exceeds_engineering_policy")
    if any(physical[name] for name in ("direct_normal_above_configured_limit", "global_horizontal_above_configured_limit", "diffuse_horizontal_above_configured_limit")):
        errors.append("solar_radiation_exceeds_engineering_policy")
    if physical["direct_normal_above_epw_extraterrestrial_normal"]:
        warnings.append("direct_normal_exceeds_epw_extraterrestrial_normal_diagnostic")
    if physical["relative_humidity_above_100_pct"]:
        warnings.append("relative_humidity_above_100_but_within_dictionary_110_possible")
    return {
        "status": "failed" if errors else "passed_engineering_file_check",
        "row_count": len(data), "expected_hourly_rows": len(expected), "leap_year": leap,
        "malformed_records": malformed, "sequence_errors": sequence_errors,
        "timestamp_errors": timestamp_errors, "source_year_values": sorted(years),
        "source_year_semantics": "EPW row years do not establish observed household-year weather",
        "minute_counts": {str(key): value for key, value in sorted(minutes.items())},
        "critical_missing_values": missing_count, "critical_invalid_values": invalid_count,
        "field_statistics": stats, "errors": sorted(set(errors)), "warnings": warnings,
        "daylight_saving": daylight_saving, "physical_diagnostics": physical,
        "physical_diagnostic_basis": "1600 Wh/m2 hourly solar caps and dew-point tolerance are configurable engineering screens, not official standards; extraterrestrial-normal comparison is diagnostic only",
        "scope": "every hourly row; chronology, twelve thermal-weather field ranges and explicit plausibility screens; not physical/climate calibration",
        "dictionary_url": DOC_EPW,
    }


def _policy(target: Mapping[str, Any]) -> dict[str, Any]:
    overrides = target.get("weather_policy", {})
    if not isinstance(overrides, Mapping) or set(overrides) - set(DEFAULT_POLICY):
        raise ValueError("weather_policy must contain only documented DEFAULT_POLICY keys")
    result = {**DEFAULT_POLICY, **overrides}
    booleans = {"allow_cross_city", "allow_archive_minute_zero", "allow_leap_year", "require_no_daylight_saving"}
    for key in booleans:
        if type(result[key]) is not bool:
            raise ValueError(f"{key} must be a boolean")
    for key in set(result) - booleans:
        result[key] = _number(result[key])
        if result[key] < 0:
            raise ValueError(f"{key} must be nonnegative")
    if result["max_critical_missing_values"] % 1:
        raise ValueError("max_critical_missing_values must be an integer count")
    return result


def resolve_weather(target: Mapping[str, Any], repo: str | Path) -> dict[str, Any]:
    """Select a traceable weather candidate without inventing target locations.

    Result statuses: missing_target, invalid_target, invalid_policy,
    invalid_catalog, no_compatible_weather, matched_engineering_candidate.
    The last status is an input-admission gate, never household calibration.
    ``selected`` contains epw/ddy repository paths, hashes, LOCATION and full
    annual quality. ``candidates`` preserves every verified same-province
    candidate, including geographic, provenance and quality rejection reasons.
    """
    result: dict[str, Any] = {
        "version": VERSION, "status": "missing_target", "target": dict(target),
        "selected": None, "candidates": [], "errors": [],
        "policy_basis": "configurable research engineering policy; no official Chinese distance/altitude tolerance claimed",
        "limitations": [
            "City and coordinate evidence are caller-supplied, not independently established household residence.",
            "Administrative city agreement does not prove an address is urban rather than town/rural.",
            "Proximity, elevation and solar-time gates do not prove climate equivalence or household weather calibration.",
            "Typical-year weather is a simulation input, not a measured household context for 2020/2021/2022.",
            "EPW LOCATION overrides Site:Location for weather-file runs in EnergyPlus 24.1; confirm eplusout.eio location.",
            "EPW undisturbed ground temperatures are not assigned to building-surface ground temperatures here.",
        ],
        "documentation": [DOC_EPW, DOC_LOCATION],
    }
    missing = [key for key in REQUIRED_TARGET if target.get(key) is None or target.get(key) == "" or target.get(key) == {}]
    if missing:
        result["missing_fields"] = missing
        result["errors"] = ["target_geography_not_supplied; no population-based city assignment performed"]
        return result
    try:
        site = {key: _number(target[key]) for key in ("latitude", "longitude", "altitude_m", "timezone")}
        site.update(province=_province(target["province"]), city=_city(target["city"]))
        if site["province"] not in MAINLAND_PROVINCES or not site["city"] or site["city"].endswith(("乡", "镇", "村")):
            raise ValueError("target must explicitly name a mainland province and city; no town/rural target admitted")
        if not (-90 <= site["latitude"] <= 90 and -180 <= site["longitude"] <= 180 and -300 <= site["altitude_m"] < 8900 and -12 <= site["timezone"] <= 14):
            raise ValueError("target outside EnergyPlus 24.1 Site:Location bounds")
        evidence = target["coordinate_evidence"]
        if not isinstance(evidence, (str, Mapping)) or not evidence:
            raise ValueError("coordinate_evidence must be a nonempty source string or provenance object")
    except (ValueError, TypeError) as exc:
        result.update(status="invalid_target", errors=[str(exc)])
        return result
    try:
        policy = _policy(target)
    except (ValueError, TypeError) as exc:
        result.update(status="invalid_policy", errors=[str(exc)])
        return result
    result["policy"] = policy
    result["normalized_target"] = site
    repo = Path(repo).resolve()
    catalog_path = repo / "simulation_resources/catalog.json"
    try:
        raw = catalog_path.read_bytes()
        catalog = json.loads(raw)
        entries = catalog["weather"]
        if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
            raise ValueError("catalog weather must be a list of station objects")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result.update(status="invalid_catalog", errors=[str(exc)])
        return result
    result["catalog"] = {"path": str(catalog_path), "sha256": _sha256(raw), "version": catalog.get("version"), "weather_entries": len(entries)}
    candidates = [entry for entry in entries if entry.get("status") == "verified" and _province(entry.get("province")) == site["province"]]
    result["catalog"]["verified_same_province_candidates"] = len(candidates)
    for entry in sorted(candidates, key=lambda item: str(item.get("id", ""))):
        same_city = _city(entry.get("city")) == site["city"]
        candidate: dict[str, Any] = {
            key: entry.get(key) for key in ("id", "province", "city", "station_name", "wmo", "series", "source_url", "epw", "epw_sha256", "ddy", "ddy_sha256", "match", "name_match")
        }
        candidate.update(same_city=same_city, eligible=False, rejection_reasons=[], annual_quality={"status": "not_evaluated"}, climate_compatibility={"status": "unknown", "evidence": None})
        reasons = candidate["rejection_reasons"]
        if not same_city and not policy["allow_cross_city"]:
            reasons.append("cross_city_not_explicitly_allowed")
        if not candidate["source_url"] or not candidate["epw_sha256"]:
            reasons.append("missing_original_url_or_expected_epw_hash")
        try:
            epw = _resource(repo, entry.get("epw"))
            epw_bytes = epw.read_bytes()
            candidate["actual_epw_sha256"] = _sha256(epw_bytes)
            candidate["epw_absolute_path"] = str(epw)
            if candidate["actual_epw_sha256"] != entry.get("epw_sha256"):
                reasons.append("epw_hash_mismatch")
            rows = list(csv.reader(epw_bytes.decode("utf-8-sig").splitlines()))
            location = _read_location(rows[0])
            candidate["epw_location"] = location
            if location["country"].strip().upper() != "CHN":
                reasons.append("epw_country_not_CHN")
            if not location["engine_site_location_bounds_ok"]:
                reasons.append("epw_elevation_outside_engine_site_location_bounds")
            if str(location["wmo"]).strip() != str(entry.get("wmo")).strip():
                reasons.append("epw_wmo_catalog_mismatch")
            for axis in ("latitude", "longitude"):
                if abs(location[axis] - _number(entry.get(axis))) > policy["max_catalog_coordinate_difference_deg"]:
                    reasons.append(f"epw_{axis}_catalog_mismatch")
            if abs(location["timezone"] - _number(entry.get("timezone"))) > 1e-9:
                reasons.append("epw_timezone_catalog_mismatch")
            distance = _distance_km(site["latitude"], site["longitude"], location["latitude"], location["longitude"])
            altitude_delta = location["altitude_m"] - site["altitude_m"]
            timezone_delta = location["timezone"] - site["timezone"]
            solar_delta = 4 * (location["longitude"] - site["longitude"]) - 60 * timezone_delta
            candidate["compatibility_metrics"] = {
                "distance_km": distance, "station_minus_target_altitude_m": altitude_delta,
                "station_minus_target_timezone_h": timezone_delta,
                "station_minus_target_mean_solar_time_min": solar_delta,
                "solar_offset_formula": "4*(station_longitude-target_longitude)-60*(station_timezone-target_timezone); ignores common equation-of-time term",
            }
            for value, threshold, reason in (
                (distance, "max_distance_km", "distance_exceeds_engineering_policy"),
                (abs(altitude_delta), "max_altitude_difference_m", "altitude_difference_exceeds_engineering_policy"),
                (abs(timezone_delta), "max_timezone_difference_h", "timezone_difference_exceeds_engineering_policy"),
                (abs(solar_delta), "max_solar_time_offset_min", "solar_time_difference_exceeds_engineering_policy"),
            ):
                if value > policy[threshold] + 1e-9:
                    reasons.append(reason)
            source_path = epw.parent / "source.json"
            if source_path.exists():
                source_bytes = source_path.read_bytes()
                source = json.loads(source_bytes)
                candidate["source_manifest"] = {"path": str(source_path), "sha256": _sha256(source_bytes), "url": source.get("url"), "archive_sha256": source.get("archive_sha256")}
                if source.get("url") != candidate["source_url"]:
                    reasons.append("source_manifest_url_catalog_mismatch")
            if entry.get("ddy"):
                ddy = _resource(repo, entry["ddy"])
                candidate["ddy_absolute_path"] = str(ddy)
                candidate["actual_ddy_sha256"] = _sha256(ddy.read_bytes())
                if candidate["actual_ddy_sha256"] != entry.get("ddy_sha256"):
                    reasons.append("ddy_hash_mismatch")
            # Audit the full annual series only after identity/geography gates;
            # rejected candidates retain explicit not-evaluated quality status.
            if not reasons:
                candidate["annual_quality"] = _annual_quality(rows, policy)
                reasons.extend(candidate["annual_quality"]["errors"])
        except (OSError, UnicodeError, ValueError, TypeError, IndexError) as exc:
            reasons.append(f"resource_read_or_metadata_error: {exc}")
        candidate["rejection_reasons"] = sorted(set(reasons))
        candidate["eligible"] = not candidate["rejection_reasons"]
        result["candidates"].append(candidate)
    eligible = [candidate for candidate in result["candidates"] if candidate["eligible"]]
    if not eligible:
        result.update(status="no_compatible_weather", errors=["no_verified_station_passes_explicit_target_and_engineering_policy"])
        return result
    selected = min(eligible, key=lambda candidate: (not candidate["same_city"], candidate["compatibility_metrics"]["distance_km"], str(candidate["id"])))
    result.update(status="matched_engineering_candidate", selected=selected)
    result["selection_rule"] = "same administrative city first, then minimum great-circle distance, then station id; no province-representative fallback"
    result["climate_equivalence_certified"] = False
    return result


def audit_verified_registry(repo: str | Path, policy_overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Audit every catalog-verified EPW, returning station aggregates only.

    This is a file-quality inventory, not a target/location assignment. Stations
    outside the mainland target scope can appear here because the inventory
    covers the existing registry; resolve_weather still enforces its scope.
    No hourly values are exported and no values are replaced or imputed.
    """
    repo = Path(repo).resolve()
    policy = _policy({"weather_policy": policy_overrides or {}})
    catalog_path = repo / "simulation_resources/catalog.json"
    raw = catalog_path.read_bytes()
    catalog = json.loads(raw)
    audits = []
    for entry in sorted(catalog["weather"], key=lambda item: str(item.get("id", ""))):
        if entry.get("status") != "verified":
            continue
        station = {key: entry.get(key) for key in ("id", "province", "city", "station_name", "wmo", "series", "source_url", "epw", "epw_sha256", "ddy", "ddy_sha256")}
        errors = []
        try:
            epw = _resource(repo, entry.get("epw"))
            epw_bytes = epw.read_bytes()
            station["actual_epw_sha256"] = _sha256(epw_bytes)
            if station["actual_epw_sha256"] != station["epw_sha256"]:
                errors.append("epw_hash_mismatch")
            rows = list(csv.reader(epw_bytes.decode("utf-8-sig").splitlines()))
            location = _read_location(rows[0])
            station["epw_location"] = location
            if location["country"].strip().upper() != "CHN":
                errors.append("epw_country_not_CHN")
            if str(location["wmo"]).strip() != str(entry.get("wmo")).strip():
                errors.append("epw_wmo_catalog_mismatch")
            for axis in ("latitude", "longitude"):
                if abs(location[axis] - _number(entry.get(axis))) > policy["max_catalog_coordinate_difference_deg"]:
                    errors.append(f"epw_{axis}_catalog_mismatch")
            if abs(location["timezone"] - _number(entry.get("timezone"))) > 1e-9:
                errors.append("epw_timezone_catalog_mismatch")
            if not location["engine_site_location_bounds_ok"]:
                errors.append("epw_elevation_outside_engine_site_location_bounds")
            if not entry.get("source_url") or not entry.get("epw_sha256"):
                errors.append("missing_original_url_or_expected_epw_hash")
            source_path = epw.parent / "source.json"
            if source_path.exists():
                source_bytes = source_path.read_bytes()
                source = json.loads(source_bytes)
                station["source_manifest"] = {"path": str(source_path), "sha256": _sha256(source_bytes), "url": source.get("url"), "archive_sha256": source.get("archive_sha256")}
                if source.get("url") != entry.get("source_url"):
                    errors.append("source_manifest_url_catalog_mismatch")
            if entry.get("ddy"):
                station["actual_ddy_sha256"] = _sha256(_resource(repo, entry["ddy"]).read_bytes())
                if station["actual_ddy_sha256"] != entry.get("ddy_sha256"):
                    errors.append("ddy_hash_mismatch")
            station["annual_quality"] = _annual_quality(rows, policy)
            errors.extend(station["annual_quality"]["errors"])
        except (OSError, UnicodeError, ValueError, TypeError, IndexError) as exc:
            errors.append(f"resource_read_or_metadata_error: {exc}")
        station["rejection_reasons"] = sorted(set(errors))
        station["file_quality_passed"] = not errors
        audits.append(station)
    reason_counts = Counter(reason for station in audits for reason in station["rejection_reasons"])
    return {
        "version": VERSION, "scope": "all catalog verified weather files; per-station summaries; no survey microdata or hourly-value export",
        "policy": policy, "policy_basis": "explicit research engineering thresholds, not official standards",
        "catalog": {"path": str(catalog_path), "sha256": _sha256(raw), "version": catalog.get("version"), "total_entries": len(catalog["weather"])},
        "station_count": len(audits), "passed_file_quality_count": sum(station["file_quality_passed"] for station in audits),
        "failed_file_quality_count": sum(not station["file_quality_passed"] for station in audits),
        "rejection_reason_station_counts": dict(sorted(reason_counts.items())),
        "stations": audits, "climate_equivalence_certified": False,
        "documentation": [DOC_EPW, DOC_LOCATION],
    }
