"""Loopback-only role study HTTP checks using disposable engineering fixtures."""
import copy
import csv
import hashlib
import http.cookiejar
import json
from pathlib import Path
import re
import shutil
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener

from role_ten_day import PUBLIC_DIR, RELEASE_GATE_VERSION, RoleStudy, blind_order, stable_hash
from server import PARTICIPANT_UI_VERSION, make_server
from common import digest
from date_sampling import assigned_context
from paired_contract import QUESTIONS, QUESTIONNAIRE_VERSION
from regional_test_support import answers
from test_offline_collection_contract import fixture_bank, fixture_evidence


def make_fixture(root):
    root = Path(root)
    bank, _ = fixture_bank()
    public_manifest_hash = hashlib.sha256((PUBLIC_DIR / "PUBLIC_MANIFEST.json").read_bytes()).hexdigest()
    bank["public_role_manifest_sha256"] = public_manifest_hash
    bank["profile_sha256"] = "7dbd4e5c87cc440de9f23a5042d83a809bd1cfea9d422245d228816146daaa69"
    for record in bank["records"]:
        record["profile_sha256"] = bank["profile_sha256"]
    bank["meter_version_sha256"] = "b" * 64
    with (PUBLIC_DIR / "households_300.csv").open(encoding="utf-8-sig", newline="") as handle:
        stations = {row["role_id"]: row["weather_station_key"] for row in csv.DictReader(handle)}
    bank["consent_text"] = "这是一份仅用于自动化回归的工程测试说明，不是正式真人研究的同意文本。"
    display = {}
    for record in bank["records"]:
        for day in record["days"]:
            cid = day["case_id"]
            plans = {}
            for slot in ("A", "B"):
                shown = {"branch_history_summary": "工程测试轨迹背景",
                         "device_schedule": [f"工程测试设备：{'18' if day['day_index'] == 1 or slot == 'A' else '19'}:00"],
                         "indoor_temperature_c": 25, "controlled_device_kwh": 1.2,
                         "task_completion": "测试完成", "metrics": {"unit": "engineering_only"}}
                plans[slot] = shown
                day["plans"][slot]["display_payload_hash"] = stable_hash(shown)
                day["plans"][slot]["metrics_hash"] = stable_hash(shown["metrics"])
            display[cid] = {"context": "工程测试日期，非真实仿真结果",
                            "weather": {"summary": "测试天气", "simulated_day_index": day["day_index"],
                                        "station_key": stations[record["role_id"]]},
                            "plans": plans}
    evidence = fixture_evidence(bank)
    bank["semantic_contrast_evidence_sha256"] = stable_hash(evidence)
    root.mkdir()
    (root / "casebank.json").write_text(json.dumps(bank, ensure_ascii=False), encoding="utf-8")
    (root / "accepted_contrasts.json").write_text(json.dumps(evidence, ensure_ascii=False), encoding="utf-8")
    (root / "display_payloads.json").write_text(json.dumps(display, ensure_ascii=False), encoding="utf-8")
    gate = {"schema_version": RELEASE_GATE_VERSION,
            "status": "ROLE_TECHNICAL_PREVIEW_APPROVED", "human_collection_approved": False,
            "engineering_only": True,
            "revoked": False,
            "casebank_sha256": stable_hash(bank), "contrast_sha256": stable_hash(evidence),
            "display_sha256": stable_hash(display), "meter_version_sha256": bank["meter_version_sha256"],
            "public_role_manifest_sha256": public_manifest_hash,
            "profile_sha256": bank["profile_sha256"],
            "final_evidence_sha256": bank["final_evidence_sha256"],
            "accepted_at": "2026-09-26T00:00:00Z"}
    gate_path = root / "release_gate.json"
    gate_path.write_text(json.dumps(gate), encoding="utf-8")
    return bank, gate_path


class RoleHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.bank, self.gate = make_fixture(base / "casebank")
        self.server = make_server(0, root=base / "server-data", disable_planning=True,
                                  role_casebank_dir=base / "casebank",
                                  role_release_gate_path=self.gate, role_expected_roles=2,
                                  admin_user="test_reviewer")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.client = build_opener(ProxyHandler({}), HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()
        self.server.store.db.close()
        self.tmp.cleanup()

    def request(self, path, data=None, client=None, admin=False):
        client = client or self.client
        headers = {"Origin": self.origin, "Content-Type": "application/json"} if data is not None else {}
        if admin:
            headers["X-EB-Authenticated-User"] = "test_reviewer"
        req = Request(self.origin + path, data=json.dumps(data).encode() if data is not None else None,
                      headers=headers)
        try:
            response = client.open(req)
        except HTTPError as exc:
            return exc.code, json.loads(exc.read())
        body = response.read()
        return response.status, json.loads(body) if response.headers.get_content_type() == "application/json" else body

    def test_locked_preview_old_intake_and_revocable_gate(self):
        self.assertEqual(self.request("/roles")[0], 200)
        self.assertEqual(self.request("/")[0], 200)
        self.assertEqual(self.request("/api/session")[0], 200)
        cookie = next(c.value for h in self.client.handlers if isinstance(h, HTTPCookieProcessor)
                      for c in h.cookiejar if c.name == "pilot_session")
        intake = {"questionnaire_context_hash": assigned_context(cookie)["context_hash"],
                  "answers": answers(), "request_id": "role_regression_intake_001",
                  "questionnaire_version": QUESTIONNAIRE_VERSION,
                  "questionnaire_hash": digest(QUESTIONS), "research_consent": True,
                  "scenario_understood": True, "research_notice_version": "eb.research_notice.v2",
                  "ui_version": PARTICIPANT_UI_VERSION}
        self.assertEqual(self.request("/api/households", intake)[0], 201)
        self.assertEqual(self.request("/api/admin/roles/feedback")[0], 403)
        code, session = self.request("/api/roles/session")
        self.assertEqual((code, session["ready"]), (200, True))
        self.assertEqual(self.request("/api/roles/preview/cityrole-0001")[0], 200)
        self.assertEqual(self.request("/api/roles/consent", {"accept": True, "consent_version": "consent-v1",
                                                       "human_mode": True, "release_gate_path": str(self.gate)})[0], 400)
        gate = json.loads(self.gate.read_text())
        gate["schema_version"] = "eb.engineering_fixture.v1"
        self.gate.write_text(json.dumps(gate))
        self.assertFalse(self.request("/api/roles/session")[1]["ready"])
        gate["schema_version"] = RELEASE_GATE_VERSION
        gate["meter_version_sha256"] = "c" * 64
        self.gate.write_text(json.dumps(gate))
        self.assertFalse(self.request("/api/roles/session")[1]["ready"])
        gate["meter_version_sha256"] = self.bank["meter_version_sha256"]
        gate["revoked"] = True
        self.gate.write_text(json.dumps(gate))
        self.assertFalse(self.request("/api/roles/session")[1]["ready"])
        self.assertEqual(self.request("/api/roles/consent", {"accept": True, "consent_version": "consent-v1"})[0], 503)

    def test_human_server_rejects_engineering_gate_override(self):
        with self.assertRaisesRegex(ValueError, "fixed accepted casebank and F release gate"):
            make_server(0, root=Path(self.tmp.name) / "human-blocked", role_human_pilot=True,
                        role_casebank_dir=Path(self.tmp.name) / "casebank",
                        role_release_gate_path=self.gate, role_expected_roles=2,
                        disable_planning=True)

    def test_human_questionnaire_and_engineering_roles_are_independent(self):
        extra = make_server(0, root=Path(self.tmp.name) / "combined-data",
                            human_pilot=True, disable_planning=True,
                            role_casebank_dir=Path(self.tmp.name) / "casebank",
                            role_release_gate_path=self.gate, role_expected_roles=2)
        worker = threading.Thread(target=extra.serve_forever, daemon=True)
        worker.start()
        origin = f"http://127.0.0.1:{extra.server_address[1]}"
        client = build_opener(ProxyHandler({}), HTTPCookieProcessor(http.cookiejar.CookieJar()))
        def request(path, payload=None):
            headers = {"Origin": origin, "Content-Type": "application/json"} if payload is not None else {}
            req = Request(origin + path, data=json.dumps(payload).encode() if payload is not None else None,
                          headers=headers)
            with client.open(req) as response:
                return json.loads(response.read())
        try:
            self.assertEqual(request("/api/session")["collection_mode"], "human_pilot")
            role = request("/api/roles/session")
            self.assertTrue(role["ready"])
            self.assertEqual(role["collection_mode"], "engineering_preview")
            actor = request("/api/roles/consent", {"accept": True, "consent_version": "consent-v1"})
            request("/api/roles/day/1")
            request("/api/roles/day-action", {"day_index": 1, "action": "acknowledge",
                                                   "idempotency_key": "combined-ack-001"})
            day = request("/api/roles/day/2")
            payload = {"schema_version": "eb.role_ten_day_blind_feedback.v1",
                       "casebank_sha256": day["casebank_sha256"], "profile_sha256": day["profile_sha256"],
                       "actor_pseudonym": actor["actor_id"], "role_id": actor["role_id"],
                       "case_id": day["case_id"], "day_index": 2,
                       "display_order_hash": day["display_order_hash"], "choice": "cannot_judge",
                       "reason": "组合模式工程检查", "ratings_by_side": {
                           side: {field: None for field in ("score", "comfort_score", "energy_score", "vpp_score")}
                           for side in ("left", "right")}, "idempotency_key": "combined-answer-001"}
            request("/api/roles/feedback", payload)
            self.assertEqual(extra.role_study.export_rows(training_only=False)[0]["data_origin"], "synthetic_engineering_test")
            self.assertEqual(extra.role_study.export_rows(training_only=True), [])
            self.assertTrue(extra.store.human_pilot)
            self.assertFalse(extra.role_study.human_mode)
        finally:
            extra.shutdown()
            worker.join(timeout=5)
            extra.server_close()
            extra.store.db.close()
        human_role = RoleStudy(Path(self.tmp.name) / "separate-human-role-data",
                               casebank_dir=Path(self.tmp.name) / "casebank",
                               release_gate_path=self.gate, expected_roles=2, human_mode=True)
        self.assertFalse(human_role.ready)

    def test_missing_casebank_cannot_open_collection(self):
        with tempfile.TemporaryDirectory() as empty:
            study = RoleStudy(Path(empty) / "data", casebank_dir=Path(empty) / "missing",
                              release_gate_path=self.gate, expected_roles=2)
            self.assertFalse(study.session("test-session")["ready"])
            with self.assertRaises(RuntimeError):
                study.consent("test-session", {"accept": True, "consent_version": "consent-v1"})

    def test_blind_label_and_private_path_are_rejected_before_release(self):
        path = Path(self.tmp.name) / "casebank" / "display_payloads.json"
        original = json.loads(path.read_text())
        changed = copy.deepcopy(original)
        first = next(iter(changed))
        changed[first]["plans"]["A"]["device_schedule"] = ["方案 A：测试设备"]
        path.write_text(json.dumps(changed, ensure_ascii=False))
        study = RoleStudy(Path(self.tmp.name) / "other-data", casebank_dir=path.parent,
                          release_gate_path=self.gate, expected_roles=2)
        self.assertFalse(study.ready)
        self.assertIn("internal A/B label", study.load_error)
        changed = copy.deepcopy(original)
        changed[first]["context"] = "/Users/example/private"
        path.write_text(json.dumps(changed, ensure_ascii=False))
        study = RoleStudy(Path(self.tmp.name) / "third-data", casebank_dir=path.parent,
                          release_gate_path=self.gate, expected_roles=2)
        self.assertFalse(study.ready)
        self.assertIn("private model path", study.load_error)

    def test_public_csv_content_must_match_manifest(self):
        copy = Path(self.tmp.name) / "public-copy"
        shutil.copytree(PUBLIC_DIR, copy)
        path = copy / "households_300.csv"
        raw = path.read_bytes()
        path.write_bytes(raw.replace("南昌市".encode(), "虚构市".encode(), 1))
        with self.assertRaisesRegex(ValueError, "public role CSV content mismatch"):
            RoleStudy(Path(self.tmp.name) / "modified-csv-data", casebank_dir=Path(self.tmp.name) / "casebank",
                      release_gate_path=self.gate, public_dir=copy, expected_roles=2)

    def test_complete_role_facts_cover_household_and_device_scenarios(self):
        study = self.server.role_study = RoleStudy(Path(self.tmp.name) / "server-data",
            casebank_dir=Path(self.tmp.name) / "casebank", release_gate_path=self.gate, expected_roles=2)
        selected = set()
        selected.add(next(rid for rid, h in study.profiles.items() if h["family_size"] == "1"))
        selected.add(next(rid for rid, h in study.profiles.items() if int(h["family_size"]) > 1))
        selected.add(next(rid for rid, h in study.profiles.items() if h["housing_mode"].startswith("shared")))
        selected.add(next(rid for rid, members in study.members.items() if any(m["routine"] == "irregular" for m in members)))
        for device in ("ac", "washer", "dryer", "dishwasher", "electric_water_heater", "home_ev"):
            selected.add(next(rid for rid, devices in study.devices.items() if any(d["device"] == device for d in devices)))
        for role_id in selected:
            code, data = self.request(f"/api/roles/preview/{role_id}")
            self.assertEqual(code, 200)
            self.assertIn("【合成角色条件", data["household"]["actor_card_full"])
            self.assertNotRegex(data["household"]["actor_card_full"], r"m\d{2}|\bH7\b|源户位 (?:edge|middle)")
            self.assertEqual(len(data["question_facts"]), 66)
            self.assertTrue(data["member_windows"])
            self.assertTrue(all(d["operation_condition"] for d in data["devices"]))
            self.assertTrue(all(not re.search(r"m\d{2}", d["operation_condition"])
                                for d in data["devices"]))
            self.assertTrue(all(q["display"] not in {"not_applicable", "UNKNOWN"} for q in data["question_facts"]))

    def test_persist_resume_feedback_revision_withdraw_and_isolation(self):
        self.request("/api/roles/session")
        code, consent = self.request("/api/roles/consent", {"accept": True, "consent_version": "consent-v1"})
        self.assertEqual(code, 200)
        self.assertEqual(consent["role_id"], "cityrole-0001")
        code, first = self.request("/api/roles/day/1")
        self.assertEqual((code, first["collectable"]), (200, False))
        self.assertEqual(self.request("/api/roles/day/10")[0], 400)
        self.assertEqual(self.request("/api/roles/feedback", {"day_index": 2})[0], 400)
        acknowledged = self.request("/api/roles/day-action", {"day_index": 1, "action": "acknowledge",
                                                             "idempotency_key": "acknowledge-key-001"})[1]
        self.assertEqual(acknowledged["next_day_index"], 2)
        unseen_case = self.bank["records"][0]["days"][1]["case_id"]
        unseen_order = blind_order(self.server.role_study.seed, stable_hash(self.bank),
                                   consent["actor_id"], consent["role_id"], 2)
        unseen_payload = {"schema_version": "eb.role_ten_day_blind_feedback.v1",
                          "casebank_sha256": stable_hash(self.bank), "profile_sha256": self.bank["profile_sha256"],
                          "actor_pseudonym": consent["actor_id"], "role_id": consent["role_id"],
                          "case_id": unseen_case, "day_index": 2,
                          "display_order_hash": unseen_order["display_order_hash"], "choice": "tie",
                          "reason": "未展示前直接提交的工程反例", "ratings_by_side": {
                              side: {field: None for field in ("score", "comfort_score", "energy_score", "vpp_score")}
                              for side in ("left", "right")}, "idempotency_key": "unseen-answer-001"}
        self.assertEqual(self.request("/api/roles/feedback", unseen_payload)[0], 400)
        code, day = self.request("/api/roles/day/2")
        self.assertEqual((code, day["collectable"]), (200, True))
        payload = {"schema_version": "eb.role_ten_day_blind_feedback.v1",
                   "casebank_sha256": day["casebank_sha256"], "profile_sha256": day["profile_sha256"],
                   "actor_pseudonym": consent["actor_id"], "role_id": consent["role_id"],
                   "case_id": day["case_id"], "day_index": 2,
                   "display_order_hash": day["display_order_hash"], "choice": "tie",
                   "reason": "工程测试原因", "ratings_by_side": {
                       side: {field: None for field in ("score", "comfort_score", "energy_score", "vpp_score")}
                       for side in ("left", "right")}, "idempotency_key": "engineering-key-001"}
        spoof = copy.deepcopy(payload)
        spoof["data_origin"] = "human_participant"
        self.assertEqual(self.request("/api/roles/feedback", spoof)[0], 400)
        code, saved = self.request("/api/roles/feedback", payload)
        self.assertEqual((code, saved["revision"]), (200, 1))
        self.assertTrue(self.request("/api/roles/feedback", payload)[1]["duplicate"])
        changed = copy.deepcopy(payload)
        changed["reason"] = "changed"
        self.assertEqual(self.request("/api/roles/feedback", changed)[0], 400)
        self.assertEqual(self.request("/api/roles/day/2")[1]["response_status"], "submitted")
        cookie = next(c.value for c in self.client.handlers if isinstance(c, HTTPCookieProcessor)
                      for c in c.cookiejar if c.name == "pilot_session")
        reloaded = RoleStudy(Path(self.tmp.name) / "server-data", casebank_dir=Path(self.tmp.name) / "casebank",
                             release_gate_path=self.gate, expected_roles=2)
        self.assertEqual(reloaded.session(cookie)["role_id"], "cityrole-0001")
        self.assertEqual(reloaded.day(cookie, 2)["response_status"], "submitted")
        self.assertEqual(self.server.role_study.export_rows(training_only=True), [])
        self.assertEqual(self.request("/api/admin/roles/feedback?view=training", admin=True)[1]["count"], 0)
        self.assertEqual(self.request("/api/admin/roles/feedback?view=audit", admin=True)[1]["count"], 1)
        other = build_opener(ProxyHandler({}), HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.request("/api/roles/session", client=other)
        self.assertEqual(self.request("/api/roles/day/2", client=other)[0], 404)
        receipt = self.request("/api/roles/withdraw-day", {"target_event_id": saved["event_id"],
                                                          "withdrawal_key": "withdraw-key-001"})[1]
        self.assertFalse(receipt["duplicate"])
        self.assertTrue(self.request("/api/roles/withdraw-day", {"target_event_id": saved["event_id"],
                                                               "withdrawal_key": "withdraw-key-001"})[1]["duplicate"])
        revised = copy.deepcopy(payload)
        revised["idempotency_key"] = "engineering-key-002"
        revised_saved = self.request("/api/roles/feedback", revised)[1]
        self.assertEqual(revised_saved["revision"], 2)
        self.assertEqual(self.request("/api/roles/session")[1]["role_id"], "cityrole-0001")
        gate = json.loads(self.gate.read_text())
        gate["revoked"] = True
        self.gate.write_text(json.dumps(gate))
        frozen = self.request("/api/roles/session")[1]
        self.assertFalse(frozen["ready"])
        self.assertEqual(frozen["withdrawable_events"], [{"event_id": revised_saved["event_id"], "day_index": 2}])
        self.assertEqual(self.request("/api/roles/day/2")[0], 503)
        self.assertEqual(self.request("/api/roles/withdraw-day", {"target_event_id": revised_saved["event_id"],
                                                                "withdrawal_key": "frozen-withdraw-001"})[0], 200)
        self.assertTrue(self.request("/api/roles/withdraw-actor", {"confirm": True})[1]["withdrawn"])
        self.assertEqual(self.request("/api/roles/feedback", revised)[0], 503)
        with self.assertRaises(RuntimeError): self.server.role_study.export_rows(training_only=True)

    def test_future_exposure_after_skip_marks_late_answer(self):
        self.request("/api/roles/session")
        actor = self.request("/api/roles/consent", {"accept": True, "consent_version": "consent-v1"})[1]
        self.request("/api/roles/day/1")
        self.request("/api/roles/day-action", {"day_index": 1, "action": "acknowledge",
                                                "idempotency_key": "acknowledge-key-002"})
        day = self.request("/api/roles/day/2")[1]
        skipped = self.request("/api/roles/day-action", {"day_index": 2, "action": "skip",
                                                       "skip_reason": "工程测试跳过", "idempotency_key": "skip-key-00002"})[1]
        self.assertEqual(skipped["status"], "skipped")
        self.assertEqual(self.request("/api/roles/day/3")[0], 200)
        payload = {"schema_version": "eb.role_ten_day_blind_feedback.v1",
                   "casebank_sha256": day["casebank_sha256"], "profile_sha256": day["profile_sha256"],
                   "actor_pseudonym": actor["actor_id"], "role_id": actor["role_id"],
                   "case_id": day["case_id"], "day_index": 2,
                   "display_order_hash": day["display_order_hash"], "choice": "cannot_judge",
                   "reason": "工程测试补答", "ratings_by_side": {
                       side: {field: None for field in ("score", "comfort_score", "energy_score", "vpp_score")}
                       for side in ("left", "right")}, "idempotency_key": "late-answer-key-002"}
        saved = self.request("/api/roles/feedback", payload)[1]
        self.assertTrue(saved["future_exposure"])
        audit = self.request("/api/admin/roles/feedback?view=audit", admin=True)[1]["rows"]
        self.assertTrue(audit[0]["future_exposure"])
        log = self.request("/api/admin/roles/action-log", admin=True)[1]["rows"]
        self.assertEqual([r["day_index"] for r in log if r["action"] == "view"], [1, 2, 3])
        self.assertEqual(next(r for r in log if r["action"] == "skip")["skip_reason"], "工程测试跳过")

    def test_new_bank_and_consent_version_exclude_old_training_rows(self):
        gate = json.loads(self.gate.read_text())
        gate["status"] = "ROLE_COLLECTION_APPROVED"
        gate["human_collection_approved"] = True
        gate["engineering_only"] = False
        self.gate.write_text(json.dumps(gate))
        data_root = Path(self.tmp.name) / "human-context-emulation-data"
        study = RoleStudy(data_root, casebank_dir=Path(self.tmp.name) / "casebank",
                          release_gate_path=self.gate, expected_roles=2, human_mode=True)
        actor = study.consent("emulated-session", {"accept": True, "consent_version": "consent-v1"})
        study.day("emulated-session", 1)
        study.day_action("emulated-session", {"day_index": 1, "action": "acknowledge",
                                             "idempotency_key": "emulated-ack-0001"})
        day = study.day("emulated-session", 2)
        payload = {"schema_version": "eb.role_ten_day_blind_feedback.v1",
                   "casebank_sha256": day["casebank_sha256"], "profile_sha256": day["profile_sha256"],
                   "actor_pseudonym": actor["actor_id"], "role_id": actor["role_id"],
                   "case_id": day["case_id"], "day_index": 2,
                   "display_order_hash": day["display_order_hash"], "choice": "tie",
                   "reason": "仅工程测试的真人来源仿真", "ratings_by_side": {
                       side: {field: None for field in ("score", "comfort_score", "energy_score", "vpp_score")}
                       for side in ("left", "right")}, "idempotency_key": "emulated-answer-001"}
        study.feedback("emulated-session", payload)
        self.assertEqual(len(study.export_rows(training_only=True)), 1)
        study.day("emulated-session", 3)
        revision = copy.deepcopy(payload)
        revision["idempotency_key"] = "emulated-answer-002"
        revision["reason"] = "工程测试：看过后续日后修改"
        self.assertTrue(study.feedback("emulated-session", revision)["future_exposure"])
        self.assertEqual(study.export_rows(training_only=True), [])
        bank_path = Path(self.tmp.name) / "casebank" / "casebank.json"
        bank = json.loads(bank_path.read_text())
        bank["consent_version"] = "consent-v2"
        bank_path.write_text(json.dumps(bank, ensure_ascii=False))
        gate = json.loads(self.gate.read_text())
        gate["casebank_sha256"] = stable_hash(bank)
        self.gate.write_text(json.dumps(gate))
        reloaded_consent = RoleStudy(data_root, casebank_dir=bank_path.parent, release_gate_path=self.gate,
                                     expected_roles=2, human_mode=True)
        self.assertTrue(reloaded_consent.ready)
        self.assertEqual(reloaded_consent.export_rows(training_only=True), [])
        self.assertEqual(len(reloaded_consent.export_rows(training_only=False)), 2)
        old_session = reloaded_consent.session("emulated-session")
        self.assertFalse(old_session["current_enrollment"])
        self.assertEqual(old_session["days"], [])
        self.assertEqual(len(old_session["withdrawable_events"]), 1)
        bank["study_batch_id"] = "new-batch"
        bank_path.write_text(json.dumps(bank, ensure_ascii=False))
        gate["casebank_sha256"] = stable_hash(bank)
        self.gate.write_text(json.dumps(gate))
        reloaded = RoleStudy(data_root, casebank_dir=bank_path.parent, release_gate_path=self.gate,
                             expected_roles=2, human_mode=True)
        self.assertTrue(reloaded.ready)
        self.assertEqual(reloaded.export_rows(training_only=True), [])
        self.assertEqual(len(reloaded.export_rows(training_only=False)), 2)
        self.assertFalse(reloaded.session("emulated-session")["current_enrollment"])
        with self.assertRaises(ValueError):
            reloaded.consent("emulated-session", {"accept": True, "consent_version": "consent-v2"})


if __name__ == "__main__":
    unittest.main()
