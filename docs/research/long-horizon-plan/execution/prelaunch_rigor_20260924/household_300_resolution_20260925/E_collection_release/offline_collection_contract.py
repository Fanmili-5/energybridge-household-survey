"""Pure, offline contract for an accepted ten-day casebank and feedback events.

This module does not generate plans, call models, persist participants, or make
synthetic feedback. A production service must add transactional storage and
authorization around the same validation rules.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import copy
from collections import defaultdict

CASEBANK_VERSION = "eb.offline_casebank.v1"
FEEDBACK_VERSION = "eb.role_ten_day_blind_feedback.v1"
LEGACY_SCORE_FIELDS = ("score", "comfort_score", "energy_score", "vpp_score")
CHOICES = {"left", "right", "tie", "reject_both", "cannot_judge"}
ORIGINS = {"human_participant", "synthetic_engineering_test"}
CONTRAST_BASIS = {"device_schedule", "temperature_setpoint", "cost_weight",
                  "task_completion", "comfort_impact", "grid_service"}


def stable_hash(value):
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def require_hex(name, value):
    if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")


def validate_casebank(bank, *, accepted_contrast_index, expected_roles=300):
    if bank.get("schema_version") != CASEBANK_VERSION or bank.get("status") != "accepted_offline":
        raise ValueError("only an accepted offline casebank may be consumed")
    for key in ("profile_sha256", "behavior_sha256", "questionnaire_sha256", "final_evidence_sha256"):
        require_hex(key, bank.get(key))
    require_hex("semantic_contrast_evidence_sha256", bank.get("semantic_contrast_evidence_sha256"))
    if (not isinstance(accepted_contrast_index, dict) or
            accepted_contrast_index.get("status") != "independently_accepted" or
            accepted_contrast_index.get("schema_version") != "eb.accepted_day_contrast.v1" or
            accepted_contrast_index.get("final_evidence_sha256") != bank["final_evidence_sha256"] or
            stable_hash(accepted_contrast_index) != bank["semantic_contrast_evidence_sha256"]):
        raise ValueError("independently accepted day-contrast index required")
    decisions = accepted_contrast_index.get("decisions")
    if not isinstance(decisions, dict):
        raise ValueError("accepted contrast decisions missing")
    if not bank.get("study_batch_id") or not bank.get("consent_version"):
        raise ValueError("study batch and consent version required")
    if bank.get("participant_feedback") is not None:
        raise ValueError("casebank must not prefill participant feedback")
    records = bank.get("records")
    if not isinstance(records, list) or len(records) != expected_roles or expected_roles > 300:
        raise ValueError("casebank role count invalid")
    roles = set()
    case_ids = set()
    for record in records:
        rid = record.get("role_id")
        if not isinstance(rid, str) or not re.fullmatch(r"cityrole-\d{4}", rid) or rid in roles:
            raise ValueError("casebank role IDs must be unique stable cityrole IDs")
        roles.add(rid)
        if record.get("profile_sha256") != bank["profile_sha256"]:
            raise ValueError("role profile version mismatch")
        days = record.get("days")
        if not isinstance(days, list) or [day.get("day_index") for day in days] != list(range(1, 11)):
            raise ValueError(f"{rid}: exactly ten ordered days required")
        for day in days:
            cid = day.get("case_id")
            if not isinstance(cid, str) or not cid or cid in case_ids:
                raise ValueError("case IDs must be unique and nonempty")
            case_ids.add(cid)
            if decisions.get(cid) != {"pre_event_state_hash_A": day.get("pre_event_state_hash_A"),
                                      "pre_event_state_hash_B": day.get("pre_event_state_hash_B"),
                                      "plan_family_id": day.get("plan_family_id"),
                                      "plan_template_fingerprint": day.get("plan_template_fingerprint"),
                                      "plan_hash_A": day.get("plans", {}).get("A", {}).get("plan_hash"),
                                      "plan_hash_B": day.get("plans", {}).get("B", {}).get("plan_hash"),
                                      "day_action_hash_A": day.get("plans", {}).get("A", {}).get("day_action_hash"),
                                      "day_action_hash_B": day.get("plans", {}).get("B", {}).get("day_action_hash"),
                                      "semantic_contrast": day.get("semantic_contrast")}:
                raise ValueError(f"{cid}: semantic decision differs from accepted evidence index")
            if not day.get("plan_family_id") or day.get("case_status") != "accepted_simulation":
                raise ValueError(f"{cid}: plan family and accepted simulation required")
            require_hex(f"{cid}.plan_template_fingerprint", day.get("plan_template_fingerprint"))
            if not day.get("history_group_id") or type(day.get("history_max_day_index")) is not int or not 0 <= day["history_max_day_index"] < day["day_index"]:
                raise ValueError(f"{cid}: history must end before the displayed day")
            for slot in ("A", "B"):
                require_hex(f"{cid}.pre_event_state_hash_{slot}", day.get(f"pre_event_state_hash_{slot}"))
            if day["day_index"] == 1 and day["pre_event_state_hash_A"] != day["pre_event_state_hash_B"]:
                raise ValueError(f"{cid}: first-day background must be shared")
            if day.get("participant_feedback") is not None:
                raise ValueError(f"{cid}: casebank cannot prefill feedback")
            pair = day.get("plans")
            if not isinstance(pair, dict) or set(pair) != {"A", "B"}:
                raise ValueError(f"{cid}: plans A and B required")
            for slot in ("A", "B"):
                if not day["plans"][slot].get("plan_version_id"):
                    raise ValueError(f"{cid}.{slot}: plan version required")
                if pair[slot].get("plan_hash_scope") != "day_slice" or pair[slot].get("day_index") != day["day_index"]:
                    raise ValueError(f"{cid}.{slot}: plan hash must bind this event day, not a ten-day plan")
                for key in ("plan_hash", "day_action_hash", "display_payload_hash", "metrics_hash"):
                    require_hex(f"{cid}.{slot}.{key}", pair[slot].get(key))
            if day["day_index"] == 1 and pair["A"]["day_action_hash"] != pair["B"]["day_action_hash"]:
                raise ValueError(f"{cid}: shared first-day background requires the same action")
            semantic = day.get("semantic_contrast")
            if not isinstance(semantic, dict) or semantic.get("status") not in {"meaningful", "equivalent", "inapplicable"}:
                raise ValueError(f"{cid}: accepted semantic contrast decision required")
            require_hex(f"{cid}.semantic_contrast.evidence_hash", semantic.get("evidence_hash"))
            if semantic.get("source") != "accepted_pre_feedback_day_evidence":
                raise ValueError(f"{cid}: contrast must come from accepted pre-feedback evidence")
            status = semantic["status"]
            if status == "meaningful":
                if (pair["A"]["plan_hash"] == pair["B"]["plan_hash"] or
                        pair["A"]["day_action_hash"] == pair["B"]["day_action_hash"] or
                        semantic.get("basis") not in CONTRAST_BASIS or
                        semantic.get("same_day_action_change") is not True or day["day_index"] == 1):
                    raise ValueError(f"{cid}: meaningful contrast needs distinct day plans and a substantive basis")
            elif not isinstance(semantic.get("reason"), str) or not semantic["reason"].strip():
                raise ValueError(f"{cid}: noncollectable pair needs a reason")
            if day.get("pair_status") != ("contrast_valid" if status == "meaningful" else "no_effect_or_identical"):
                raise ValueError(f"{cid}: pair status disagrees with semantic decision")
            if day.get("collectable") is not (status == "meaningful"):
                raise ValueError(f"{cid}: only meaningful event-day contrasts are collectable")
    if expected_roles == 300 and roles != {f"cityrole-{i:04d}" for i in range(1, 301)}:
        raise ValueError("final casebank must contain cityrole-0001..0300 exactly")
    if set(decisions) != case_ids:
        raise ValueError("accepted contrast index has missing or extra cases")
    return {"roles": len(roles), "days": len(case_ids), "collectable_days": sum(
        day["collectable"] for record in records for day in record["days"])}


def case_index(bank):
    return {day["case_id"]: (record["role_id"], day)
            for record in bank["records"] for day in record["days"]}


def blind_order(secret_seed: bytes, casebank_sha256: str, actor_pseudonym: str, role_id: str, day_index: int):
    if not secret_seed or len(secret_seed) < 16:
        raise ValueError("private randomization seed must be at least 16 bytes")
    require_hex("casebank_sha256", casebank_sha256)
    message = f"{casebank_sha256}|{actor_pseudonym}|{role_id}|{day_index}".encode("utf-8")
    digest = hmac.new(secret_seed, message, hashlib.sha256).digest()
    left_slot = "A" if digest[0] & 1 == 0 else "B"
    right_slot = "B" if left_slot == "A" else "A"
    public_view = {"left": left_slot, "right": right_slot, "day_index": day_index}
    return {"left_slot": left_slot, "right_slot": right_slot,
            "display_order_hash": stable_hash({"message": message.decode("utf-8"), "view": public_view}),
            "seed_commitment": hashlib.sha256(secret_seed).hexdigest()}


class ActorRegistry:
    """In-memory fixture. Production storage must enforce the same uniqueness in a transaction."""
    def __init__(self):
        self.actor_to_role = {}
        self.role_to_actor = {}
        self.consents = {}

    def assign(self, actor_pseudonym, role_id):
        if (not isinstance(actor_pseudonym, str) or not actor_pseudonym or
                not isinstance(role_id, str) or not re.fullmatch(r"cityrole-\d{4}", role_id) or
                not 1 <= int(role_id[-4:]) <= 300):
            raise ValueError("actor and role required")
        old = self.actor_to_role.get(actor_pseudonym)
        if old is not None and old != role_id:
            raise ValueError("actor cannot switch role on resume")
        other = self.role_to_actor.get(role_id)
        if other is not None and other != actor_pseudonym:
            raise ValueError("default study batch allows one active actor per role")
        self.actor_to_role[actor_pseudonym] = role_id
        self.role_to_actor[role_id] = actor_pseudonym
        return role_id

    def record_consent(self, actor_pseudonym, *, version, recorded_at, study_batch_id):
        """Trusted server action after informed consent, never a browser feedback field."""
        if actor_pseudonym not in self.actor_to_role or actor_pseudonym in self.consents:
            raise ValueError("actor must be assigned and consent recorded only once per batch")
        if not all(isinstance(v, str) and v.strip() for v in (version, recorded_at, study_batch_id)):
            raise ValueError("consent version, time and batch required")
        self.consents[actor_pseudonym] = {"version": version, "recorded_at": recorded_at,
                                          "study_batch_id": study_batch_id, "active": True}

    def withdraw_consent(self, actor_pseudonym):
        if actor_pseudonym not in self.consents:
            raise ValueError("no recorded consent for actor")
        self.consents[actor_pseudonym]["active"] = False


def validate_submission(payload, bank, registry, secret_seed, casebank_sha256, *, trusted_origin,
                        accepted_contrast_index):
    validate_casebank(bank, accepted_contrast_index=accepted_contrast_index,
                      expected_roles=len(bank["records"]))
    require_hex("casebank_sha256", casebank_sha256)
    if stable_hash(bank) != casebank_sha256:
        raise ValueError("casebank content hash mismatch")
    if payload.get("schema_version") != FEEDBACK_VERSION:
        raise ValueError("feedback schema version mismatch")
    if "data_origin" in payload or "consent" in payload:
        raise ValueError("origin and consent are server-owned, not feedback fields")
    if trusted_origin not in ORIGINS:
        raise ValueError("trusted server origin required")
    if payload.get("casebank_sha256") != casebank_sha256:
        raise ValueError("stale casebank version")
    actor = payload.get("actor_pseudonym")
    role = payload.get("role_id")
    if registry.actor_to_role.get(actor) != role:
        raise ValueError("actor-role assignment mismatch")
    consent = registry.consents.get(actor)
    if trusted_origin == "human_participant" and (
            not consent or not consent["active"] or
            consent["version"] != bank["consent_version"] or
            consent["study_batch_id"] != bank["study_batch_id"]):
        raise ValueError("active matching server-recorded consent required")
    indexed = case_index(bank)
    cid = payload.get("case_id")
    if cid not in indexed or indexed[cid][0] != role:
        raise ValueError("case does not belong to assigned role")
    day = indexed[cid][1]
    if payload.get("day_index") != day["day_index"] or not day["collectable"]:
        raise ValueError("day mismatch or noncontrast case")
    expected_order = blind_order(secret_seed, casebank_sha256, actor, role, day["day_index"])
    if payload.get("display_order_hash") != expected_order["display_order_hash"]:
        raise ValueError("display order is stale or forged")
    if payload.get("choice") not in CHOICES:
        raise ValueError("choice must distinguish left/right/tie/reject_both/cannot_judge")
    reason = payload.get("reason")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000:
        raise ValueError("a nonempty reason of at most 1000 characters is required")
    ratings = payload.get("ratings_by_side")
    if not isinstance(ratings, dict) or set(ratings) != {"left", "right"}:
        raise ValueError("ratings_by_side must contain left and right, even if unrated")
    for side in ("left", "right"):
        values = ratings[side]
        if not isinstance(values, dict) or set(values) != set(LEGACY_SCORE_FIELDS):
            raise ValueError("preserve original four score fields for each shown side")
        for value in values.values():
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or not 1 <= value <= 5):
                raise ValueError("scores must be 1-5 finite values or explicitly null")
    key = payload.get("idempotency_key")
    if not isinstance(key, str) or len(key) < 12 or len(key) > 128:
        raise ValueError("idempotency key length invalid")
    if payload.get("profile_sha256") != bank["profile_sha256"]:
        raise ValueError("profile cannot be updated from future feedback")
    return {"consent_snapshot": copy.deepcopy(consent) if trusted_origin == "human_participant" else None,
            "left_plan_hash": day["plans"][expected_order["left_slot"]]["plan_hash"],
            "right_plan_hash": day["plans"][expected_order["right_slot"]]["plan_hash"],
            "left_plan_version_id": day["plans"][expected_order["left_slot"]]["plan_version_id"],
            "right_plan_version_id": day["plans"][expected_order["right_slot"]]["plan_version_id"],
            "plan_family_id": day["plan_family_id"],
            "plan_template_fingerprint": day["plan_template_fingerprint"],
            "history_group_id": day["history_group_id"],
            "history_max_day_index": day["history_max_day_index"],
            "display_order_hash": expected_order["display_order_hash"]}


class FeedbackLedger:
    """Pure replay model for contract tests; no production storage or fake human data."""
    def __init__(self):
        self.by_key = {}
        self.latest = {}
        self.events = []
        self.withdrawals = {}
        self.withdrawn_actors = set()

    def submit(self, payload, bank, registry, secret_seed, casebank_sha256, *, trusted_origin,
               accepted_contrast_index):
        checked = validate_submission(payload, bank, registry, secret_seed, casebank_sha256,
                                      trusted_origin=trusted_origin,
                                      accepted_contrast_index=accepted_contrast_index)
        actor = payload["actor_pseudonym"]
        if actor in self.withdrawn_actors:
            raise ValueError("withdrawn actor requires new consent and new study batch")
        dedup_key = (actor, payload["idempotency_key"])
        frozen_payload = copy.deepcopy(payload)
        payload_hash = stable_hash({"payload": frozen_payload, "trusted_origin": trusted_origin})
        if dedup_key in self.by_key:
            prior = self.by_key[dedup_key]
            if prior["payload_hash"] != payload_hash:
                raise ValueError("same idempotency key with changed content")
            return {"event_id": prior["event_id"], "duplicate": True, "revision": prior["revision"]}
        day_key = (actor, payload["case_id"])
        prior = self.latest.get(day_key)
        revision = prior["revision"] + 1 if prior else 1
        event_id = stable_hash({"actor": actor, "case_id": payload["case_id"],
                                "revision": revision, "payload_hash": payload_hash})
        event = {"event_id": event_id, "revision": revision, "payload_hash": payload_hash,
                 "payload": frozen_payload, "verified": copy.deepcopy(checked),
                 "trusted_origin": trusted_origin, "status": "submitted"}
        if prior and prior["status"] == "submitted": prior["status"] = "superseded"
        self.by_key[dedup_key] = event
        self.latest[day_key] = event
        self.events.append(event)
        return {"event_id": event_id, "duplicate": False, "revision": revision}

    def withdraw(self, actor_pseudonym, target_event_id, withdrawal_key):
        if not withdrawal_key or len(withdrawal_key) < 12:
            raise ValueError("withdrawal idempotency key required")
        dedup_key = (actor_pseudonym, withdrawal_key)
        if dedup_key in self.withdrawals:
            prior = self.withdrawals[dedup_key]
            if prior["target_event_id"] != target_event_id:
                raise ValueError("same withdrawal key with changed target")
            return {**prior, "duplicate": True}
        targets = [event for event in self.events if event["event_id"] == target_event_id and
                   event["payload"]["actor_pseudonym"] == actor_pseudonym]
        if len(targets) != 1:
            raise ValueError("target response not found for actor")
        target = targets[0]
        if self.latest.get((actor_pseudonym, target["payload"]["case_id"])) is not target:
            raise ValueError("only the current day response may be withdrawn")
        target["status"] = "withdrawn"
        receipt = {"target_event_id": target_event_id, "status": "withdrawn",
                   "withdrawal_receipt": stable_hash({"actor": actor_pseudonym, "target": target_event_id,
                                                      "key": withdrawal_key})}
        self.withdrawals[dedup_key] = receipt
        return {**receipt, "duplicate": False}

    def withdraw_actor(self, actor_pseudonym, registry):
        """Consent withdrawal excludes every response from this actor's training export."""
        if actor_pseudonym in self.withdrawn_actors:
            return {"actor_pseudonym": actor_pseudonym, "duplicate": True}
        registry.withdraw_consent(actor_pseudonym)
        self.withdrawn_actors.add(actor_pseudonym)
        for event in self.events:
            if event["payload"]["actor_pseudonym"] == actor_pseudonym:
                event["status"] = "withdrawn"
        return {"actor_pseudonym": actor_pseudonym, "duplicate": False}


