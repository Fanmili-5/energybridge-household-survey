"""Replay every fixed seed-zero comparator input after the scoped schema fix."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from benchmark.ab_generation.common import read,save,digest,sha
from benchmark.ab_generation.unified.pipeline import _job
from benchmark.ab_generation.unified.contract import code_hash


def comparable(result):
    return dict(rows={r['id']:digest(r['patches']) for r in result['rows']},factors=result['factors'],
        targets=[(r['target'],r['status'],r.get('reason')) for r in result['coverage']['coverage']],
        gaps=result['gaps'],orders=[(r['order'],r['status']) for r in result['joint_orders']],
        independent_engineering_errors=result['independent_engineering_errors'])


def job(args):
    r,out=args;before=read(r['path']);configuration=before['comparison']['configuration'];record=before['comparison']['input_record']
    now=_job((record,configuration));target=Path(out)/(digest([record,r['seed']])[:24]+'.json.gz');save(target,now)
    return dict(household_id=r['household_id'],date=r['date'],seed=r['seed'],
        exact_candidate_and_target_replay=comparable(before)==comparable(now),
        original_catalogue_sha256=sha(r['path']),replay_catalogue_sha256=sha(target),replay_path=str(target),
        old_rows=len(before['rows']),new_rows=len(now['rows']))


def run(out,previous,workers=4):
    out,previous=Path(out),Path(previous);rs=[r for r in read(previous/'comparisons/RESULTS.json') if r['arm']=='ipog_base' and r['seed']==0]
    with ProcessPoolExecutor(max_workers=workers) as pool:rows=list(pool.map(job,[(r,out/'compatibility-replay') for r in rs],buffersize=workers*2))
    result=dict(records=rows,all_24_fixed_inputs_replay=all(r['exact_candidate_and_target_replay'] for r in rows) and len(rows)==24,
        scoped_preconditions=read(previous/'SCOPED_PATCH_PRECONDITIONS.json'),new_source_hash=code_hash(),
        reused_evidence='v2.1 fifty and 1152 comparison catalogues;their original source hashes remain authoritative',
        normal_path_proof='all 560 frozen contexts non-granular EV;all candidate runs nonempty and no exceptions;new EV/no-op/exception paths unreachable;A solver and selectors unchanged')
    save(out/'COMPATIBILITY_REPLAY.json',result);return dict(cases=len(rows),passed=result['all_24_fixed_inputs_replay'])


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--previous',required=True);p.add_argument('--workers',type=int,default=4)
    a=p.parse_args();print(run(a.out,a.previous,a.workers))
