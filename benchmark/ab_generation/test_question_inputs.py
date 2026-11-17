"""Decision-input regression checks for contradictory source/operative views."""
import copy
import unittest
from .common import digest
from .task_context import upgrade_problem, audit_tasks, derive_tasks
from .question_inputs import compile_question, plan_view
from ..household_stage1.generator.views import current_household

def fixture():
    keys={"AC":"space_ac_available","WM":"washer_available","DR":"dryer_available",
          "DW":"dishwasher_available","WH":"water_heater_available","EV":"home_vehicle_charging"}
    controlled={"AC","WM","DR","DW"}
    h=dict(country="CN",role_name="价格敏感",attitudes={"price_priority":"high"},
        comfort={"preferred_cooling_c":[24,26],"comfort_ceiling_c":26},
        controlled_function_ids=sorted(controlled),decision_maker_id="M01",
        members=[dict(id="M01",reference_age=35,activity="work",employment="employed",work_mode="onsite",
                      source_person_key="PRIVATE_SOURCE")],
        dwelling={"type":"apartment","reference_area_m2":80},
        equipment={k:{"present":f in controlled} for f,k in keys.items()},
        control_inventory={f:{"enabled":f in controlled} for f in keys},
        service_asset_registry={f:{"functions":[f]} for f in controlled},
        calendar={"weekly_events":[]},ev={},
        routine={"information_contract":{"reference_week_is_actual_diary":False},
                 "daily_services":[{"day":i,
                    "meals":[{"kind":"breakfast","location":"home","participants":["M01"],"start":420,"end":450}],
                    "bathing_services":[{"member_id":"M01","start":1140,"end":1150,"assistant_id":None}]} for i in range(7)]})
    c=dict(case_id="PRIVATE_CASE",source={"dataset":"PRIVATE_DATA"},household=h,
           card={"unknown_equipment":["空调","洗碗机"]})
    jobs=[]
    for k in ("washer","dryer","dishwasher"):
        j=dict(kind=k,need_id=k,release_min=480,deadline_min=1440,
               policy={"duration_min":60})
        if k=="dryer":j["depends_on_need_id"]="washer"
        if k=="dishwasher":j["A_reference_dish_load"]={"meal_kind":"dinner","meal_end_min":1110}
        jobs.append(j)
    # Freeze a real task record before either plan is built. This fixture is
    # deliberately synthetic; no source diary or legacy-B upgrade is implied.
    reference={"programs":{k:{"duration_min":60} for k in ("washer","dryer","dishwasher")}}
    tc=derive_tasks(c,"2007-07-18",reference)
    for j in jobs:
        t=next(t for t in tc["tasks"] if t["kind"]==j["kind"])
        j.update(release_min=t["ready_min"],task_load_id=t["load_id"],task_context_sha256=tc["sha256"])
    problem=dict(jobs=jobs,task_context=tc)
    A={"tasks":[dict(task_id=k,need_id=k,asset_id=k,kind=k,start_min=a,end_min=z,
          **({"depends_on_need_id":"washer"} if k=="dryer" else {}))
          for k,a,z in [("washer",1080,1140),("dryer",1140,1200),("dishwasher",1200,1260)]],
       "operations":[],"controls":[dict(asset_id="AC",kind="ac_setpoint",start_min=0,end_min=1440,
            cooling_setpoint_C=25,heating_setpoint_C=20,fan_operating_mode=0)]}
    B=copy.deepcopy(A);B["tasks"][2].update(start_min=990,end_min=1050)
    event=dict(start_min=1080,end_min=1140,direction="down",target_kw=None)
    context=dict(A=A,events=[event],needs=[dict(need_id=j["need_id"],release_min=j["release_min"],task_context_sha256=tc["sha256"]) for j in jobs])
    idx=dict(pair_id="PARENT_PAIR",scenario_sha256="SCENE",A_sha256=digest(A),B_sha256=digest(B),
             event=event,context_sha256=digest(context),context_relative_path="0000/X_SCENE.json.gz",task_context_sha256=tc["sha256"])
    pair={**idx,"date":"2007-07-18","A":A,"B":B,"source_household_sha256":digest(c),
          "selected_proposal":{"judgment_context":"DO_NOT_EXPOSE","issues":["PREFERENCE_CONFLICT"]}}
    return c,dict(problem=problem,context=context),pair,idx

