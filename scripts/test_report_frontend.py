"""Problem reporting in disposable browsers/databases; no EP or model calls."""
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'realtime_pilot'))
from common import digest
from date_sampling import assigned_context
from paired_contract import QUESTIONS, QUESTIONNAIRE_VERSION, CONTEXT
from regional_test_support import answers
from server import make_server, PARTICIPANT_UI_VERSION
from test_pilot import NoExecute


def check(script, seeded=False):
    with tempfile.TemporaryDirectory(prefix='eb-report-browser-') as root:
        server = make_server(0, root, disable_planning=True, admin_user='testadmin')
        server.store.pool.shutdown()
        server.store.pool = NoExecute()
        if seeded:
            owner = 'a' * 64
            intake = server.store.save_household(owner, {
                'request_id': 'report_browser_household_01', 'answers': answers(),
                'participant_name': '测试昵称', 'questionnaire_version': QUESTIONNAIRE_VERSION,
                'questionnaire_hash': digest(QUESTIONS),
                'questionnaire_context_hash': assigned_context(owner)['context_hash'],
                'ui_version': PARTICIPANT_UI_VERSION,
            })
            job = server.store.create(owner, {
                'request_id': 'report_browser_case_01', 'submission_id': intake['id'],
                'scenario_id': CONTEXT['id'], 'scenario_understood': True,
            }, paired_flow=True)
            job.update(status='failed', error='Synthetic failed case; no worker was run.')
            server.store.jobs[job['id']] = job
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            subprocess.run(['node', str(ROOT / 'realtime_pilot/deploy' / script)],
                           env={**os.environ, 'REPORT_TEST_URL':
                                f'http://127.0.0.1:{server.server_address[1]}'},
                           check=True, timeout=90)
        finally:
            server.shutdown()
            server.server_close()
            server.store.pool.shutdown()
            server.store.db.close()


if __name__ == '__main__':
    check('verify_floating_report.js')
    check('verify_case_reports.js', seeded=True)
