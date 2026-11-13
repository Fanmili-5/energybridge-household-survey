"""Seeded household-routine timing around unchanged EB appliance primitives.

Exact clocks are experimental household-card reference schedules. They are not
observed diary times. Events, prices, outcomes and human answers are not inputs.
"""
import datetime as dt
import hashlib
import math
from ortools.sat.python import cp_model

VERSION = "eb.household_conditioned_daily_A.v2"

def daily_routine(household, date):
    day=dt.date.fromisoformat(date).weekday()
    return next(r for r in household["routine"]["daily_services"] if r["day"]==day)

def bind_routine(problem, household, reference):
    routine=daily_routine(household,problem["anchor"])
    chores=list(routine["flexible_chore_window"])
    dinners=[m["end"]%1440 for m in routine.get("meals",[]) if m["kind"]=="dinner" and m["location"]=="home"]
    dinner_end=max(dinners,default=chores[0])
    baths=[{"start":b["start"]%1440,"end":b["end"]%1440,"member_id":b["member_id"]} for b in routine.get("bathing_services",[])]
    if not baths:
        raise ValueError("A_BATHING_REFERENCE_MISSING")
    first=min(b["start"] for b in baths);last=max(b["end"] for b in baths)
    # Preserve the four-hour ordinary window, ensure at least one hour of lead
    # before the first bath. Later storage service is tested by thermal physics.
    duration=round((float(reference.get("WH_normal_end_h",21))-float(reference.get("WH_normal_start_h",17)))*60)
    if not 0<duration<=240:raise ValueError("A_UNSUPPORTED_ORDINARY_WH_WINDOW")
    end=math.ceil(min(last,first+duration-60)/10)*10
    start=max(0,end-duration);end=start+duration
    cfg=problem["native_appliance_configuration"]["water_heater"]
    cfg.update(normal_start_h=start/60,normal_end_h=end/60,bath_required_h=first/60)
    for row in problem["controls"]:
        if row["kind"]=="tank_setpoint":
            base=row["start_min"]//1440*1440
            row.update(start_min=base+start,end_min=base+end)
    for job in problem["jobs"]:
        lower=chores[0];upper=chores[1]
        if job["kind"]=="dishwasher":
            # Select an existing completed household meal that admits the full
            # same-day programme. This is an A construction choice, not a new
            # B admission rule or an observed dish-loading record.
            feasible=[m for m in routine.get("meals",[]) if m["location"]=="home" and (m["end"]%1440)+job["policy"]["duration_min"]<=job["deadline_min"]]
            if not feasible:raise ValueError("A_NO_COMPLETE_SAME_DAY_POST_MEAL_DISHWASHER_SLOT")
            chosen=max(feasible,key=lambda m:m["end"]%1440)
            release=chosen["end"]%1440
            job["A_routine_start_not_before_min"]=release
            job["A_reference_dish_load"]={"meal_kind":chosen["kind"],"meal_end_min":release,"participants":chosen.get("participants",[]),"status":"experimental_load_assignment_to_existing_reference_meal"}
            if chosen["kind"]=="dinner":lower=max(chores[0],release);upper=max(lower,chores[1])
            else:lower=release;upper=min(release+60,job["deadline_min"]-job["policy"]["duration_min"])
            problem["routine_binding_dish_load"]=job["A_reference_dish_load"]
        job["routine_preferred_start_window_min"]=[lower,max(lower,upper)]
        job["routine_timing_origin"]="frozen_household_reference_routine;soft_A_construction_target"
    problem["routine_binding"]=dict(version=VERSION,chore_start_window_min=chores,dinner_end_min=dinner_end,
        bathing=baths,ordinary_heater_window_min=[start,end],observed_diary=False,
        programme_window_policy="source_explicit_bounds_else_08:00_to_24:00;complete_same_day",
        heater_service_guaranteed_without_physics=False,manual_operation_fields_used=False,
        heater_window_command_grid_min=10,household_bathing_clocks_modified=False)
    problem["input_lineage"].update(A_method=VERSION,
        window_default_change="22:00 implicit default replaced by explicit same-day 24:00 completion;reference bounds preserved",
        exact_routine_clocks="frozen experimental household card")
    return problem

