"""Loopback, read-only server for the existing v69 questionnaire material bank."""
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit
from benchmark.ab_generation.common import bound
from .questionnaire import verify_questionnaire

PREFIX = '/household50-current'


def handler(folder):
    root = Path(folder).resolve() / 'public'
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, code, body, mime='application/json; charset=utf-8', location=None):
            raw = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            for key, value in {'Content-Type': mime, 'Content-Length': str(len(raw)), 'Cache-Control': 'no-store',
                    'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
                    'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"}.items():
                self.send_header(key, value)
            if location:
                self.send_header('Location', location)
            self.end_headers(); self.wfile.write(raw)

        def do_GET(self):
            path = unquote(urlsplit(self.path).path)
            if path in ('/', PREFIX):
                return self.send(302, b'', location=PREFIX + '/form')
            if not path.startswith(PREFIX + '/'):
                return self.send(404, {'error': 'NOT_FOUND'})
            relative = path[len(PREFIX) + 1:]
            if relative in ('form', ''):
                relative = 'index.html'
            try:
                target = bound(root, relative)
                if target.suffix not in ('.html', '.js', '.css', '.json') or not target.is_file():
                    raise ValueError('NOT_PUBLIC')
                return self.send(200, target.read_bytes(), (mimetypes.guess_type(str(target))[0] or 'application/octet-stream') + '; charset=utf-8')
            except (ValueError, OSError):
                return self.send(404, {'error': 'NOT_FOUND'})

        def do_POST(self):
            return self.send(405, {'saved': False, 'error': 'READ_ONLY_MATERIAL_PREVIEW;NO_COLLECTION_OR_SIMULATION'})
    return Handler


def serve(release, port=18780):
    verify_questionnaire(release)
    server = ThreadingHTTPServer(('127.0.0.1', port), handler(release))
    print('v69 questionnaire materials preview: http://127.0.0.1:%d%s/form' % (server.server_port, PREFIX), flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
