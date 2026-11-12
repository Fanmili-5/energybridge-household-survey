"""Unmodified no-DR routine from pinned public EnergyBridge family_runner.py."""
import hashlib
import random
from typing import Any

EB_COMMIT="2b17ae63e613da776c93e900f5dace50d63a88a8"

def _schedule_no_dr_routine_appliances(suite, appliance_config: dict | None, sim_days: int, seed_text: str) -> list[dict]:
    """Create a reproducible non-DR appliance routine.

    This is a counterfactual user routine, not a controller fallback: it ignores
    VPP timing, schedules shiftable tasks randomly within each user's allowed
    window, and uses ordinary water-heater/EV service windows.
    """
    rng = random.Random(int(hashlib.sha256(seed_text.encode("utf-8")).hexdigest()[:16], 16))
    records: list[dict] = []
    cfg = appliance_config or {}
    for day_idx in range(max(1, int(sim_days))):
        day_record: dict[str, Any] = {"day": day_idx + 1, "actions": {}}
        for name in ("washer", "dishwasher", "dryer"):
            app_cfg = cfg.get(name, {}) if isinstance(cfg.get(name, {}), dict) else {}
            if not bool(app_cfg.get("present", False)):
                continue
            earliest = float(app_cfg.get("earliest_h", 8.0))
            latest = float(app_cfg.get("latest_h", 22.0))
            duration = float(app_cfg.get("duration_h", 2.0))
            if latest < earliest:
                latest += 24.0
            # The last simulated day's after-midnight portion is outside the
            # evaluation horizon. Keep that final routine in the same-evening
            # segment so a valid service is not counted as horizon-censored.
            if day_idx == max(1, int(sim_days)) - 1 and latest > 24.0:
                latest = 24.0
            latest_start = max(earliest, latest - duration)
            start_h = earliest if latest_start <= earliest else rng.uniform(earliest, latest_start)
            start_abs = day_idx * 24.0 + start_h
            ok = suite.shift_appliance(name, day_idx, start_abs)
            if ok:
                day_record["actions"][f"{name}_start_h"] = round(start_h % 24.0, 3)
        wh_cfg = cfg.get("water_heater", {}) if isinstance(cfg.get("water_heater", {}), dict) else {}
        if bool(wh_cfg.get("present", False)):
            start_h = float(wh_cfg.get("normal_start_h", 17.0))
            end_h = float(wh_cfg.get("normal_end_h", 21.0))
            temp_c = float(wh_cfg.get("normal_temp_c", 60.0))
            if suite.set_ewh_preheat_schedule(day_idx, start_h=start_h, end_h=end_h, temp_c=temp_c):
                day_record["actions"].update({
                    "water_heater_preheat": True,
                    "water_heater_preheat_start_h": round(start_h, 3),
                    "water_heater_preheat_end_h": round(end_h, 3),
                    "water_heater_preheat_temp_c": round(temp_c, 1),
                })
        ev_cfg = cfg.get("ev", {}) if isinstance(cfg.get("ev", {}), dict) else {}
        if bool(ev_cfg.get("present", False)):
            start_h = float(ev_cfg.get("arrival_h", 18.0))
            end_h = float(ev_cfg.get("departure_h", 7.5))
            suite.set_ev_mode(day_idx, "normal")
            if suite.set_ev_charge_window(day_idx, start_h=start_h, end_h=end_h):
                day_record["actions"].update({
                    "ev_charge_start_h": round(start_h, 3),
                    "ev_charge_end_h": round(end_h, 3),
                })
        records.append(day_record)
    return records
