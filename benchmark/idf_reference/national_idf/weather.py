"""Unmodified EPW admission. Source identity is separate from climate equivalence."""
from __future__ import annotations

import calendar
import csv
import datetime as dt
import math
from collections import Counter
from pathlib import Path
from .common import require, sha, locked

KEYS = {6: ("dry_bulb_C", -90, 70, 99.9), 7: ("dew_point_C", -100, 70, 99.9),
        8: ("relative_humidity_pct", 0, 100, 999),
        9: ("pressure_Pa", 30000, 110000, 999999),
        12: ("infrared_Wh_m2", 0, 1500, 9999),
        13: ("GHI_Wh_m2", 0, 2000, 9999), 14: ("DNI_Wh_m2", 0, 2000, 9999),
        15: ("DHI_Wh_m2", 0, 2000, 9999), 20: ("wind_direction_deg", 0, 360, 999),
        21: ("wind_speed_m_s", 0, 60, 999)}


def distance_km(a, b):
    p1, p2 = map(math.radians, (a[0], b[0]))
    dp, dl = p2-p1, math.radians(b[1]-a[1])
    return 6371 * 2 * math.asin(min(1, math.sqrt(math.sin(dp/2)**2 +
                             math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2)))


def cosine_zenith(month, day, hour, latitude, longitude, timezone):
    n = dt.date(2001, month, day).timetuple().tm_yday
    gamma = 2*math.pi/365 * (n-1+(hour-12)/24)
    eq = 229.18*(0.000075+0.001868*math.cos(gamma)-0.032077*math.sin(gamma)
                 -0.014615*math.cos(2*gamma)-0.040849*math.sin(2*gamma))
    decl = (0.006918-0.399912*math.cos(gamma)+0.070257*math.sin(gamma)
            -0.006758*math.cos(2*gamma)+0.000907*math.sin(2*gamma)
            -0.002697*math.cos(3*gamma)+0.00148*math.sin(3*gamma))
    ha = math.radians((hour*60+eq+4*longitude-60*timezone)/4-180)
    lat = math.radians(latitude)
    return max(0, math.sin(lat)*math.sin(decl)+math.cos(lat)*math.cos(decl)*math.cos(ha))