def export_feedback_rows(ledger, *, include_engineering_tests=False):
    rows = []
    for event in ledger.events:
        payload = event["payload"]
        if event["trusted_origin"] == "synthetic_engineering_test" and not include_engineering_tests:
            continue
        rows.append({"event_id": event["event_id"], "actor_pseudonym": payload["actor_pseudonym"],
                     "role_id": payload["role_id"], "casebank_sha256": payload["casebank_sha256"],
                     "profile_sha256": payload["profile_sha256"], "case_id": payload["case_id"],
                     "day_index": payload["day_index"], "plan_family_id": event["verified"]["plan_family_id"],
                     "plan_template_fingerprint": event["verified"]["plan_template_fingerprint"],
                     "history_group_id": event["verified"]["history_group_id"],
                     "history_max_day_index": event["verified"]["history_max_day_index"],
                     "display_order_hash": event["verified"]["display_order_hash"],
                     "left_plan_hash": event["verified"]["left_plan_hash"],
                     "right_plan_hash": event["verified"]["right_plan_hash"],
                     "left_plan_version_id": event["verified"]["left_plan_version_id"],
                     "right_plan_version_id": event["verified"]["right_plan_version_id"],
                     "choice": payload["choice"], "reason": payload["reason"],
                     "ratings_by_side": copy.deepcopy(payload["ratings_by_side"]),
                     "response_status": event["status"], "revision": event["revision"],
                     "data_origin": event["trusted_origin"],
                     "consent_snapshot": copy.deepcopy(event["verified"]["consent_snapshot"])})
    return rows


