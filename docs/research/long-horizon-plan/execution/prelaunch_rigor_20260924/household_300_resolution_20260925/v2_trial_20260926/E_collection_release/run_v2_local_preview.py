"""Localhost-only v2 engineering role preview; requires F's technical-preview gate.

This reuses the already-reviewed role UI and API without changing the old
service. It exposes only role routes, on a separate port and data directory.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
REPO = next(p for p in HERE.parents if (p / "realtime_pilot/server.py").is_file())
sys.path.insert(0, str(REPO / "realtime_pilot"))
from role_ten_day import RoleStudy
from server import Handler, make_server


class V2RoleStudy(RoleStudy):
    def profile(self, role_id):
        result = super().profile(role_id)
        for device in result["devices"]:
            if device["device"] == "ac":
                device["synthetic_owned_unit_count"] = device["owned_unit_count"]
                device["owned_unit_count"] = device["eb_controlled_unit_count"]
                device["display_unit_count_semantics"] = "D_ACTUAL_EB_CONTROLLABLE_AC_UNITS"
        return result


class V2RoleOnlyHandler(Handler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path not in {"/roles", "/roles.css", "/roles.js", "/plan-view.js"} and not path.startswith("/api/roles/"):
            return self.reply(404, {"error": "隔离 v2 工程预览仅开放角色页面"})
        if path == "/roles":
            page = (REPO / "realtime_pilot/static/roles.html").read_text(encoding="utf-8")
            page = page.replace('<a href="/" class="brand"', '<a href="/roles" class="brand"')
            page = page.replace('<a href="/">真实家庭问卷</a>', '<span>隔离工程预览</span>')
            return self.reply(200, page.encode("utf-8"), content_type="text/html; charset=utf-8")
        return super().do_GET()

    def do_POST(self):
        if not urlparse(self.path).path.startswith("/api/roles/"):
            return self.reply(404, {"error": "隔离 v2 工程预览仅开放角色接口"})
        return super().do_POST()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate", type=Path, required=True, help="F-signed role technical-preview gate")
    parser.add_argument("--data-dir", type=Path, default=HERE / "local_preview_data")
    parser.add_argument("--port", type=int, default=18766)
    args = parser.parse_args()
    gate = json.loads(args.gate.read_text(encoding="utf-8"))
    if (gate.get("status") != "ROLE_TECHNICAL_PREVIEW_APPROVED" or
            gate.get("human_collection_approved") is not False or
            gate.get("engineering_only") is not True or gate.get("revoked") is not False):
        raise ValueError("F engineering role-preview gate is absent or invalid")
    data_dir = args.data_dir.resolve()
    if data_dir == (REPO / "realtime_pilot/data/web").resolve():
        raise ValueError("v2 preview must not reuse the old service data directory")
    server = make_server(args.port, root=data_dir, disable_planning=True,
                         role_casebank_dir=HERE.parent / "G_casebank/accepted_public",
                         role_release_gate_path=args.gate, session_cookie_name="v2_role_engineering_session")
    server.RequestHandlerClass = V2RoleOnlyHandler
    try:
        study = V2RoleStudy(server.store.root, public_dir=HERE / "public_role_package",
                          casebank_dir=HERE.parent / "G_casebank/accepted_public",
                          release_gate_path=args.gate, human_mode=False)
        if not study.ready or not study.casebank["study_batch_id"].startswith("eb.engineering."):
            raise ValueError(f"v2 role preview is not F-ready: {study.load_error or study.not_ready_reason}")
        server.role_study = study
        print(json.dumps({"url": f"http://127.0.0.1:{server.server_address[1]}/roles",
                          "scope": "isolated_v2_engineering_preview", "cases": len(study.cases),
                          "human_collection": False, "data_dir": str(data_dir)}, ensure_ascii=False), flush=True)
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
