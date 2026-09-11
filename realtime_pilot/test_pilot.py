"""Contract and HTTP isolation tests. Fixtures are never counted as human data."""
import copy
import http.cookiejar
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

from common import ROOT, SCENARIO, PROFILE_IDS, RATING_IDS, digest, normalize_answers, training_candidate, write_json
from server import make_server, Store
from worker import finite_json

class NoExecute:
    def submit(self, *args):
        pass
    def shutdown(self, **kwargs):
        pass

class ContractTests(unittest.TestCase):
    def test_missing_and_neutral_distinct(self):
        p = normalize_answers({"A01": 3, "A02": "dont_know"}, PROFILE_IDS)
        self.assertEqual(p["A01"], {"value": 3, "response_status": "answered"})
        self.assertEqual(p["A02"], {"value": None, "response_status": "dont_know"})
        self.assertEqual(p["A03"]["response_status"], "skipped")

    def test_bad_and_exclusive_options_rejected(self):
        for answers in [{"A01": 6}, {"A01": True}, {"unknown": 1}, {"B05": ["ac", "none"]}, {"B05": ["ac", "ac"]}]:
            with self.assertRaises(ValueError):
                normalize_answers(answers, PROFILE_IDS)

    def test_nonfinite_engine_values_are_null_not_score(self):
        self.assertEqual(finite_json({"a": float("nan"), "b": [float("inf"), 3]}), {"a": None, "b": [None, 3]})

    def test_restart_marks_work_interrupted(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_json(Path(tmp)/"job1/job.json", {"id": "job1", "status": "running"})
            store = Store(tmp)
            self.assertEqual(store.jobs["job1"]["status"], "interrupted")
            store.pool.shutdown()

class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.server = make_server(0, cls.temp.name)
        cls.server.store.pool.shutdown()
        cls.server.store.pool = NoExecute()
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.temp.cleanup()

    def setUp(self):
        self.client = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.get("/api/session")

    def get(self, path):
        try:
            with self.client.open(self.base+path) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            exc.close()
            raise

    def post(self, path, body, origin=None):
        request = urllib.request.Request(self.base+path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "Origin": origin or self.base})
        try:
            with self.client.open(request) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            exc.close()
            raise

    def create(self):
        return self.post("/api/jobs", {"request_id": "request_"+str(time.time_ns()), "scenario_id": SCENARIO["id"], "scenario_understood": True,
                                      "applicability": "close", "engineering_test": True, "answers": {"A01": 4, "A03": 5}})

    def test_origin_isolation(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/jobs", {}, "https://unrelated.example")
        self.assertEqual(ctx.exception.code, 403)

    def test_session_cannot_read_or_rate_another_job(self):
        job = self.create()
        self.client = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.get("/api/session")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/api/jobs/"+job["id"])
        self.assertEqual(ctx.exception.code, 404)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post(f"/api/jobs/{job['id']}/rating", {})
        self.assertEqual(ctx.exception.code, 404)

    def test_job_submission_idempotency_and_cancel(self):
        payload = {"request_id": "same_submission_"+str(time.time_ns()), "scenario_id": SCENARIO["id"], "scenario_understood": True, "applicability": "close", "answers": {}}
        first, second = self.post("/api/jobs", payload), self.post("/api/jobs", payload)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(self.post(f"/api/jobs/{first['id']}/cancel", {})["status"], "cancelled")
        with self.assertRaises(urllib.error.HTTPError):
            self.post(f"/api/jobs/{first['id']}/rating", {"answers": {"R01": 1}})

    def test_display_binding_rating_persistence_and_sft(self):
        # Synthetic display fixture: tests label binding, not EP physics.
        job = self.create()
        display = {"fixture": "synthetic display for label binding"}
        outcome = {"display": display, "display_hash": digest(display)}
        store = self.server.store
        with store.lock:
            j = store.jobs[job["id"]]
            j.update(status="complete", result=outcome)
            store.persist(j)
        path = f"/api/jobs/{job['id']}/rating"
        with self.assertRaises(urllib.error.HTTPError):
            self.post(path, {"display_hash": "wrong", "answers": {"R01": 4}})
        payload = {"display_hash": outcome["display_hash"], "answers": {"R01": 4, "R02": "cannot_judge", "R07": "功能测试，不是真人调查答案"}}
        self.assertTrue(self.post(path, payload)["saved"])
        self.assertTrue(self.post(path, payload)["duplicate"])
        changed = copy.deepcopy(payload)
        changed["answers"]["R01"] = 1
        with self.assertRaises(urllib.error.HTTPError):
            self.post(path, changed)
        candidate = json.loads((store.root/job["id"]/"sft_candidate.json").read_text())
        target = json.loads(candidate["messages"][-1]["content"])
        self.assertEqual(target["score"], 4)
        self.assertNotIn("comfort_score", target)
        self.assertFalse(candidate["training_release"])
        self.assertEqual(candidate["target_source"], "engineering_test")
        self.assertTrue(self.get("/api/jobs/"+job["id"])["rating_saved"])

if __name__ == "__main__":
    unittest.main(verbosity=2)
