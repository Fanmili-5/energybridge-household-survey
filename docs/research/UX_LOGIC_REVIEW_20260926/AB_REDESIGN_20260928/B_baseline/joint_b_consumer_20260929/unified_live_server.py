"""Isolated server for the unified page's engineering trial.

This serves one already built synthetic role. It records engineering clicks and
issue reports; it does not implement invitation identity or human collection.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
from urllib.parse import urlsplit


ASSETS = {"style.css", "candidate.css", "joint-view.css", "plan-view.js",
          "source-draft.js", "household-view.js", "joint-view.js"}
ISSUE_CATEGORIES = {"household", "schedule", "missing_result", "display", "other"}
DECISIONS = {"accept", "reject"}
MAX_BODY = 2_000_000


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def field_json(page, element_id):
    match = re.search(r'<script[^>]+id="' + re.escape(element_id) + r'"[^>]*>(.*?)</script>', page, re.S)
    if not match:
        raise ValueError(f"Missing page field: {element_id}")
    return json.loads(match.group(1))


def validate_score(value):
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 1 <= value <= 5:
        raise ValueError("Score must be 1–5 or null")
    if abs(value * 10 - round(value * 10)) > 1e-8:
        raise ValueError("Score has more than one decimal place")


def validate_record(kind, record, index, cases, hashes):
    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(cases):
        raise ValueError("Invalid case index")
    if not isinstance(record, dict):
        raise ValueError("Invalid record")
    case, source_hash = cases[index], hashes[index]
    if kind == "answers":
        if record.get("schema") != "eb.joint_b.local_test_export.v5" or record.get("status") != "engineering_click_not_human_feedback":
            raise ValueError("Wrong answer version")
        if record.get("human_label_count") != 0 or record.get("training_release") is not False or record.get("formal_export_eligible") is not False:
            raise ValueError("Engineering status required")
        feedback = record.get("test_feedback")
        if not isinstance(feedback, dict) or feedback.get("decision") not in DECISIONS or feedback.get("decision_status") != "answered":
            raise ValueError("Choose accept or reject")
        if set(feedback) != {"decision", "decision_status", "score", "comfort_score", "energy_score", "vpp_score", "comment"}:
            raise ValueError("Feedback fields invalid")
        for name in ("score", "comfort_score", "energy_score", "vpp_score"):
            validate_score(feedback[name])
        comment = feedback["comment"]
        if not isinstance(comment, str) or not comment.strip() or len(comment) > 1000:
            raise ValueError("A short reason is required")
        audit = record.get("audit", {})
        if audit.get("source_case") != case or audit.get("source_binding", {}).get("source_package_sha256") != source_hash:
            raise ValueError("Source binding mismatch")
        if record.get("input", {}).get("date") != case["identity"]["date"]:
            raise ValueError("Displayed date mismatch")
    else:
        if record.get("schema") != "eb.joint_b.local_issue.v1" or record.get("status") != "engineering_issue_submission":
            raise ValueError("Wrong issue version")
        issue = record.get("issue")
        if not isinstance(issue, dict) or set(issue) != {"category", "description"} or issue["category"] not in ISSUE_CATEGORIES:
            raise ValueError("Issue category invalid")
        if not isinstance(issue["description"], str) or not issue["description"].strip() or len(issue["description"]) > 2000:
            raise ValueError("Issue description required")
        context = record.get("context", {})
        if context.get("household_id") != case["identity"]["role_id"] or context.get("case_id") != case["identity"]["case_id"] or context.get("source_package_sha256") != source_hash:
            raise ValueError("Issue source binding mismatch")


class App:
    def __init__(self, site_dir, data_dir, prefix, public_origin):
        self.site_dir = Path(site_dir).resolve()
        self.page = (self.site_dir / "index.html").read_text()
        self.cases = field_json(self.page, "joint-cases-data")
        self.hashes = field_json(self.page, "source-hashes-data")
        if not self.cases or len(self.cases) != len(self.hashes):
            raise ValueError("Case/hash binding missing")
        if not re.fullmatch(r"/[a-z][a-z0-9-]{2,63}", prefix):
            raise ValueError("Invalid route prefix")
        if not public_origin.startswith("https://") or "/" in public_origin[8:]:
            raise ValueError("A precise HTTPS public origin is required")
        self.prefix, self.public_origin = prefix, public_origin
        self.data_dir = Path(data_dir).resolve()
        self.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.db_path = self.data_dir / "engineering.sqlite3"
        self.lock = threading.Lock()
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions(session_id TEXT PRIMARY KEY, csrf TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS writes(request_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, kind TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL, receipt_id TEXT NOT NULL, case_id TEXT NOT NULL,
                    record_json TEXT NOT NULL, created_at TEXT NOT NULL);
            """)

    def connect(self):
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def session(self, cookie_header, create=False):
        cookie = SimpleCookie()
        try:
            cookie.load(cookie_header or "")
            sid = cookie.get("eb_joint_engineering")
            sid = sid.value if sid else None
        except Exception:
            sid = None
        with self.connect() as db:
            row = db.execute("SELECT session_id,csrf FROM sessions WHERE session_id=?", (sid,)).fetchone() if sid else None
            if row or not create:
                return row
            sid, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            db.execute("INSERT INTO sessions VALUES (?,?,?)", (sid, csrf, datetime.now(timezone.utc).isoformat()))
            return {"session_id": sid, "csrf": csrf}

    def save(self, kind, payload, sid):
        if not isinstance(payload, dict) or set(payload) != {"case_index", "record", "request_id"}:
            raise ValueError("Request fields invalid")
        request_id = payload["request_id"]
        if not isinstance(request_id, str) or not re.fullmatch(r"[a-f0-9-]{36}", request_id):
            raise ValueError("Request ID invalid")
        index, record = payload["case_index"], payload["record"]
        validate_record(kind, record, index, self.cases, self.hashes)
        body_hash = hashlib.sha256(encoded(payload)).hexdigest()
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT session_id,kind,payload_sha256,receipt_id FROM writes WHERE request_id=?", (request_id,)).fetchone()
            if old:
                if (old["session_id"], old["kind"], old["payload_sha256"]) != (sid, kind, body_hash):
                    raise ValueError("Request ID reused with different content")
                return {"saved": True, "duplicate": True, "receipt_id": old["receipt_id"]}
            receipt = ("ANS-" if kind == "answers" else "ISS-") + secrets.token_hex(8).upper()
            db.execute("INSERT INTO writes VALUES (?,?,?,?,?,?,?,?)", (request_id, sid, kind, body_hash, receipt,
                       self.cases[index]["identity"]["case_id"], encoded(record).decode(), datetime.now(timezone.utc).isoformat()))
            return {"saved": True, "duplicate": False, "receipt_id": receipt}


