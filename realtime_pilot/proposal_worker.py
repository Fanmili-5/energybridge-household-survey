"""One bounded EB planning call; does not run EP or fabricate forecasts/consent."""
import json
import os
from pathlib import Path
import sys
import time
from common import ROOT, UPSTREAM, digest, file_hash, profile_text, write_json
from proposal_contract import CONTEXT, VERSION, executable, pair_display, validate_offer

def run(folder):
    started = time.perf_counter()
    request = json.loads((folder / "request.json").read_text())
    from runtime_config import load_model_environment
    load_model_environment()
    sys.path.insert(0, str(UPSTREAM))
    from energybridge.harness.planning import build_planning_prompts, evaluate_planning_response
    from energybridge.llm.client import LLMClient
    original = request["original_plan"]
    state = {"current_hod": 16, "ordinary_plan": executable(original),
             "device_capabilities": original["devices"],
             "action_contract": {"required_shape": executable(original),
                 "rules": ["Only the exact keys in required_shape are allowed. All keys must be retained.",
                    "Only change numeric setpoint (20 to 30 Celsius) and active task start times.",
                    "AC change applies only at 18:00-19:00 then restores original setpoint.",
                    "No task cancellation or duration changes. Start >= earliest_h; finish <= deadline_h.",
                    "Do not add devices. Unused and unchanged devices stay unchanged.",
                    "Ordinary plan is frozen and participant-confirmed. Keeping it unchanged is valid.",
                    "No EP forecasts are available. Do not invent energy, price savings, or room temperatures."]}}
    # Scheduled event overlap is a fact about the plan, not an energy forecast.
    state["ordinary_task_event_overlap_hours"] = {
        d: max(0, min(r["start_h"] + r["duration_h"], 19) - max(r["start_h"], 18))
        for d, r in original["devices"].items() if r.get("active") and "start_h" in r
    }
    inputs = {"observable_state": state,
              "observable_profile": request.get("observable_profile") or {"household_answers": profile_text(request["profile"])},
              "memory": {}, "event": {**CONTEXT, **CONTEXT["event"],
                  "planning_goal": "Propose a feasible response to reduce activity during 18:00-19:00 while respecting household needs. Consider moving active independent tasks outside that window within their confirmed earliest/deadline bounds. Keeping P0 is valid when no supported change is suitable. Reduced schedule overlap is not quantified energy or cost savings."}}
    system, user = build_planning_prompts(**inputs)
    system += "\nThis questionnaire adapter has a strict action contract in observable_state. The plan must contain ONLY the keys in required_shape; omit all metadata from plan. Use candidate_id for each candidate. Write explanations in Chinese."
    write_json(folder / "planning_input.json", {"inputs": inputs, "system_prompt": system, "user_prompt": user})
    write_json(folder / "progress.json", {"stage": "planning", "llm_calls_started": 1, "llm_calls_completed": 0})
    response = LLMClient().chat_with_metrics(system, user, max_retries=1, response_format={"type": "json_object"})
    write_json(folder / "planning_response.json", response)
    evaluation = evaluate_planning_response(response["text"], **inputs)
    write_json(folder / "planning_audit.json", evaluation)
    selected = evaluation["selected_executable_plan"]
    # EB attaches explanatory metadata after validation. Retain it in the audit,
    # but separate it from controls; never strip an unknown executable field.
    controls = {k: v for k, v in selected.items() if k != "strategy_explanation"} if isinstance(selected, dict) else selected
    plan = validate_offer(original, controls)
    display = pair_display(original, plan, request["baseline_source"])
    result = {"schema_version": VERSION, "task": "plan_judgement", "original_plan": original,
              "original_plan_hash": digest(original), "proposal_plan": plan, "proposal_plan_hash": digest(plan),
              "display": display, "display_hash": digest(display),
              "execution_status": "not_run", "forecast_status": "not_run",
              "timings": {"worker_total_seconds": round(time.perf_counter() - started, 3),
                          "llm": response["metrics"]},
              "provenance": {"integration": "EB build_planning_prompts + evaluate_planning_response; questionnaire action adapter",
                 "upstream_commit": "2b17ae63e613da776c93e900f5dace50d63a88a8",
                 "planning_source_sha256": file_hash(UPSTREAM / "energybridge/harness/planning.py"),
                 "adapter_sha256": file_hash(__file__), "contract_sha256": file_hash(ROOT / "proposal_contract.py"),
                 "questionnaire_version": request.get("questionnaire_version"),
                 "questionnaire_hash": digest(request.get("questionnaire_snapshot", [])),
                 "questionnaire_adapter_sha256": file_hash(ROOT / "questionnaire_persona.py"),
                 "ordinary_plan_source": request["baseline_source"], "is_full_benchmark": False}}
    write_json(folder / "outcome.json", result)
    write_json(folder / "progress.json", {"stage": "complete", "llm_calls_started": 1, "llm_calls_completed": 1})

if __name__ == "__main__":
    folder = Path(sys.argv[1])
    try:
        run(folder)
    except Exception as exc:
        # Do not expose API exception strings, which can include request/provider details.
        write_json(folder / "failure.json", {"stage": "proposal", "error_type": type(exc).__name__, "status": "no_validated_proposal"})
        print("Proposal generation failed; see structured audit.")
        sys.exit(1)
