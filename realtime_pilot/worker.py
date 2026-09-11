"""One isolated EB process per job, with observable onboarding and deferred human scores.

The upstream checkout is never edited. The one nested scoring hook is replaced in
memory with a pending record, rather than injecting a made-up score into EB.
"""
from __future__ import annotations
import argparse
import contextlib
import difflib
import functools
import json
import math
import os
import re
import sys
import time
import traceback
import types
from datetime import date
from pathlib import Path

from common import ROOT, UPSTREAM, SCENARIO, VERSION, digest, file_hash, write_json, profile_text, make_persona, answer_text

def finite_json(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: finite_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [finite_json(v) for v in value]
    return value

PENDING_SCORE_BODY = '''    def _score_event(ev, loop_ref, sim_h, event_index=1, human_mode=False):
        return {
            "id": ev["id"], "setpoint": loop_ref.sp, "score": None,
            "comfort_score": None, "energy_score": None, "vpp_score": None,
            "label": "pending_human", "comment": "", "source": "pending_human",
            "user_input": loop_ref.vpp_user_input_by_id.get(ev["id"], ""),
            "trigger_h": ev["trigger_h"], "end_h": ev["end_h"], "day": ev["day"],
            "reason": loop_ref.vpp_trigger_reason_by_id.get(ev["id"], ""),
            "strategy_trace": loop_ref.vpp_strategy_trace_by_id.get(ev["id"], {}),
            "strategy_explanation": loop_ref.vpp_strategy_explanation_by_id.get(ev["id"], {}),
            "vpp_acceptance_gate": {"status": "hypothetical_execution_not_human_consent"},
        }

'''

def load_runner(job_dir):
    source_path = UPSTREAM / "experiments/benchmark/family_runner.py"
    source = source_path.read_text()
    start = source.index("    def _score_event(ev, loop_ref,")
    end = source.index("    def _event_score_due_hour(", start)
    patched = source[:start] + PENDING_SCORE_BODY + source[end:]
    (job_dir / "runner_adapter.diff").write_text("".join(difflib.unified_diff(source.splitlines(True), patched.splitlines(True), fromfile="upstream/family_runner.py", tofile="in_memory/pilot_family_runner.py")))
    module = types.ModuleType("family_runner")
    module.__file__ = str(source_path)
    sys.modules["family_runner"] = module
    exec(compile(patched, str(source_path), "exec"), module.__dict__)
    return module

def onboarding(fr, profile):
    groups = [
        ("vpp_priority", ["A01", "A02", "A03", "A11", "A12"]),
        ("thermostat_flexibility", ["A04"]),
        ("appliance_shift_consent", ["A05", "A06", "A07", "A08", "A09", "A10"]),
        ("calendar_routine_constraints", ["B01", "B02", "B04", "B05", "B06"]),
    ]
    from common import QUESTIONS
    answers = [{"id": k, "selected_option_ids": [], "answer": "\n".join(
        f"{QUESTIONS[q]['prompt']} {answer_text(q, profile[q])}" for q in ids)} for k, ids in groups]
    # Deliberately no selection of EB's temperature/consent options by attitude thresholds.
    return fr._normalize_agent_onboarding_result({"answers": answers}, questions=fr._agent_onboarding_questions(), source="web_questionnaire_direct_answers")

def run(job_dir: Path, mode="agent"):
    started = time.perf_counter()
    request = json.loads((job_dir / "request.json").read_text())
    profile = request["profile"]
    phases = {}
    calls = []
    def progress(stage):
        write_json(job_dir / "progress.json", {"stage": stage, "elapsed_seconds": round(time.perf_counter()-started, 3), "llm_calls_started": len(calls), "llm_calls_completed": sum("seconds" in c for c in calls)})
    from runtime_config import load_model_environment
    load_model_environment()
    os.environ.setdefault("EPLUS_ROOT", "/Applications/EnergyPlus-24-1-0")
    os.environ["ENERGYBRIDGE_HARNESS_PROFILE"] = "adaptive_v2"
    os.environ["ENERGYBRIDGE_DISABLE_ACCEPTANCE_FALLBACK"] = "1"
    os.environ["ENERGYBRIDGE_ROLEPLAY_MANUAL_OVERRIDE"] = "0"
    os.environ["ENERGYBRIDGE_PERSIST_AGENT_MEMORY"] = "0"
    os.environ["ENERGYBRIDGE_LOAD_AGENT_MEMORY"] = "0"
    os.environ.pop("ENERGYBRIDGE_AGENT_MEMORY_STORE", None)
    for path in [UPSTREAM, UPSTREAM / "experiments/benchmark", Path(os.environ["EPLUS_ROOT"])]:
        sys.path.insert(0, str(path))
    progress("loading")
    fr = load_runner(job_dir)
    fr._run_agent_onboarding_questionnaire = lambda *a, **k: onboarding(fr, profile)
    original_feedback = fr._update_agent_preference_memory
    def deferred_feedback(loop, result, **kwargs):
        if result.get("source") != "pending_human":
            return original_feedback(loop, result, **kwargs)
    fr._update_agent_preference_memory = deferred_feedback
    from energybridge.llm.client import LLMClient
    original_chat = LLMClient.chat_with_metrics
    @functools.wraps(original_chat)
    def timed_chat(self, system, user, *args, **kwargs):
        if self.config is None or not self.config.api_key:
            raise RuntimeError("missing_api_configuration")
        row = {"index": len(calls)+1, "model": self.config.model,
               "prompt_hash": digest([system, user]), "started_seconds": time.perf_counter()-started,
               "call_path": [f.name for f in traceback.extract_stack()[-8:-1]]}
        calls.append(row)
        progress("planning")
        write_json(job_dir / "llm_timing.json", calls)
        t = time.perf_counter()
        try:
            result = original_chat(self, system, user, *args, **kwargs)
            row.update(success=True, metrics=result.get("metrics", {}))
            return result
        except Exception as exc:
            row.update(success=False, failure_type=type(exc).__name__)
            raise
        finally:
            row["seconds"] = time.perf_counter()-t
            write_json(job_dir / "llm_timing.json", calls)
            progress("simulating")
    LLMClient.chat_with_metrics = timed_chat
    persona = make_persona(profile)
    # An absent controllable water heater must not force the template's background
    # hot-water system to 40 C. Leave that system's native schedule intact.
    original_init = fr._FamilyLoop.init
    def init_with_background_hot_water(loop, exchange, state):
        ready = original_init(loop, exchange, state)
        if ready and not persona["appliances"]["water_heater"]["present"]:
            loop.h_ewh_sp = -1
        return ready
    fr._FamilyLoop.init = init_with_background_hot_water
    from energybridge.data.day_ahead import generate_runperiod_idf, read_facility_meter_steps, DayAheadPriceProfile
    from experiments.benchmark.run_persona_json import _write_persona_occupancy_idf
    idf = generate_runperiod_idf(UPSTREAM / "experiments/models/family_home/family_simple_3day.idf", job_dir / "assets", start_date=date(2007, 7, 1), days=1)
    _write_persona_occupancy_idf(idf, persona, 1)
    epw = UPSTREAM / "experiments/weather/epw/CHN_TJ_Tianjin.545270_CSWD.epw"
    write_json(job_dir / "persona_adapter.json", persona)
    provenance = {
        "schema_version": VERSION, "source_commit": "2b17ae63e613da776c93e900f5dace50d63a88a8",
        "runner_source_hash": file_hash(UPSTREAM / "experiments/benchmark/family_runner.py"),
        "adapter_hash": file_hash(__file__), "idf_hash": file_hash(idf), "epw_hash": file_hash(epw),
        "scenario": SCENARIO, "physical_parameters_source": "shared_research_assumptions",
        "engine_root": os.environ["EPLUS_ROOT"], "controller_method": mode,
        "consent_mode": "hypothetical_execution_gate_bypassed_not_consent_data",
        "score_mode": "deferred_to_web_human_no_synthetic_rating", "api_tuning": "upstream_defaults",
        "physical_adapter": "absent_controllable_EWH_keeps_native_background_hot_water_schedule",
        "planner_tariff": SCENARIO["tariff"],
        "training_release": False,
    }
    write_json(job_dir / "provenance.json", provenance)
    phases["prepare_seconds"] = time.perf_counter()-started
    progress("simulating")
    t = time.perf_counter()
    result = fr.run_family_agent(
        idf_path=idf, epw_path=epw, output_dir=job_dir / "simulation", weather_label="tianjin",
        appliance_config=persona["appliances"], persona_config=persona,
        user_pref=profile_text(profile), method=mode, sim_days=1, start_date="2007-07-01",
        human_mode=True, vpp_events_config=[SCENARIO["event"]], vpp_schedule_source=SCENARIO["id"],
        day_ahead_price_profile=DayAheadPriceProfile([], source=SCENARIO["tariff"]["id"], recurring_hour_prices={h:0.6 for h in range(24)}, price_unit="CNY/kWh (research assumption)"),
        pre_event_preference_callback=lambda *a, **k: profile_text(profile),
    )
    phases["eb_and_energyplus_seconds"] = time.perf_counter()-t
    raw = finite_json(result.as_dict())
    # Even the raw benchmark record has no pretend human score.
    write_json(job_dir / "benchmark_result.json", raw)
    progress("summarizing")
    write_json(job_dir / "phase_timing.json", phases)
    outcome = summarize(job_dir, raw)
    phases["llm_seconds"] = sum(c["seconds"] for c in calls)
    phases["non_llm_inside_eb_seconds"] = max(0, phases["eb_and_energyplus_seconds"]-phases["llm_seconds"])
    phases["worker_total_seconds"] = time.perf_counter()-started
    outcome.update(timings=phases, llm_calls=len(calls), llm_failed_calls=sum(not c.get("success", False) for c in calls))
    write_json(job_dir / "outcome.json", outcome)
    progress("complete")

def summarize(job_dir, raw):
    from energybridge.data.day_ahead import read_facility_meter_steps
    t = time.perf_counter()
    error_text = (job_dir / "simulation/eplusout.err").read_text(errors="replace")
    if "EnergyPlus Completed Successfully" not in error_text or re.search(r"\*\*\s+(Severe|Fatal)\s+\*\*", error_text):
        raise RuntimeError("energyplus_not_successful")
    calls = json.loads((job_dir / "llm_timing.json").read_text()) if (job_dir / "llm_timing.json").exists() else []
    if raw.get("method") == "agent" and not any(c.get("success") for c in calls):
        raise RuntimeError("no_successful_real_planner_call")
    meter = read_facility_meter_steps(job_dir / "simulation")
    if not meter:
        raise RuntimeError("facility_meter_missing")
    write_json(job_dir / "meter_steps.json", meter)
    trace = raw.get("daily_trace_rows", [])
    if not trace or len(raw.get("vpp_event_log", [])) != 1:
        raise RuntimeError("missing_trajectory_or_event")
    # Meter field names are checked rather than guessing units.
    # Cost below is computed directly from the verified facility energy meter.
    meter = [s for s in meter if 0 <= s["start_h"] < s["end_h"] <= 24]
    if abs(sum(s["end_h"]-s["start_h"] for s in meter)-24) > 0.01:
        raise RuntimeError("facility_meter_window_not_24_hours")
    energy = sum(float(s["kwh"]) for s in meter)
    event = raw["vpp_event_log"][0]
    event_energy = sum(s["kwh"] * max(0, min(s["end_h"], 19)-max(s["start_h"], 18))/(s["end_h"]-s["start_h"]) for s in meter)
    temps = [r["indoor_temperature_c"] for r in trace if 18 <= r["sim_h"] <= 19]
    decisions = event.get("day_decisions", [])
    actions = [{k: d[k] for k in ["h", "sp", "setpoint", "effective_setpoint", "actions", "raw_appliance_actions", "ac_mode"] if k in d} for d in decisions]
    actions = [d for d in actions if len(d) > 1]
    display = {
        "title": "本次安排的模拟结果", "basis": "假设采用本方案；请按全家人的取舍评价。",
        "window": "模拟当天 00:00—24:00，含 18:00—19:00 事件及其后恢复时段",
        "energy_kwh": round(energy, 3), "cost_cny": round(energy * 0.6, 2),
        "event_energy_kwh": round(event_energy, 4),
        "event_temperature_min_c": round(min(temps), 2), "event_temperature_max_c": round(max(temps), 2),
        "trajectory": trace,
        "actions": actions,
        "appliance_summary": event.get("appliance_summary", {}),
        "limitations": ["费用按情境中假设的统一电价计算。", "尚未计算同条件参考方案，因此不宣称省了多少电或钱。", "室温来自 EnergyPlus；洗衣任务完成情况来自 EB 设备模型。", "模型警告及控制一致性尚待审核，本页仅用于开发试填，不能作为正式调查材料。"],
    }
    return {"display": display, "display_hash": digest(display), "summary_seconds": time.perf_counter()-t,
            "engine_summary": error_text.splitlines()[-1], "physical_validation": "pilot_unvalidated", "training_release": False}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("job_dir", type=Path)
    parser.add_argument("--mode", choices=["agent", "no_dr"], default="agent")
    args = parser.parse_args()
    args.job_dir.mkdir(parents=True, exist_ok=True)
    try:
        run(args.job_dir, args.mode)
    except Exception as exc:
        # Persist the class and a credential-free traceback; do not echo provider response bodies.
        import traceback
        frames = [{"file": Path(f.filename).name, "line": f.lineno, "function": f.name} for f in traceback.extract_tb(exc.__traceback__)]
        write_json(args.job_dir / "failure.json", {"failure_type": type(exc).__name__, "frames": frames})
        print("PILOT_FAILED", type(exc).__name__, flush=True)
        raise SystemExit(1)

if __name__ == "__main__":
    main()
