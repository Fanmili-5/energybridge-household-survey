"""Engineering fixtures only: no human feedback or accepted simulation data."""
import copy
import unittest

from offline_collection_contract import (
    ActorRegistry, FeedbackLedger, blind_order, export_feedback_rows,
    isolation_components, split_rows, stable_hash, training_rows, validate_casebank,
)

H = "a" * 64
SEED = b"local-test-seed-is-never-published"


def fixture_bank():
    records = []
    for role_num in (1, 2):
        role = f"cityrole-{role_num:04d}"
        days = []
        for index in range(1, 11):
            plans = {
                slot: {"plan_version_id": f"{role}-{index}-{slot}-v1",
                       "plan_hash_scope": "day_slice", "day_index": index,
                       "plan_hash": stable_hash([role, index, slot]),
                       "day_action_hash": stable_hash(["action", role, index, slot]),
                       "display_payload_hash": stable_hash(["display", role, index, slot]),
                       "metrics_hash": stable_hash(["metrics", role, index, slot])}
                for slot in ("A", "B")
            }
            if index == 1:
                plans["B"]["plan_hash"] = plans["A"]["plan_hash"]
                plans["B"]["day_action_hash"] = plans["A"]["day_action_hash"]
            days.append({"case_id": f"{role}-day-{index}", "day_index": index,
                         "plan_family_id": f"family-{role}",
                         "plan_template_fingerprint": stable_hash(["template", role]),
                         "history_group_id": f"history-{role}",
                         "history_max_day_index": index - 1,
                         "pre_event_state_hash_A": stable_hash(["state-A", role, index]),
                         "pre_event_state_hash_B": stable_hash(["state-A" if index == 1 else "state-B", role, index]),
                         "semantic_contrast": {"status": "equivalent" if index == 1 else "meaningful",
                                               "basis": "device_schedule" if index > 1 else None,
                                               "reason": "shared baseline" if index == 1 else None,
                                               "same_day_action_change": index > 1,
                                               "source": "accepted_pre_feedback_day_evidence",
                                               "evidence_hash": stable_hash(["schedule_difference", role, index])},
                         "case_status": "accepted_simulation", "pair_status": "no_effect_or_identical" if index == 1 else "contrast_valid",
                         "collectable": index > 1, "plans": plans})
        records.append({"role_id": role, "profile_sha256": H, "days": days})
    bank = {"schema_version": "eb.offline_casebank.v1", "status": "accepted_offline",
            "study_batch_id": "engineering-batch-1", "consent_version": "consent-v1",
            "profile_sha256": H, "behavior_sha256": H,
            "questionnaire_sha256": H, "final_evidence_sha256": H,
            "records": records}
    evidence = fixture_evidence(bank)
    bank["semantic_contrast_evidence_sha256"] = stable_hash(evidence)
    return bank, evidence


def fixture_evidence(bank):
    return {"schema_version": "eb.accepted_day_contrast.v1", "status": "independently_accepted",
            "final_evidence_sha256": bank["final_evidence_sha256"], "decisions": {
                day["case_id"]: {"pre_event_state_hash_A": day["pre_event_state_hash_A"],
                                  "pre_event_state_hash_B": day["pre_event_state_hash_B"],
                                  "plan_family_id": day["plan_family_id"],
                                  "plan_template_fingerprint": day["plan_template_fingerprint"],
                                  "plan_hash_A": day["plans"]["A"]["plan_hash"],
                                  "plan_hash_B": day["plans"]["B"]["plan_hash"],
                                  "day_action_hash_A": day["plans"]["A"]["day_action_hash"],
                                  "day_action_hash_B": day["plans"]["B"]["day_action_hash"],
                                  "semantic_contrast": copy.deepcopy(day["semantic_contrast"])}
                for record in bank["records"] for day in record["days"]}}


