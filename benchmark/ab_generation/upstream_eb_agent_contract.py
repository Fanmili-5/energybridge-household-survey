"""Unmodified extracted functions from pinned original EB;see provenance JSON."""
from __future__ import annotations
import math,re
from typing import List,Any
SOURCE_COMMIT="2b17ae63e613da776c93e900f5dace50d63a88a8"

def _agent_memory_profile(loop):
    """Benchmark adapter:explicit observable profile,never hidden response labels."""
    return loop.observable_profile

def _adaptive_v3_water_heater_action_errors(
    actions: dict | None,
    appliance_config: dict | None,
) -> list[str]:
    """Validate the conditional V3 water-heater action contract."""
    actions = actions if isinstance(actions, dict) else {}
    wh_config = (appliance_config or {}).get("water_heater", {}) or {}
    if not isinstance(wh_config, dict) or not bool(wh_config.get("present", False)):
        return []
    enabled = actions.get("water_heater_preheat")
    if not isinstance(enabled, bool):
        return ["water_heater_preheat must be an explicit boolean"]
    if enabled is False:
        # Associated fields are intentionally ignored at application time.  A
        # false command is a real disable/no-op, never an implicit enable.
        return []

    errors: list[str] = []
    values: dict[str, float] = {}
    for key in (
        "water_heater_preheat_start_h",
        "water_heater_preheat_end_h",
        "water_heater_preheat_temp_c",
    ):
        raw = actions.get(key)
        if isinstance(raw, bool):
            errors.append(f"{key} must be a finite number when preheat=true")
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            errors.append(f"{key} must be a finite number when preheat=true")
            continue
        if not math.isfinite(value):
            errors.append(f"{key} must be a finite number when preheat=true")
            continue
        values[key] = value
    start = values.get("water_heater_preheat_start_h")
    end = values.get("water_heater_preheat_end_h")
    temp = values.get("water_heater_preheat_temp_c")
    if start is not None and not 0.0 <= start < 24.0:
        errors.append("water_heater_preheat_start_h must be in [0, 24)")
    if end is not None and not 0.0 <= end <= 24.0:
        errors.append("water_heater_preheat_end_h must be in [0, 24]")
    if temp is not None and not 45.0 <= temp <= 75.0:
        errors.append("water_heater_preheat_temp_c must be in [45, 75]")
    if start is not None and end is not None and 0.0 <= start < 24.0 and 0.0 <= end <= 24.0:
        duration = end - start
        if duration <= 0.0:
            duration += 24.0
        if duration <= 1e-6 or duration > 8.0:
            errors.append("water-heater preheat window duration must be greater than 0 and at most 8 hours")
    return errors

def _adaptive_v3_appliance_action_contract_errors(
    actions: dict | None,
    appliance_config: dict | None,
) -> list[str]:
    """Validate exact V3 types and canonical local-hour ranges."""
    actions = actions if isinstance(actions, dict) else {}
    config = appliance_config or {}
    errors = _adaptive_v3_water_heater_action_errors(actions, appliance_config)

    def finite_hour(key: str, *, end_semantics: bool = False) -> None:
        raw = actions.get(key)
        if raw is None:
            return
        if isinstance(raw, bool):
            errors.append(f"{key} must be numeric")
            return
        try:
            value = float(raw)
        except (TypeError, ValueError):
            errors.append(f"{key} must be numeric")
            return
        if not math.isfinite(value):
            errors.append(f"{key} must be finite")
            return
        upper_ok = value <= 24.0 if end_semantics else value < 24.0
        if value < 0.0 or not upper_ok:
            interval = "[0, 24]" if end_semantics else "[0, 24)"
            errors.append(f"{key} must use canonical local hours in {interval}")

    for name in ("washer", "dishwasher", "dryer"):
        device = config.get(name, {}) or {}
        if not isinstance(device, dict) or not bool(device.get("present", False)):
            continue
        skip_key = f"{name}_skip"
        if skip_key in actions and not isinstance(actions.get(skip_key), bool):
            errors.append(f"{skip_key} must be an exact boolean")
        service_required = bool(device.get("service_required_today", True))
        if actions.get(skip_key) is True and service_required:
            errors.append(
                f"{skip_key}=true would cancel a required daily service; "
                "schedule it inside the declared executable window instead"
            )
        if actions.get(skip_key) is not True:
            finite_hour(f"{name}_start_h")

    ev = config.get("ev", {}) or {}
    if isinstance(ev, dict) and bool(ev.get("present", False)):
        mode = actions.get("ev_mode")
        if mode is not None and (not isinstance(mode, str) or mode not in {"normal", "smart", "delay"}):
            errors.append("ev_mode must be one of: normal, smart, delay")
        finite_hour("ev_charge_start_h")
        finite_hour("ev_charge_end_h", end_semantics=True)
    return errors

