"""Build and check the EnergyBridge household benchmark input registry."""
from collections import Counter, defaultdict
from contextlib import contextmanager
import csv
import hashlib
import io
import json
from pathlib import Path
import sys
from zipfile import ZipFile

import pyreadstat

ROOT = Path(__file__).resolve().parent
INPUTS = ROOT / "inputs"
PUBLIC = ROOT.parent / "public_sources"
SEED = "EB-stage1-20261107-v1"
QUOTAS = {"A": 166, "B": 198, "C": 125, "D": 151, "E": 156, "F": 204}
ROLE_NAMES = {
    "A": "role_a_price_cooperative_commuter",
    "B": "role_b_home_comfort_gated",
    "C": "role_c_irregular_cautious",
    "D": "role_d_ideal_dr_participant",
    "E": "role_e_caregiver_low_dr",
    "F": "role_f_ev_commuter_optimizer",
}
FILES = {
    "ENABLE_EU": INPUTS / "enable.sav",
    "RECS2024_v1": INPUTS / "recs2024_public_v1.csv",
    "IDEAL_home": INPUTS / "ideal/home.csv",
    "IDEAL_room": INPUTS / "ideal/room.csv",
    "IDEAL_appliance": INPUTS / "ideal/appliance.csv",
    "IRES2020": PUBLIC / "ires-data.tab",
    "ENASIC2022": PUBLIC / "mexico_enasic_2022/enasic.zip",
    "ENIGH2024_hogares": PUBLIC / "mexico_enigh_2024/hogares.zip",
    "ENIGH2024_viviendas": PUBLIC / "mexico_enigh_2024/viviendas.zip",
    "EB_role_cards": INPUTS / "fixed_role_cards_zh_en.json",
}
US_TYPE = {"2": "detached_house", "3": "attached_house", "4": "small_apartment_building", "5": "large_apartment_building"}
MX_TYPE = {"1": "detached_house", "2": "apartment"}
INDIA_TYPE = {"1": "independent_house_or_bungalow", "2": "multi_storey_apartment"}

def check(condition, message):
    if not condition:
        raise ValueError(message)

def digest(path):
    with path.open("rb") as f:
        h = hashlib.sha256()
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
        return h.hexdigest()

def rank(*values):
    return hashlib.sha256("|".join((SEED, *map(str, values))).encode()).hexdigest()

def integer(raw):
    s = str(raw).strip()
    return int(s) if s.isdecimal() else -1

def fact(value, fields, status="observed", **extra):
    return {"value": value, "status": status, "fields": list(fields), **extra}

DEVICE_FIELDS = (
    "washer_available", "dryer_available", "dishwasher_available",
    "space_ac_available", "water_heater_available", "home_vehicle_charging",
)

def coded_device(row, field, yes, no, imputation_field=None, **extra):
    code = row[field]
    if code not in yes and code not in no:
        return fact(None, [field], "unknown")
    fields = [field] if imputation_field is None else [field, imputation_field]
    status = "survey_imputed" if imputation_field and row[imputation_field] != "0" else "observed"
    return fact(code in yes, fields, status, **extra)

def ref(dataset, key, country, n, house, size, washer, **kwargs):
    return {
        "source": {"dataset": dataset, "household_key": str(key), "country": country},
        "household_size": n,
        "dwelling": {"observed_type": house, "size": size},
        "devices": {k: washer if k == "washer_available" else fact(None, [], "unknown") for k in DEVICE_FIELDS},
        **kwargs,
    }

def source_key(row):
    return row["source"]["dataset"], row["source"]["household_key"]

def device_signature(row):
    return tuple((row["devices"][name]["value"], row["devices"][name]["status"]) for name in DEVICE_FIELDS)

@contextmanager
def zip_rows(dataset, member):
    with ZipFile(FILES[dataset]) as archive:
        with io.TextIOWrapper(archive.open(member), encoding="utf-8-sig", newline="") as f:
            yield csv.DictReader(f)

def load_csv(dataset, delimiter=","):
    with FILES[dataset].open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=delimiter))