def solve_programmes(problem, seed):
    model=cp_model.CpModel();starts={};ends={};intervals={};costs=[];anchors={}
    identity=f"{seed}:{problem['household_id']}:{problem['anchor']}"
    for job in problem["jobs"]:
        lo=math.ceil(job["release_min"]/10)*10
        hi=min(job["deadline_min"]-job["policy"]["duration_min"],1439)
        domain=list(range(lo,math.floor(hi/10)*10+1,10))
        if not domain:return None,{"reason":"EMPTY_NATIVE_PROGRAMME_DOMAIN","need_id":job["need_id"]}
        key=job["need_id"];start=model.NewIntVarFromDomain(cp_model.Domain.FromValues(domain),key)
        end=model.NewIntVar(0,1440,key+":end");model.Add(end==start+job["policy"]["duration_min"])
        if "A_routine_start_not_before_min" in job:model.Add(start>=job["A_routine_start_not_before_min"])
        starts[key]=start;ends[key]=end
        intervals[key]=model.NewIntervalVar(start,job["policy"]["duration_min"],end,key+":interval")
        preferred=job["routine_preferred_start_window_min"]
        targets=list(range(math.ceil(preferred[0]/10)*10,math.floor(preferred[1]/10)*10+1,10)) or [preferred[0]]
        target=targets[int(hashlib.sha256((identity+":"+job["kind"]).encode()).hexdigest()[:16],16)%len(targets)]
        anchors[key]=target
        # Dryer timing follows its declared same-load parent, rather than an
        # independent chore anchor that could force washing before the family routine.
        if not job.get("depends_on_need_id"):
            entries=[(x,abs(x-target)*1000000+int(hashlib.sha256(f"{identity}:{key}:{x}".encode()).hexdigest()[:8],16)%1000) for x in domain]
            cost=model.NewIntVar(0,2000000000,key+":routine_cost");model.AddAllowedAssignments([start,cost],entries);costs.append(cost)
    for job in problem["jobs"]:
        parent=job.get("depends_on_need_id")
        if parent:
            model.Add(starts[job["need_id"]]>=ends[parent])
            wait=model.NewIntVar(0,1440,job["need_id"]+":wait")
            model.Add(wait==starts[job["need_id"]]-ends[parent]);costs.append(wait*1000000)
    for asset in {j["asset_id"] for j in problem["jobs"]}:
        model.AddNoOverlap([intervals[j["need_id"]] for j in problem["jobs"] if j["asset_id"]==asset])
    model.Minimize(sum(costs))
    solver=cp_model.CpSolver();solver.parameters.num_search_workers=1
    solver.parameters.max_deterministic_time=5.0
    status=solver.Solve(model)
    if status!=cp_model.OPTIMAL:return None,{"reason":"A_OPTIMAL_ROUTINE_SCHEDULE_NOT_ESTABLISHED","solver_status":solver.StatusName(status)}
    tasks=[]
    for job in problem["jobs"]:
        tasks.append(dict(task_id=job["need_id"],need_id=job["need_id"],asset_id=job["asset_id"],kind=job["kind"],
            start_min=solver.Value(starts[job["need_id"]]),end_min=solver.Value(ends[job["need_id"]]),
            power_kw=problem["native_appliance_configuration"][job["kind"]]["power_kw"],
            **({"depends_on_need_id":job["depends_on_need_id"]} if job.get("depends_on_need_id") else {})))
    return tasks,dict(method=VERSION,solver_status=solver.StatusName(status),soft_target_start_min=anchors,
        events_prices_outcomes_answers_used=False,source_programme_parameters_modified=False)
