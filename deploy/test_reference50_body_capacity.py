"""Reject truncated proxy paths without creating a collection identity."""
import io
import json
import unittest
import types
import urllib.error
from unittest.mock import patch
from deploy.activate_reference50_ui91 import verify_public_body_capacity,verify_presentation,storage_unit_guard


def rejected(code,body):
    return urllib.error.HTTPError('https://example.invalid',code,'fixture',{},io.BytesIO(body))


def too_small(*args,**kwargs):
    raise rejected(413,b'')


class BodyCapacityTests(unittest.TestCase):
    def test_clean_presentation_requires_its_parent_and_zero_to_five_integers(self):
        release=types.SimpleNamespace(manifest={'presentation_revision':'eb.questionnaire50.refined.v91.clean.v2',
            'source_pins':{'parent_information_release_sha256':'parent'},'presentation_update':{'case_bytes_unchanged':True}},
            answer_instructions={'range':[0,5],'decimal_places':0,'score_values':[0,1,2,3,4,5]})
        self.assertTrue(verify_presentation(release,'parent').endswith('clean.v2'))
        with self.assertRaises(AssertionError):verify_presentation(release,'wrong-parent')
        release.answer_instructions['decimal_places']=1
        with self.assertRaises(AssertionError):verify_presentation(release,'parent')

    def test_mount_guards_apply_to_the_new_layout_without_replacing_old_layout(self):
        layout={'mount_root':'/srv/data','binds':{'/opt/current':'/srv/data/programs','/var/lib/current':'/srv/data/answers'}}
        with patch('deploy.activate_reference50_ui91.command',side_effect=['srv-data.mount','opt-current.mount','var-lib-current.mount']):
            text=storage_unit_guard('/etc/collection/new-layout.json',layout)
        self.assertIn('RequiresMountsFor=/srv/data /opt/current /var/lib/current',text)
        self.assertIn('BindsTo=srv-data.mount opt-current.mount var-lib-current.mount',text)
        self.assertIn('--layout /etc/collection/new-layout.json',text)

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