def indexed(rows, get_key):
    result = {}
    for row in rows:
        key = get_key(row)
        check(bool(key) and key not in result, f"Missing or duplicate source key {key!r}")
        result[key] = row
    return result

def enable_candidates():
    members = [f"S1{s}c{a}" for s in ("A", "B") for a in (1, 2, 3)]
    columns = ["UID", "Country", "H1", "H3", "H11B", "H11C", "H11E", "H11G", "S3", "M1A", "M3A1", "C4G", *members]
    data, meta = pyreadstat.read_sav(FILES["ENABLE_EU"], usecols=columns, output_format="dict")
    check(len(set(data["UID"])) == len(data["UID"]), "ENABLE household keys repeat")
    out = []
    for vals in zip(*(data[k] for k in columns)):
        x = dict(zip(columns, vals))
        labels = meta.variable_value_labels
        counts = [x[k] for k in members]
        if (labels["Country"].get(x["Country"]) != "Spain" or x["H1"] not in {1,2,3,4}
            or x["H3"] not in {1,2,3,4,5,6} or x["H11C"] not in {1,2,4}
            or not all(v is not None and v >= 0 and v == int(v) for v in counts)
            or not 1 <= sum(counts) <= 20):
            continue
        a = x["S3"] in {1,2} and x["M1A"] in {3,4,5,6,7} and x["M3A1"] == 1
        b = x["C4G"] == 5
        if not a and not b:
            continue
        row = ref("ENABLE_EU", x["UID"], "ES", fact(int(sum(counts)), members, "derived"),
                  fact(labels["H1"][x["H1"]], ["H1"], code=int(x["H1"])),
                  fact(labels["H3"][x["H3"]], ["H3"], measure="dwelling_area_band", code=int(x["H3"])),
                  fact(True, ["H11C"], code=int(x["H11C"])))
        for slot, field in (("dishwasher_available","H11B"),("space_ac_available","H11E")):
            row["devices"][slot] = coded_device(x, field, {1,2,4}, {5})
        if x["H11G"] in {1,2,4}:
            row["devices"]["water_heater_available"] = fact(True,["H11G"], appliance_type="standalone_electric_boiler")
        row["anchors"] = {}
        if a:
            row["anchors"]["A"] = fact({"days_to_work_or_study": int(x["M1A"]), "leaves_from_home": True,
                                       "employment_code": int(x["S3"])}, ["M1A", "M3A1", "S3"])
        if b:
            row["anchors"]["B"] = fact({"home_presence_item_code": 5, "context": "heating"}, ["C4G"])
        out.append(row)
    return out

