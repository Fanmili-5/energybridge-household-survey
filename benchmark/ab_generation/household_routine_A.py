"""Ordinary A from frozen life tasks and pinned EB programme parameters.

No event, future outcome, B or human label is used. The 22:00 preference is
an explicit benchmark A construction rule, never a B admission restriction.
"""
import datetime as dt
import hashlib
import math
from ortools.sat.python import cp_model

VERSION = "eb.household_conditioned_daily_A.v5_original_EB_programmes"

def daily_routine(household,date):
    return next(r for r in household["routine"]["daily_services"] if r["day"]==dt.date.fromisoformat(date).weekday())

def bind_routine(problem,household,reference):
    routine=daily_routine(household,problem["anchor"])
    chores=list(routine["flexible_chore_window"])
    baths=[dict(start=b["start"]%1440,end=b["end"]%1440,member_id=b["member_id"]) for b in routine.get("bathing_services",[])]
    if not baths:raise ValueError("A_BATHING_REFERENCE_MISSING")
    first=min(b["start"] for b in baths);last=max(b["end"] for b in baths)
    duration=round((float(reference.get("WH_normal_end_h",21))-float(reference.get("WH_normal_start_h",17)))*60)
    if not 0<duration<=240:raise ValueError("A_UNSUPPORTED_ORDINARY_WH_WINDOW")
    end=math.ceil(min(last,first+duration-60)/10)*10
    start=max(0,end-duration);end=start+duration
    problem["native_appliance_configuration"]["water_heater"].update(normal_start_h=start/60,normal_end_h=end/60,bath_required_h=first/60)
    for row in problem["controls"]:
        if row["kind"]=="tank_setpoint":
            base=row["start_min"]//1440*1440
            row.update(start_min=base+start,end_min=base+end)
    role=household["role_id"].split("_")[1]
    policy=reference["ordinary_A"]
    wm_target=round(policy["washer_preferred_h_by_EB_role"][role]*60)
    weekday=dt.date.fromisoformat(problem["anchor"]).weekday()
    # Day-off timing is an explicit reference preference, not a measured diary.
    adult_ids={m["id"] for m in household["members"] if m["reference_age"]>=18}
    away=[e for e in household["calendar"]["weekly_events"] if e["member_id"] in adult_ids and e["location"]=="away"]
    def home(t):
        abs_t=weekday*1440+t
        return any(not any(e["member_id"]==mid and e["start"]<=abs_t<e["end"] for e in away) for mid in adult_ids)
    if weekday>=5 and any(home(t) for t in range(540,720,10)):
        wm_target=policy["day_off_morning_target_min"]
    by_kind={t["kind"]:t for t in problem["task_context"]["tasks"]}
    for job in problem["jobs"]:
        task=by_kind[job["kind"]]
        job["A_ordinary_completion_preferred_min"]=policy["soft_completion_preferred_min"]
        job["A_home_context_start_minutes"]=[t for t in range(480,1440,10) if home(t)]
        if job["kind"]=="dishwasher":
            # The named source is the actual load. A breakfast load must not
            # be held until an unrelated dinner anchor by this constructor.
            events=task["source_events"]
            exact_ready=max(e["end_min"] for e in events)
            anchor=dict(meal_kind=task["source_meal"],meal_end_min=exact_ready,
                        source_day_offset=task["source_day_offset"],
                        source_event_ids=[e["event_id"] for e in events],
                        status="same_frozen_meal_batch_as_A_and_B")
            job["A_routine_meal_anchor"]=anchor
            problem["routine_meal_anchor"]=anchor
            job["A_routine_start_not_before_min"]=task["ready_min"]
            lower=max(540,task["ready_min"])
            job["routine_preferred_start_window_min"]=[lower,lower+30]
            job["routine_timing_origin"]="named_frozen_meal_batch;morning_if_already_ready_else_soon_after_actual_meal"
        elif job["kind"]=="washer":
            job["routine_preferred_start_window_min"]=[max(480,wm_target-30),wm_target+30]
            job["routine_timing_origin"]="pinned_EB_role_normal_time_with_household_day_off_context;soft_preference"
        else:
            job["routine_preferred_start_window_min"]=[wm_target,wm_target]
            job["routine_timing_origin"]="same_load_after_current_washer;no_independent_late_dryer_anchor"
    problem["routine_binding"]=dict(version=VERSION,chore_start_window_min=chores,
        bathing=baths,ordinary_heater_window_min=[start,end],observed_diary=False,
        programme_window_policy="reference_programme_earliest_to_same_day24;complete_same_day",
        ordinary_A_completion_preferred_min=policy["soft_completion_preferred_min"],
        A_completion_preference_is_B_legality_rule=False,
        programme_duration_and_power_source=reference["programme_parameter_origin"],
        dishwasher_anchor_policy="actual_frozen_batch;not_later_unrelated_dinner",
        heater_service_guaranteed_without_physics=False,manual_operation_fields_used=False,
        heater_window_command_grid_min=10,household_bathing_clocks_modified=False)
    problem["input_lineage"].update(A_method=VERSION,
        exact_routine_clocks="frozen experimental household card",
        programme_reference="original_EB_config_120_90_90_minutes",
        A_ordinary_finish="22h soft construction preference only;never rejects a B")
    from .task_context import attach
    return attach(problem)

