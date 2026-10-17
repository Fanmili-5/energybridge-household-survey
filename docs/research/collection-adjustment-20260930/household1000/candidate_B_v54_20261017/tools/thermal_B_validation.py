"""Paired native B functional readback on predeclared household/date cases.

A states are common reference runs; the same compiler replaces only the saved
B control schedule, with prior A retained. Neither samples nor B are selected
for physical success. This checks control/state linkage, not all10000 outcomes.
"""
import argparse,sys,collections,gzip,json,copy,datetime as dt
from pathlib import Path
import native_state_runner as runner
native=runner.native
DEST=native.DEST
PAIR_BINDINGS=DEST/'PAIR_BINDINGS10000.json'
SOURCE=native.STAGE
COMPILER_PATH=Path(__file__)

# Selection fixed by IDs and first source date, before seeing B success.
HIDS=[f'ordinary-v6-{i:04d}'for i in(1,6,17,45,48,51,102,145,201,250,333,400,501,600,661,700,801,850,900,950,999,1000)]
SPECIAL={'ordinary-v6-0001':'2025-03-22','ordinary-v6-0006':'2025-06-16','ordinary-v6-0017':'2025-08-21','ordinary-v6-0045':'2025-02-18','ordinary-v6-0048':'2025-04-02'}

def one(job):
    hid,date,pair_path=job;p=native.read(DEST/pair_path);a=native.A_ROWS[hid];original_read=native.read;original_dest=native.DEST
    y=copy.deepcopy(original_read(SOURCE/a['annual_A_path']))
    target=dt.date.fromisoformat(date);offset=native.origin(target)
    for day in [target+dt.timedelta(days=i)for i in(-1,0,1,2)]:
        off=native.origin(day)
        y['days'][str(day)]['controls']=[{**x,'start_min':x['start_min']+offset,'end_min':x['end_min']+offset}for x in p['B']['controls']if native.overlap((x['start_min']+offset,x['end_min']+offset),(off,off+1440))]
    def patched_read(path):return y if Path(path)==SOURCE/a['annual_A_path']else original_read(path)
    native.read=patched_read;native.DEST=DEST/'paired_thermal_validation'
    try:
        r=runner._run(hid,date)
        r['pair_sha256']=native.sha(DEST/pair_path);r['pair_path']=pair_path;r['sample_selected_before_physical_results']=True
        if r['passed']:
            folder=native.DEST/r['folder'];ip=folder/'INPUT.json';meta=native.read(ip);meta.update(target_B_pair_sha256=r['pair_sha256'],target_B_controls_sha256=native.digest(p['B']['controls']),override_compiler_sha256=native.sha(__file__),scope='paired native B control override on same A annual history;functional readback only');native.save(ip,meta);r['inputs_sha256']=native.sha(ip)
            sp=native.DEST/r['state_path'];b=native.read(sp);b.update(inputs_sha256=r['inputs_sha256'],target_B_pair_sha256=r['pair_sha256'],override_compiler_sha256=native.sha(__file__),reference_scope='paired B same native shell,HVAC,tank,people,A history;control override only;missing appliance lighting cooking gains;not complete B delivery/comfort');sp.write_bytes(gzip.compress((native.canonical(b)+'\n').encode(),mtime=0));r['state_sha256']=native.sha(sp)
            refs=native.read(DEST/'STATE_BINDINGS.json');ar=next(x for x in refs['records']if x['household_id']==hid and x['date']==date);aa=native.read(DEST/ar['state_path']);deltas=[]
            for e in p['VPP_events']:
                for device in b['asset_mapping']:
                    energies={}
                    for side,s in [('A',aa),('B',b)]:
                        m=s['asset_mapping'][device]
                        keys=[k for k in s['channels']if (m.get('tank_key')and k==m['tank_key']+'|Water Heater Electricity Energy')or('energy_keys'in m and k.split('|')[0]in m['energy_keys'].values()and 'Electricity Energy'in k)]
                        energies[side]=sum(v for k in keys for t,v in s['channels'][k]if e['start_min']<=t<e['end_min'])/3600000
                    delta=(energies['B']-energies['A'])*60/(e['end_min']-e['start_min'])
                    deltas.append({'event_id':e['event_id'],'asset_id':device,'direction_requested':e['direction'],'native_A_event_kWh':energies['A'],'native_B_event_kWh':energies['B'],'native_delta_kw':delta,'native_response_relation':'unchanged'if abs(delta)<1e-6 else'aligned'if(delta>0)==(e['direction']=='up')else'opposing','full_combination_target_met':None,'human_acceptance':None})
            r['native_event_readbacks']=deltas;r['state_path']=str((native.DEST/r['state_path']).relative_to(DEST));r['A_state_sha256']=ar['state_sha256'];r['folder']=str(folder.relative_to(DEST));native.save(folder/'RESULT.json',r)
        return r
    except Exception as e:return {'household_id':hid,'date':date,'passed':False,'error':str(e)}
    finally:native.read=original_read;native.DEST=original_dest

