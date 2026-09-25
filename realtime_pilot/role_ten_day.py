"""Isolated, offline-only role study storage and accepted casebank adapter."""
from __future__ import annotations

import csv
from contextlib import closing
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import sqlite3
import sys
import threading
from datetime import datetime, timezone

E_DIR = (Path(__file__).resolve().parent.parent / "docs/research/long-horizon-plan/execution/"
         "prelaunch_rigor_20260924/household_300_resolution_20260925/E_collection_release")
if str(E_DIR) not in sys.path:
    sys.path.insert(0, str(E_DIR))
from offline_collection_contract import (ActorRegistry, blind_order, case_index,
                                         stable_hash, validate_casebank, validate_submission)

PUBLIC_DIR = E_DIR / "public_role_package"
DEFAULT_CASEBANK_DIR = E_DIR.parent / "G_casebank" / "accepted_public"
DEFAULT_RELEASE_GATE = E_DIR.parent / "F_independent_review" / "ROLE_COLLECTION_RELEASE_GATE.json"
RELEASE_GATE_VERSION = "eb.F_role_collection_release.v1"
SCORE_FIELDS = ("score", "comfort_score", "energy_score", "vpp_score")


def _csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


class RoleStudy:
    def __init__(self, data_root, *, casebank_dir=None, release_gate_path=None, public_dir=None,
                 expected_roles=300, human_mode=False):
        self.root = Path(data_root).resolve() / "role_ten_day"
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "feedback.sqlite3"
        self.lock = threading.RLock()
        self.human_mode = bool(human_mode)
        self.release_gate_path = Path(release_gate_path) if release_gate_path else DEFAULT_RELEASE_GATE
        self.expected_roles = expected_roles
        self.public_dir = Path(public_dir) if public_dir else PUBLIC_DIR
        self.public_manifest = self._verify_public_package()
        self.public_manifest_sha256 = hashlib.sha256((self.public_dir / "PUBLIC_MANIFEST.json").read_bytes()).hexdigest()
        self.profiles = {r["role_id"]: r for r in _csv(self.public_dir / "households_300.csv")}
        self.members = {}
        self.windows = {}
        self.devices = {}
        self.questions = {}
        for name, target in (("members_300.csv", self.members), ("member_windows_300.csv", self.windows),
                             ("devices_300.csv", self.devices), ("question_answers_300.csv", self.questions)):
            for row in _csv(self.public_dir / name):
                target.setdefault(row["role_id"], []).append(row)
        self.seed = self._seed()
        self._init_db()
        self.casebank = None
        self.contrasts = None
        self.display = None
        self.display_hash = None
        self.casebank_hash = None
        self.cases = {}
        self.not_ready_reason = "十天案例仍在独立核对，当前只可预览固定角色。"
        self.load_error = None
        self._load_casebank(Path(casebank_dir) if casebank_dir else DEFAULT_CASEBANK_DIR)

    def _verify_public_package(self):
        manifest = json.loads((self.public_dir / "PUBLIC_MANIFEST.json").read_text(encoding="utf-8"))
        if (manifest.get("schema_version") != "eb.public_synthetic_fixed_roles.v1" or
                manifest.get("status") != "PUBLIC_CANDIDATE_FIXED_ROLES_ONLY_NOT_COLLECTION_READY"):
            raise ValueError("public fixed-role package status invalid")
        required_tables = {"households_300.csv", "members_300.csv", "member_links_300.csv",
                           "member_windows_300.csv", "devices_300.csv", "question_answers_300.csv",
                           "provenance_300.csv"}
        if set(manifest.get("tables", {})) != required_tables:
            raise ValueError("public package must bind all seven fixed-role CSV files")
        for name, info in manifest["tables"].items():
            if not re.fullmatch(r"[a-z_0-9]+\.csv", name):
                raise ValueError("public package table name invalid")
            actual = hashlib.sha256((self.public_dir / name).read_bytes()).hexdigest()
            if actual != info["sha256"]:
                raise ValueError(f"public role CSV content mismatch: {name}")
        if len(_csv(self.public_dir / "households_300.csv")) != 300:
            raise ValueError("public role package must retain all 300 profiles")
        return manifest

    def _seed(self):
        path = self.root / "blind_seed.bin"
        if not path.exists():
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(secrets.token_bytes(32))
        seed = path.read_bytes()
        if len(seed) < 16:
            raise ValueError("private blind seed is invalid")
        return seed

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        with closing(self._connect()) as conn, conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS actors (
              actor_id TEXT PRIMARY KEY, session_hash TEXT UNIQUE NOT NULL,
              role_id TEXT UNIQUE NOT NULL, study_batch_id TEXT NOT NULL,
              consent_version TEXT NOT NULL, consent_at TEXT NOT NULL,
              consent_active INTEGER NOT NULL CHECK(consent_active IN (0,1)));
            CREATE TABLE IF NOT EXISTS feedback (
              event_id TEXT PRIMARY KEY, actor_id TEXT NOT NULL REFERENCES actors(actor_id),
              case_id TEXT NOT NULL, revision INTEGER NOT NULL,
              idempotency_key TEXT NOT NULL, payload_hash TEXT NOT NULL,
              payload_json TEXT NOT NULL, verified_json TEXT NOT NULL,
              trusted_origin TEXT NOT NULL, status TEXT NOT NULL,
              created_at TEXT NOT NULL, UNIQUE(actor_id,idempotency_key),
              UNIQUE(actor_id,case_id,revision));
            CREATE TABLE IF NOT EXISTS withdrawals (
              actor_id TEXT NOT NULL REFERENCES actors(actor_id),
              withdrawal_key TEXT NOT NULL, target_event_id TEXT NOT NULL,
              receipt TEXT NOT NULL, PRIMARY KEY(actor_id,withdrawal_key));
            CREATE TABLE IF NOT EXISTS day_progress (
              actor_id TEXT NOT NULL REFERENCES actors(actor_id), case_id TEXT NOT NULL,
              day_index INTEGER NOT NULL, status TEXT NOT NULL,
              first_viewed_at TEXT NOT NULL, last_viewed_at TEXT NOT NULL,
              completed_at TEXT, PRIMARY KEY(actor_id,case_id), UNIQUE(actor_id,day_index));
            CREATE TABLE IF NOT EXISTS day_actions (
              actor_id TEXT NOT NULL REFERENCES actors(actor_id), idempotency_key TEXT NOT NULL,
              case_id TEXT NOT NULL, action TEXT NOT NULL, receipt TEXT NOT NULL, reason TEXT,
              PRIMARY KEY(actor_id,idempotency_key));
            CREATE TABLE IF NOT EXISTS action_log (
              sequence INTEGER PRIMARY KEY AUTOINCREMENT, actor_id TEXT NOT NULL REFERENCES actors(actor_id),
              case_id TEXT, day_index INTEGER NOT NULL, action TEXT NOT NULL,
              event_id TEXT, happened_at TEXT NOT NULL);
            """)
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(feedback)")}
            for name, definition in {
                "study_batch_id": "TEXT", "casebank_sha256": "TEXT", "profile_sha256": "TEXT",
                "meter_version_sha256": "TEXT", "public_role_manifest_sha256": "TEXT",
                "presented_at": "TEXT", "future_exposure": "INTEGER", "max_viewed_day": "INTEGER",
            }.items():
                if name not in columns:
                    conn.execute(f"ALTER TABLE feedback ADD COLUMN {name} {definition}")
            actor_columns = {row["name"] for row in conn.execute("PRAGMA table_info(actors)")}
            if "casebank_sha256" not in actor_columns:
                conn.execute("ALTER TABLE actors ADD COLUMN casebank_sha256 TEXT")
            action_columns = {row["name"] for row in conn.execute("PRAGMA table_info(day_actions)")}
            if "reason" not in action_columns:
                conn.execute("ALTER TABLE day_actions ADD COLUMN reason TEXT")

    def _log(self, conn, actor_id, case_id, day_index, action, event_id=None):
        conn.execute("INSERT INTO action_log(actor_id,case_id,day_index,action,event_id,happened_at) VALUES (?,?,?,?,?,?)",
                     (actor_id, case_id, day_index, action, event_id, _utc_now()))

    def _load_casebank(self, directory):
        try:
            bank = json.loads((directory / "casebank.json").read_text(encoding="utf-8"))
            contrasts = json.loads((directory / "accepted_contrasts.json").read_text(encoding="utf-8"))
            display = json.loads((directory / "display_payloads.json").read_text(encoding="utf-8"))
            display_text = json.dumps(display, ensure_ascii=False)
            if any(marker in display_text for marker in ("/Users/", "\\Users\\", "runtime_inputs/", "eplusout.", "process.log")):
                raise ValueError("private model path or runtime marker in public display")
            validate_casebank(bank, accepted_contrast_index=contrasts,
                              expected_roles=self.expected_roles)
            for key in ("meter_version_sha256", "public_role_manifest_sha256"):
                if not isinstance(bank.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", bank[key]):
                    raise ValueError(f"{key} missing from accepted casebank")
            if (bank["profile_sha256"] != self.public_manifest["source_input_sha256"]["B_profile"] or
                    bank["public_role_manifest_sha256"] != self.public_manifest_sha256):
                raise ValueError("casebank fixed-role source differs from verified public CSV package")
            if not isinstance(bank.get("consent_text"), str) or len(bank["consent_text"].strip()) < 30:
                raise ValueError("approved study consent text is missing")
            indexed = case_index(bank)
            if set(display) != set(indexed):
                raise ValueError("display payload coverage differs from accepted cases")
            for cid, (role_id, day) in indexed.items():
                item = display[cid]
                if not isinstance(item, dict) or set(item) != {"context", "weather", "plans"}:
                    raise ValueError(f"{cid}: display context, weather and plans required")
                if not isinstance(item["context"], str) or not isinstance(item["weather"], dict):
                    raise ValueError(f"{cid}: display context or weather malformed")
                weather = item["weather"]
                if (not isinstance(weather.get("summary"), str) or not weather["summary"].strip() or
                        weather.get("station_key") != self.profiles[role_id]["weather_station_key"] or
                        weather.get("simulated_day_index") != day["day_index"]):
                    raise ValueError(f"{cid}: simulated weather label or station mismatch")
                if not isinstance(item["plans"], dict) or set(item["plans"]) != {"A", "B"}:
                    raise ValueError(f"{cid}: display A/B pair malformed")
                for slot in ("A", "B"):
                    shown = item["plans"][slot]
                    if not isinstance(shown, dict) or set(shown) != {"branch_history_summary", "device_schedule", "indoor_temperature_c",
                                                                   "controlled_device_kwh", "task_completion",
                                                                   "metrics"}:
                        raise ValueError(f"{cid}.{slot}: required daily display fields missing")
                    if (not isinstance(shown["branch_history_summary"], str) or
                            not isinstance(shown["device_schedule"], list) or
                            any(not isinstance(line, str) for line in shown["device_schedule"]) or
                            not isinstance(shown["metrics"], dict)):
                        raise ValueError(f"{cid}.{slot}: schedule or metrics malformed")
                    if (type(shown["controlled_device_kwh"]) not in (int, float) or
                            not math.isfinite(shown["controlled_device_kwh"]) or
                            shown["controlled_device_kwh"] < 0 or
                            not isinstance(shown["task_completion"], str)):
                        raise ValueError(f"{cid}.{slot}: controlled electricity or task label malformed")
                    visible_text = shown["branch_history_summary"] + " ".join(shown["device_schedule"])
                    if re.search(r"(?:方案|轨迹|候选)\s*[AB](?![A-Za-z])", visible_text):
                        raise ValueError(f"{cid}.{slot}: internal A/B label leaked into blinded display")
                    if stable_hash(shown) != day["plans"][slot]["display_payload_hash"] or stable_hash(shown["metrics"]) != day["plans"][slot]["metrics_hash"]:
                        raise ValueError(f"{cid}.{slot}: display hash mismatch")
            self.casebank, self.contrasts, self.display = bank, contrasts, display
            self.display_hash = stable_hash(display)
            self.casebank_hash, self.cases = stable_hash(bank), indexed
            self.not_ready_reason = None
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            self.load_error = str(exc)
            self.not_ready_reason = "十天案例仍在独立核对，当前只可预览固定角色。"

    @property
    def ready(self):
        return self.casebank is not None and self._release_gate_valid()

    def _release_gate_valid(self):
        """Read on every access so F can revoke an earlier approval immediately."""
        try:
            gate = json.loads(self.release_gate_path.read_text(encoding="utf-8"))
            mode_allowed = ((not self.human_mode and
                             ((gate.get("status") == "ROLE_TECHNICAL_PREVIEW_APPROVED" and
                               gate.get("human_collection_approved") is False and
                               gate.get("engineering_only") is True) or
                              (gate.get("status") == "ROLE_COLLECTION_APPROVED" and
                               gate.get("human_collection_approved") is True))) or
                            (self.human_mode and gate.get("status") == "ROLE_COLLECTION_APPROVED" and
                             gate.get("human_collection_approved") is True and
                             gate.get("engineering_only") is False and
                             not self.casebank["study_batch_id"].startswith("eb.engineering.") and
                             not self.casebank["consent_version"].startswith("eb.engineering.")))
            return (gate.get("schema_version") == RELEASE_GATE_VERSION and
                    mode_allowed and
                    gate.get("revoked") is False and
                    gate.get("casebank_sha256") == self.casebank_hash and
                    gate.get("contrast_sha256") == stable_hash(self.contrasts) and
                    gate.get("display_sha256") == self.display_hash and
                    gate.get("public_role_manifest_sha256") == self.public_manifest_sha256 and
                    gate.get("profile_sha256") == self.casebank["profile_sha256"] and
                    gate.get("final_evidence_sha256") == self.casebank["final_evidence_sha256"] and
                    gate.get("meter_version_sha256") == self.casebank["meter_version_sha256"] and
                    isinstance(gate.get("accepted_at"), str) and bool(gate["accepted_at"]))
        except (OSError, ValueError, TypeError):
            return False

    def _require_ready(self):
        if not self.ready:
            raise RuntimeError(self.not_ready_reason or "F 当前有效的角色采集放行记录缺失或已撤回。")

    def profile(self, role_id):
        if role_id not in self.profiles:
            raise KeyError("角色不存在")
        row = self.profiles[role_id]
        keys = ("role_id", "city", "province", "family_size", "housing_form", "housing_mode", "building_type",
                "h6_design_building_area_m2", "h6_area_basis", "whole_dwelling_building_area_m2",
                "whole_dwelling_area_status", "household_accounted_net_area_m2",
                "selected_controlled_zone_area_m2", "common_allocated_area_m2", "private_control_scope",
                "source_catalog_key", "weather_station_key", "weather_station_distance_km",
                "monthly_income_scenario_yuan", "monthly_bill_scenario_yuan",
                "bill_pressure_description", "budget_explanation", "tradeoff_condition",
                "cost_importance_1_5", "comfort_importance_1_5",
                "grid_importance_1_5", "control_condition", "role_card_short", "actor_card_full")
        facts = {}
        for answer in self.questions.get(role_id, []):
            qid = answer["question_id"]
            fact = facts.setdefault(qid, {"question_id": qid, "question_group": answer["question_group"],
                                          "question_prompt": answer["question_prompt"], "labels": [],
                                          "response_status": answer["response_status"]})
            if answer["response_status"] == "answered" and answer["display_label"]:
                fact["labels"].append(answer["display_label"])
        for fact in facts.values():
            if fact["response_status"] == "not_applicable":
                fact["display"] = "不适用"
            elif fact["response_status"] != "answered":
                fact["display"] = "未知或未填写"
            else:
                fact["display"] = "、".join(fact["labels"]) or "见成员生活表"
        household = {key: row.get(key, "") for key in keys}
        card = household["actor_card_full"]
        card = re.sub(r"(?<![A-Za-z0-9_])m(\d{2})(?![A-Za-z0-9_])",
                      lambda match: f"第{int(match[1])}位成员", card)
        card = re.sub(r"\bH7\s*", "", card)
        card = card.replace("源户位 edge", "源模型户位 边户").replace("源户位 middle", "源模型户位 中间户")
        household["actor_card_full"] = card
        devices = []
        for original in self.devices.get(role_id, []):
            device = dict(original)
            condition = device.get("operation_condition", "")
            device["operation_condition"] = re.sub(
                r"(?<![A-Za-z0-9_])m(\d{2})(?![A-Za-z0-9_])",
                lambda match: f"第{int(match[1])}位成员", condition)
            devices.append(device)
        return {"household": household,
                "members": self.members.get(role_id, []), "member_windows": self.windows.get(role_id, []),
                "devices": devices, "question_facts": list(facts.values()),
                "first_day_weather": (self.display[f"{role_id}/day-01"]["weather"]["summary"]
                                      if self.ready and not self.human_mode and
                                      f"{role_id}/day-01" in self.display else None)}

    def _actor(self, conn, session):
        return conn.execute("SELECT * FROM actors WHERE session_hash=?", (hashlib.sha256(session.encode()).hexdigest(),)).fetchone()

    def session(self, session):
        with self.lock, closing(self._connect()) as conn, conn:
            actor = self._actor(conn, session)
            ready = self.ready
            current_enrollment = bool(actor and ready and actor["consent_active"] and
                                      actor["study_batch_id"] == self.casebank["study_batch_id"] and
                                      actor["consent_version"] == self.casebank["consent_version"] and
                                      actor["casebank_sha256"] == self.casebank_hash)
            withdrawable = []
            if actor:
                for event in conn.execute("SELECT event_id,payload_json FROM feedback WHERE actor_id=? AND status='submitted'",
                                          (actor["actor_id"],)):
                    saved = json.loads(event["payload_json"])
                    withdrawable.append({"event_id": event["event_id"], "day_index": saved["day_index"]})
            return {"ready": ready, "reason": self.not_ready_reason if self.casebank is None else
                    ("该会话属于旧案例或同意版本，仅可撤回已有记录。" if ready and actor and not current_enrollment else
                     None if ready else "F 当前有效的角色采集放行记录缺失或已撤回。"),
                    "preview_role_id": "cityrole-0001", "actor_id": actor["actor_id"] if actor else None,
                    "collection_mode": "human" if self.human_mode else "engineering_preview",
                    "role_id": actor["role_id"] if actor else None,
                    "consent_active": bool(actor["consent_active"]) if actor else False,
                    "current_enrollment": current_enrollment,
                    "consent_version": self.casebank["consent_version"] if ready else None,
                    "consent_text": self.casebank["consent_text"] if ready and not actor else None,
                    "withdrawable_events": withdrawable,
                    "days": self._progress(conn, actor) if current_enrollment else []}

    def _progress(self, conn, actor):
        days = next(r["days"] for r in self.casebank["records"] if r["role_id"] == actor["role_id"])
        result = []
        unlocked = True
        for day in days:
            progress = conn.execute("SELECT status FROM day_progress WHERE actor_id=? AND day_index=?",
                                    (actor["actor_id"], day["day_index"])).fetchone()
            latest = conn.execute("SELECT status,revision FROM feedback WHERE actor_id=? AND case_id=? ORDER BY revision DESC LIMIT 1",
                                  (actor["actor_id"], day["case_id"])).fetchone()
            result.append({"day_index": day["day_index"], "collectable": day["collectable"],
                           "unlocked": unlocked,
                           "status": (latest["status"] if latest and latest["status"] == "submitted" else
                                      progress["status"] if progress else "not_started")})
            unlocked = unlocked and bool(progress and progress["status"] in {"acknowledged", "skipped", "answered"})
        return result

    def consent(self, session, payload):
        self._require_ready()
        allowed = {"accept", "consent_version"} if self.human_mode else {"accept", "consent_version", "requested_role_id"}
        if (not {"accept", "consent_version"} <= set(payload) or set(payload) - allowed or
                payload["accept"] is not True or payload["consent_version"] != self.casebank["consent_version"]):
            raise ValueError("须阅读并同意当前版本说明")
        requested = payload.get("requested_role_id")
        if requested is not None and requested not in {r["role_id"] for r in self.casebank["records"]}:
            raise ValueError("工程预览角色不存在")
        with self.lock, closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            actor = self._actor(conn, session)
            if actor:
                if (not actor["consent_active"] or actor["study_batch_id"] != self.casebank["study_batch_id"] or
                        actor["consent_version"] != self.casebank["consent_version"] or
                        actor["casebank_sha256"] != self.casebank_hash):
                    raise ValueError("当前会话已撤回或批次不符")
                return {"role_id": actor["role_id"], "actor_id": actor["actor_id"], "resumed": True}
            used = {r["role_id"] for r in conn.execute("SELECT role_id FROM actors")}
            role = requested if requested and requested not in used else (
                None if requested else next((r["role_id"] for r in self.casebank["records"]
                                             if r["role_id"] not in used), None))
            if role is None:
                raise ValueError("本批角色名额已满")
            actor_id = secrets.token_hex(16)
            conn.execute("INSERT INTO actors(actor_id,session_hash,role_id,study_batch_id,consent_version,consent_at,consent_active,casebank_sha256) VALUES (?,?,?,?,?,?,1,?)",
                         (actor_id, hashlib.sha256(session.encode()).hexdigest(), role,
                          self.casebank["study_batch_id"], self.casebank["consent_version"], _utc_now(),
                          self.casebank_hash))
            self._log(conn, actor_id, None, 0, "consent")
            return {"role_id": role, "actor_id": actor_id, "resumed": False}

    def day(self, session, index):
        self._require_ready()
        with self.lock, closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            actor = self._actor(conn, session)
            if (not actor or not actor["consent_active"] or
                    actor["study_batch_id"] != self.casebank["study_batch_id"] or
                    actor["consent_version"] != self.casebank["consent_version"] or
                    actor["casebank_sha256"] != self.casebank_hash):
                raise KeyError("请先完成本批同意")
            if not 1 <= index <= 10:
                raise KeyError("日期不存在")
            if not self._progress(conn, actor)[index - 1]["unlocked"]:
                raise ValueError("请先完成前一天的查看与回答或跳过")
            day = next(r["days"][index - 1] for r in self.casebank["records"] if r["role_id"] == actor["role_id"])
            now = _utc_now()
            conn.execute("INSERT INTO day_progress(actor_id,case_id,day_index,status,first_viewed_at,last_viewed_at) VALUES (?,?,?,?,?,?) "
                         "ON CONFLICT(actor_id,case_id) DO UPDATE SET last_viewed_at=excluded.last_viewed_at",
                         (actor["actor_id"], day["case_id"], index, "viewed", now, now))
            self._log(conn, actor["actor_id"], day["case_id"], index, "view")
            display = self.display[day["case_id"]]
            order = blind_order(self.seed, self.casebank_hash, actor["actor_id"], actor["role_id"], index)
            prior = conn.execute("SELECT event_id,payload_json,status,revision FROM feedback WHERE actor_id=? AND case_id=? ORDER BY revision DESC LIMIT 1",
                                 (actor["actor_id"], day["case_id"])).fetchone()
            answer = json.loads(prior["payload_json"]) if prior and prior["status"] == "submitted" else None
            progress = conn.execute("SELECT status FROM day_progress WHERE actor_id=? AND case_id=?",
                                    (actor["actor_id"], day["case_id"])).fetchone()
            return {"role_id": actor["role_id"], "day_index": index, "case_id": day["case_id"],
                    "casebank_sha256": self.casebank_hash, "profile_sha256": self.casebank["profile_sha256"],
                    "display_order_hash": order["display_order_hash"],
                    "context": display["context"], "weather": display["weather"],
                    "plans": {side: display["plans"][order[f"{side}_slot"]] for side in ("left", "right")},
                    "collectable": day["collectable"],
                    "noncollectable_reason": day["semantic_contrast"].get("reason") if not day["collectable"] else None,
                    "prior_answer": answer, "prior_event_id": prior["event_id"] if answer else None,
                    "response_status": prior["status"] if prior and prior["status"] == "submitted" else progress["status"]}

    def day_action(self, session, payload):
        self._require_ready()
        if (set(payload) - {"day_index", "action", "idempotency_key", "skip_reason"} or
                not {"day_index", "action", "idempotency_key"} <= set(payload) or
                payload["action"] not in {"acknowledge", "skip"} or
                type(payload["day_index"]) is not int or not 1 <= payload["day_index"] <= 10 or
                not isinstance(payload["idempotency_key"], str) or len(payload["idempotency_key"]) < 12):
            raise ValueError("逐日确认字段无效")
        if payload["action"] == "skip" and (not isinstance(payload.get("skip_reason"), str) or
                                               not payload["skip_reason"].strip() or len(payload["skip_reason"]) > 500):
            raise ValueError("跳过须说明简短原因")
        with self.lock, closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            actor = self._actor(conn, session)
            if (not actor or not actor["consent_active"] or actor["study_batch_id"] != self.casebank["study_batch_id"] or
                    actor["casebank_sha256"] != self.casebank_hash):
                raise KeyError("请先完成本批同意")
            day = next(r["days"][payload["day_index"] - 1] for r in self.casebank["records"] if r["role_id"] == actor["role_id"])
            if day["collectable"] is (payload["action"] == "acknowledge"):
                raise ValueError("无对照日须确认阅读；可评价日可明确跳过")
            receipt = stable_hash({"actor": actor["actor_id"], "case_id": day["case_id"],
                                   "action": payload["action"], "key": payload["idempotency_key"],
                                   "skip_reason": payload.get("skip_reason")})
            prior_key = conn.execute("SELECT * FROM day_actions WHERE actor_id=? AND idempotency_key=?",
                                     (actor["actor_id"], payload["idempotency_key"])).fetchone()
            if prior_key:
                if prior_key["receipt"] != receipt:
                    raise ValueError("同一逐日操作键内容已改变")
                return {"receipt": prior_key["receipt"], "duplicate": True}
            progress = conn.execute("SELECT * FROM day_progress WHERE actor_id=? AND case_id=?",
                                    (actor["actor_id"], day["case_id"])).fetchone()
            if not progress or progress["status"] != "viewed":
                raise ValueError("须先在服务端展示当天内容，且当天尚未完成")
            action = payload["action"]
            new_status = "acknowledged" if action == "acknowledge" else "skipped"
            now = _utc_now()
            conn.execute("UPDATE day_progress SET status=?,completed_at=? WHERE actor_id=? AND case_id=?",
                         (new_status, now, actor["actor_id"], day["case_id"]))
            conn.execute("INSERT INTO day_actions(actor_id,idempotency_key,case_id,action,receipt,reason) VALUES (?,?,?,?,?,?)",
                         (actor["actor_id"], payload["idempotency_key"], day["case_id"], action, receipt,
                          payload.get("skip_reason") if action == "skip" else None))
            self._log(conn, actor["actor_id"], day["case_id"], day["day_index"], action)
            return {"receipt": receipt, "duplicate": False, "status": new_status,
                    "next_day_index": day["day_index"] + 1 if day["day_index"] < 10 else None}

    def feedback(self, session, payload):
        self._require_ready()
        origin = "human_participant" if self.human_mode else "synthetic_engineering_test"
        with self.lock, closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            actor = self._actor(conn, session)
            if (not actor or not actor["consent_active"] or actor["study_batch_id"] != self.casebank["study_batch_id"] or
                    actor["consent_version"] != self.casebank["consent_version"] or
                    actor["casebank_sha256"] != self.casebank_hash):
                raise KeyError("请先完成本批同意")
            registry = ActorRegistry()
            registry.assign(actor["actor_id"], actor["role_id"])
            registry.record_consent(actor["actor_id"], version=actor["consent_version"],
                                    recorded_at=actor["consent_at"], study_batch_id=actor["study_batch_id"])
            checked = validate_submission(payload, self.casebank, registry, self.seed,
                                          self.casebank_hash, trusted_origin=origin,
                                          accepted_contrast_index=self.contrasts)
            self._require_ready()
            if payload["actor_pseudonym"] != actor["actor_id"]:
                raise ValueError("参与者不匹配")
            payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
            payload_hash = stable_hash({"payload": payload, "trusted_origin": origin})
            old_key = conn.execute("SELECT * FROM feedback WHERE actor_id=? AND idempotency_key=?",
                                   (actor["actor_id"], payload["idempotency_key"])).fetchone()
            if old_key:
                if old_key["payload_hash"] != payload_hash:
                    raise ValueError("同一提交键的内容已改变")
                return {"event_id": old_key["event_id"], "revision": old_key["revision"],
                        "duplicate": True, "future_exposure": bool(old_key["future_exposure"])}
            progress = conn.execute("SELECT * FROM day_progress WHERE actor_id=? AND case_id=?",
                                    (actor["actor_id"], payload["case_id"])).fetchone()
            if not progress or progress["status"] not in {"viewed", "skipped", "answered"}:
                raise ValueError("须先由服务端展示当天案例，且按序开放")
            max_viewed = conn.execute("SELECT MAX(day_index) FROM action_log WHERE actor_id=? AND action='view'",
                                      (actor["actor_id"],)).fetchone()[0]
            future_exposure = bool(max_viewed is not None and max_viewed > payload["day_index"])
            prior = conn.execute("SELECT * FROM feedback WHERE actor_id=? AND case_id=? ORDER BY revision DESC LIMIT 1",
                                 (actor["actor_id"], payload["case_id"])).fetchone()
            revision = prior["revision"] + 1 if prior else 1
            event_id = stable_hash({"actor": actor["actor_id"], "case_id": payload["case_id"],
                                    "revision": revision, "payload_hash": payload_hash})
            if prior and prior["status"] == "submitted":
                conn.execute("UPDATE feedback SET status='superseded' WHERE event_id=?", (prior["event_id"],))
            conn.execute("INSERT INTO feedback(event_id,actor_id,case_id,revision,idempotency_key,payload_hash,payload_json,verified_json,trusted_origin,status,created_at,study_batch_id,casebank_sha256,profile_sha256,meter_version_sha256,public_role_manifest_sha256,presented_at,future_exposure,max_viewed_day) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (event_id, actor["actor_id"], payload["case_id"], revision,
                          payload["idempotency_key"], payload_hash, payload_json,
                          json.dumps(checked, ensure_ascii=False, sort_keys=True), origin,
                          "submitted", _utc_now(), self.casebank["study_batch_id"], self.casebank_hash,
                          self.casebank["profile_sha256"], self.casebank["meter_version_sha256"],
                          self.public_manifest_sha256, progress["first_viewed_at"],
                          int(future_exposure), max_viewed))
            conn.execute("UPDATE day_progress SET status='answered',completed_at=? WHERE actor_id=? AND case_id=?",
                         (_utc_now(), actor["actor_id"], payload["case_id"]))
            self._log(conn, actor["actor_id"], payload["case_id"], payload["day_index"],
                      "revise" if prior else "submit", event_id)
            return {"event_id": event_id, "revision": revision, "duplicate": False,
                    "future_exposure": future_exposure}

    def withdraw_day(self, session, payload):
        if set(payload) != {"target_event_id", "withdrawal_key"} or not isinstance(payload["withdrawal_key"], str) or len(payload["withdrawal_key"]) < 12:
            raise ValueError("撤回请求字段无效")
        with self.lock, closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            actor = self._actor(conn, session)
            if not actor:
                raise KeyError("找不到角色会话")
            old = conn.execute("SELECT * FROM withdrawals WHERE actor_id=? AND withdrawal_key=?",
                               (actor["actor_id"], payload["withdrawal_key"])).fetchone()
            if old:
                if old["target_event_id"] != payload["target_event_id"]:
                    raise ValueError("同一撤回键目标已改变")
                return {"receipt": old["receipt"], "duplicate": True}
            target = conn.execute("SELECT * FROM feedback WHERE event_id=? AND actor_id=?",
                                  (payload["target_event_id"], actor["actor_id"])).fetchone()
            if not target:
                raise KeyError("找不到本人的回答")
            latest = conn.execute("SELECT event_id FROM feedback WHERE actor_id=? AND case_id=? ORDER BY revision DESC LIMIT 1",
                                  (actor["actor_id"], target["case_id"])).fetchone()
            if latest["event_id"] != target["event_id"]:
                raise ValueError("只能撤回当前版本")
            conn.execute("UPDATE feedback SET status='withdrawn' WHERE event_id=?", (target["event_id"],))
            receipt = stable_hash({"actor": actor["actor_id"], "event": target["event_id"],
                                   "key": payload["withdrawal_key"]})
            conn.execute("INSERT INTO withdrawals VALUES (?,?,?,?)",
                         (actor["actor_id"], payload["withdrawal_key"], target["event_id"], receipt))
            self._log(conn, actor["actor_id"], target["case_id"],
                      json.loads(target["payload_json"])["day_index"], "withdraw_day", target["event_id"])
            return {"receipt": receipt, "duplicate": False}

    def withdraw_actor(self, session):
        with self.lock, closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            actor = self._actor(conn, session)
            if not actor:
                raise KeyError("找不到角色会话")
            if not actor["consent_active"]:
                return {"withdrawn": True, "duplicate": True}
            conn.execute("UPDATE actors SET consent_active=0 WHERE actor_id=?", (actor["actor_id"],))
            conn.execute("UPDATE feedback SET status='withdrawn' WHERE actor_id=?", (actor["actor_id"],))
            self._log(conn, actor["actor_id"], None, 0, "withdraw_actor")
            return {"withdrawn": True, "duplicate": False}

    def export_rows(self, *, training_only=True):
        if training_only:
            self._require_ready()
        with self.lock, closing(self._connect()) as conn, conn:
            rows = conn.execute("SELECT f.*,a.role_id,a.consent_active,a.consent_version,"
                                "a.study_batch_id AS actor_study_batch_id,a.casebank_sha256 AS actor_casebank_sha256 "
                                "FROM feedback f JOIN actors a ON a.actor_id=f.actor_id ORDER BY f.created_at,f.event_id").fetchall()
            result = []
            for row in rows:
                verified = json.loads(row["verified_json"])
                consent = verified["consent_snapshot"]
                if training_only and (row["trusted_origin"] != "human_participant" or row["status"] != "submitted" or
                                      not row["consent_active"] or not consent or bool(row["future_exposure"]) or
                                      row["study_batch_id"] != self.casebank["study_batch_id"] or
                                      row["actor_study_batch_id"] != self.casebank["study_batch_id"] or
                                      row["casebank_sha256"] != self.casebank_hash or
                                      row["actor_casebank_sha256"] != self.casebank_hash or
                                      row["profile_sha256"] != self.casebank["profile_sha256"] or
                                      row["meter_version_sha256"] != self.casebank["meter_version_sha256"] or
                                      row["public_role_manifest_sha256"] != self.public_manifest_sha256 or
                                      not row["presented_at"] or
                                      consent["version"] != row["consent_version"] or
                                      consent["version"] != self.casebank["consent_version"] or
                                      consent["study_batch_id"] != self.casebank["study_batch_id"]):
                    continue
                result.append({"event_id": row["event_id"], "actor_pseudonym": row["actor_id"],
                               "role_id": row["role_id"], "case_id": row["case_id"],
                               "revision": row["revision"], "response_status": row["status"],
                               "data_origin": row["trusted_origin"], "payload": json.loads(row["payload_json"]),
                               "verified": verified, "study_batch_id": row["study_batch_id"],
                               "casebank_sha256": row["casebank_sha256"],
                               "profile_sha256": row["profile_sha256"],
                               "meter_version_sha256": row["meter_version_sha256"],
                               "public_role_manifest_sha256": row["public_role_manifest_sha256"],
                               "presented_at": row["presented_at"],
                               "future_exposure": bool(row["future_exposure"]),
                               "max_viewed_day": row["max_viewed_day"]})
            return result

    def export_action_log(self):
        with self.lock, closing(self._connect()) as conn, conn:
            return [dict(row) for row in conn.execute(
                "SELECT l.*,d.reason AS skip_reason FROM action_log l "
                "LEFT JOIN day_actions d ON d.actor_id=l.actor_id AND d.case_id=l.case_id "
                "AND d.action=l.action AND l.action='skip' ORDER BY l.sequence")]
