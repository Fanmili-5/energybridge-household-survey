"""Archive the exact predeclared probe domains, including engineering requests.

Deterministic reconstruction of the recorded probes; no selection or reroll.
The primary build already retains its complete catalogue and error ledgers.
"""
import argparse
from pathlib import Path
from benchmark.ab_generation.common import read,save,sha,verify,seal,code_hash
from benchmark.ab_generation.collection_candidates import generate_day
from benchmark.ab_generation.collection_design import design,report_counts


def archive(root,probe,out):
    root,probe,out=Path(root),Path(probe),Path(out)
    verify(root);verify(probe);pre=read(probe/'PRE_PROBE.json')
    if pre['code_sha256']!=code_hash():raise ValueError('PROBE_ARCHIVE_CODE_MISMATCH')
    cfg=read(root/'DESIGN.json');out.mkdir(parents=True,exist_ok=False);records=[]
    expected={(r['variant'],r['case_id']):r for r in read(probe/'RESULT.json')['records']}
    for name,overrides in pre['variants']:
        for case in pre['cases']:
            c=read(root/'contexts'/(case+'.json.gz'));d=generate_day(c,design({**cfg,**overrides}))
            old=expected[(name,case)]
            if len(d['rows'])!=old['catalogue_unique'] or report_counts(d['rows'])!=old['counts']:
                raise ValueError('PROBE_ARCHIVE_DOMAIN_CHANGED')
            save(out/name/(case+'.json.gz'),d)
            records.append({'variant':name,'case_id':case,'same_recorded_counts':True,
                'eligible':len(d['rows']),'engineering':len(d['engineering_diagnostics']),
                'quarantined':len(d['quarantined_requests'])})
    result={'passed':True,'probes':len(records),'records':records,'selection_changed':False,
            'engineering_requests_retained':sum(r['engineering'] for r in records),
            'code_sha256':code_hash(),'probe_pre_registration_sha256':sha(probe/'PRE_PROBE.json'),
            'outcomes_used':False,'new_engine_runs':0}
    save(out/'SUMMARY.json',result);seal(out,{'schema':'eb.collection.probe_archive.v2','code_sha256':code_hash()})
    return {k:v for k,v in result.items() if k!='records'}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',required=True)
    p.add_argument('--probe',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    print(archive(a.root,a.probe,a.out))