def audit(path: str | Path, metadata: dict | None = None) -> dict:
    path = Path(path)
    with path.open(encoding="utf-8-sig", errors="strict", newline="") as f:
        rows = list(csv.reader(f))
    require(len(rows) >= 8 and rows[0][0] == "LOCATION", "EPW_HEADER")
    h, data = rows[0], rows[8:]
    errors, warnings, examples = Counter(), Counter(), []
    require(len(h) >= 10, "EPW_LOCATION_FIELDS")
    lat, lon, tz, elevation = map(float, h[6:10])
    require(-90 <= lat <= 90 and -180 <= lon <= 180 and -12 <= tz <= 14,
            "EPW_LOCATION_RANGE")
    if len(data) not in (8760, 8784): errors["hour_count"] += 1
    leap = len(data) == 8784
    year = 2000 if leap else 2001
    expected = dt.datetime(year, 1, 1)
    values = {v[0]: [] for v in KEYS.values()}
    dry_by_day = {}
    for i, r in enumerate(data):
        local_errors = []
        if len(r) < 35:
            errors["field_count"] += 1
            continue
        try:
            m,d,hour,minute = map(int, r[1:5])
            stamp = (m,d,hour)
            want = expected + dt.timedelta(hours=i)
            if stamp != (want.month,want.day,want.hour+1): local_errors.append("time_axis")
            if minute not in (0, 30, 60): local_errors.append("minute_label")
            for col,(name,lo,hi,missing) in KEYS.items():
                v = float(r[col])
                if not math.isfinite(v) or v == missing or not lo <= v <= hi:
                    local_errors.append(name)
                else: values[name].append(v)
            db,dew,rh,ghi,dni,dhi = (float(r[c]) for c in (6,7,8,13,14,15))
            if all(math.isfinite(v) for v in (db,dew)) and dew > db + 0.5:
                local_errors.append("dew_above_dry")
            if 1 <= m <= 12 and 1 <= d <= calendar.monthrange(year,m)[1]:
                dry_by_day.setdefault(f"{m:02}-{d:02}", []).append(db)
                if not (m == 2 and d == 29) and all(0 <= v < 9999 for v in (ghi,dni,dhi)):
                    cz = cosine_zenith(m,d,hour-0.5,lat,lon,tz)
                    # Hour-integrated vs midpoint irradiance is a diagnostic, not a proof of corruption.
                    if abs(ghi-(dhi+dni*cz)) > max(100, 0.25*ghi): warnings["radiation_closure"] += 1
                    if cz == 0 and ghi > 30: warnings["night_radiation"] += 1
        except (ValueError, IndexError, OverflowError):
            local_errors.append("unparseable_row")
        for e in set(local_errors): errors[e] += 1
        if local_errors and len(examples) < 12: examples.append({"line":i+9,"errors":local_errors})
    if rows[7][0] != "DATA PERIODS" or len(rows[7]) < 3 or rows[7][2] != "1":
        errors["unsupported_data_period_resolution"] += 1
    if len(rows[4]) < 5 or rows[4][0] != "HOLIDAYS/DAYLIGHT SAVINGS":
        errors["dst_header"] += 1
    elif rows[4][2:4] not in (["0","0"], ["0.0","0.0"]): errors["active_DST"] += 1
    identity = {"city":h[1],"region":h[2],"country":h[3],"source_label":h[4],
                "wmo":h[5],"latitude":lat,"longitude":lon,"timezone":tz,"elevation_m":elevation}
    if metadata:
        if metadata.get("sha256") != sha(path): errors["source_hash"] += 1
        if str(metadata.get("wmo")) != str(h[5]): errors["station_identity"] += 1
        for key in ("provider","dataset","source_period","download_url"):
            if not metadata.get(key): errors["source_metadata_"+key] += 1
    return {"schema":"national_idf.weather_audit.v1","path":str(path.resolve()),
            "sha256":sha(path),"identity":identity,"hours":len(data),"leap":leap,
            "admitted":not errors,"errors":dict(errors),"diagnostics":dict(warnings),
            "error_examples":examples,"ranges":{k:{"min":min(v),"max":max(v)}
                for k,v in values.items() if v},
            "daily_mean_dry_C":{k:sum(v)/len(v) for k,v in dry_by_day.items() if len(v)==24},
            "climate_equivalence_certified":False,"source_modified":False,
            "radiation_diagnostic_method":"NOAA_midpoint_approximation;not_hourly_integration;100Wh_or25pct_threshold",
            "metadata":metadata}


def match(site: dict, registry: list[dict], base=".") -> dict:
    needed = ("province","city","latitude","longitude","elevation_m","timezone",
              "terrain_context","location_basis")
    require(all(k in site for k in needed), "SITE_INCOMPLETE", needed)
    considered = []
    for entry in registry:
        if entry["province"] != site["province"] or entry["city"] != site["city"]: continue
        report = audit(locked(entry,base), entry)
        loc = report["identity"]
        km = distance_km((site["latitude"],site["longitude"]),(loc["latitude"],loc["longitude"]))
        reasons = list(report["errors"])
        if km > 50: reasons.append("distance_over_50km_project_limit")
        if abs(site["elevation_m"]-loc["elevation_m"]) > 300: reasons.append("elevation_over_300m_project_limit")
        if abs(site["timezone"]-loc["timezone"]) > 1e-9: reasons.append("timezone")
        if site["terrain_context"] != entry.get("terrain_context"): reasons.append("terrain_context_unresolved")
        considered.append({"id":entry["id"],"distance_km":km,"reasons":reasons,
                           "admitted":not reasons,"audit":report})
    ok = sorted((r for r in considered if r["admitted"]),key=lambda r:(r["distance_km"],r["id"]))
    return {"status":"matched_reference_weather" if ok else "unsupported_weather",
            "selected":ok[0]["id"] if ok else None,"considered":considered,
            "cross_city_fallback":False,"climate_equivalence_certified":False}
