"""Exact physical-output reuse, preserving provenance and current-ledger readback."""
import collections,os,shutil
from common import *
from ep_gate import require_reviewed_ep,guard_job
from physics import scoped_rows,check_run_coverage,ENGINE
def key(r):return (r['household_id'],r['round_index'],r['variant'],r['arm'])
def main():
 school_guard();lease=require_reviewed_ep('original50');old=BASE/'reviewed_reference_production_20261010_v21'
 source=[]
 for name in ['EP_all_REVIEW.json','EP_sensitivity_REVIEW.json']:
  source.extend(read(old/name)['records'])
 for r in read(old/'MODEL_FORM_SENSITIVITY.json')['records']:source.extend(r['runs'].values())
 index={}
 for r in source:
  k=key(r)
  if k in index and (index[k]['signature']!=r['signature'] or index[k]['SQL_sha256']!=r['SQL_sha256']):
   raise RuntimeError('Conflicting old run receipts: '+str(k))
  index[k]=r
 reused={};evidence=[]
 for scope in ['all','sensitivity','model_form']:
  rows=scoped_rows(scope);records=[]
  for c in rows:
   for side in ('A','B'):
    guard_job(c,side,lease);k=(* (c['household_id'],c['round_index'],c['variant']),side)
    if k not in reused:
     r=index[k];b=c[side];actual={'IDF_sha256':sha(OUT/b['IDF_path']),'weather_sha256':sha(c['weather']['path']),'engine_sha256':sha(ENGINE)}
     if actual!=r['signature'] or not r['runtime_pass'] or r['returncode']!=0 or r['severe_fatal']:raise RuntimeError('Old physical identity is not exact: '+str(k))
     source_sql=old/r['SQL_path']
     if sha(source_sql)!=r['SQL_sha256']:raise RuntimeError('Old SQL bytes changed')
     receipt=source_sql.parent/'RUN_RECORD.json'
     if sha(receipt) is None or read(receipt)['signature']!=actual:raise RuntimeError('Old receipt identity mismatch')
     target=OUT/'runs'/c['variant']/c['household_id']/f"{c['round_index']:02d}_{side}"
     target.mkdir(parents=True,exist_ok=True)
     for source_file in [source_sql,source_sql.parent/'eplusout.err']:
      dst=target/source_file.name
      if dst.exists():
       if sha(dst)!=sha(source_file):raise RuntimeError('Refuse overwriting reused output')
      else:
       try:os.link(source_file,dst)
       except OSError:shutil.copy2(source_file,dst)
     current={**r,'SQL_path':str((target/'eplusout.sql').relative_to(OUT)),
        'physical_execution':'verified_exact_reuse','source_stage':old.name,
        'source_run_receipt_sha256':sha(receipt),'source_SQL_sha256':r['SQL_sha256'],
        'new_engine_launch':False,'current_ledger_sha256':b['signal_ledger_sha256'],
        'current_world_sha256':c['world_sha256'],'current_pair_sha256':c['pair_sha256']}
     save(target/'RUN_RECORD.json',current);reused[k]=current
     evidence.append({'household_id':c['household_id'],'round_index':c['round_index'],'variant':c['variant'],'arm':side,
       'signature':actual,'SQL_sha256':r['SQL_sha256'],'source_run_receipt_sha256':sha(receipt),
       'current_ledger_sha256':b['signal_ledger_sha256'],'current_world_sha256':c['world_sha256'],'current_pair_sha256':c['pair_sha256']})
    records.append(reused[k])
  check_run_coverage(rows,records)
  save(OUT/f'EP_{scope}_REVIEW.json',{'requested':len(records),'completed':len(records),'failed':0,'records':records,
    'new_engine_launches':0,'exact_reused_records':len(records),'source_stage':old.name,'other950_executed':False,'human_answers':0})
 require_reviewed_ep('original50')
 save(OUT/'RESULT_REUSE_REVIEW.json',{'status':'pass','unique_physical_runs':len(reused),'new_engine_launches':0,
    'source_stage':old.name,'records':evidence,'original50_only':True,'SQL_reused_acceptance_not_reused':True,
    'current_service_acceptance_pending_new_readback':True,'human_answers':0})
 print({'unique_verified_physical_runs':len(reused),'new_engine_launches':0,'next':'readback current ledgers'},flush=True)
if __name__=='__main__':main()
