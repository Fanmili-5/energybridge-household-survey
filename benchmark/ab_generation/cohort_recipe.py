"""Portable cohort allocation and explicit archived-choice reconstruction.

The solver never reads the archived choices. Reconstruction replays those
declared choices from candidate patches; it is not independent regeneration.
No physical engine, model API, answer store or online service is called.
"""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
import gzip
import hashlib
import json
import math
from pathlib import Path
import platform
import shutil
import time

from .common import digest
from .cohort_coverage import simple_tokens
from .candidate_completion import qualified

SCHEMA = "eb.portable_cohort_recipe.v1"


def read(path):
    path = Path(path)
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            return json.load(stream)
    return json.loads(path.read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".gz":
        payload=json.dumps(value,ensure_ascii=False,separators=(",", ":")).encode("utf-8")
        with path.open("wb") as output:
            with gzip.GzipFile(filename="",mode="wb",fileobj=output,mtime=0) as stream:
                stream.write(payload)
    else:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def local(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError("PATH_OUTSIDE_RECIPE:" + str(relative))
    return path


def verify(bundle, *, historical=False):
    bundle = Path(bundle).resolve()
    manifest = read(bundle / "MANIFEST.json")
    if manifest["schema"] != SCHEMA:
        raise ValueError("UNSUPPORTED_COHORT_RECIPE")
    if digest({k:v for k,v in manifest.items() if k != "manifest_sha256"}) != manifest["manifest_sha256"]:
        raise ValueError("RECIPE_MANIFEST_CHANGED")
    for name, expected in manifest["files"].items():
        if not historical and name == manifest["historical_choices"]:
            continue
        if sha(local(bundle, name)) != expected:
            raise ValueError("RECIPE_FILE_CHANGED:" + name)
    return manifest


def freeze(batch, households, required, opportunity, out):
    """Export immutable upstream candidates and an explicitly labelled choice lock.

    The original B plans are not exported. Their candidate IDs are archived
    for historical replay only; the fresh solver does not open that file.
    """
    batch, households, out = Path(batch).resolve(), Path(households).resolve(), Path(out).resolve()
    if out.exists():
        raise FileExistsError(out)
    out.mkdir(parents=True)
    cases_raw = households.read_bytes()
    case_rows = [json.loads(line) for line in cases_raw.splitlines() if line.strip()]
    cases = {c["case_id"]:c for c in case_rows}
    if not cases or len(cases)!=len(case_rows):
        raise ValueError("DUPLICATE_OR_EMPTY_SOURCE_HOUSEHOLDS")
    source_keys={(c["source"]["dataset"],c["source"]["household_key"]) for c in case_rows}
    if len(source_keys)!=len(case_rows):
        raise ValueError("DUPLICATE_SURVEY_SOURCE_RECORD")
    indexes = [json.loads(line) for line in (batch / "PAIR_INDEX.jsonl").read_text().splitlines() if line.strip()]
    if len({(r["case_id"],r["date"]) for r in indexes}) != len(indexes):
        raise ValueError("DUPLICATE_UPSTREAM_SLOT")
    by_house = defaultdict(list)
    for row in indexes:
        by_house[row["index"]].append(row)
    if {r["case_id"] for r in indexes} != set(cases):
        raise ValueError("HOUSEHOLD_AND_BATCH_SOURCE_SET_MISMATCH")
    basics = read(required) if required else {}
    eligible = read(opportunity)["eligibility"] if opportunity else {}
    (out / "households.jsonl").write_bytes(cases_raw)
    configuration = read(batch / "PRE_RUN.json")["configuration"]
    write(out / "CONFIGURATION.json", configuration)
    files = {"households.jsonl":sha(out/"households.jsonl"),
             "CONFIGURATION.json":sha(out/"CONFIGURATION.json")}
    houses, choices = [], []
    copied = set()
    def copy_context(relative):
        if relative in copied:return
        copied.add(relative)
        source = local(batch, relative)
        destination = local(out / "contexts", relative)
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            files[str(destination.relative_to(out))] = sha(destination)
    for index, slots in sorted(by_house.items()):
        slots.sort(key=lambda r:r["date"])
        cid = slots[0]["case_id"]
        if any(row["case_id"] != cid for row in slots):
            raise ValueError("UPSTREAM_INDEX_HAS_MULTIPLE_HOUSEHOLDS")
        case = cases[cid]
        folder = batch / f"{index:04}"
        initial = read(folder / "SELECTION.json.gz")["selected_ids"]
        rows = {}
        catalogue_files = [folder / "CATALOGUES.json.gz"]
        if (folder / "COVERAGE_EXTRA_CANDIDATES.json.gz").exists():
            catalogue_files.append(folder / "COVERAGE_EXTRA_CANDIDATES.json.gz")
        for source in catalogue_files:
            for day in read(source):
                for row in day["rows"]:
                    if not qualified(row):
                        continue
                    if row["date"] not in {r["date"] for r in slots}:
                        raise ValueError("CANDIDATE_OUTSIDE_DECLARED_DATES")
                    if row["id"] in rows:
                        if rows[row["id"]]["patches"] != row["patches"] or rows[row["id"]].get("scene_context_relative_path") != row.get("scene_context_relative_path"):
                            raise ValueError("CANDIDATE_ID_COMMAND_COLLISION")
                        continue
                    rows[row["id"]] = row
                    copy_context(row.get("scene_context_relative_path",
                                         f"{index:04}/{row['date']}_A.json.gz"))
        if not set(initial) <= set(rows):
            raise ValueError("INITIAL_SELECTION_NOT_IN_UPSTREAM_POOL")
        metadata = []
        for item in slots:
            date = item["date"]
            copy_context(f"{index:04}/{date}_A.json.gz")
            context = read(local(batch, item["context_relative_path"]))
            if sha(local(batch,item["relative_path"])) != item["pair_file_sha256"]:
                raise ValueError("UPSTREAM_PAIR_CHANGED")
            # Only the candidate ID is extracted; no final A/B plan is copied.
            pair = read(local(batch, item["relative_path"]))
            selected = pair["selected_proposal"]["id"]
            if selected not in rows:
                raise ValueError("ARCHIVED_CHOICE_OUTSIDE_CANDIDATE_POOL")
            expected_context = rows[selected].get("scene_context_relative_path",f"{index:04}/{date}_A.json.gz")
            if expected_context != item["context_relative_path"]:
                raise ValueError("ARCHIVED_CHOICE_CONTEXT_COLLISION")
            if digest(context["context"]) != item["context_sha256"]:
                raise ValueError("UPSTREAM_CONTEXT_CHANGED")
            choices.append(dict(index=index,date=date,candidate_id=selected))
            metadata.append(dict(date=date,A_sha256=item["A_sha256"],
                                 task_context_sha256=item["task_context_sha256"],
                                 reviewed_A_file_sha256=item.get("reviewed_A_file_sha256"),
                                 reviewed_A_index_sha256=item.get("reviewed_A_index_sha256")))
        wrapped=[dict(row=row,tokens=sorted(simple_tokens(row)))
                 for row in sorted(rows.values(),key=lambda r:r["id"])]
        initial_tokens=sorted({t for w in wrapped if w["row"]["id"] in set(initial) for t in w["tokens"]})
        if str(index) not in basics:basics[str(index)]={"required":initial_tokens}
        if not set(basics[str(index)]["required"])<=set(initial_tokens):
            raise ValueError("BASE_TOKENS_NOT_SUPPORTED_BY_INITIAL_SELECTION")
        names={"AC":"ac","WM":"washer","DR":"dryer","DW":"dishwasher","WH":"water_heater","EV":"ev"}
        controls={names[f] for f in case["household"]["controlled_function_ids"]}
        if str(index) not in eligible:
            witnessed={c["family"] for row in rows.values() for c in row["components"]}
            missing=controls-witnessed
            for family in missing:
                if not all(prove_no_event_opportunity(read(local(batch,f"{index:04}/{r['date']}_A.json.gz")),family) for r in slots):
                    raise ValueError("FUNCTION_GAP_NEEDS_CANDIDATE_COMPLETION:"+family)
            eligible[str(index)]={"required_functions":sorted(controls-missing),
                                  "proven_no_evening_event_opportunity":sorted(missing)}
        if set(eligible[str(index)]["required_functions"])|set(eligible[str(index)]["proven_no_evening_event_opportunity"])!=controls:
            raise ValueError("CONTROL_INVENTORY_AND_OPPORTUNITY_CONTRACT_DIFFER")
        pack = dict(index=index,case_id=cid,country=case["household"]["country"],
                    role=case["household"]["role_id"],slots=metadata,
                    initial_selected_ids=initial,
                    protected_tokens=basics[str(index)]["required"],
                    required_functions=eligible[str(index)]["required_functions"],
                    proven_no_event_opportunity=eligible[str(index)]["proven_no_evening_event_opportunity"],
                    rows=wrapped)
        relative = f"candidates/{index:04}.json.gz"
        write(out / relative, pack); files[relative] = sha(out/relative)
        houses.append(dict(index=index,case_id=cid,role=pack["role"],country=pack["country"],path=relative))
        if len(houses)%100 == 0:
            print(json.dumps(dict(phase="freeze",households=len(houses))),flush=True)
    write(out / "HISTORICAL_CHOICES.json",dict(
        schema="eb.archived_discrete_choices.v1",
        scope="archived choice replay,not an independent solver run",
        choices=sorted(choices,key=lambda r:(r["index"],r["date"]))))
    files["HISTORICAL_CHOICES.json"] = sha(out/"HISTORICAL_CHOICES.json")
    manifest = dict(schema=SCHEMA,households=len(houses),pairs=len(indexes),
                    household_source_sha256=hashlib.sha256(cases_raw).hexdigest(),
                    houses=houses,files=files,historical_choices="HISTORICAL_CHOICES.json",
                    original_native_source_sha256="be072673de26228a286e5ab9223d160a2a71084fa7b6c9146dbc5d024a879de9",
                    final_B_plan_files_included=False,
                    archived_choices_are_reproduction_inputs=True,
                    producer_configuration="CONFIGURATION.json")
    manifest["manifest_sha256"] = digest(manifest)
    write(out / "MANIFEST.json",manifest)
    return manifest


def allocate(packs, *, deterministic_time=60, seed=20261116):
    """Fresh CP-SAT solve; accepts no archived/final choice parameter."""
    from ortools.sat.python import cp_model
    import ortools
    if isinstance(deterministic_time,bool) or not math.isfinite(deterministic_time) or deterministic_time <= 0:
        raise ValueError("INVALID_ALLOCATION_BUDGET")
    candidates, by_slot, by_token, by_function, by_cell = [], defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
    initial = set()
    for house in sorted(packs,key=lambda h:h["index"]):
        initial.update(house["initial_selected_ids"])
        for wrapped in sorted(house["rows"],key=lambda w:w["row"]["id"]):
            row=wrapped["row"];j=len(candidates);candidates.append((house["index"],row))
            by_slot[(house["index"],row["date"])].append(j)
            for token in wrapped["tokens"]:by_token[(house["index"],token)].append(j)
            for family in sorted({c["family"] for c in row["components"]}):
                by_function[(house["index"],family)].append(j)
            for cell in sorted(row["raw_root_cells"]):
                by_cell[(cell,house["country"])].append(j)
    expected={(h["index"],s["date"]) for h in packs for s in h["slots"]}
    if set(by_slot) != expected or len(expected) != sum(len(h["slots"]) for h in packs):
        raise ValueError("ALLOCATION_SLOT_SET_CHANGED")
    model=cp_model.CpModel()
    x=[model.new_bool_var("r"+str(i)) for i in range(len(candidates))]
    for slot in sorted(by_slot):
        model.add_exactly_one(x[j] for j in by_slot[slot])
    for h in sorted(packs,key=lambda h:h["index"]):
        for token in sorted(h["protected_tokens"]):
            js=by_token[(h["index"],token)]
            if not js:raise ValueError("PROTECTED_TOKEN_HAS_NO_CANDIDATE")
            model.add(sum(x[j] for j in js)>=1)
        for family in sorted(h["required_functions"]):
            js=by_function[(h["index"],family)]
            if not js:raise ValueError("REQUIRED_FUNCTION_HAS_NO_CANDIDATE")
            model.add(sum(x[j] for j in js)>=1)
    roots=sorted({key for key,country in by_cell})
    repetitions=[]
    for number,key in enumerate(roots):
        hits=[]
        for cell,country in sorted(by_cell):
            if cell!=key:continue
            hit=model.new_bool_var(f"cell{number}_{country}")
            model.add_max_equality(hit,[x[j] for j in by_cell[(cell,country)]])
            hits.append(hit)
        model.add(sum(hits)>=1)
        rep=model.new_int_var(0,min(2,len(hits)),"rep"+str(number))
        model.add_min_equality(rep,[2,sum(hits)]);repetitions.append(rep)
    replacements=sum(x[j] for j,(_,r) in enumerate(candidates) if r["id"] not in initial)
    model.maximize(sum(repetitions)*(len(expected)+1)-replacements)
    for j,(_,row) in enumerate(candidates):
        model.add_hint(x[j],int(row["id"] in initial))
    solver=cp_model.CpSolver()
    solver.parameters.num_search_workers=1
    solver.parameters.random_seed=seed
    solver.parameters.max_deterministic_time=deterministic_time
    status=solver.solve(model)
    result=dict(status=solver.status_name(status),seed=seed,
                deterministic_time=deterministic_time,workers=1,
                ortools_version=ortools.__version__,python=platform.python_version(),
                candidate_rows=len(candidates),slots=len(expected),root_cells=len(roots),
                protected_coverage_is_hard=True,archived_choices_read=False,
                scope="fresh allocation from frozen upstream candidate pool;not candidate regeneration")
    if status not in (cp_model.OPTIMAL,cp_model.FEASIBLE):
        result["choices"]=[];return result
    result.update(choices=[dict(index=i,date=r["date"],candidate_id=r["id"])
                           for j,(i,r) in enumerate(candidates) if solver.value(x[j])],
                  objective=solver.objective_value,best_bound=solver.best_objective_bound,
                  proven_optimal=status==cp_model.OPTIMAL)
    return result


def prove_no_event_opportunity(document, family):
    """Conservative proof on the declared16:00-21:00 event union."""
    p=document["problem"];c=document["context"]
    def touches(start,end):return start<1260 and end>960
    if family=="ev":
        return not any(touches(x["start_min"],x["end_min"]) for x in c["physical_ev_connections"])
    if family!="washer":return False
    dryer=next(j for j in p["jobs"] if j["kind"]=="dryer")
    if dryer["control_mode"]!="fixed_routine":return False
    fixed=next(t for t in c["A"]["tasks"] if t["kind"]=="dryer")
    washer=next(t for t in c["A"]["tasks"] if t["kind"]=="washer")
    task=next(t for t in p["task_context"]["tasks"] if t["function"]=="WM")
    duration=task["duration_min"]
    latest=min(task["deadline_min"]-duration,fixed["start_min"]-duration)
    starts=range(math.ceil(task["ready_min"]/10)*10,math.floor(latest/10)*10+1,10)
    return not touches(washer["start_min"],washer["end_min"]) and not any(touches(x,x+duration) for x in starts)


def check_exemptions(bundle,pack):
    for family in pack.get("proven_no_event_opportunity",[]):
        for slot in pack["slots"]:
            document=read(local(Path(bundle)/"contexts",f'{pack["index"]:04}/{slot["date"]}_A.json.gz'))
            if not prove_no_event_opportunity(document,family):
                raise ValueError("UNPROVEN_FUNCTION_EXEMPTION")
    return len(pack.get("proven_no_event_opportunity",[]))


def solve_role(item):
    bundle, houses, budget, seed = item
    packs=[read(local(bundle,h["path"])) for h in houses]
    for pack in packs:check_exemptions(bundle,pack)
    return allocate(packs,deterministic_time=budget,seed=seed)


def solve(bundle, out, *, workers=6, deterministic_time=60, seed=20261116):
    manifest=verify(bundle,historical=False)
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    roles=sorted({h["role"] for h in manifest["houses"]})
    grouped=[[h for h in manifest["houses"] if h["role"]==role] for role in roles]
    results={}
    with ProcessPoolExecutor(max_workers=min(workers,len(roles))) as pool:
        jobs={pool.submit(solve_role,(str(bundle),houses,deterministic_time,seed)):role
              for role,houses in zip(roles,grouped)}
        for future in as_completed(jobs):
            role=jobs[future];result=future.result();results[role]=result
            write(out/(role+".json"),result)
            print(json.dumps(dict(role=role,status=result["status"],slots=result["slots"])),flush=True)
    passed=all(r["status"] in ("OPTIMAL","FEASIBLE") for r in results.values())
    record=dict(schema="eb.fresh_cohort_allocation.v1",passed=passed,
                recipe_sha256=manifest["manifest_sha256"],roles=results,
                historical_choices_read=False,physical_outcomes_computed=False)
    write(out/"RESULT.json",record)
    if not passed:raise ValueError("ALLOCATION_HAS_UNRESOLVED_OR_INFEASIBLE_ROLE")
    choices=[x for role in roles for x in results[role]["choices"]]
    write(out/"CHOICES.json",dict(schema="eb.fresh_discrete_choices.v1",
                                  choices=choices,recipe_sha256=manifest["manifest_sha256"],
                                  archived_choices_read=False))
    return record


def rebuild_house(item):
    bundle, house, selections, out, native, household, manifest = item
    from .model import apply
    from .eb_alignment import audit
    from .task_context import audit_tasks
    from .paper_v1_native_replay import replay
    bundle,out=Path(bundle),Path(out)
    pack=read(local(bundle,house["path"]))
    check_exemptions(bundle,pack)
    names={"AC":"ac","WM":"washer","DR":"dryer","DW":"dishwasher","WH":"water_heater","EV":"ev"}
    if set(pack["required_functions"])|set(pack.get("proven_no_event_opportunity",[])) != {names[f] for f in household["household"]["controlled_function_ids"]}:
        raise ValueError("CONTROLLED_FUNCTION_COVERAGE_CONTRACT_CHANGED")
    rows={w["row"]["id"]:w["row"] for w in pack["rows"]}
    metadata={s["date"]:s for s in pack["slots"]}
    chosen={s["date"]:s["candidate_id"] for s in selections}
    if len(chosen)!=len(selections) or set(chosen)!=set(metadata):
        raise ValueError("ONE_CHOICE_PER_DECLARED_SLOT_REQUIRED")
    tokens, functions = set(), set()
    indexes=[];cells=[]
    for date in sorted(chosen):
        row=rows.get(chosen[date])
        if row is None or row["date"]!=date:
            raise ValueError("CHOICE_NOT_IN_SAME_SLOT_CANDIDATE_POOL")
        tokens.update(next(w["tokens"] for w in pack["rows"] if w["row"]["id"]==row["id"]))
        functions.update(c["family"] for c in row["components"])
        relative=row.get("scene_context_relative_path",f"{house['index']:04}/{date}_A.json.gz")
        source=local(bundle/"contexts",relative);doc=read(source);c=doc["context"];p=doc["problem"]
        base_relative=f"{house['index']:04}/{date}_A.json.gz"
        base=read(local(bundle/"contexts",base_relative))
        if p!=base["problem"] or c["A"]!=base["context"]["A"]:
            raise ValueError("SCENE_CHANGED_FROZEN_TASKS_OR_A")
        tc=p["task_context"]
        if tc["sha256"]!=digest({k:v for k,v in tc.items() if k!="sha256"}) or tc["household_case_sha256"]!=digest(household):
            raise ValueError("FROZEN_TASK_SOURCE_OR_CONTENT_CHANGED")
        A=deepcopy(c["A"]);B=apply(A,row["patches"])
        if digest(A)!=metadata[date]["A_sha256"] or tc["sha256"]!=metadata[date]["task_context_sha256"]:
            raise ValueError("REVIEWED_A_OR_TASK_CHANGED")
        for arm,plan in (("A",A),("B",B)):
            if audit_tasks(tc,plan):raise ValueError(arm+"_TASK_ERROR")
        gate=audit(c,B,row["components"],side="B")
        if not gate["passed"]:raise ValueError("SELECTED_NATIVE_ACTION_ERROR")
        proofs={arm:replay(p,c,plan,native) for arm,plan in (("A",A),("B",B))}
        if not all(x["passed"] for x in proofs.values()):
            raise ValueError("FRESH_NATIVE_EXECUTION_FAILED")
        event=deepcopy(c["events"][0]);ah,bh=digest(A),digest(B);ch=digest(c)
        scenario=digest(dict(household_sha256=digest(household),task_sha256=tc["sha256"],event=event,date=date))
        pairid=digest(dict(scenario_sha256=scenario,A_sha256=ah,B_sha256=bh,context_sha256=ch))
        pair=dict(schema="eb.paper_v1.causal_native_pair.v4",date=date,
                  source_household_sha256=digest(household),source_manifest_sha256=manifest["household_source_sha256"],
                  A=A,B=B,A_sha256=ah,B_sha256=bh,selected_proposal=row,
                  daily_service_contract=c["daily_service_requirements"],native_B_acceptance=gate,
                  paper_v1_execution=proofs,physical_outcomes=None,human_answers=None,
                  formal_questionnaire_release=False,pair_id=pairid,scenario_sha256=scenario,
                  context_sha256=ch,event=event,task_context_sha256=tc["sha256"])
        for rel in {relative,base_relative}:
            dest=local(out/"native",rel);dest.parent.mkdir(parents=True,exist_ok=True)
            if not dest.exists():shutil.copyfile(local(bundle/"contexts",rel),dest)
        pair_rel=f"{house['index']:04}/{date}_PAIR.json.gz"
        path=local(out/"native",pair_rel);write(path,pair)
        indexes.append(dict(index=house["index"],case_id=house["case_id"],date=date,
                            relative_path=pair_rel,A_sha256=ah,B_sha256=bh,
                            pair_file_sha256=sha(path),pair_id=pairid,scenario_sha256=scenario,event=event,
                            context_relative_path=relative,context_sha256=ch,task_context_sha256=tc["sha256"],
                            reviewed_A_index_sha256=metadata[date].get("reviewed_A_index_sha256"),
                            reviewed_A_file_sha256=metadata[date].get("reviewed_A_file_sha256")))
        cells.extend((house["role"],key,house["country"]) for key in row["raw_root_cells"])
    if not set(pack["protected_tokens"])<=tokens or not set(pack["required_functions"])<=functions:
        raise ValueError("PROTECTED_HOUSEHOLD_COVERAGE_LOST")
    return dict(indexes=indexes,cells=cells)


def rebuild(bundle,out,native,*,selection=None,workers=7):
    manifest=verify(bundle,historical=selection is None)
    if sha(native)!=manifest["original_native_source_sha256"]:
        raise ValueError("PINNED_NATIVE_SOURCE_CHANGED")
    choice=read(selection if selection else local(bundle,manifest["historical_choices"]))
    if selection and choice.get("recipe_sha256")!=manifest["manifest_sha256"]:
        raise ValueError("SELECTION_RECIPE_IDENTITY_MISMATCH")
    selections=choice["choices"];by_house=defaultdict(list)
    for x in selections:by_house[x["index"]].append(x)
    if len(selections)!=manifest["pairs"] or set(by_house)!={h["index"] for h in manifest["houses"]}:
        raise ValueError("SELECTION_SLOT_COUNT_CHANGED")
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False)
    source=local(bundle,"households.jsonl")
    cases={c["case_id"]:c for c in map(json.loads,source.read_bytes().splitlines())}
    shutil.copyfile(source,out/"households.jsonl")
    results=[];start=time.monotonic()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        jobs=[pool.submit(rebuild_house,(str(bundle),h,by_house[h["index"]],str(out),str(native),cases[h["case_id"]],{"household_source_sha256":manifest["household_source_sha256"]})) for h in manifest["houses"]]
        for future in as_completed(jobs):
            results.append(future.result())
            if len(results)%100==0:print(json.dumps(dict(phase="rebuild",households=len(results))),flush=True)
    rows=sorted((r for result in results for r in result["indexes"]),key=lambda x:(x["index"],x["date"]))
    index=out/"native/PAIR_INDEX.jsonl"
    index.write_text("".join(json.dumps(x,ensure_ascii=False)+"\n" for x in rows))
    cells=defaultdict(set)
    for result in results:
        for role,key,country in result["cells"]:cells[(role,key)].add(country)
    from .prepare_question_inputs import build
    inputs=build(out/"households.jsonl",out/"native",out/"question_inputs",manifest["household_source_sha256"])
    result=dict(schema="eb.cohort_rebuild.result.v1",passed=True,
                mode="archived_choice_reconstruction" if selection is None else "fresh_allocation_materialization",
                independent_historical_solver_regeneration=False,
                household_source_sha256=sha(out/"households.jsonl"),
                recipe_sha256=manifest["manifest_sha256"],households=len(results),pairs=len(rows),
                fresh_original_native_checks=2*len(rows),question_inputs=inputs["questions"],
                current_root_cells=len(cells),two_or_more_countries=sum(len(v)>=2 for v in cells.values()),
                single_country=sum(len(v)==1 for v in cells.values()),
                physical_outcomes=None,human_answers=None,collection_ready=False,seconds=time.monotonic()-start,
                python=platform.python_version(),implementation_sha256=sha(Path(__file__)))
    write(out/"RESULT.json",result);return result


def compare(rebuilt,reference_batch,reference_questions):
    rebuilt,reference_batch,reference_questions=map(Path,(rebuilt,reference_batch,reference_questions))
    def index(path):
        rows=[json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        result={(r["case_id"],r["date"]):r for r in rows}
        if len(result)!=len(rows):raise ValueError("DUPLICATE_COMPARE_SLOT")
        return result
    actual=index(rebuilt/"native/PAIR_INDEX.jsonl")
    expected=index(reference_batch/"PAIR_INDEX.jsonl")
    aq=index(rebuilt/"question_inputs/QUESTION_INDEX.jsonl")
    eq=index(reference_questions/"QUESTION_INDEX.jsonl")
    if set(actual)!=set(expected) or set(aq)!=set(eq) or set(actual)!=set(aq):
        raise ValueError("REPRODUCTION_SLOT_SET_MISMATCH")
    counts=Counter();errors=[]
    for key in sorted(expected):
        a,e=actual[key],expected[key]
        for field in ("A_sha256","B_sha256","task_context_sha256","event","context_sha256","scenario_sha256","pair_id"):
            if a[field]!=e[field]:errors.append(dict(slot=list(key),field=field))
            else:counts[field]+=1
        ap=read(local(rebuilt/"native",a["relative_path"]))
        ep=read(local(reference_batch,e["relative_path"]))
        for arm in ("A","B"):
            if ap[arm]!=ep[arm]:errors.append(dict(slot=list(key),field=arm+"_content"))
            else:counts[arm+"_content"]+=1
        ai=read(local(rebuilt/"question_inputs",aq[key]["input_relative_path"]))
        ei=read(local(reference_questions,eq[key]["input_relative_path"]))
        if ai!=ei:errors.append(dict(slot=list(key),field="whole_question_input"))
        else:counts["whole_question_input"]+=1
    result=dict(schema="eb.cohort_exact_semantic_reproduction.v1",passed=not errors,pairs=len(expected),
                equal=dict(counts),mismatches=len(errors),first_mismatches=errors[:20],
                comparison_used_for_generation=False,
                compressed_bytes_and_runtime_metadata_required_equal=False,
                scope="household-conditioned task,date,event,A/B,scene and complete judgment input identity")
    write(rebuilt/"EXACT_COMPARISON.json",result)
    if errors:raise ValueError("CURRENT_DATASET_NOT_REPRODUCED:"+str(len(errors)))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="command",required=True)
    p=sub.add_parser("freeze")
    for name in ("batch","households","out"):p.add_argument("--"+name,type=Path,required=True)
    for name in ("required","opportunity"):p.add_argument("--"+name,type=Path)
    p=sub.add_parser("solve")
    p.add_argument("--bundle",type=Path,required=True);p.add_argument("--out",type=Path,required=True)
    p.add_argument("--workers",type=int,default=6);p.add_argument("--deterministic-time",type=float,default=60)
    p.add_argument("--seed",type=int,default=20261116)
    p=sub.add_parser("rebuild")
    for name in ("bundle","out","native-source"):p.add_argument("--"+name,type=Path,required=True)
    p.add_argument("--selection",type=Path);p.add_argument("--workers",type=int,default=7)
    p=sub.add_parser("reproduce",help="archived-choice reconstruction,then independent reference comparison")
    for name in ("bundle","out","native-source","reference-batch","reference-questions"):
        p.add_argument("--"+name,type=Path,required=True)
    p.add_argument("--workers",type=int,default=7)
    p=sub.add_parser("compare")
    for name in ("rebuilt","reference-batch","reference-questions"):p.add_argument("--"+name,type=Path,required=True)
    args=parser.parse_args()
    if hasattr(args,"workers") and not 1<=args.workers<=7:parser.error("workers must be between1and7")
    if args.command=="freeze":result=freeze(args.batch,args.households,args.required,args.opportunity,args.out)
    elif args.command=="solve":result=solve(args.bundle,args.out,workers=args.workers,deterministic_time=args.deterministic_time,seed=args.seed)
    elif args.command=="rebuild":result=rebuild(args.bundle,args.out,args.native_source,selection=args.selection,workers=args.workers)
    elif args.command=="reproduce":
        result=rebuild(args.bundle,args.out,args.native_source,workers=args.workers)
        comparison=compare(args.out,args.reference_batch,args.reference_questions)
        result["exact_reference_comparison_passed"]=comparison["passed"]
        write(args.out/"RESULT.json",result)
    else:result=compare(args.rebuilt,args.reference_batch,args.reference_questions)
    print(json.dumps({k:v for k,v in result.items() if k not in ("files","houses","roles")},ensure_ascii=False),flush=True)


if __name__=="__main__":
    main()
