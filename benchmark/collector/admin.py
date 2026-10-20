"""Private status, append-only quality reviews, exports and consistent backup."""
import argparse
import collections
import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
from pathlib import Path
from identity import now
from ledger import CollectionStore,NOTICE_VERSION
from release import Release

def backup(root,output):
    root=Path(root);output=Path(output);output.mkdir(parents=True,exist_ok=True,mode=0o700)
    with tempfile.TemporaryDirectory(prefix='snapshot-',dir=output)as temp:
        stage=Path(temp)
        with sqlite3.connect('file:'+str(root/'formal_responses.sqlite3')+'?mode=ro',uri=True)as source,sqlite3.connect(stage/'formal_responses.sqlite3')as target:
            source.backup(target)
        with sqlite3.connect(stage/'formal_responses.sqlite3')as db:
            assert db.execute('pragma integrity_check').fetchone()[0]=='ok'
            counts={t:db.execute('select count(*)from '+t).fetchone()[0]for t in ['actors','current_drafts','responses_v69','view_history','withdrawals','assignment_leases','quality_reviews']}
            if db.execute("select 1 from sqlite_master where name='participant_rounds'").fetchone():counts['participant_rounds']=db.execute('select count(*)from participant_rounds').fetchone()[0]
            signature=db.execute("select value from collection_metadata where key='release_sha256'").fetchone()[0]
        shutil.copy2(root/'credential_pepper',stage/'credential_pepper')
        manifest={'schema':'eb.reference_benchmark.backup.v1','created_at':now(),'release_sha256':signature,'row_counts':counts,'sqlite_integrity':'ok'}
        (stage/'MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
        pending=output/'pending.tar.gz'
        with tarfile.open(pending,'w:gz')as tar:
            for path in sorted(stage.iterdir()):tar.add(path,arcname=path.name)
        if (output/'latest.tar.gz').exists():(output/'latest.tar.gz').replace(output/'previous.tar.gz')
        pending.replace(output/'latest.tar.gz');(output/'latest.tar.gz').chmod(0o600)
        (output/'LATEST_RECEIPT.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest

def status(store):
    with store.connect()as db:
        rows=db.execute('''select r.actor_id,r.case_id,r.revision,a.household_id from responses_v69 r join actors a using(actor_id)
            where r.release=?and a.active=1 and a.consent_version=?order by r.rowid''',(store.release,NOTICE_VERSION)).fetchall()
        reviews=db.execute('select * from quality_reviews where release=?order by review_id',(store.release,)).fetchall()
        actors=db.execute('select count(*)from actors where active=1').fetchone()[0]
        people=db.execute('select count(distinct p.participant_id)from participant_rounds p join actors a using(actor_id)where a.active=1').fetchone()[0]
    latest={(r['actor_id'],r['case_id']):dict(r)for r in rows}
    review_by_key={(r['actor_id'],r['case_id'],r['answer_revision']):r['status']for r in reviews}
    submitted=collections.Counter();valid=collections.Counter();unreviewed=collections.Counter()
    for row in latest.values():
        case=row['case_id'];key=(row['actor_id'],case,row['revision']);submitted[case]+=1
        if review_by_key.get(key)=='valid':valid[case]+=1
        if key not in review_by_key:unreviewed[case]+=1
    cases=[]
    for case,row in store.public_release.records.items():
        cases.append({'case_id':case,'household_id':row['household_id'],'submitted':submitted[case],
                      'reviewed_valid':valid[case],'unreviewed':unreviewed[case]})
    complete=collections.Counter(row['actor_id']for row in latest.values())
    return {'schema':'eb.reference_benchmark.collection_status.v1','release_sha256':store.release,'active_identities':people,
            'active_assignments':actors,'completed_rounds':sum(n==store.public_release.questions_per_household for n in complete.values()),
            'human_identity_validation':'not_performed','submitted_latest_actor_cases':len(latest),
            'reviewed_valid_actor_cases':sum(c['reviewed_valid']for c in cases),
            'source_cases_with_submissions':sum(c['submitted']>0 for c in cases),'source_case_count':len(cases),'cases':cases}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['backup','status','export','review'])
    p.add_argument('--data-root',type=Path,required=True);p.add_argument('--release',type=Path)
    p.add_argument('--output',type=Path);p.add_argument('--review-file',type=Path);p.add_argument('--quality',choices=['all','valid'],default='all')
    a=p.parse_args();os.umask(0o077)
    if a.action=='backup':assert a.output;print(json.dumps(backup(a.data_root,a.output)));raise SystemExit
    assert a.release;store=CollectionStore(a.data_root,Release(a.release))
    if a.action=='review':assert a.review_file;print(json.dumps(store.review(json.loads(a.review_file.read_text()))));raise SystemExit
    if a.action=='status':print(json.dumps(status(store),ensure_ascii=False));raise SystemExit
    assert a.output and not a.output.exists();a.output.parent.mkdir(parents=True,exist_ok=True)
    records=store.export(a.quality)
    with a.output.open('x')as f:
        for record in records:f.write(json.dumps(record,ensure_ascii=False,separators=(',',':'))+'\n')
    a.output.chmod(0o600)
    print(json.dumps({'exported_latest_nonwithdrawn_answers':len(records),'quality_scope':a.quality,'training_release':False}))
