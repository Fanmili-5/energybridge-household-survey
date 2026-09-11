"""Consistent SQLite backup + completed simulation artifacts. No API access."""
import argparse,hashlib,json,sqlite3,tarfile,tempfile,time
from pathlib import Path
from common import write_json

def backup(root,output,include_traces=True):
    root=Path(root).resolve();output=Path(output).resolve()
    if output.exists():raise FileExistsError(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        snapshot=Path(tmp)/'state.sqlite3'
        with sqlite3.connect((root/'state.sqlite3').as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(snapshot) as dst:
            src.backup(dst)
            assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        with sqlite3.connect(snapshot) as snapshot_db,tarfile.open(str(output)+'.tmp','w:gz') as archive:
            jobs=snapshot_db.execute('SELECT id,status FROM jobs').fetchall()
            document_count=snapshot_db.execute('SELECT count(*) FROM documents').fetchone()[0]
            archive.add(snapshot,arcname='state.sqlite3')
            for jid,name,payload in snapshot_db.execute('SELECT job_id,name,payload FROM documents'):
                if Path(name).name!=name or Path(jid).name!=jid:raise ValueError('Invalid backup path')
                path=Path(tmp)/jid/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(payload)
                archive.add(path,arcname=f'{jid}/{name}')
            # Running EP outputs are not a valid checkpoint. Their durable inputs
            # are in the DB and can be replayed after an interrupted-job recovery.
            if include_traces:
                for jid,status in jobs:
                    if status!='complete':continue
                    case=root/jid
                    for name in ('attempts','baseline','proposal','planning'):
                        path=case/name
                        if path.exists():archive.add(path,arcname=f"{jid}/{name}")
        Path(str(output)+'.tmp').replace(output)
    checksum=hashlib.sha256()
    with output.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):checksum.update(block)
    report={'created_at':time.time(),'jobs':len(jobs),'documents':document_count,'sqlite_integrity':'ok','includes_completed_traces':include_traces,'sha256':checksum.hexdigest(),'bytes':output.stat().st_size,'path':str(output)}
    write_json(output.with_suffix('.manifest.json'),report)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data-dir',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--without-traces',action='store_true');a=p.parse_args()
    print(json.dumps(backup(a.data_dir,a.output,not a.without_traces)))