def training_rows(ledger, registry, bank):
    """Only active, consented human submissions; audit events remain in the ledger."""
    result = []
    for row in export_feedback_rows(ledger):
        consent = registry.consents.get(row["actor_pseudonym"])
        if (row["response_status"] == "submitted" and
                row["actor_pseudonym"] not in ledger.withdrawn_actors and
                consent and consent["active"] and row["consent_snapshot"] == consent and
                consent["version"] == bank["consent_version"] and
                consent["study_batch_id"] == bank["study_batch_id"]):
            result.append(row)
    return result


def _validate_split_rows(rows):
    for row in rows:
        for label in ("actor_pseudonym", "role_id", "plan_family_id", "history_group_id",
                      "plan_template_fingerprint"):
            if not row.get(label):
                raise ValueError(f"missing leakage identity: {label}")
        if type(row.get("day_index")) is not int or type(row.get("history_max_day_index")) is not int or not 0 <= row["history_max_day_index"] < row["day_index"]:
            raise ValueError("history includes current or future day")


def isolation_components(rows, *, track="primary_unseen_household"):
    """Components for the preregistered track; primary may share plan families."""
    if track not in {"primary_unseen_household", "strict_unseen_household_and_family"}:
        raise ValueError("unknown evaluation track")
    _validate_split_rows(rows)
    parent = list(range(len(rows)))
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def union(a, b):
        parent[find(b)] = find(a)
    owners = {}
    for index, row in enumerate(rows):
        labels = ("actor_pseudonym", "role_id", "history_group_id")
        if track == "strict_unseen_household_and_family":
            labels += ("plan_family_id", "plan_template_fingerprint")
        for label in labels:
            value = row.get(label)
            key = (label, value)
            if key in owners: union(index, owners[key])
            else: owners[key] = index
    groups = defaultdict(list)
    for index in range(len(rows)):
        groups[find(index)].append(index)
    return list(groups.values())


