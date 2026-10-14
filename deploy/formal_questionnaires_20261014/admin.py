"""Private invitation provisioning, consistent backup and withdrawn-safe export."""
import argparse,csv,json,os,secrets,sqlite3
from pathlib import Path
from server import Release
from store import Store

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['provision','export','backup']);p.add_argument('--data-root',type=Path,required=True);p.add_argument('--release',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--origin',default='https://47.85.194.154');a=p.parse_args();os.umask(0o077)
    assert not a.output.exists(),'Do not overwrite invitations, exports or backups'
    if a.action=='backup':
        a.output.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        with sqlite3.connect('file:'+str(a.data_root/'formal_responses.sqlite3')+'?mode=ro',uri=True)as src,sqlite3.connect(a.output)as dst:src.backup(dst)
        a.output.chmod(0o600);print(json.dumps({'backup':'pass'}));return
    release=Release(a.release)if a.release else None
    store=Store(a.data_root,release.signature if release else 'private-export-only')
    a.output.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if a.action=='export':
        records=store.export()
        with a.output.open('x')as f:
            for record in records:f.write(json.dumps(record,ensure_ascii=False,separators=(',',':'))+'\n')
        a.output.chmod(0o600);print(json.dumps({'exported_current_nonwithdrawn_responses':len(records),'training_release':False}));return
    if not release:raise ValueError('Provisioning requires a verified release')
    assignments=[(release.batch+'-'+row['household_id'],release.batch,row['household_id'],secrets.token_urlsafe(32))for row in release.rows.values()]
    # Private file is written exclusively before the DB transaction. If the
    # transaction fails, retain the file for operator audit; no secret is logged.
    with a.output.open('x',newline='')as f:
        writer=csv.writer(f);writer.writerow(['slot_id','batch','household_id','entry_url','invite_code'])
        writer.writerows((slot,batch,hid,a.origin+release.prefix,token)for slot,batch,hid,token in assignments)
    a.output.chmod(0o600);store.provision(assignments);print(json.dumps({'provisioned':len(assignments),'batch':release.batch,'credentials_logged':False}))

if __name__=='__main__':main()
