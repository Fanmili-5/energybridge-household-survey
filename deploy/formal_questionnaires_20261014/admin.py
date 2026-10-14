"""Private invitation provisioning, consistent backup and withdrawn-safe export."""
import argparse,csv,json,os,secrets,sqlite3
from pathlib import Path
from server import Release
from store import Store

def provision_release(store,release,output,origin='https://47.85.194.154'):
    """Resume from the same private CSV; never rotate existing credentials."""
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    expected={release.batch+'-'+r['household_id']:r['household_id']for r in release.rows.values()}
    reused=output.exists()
    if reused:
        with output.open(newline='')as f:
            reader=csv.DictReader(f)
            if reader.fieldnames!=['slot_id','batch','household_id','entry_url','invite_code']:raise ValueError('Invalid private invitation columns')
            rows=list(reader)
        if len(rows)!=len(expected)or {r['slot_id']for r in rows}!=set(expected):raise ValueError('Private invitation household set differs from verified release')
        for r in rows:
            if r['batch']!=release.batch or r['household_id']!=expected[r['slot_id']]or r['entry_url']!=origin+release.prefix:raise ValueError('Private invitation assignment differs from verified release')
        assignments=[(r['slot_id'],r['batch'],r['household_id'],r['invite_code'])for r in rows]
    else:
        assignments=[(slot,release.batch,hid,secrets.token_urlsafe(32))for slot,hid in expected.items()]
        # Write credentials before the transaction, then replay exactly this
        # file on interruption. Its existence is never a DB acceptance signal.
        with output.open('x',newline='')as f:
            writer=csv.writer(f);writer.writerow(['slot_id','batch','household_id','entry_url','invite_code'])
            writer.writerows((slot,batch,hid,origin+release.prefix,token)for slot,batch,hid,token in assignments)
            f.flush();os.fsync(f.fileno())
        output.chmod(0o600)
    with store.connect()as db:
        prior_slots={r['slot_id']for r in db.execute('select slot_id from invitations where batch=?',(release.batch,))}
    if not prior_slots<=set(expected):raise ValueError('Existing database contains unexpected household invitations')
    inserted=store.provision(assignments)
    with store.connect()as db:
        slots={r['slot_id']for r in db.execute('select slot_id from invitations where batch=?',(release.batch,))}
    if slots!=set(expected):raise ValueError('Database invitation set differs from verified release')
    return {'provisioned':inserted,'verified':len(assignments),'batch':release.batch,'reused_private_file':reused,'credentials_logged':False}

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['provision','export','backup']);p.add_argument('--data-root',type=Path,required=True);p.add_argument('--release',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--origin',default='https://47.85.194.154');a=p.parse_args();os.umask(0o077)
    if a.action!='provision':assert not a.output.exists(),'Do not overwrite exports or backups'
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
    print(json.dumps(provision_release(store,release,a.output,a.origin)))

if __name__=='__main__':main()
