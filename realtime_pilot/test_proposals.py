"""Decision semantics and immutable plan-pair regression tests; no external API."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from common import PROPOSAL_PROFILE_QUESTIONS, digest, normalize_answers
from proposal_contract import CONTEXT, ordinary_plan, executable, validate_offer, pair_display
from server import Store
from test_pilot import NoExecute

def payload():
    return {"request_id": "proposal_test_nonce_001", "scenario_id": CONTEXT["id"],
            "scenario_understood": True, "original_confirmed": True, "applicability": "close",
            "baseline_source": "usual_routine_in_scenario", "engineering_test": True,
            "answers": {"B05": ["ac", "washer", "dishwasher", "electric_water_heater"], "A_EB_COMFORT": "temp_sensitive"},
            "routine": {"ac": {"active": True, "setpoint": 25.5},
                        "washer": {"active": True, "start_h": 18, "duration_h": 2, "earliest_h": 16, "deadline_h": 22},
                        "dishwasher": {"active": False}, "electric_water_heater": {"mode": "unchanged"}}}

class ProposalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.store.pool.shutdown()
        self.store.pool = NoExecute()
        self.addCleanup(self.temp.cleanup)

    def completed(self):
        j = self.store.create("owner", payload(), proposal=True)
        proposal = {"setpoint": 26.5, "appliances": {"washer_start_h": 19}}
        display = pair_display(j["original_plan"], proposal, j["baseline_source"])
        j.update(status="complete", result={"proposal_plan": proposal, "display": display,
                 "display_hash": digest(display), "proposal_plan_hash": digest(proposal),
                 "original_plan_hash": j["original_plan_hash"]})
        self.store.persist(j)
        return j

    def decision(self, j, choice="accept", reason=""):
        return {"choice": choice, "comment": reason,
                **{k: j["result"][k] for k in ("display_hash", "original_plan_hash", "proposal_plan_hash")}}

    def test_owned_unused_and_original_are_respected(self):
        p=payload()
        original=ordinary_plan(normalize_answers(p["answers"], [q["id"] for q in PROPOSAL_PROFILE_QUESTIONS], {q["id"]:q for q in PROPOSAL_PROFILE_QUESTIONS}), p["routine"])
        self.assertEqual(executable(original), {"setpoint": 25.5, "appliances": {"washer_start_h": 18.0}})
        before=copy.deepcopy(original)
        valid={"setpoint": 26.5, "appliances": {"washer_start_h": 19}}
        display=pair_display(original,valid,p["baseline_source"])
        self.assertEqual(original,before)
        self.assertEqual(len(display["rows"]),4)
        for invalid in [None, {"setpoint": 31,"appliances":{"washer_start_h":19}},
                        {"setpoint":25.5,"appliances":{"washer_start_h":21}},
                        {"setpoint":25.5,"appliances":{"washer_start_h":19,"dishwasher_start_h":20}},
                        {"setpoint":25.5,"appliances":{}}]:
            with self.assertRaises(ValueError): validate_offer(original,invalid)

    def test_explicit_initial_confirmation_and_consistent_inventory(self):
        for change in [{"original_confirmed":False},{"routine":{}},{"answers":{"B05":["none"]}}]:
            with self.assertRaises(ValueError):self.store.create("owner", {**payload(),**change}, proposal=True)
        p=payload();p["routine"]["washer"]["deadline_h"]=19
        with self.assertRaises(ValueError): self.store.create("owner",p,proposal=True)

    def test_plan_pair_bound_decision_is_immutable_and_sft_is_pre_execution(self):
        j=self.completed(); data=self.decision(j)
        for key in ("display_hash","original_plan_hash","proposal_plan_hash"):
            with self.assertRaises(ValueError):self.store.decide(j["id"],"owner",{**data,key:"wrong"})
        with self.assertRaises(KeyError):self.store.decide(j["id"],"someone_else",data)
        with self.assertRaises(ValueError):self.store.rate(j["id"],"owner",{})
        self.assertTrue(self.store.decide(j["id"],"owner",data)["saved"])
        self.assertTrue(self.store.decide(j["id"],"owner",data)["duplicate"])
        with self.assertRaises(ValueError): self.store.decide(j["id"],"owner",self.decision(j,"reject"))
        row=json.loads((Path(self.temp.name)/j["id"]/"sft_candidate.json").read_text())
        self.assertEqual(json.loads(row["messages"][-1]["content"]),{"decision":"accept"})
        self.assertEqual(row["task"],"plan_judgement")
        self.assertEqual(row["target_source"],"engineering_test")
        self.assertEqual(row["execution_status"],"not_run")
        self.assertFalse(row["training_release"])
        self.assertNotIn('"decision": "accept"',row["messages"][1]["content"])

    def test_legacy_question_meaning_is_not_relabelled(self):
        from proposal_contract import decision_record
        job=self.completed()
        job.update(flow='paired_ep_v1')
        job['result']['schema_version']='eb.paired_ep.v2.3'
        before=copy.deepcopy(job)
        with self.assertRaisesRegex(ValueError, '旧版评价情境'):
            decision_record(job,{**self.decision(job), 'score':3,
                'comfort_score':2, 'energy_score':4, 'vpp_score':2})
        self.assertEqual(job,before)

    def test_only_binary_decisions_and_independent_scores(self):
        from proposal_contract import decision_record, SCORE_FIELDS
        j=self.completed()
        for choice in ("modify","need_information"):
            with self.assertRaises(ValueError):decision_record(j,self.decision(j,choice,"反馈"))
        scores={"score":3,"comfort_score":2,"energy_score":4,"vpp_score":2}
        data={**self.decision(j,"reject","功能测试"),**scores}
        self.store.decide(j["id"],"owner",data)
        row=json.loads((Path(self.temp.name)/j["id"]/"sft_candidate.json").read_text())
        target=json.loads(row["messages"][-1]["content"])
        self.assertEqual(target,{"decision":"reject","comment":"功能测试",**scores})
        for key in SCORE_FIELDS:
            for bad in [True,0,6,float("nan"),float("inf"),"3"]:
                with self.assertRaises(ValueError):decision_record(j,{**data,key:bad})
        missing=decision_record(j,self.decision(j))
        self.assertIsNone(missing["score"])
        self.assertEqual(missing["score_status"]["score"],"skipped")
        with self.assertRaises(ValueError):self.store.decide(j["id"],"owner",{**data,"energy_score":5})

    def test_decimal_scores_survive_storage_and_sft(self):
        j=self.completed()
        scores={"score":3.75,"comfort_score":2.5,"energy_score":4.2,"vpp_score":2.125}
        data={**self.decision(j,"accept","小数评分"),**scores}
        self.store.decide(j['id'],'owner',data)
        saved=json.loads((Path(self.temp.name)/j['id']/'decision.json').read_text())
        row=json.loads((Path(self.temp.name)/j['id']/'sft_candidate.json').read_text())
        target=json.loads(row['messages'][-1]['content'])
        for key,value in scores.items():
            self.assertEqual(saved[key],value)
            self.assertEqual(target[key],value)

    def test_no_forced_changes_and_no_consent_for_failed_or_legacy_job(self):
        j=self.completed(); original=j["original_plan"]
        self.assertFalse(pair_display(original,executable(original),j["baseline_source"])["has_changes"])
        for status,task in [("failed","plan_judgement"),("complete","outcome_rating")]:
            j.update(status=status,task=task)
            with self.assertRaises(ValueError):self.store.decide(j["id"],"owner",self.decision(j))

if __name__=="__main__":unittest.main(verbosity=2)