def split_rows(rows, *, train_roles, test_roles, track="primary_unseen_household",
               train_families=None, test_families=None):
    """Apply preregistered role/family sets; strict cross cells are excluded."""
    _validate_split_rows(rows)
    if not train_roles or not test_roles or set(train_roles) & set(test_roles):
        raise ValueError("nonempty disjoint train/test role sets required")
    strict = track == "strict_unseen_household_and_family"
    if track not in {"primary_unseen_household", "strict_unseen_household_and_family"}:
        raise ValueError("unknown evaluation track")
    if strict and (not train_families or not test_families or set(train_families) & set(test_families)):
        raise ValueError("strict track needs nonempty disjoint plan-family sets")
    result = {"train": [], "test": [], "excluded": []}
    for row in rows:
        role_side = "train" if row["role_id"] in train_roles else "test" if row["role_id"] in test_roles else None
        if strict:
            family_side = ("train" if row["plan_family_id"] in train_families else
                           "test" if row["plan_family_id"] in test_families else None)
            side = role_side if role_side == family_side else None
        else:
            side = role_side
        result[side or "excluded"].append(row)
    if not result["train"] or not result["test"]:
        raise ValueError("requested track has no feasible nonempty train/test split")
    for label in ("actor_pseudonym", "role_id", "history_group_id") + (("plan_family_id", "plan_template_fingerprint") if strict else ()):
        if {row[label] for row in result["train"]} & {row[label] for row in result["test"]}:
            raise ValueError(f"split leaks {label}")
    return result