def fixture_payload(bank, actor="test-actor-1", role="cityrole-0001", day=2, key="test-key-00001"):
    bank_hash = stable_hash(bank)
    order = blind_order(SEED, bank_hash, actor, role, day)
    return {"schema_version": "eb.role_ten_day_blind_feedback.v1",
            "casebank_sha256": bank_hash,
            "profile_sha256": H, "actor_pseudonym": actor, "role_id": role,
            "case_id": f"{role}-day-{day}", "day_index": day,
            "display_order_hash": order["display_order_hash"], "choice": "left",
            "reason": "Engineering fixture", "ratings_by_side": {
                side: {field: None for field in ("score", "comfort_score", "energy_score", "vpp_score")}
                for side in ("left", "right")}, "idempotency_key": key}


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.bank, self.evidence = fixture_bank()
        self.digest = stable_hash(self.bank)
        self.registry = ActorRegistry()
        self.registry.assign("test-actor-1", "cityrole-0001")
        self.ledger = FeedbackLedger()

    def submit(self, payload, *, origin="synthetic_engineering_test"):
        return self.ledger.submit(payload, self.bank, self.registry, SEED, self.digest,
                                  trusted_origin=origin, accepted_contrast_index=self.evidence)

    def test_ten_day_bank_and_no_prefill(self):
        self.assertEqual(validate_casebank(self.bank, accepted_contrast_index=self.evidence, expected_roles=2),
                         {"roles": 2, "days": 20, "collectable_days": 18})
        changed = copy.deepcopy(self.bank)
        changed["records"][0]["days"].pop()
        with self.assertRaises(ValueError): validate_casebank(changed, accepted_contrast_index=self.evidence, expected_roles=2)
        changed = copy.deepcopy(self.bank)
        changed["records"][0]["days"][0]["participant_feedback"] = {"choice": "left"}
        with self.assertRaises(ValueError): validate_casebank(changed, accepted_contrast_index=self.evidence, expected_roles=2)

    def test_noncontrast_and_history_fail_closed(self):
        changed = copy.deepcopy(self.bank)
        day = changed["records"][0]["days"][1]
        day["plans"]["B"]["plan_hash"] = day["plans"]["A"]["plan_hash"]
        with self.assertRaises(ValueError): validate_casebank(changed, accepted_contrast_index=self.evidence, expected_roles=2)
        accepted = fixture_evidence(changed)
        changed["semantic_contrast_evidence_sha256"] = stable_hash(accepted)
        with self.assertRaises(ValueError): validate_casebank(changed, accepted_contrast_index=accepted, expected_roles=2)
        day["semantic_contrast"]["status"] = "equivalent"
        day["semantic_contrast"]["reason"] = "same event-day schedule"
        day["pair_status"] = "no_effect_or_identical"
        day["collectable"] = False
        accepted = fixture_evidence(changed)
        changed["semantic_contrast_evidence_sha256"] = stable_hash(accepted)
        self.assertEqual(validate_casebank(changed, accepted_contrast_index=accepted, expected_roles=2)["collectable_days"], 17)
        # Different byte hashes with only metadata changes are still uncollectable.
        day["plans"]["B"]["plan_hash"] = stable_hash("metadata-only-revision")
        accepted = fixture_evidence(changed)
        changed["semantic_contrast_evidence_sha256"] = stable_hash(accepted)
        self.assertEqual(validate_casebank(changed, accepted_contrast_index=accepted, expected_roles=2)["collectable_days"], 17)
        day["collectable"] = True
        with self.assertRaises(ValueError): validate_casebank(changed, accepted_contrast_index=accepted, expected_roles=2)
        changed = copy.deepcopy(self.bank)
        changed["records"][0]["days"][1]["history_max_day_index"] = 2
        with self.assertRaises(ValueError): validate_casebank(changed, accepted_contrast_index=self.evidence, expected_roles=2)
        changed = copy.deepcopy(self.bank)
        changed["records"][0]["days"][0]["plans"]["A"]["plan_hash_scope"] = "ten_day_plan"
        with self.assertRaises(ValueError): validate_casebank(changed, accepted_contrast_index=self.evidence, expected_roles=2)
        changed = copy.deepcopy(self.bank)
        day = changed["records"][0]["days"][1]
        day["plans"]["B"]["day_action_hash"] = day["plans"]["A"]["day_action_hash"]
        accepted = fixture_evidence(changed)
        changed["semantic_contrast_evidence_sha256"] = stable_hash(accepted)
        with self.assertRaises(ValueError): validate_casebank(changed, accepted_contrast_index=accepted, expected_roles=2)

    def test_actor_lock_blind_order_and_choices(self):
        with self.assertRaises(ValueError): self.registry.assign("test-actor-1", "cityrole-0002")
        with self.assertRaises(ValueError): self.registry.assign("another", "cityrole-0001")
        first = blind_order(SEED, self.digest, "test-actor-1", "cityrole-0001", 1)
        self.assertEqual(first, blind_order(SEED, self.digest, "test-actor-1", "cityrole-0001", 1))
        for index, choice in enumerate(("left", "right", "tie", "reject_both", "cannot_judge"), 2):
            payload = fixture_payload(self.bank, day=index, key=f"test-key-{index:05d}")
            payload["choice"] = choice
            self.submit(payload)
        bad = fixture_payload(self.bank, day=7, key="test-key-00006")
        bad["choice"] = "A"
        with self.assertRaises(ValueError): self.submit(bad)

    def test_scores_version_and_display_guard(self):
        base = fixture_payload(self.bank)
        base["ratings_by_side"]["left"] = dict.fromkeys(base["ratings_by_side"]["left"], 1)
        base["ratings_by_side"]["right"] = dict.fromkeys(base["ratings_by_side"]["right"], 5)
        self.submit(base)
        for field, value in (("score", 0), ("comfort_score", 6), ("energy_score", float("nan"))):
            bad = fixture_payload(self.bank, day=2, key=f"test-bad-{field}-0001")
            bad["ratings_by_side"]["left"][field] = value
            with self.assertRaises(ValueError): self.submit(bad)
        for field, value in (("display_order_hash", H), ("casebank_sha256", H), ("profile_sha256", "b" * 64)):
            bad = fixture_payload(self.bank, day=2, key=f"test-bad-{field}-0002")
            bad[field] = value
            with self.assertRaises(ValueError): self.submit(bad)

    def test_idempotency_revision_and_withdrawal(self):
        base = fixture_payload(self.bank)
        first = self.submit(base)
        self.assertFalse(first["duplicate"])
        self.assertTrue(self.submit(base)["duplicate"])
        altered = copy.deepcopy(base)
        altered["reason"] = "Changed reason"
        with self.assertRaises(ValueError): self.submit(altered)
        receipt = self.ledger.withdraw("test-actor-1", first["event_id"], "withdraw-key-0001")
        self.assertEqual(receipt["status"], "withdrawn")
        self.assertTrue(self.ledger.withdraw("test-actor-1", first["event_id"], "withdraw-key-0001")["duplicate"])
        self.assertEqual(training_rows(self.ledger, self.registry, self.bank), [])
        revised = fixture_payload(self.bank, key="test-key-00002")
        self.assertEqual(self.submit(revised)["revision"], 2)
        self.assertEqual(len(export_feedback_rows(self.ledger, include_engineering_tests=True)), 2)
        self.assertEqual(training_rows(self.ledger, self.registry, self.bank), [])
        self.registry.record_consent("test-actor-1", version="consent-v1",
                                     recorded_at="2026-09-26T00:00:00Z", study_batch_id="engineering-batch-1")
        self.assertFalse(self.ledger.withdraw_actor("test-actor-1", self.registry)["duplicate"])
        self.assertTrue(self.ledger.withdraw_actor("test-actor-1", self.registry)["duplicate"])
        with self.assertRaises(ValueError): self.submit(fixture_payload(self.bank, day=2, key="test-key-00003"))

    def test_training_export_only_active_human_response(self):
        first = fixture_payload(self.bank)
        # A browser-provided origin cannot turn an engineering event into human data.
        first["data_origin"] = "human_participant"
        with self.assertRaises(ValueError): self.submit(first)
        first.pop("data_origin")
        with self.assertRaises(ValueError): self.submit(first, origin="human_participant")
        self.registry.record_consent("test-actor-1", version="consent-v1",
                                     recorded_at="2026-09-26T00:00:00Z", study_batch_id="engineering-batch-1")
        self.submit(first, origin="human_participant")
        self.assertEqual(len(training_rows(self.ledger, self.registry, self.bank)), 1)
        second = fixture_payload(self.bank, key="test-key-00002")
        second["choice"] = "tie"
        self.submit(second, origin="human_participant")
        rows = training_rows(self.ledger, self.registry, self.bank)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["choice"], rows[0]["revision"]), ("tie", 2))
        self.ledger.withdraw_actor("test-actor-1", self.registry)
        self.assertEqual(training_rows(self.ledger, self.registry, self.bank), [])

    def test_consent_version_batch_origin_and_payload_snapshot(self):
        payload = fixture_payload(self.bank)
        self.registry.record_consent("test-actor-1", version="old-v0",
                                     recorded_at="2026-09-26T00:00:00Z", study_batch_id="engineering-batch-1")
        with self.assertRaises(ValueError): self.submit(payload, origin="human_participant")
        self.registry.consents["test-actor-1"]["version"] = "consent-v1"
        self.registry.consents["test-actor-1"]["study_batch_id"] = "old-batch"
        with self.assertRaises(ValueError): self.submit(payload, origin="human_participant")
        self.registry.consents["test-actor-1"]["study_batch_id"] = "engineering-batch-1"
        self.submit(payload, origin="human_participant")
        payload["reason"] = "caller mutation after submit"
        payload["ratings_by_side"]["left"]["score"] = 5
        row = export_feedback_rows(self.ledger)[0]
        self.assertEqual(row["reason"], "Engineering fixture")
        self.assertIsNone(row["ratings_by_side"]["left"]["score"])
        self.assertEqual(self.ledger.events[0]["payload_hash"], stable_hash({
            "payload": self.ledger.events[0]["payload"], "trusted_origin": "human_participant"}))
        self.assertEqual(len(training_rows(self.ledger, self.registry, self.bank)), 1)
        self.registry.withdraw_consent("test-actor-1")
        self.assertEqual(training_rows(self.ledger, self.registry, self.bank), [])

    def test_isolation_components(self):
        rows = [
            {"actor_pseudonym": "a", "role_id": "r1", "plan_family_id": "f1",
             "plan_template_fingerprint": stable_hash("template-a"),
             "history_group_id": "h1", "day_index": 2, "history_max_day_index": 1},
            {"actor_pseudonym": "b", "role_id": "r2", "plan_family_id": "f1",
             "plan_template_fingerprint": stable_hash("template-a"),
             "history_group_id": "h2", "day_index": 3, "history_max_day_index": 2},
            {"actor_pseudonym": "c", "role_id": "r3", "plan_family_id": "f3",
             "plan_template_fingerprint": stable_hash("template-c"),
             "history_group_id": "h3", "day_index": 4, "history_max_day_index": 3},
        ]
        self.assertEqual(sorted(len(part) for part in isolation_components(rows)), [1, 1, 1])
        self.assertEqual(sorted(len(part) for part in isolation_components(
            rows, track="strict_unseen_household_and_family")), [1, 2])
        primary = split_rows(rows, train_roles={"r1", "r3"}, test_roles={"r2"})
        self.assertEqual((len(primary["train"]), len(primary["test"])), (2, 1))
        strict = split_rows(rows, train_roles={"r1", "r3"}, test_roles={"r2"},
                            train_families={"f3"}, test_families={"f1"},
                            track="strict_unseen_household_and_family")
        self.assertEqual((len(strict["train"]), len(strict["test"]), len(strict["excluded"])), (1, 1, 1))
        with self.assertRaises(ValueError): split_rows(
            rows, train_roles={"r1"}, test_roles={"r2"}, train_families={"f1"},
            test_families={"f3"}, track="strict_unseen_household_and_family")
        renamed = copy.deepcopy(rows)
        renamed[1]["plan_family_id"] = "renamed-same-template"
        with self.assertRaises(ValueError): split_rows(
            renamed, train_roles={"r1"}, test_roles={"r2"}, train_families={"f1"},
            test_families={"renamed-same-template"},
            track="strict_unseen_household_and_family")
        rows[2]["history_max_day_index"] = 4
        with self.assertRaises(ValueError): isolation_components(rows)


if __name__ == "__main__": unittest.main()
