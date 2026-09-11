import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from server import Store
from backup_backend import backup
from durable_storage import Database
from test_pilot import NoExecute
from verify_paired_physics import answers
from paired_contract import CONTEXT

class DurableTests(unittest.TestCase):
    def create(self,store,owner='owner',nonce='durable_request_001'):
        return store.create(owner,{'answers':answers(),'request_id':nonce,'scenario_id':CONTEXT['id'],'scenario_understood':True},paired_flow=True)

    def test_receipt_survives_mirror_failure_and_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(tmp);store.pool=NoExecute()
            with patch('durable_storage.write_json',side_effect=OSError('disk mirror unavailable')):
                job=self.create(store)
            self.assertTrue(store.db.document(job['id'],'questionnaire_submission.json'))
            self.assertFalse((Path(tmp)/job['id']/'request.json').exists())
            store.db.close();recovered=Store(tmp);recovered.pool=NoExecute()
            self.assertEqual(recovered.jobs[job['id']]['status'],'queued')
            self.assertTrue((Path(tmp)/job['id']/'request.json').exists())
            self.assertEqual(self.create(recovered)['id'],job['id'])
            recovered.db.close()

    def test_sql_transaction_rolls_back_all_documents(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Database(tmp)
            with db.lock,db.conn:
                db.conn.execute("CREATE TRIGGER abort_docs BEFORE INSERT ON documents BEGIN SELECT RAISE(ABORT,'test failure'); END;")
            with self.assertRaises(Exception):db.save({'id':'a','status':'queued'},{'request.json':{'a':1}})
            self.assertEqual(db.jobs(),[])
            self.assertIsNone(db.document('a','request.json'))
            db.close()

    def test_restart_retries_bounded_and_keeps_attempt_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(tmp);store.pool=NoExecute();j=self.create(store)
            j.update(status='running',attempts=3);store.persist(j);store.db.close()
            recovered=Store(tmp)
            self.assertEqual(recovered.jobs[j['id']]['status'],'interrupted')
            self.assertTrue(recovered.db.document(j['id'],'request.json'))
            recovered.pool.shutdown();recovered.db.close()

    def test_backup_restores_durable_answers(self):
        import tarfile
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'jobs';store=Store(root);store.pool=NoExecute();j=self.create(store)
            archive=Path(tmp)/'backup.tar.gz';report=backup(root,archive)
            self.assertEqual(report['jobs'],1)
            restore=Path(tmp)/'restore'
            with tarfile.open(archive) as tar:tar.extractall(restore,filter='data')
            recovered=Store(restore)
            self.assertEqual(recovered.db.document(j['id'],'questionnaire_submission.json')['raw_answers'],answers())
            recovered.pool.shutdown();recovered.db.close();store.db.close()

    def test_shutdown_does_not_claim_another_queued_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(tmp);store.pool=NoExecute();j=self.create(store)
            store.stopping=True
            with patch('server.subprocess.Popen') as process:
                store.execute(j['id'])
            process.assert_not_called()
            self.assertEqual(store.db.jobs()[0]['status'],'queued')
            self.assertNotIn('attempts',store.db.jobs()[0])
            store.db.close()