def solve_programmes(problem,seed,*,deterministic_time=5.0):
    if isinstance(deterministic_time,bool) or not isinstance(deterministic_time,(int,float)) or not math.isfinite(deterministic_time) or deterministic_time<=0:
        raise ValueError("INVALID_A_DETERMINISTIC_TIME")
    model=cp_model.CpModel();starts={};ends={};intervals={};costs=[];late_costs=[];anchors={}
    identity=f"{seed}:{problem['household_id']}:{problem['anchor']}"
    for job in problem["jobs"]:
        lo=math.ceil(job["release_min"]/10)*10
        hi=min(job["deadline_min"]-job["policy"]["duration_min"],1439)
        domain=list(range(lo,math.floor(hi/10)*10+1,10))
        if not domain:return None,dict(reason="EMPTY_NATIVE_PROGRAMME_DOMAIN",need_id=job["need_id"],solver_status="INFEASIBLE",proof_scope="empty_declared_programme_domain")
        key=job["need_id"]
        start=model.NewIntVarFromDomain(cp_model.Domain.FromValues(domain),key)
        end=model.NewIntVar(0,1440,key+":end")
        model.Add(end==start+job["policy"]["duration_min"])
        if "A_routine_start_not_before_min" in job:model.Add(start>=job["A_routine_start_not_before_min"])
        starts[key]=start;ends[key]=end
        intervals[key]=model.NewIntervalVar(start,job["policy"]["duration_min"],end,key+":interval")
        pref=job["routine_preferred_start_window_min"]
        targets=list(range(math.ceil(pref[0]/10)*10,math.floor(pref[1]/10)*10+1,10)) or [pref[0]]
        target=targets[int(hashlib.sha256((identity+":"+job["kind"]).encode()).hexdigest()[:16],16)%len(targets)]
        anchors[key]=target
        late=model.NewIntVar(0,1440,key+":ordinary_late")
        model.AddMaxEquality(late,[0,end-job["A_ordinary_completion_preferred_min"]])
        late_costs.append(late)
        if not job.get("depends_on_need_id"):
            home=set(job["A_home_context_start_minutes"])
            entries=[(x,(abs(x-target)+(0 if x in home else 30))*1000000+int(hashlib.sha256(f"{identity}:{key}:{x}".encode()).hexdigest()[:8],16)%1000) for x in domain]
            cost=model.NewIntVar(0,2000000000,key+":routine_cost")
            model.AddAllowedAssignments([start,cost],entries);costs.append(cost)
    for job in problem["jobs"]:
        parent=job.get("depends_on_need_id")
        if parent:
            model.Add(starts[job["need_id"]]>=ends[parent])
            wait=model.NewIntVar(0,1440,job["need_id"]+":wait")
            model.Add(wait==starts[job["need_id"]]-ends[parent]);costs.append(wait*1000000)
    for asset in {j["asset_id"] for j in problem["jobs"]}:
        model.AddNoOverlap([intervals[j["need_id"]] for j in problem["jobs"] if j["asset_id"]==asset])
    # The weight exceeds every possible routine-distance cost in this small
    # daily model. Late completion is avoided whenever source facts allow it.
    model.Minimize(sum(late_costs)*10000000000+sum(costs))
    solver=cp_model.CpSolver();solver.parameters.num_search_workers=1
    solver.parameters.max_deterministic_time=float(deterministic_time)
    status=solver.Solve(model)
    if status!=cp_model.OPTIMAL:
        return None,dict(reason="A_PROGRAMME_MODEL_PROVEN_INFEASIBLE" if status==cp_model.INFEASIBLE else "A_SEARCH_NOT_PROVEN_OPTIMAL",
                         solver_status=solver.StatusName(status),deterministic_time_budget=float(deterministic_time),optimal_baseline_required=True)
    tasks=[]
    for job in problem["jobs"]:
        tasks.append(dict(task_id=job["need_id"],need_id=job["need_id"],asset_id=job["asset_id"],kind=job["kind"],
            start_min=solver.Value(starts[job["need_id"]]),end_min=solver.Value(ends[job["need_id"]]),
            power_kw=problem["native_appliance_configuration"][job["kind"]]["power_kw"],
            **({"depends_on_need_id":job["depends_on_need_id"]} if job.get("depends_on_need_id") else {})))
    return tasks,dict(method=VERSION,solver_status=solver.StatusName(status),soft_target_start_min=anchors,
        A_programme_minutes_after22=sum(solver.Value(x) for x in late_costs),
        events_prices_outcomes_answers_used=False,source_programme_parameters_modified=False)
