"""Explicit public origins must not weaken request isolation."""
import tempfile
import unittest
import threading
import json
import http.client
from server import make_server

class DeploymentTests(unittest.TestCase):
    def test_paused_server_rejects_all_generation_routes_before_queueing(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = make_server(0, tmp, disable_planning=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            conn = http.client.HTTPConnection(*server.server_address, timeout=5)
            try:
                for path in ('/api/jobs', '/api/paired', '/api/proposals', '/api/example'):
                    conn.request('POST', path, json.dumps({}), headers={
                        'Origin':f'http://127.0.0.1:{server.server_address[1]}',
                        'Cookie':'pilot_session='+'a'*64,
                        'Content-Type':'application/json'})
                    response = conn.getresponse()
                    self.assertEqual(response.status, 503)
                    response.read()
                self.assertEqual(server.store.jobs, {})
            finally:
                conn.close()
                server.shutdown()
                server.server_close()
                server.store.pool.shutdown()

    def test_explicit_origin_only_and_loopback_listener(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = make_server(0, tmp, public_origin='http://192.0.2.10')
            try:
                self.assertEqual(server.server_address[0], '127.0.0.1')
                self.assertIn('192.0.2.10', server.allowed_hosts)
                self.assertIn('http://192.0.2.10', server.allowed_origins)
                self.assertNotIn('http://unrelated.example', server.allowed_origins)
            finally:
                server.store.pool.shutdown()
                server.server_close()

    def test_invalid_origins_fail_before_startup(self):
        for origin in ('*', 'ftp://example.org', 'https://example.org/path', 'http://user:pass@example.org', 'http://example.org?x=1'):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                make_server(0, public_origin=origin)
