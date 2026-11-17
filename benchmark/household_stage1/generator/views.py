"""Current reference household used for judgment, separate from source audit."""
from copy import deepcopy
import datetime as dt

FUNCTIONS = {
    "AC": ("space_ac_available", "空调"),
    "WM": ("washer_available", "洗衣"),
    "DR": ("dryer_available", "烘干"),
    "DW": ("dishwasher_available", "洗碗"),
    "WH": ("water_heater_available", "热水服务"),
    "EV": ("home_vehicle_charging", "电动车充电"),
}
MEMBER_FIELDS = ("id", "reference_age", "activity", "employment",
                 "work_mode", "school_enrolled")

def current_household(case):
    h = case["household"]
    controlled = set(h["controlled_function_ids"])
    if "AC" not in controlled or not 4 <= len(controlled) <= 6:
        raise ValueError("CURRENT_CONTROL_CONFIGURATION_INVALID")
    equipment = []
    for fun, (key, name) in FUNCTIONS.items():
        eq = h["equipment"][key]
        enabled = bool(h["control_inventory"][fun]["enabled"])
        if enabled != (fun in controlled):
            raise ValueError("CONTROL_INVENTORY_DISAGREES")
        registered = any(fun in r["functions"]
                         for r in h["service_asset_registry"].values())
        present = bool(eq["present"]) or registered
        if enabled and not present:
            raise ValueError("CONTROLLED_REFERENCE_EQUIPMENT_ABSENT")
        item = dict(function=fun, name=name, present=present,
                    controlled=enabled)
        if fun == "WH" and registered and not enabled:
            item["arrangement"] = "固定热水服务，本题不调整"
        equipment.append(item)
    view = {
        "country": h["country"],
        "role": h["role_name"],
        "attitudes": deepcopy(h["attitudes"]),
        "comfort_preferences": deepcopy(h["comfort"]),
        "members": [{k: deepcopy(m[k]) for k in MEMBER_FIELDS if k in m}
                    for m in h["members"]],
        "decision_maker_member": h["decision_maker_id"],
        "reference_home": {
            k: deepcopy(h["dwelling"][k])
            for k in ("type", "reference_area_m2")
            if k in h["dwelling"]
        },
        "equipment": equipment,
    }
    view["shared_equipment_functions"] = [sorted(a["functions"]) for a in h["service_asset_registry"].values() if len(a["functions"]) > 1]
    if h.get("medical_service_must_not_be_interrupted") is True:
        view["protected_medical_service"] = True
    if h.get("ev"):
        ev = h["ev"]
        view["EV_requirements"] = {
            k: deepcopy(ev[k]) for k in (
                "vehicle_user_member_id", "arrival_soc",
                "departure_soc_target", "reference_battery_kwh",
                "reference_charger_kw", "charge_efficiency")
            if k in ev
        }
    return view

def day_routine(case, date):
    h = case["household"]
    day = dt.date.fromisoformat(date).weekday()
    start, end = day * 1440, (day + 1) * 1440
    events = []
    for e in h["calendar"]["weekly_events"]:
        if max(start, e["start"]) >= min(end, e["end"]):
            continue
        events.append({
            "member": e["member_id"],
            "kind": e["kind"], "location": e["location"],
            "start_min": max(start, e["start"]) - start,
            "end_min": min(end, e["end"]) - start,
        })
    source = next(d for d in h["routine"]["daily_services"] if d["day"] == day)
    meals = [{k: deepcopy(r[k]) for k in
              ("kind", "location", "participants", "start", "end", "supervision") if k in r}
             for r in source["meals"]]
    baths = [{k: deepcopy(r[k]) for k in
              ("member_id", "assistant_id", "service", "start", "end") if k in r}
             for r in source["bathing_services"]]
    care = []
    for arrangement in h.get("care_arrangements", []):
        recipient = next((arrangement[k] for k in ("child_id", "dependent_id", "recipient_id", "elder_id") if k in arrangement), None)
        item = {k: deepcopy(arrangement[k]) for k in ("caregiver_id", "daytime_setting", "home_care_must_have_adult", "supervision_mode") if k in arrangement}
        if recipient is not None:
            item["dependent_member"] = recipient
        item["supervision"] = []
        for e in arrangement.get("home_supervision", []):
            if max(start, e["start"]) < min(end, e["end"]):
                item["supervision"].append(dict(caregiver=e["caregiver_id"], mode=e["mode"], start_min=max(start,e["start"])-start, end_min=min(end,e["end"])-start))
        item["transport"] = [{"kind":e["kind"],"responsible":e["responsible"],"interval_min":[x-start for x in e["child_interval"]]} for e in arrangement.get("transport_legs",[]) if e["day"]==day]
        care.append(item)
    return dict(date=date, weekday=day, member_schedule=events,
                meals=meals, bathing_services=baths, care=care,
                information_contract=deepcopy(h["routine"]["information_contract"]))
