"""Reject truncated proxy paths without creating a collection identity."""
import io
import json
import unittest
import urllib.error
from unittest.mock import patch
from deploy.activate_reference50_ui91 import verify_public_body_capacity


def rejected(code,body):
    return urllib.error.HTTPError('https://example.invalid',code,'fixture',{},io.BytesIO(body))


def too_small(*args,**kwargs):
    raise rejected(413,b'')


class BodyCapacityTests(unittest.TestCase):
    def test_full_application_bound_is_probed_without_identity(self):
        error=rejected(403,json.dumps({'error':'会话已失效'}).encode())
        with patch('deploy.activate_reference50_ui91.urllib.request.urlopen',side_effect=error)as opened:
            result=verify_public_body_capacity('https://example.invalid')
        request=opened.call_args.args[0]
        self.assertEqual(len(request.data),256*1024)
        self.assertEqual(set(json.loads(request.data)),{'engineering_body_size_probe'})
        self.assertIsNone(request.get_header('Cookie'))
        self.assertIsNone(request.get_header('X-eb-csrf'))
        self.assertTrue(result['unauthenticated_write_rejected'])

    def test_reload_may_drain_old_workers_but_permanent_413_blocks_release(self):
        errors=[rejected(413,b''),rejected(403,json.dumps({'error':'会话已失效'}).encode())]
        with patch('deploy.activate_reference50_ui91.time.sleep'),patch('deploy.activate_reference50_ui91.urllib.request.urlopen',side_effect=errors):
            self.assertTrue(verify_public_body_capacity('https://example.invalid')['passed'])
        with patch('deploy.activate_reference50_ui91.time.sleep'),patch('deploy.activate_reference50_ui91.urllib.request.urlopen',side_effect=too_small):
            with self.assertRaisesRegex(RuntimeError,'Proxy body limit'):
                verify_public_body_capacity('https://example.invalid')

    def test_anonymous_probe_must_not_succeed_or_stop_at_unrelated_auth(self):
        with patch('deploy.activate_reference50_ui91.urllib.request.urlopen',return_value=io.BytesIO(b'{}')):
            with self.assertRaisesRegex(RuntimeError,'unexpectedly accepted'):
                verify_public_body_capacity('https://example.invalid')
        with patch('deploy.activate_reference50_ui91.urllib.request.urlopen',side_effect=rejected(403,b'{"error":"other authorization"}')):
            with self.assertRaisesRegex(RuntimeError,'session rejection'):
                verify_public_body_capacity('https://example.invalid')


if __name__=='__main__':unittest.main()
