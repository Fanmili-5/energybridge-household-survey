"""Local-only read-only preview: no server answers, no EP and no model calls."""
import argparse,html,json,mimetypes
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
ASSETS={'style.css','candidate.css','joint-view.css','plan-view.js','source-draft.js','household-view.js','joint-view.js','respondent-info.js'}
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path=urlsplit(self.path).path
        if path in ['/household50','/household50/']:
            items=''.join('<li><a href="'+r['route']+'/">'+html.escape(r['province'])+' · '+str(r['N'])+'人 · 10日期</a></li>'for r in self.server.rows)
            data=('<!doctype html><html lang="zh-CN"><title>50户改版预览</title><h1>50户改版预览</h1><p>仅供核验；回答只下载，不写入服务器。</p><ol>'+items+'</ol></html>').encode();mime='text/html; charset=utf-8'
        else:
            parts=path.strip('/').split('/');row=self.server.routes.get('/'+parts[0]);name=parts[1]if len(parts)>1 and parts[1]else 'index.html'
            if not row or len(parts)>2 or name not in ASSETS|{'index.html'}:self.send_error(404);return
            p=self.server.root/'households'/row['household_id']/name;data=p.read_bytes();mime=mimetypes.guess_type(p.name)[0]or'application/octet-stream'
        self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)
    def do_POST(self):self.send_error(405)
    def log_message(self,*args):pass
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--release',type=Path,required=True);ap.add_argument('--port',type=int,default=18828);a=ap.parse_args()
    s=ThreadingHTTPServer(('127.0.0.1',a.port),Handler);s.root=a.release;s.rows=json.loads((a.release/'INDEX50.json').read_text())['households'];s.routes={r['route']:r for r in s.rows};print('read-only preview ready',flush=True);s.serve_forever()
