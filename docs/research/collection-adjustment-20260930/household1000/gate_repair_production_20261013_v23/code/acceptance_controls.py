"""School-only regression of the three acceptance defects; never launches EP."""
import copy,contextlib,io,shutil,tempfile,subprocess,collections
import concurrent.futures
from common import *
import ep_gate as gate
import physics
class ImmediatePool:
    def __init__(self,**kw):
        if kw.get('initializer'):kw['initializer'](*kw.get('initargs',()))
    def __enter__(self):return self
    def __exit__(self,*a):pass
    def submit(self,fn,*args):
        f=concurrent.futures.Future()
        try:f.set_result(fn(*args))
        except Exception as e:f.set_exception(e)
        return f
def main():
    school_guard();results=[]
    def test(name,fn,should_reject=True):
        error=None
        try:fn()
        except Exception as e:error=str(e)
        ok=(error is not None)==should_reject
        results.append({'control':name,'expected_rejection':should_reject,'rejected':error is not None,'passed':ok,'error':error})
        if not ok:raise RuntimeError('Acceptance regression failed: '+name)
    save(OUT/'ACCEPTANCE_NEGATIVE_CONTROLS.json',{'status':'running','human_answers':0,'EP_runs':0})
    original=gate.OUT
    with tempfile.TemporaryDirectory(prefix='eb-v23-acceptance-') as td:
        f=Path(td)/'fixture';f.mkdir()
        # Independent disposable copy. Production worlds and prior failures stay intact.
        for name in gate.DATA_DIRS+['code']:
            subprocess.run(['cp','-a','--reflink=auto',str(OUT/name),str(f/name)],check=True)
        for p in OUT.glob('*.json'):shutil.copy2(p,f/p.name)
        for p in OUT.glob('*.md'):shutil.copy2(p,f/p.name)
        gate.OUT=f
        signature,files=gate.input_signature()
        save(f/'PRE_EP_SCIENTIFIC_REVIEW.json',{'input_signature':signature,'purpose_recheck_passed':True,
            'reference_production_accepted':True,'critical_reference_findings':[],'allowed_EP_scopes':['original50'],
            'full1000_EP_allowed':False,'national_behavior_validated':False,'formal_benchmark_release':False,
            'synthetic_fixture_only':True})
        selection=read(f/'SELECTION1000.json')['records'];h=selection[0];c=read(f/'COMPILED50.json')['records'][0]
        targets={'world_changed':h['world_path'],'pair_changed':h['rounds'][0]['pair_path'],
          'ledger_changed':c['A']['signal_ledger_path'],'actor_changed':read(f/'ACTOR_BINDINGS.json')['records'][0]['actor_path'],
          'consumer_changed':read(f/'CONSUMER_BINDINGS.json')['records'][0]['consumer_path'],
          'frontend_HTML_changed':str(next((f/'frontend_release/households').glob('*/index.html')).relative_to(f)),
          'nested_code_changed':'code/base_v19/activity_model.py'}
        for name,rel in targets.items():
            path=f/rel;before=path.read_bytes()
            if name=='world_changed':
                changed=read(path);changed['members'][0]['age_years']+=1;save(path,changed)
            else:path.write_bytes(before+b'\n')
            test(name,lambda:gate.require_reviewed_ep('original50'))
            path.write_bytes(before)
        test('full1000_scope',lambda:gate.require_reviewed_ep('full1000'))
        # The real scoped readback function is exercised with synthetic SQL
        # summaries; no engine call or real actor record is made.
        physics.OUT=f;rows=physics.scoped_rows('all');allruns=[]
        for r in rows:
            for side in ('A','B'):
                allruns.append({'household_id':r['household_id'],'round_index':r['round_index'],'variant':r['variant'],
                    'arm':side,'date':r['date'],'runtime_pass':True,'returncode':0,'severe_fatal':[],
                    'SQL_path':'synthetic-unused.sql','SQL_sha256':'synthetic-not-an-engine-output',
                    'signature':{'IDF_sha256':r[side]['IDF_sha256'],'weather_sha256':r['weather']['sha256'],'engine_sha256':sha(physics.ENGINE)},
                    'warnings':{'psychrometric_domain':False,'DX_airflow_domain':False,'AHRI_curve_domain':False}})
        test('missing_all_runs',lambda:physics.check_run_coverage(rows,[]))
        test('missing_one_side',lambda:physics.check_run_coverage(rows,allruns[:-1]))
        test('duplicate_run',lambda:physics.check_run_coverage(rows,allruns+[allruns[0]]))
        bad=copy.deepcopy(allruns);bad[0]['household_id']='not-in-original50'
        test('outside_original50',lambda:physics.check_run_coverage(rows,bad))
        bad=copy.deepcopy(allruns);bad[0]['runtime_pass']=False
        test('failed_engine_receipt',lambda:physics.check_run_coverage(rows,bad))
        bad=copy.deepcopy(allruns);bad[0]['signature']['IDF_sha256']='wrong'
        test('wrong_IDF_receipt',lambda:physics.check_run_coverage(rows,bad))
        bad=copy.deepcopy(allruns);bad[0]['signature']['engine_sha256']='wrong'
        test('wrong_engine_receipt',lambda:physics.check_run_coverage(rows,bad))
        bad=copy.deepcopy(allruns);bad[0]['date']='2025-01-01'
        test('changed_date_receipt',lambda:physics.check_run_coverage(rows,bad))
        real_require=gate.require_reviewed_ep;gate.require_reviewed_ep=lambda *_:{'synthetic_fixture_only':True}
        real_pool=physics.concurrent.futures.ProcessPoolExecutor;real_readback=physics.pair_readback
        physics.concurrent.futures.ProcessPoolExecutor=ImmediatePool
        condition={'side':None,'kind':None}
        def fake(c,runs):
            d={'household_id':c['household_id'],'round_index':c['round_index'],'variant':c['variant'],
                'pre_notice_max_difference':0.,'meter_residual_J':{'A':0.,'B':0.},'spatial_SQL_max_difference':{'A':0.,'B':0.},'services':{}}
            for s in ('A','B'):
                fail=s==condition['side'] and c is rows[0]
                d['services'][s]={'hot_water':[],'EV':{'goals':[],'trips':[]},
                  'AC_curve_boundary':{'status':'within_original_boundary'},
                  'power_limits':{'circuit_exceeded':['AC'] if fail and condition['kind']=='circuit' else [],
                                  'home_exceeded':bool(fail and condition['kind']=='home')}}
            return d
        physics.pair_readback=fake
        def exercise():
            with contextlib.redirect_stdout(io.StringIO()):physics.read_all('all',1)
        try:
            save(f/'EP_all_REVIEW.json',{'records':[]});test('empty_readback_rejected',exercise)
            save(f/'EP_all_REVIEW.json',{'records':allruns})
            # Scoped rows are reconstructed by read_all; compare stable key.
            firstkey=physics.row_key(rows[0])
            previous=fake
            def keyed_fake(c,runs):
                d=previous(c,runs)
                if physics.row_key(c)==firstkey and condition['side']:
                    p=d['services'][condition['side']]['power_limits']
                    p['home_exceeded']=condition['kind']=='home'
                    p['circuit_exceeded']=['AC'] if condition['kind']=='circuit' else []
                    if condition['kind']=='reserve':d['services'][condition['side']]['EV']['trips']=[{'trip_departed':True,'reference_reserve_pass':False}]
                return d
            physics.pair_readback=keyed_fake
            for side,kind in [('A','circuit'),('A','home'),('A','reserve'),('B','circuit'),('B','home'),('B','reserve')]:
                condition.update(side=side,kind=kind)
                test(side+'_'+kind+'_readback',exercise,should_reject=side=='A')
        finally:
            gate.require_reviewed_ep=real_require;physics.concurrent.futures.ProcessPoolExecutor=real_pool;physics.pair_readback=real_readback
            physics.OUT=original;gate.OUT=original
    report={'schema':'eb.acceptance_negative_controls.v23','status':'pass','date':'2026-10-13','records':results,
        'tested_code_sha256':{n:sha(OUT/'code'/n) for n in ['ep_gate.py','physics.py','acceptance_controls.py']},
        'controls':len(results),'all_expected_behaviors_verified':all(r['passed'] for r in results),
        'worlds_or_pairs_regenerated':False,'production_input_files_changed':False,
        'isolated_fixture_certificates_not_production_reviews':True,'human_answers':0,'EP_runs':0,
        'bad_B_power_boundaries_retained_without_human_rejection_labels':True}
    save(OUT/'ACCEPTANCE_NEGATIVE_CONTROLS.json',report);print({k:v for k,v in report.items() if k!='records'},flush=True)
if __name__=='__main__':main()