def compiler_equivalence():
    results=[]
    # Only memoization differs; compare complete compiler output bytes.
    for hid,date in [('ordinary-v6-0001','2025-03-22'),('ordinary-v6-0051','2025-02-01'),('ordinary-v6-1000','2025-06-01')]:
        native.resident_slot=runner._resident;folder,_=runner._build(hid,dt.date.fromisoformat(date));plain=native.sha(folder/'probe.idf')
        native.resident_slot=runner.memo_resident;folder,_=runner.memo_build(hid,dt.date.fromisoformat(date));memo=native.sha(folder/'probe.idf')
        results.append({'household_id':hid,'date':date,'same_compiled_IDF':plain==memo,'idf_sha256':plain})
    native.save(DEST/'NATIVE_COMPILER_REGRESSIONS.json',{'passed':all(x['same_compiled_IDF']for x in results),'records':results,'compiler_sha256':native.sha(native.__file__),'wrapper_sha256':native.sha(runner.__file__)})

def main():
    from concurrent.futures import ProcessPoolExecutor
    parser=argparse.ArgumentParser();parser.add_argument('--workers',type=int,default=4);args=parser.parse_args();bindings=native.read(PAIR_BINDINGS);rows={x['household_id']:x for x in bindings['records']};jobs=[]
    for hid in HIDS:
        row=rows[hid]
        dates=list(dict.fromkeys(([SPECIAL[hid]]if hid in SPECIAL else[])+[row['rounds'][0]['date'],row['rounds'][5]['date']]))
        for date in dates:jobs.append((hid,date,next(r['path']for r in row['rounds']if r['date']==date)))
    native.save(DEST/'THERMAL_VALIDATION_SAMPLE.json',{'selection':'fixed household IDs,first and sixth source dates,plus five prior-review cases;no outcome selection','jobs':jobs,'bindings_sha256':native.sha(PAIR_BINDINGS)})
    with ProcessPoolExecutor(max_workers=args.workers)as pool:results=list(pool.map(one,jobs))
    report={'passed':all(r['passed']for r in results),'cases':len(results),'records':results,'bindings_sha256':native.sha(PAIR_BINDINGS),'rules_sha256':bindings['rules_sha256'],'scope':'paired native thermal functional readback on predeclared cases;not all10000 B physical acceptance,comfort or questionnaire acceptance','full_AB_physical_acceptance':False,'compiler_sha256':native.sha(COMPILER_PATH)}
    native.save(DEST/'THERMAL_EVENT_VALIDATION.json',report);compiler_equivalence();print(native.canonical({'passed':report['passed'],'cases':len(results),'failures':[r for r in results if not r['passed']]}))
    if not report['passed']:raise SystemExit(2)
if __name__=='__main__':main()
