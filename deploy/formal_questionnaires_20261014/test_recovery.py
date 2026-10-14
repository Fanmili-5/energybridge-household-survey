"""Failure-injection acceptance; uses invented invitations and temporary DBs."""
import csv,hashlib,json,sqlite3,tarfile,tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from admin import provision_release
from backup import backup
from store import Store

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def rejected(call,kind=ValueError):
    try:call()
    except kind:return
    raise AssertionError('Invalid recovery state was accepted')

def run():
    checks={}
    release=SimpleNamespace(batch='formal50',prefix='/household50',rows={str(i):{'household_id':'invented-fixture-'+str(i)}for i in range(50)})
    with tempfile.TemporaryDirectory(prefix='eb-recovery-fixtures-')as tmp:
        root=Path(tmp)/'source';store=Store(root/'collection_v1','invented-release',fixtures=True)
        invites=root/'operator_invites'/'formal50.csv'
        with patch.object(store,'provision',side_effect=RuntimeError('invented interruption after CSV write')):
            rejected(lambda:provision_release(store,release,invites),RuntimeError)
        file_hash=sha(invites)
        with store.connect()as db:assert db.execute('select count(*)from invitations').fetchone()[0]==0
        resumed=provision_release(store,release,invites)
        assert resumed['reused_private_file']and resumed['provisioned']==50 and sha(invites)==file_hash
        checks['CSV_present_DB_transaction_failed_resumes_same_credentials']=True
        with invites.open(newline='')as f:rows=list(csv.DictReader(f))
        session,token=store.session(None,create=True)
        claimed=store.claim(session,'formal50',rows[0]['invite_code'],'invented-fixture-IP')
        repeated=provision_release(store,release,invites)
        assert repeated['provisioned']==0 and repeated['verified']==50 and sha(invites)==file_hash
        with store.connect()as db:
            assert db.execute('select actor_id from invitations where slot_id=?',(rows[0]['slot_id'],)).fetchone()[0]==claimed['participant_id']
        checks['repeat_provision_preserves_codes_and_claimed_identity']=True
        session,_=store.session(token)
        store.withdraw(session)
        rejected(lambda:store.actor(session),PermissionError)
        rejected(lambda:store.claim(session,'formal50',rows[0]['invite_code'],'invented-fixture-IP'),PermissionError)
        checks['stale_session_and_withdrawn_invite_rejected']=True
        # One conflict must roll back the entire attempted assignment batch.
        db_hash=sha(store.db_path)
        bad=[(r['slot_id'],r['batch'],r['household_id'],r['invite_code'])for r in rows]
        bad[-1]=(*bad[-1][:3],'invented-conflicting-credential-00001')
        rejected(lambda:store.provision(bad))
        assert sha(store.db_path)==db_hash
        checks['conflicting_credential_rejected_without_DB_write']=True
        # An extra household slot must be detected before filling a missing one.
        with store.connect()as db:
            db.execute('delete from invitations where slot_id=?',(rows[-1]['slot_id'],))
            db.execute('insert into invitations values(?,?,?,?,NULL)',('invented-extra-digest','invented-extra-slot','formal50','invented-extra-household'))
        db_hash=sha(store.db_path)
        rejected(lambda:provision_release(store,release,invites))
        assert sha(store.db_path)==db_hash and sha(invites)==file_hash
        checks['unexpected_DB_household_rejected_before_partial_repair']=True
        with store.connect()as db:db.execute('delete from invitations where slot_id=?',('invented-extra-slot',))
        assert provision_release(store,release,invites)['provisioned']==1
        db_hash=sha(store.db_path)
        receipt=backup(root,Path(tmp)/'rolling');assert receipt['backup']=='pass'and sha(store.db_path)==db_hash
        restore=Path(tmp)/'restore';restore.mkdir()
        with tarfile.open(Path(tmp)/'rolling'/'latest.tar.gz')as archive:
            for member in archive.getmembers():
                target=restore/member.name;assert target.resolve().is_relative_to(restore.resolve())and not member.issym()and not member.islnk()
                if member.isfile():target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(archive.extractfile(member).read())
        manifest=json.loads((restore/'MANIFEST.json').read_text())
        assert all(sha(restore/name)==value for name,value in manifest['files'].items())
        with sqlite3.connect(restore/'formal_responses.sqlite3')as db:assert db.execute('pragma integrity_check').fetchone()[0]=='ok'
        assert sha(restore/'credential_pepper')==sha(store.root/'credential_pepper')
        checks['consistent_recovery_bundle_hash_and_SQLite_restore']=True
        pepper=store.root/'credential_pepper';original=pepper.read_bytes();pepper.unlink()
        rejected(lambda:Store(store.root,'invented-release',fixtures=True),RuntimeError)
        assert not pepper.exists()and sha(store.db_path)==db_hash
        pepper.write_bytes(original);pepper.chmod(0o600)
        checks['existing_DB_missing_pepper_fails_without_rekey']=True
    return {'passed':True,'checks':checks,'human_answers_generated':0,'production_records_written':0,'scope':'invented failure injection; no human or physical validity claim'}

if __name__=='__main__':print(json.dumps(run(),sort_keys=True))