def _adaptive_v3_plan_control_errors(
    plan: dict | None,
    *,
    sim_h: float,
    total_sim_hours: float,
    setpoint_min_c: float,
    setpoint_max_c: float,
) -> list[str]:
    """Validate scalar execution fields before portfolio selection."""
    if not isinstance(plan, dict):
        return ["selected plan is not an executable object"]
    errors: list[str] = []
    try:
        raw_setpoint = plan.get("setpoint")
        if isinstance(raw_setpoint, bool):
            raise ValueError("boolean is not a setpoint")
        setpoint = float(raw_setpoint)
        if not math.isfinite(setpoint):
            raise ValueError("non-finite")
        if not float(setpoint_min_c) <= setpoint <= float(setpoint_max_c):
            errors.append(
                f"setpoint must be within [{float(setpoint_min_c):.3f}, {float(setpoint_max_c):.3f}]"
            )
    except (TypeError, ValueError):
        errors.append("setpoint must be finite")
    next_check = plan.get("next_check_hour")
    if next_check is not None:
        try:
            if isinstance(next_check, bool):
                raise ValueError("boolean is not an hour")
            next_value = float(next_check)
            if not math.isfinite(next_value):
                raise ValueError("non-finite")
            if next_value < float(sim_h) + 0.25 - 1e-9:
                errors.append("next_check_hour must be in the future")
            elif next_value > float(total_sim_hours):
                errors.append("next_check_hour exceeds the simulation horizon")
        except (TypeError, ValueError):
            errors.append("next_check_hour must be a finite number or null")
    if not isinstance(plan.get("appliances"), dict):
        errors.append("appliances must be an object")
    return errors

def _missing_explicit_appliance_actions(
    actions: dict | None,
    appliance_config: dict | None,
    *,
    adaptive_contract: bool = False,
    completed_services: set[str] | None = None,
) -> List[str]:
    """Return fields missing from an Agent response for present controllable appliances."""
    actions = actions or {}
    missing: List[str] = []
    present = set(_present_agent_controlled_appliances(appliance_config))
    completed = {str(value) for value in (completed_services or set())}
    for name in ("washer", "dishwasher", "dryer"):
        if name in present and name not in completed:
            start_key = f"{name}_start_h"
            skip_key = f"{name}_skip"
            if actions.get(skip_key) is True:
                continue
            if actions.get(start_key) is None:
                missing.append(start_key)
            if actions.get(skip_key) is None:
                missing.append(skip_key)
    if "water_heater" in present:
        if adaptive_contract:
            enabled = actions.get("water_heater_preheat")
            if not isinstance(enabled, bool):
                missing.append("water_heater_preheat")
            elif enabled:
                for key in (
                    "water_heater_preheat_start_h",
                    "water_heater_preheat_end_h",
                    "water_heater_preheat_temp_c",
                ):
                    if actions.get(key) is None:
                        missing.append(key)
        else:
            for key in (
                "water_heater_preheat_start_h",
                "water_heater_preheat_end_h",
                "water_heater_preheat_temp_c",
                "water_heater_preheat",
            ):
                if actions.get(key) is None:
                    missing.append(key)
    if "ev" in present:
        if actions.get("ev_charge_start_h") is None:
            missing.append("ev_charge_start_h")
        if actions.get("ev_charge_end_h") is None:
            missing.append("ev_charge_end_h")
    return missing

def _present_agent_controlled_appliances(appliance_config: dict | None) -> List[str]:
    """Present non-AC appliances the policy must explicitly command.

    Even non-DR-adjustable devices need a policy command in explicit-only
    simulation; for those devices the command should preserve the user's
    routine rather than reschedule it.
    """
    cfg = appliance_config or {}
    names = []
    for name in ("washer", "dishwasher", "dryer", "water_heater", "ev"):
        dev_cfg = cfg.get(name, {}) or {}
        if bool(dev_cfg.get("present", False)):
            names.append(name)
    return names

def _agent_observable_ac_bounds(loop) -> tuple[float, float, float]:
    """Return thermostat bounds inferred only from observable onboarding."""
    memory = getattr(loop, "agent_preference_memory", {}) or {}
    onboarding = memory.get("onboarding") if isinstance(memory.get("onboarding"), dict) else {}
    answers = onboarding.get("answers") if isinstance(onboarding.get("answers"), list) else []
    preferred_min, preferred_max = 24.0, 26.0
    for item in answers:
        if not isinstance(item, dict) or str(item.get("id", "")) != "thermostat_flexibility":
            continue
        text = str(item.get("answer", "") or "")
        match = re.search(
            r"(\d{2}(?:\.\d+)?)\s*(?:-|–|—|to)\s*(\d{2}(?:\.\d+)?)\s*°?\s*[Cc]",
            text,
        )
        if match:
            left, right = float(match.group(1)), float(match.group(2))
            if 15.0 <= left <= right <= 35.0:
                preferred_min, preferred_max = left, right
        break
    profile = _agent_memory_profile(loop)
    try:
        tolerance = float(profile.get("thermostat_flexibility_c", 1.0) or 1.0)
    except (TypeError, ValueError):
        tolerance = 1.0
    return preferred_min, preferred_max, max(0.0, min(5.0, tolerance))