class QuestionInputs(unittest.TestCase):
    def test_current_equipment_wins_without_rewriting_source(self):
        c,_,_,_=fixture();before=copy.deepcopy(c)
        v=current_household(c)
        self.assertTrue(next(x for x in v["equipment"] if x["function"]=="AC")["present"])
        self.assertNotIn("unknown_equipment",str(v))
        self.assertNotIn("PRIVATE_SOURCE",str(v))
        self.assertEqual(c,before)

    def test_earlier_dishwashing_has_given_ready_load_not_future_dinner_load(self):
        c,d,p,i=fixture();before=copy.deepcopy(d)
        v=compile_question(c,d,p,i)
        self.assertEqual(v["input"]["plans"]["B"]["programmes"][0]["start_min"],990)
        self.assertEqual(d,before)
        t=next(t for t in v["input"]["situation"]["tasks"] if t["function"]=="DW")
        self.assertEqual(t["ready_min"],480)
        self.assertNotIn("A_reference_dish_load",str(v["input"]))

    def test_truly_unready_programme_still_fails(self):
        _,d,p,_=fixture();problem=upgrade_problem(d["problem"])
        b=copy.deepcopy(p["B"]);b["tasks"][2].update(start_min=470,end_min=530)
        self.assertIn("TASK_BEFORE_DECLARED_READY_TIME",audit_tasks(problem["task_context"],b))

    def test_wash_dry_causality_is_not_a_soft_preference(self):
        _,d,p,_=fixture();problem=upgrade_problem(d["problem"])
        b=copy.deepcopy(p["B"]);b["tasks"][1].update(start_min=1100,end_min=1160)
        self.assertIn("SAME_LOAD_PREDECESSOR_NOT_FINISHED",audit_tasks(problem["task_context"],b))

    def test_scene_mismatch_rejected(self):
        c,d,p,i=fixture();d["context"]["events"]=[{**i["event"],"start_min":960}]
        with self.assertRaisesRegex(ValueError,"EVENT"):
            compile_question(c,d,p,i)

    def test_generator_judgment_not_model_input(self):
        c,d,p,i=fixture();v=compile_question(c,d,p,i)
        self.assertNotIn("DO_NOT_EXPOSE",str(v["input"]))
        self.assertNotIn("PRIVATE_CASE",str(v["input"]))
        self.assertIsNone(v["targets"]);self.assertFalse(v["collection_ready"])

    def test_charge_permission_is_not_duration_or_claimed_physics(self):
        c,_,p,_=fixture();plan=copy.deepcopy(p["A"])
        plan["controls"].append(dict(kind="ev_charge_window",asset_id="EV",
            start_min=1080,end_min=1950,stop_at_target_soc=.8))
        r=next(x for x in plan_view(plan,c)["controls"] if x["function"]=="EV")
        self.assertEqual((r["permitted_start_min"],r["permitted_end_min"]),(1080,1950))
        self.assertEqual(r["stop_at_soc"],.8)
        self.assertNotIn("actual_charge_duration_min",r)
        self.assertIn("不等于实际充电时长",r["meaning"])

    def test_task_context_changes_identity_without_changing_commands(self):
        c,d,p,i=fixture();v=compile_question(c,d,p,i)
        tc=d["problem"]["task_context"]
        tc["information_perspective"]+=";explicit additional scenario information"
        tc["sha256"]=digest({k:v for k,v in tc.items() if k!="sha256"})
        for job in d["problem"]["jobs"]:job["task_context_sha256"]=tc["sha256"]
        for need in d["context"]["needs"]:need["task_context_sha256"]=tc["sha256"]
        for item in (p,i):item["task_context_sha256"]=tc["sha256"];item["context_sha256"]=digest(d["context"])
        w=compile_question(c,d,p,i)
        self.assertNotEqual(v["question_id"],w["question_id"])
        self.assertEqual(v["lineage"]["parent"]["B_sha256"],w["lineage"]["parent"]["B_sha256"])

    def test_posthoc_job_release_rewrite_is_rejected(self):
        c,d,p,i=fixture()
        d["problem"]["jobs"][2]["release_min"]=540
        with self.assertRaisesRegex(ValueError,"TASK_CONTEXT_NOT_BOUND"):
            compile_question(c,d,p,i)

    def test_legacy_problem_cannot_be_upgraded_after_plans(self):
        _,d,_,_=fixture()
        del d["problem"]["task_context"]
        with self.assertRaisesRegex(ValueError,"OLD_B_CANNOT_BE_RELABELED"):
            upgrade_problem(d["problem"])

if __name__=="__main__":
    unittest.main()
