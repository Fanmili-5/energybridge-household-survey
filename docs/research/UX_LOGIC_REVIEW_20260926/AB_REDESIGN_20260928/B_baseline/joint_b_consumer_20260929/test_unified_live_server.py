"""Focused HTTP checks for the isolated engineering service."""
from __future__ import annotations

import json
from pathlib import Path
import re
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler
import uuid

from unified_live_server import App, Server


HERE = Path(__file__).resolve().parent
SITE = HERE / "unified_preview/revision2_full/cityrole-0012"


class LiveServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = App(SITE, self.tmp.name, "/joint-b", "https://example.test")
        self.server = Server(("127.0.0.1", 0), self.app)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}/joint-b"
        status, page, headers = self.request("/", method="GET")
        self.assertEqual(status, 200)
        self.assertIn("报告问题", page)
        self.cookie = headers["Set-Cookie"].split(";", 1)[0]
        self.csrf = re.search(r'window.EBLiveConfig=({.*?})</script>', page)[1]
        self.csrf = json.loads(self.csrf)["csrf"]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.tmp.cleanup()

    def request(self, path, data=None, *, method="POST", cookie=True, origin="https://example.test", csrf=True):
        headers = {}
        if method == "POST":
            headers["Content-Type"] = "application/json"
            headers["Origin"] = origin
            if cookie:
                headers["Cookie"] = self.cookie
            if csrf:
                headers["X-EB-CSRF"] = self.csrf
        request = Request(self.base + path, data=json.dumps(data).encode() if data is not None else None,
                          headers=headers, method=method)
        try:
            response = build_opener(ProxyHandler({})).open(request, timeout=3)
        except HTTPError as error:
            response = error
        raw = response.read().decode()
        value = json.loads(raw) if (response.headers.get("Content-Type") or "").startswith("application/json") else raw
        return response.status, value, response.headers

    def test_answer_issue_and_idempotency(self):
        case, digest = self.app.cases[0], self.app.hashes[0]
        record = {"schema": "eb.joint_b.local_test_export.v5", "status": "engineering_click_not_human_feedback",
                  "human_label_count": 0, "training_release": False, "formal_export_eligible": False,
                  "test_feedback": {"decision": "reject", "decision_status": "answered", "score": 3.5,
                                    "comfort_score": None, "energy_score": None, "vpp_score": 2.0,
                                    "comment": "安排晚于通常时间"},
                  "input": {"date": case["identity"]["date"]},
                  "audit": {"source_case": case, "source_binding": {"source_package_sha256": digest}}}
        payload = {"case_index": 0, "record": record, "request_id": str(uuid.uuid4())}
        self.assertEqual(self.request("/api/answers", payload, cookie=False)[0], 403)
        self.assertEqual(self.request("/api/answers", payload, origin="https://other.test")[0], 403)
        self.assertEqual(self.request("/api/answers", payload, csrf=False)[0], 403)
        status, saved, _ = self.request("/api/answers", payload)
        self.assertEqual(status, 201)
        self.assertTrue(saved["receipt_id"].startswith("ANS-"))
        self.assertEqual(self.request("/api/answers", payload)[1]["receipt_id"], saved["receipt_id"])
        invalid = json.loads(json.dumps(payload))
        invalid["request_id"] = str(uuid.uuid4())
        invalid["record"]["test_feedback"]["decision"] = "cannot_judge"
        self.assertEqual(self.request("/api/answers", invalid)[0], 400)
        issue = {"schema": "eb.joint_b.local_issue.v1", "status": "engineering_issue_submission",
                 "issue": {"category": "display", "description": "标签重叠"},
                 "context": {"household_id": case["identity"]["role_id"],
                             "case_id": case["identity"]["case_id"], "source_package_sha256": digest}}
        status, saved_issue, _ = self.request("/api/issues", {"case_index": 0, "record": issue, "request_id": str(uuid.uuid4())})
        self.assertEqual(status, 201)
        self.assertTrue(saved_issue["receipt_id"].startswith("ISS-"))
        with self.app.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM writes").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
