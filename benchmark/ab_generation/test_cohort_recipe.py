"""Checks for fresh cohort allocation and explicitly labelled artifact replay."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from . import cohort_recipe as recipe


def pack():
    def row(id,date,family,root):
        return dict(row=dict(id=id,date=date,components=[dict(family=family)],
                             raw_root_cells=[root],comfort_conflict=True,nominal_effect=-1),
                    tokens=["base"])
    return dict(index=0,country="CN",slots=[dict(date="d1"),dict(date="d2")],
                initial_selected_ids=["old1","old2"],protected_tokens=["base"],
                required_functions=["ac","washer"],
                rows=[row("old1","d1","ac","a"),row("new1","d1","ev","b"),
                      row("old2","d2","ac","a"),row("new2","d2","washer","b")])


class CohortRecipeTests(unittest.TestCase):
    def test_unique_valid_solution_protects_task_function_and_root_coverage(self):
        result=recipe.allocate([pack()],deterministic_time=1)
        self.assertEqual("OPTIMAL",result["status"])
        self.assertEqual({"old1","new2"},{r["candidate_id"] for r in result["choices"]})
        self.assertFalse(result["archived_choices_read"])

    def test_rejected_resident_preference_is_not_a_generation_filter(self):
        data=pack();before=copy.deepcopy(data)
        result=recipe.allocate([data],deterministic_time=1)
        self.assertIn("new2",{r["candidate_id"] for r in result["choices"]})
        self.assertEqual(before,data)

    def test_infeasible_coverage_does_not_return_fake_choices(self):
        data=pack();data["rows"][2]["row"]["raw_root_cells"]=["third"]
        data["required_functions"]=[]
        # At most two roots in two slots, but all three are declared.
        result=recipe.allocate([data],deterministic_time=1)
        self.assertEqual("INFEASIBLE",result["status"]);self.assertEqual([],result["choices"])

    def test_input_order_is_canonicalized(self):
        data=pack();other=copy.deepcopy(data);other["rows"].reverse()
        a=recipe.allocate([data],deterministic_time=1)
        b=recipe.allocate([other],deterministic_time=1)
        self.assertEqual(a["choices"],b["choices"])

    def test_budget_is_strict(self):
        for value in [False,0,-1,float("nan"),float("inf")]:
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,"BUDGET"):
                recipe.allocate([pack()],deterministic_time=value)

    def test_candidates_cannot_add_an_undeclared_slot(self):
        data=pack();data["rows"][0]["row"]["date"]="other"
        with self.assertRaisesRegex(ValueError,"SLOT_SET"):
            recipe.allocate([data],deterministic_time=1)

    def test_duplicate_declared_slots_are_rejected(self):
        data=pack();data["slots"].append(dict(date="d1"))
        with self.assertRaisesRegex(ValueError,"SLOT_SET"):
            recipe.allocate([data],deterministic_time=1)

    def test_paths_cannot_escape_recipe(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError,"OUTSIDE"):
                recipe.local(temp,"../secret")

    def test_fresh_validation_does_not_read_historical_choices(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);recipe.write(root/"input.json",{"x":1})
            manifest=dict(schema=recipe.SCHEMA,files={"input.json":recipe.sha(root/"input.json"),
                          "history.json":"0"*64},historical_choices="history.json")
            manifest["manifest_sha256"]=recipe.digest(manifest)
            recipe.write(root/"MANIFEST.json",manifest)
            self.assertEqual(recipe.SCHEMA,recipe.verify(root,historical=False)["schema"])
            with self.assertRaises(FileNotFoundError):recipe.verify(root,historical=True)

    def test_input_or_manifest_tamper_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);recipe.write(root/"input.json",{"x":1})
            manifest=dict(schema=recipe.SCHEMA,files={"input.json":recipe.sha(root/"input.json")},
                          historical_choices="history.json")
            manifest["manifest_sha256"]=recipe.digest(manifest)
            recipe.write(root/"MANIFEST.json",manifest);recipe.write(root/"input.json",{"x":2})
            with self.assertRaisesRegex(ValueError,"FILE_CHANGED"):recipe.verify(root)
            manifest["schema"]="modified"
            recipe.write(root/"MANIFEST.json",manifest)
            with self.assertRaises(ValueError):recipe.verify(root)

    def test_existing_destination_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(FileExistsError):
                recipe.freeze("unused","unused","unused","unused",temp)


    def test_ev_exemption_requires_no_connection_in_event_union(self):
        doc={"problem":{},"context":{"physical_ev_connections":[{"start_min":1270,"end_min":1800}]}}
        self.assertTrue(recipe.prove_no_event_opportunity(doc,"ev"))
        doc["context"]["physical_ev_connections"][0]["start_min"]=1200
        self.assertFalse(recipe.prove_no_event_opportunity(doc,"ev"))

    def test_washer_exemption_requires_immutable_early_dryer(self):
        doc={"problem":{"jobs":[{"kind":"dryer","control_mode":"fixed_routine"}],
                        "task_context":{"tasks":[{"function":"WM","ready_min":480,"deadline_min":1440,"duration_min":120}]}},
             "context":{"A":{"tasks":[{"kind":"dryer","start_min":800,"end_min":890},
                                      {"kind":"washer","start_min":600,"end_min":720}]}}}
        self.assertTrue(recipe.prove_no_event_opportunity(doc,"washer"))
        doc["context"]["A"]["tasks"][0]["start_min"]=1100
        self.assertFalse(recipe.prove_no_event_opportunity(doc,"washer"))

    def test_exact_compare_rejects_changed_plan_even_with_same_input_count(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);actual=root/"actual";reference=root/"reference";questions=root/"questions"
            item=dict(case_id="SYNTHETIC",date="d1",relative_path="p.json",A_sha256="a",B_sha256="b",
                      task_context_sha256="t",event={"start":1},context_sha256="c",scenario_sha256="s",pair_id="p")
            for directory,row in [(actual/"native",item),(reference,{**item,"B_sha256":"wrong"})]:
                directory.mkdir(parents=True)
                (directory/"PAIR_INDEX.jsonl").write_text(json.dumps(row)+"\n")
                recipe.write(directory/"p.json",{"A":{"x":1},"B":{"x":2}})
            for directory in (actual/"question_inputs",questions):
                directory.mkdir(parents=True)
                (directory/"QUESTION_INDEX.jsonl").write_text(json.dumps({"case_id":"SYNTHETIC","date":"d1","input_relative_path":"q.json"})+"\n")
                recipe.write(directory/"q.json",{"input":"same"})
            with self.assertRaisesRegex(ValueError,"NOT_REPRODUCED"):
                recipe.compare(actual,reference,questions)
            self.assertFalse(recipe.read(actual/"EXACT_COMPARISON.json")["passed"])

    def test_reference_is_passed_only_to_post_rebuild_comparison(self):
        from unittest.mock import patch
        sequence=[]
        def build(*args,**kwargs):
            sequence.append("build")
            self.assertFalse(any("reference" in str(x) for x in args))
            return {"passed":True}
        def compare(*args,**kwargs):
            sequence.append("compare");return {"passed":True}
        argv=["recipe","reproduce","--bundle","bundle","--out","out","--native-source","native",
              "--reference-batch","reference-batch","--reference-questions","reference-questions"]
        with patch("sys.argv",argv),patch.object(recipe,"rebuild",side_effect=build),patch.object(recipe,"compare",side_effect=compare),patch.object(recipe,"write"):
            recipe.main()
        self.assertEqual(["build","compare"],sequence)


    def test_new_gzip_artifacts_have_no_clock_or_filename_dependency(self):
        with tempfile.TemporaryDirectory() as temp:
            a,b=Path(temp)/"a.json.gz",Path(temp)/"b.json.gz"
            recipe.write(a,{"x":1});recipe.write(b,{"x":1})
            self.assertEqual(a.read_bytes(),b.read_bytes())
            self.assertEqual(0,int.from_bytes(a.read_bytes()[4:8],"little"))


if __name__=="__main__":
    unittest.main()
