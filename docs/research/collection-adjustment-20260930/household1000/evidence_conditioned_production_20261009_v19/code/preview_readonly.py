"""Loopback-only static preview of the unchanged binary-adoption frontend.

The original HTTPS recording server remains unchanged. This adapter serves the
frozen pages and their exact assets, rejects every POST, and creates no answers.
The frontend's existing local-download mode is used, not experience_only mode
(which would change its questions).
"""
import argparse
import html
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ASSETS = {"style.css", "candidate.css", "joint-view.css", "plan-view.js",
          "source-draft.js", "household-view.js", "joint-view.js"}


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, body, mime="application/json; charset=utf-8"):
        if isinstance(body, dict):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path in {"/household50", "/household50/"}:
            return self.reply(200, self.server.catalog, "text/html; charset=utf-8")
        if path == "/household50/api/health":
            return self.reply(200, {"mode": "read_only_pages_local_download",
                                   "households": 50, "cases": 500,
                                   "server_answer_writes": False,
                                   "original_binary_question_contract": True})
        if path == "/household50/style.css":
            target = self.server.release / "households" / self.server.index[0]["household_id"] / "style.css"
        else:
            parts = path.strip("/").split("/")
            route = "/" + parts[0]
            row = self.server.routes.get(route)
            if row is None or len(parts) > 2:
                return self.reply(404, {"error": "Not found"})
            name = parts[1] if len(parts) == 2 and parts[1] else "index.html"
            if name != "index.html" and name not in ASSETS:
                return self.reply(404, {"error": "Not found"})
            target = self.server.release / "households" / row["household_id"] / name
        return self.reply(200, target.read_bytes(), mimetypes.guess_type(target.name)[0] or "application/octet-stream")

    def do_POST(self):
        return self.reply(405, {"error": "Read-only preview; no server answers are saved"})

    def log_message(self, *args):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--release", type=Path, required=True)
    ap.add_argument("--port", type=int, default=18779)
    args = ap.parse_args()
    release = args.release.resolve()
    index = json.loads((release / "INDEX50.json").read_text())["households"]
    assert len(index) == 50 and sum(row["cases"] for row in index) == 500
    items = "".join(f'<li><a href="{row["route"]}/">第 {i} 户 · {html.escape(row["province"])} · {row["N"]} 人 · {row["G"]} 代 · {row["K"]} 类设备 · 10个日期</a></li>' for i, row in enumerate(index, 1))
    catalog = ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>V19原前端 · 50户参考任务</title><link rel="stylesheet" href="/household50/style.css"></head><body class="survey-page"><header><span class="brand">EnergyBridge</span><span>V19原前端参考任务</span></header><main><section class="panel"><h1>选择测试家庭</h1><p>原50户、原随机10日期，共500对新A/B，接入同版学校参考仿真。沿用原二元采纳题、四项可空评分和原因。</p><p>本预览不在服务器保存回答；原本地下载仅用于工程检查，不是正式真人反馈。实际真人回答仍为0，参考作息与物理结果未实测校准。</p><ol>' + items + '</ol></section></main></body></html>').encode()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.release, server.index, server.catalog = release, index, catalog
    server.routes = {row["route"]: row for row in index}
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