class Handler(BaseHTTPRequestHandler):
    server: "Server"

    def reply(self, status, data, *, mime="application/json; charset=utf-8", cookie=None):
        raw = encoded(data) if mime.startswith("application/json") else data
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(raw)

    def route(self):
        path = urlsplit(self.path).path
        prefix = self.server.app.prefix
        if path == prefix:
            return "/"
        if path.startswith(prefix + "/"):
            return path[len(prefix):]
        return None

    def do_GET(self):
        app, route = self.server.app, self.route()
        if route is None:
            return self.reply(HTTPStatus.NOT_FOUND, {"error": "Not found"})
        if route == "/api/health":
            return self.reply(HTTPStatus.OK, {"mode": "engineering_only", "cases": len(app.cases)})
        if route in {"/", "/index.html"}:
            session = app.session(self.headers.get("Cookie"), create=True)
            config = json.dumps({"base": app.prefix, "csrf": session["csrf"]}, separators=(",", ":"))
            html = app.page.replace("</head>", "<script>window.EBLiveConfig=" + config + "</script></head>", 1)
            cookie = f"eb_joint_engineering={session['session_id']}; Path={app.prefix}; HttpOnly; Secure; SameSite=Lax"
            return self.reply(HTTPStatus.OK, html.encode(), mime="text/html; charset=utf-8", cookie=cookie)
        name = route.lstrip("/")
        if "/" not in name and name in ASSETS:
            return self.reply(HTTPStatus.OK, (app.site_dir / name).read_bytes(),
                              mime=mimetypes.guess_type(name)[0] or "application/octet-stream")
        return self.reply(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def do_POST(self):
        app, route = self.server.app, self.route()
        if route not in {"/api/answers", "/api/issues"}:
            return self.reply(HTTPStatus.NOT_FOUND, {"error": "Not found"})
        session = app.session(self.headers.get("Cookie"))
        if not session or self.headers.get("Origin") != app.public_origin or not secrets.compare_digest(
                self.headers.get("X-EB-CSRF", ""), session["csrf"]):
            return self.reply(HTTPStatus.FORBIDDEN, {"error": "会话或来源校验失败，请刷新页面。"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size <= 0 or size > MAX_BODY or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                raise ValueError("Request size or type invalid")
            payload = json.loads(self.rfile.read(size))
            result = app.save(route.split("/")[-1], payload, session["session_id"])
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            return self.reply(HTTPStatus.BAD_REQUEST, {"saved": False, "error": str(error)})
        return self.reply(HTTPStatus.CREATED, result)

    def log_message(self, fmt, *args):
        # Do not log submitted free text or cookies.
        super().log_message(fmt, *args)


class Server(ThreadingHTTPServer):
    def __init__(self, address, app):
        super().__init__(address, Handler)
        self.app = app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--site-dir", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--prefix", default="/joint-b")
    parser.add_argument("--public-origin", required=True)
    parser.add_argument("--port", type=int, default=18770)
    args = parser.parse_args()
    os.umask(0o077)
    app = App(args.site_dir, args.data_dir, args.prefix, args.public_origin)
    server = Server(("127.0.0.1", args.port), app)
    server.serve_forever()


if __name__ == "__main__":
    main()
