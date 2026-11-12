# Dated EB appliance plans

## Authoritative contract

The user's2026-11-10 correction is authoritative. Keep1000 frozen households and ten independent dates per household. Each present relevant appliance has its daily service. All ACs remain controlled. Preserve household source facts, country quotas and the six roles.

The active model uses the original EnergyBridge appliance-call interface: complete programme start_h, AC setpoints, WH preheat window/temperature, and EV charge window/departure target. It has no loading/retrieval operations, human operation duration, preloading deadline or retrieval wait. The former daily_problem compiler explicitly rejects stale callers. Legacy generic life schedulers remain for their own historical protocols and cannot define native EB inputs.

Only EV may cross midnight. Washer/dryer/dishwasher must run one complete programme and finish on the same calendar date. WH windows finish on their date. AC baseline schedules are split by calendar date. The UI91 view remains08:00 to next08:00, retaining the full EV connection/departure tail where required. This does not require every programme to be allowed after midnight.

## Source map

| Rule | Source |
| --- | --- |
| One complete programme/day; explicit commands even for fixed devices | Pinned original EB native appliance and main method |
| A samples inside allowed device windows without VPP information | Exact original _schedule_no_dr_routine_appliances |
| Programme windows default08–22 when the reference supplies no override | Original EB constructor/routine defaults |
| Programme duration/power and WH55C reference | Existing frozen hardware/resource reference, not an observed household use trace |
| EV arrival/connection/SOC/target/capacity/charger/efficiency | Frozen household reference input, instantiated as a given connected episode |
| Existing explicit washer-before-dryer requirement or a shared physical asset | Existing household service/asset declarations; no invented manual transfer |
| No non-EV overnight; no fabricated handling | User2026-11-10 narrower benchmark contract |
| Charging must meet departure target | Original EB main-method service rule; checked against B's literal commands |

Public EB commit:2b17ae63e613da776c93e900f5dace50d63a88a8.
Routine:https://github.com/Agentic-Intelligence-Lab/EnergyBridge/blob/2b17ae63e613da776c93e900f5dace50d63a88a8/experiments/benchmark/family_runner.py#L3734-L3787
Departure rule:https://github.com/Agentic-Intelligence-Lab/EnergyBridge/blob/2b17ae63e613da776c93e900f5dace50d63a88a8/experiments/benchmark/family_runner.py#L3817-L3871
Native interface:https://github.com/Agentic-Intelligence-Lab/EnergyBridge/blob/2b17ae63e613da776c93e900f5dace50d63a88a8/energybridge/simulation/appliance_sim.py

## Algorithm

1. Bind frozen household devices, fixed/control permissions, comfort and EV input to declared native configurations. Manual chore windows are not consulted. Household occupancy remains available for comfort evaluation, and is not fabricated or used as a blanket prohibition on native AC setpoint commands.
2. Call the exact copied original no-DR routine. Map sampled starts conservatively onto the declared10min command grid. Rejection-sample only for an explicitly declared shared asset or programme order; never delete a required programme. Both the wrapper and this conditioning are benchmark adapters, not changes to the upstream routine.
3. Produce A with complete programmes, ordinary thermal controls and a single EV permission window. Use the original native EV simulator for A energy bins at given arrival SOC. The selected episode has no invented driving trajectory.
4. Build B from literal native start-time, temperature and continuous EV-window changes. No loading/retrieval patches or operation-time variants exist. WH uses one explicit native preheat window/temperature per date, within45–75C and the bound hardware maximum; windows that the original applier would shorten are rejected. Candidate windows are drawn from EB normal/preheat templates and declared timing levels, rather than arbitrary piecewise tank schedules. Every requested programme retains its identity and full duration. Fixed services remain fixed.
5. Validate B commands against the original native semantics, including automatic VPP avoidance of explicit EV windows. Reject shortfall at departure and arbitrary interruptions. A control window is not evidence of target satisfaction: rederive positive energy from B's own commands and given state.
6. Select one B per dated question before actual physical outcomes/human answers are available. Keep candidate/rejection evidence. Verify final exports, not only internal candidates.
7. Separately execute the matched A/B physical cases and project verified consequences into original UI91. Command acceptance alone is not a room-temperature, hot-water or whole-house physical acceptance.

## Entrypoints and invariants

Canonical A:benchmark.ab_generation.v9_date_adapter.generate_day_baseline.
A batch:python -m benchmark.ab_generation.daily_batch.
Native implementation:eb_primary.py;B grammar:eb_primary_candidates.py.
The source/native file is explicitly supplied and SHA256-checked. The sampler source in upstream_eb_routine.py is copied unmodified. A's seed is bound to household/date and does not consume VPP, tariff, B, physical outcome or labels.

fresh_context translates release_min,deadline_min,start_window_min and any exact_source_release_min together when changing time origin. Duration and within-day machine clock windows are not translated.

The former117-cell coverage contract included fabricated handling dimensions and is superseded. Native mechanism/role/class coverage must be reported under the new command domain. Never reuse a historical diagnostic search as a formal coverage pass. Frozen source data and old results retain their own hashes; none are silently overwritten.
