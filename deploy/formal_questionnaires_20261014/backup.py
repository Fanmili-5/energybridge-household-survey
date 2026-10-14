"""Consistent private recovery bundle; retains latest and previous snapshots.

Every bundle contains a SQLite online backup, credential pepper and both
operator invitation lists. It is separate from the append-only source data.
Only obsolete recovery bundles rotate; source responses are never changed.
"""
import argparse,hashlib,json,os,shutil,sqlite3,tarfile,tempfile
from datetime import datetime,timezone
from pathlib import Path

def backup(root,out):
    os.umask(0o077);out.mkdir(parents=True,exist_ok=True,mode=0o700)
    data=root/'collection_v1';source=data/'formal_responses.sqlite3'
    assert source.exists()and(data/'credential_pepper').exists()
    with tempfile.TemporaryDirectory(prefix='consistent-',dir=out)as tmp:
        stage=Path(tmp);database=stage/'formal_responses.sqlite3'
        with sqlite3.connect('file:'+str(source)+'?mode=ro',uri=True)as src,sqlite3.connect(database)as dst:src.backup(dst)
        with sqlite3.connect(database)as db:
            assert db.execute('pragma integrity_check').fetchone()[0]=='ok'
            counts={name:db.execute('select count(*)from '+name).fetchone()[0]for name in('invitations','actors','sessions','answers','withdrawals')}
        shutil.copy2(data/'credential_pepper',stage/'credential_pepper');shutil.copytree(root/'operator_invites',stage/'operator_invites')
        hashes={}
        for p in stage.rglob('*'):
            if not p.is_file():continue
            h=hashlib.sha256()
            with p.open('rb')as f:
                for block in iter(lambda:f.read(2**20),b''):h.update(block)
            hashes[str(p.relative_to(stage))]=h.hexdigest()
        manifest={'schema':'eb.private_collection_recovery.v1','created_at':datetime.now(timezone.utc).isoformat(),'row_counts':counts,'files':hashes,'sqlite_integrity':'ok'}
        (stage/'MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
        pending=out/'pending.tar.gz'
        with tarfile.open(pending,'w:gz',compresslevel=1)as archive:
            for p in sorted(stage.iterdir()):archive.add(p,arcname=p.name)
        # Retain two consistent bundles, without changing the collection DB.
        latest=out/'latest.tar.gz';previous=out/'previous.tar.gz'
        if latest.exists():latest.replace(previous)
        pending.replace(latest);latest.chmod(0o600)
        (out/'LATEST_RECEIPT.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return {'backup':'pass','row_counts':counts,'sqlite_integrity':'ok','two_rolling_recovery_bundles':True,'private_credentials_logged':False}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path('/var/lib/energybridge-role-collection'));p.add_argument('--output',type=Path,default=Path('/var/backups/energybridge-role-collection/rolling'));a=p.parse_args();print(json.dumps(backup(a.root,a.output)))