def recs_candidates():
    raw = indexed(load_csv("RECS2024_v1"), lambda x: x["DOEID"])
    out = []
    for key, x in raw.items():
        people, sqft = integer(x["NHSLDMEM_PUB"]), integer(x["SQFTEST_PUB"])
        if (not 1 <= people <= 10 or not 200 <= sqft <= 14000 or x["TYPEHUQ"] not in US_TYPE
            or x["CWASHER"] != "1" or any(x[c] != "0" for c in ("ZTYPEHUQ", "ZSQFTEST_PUB", "ZCWASHER"))):
            continue
        area = round(sqft * 0.09290304, 2)
        row = ref("RECS2024_v1", key, "US", fact(people, ["NHSLDMEM_PUB"], "derived"),
                  fact(US_TYPE[x["TYPEHUQ"]], ["TYPEHUQ","ZTYPEHUQ"], code=x["TYPEHUQ"]),
                  fact(area, ["SQFTEST_PUB","ZSQFTEST_PUB"], "derived", measure="dwelling_area_m2", source_sqft=sqft),
                  fact(True, ["CWASHER","ZCWASHER"]),
                  block=[x["REGIONC"], US_TYPE[x["TYPEHUQ"]], people, int(area // 25)],
                  anchors={})
        row["devices"]["dryer_available"] = coded_device(x,"DRYER",{"1"},{"0"},"ZDRYER")
        row["devices"]["dishwasher_available"] = coded_device(x,"DISHWASH",{"1"},{"0"},"ZDISHWASH")
        row["devices"]["home_vehicle_charging"] = coded_device(x,"EVCHRGHOME",{"1"},{"0"})
        if x["ATHOME"] == "5" and x["ZATHOME"] == "0":
            row["anchors"]["B"] = fact({"someone_home_weekdays": 5}, ["ATHOME","ZATHOME"])
        if x["EVCHRGHOME"] == "1":
            row["anchors"]["F"] = fact({"vehicle_charged_at_home": True}, ["EVCHRGHOME"])
        out.append(row)
    return out

def ideal_candidates():
    check("Room floor area in tenths of meters squared" in (INPUTS/"ideal/IDEALdata.md").read_text(), "IDEAL area unit")
    homes = indexed(load_csv("IDEAL_home"), lambda x: x["homeid"])
    rooms, washers, appliances = defaultdict(list), defaultdict(list), defaultdict(list)
    for x in load_csv("IDEAL_room"):
        area = integer(x["floorarea"])
        if area > 0:
            rooms[x["homeid"]].append((x["roomid"], area))
    for x in load_csv("IDEAL_appliance"):
        if integer(x["number"]) > 0:
            appliances[x["homeid"]].append(x)
        if x["appliancetype"] in {"washingmachine", "washingmachinetumbledrier"} and integer(x["number"]) > 0:
            washers[x["homeid"]].append(x["applianceid"])
    result = []
    for key, x in homes.items():
        n = integer(x["residents"])
        if not (1 <= n <= 20 and x["hometype"] in {"flat","house_or_bungalow"}
                and rooms[key] and washers[key]):
            continue
        room, raw_area = sorted(rooms[key])[0]
        result.append(ref("IDEAL", key, "GB", fact(n, ["home.residents"]),
                          fact(x["hometype"], ["home.hometype"]),
                          fact(raw_area / 10, ["room.floorarea"], "derived", measure="single_observed_room_area_m2", room_key=room),
                          fact(True, ["appliance.appliancetype","appliance.number"], appliance_key=sorted(washers[key])[0]),
                          anchors={"B": fact({"home_occupied_days_typical_week": 7}, ["home.occupied_days"])}))
        for slot, types in (("dryer_available",{"tumbledrier","washingmachinetumbledrier"}),
                            ("dishwasher_available",{"dishwasher"})):
            matches = sorted((d for d in appliances[key] if d["appliancetype"] in types), key=lambda d:d["applianceid"])
            if matches:
                asset = matches[0]
                result[-1]["devices"][slot] = fact(True, ["appliance.appliancetype","appliance.number"],
                                                    appliance_key=asset["applianceid"], appliance_type=asset["appliancetype"])
    return result

def india_candidates():
    raw = indexed(load_csv("IRES2020", "\t"), lambda x: x["hhid"])
    result = []
    for key, x in raw.items():
        kind = x["q217_house_type"]
        people = integer(x["q213_no_members"])
        bedrooms = integer(x["q223_house_no_bedrooms"])
        other = integer(x["q225_house_no_otherrooms"])
        if (kind not in INDIA_TYPE or not 1 <= people <= 20 or min(bedrooms, other) < 0
            or not 1 <= bedrooms + other <= 20 or x["q472_wash_mach_yn"] != "1" or not x["state_abbv"]):
            continue
        rooms = bedrooms + other
        result.append(ref("IRES2020", key, "IN", fact(people, ["q213_no_members"]),
                          fact(INDIA_TYPE[kind], ["q217_house_type"], code=kind),
                          fact(rooms, ["q223_house_no_bedrooms","q225_house_no_otherrooms"], "derived",
                               measure="dwelling_rooms_excluding_bathrooms"),
                          fact(True, ["q472_wash_mach_yn"]),
                          block=[x["state_abbv"], INDIA_TYPE[kind], people, rooms], anchors={}))
        if x["q451_geyser_use_1"] == "1":
            result[-1]["devices"]["water_heater_available"] = fact(True,["q451_geyser_use_1"],appliance_type="electric_geyser")
    return result

def mexico_candidates():
    with zip_rows("ENIGH2024_viviendas", "viviendas.csv") as rows:
        donors_housing = indexed(rows, lambda x: x["folioviv"])
    with zip_rows("ENIGH2024_hogares", "hogares.csv") as rows:
        donors_households = indexed(rows, lambda x: (x["folioviv"], x["foliohog"]))
    donors = defaultdict(list)
    for (dwelling_key, hh_key), x in donors_households.items():
        h = donors_housing[dwelling_key]
        if h["tot_hog"] == "1" and h["tipo_viv"] in MX_TYPE and integer(x["num_lavad"]) > 0:
            signature = (integer(h["num_cuarto"]), integer(h["tot_resid"]))
            donors[signature].append((dwelling_key, hh_key, MX_TYPE[h["tipo_viv"]]))
    with zip_rows("ENASIC2022", "TVIVIENDA.csv") as rows:
        dwellings = indexed(rows, lambda x: x["LLAVEVIV"])
    with zip_rows("ENASIC2022", "THOGAR.csv") as rows:
        homes = indexed(rows, lambda x: x["LLAVEHOG"])
    with zip_rows("ENASIC2022", "TCSDEMPO.csv") as rows:
        people = indexed(rows, lambda x: x["LLAVESDE"])
    roster_counts = Counter(p["LLAVEHOG"] for p in people.values())
    edges = defaultdict(set)
    for child_id, child in people.items():
        age, key = integer(child["EDAD"]), child["LLAVEHOG"]
        check(child_id.startswith(key) and len(child_id)==len(key)+2, "ENASIC person key layout")
        check(homes[key]["LLAVEVIV"] == child["LLAVEVIV"], "ENASIC person dwelling link")
        if 0 <= age <= 5 and child["P4_16"] == "1":
            gate, prefix = "P4_16", "P4_17"
        elif 6 <= age <= 17 and child["P4_27"] == "1":
            gate, prefix = "P4_27", "P4_28"
        else:
            continue
        for i in range(1, 4):
            col = f"{prefix}_{i}"
            ordinal = integer(child[col])
            if ordinal in {-1,0,99}:
                continue
            caregiver_id = f"{key}{ordinal:02d}"
            caregiver = people.get(caregiver_id)
            if (caregiver is not None and child_id != caregiver_id and caregiver["LLAVEHOG"] == key
                and 18 <= integer(caregiver["EDAD"]) <= 98):
                edges[key].add((child_id, caregiver_id, age, integer(caregiver["EDAD"]), gate, col))
    result = []
    for key, observed_edges in edges.items():
        h = dwellings[homes[key]["LLAVEVIV"]]
        rooms, people_n = integer(h["P1_3A"]), roster_counts[key]
        if not 1 <= rooms <= 20 or not 2 <= people_n <= 20 or h["P1_10_02"] != "1":
            continue
        pool = donors[(rooms, people_n)]
        if len(pool) < 30:
            continue
        type_counts = Counter(d[2] for d in pool)
        supported = [d for d in pool if type_counts[d[2]] >= 5]
        if not supported:
            continue
        pick = min(supported, key=lambda d: rank("MX dwelling", key, d[0], d[1]))
        e = min(observed_edges, key=lambda edge: rank("care edge", key, *edge))
        row = ref("ENASIC2022", key, "MX", fact(people_n, ["TCSDEMPO.LLAVEHOG","TCSDEMPO.LLAVESDE"], "derived"),
                  fact(None, [], "unknown"),
                  fact(rooms, ["TVIVIENDA.P1_3A"], measure="dwelling_room_count"),
                  fact(True, ["TVIVIENDA.P1_10_02"]),
                  anchors={"E": fact({"child_key": e[0], "adult_caregiver_key": e[1], "child_age": e[2],
                                       "caregiver_age": e[3], "last_week": True},
                                      ["LLAVEHOG","LLAVESDE","EDAD",e[4],e[5]], "derived")})
        row["devices"]["space_ac_available"] = coded_device(h,"P1_9_10",{"1"},{"2"})
        heater_fields = [f for f in ("P1_9_07","P1_9_08") if h[f] == "1"]
        if heater_fields:
            row["devices"]["water_heater_available"] = fact(True,heater_fields,
                appliance_type="reported_boiler_or_solar_heater", electric_control_eligibility=None)
        row["dwelling"]["reference_type"] = fact(pick[2], ["viviendas.tipo_viv"], "reference_matched",
             source_dataset="ENIGH2024", donor_dwelling_key=pick[0], donor_household_key=pick[1],
             matched={"country":"MX","dwelling_rooms":rooms,"household_size":people_n,"washer":True},
             donor_pool_count=len(pool), supported_donor_count=len(supported), type_counts=dict(type_counts))
        result.append(row)
    return result

def build():
    expected = {x["role_card_id"] for x in json.loads(FILES["EB_role_cards"].read_text())}
    check(set(ROLE_NAMES.values()) == expected, "Original EB role IDs changed")
    enable, recs, uk, india, mexico = (enable_candidates(),recs_candidates(),ideal_candidates(),india_candidates(),mexico_candidates())
    used, cases = set(), []

    def select(pool, role, n, key):
        available = sorted((r for r in pool if source_key(r) not in used), key=lambda r: rank(key, *source_key(r)))
        check(len(available) >= n, f"Only {len(available)} candidates for {key}, need {n}")
        for r in available[:n]:
            add(r, role)

    def add(r, role, pair=None):
        key = source_key(r)
        check(key not in used, f"Source household reused: {key}")
        used.add(key)
        anchor = r["anchors"].get(role)
        if role in "ABEF":
            check(anchor is not None, f"Missing {role} source evidence")
        else:
            anchor = fact("routine_variation" if role == "C" else "stable_routine", [], "benchmark_assigned")
        role_conditions = {
            "A": {"daily_return_timing":"unspecified", "preferences":"price_and_reliable_evening_service"},
            "B": {"daytime_comfort_priority":True},
            "C": {"weekday_return_minutes":[1020,1080,1140,1050,1110], "flexibility":"explain_and_allow_reversal"},
            "D": {"weekday_return_minutes":[1080,1080,1080,1080,1080], "flexibility":"allow_bounded_automation"},
            "E": {"protect_care_activities":True,"care_time_windows":"unspecified"},
            "F": {"vehicle_use":"work_commute","charge_deadline":"next_morning_departure",
                  "observed_powertrain":None,"observed_commute_use":None},
        }
        case = {k: v for k,v in r.items() if k not in {"anchors","block"}}
        case.update(case_id=f"EB1-{role}-{rank(role,*key)[:16]}", benchmark_role=role,
                    role_card_id=ROLE_NAMES[role], role_status="benchmark_assigned",
                    role_anchor=anchor, conditions=fact(role_conditions[role], [], "benchmark_assigned"))
        if "block" in r:
            case["matching_block"] = r["block"]
        if pair is not None:
            case["cd_pair_id"] = pair
        cases.append(case)

    select([r for r in recs if "F" in r["anchors"]], "F", 204, "F US home charging")
    select([r for r in enable if "A" in r["anchors"]], "A", 166, "A ES observed commute")
    select([r for r in enable if "B" in r["anchors"]], "B", 40, "B ES observed presence")
    select(uk, "B", 40, "B GB observed presence")
    select([r for r in recs if "B" in r["anchors"]], "B", 118, "B US observed presence")
    select(mexico, "E", 156, "E MX observed care")

    def paired(pool, country, n):
        groups = defaultdict(list)
        for row in pool:
            if source_key(row) not in used:
                groups[(tuple(row["block"]),device_signature(row))].append(row)
        pairs = []
        for group in groups.values():
            group.sort(key=lambda row: rank("within CD block", *source_key(row)))
            pairs.extend(zip(group[::2],group[1::2]))
        pairs.sort(key=lambda pair: rank("CD pair selection", *source_key(pair[0]), *source_key(pair[1])))
        check(len(pairs) >= n, f"Only {len(pairs)} matched pairs for {country}")
        for a,b in pairs[:n]:
            pair_id = f"CD-{country}-{rank(*source_key(a),*source_key(b))[:12]}"
            add(a,"C",pair_id)
            add(b,"D",pair_id)

    paired(recs,"US",75)
    paired(india,"IN",50)
    select(recs,"D",13,"D US supplementary")
    select(india,"D",13,"D IN supplementary")
    coverage = {
        "ES_A": sum("A" in r["anchors"] for r in enable),
        "ES_B": sum("B" in r["anchors"] for r in enable),
        "GB_B": len(uk), "US_B": sum("B" in r["anchors"] for r in recs),
        "US_F_home_charging": sum("F" in r["anchors"] for r in recs),
        "MX_E_reference_match": len(mexico), "IN_CD_carriers": len(india),
    }
    return sorted(cases,key=lambda x:(x["benchmark_role"],x["case_id"])), coverage

def validate(cases):
    check(Counter(x["benchmark_role"] for x in cases) == QUOTAS, "Role quotas differ")
    check(len({x["case_id"] for x in cases}) == 1000, "Case IDs repeat")
    check(len({source_key(x) for x in cases}) == 1000, "Household source keys repeat")
    pairs, mixes, anchors = defaultdict(list), defaultdict(Counter), Counter()
    inventory = defaultdict(Counter)
    for x in cases:
        role, country = x["benchmark_role"], x["source"]["country"]
        mixes[country][role] += 1
        anchors[x["role_anchor"]["status"]] += 1
        check(x["role_status"] == "benchmark_assigned" and x["conditions"]["status"] == "benchmark_assigned", "Role provenance")
        check(set(x["devices"]) == set(DEVICE_FIELDS), "Incomplete inventory schema")
        for device, value in x["devices"].items():
            check((value["value"] is None) == (value["status"] == "unknown"), "Device evidence or missingness")
            category = value["status"] if value["value"] is None else f"{value['status']}_{str(value['value']).lower()}"
            inventory[device][category] += 1
        check(x["devices"]["washer_available"]["value"] is True, "Missing washer support")
        check(x["household_size"]["value"] >= 1, "Invalid household size")
        check(x["dwelling"]["size"]["measure"] == "dwelling_area_band" or x["dwelling"]["size"]["value"] > 0, "Invalid dwelling size")
        if role == "E":
            h = x["dwelling"]["reference_type"]
            check(x["dwelling"]["observed_type"]["value"] is None and h["status"] == "reference_matched", "E type provenance")
            check(h["donor_pool_count"] >= 30 and h["type_counts"][h["value"]] >= 5, "Insufficient E donor support")
            check(h["matched"] == {"country":country,"dwelling_rooms":x["dwelling"]["size"]["value"],
                                   "household_size":x["household_size"]["value"],"washer":True}, "E reference match")
            e = x["role_anchor"]["value"]
            check(e["child_key"] != e["adult_caregiver_key"] and e["last_week"] and e["child_age"] < 18 <= e["caregiver_age"], "E care link")
        else:
            check(x["dwelling"]["observed_type"]["status"] == "observed", "Missing observed dwelling type")
        if role == "F":
            check(x["role_anchor"]["value"]["vehicle_charged_at_home"] is True
                  and x["conditions"]["value"]["observed_commute_use"] is None, "F commute provenance")
        if role in "CD":
            check(x["role_anchor"]["status"] == "benchmark_assigned", "C/D must be assigned")
            clock = x["conditions"]["value"]["weekday_return_minutes"]
            check(len(clock)==5 and (max(clock)-min(clock)==(120 if role=="C" else 0)), "Wrong C/D condition")
        if "cd_pair_id" in x:
            pairs[x["cd_pair_id"]].append(x)
    check(len(pairs)==125 and sum(len(p) for p in pairs.values())==250, "Missing C/D pairs")
    for pair in pairs.values():
        a,b = sorted(pair,key=lambda x:x["benchmark_role"])
        check({a["benchmark_role"],b["benchmark_role"]}=={"C","D"}
              and a["source"]["country"]==b["source"]["country"]
              and a["matching_block"]==b["matching_block"]
              and device_signature(a)==device_signature(b), "C/D match differs")
    return {"country_role_counts":{k:dict(v) for k,v in mixes.items()}, "role_anchor_status_counts":dict(anchors),
            "matched_cd_pairs":len(pairs), "unpaired_d_cases":26,
            "device_inventory_status":{k:dict(v) for k,v in inventory.items()}}


