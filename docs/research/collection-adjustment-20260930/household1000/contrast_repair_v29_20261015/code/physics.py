"""Bounded original50 compilation, execution and independent SQL sensitivity audit."""
import argparse,collections,concurrent.futures,datetime as dt,os,re,sqlite3,subprocess,time,math
from common import *
from plans import make_A
ENGINE=Path('/home/hku_user3/energybridge-compute/EnergyPlus-24-1-0/energyplus')
VARIANTS={'base7':(7,'fixed15'),'prior14':(14,'fixed15'),'seasonal7':(7,'seasonal'),'seasonal14':(14,'seasonal')}
ENERGY_NAMES={'Lights Electricity Energy','Electric Equipment Electricity Energy','Cooling Coil Electricity Energy','Fan Electricity Energy','Water Heater Electricity Energy'}
A_HARD_FAILURES=('A_hot_water_target_failures','A_EV_access_target_failures','A_EV_undelivered_trips','A_EV_reserve_failures','A_circuit_exceeded_pairs','A_home_exceeded_pairs')
def set_readback_lease(lease):
    global _READBACK_LEASE
    _READBACK_LEASE=lease
def row_key(r):return (r['household_id'],r['round_index'],r['variant'])
def scoped_rows(scope):
    """Expected coverage comes from the frozen original selection, never from available runs."""
    selection=read(OUT/'SELECTION50.json')['records'];original=read(PILOT/'SELECTION50.json')['records']
    dates={(h['household_id'],c['round_index']):c['date'] for h in original for c in h['rounds']}
    current={(h['household_id'],c['round_index']):c['date'] for h in selection for c in h['rounds']}
    if len(selection)!=50 or len(dates)!=500 or current!=dates:raise RuntimeError('Original50/date coverage changed')
    summer={h['household_id']:next(c['round_index'] for c in h['rounds'] if 7<=dt.date.fromisoformat(c['date']).month<=9) for h in original}
    expected={(hid,i,'base7'):date for (hid,i),date in dates.items()}
    expected.update({(hid,i,v):dates[hid,i] for hid,i in summer.items() for v in VARIANTS if v!='base7'})
    rows=read(OUT/'COMPILED50.json')['records'];keys=[row_key(r) for r in rows]
    if len(keys)!=len(set(keys)) or set(keys)!=set(expected) or any(r['date']!=expected[row_key(r)] for r in rows):
        raise RuntimeError('Compiled650 coverage missing,duplicated,changed or outside original50')
    if scope=='all':wanted={k for k in expected if k[2]=='base7'}
    elif scope=='sensitivity':wanted={k for k in expected if k[1]==summer[k[0]]}
    elif scope=='first':wanted={('ordinary-v6-0204',summer['ordinary-v6-0204'],'base7')}
    elif scope=='model_form':
        extra=read(OUT/'MODEL_FORM_INPUTS.json')['records'];ek=[row_key(r) for r in extra]
        wanted={(hid,i,'temperature_flat7') for hid,i in summer.items()}
        if len(ek)!=50 or len(set(ek))!=50 or set(ek)!=wanted or any(r['date']!=dates[r['household_id'],r['round_index']] for r in extra):
            raise RuntimeError('Model-form coverage changed from fixed original50 summer')
        return sorted(extra,key=row_key)
    else:raise RuntimeError('Unknown scope')
    return sorted((r for r in rows if row_key(r) in wanted),key=row_key)
def check_run_coverage(rows,runs):
    expected={(*row_key(c),s):c for c in rows for s in ('A','B')};actual={}
    engine=read(OUT/'EXTERNAL_INPUT_LOCK.json')['engine_sha256']
    for r in runs:
        k=(r['household_id'],r['round_index'],r['variant'],r['arm'])
        if k in actual:raise RuntimeError('Duplicate run record: '+str(k))
        if k not in expected:raise RuntimeError('Run outside expected fixed scope: '+str(k))
        c=expected[k];b=c[r['arm']]
        if not r.get('runtime_pass') or r.get('returncode')!=0 or r.get('severe_fatal') or not r.get('SQL_path') or not r.get('SQL_sha256'):
            raise RuntimeError('Failed or incomplete run receipt: '+str(k))
        if r['date']!=c['date'] or r['signature']['IDF_sha256']!=b['IDF_sha256'] or r['signature']['weather_sha256']!=c['weather']['sha256'] or r['signature'].get('engine_sha256')!=engine:
            raise RuntimeError('Run input identity changed: '+str(k))
        actual[k]=r
    if not expected or set(actual)!=set(expected):raise RuntimeError('Missing expected runs: '+str(sorted(set(expected)-set(actual))[:8]))
    return actual
def static_gate():
    assert read(OUT/'INPUT_AUDIT.json')['failures']==[]
    assert read(OUT/'CALENDAR_AUDIT.json')['failures']==[]
    assert read(OUT/'IDF_INPUT_AUDIT.json')['failures']==[]
    assert read(OUT/'MECHANISM_NEGATIVE_CONTROLS.json')['status']=='pass'
    assert read(OUT/'STATIC_REVIEW.json')['pairs']==500
    ids={r['household_id'] for r in read(PILOT/'SELECTION50.json')['records']}
    selection=read(OUT/'SELECTION50.json');assert {r['household_id'] for r in selection['records']}==ids and len(ids)==50
    return selection
def compile_job(job):
    from compile_inputs import compile_one
    h,c,variant=job;w=read(OUT/h['world_path']);p=read(OUT/c['pair_path']);history,inlet=VARIANTS[variant]
    background=parse(V12/'background_idfs'/f'{h["household_id"]}.idf')
    r={s:compile_one(w,p,s,background,prior_days=history,inlet=inlet,variant=variant,weather_path=h['weather']['path']) for s in ('A','B')}
    from curve_observer import attach
    for binding in r.values():
        native=OUT/binding['IDF_path'];rows=parse(native);binding['native_IDF_sha256']=sha(native);binding['native_IDF_path']=binding['IDF_path'];binding['curve_observation_meta']=attach(rows)
        path=OUT/'idfs'/('observed_'+variant)/h['household_id']/native.name;path.parent.mkdir(parents=True,exist_ok=True);atomic_text(path,dump(rows));binding['IDF_path']=str(path.relative_to(OUT));binding['IDF_sha256']=sha(path)
    return {'household_id':h['household_id'],'round_index':c['round_index'],'date':c['date'],'variant':variant,
            'world_path':h['world_path'],'world_sha256':h['world_sha256'],'pair_path':c['pair_path'],
            'pair_sha256':c['pair_sha256'],'weather':h['weather'],**r}
def compile_all(workers):
    sel=static_gate();jobs=[(h,c,'base7') for h in sel['records'] for c in h['rounds']]
    for h in sel['records']:
        c=next(c for c in h['rounds'] if 7<=dt.date.fromisoformat(c['date']).month<=9)
        jobs += [(h,c,v) for v in VARIANTS if v!='base7']
    rows=[]
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
        for r in pool.map(compile_job,jobs):
            rows.append(r)
            if len(rows)%100==0:print({'compiled_pairs':len(rows),'planned_pairs':len(jobs)},flush=True)
    save(OUT/'COMPILED50.json',{'households':50,'pairs':len(rows),'IDF_count':len(rows)*2,'records':rows,
        'sensitivity_selection':'first original chronological quarter3 date per original50, fixed by input dates; 2x2 prior/inlet across A/B',
        'other950_EP_authorized':False})
    print({'compiled_pairs':len(rows),'IDFs':len(rows)*2},flush=True)
def run_job(job,lease=None):
    from ep_gate import require_reviewed_ep,guard_job
    if lease is None:lease=require_reviewed_ep('original50')
    c,side=job
    guard_job(c,side,lease)
    assert c['household_id'] in lease['allowed_households'],'EP hold: household outside reviewed cohort'
    v=c['variant'];hid=c['household_id'];i=c['round_index'];b=c[side]
    path=OUT/b['IDF_path'];weather=Path(c['weather']['path']);out=OUT/'runs'/v/hid/f'{i:02d}_{side}';out.mkdir(parents=True,exist_ok=True)
    signature={'IDF_sha256':sha(path),'weather_sha256':sha(weather),'engine_sha256':sha(ENGINE)}
    assert signature['IDF_sha256']==b['IDF_sha256'] and signature['weather_sha256']==c['weather']['sha256']
    receipt=out/'RUN_RECORD.json'
    if receipt.exists():
        old=read(receipt)
        if old.get('signature')==signature and old['runtime_pass'] and sha(out/'eplusout.sql')==old['SQL_sha256']:return old
        archive=OUT/'development/superseded_runs'/old['signature']['IDF_sha256']/v/hid/out.name
        archive.parent.mkdir(parents=True,exist_ok=True)
        if archive.exists():raise RuntimeError('Do not overwrite superseded evidence')
        out.rename(archive);out.mkdir(parents=True)
        save(archive/'RELOCATION.json',{'old_run_path':str(out.relative_to(OUT)),'archived_run_path':str(archive.relative_to(OUT)),
                                     'old_SQL_sha256':old.get('SQL_sha256'),'reason':'versioned input repair; original output preserved'})
    t=time.monotonic();env={**os.environ,'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1'}
    proc=subprocess.run([str(ENGINE),'-w',str(weather),'-d',str(out),str(path)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,env=env,timeout=900)
    (out/'engine.log').write_text(proc.stdout);err=(out/'eplusout.err').read_text(errors='replace') if (out/'eplusout.err').exists() else proc.stdout
    severe=[s.strip() for s in err.splitlines() if re.search(r'\*\*\s*(Severe|Fatal)\s*\*\*',s)]
    ok=proc.returncode==0 and not severe and (out/'eplusout.sql').is_file()
    r={'household_id':hid,'round_index':i,'date':c['date'],'variant':v,'arm':side,'runtime_pass':ok,'returncode':proc.returncode,
       'severe_fatal':severe,'signature':signature,'warning_markers':len(re.findall(r'\*\*\s*Warning\s*\*\*',err)),
       'warnings':{'psychrometric_domain':'(PsyPsatFnTemp)' in err,'DX_airflow_domain':'Rated air volume flow rate per watt' in err,
                   'AHRI_curve_domain':'not at the AHRI test condition' in err},
       'SQL_path':str((out/'eplusout.sql').relative_to(OUT)) if ok else None,'SQL_sha256':sha(out/'eplusout.sql') if ok else None,
       'elapsed_seconds':time.monotonic()-t}
    save(receipt,r);return r
def run_all(workers,scope):
    from ep_gate import require_reviewed_ep
    static_gate();lease=require_reviewed_ep('original50');rows=scoped_rows(scope)
    outputs=[];t=time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for r in pool.map(lambda j:run_job(j,lease),[(c,s) for c in rows for s in ('A','B')]):
            outputs.append(r)
            if len(outputs)%20==0 or not r['runtime_pass']:print({'finished':len(outputs),'planned':len(rows)*2,'failed':sum(not x['runtime_pass'] for x in outputs),'seconds':round(time.monotonic()-t)},flush=True)
    require_reviewed_ep('original50');check_run_coverage(rows,outputs)
    save(OUT/f'EP_{scope}_REVIEW.json',{'requested':len(rows)*2,'completed':len(outputs),'failed':sum(not r['runtime_pass'] for r in outputs),
         'records':outputs,'other950_executed':False,'human_answers':0})
    if any(not r['runtime_pass'] for r in outputs):raise RuntimeError('EP failed; inspect run receipts')
def frame(r):
    path=OUT/r['SQL_path'];assert sha(path)==r['SQL_sha256'];db=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True)
    data=db.execute('SELECT t.SimulationDays,t.Hour,t.Minute,t.Interval,d.KeyValue,d.Name,r.Value FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE t.WarmupFlag=0 AND d.ReportingFrequency="Zone Timestep" ORDER BY t.TimeIndex').fetchall()
    days=db.execute('SELECT t.SimulationDays,t.Year,t.Month,t.Day,count(DISTINCT t.TimeIndex) FROM Time t JOIN ReportData r USING(TimeIndex) JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) WHERE t.WarmupFlag=0 AND d.ReportingFrequency="Zone Timestep" GROUP BY t.SimulationDays,t.Year,t.Month,t.Day ORDER BY t.SimulationDays').fetchall();db.close();f=collections.defaultdict(dict)
    for day,hour,minute,interval,key,name,value in data:
        assert interval==10 and math.isfinite(value)
        index=round(((day-1)*1440+hour*60+minute)/10)-1
        f[index][name,(key or '').upper()]=value
    return dict(f),days
def structural_zero_people(frame_data,ledger,idf_rows):
    """Absent People output means zero only with both independent input proofs.

    Never impute an occupied room's missing SQL variable or other quantities.
    EnergyPlus omits a zone count when there is no People component there.
    """
    inserted=[]
    actual_people_zones={row[2].upper()for row in idf_rows if row[0]=='People'}
    spatial=ledger['spatial'];n=len(frame_data)
    for rid in spatial['lighting']:
        key=('Zone People Occupant Count',rid.upper());present=[key in frame_data[i]for i in range(n)]
        if all(present):continue
        expected=[sum(by[rid][i]for by in spatial['resident_occupancy'].values())+sum(by[rid][i]for by in spatial['external_occupancy'].values())for i in range(n)]
        if any(present)or any(expected)or rid.upper()in actual_people_zones:
            raise RuntimeError('Unexplained missing occupancy SQL output: '+rid)
        for values in frame_data.values():values[key]=0.
        inserted.append(rid)
    actual_schedules={row[1].upper()for row in idf_rows if row[0].startswith('Schedule:')}
    signals=[]
    for mid,byroom in spatial['resident_occupancy'].items():
        signals.extend(('v19_person_'+mid.split('-')[-1]+'_'+rid,vs)for rid,vs in byroom.items())
    bindings=spatial.get('external_occupancy_SQL_bindings',{})
    if set(bindings)!=set(spatial['external_occupancy']):raise RuntimeError('Explicit external actor/SQL bindings missing')
    for mid,byroom in spatial['external_occupancy'].items():
        signals.extend((bindings[mid][rid],vs)for rid,vs in byroom.items())
    for name,vs in signals:
        key=('Schedule Value',name.upper());present=[key in frame_data[i]for i in range(n)]
        if all(present):continue
        if any(present)or any(vs)or name.upper()in actual_schedules:
            raise RuntimeError('Unexplained missing occupancy schedule SQL output: '+name)
        for values in frame_data.values():values[key]=0.
        inserted.append('absent_zero_schedule:'+name)
    return inserted

def pair_readback(c,runs):
    from ep_gate import guard_job
    for s in ('A','B'):guard_job(c,s,_READBACK_LEASE)
    w=read(OUT/c['world_path']);p=read(OUT/c['pair_path']);assert sha(OUT/c['world_path'])==c['world_sha256'] and sha(OUT/c['pair_path'])==c['pair_sha256']
    frames={};prior=c['A']['prior_days'];base=prior*144;date=dt.date.fromisoformat(c['A']['start_date']);n=(prior+3)*144
    structural_zeros={}
    for s in ('A','B'):
        f,days=frame(runs[s]);assert set(f)==set(range(n));assert days==[(i+1,(date+dt.timedelta(days=i)).year,(date+dt.timedelta(days=i)).month,(date+dt.timedelta(days=i)).day,144) for i in range(prior+3)]
        binding=c[s];assert sha(OUT/binding['signal_ledger_path'])==binding['signal_ledger_sha256']
        structural_zeros[s]=structural_zero_people(f,read(OUT/binding['signal_ledger_path']),parse(OUT/binding['IDF_path']))
        frames[s]=f
    decision=base+p['decision_abs_min']//10
    pre=max(abs(frames['A'][i][k]-frames['B'][i][k]) for i in range(decision) for k in frames['A'][i]);assert pre<1e-5
    scopes={'living_day':(base+48,base+192),'event':(base+p['event_window_min'][0]//10,base+p['event_window_min'][1]//10),
            'living_day_and_service_tail':(base+48,base+p['service_tail_min'][1]//10)}
    out={'household_id':c['household_id'],'round_index':c['round_index'],'date':c['date'],'variant':c['variant'],'world_sha256':c['world_sha256'],
         'pair_sha256':c['pair_sha256'],'pre_notice_max_difference':pre,'structural_zero_people_without_IDF_components':structural_zeros,'energy':{},'services':{},'meter_residual_J':{},'program_residual_J':{},'pre_event_state':{},'terminal_states':{}}
    for s,f in frames.items():
        residual=max(abs(v['Electricity:Facility','']-sum(x for (name,key),x in v.items() if name in ENERGY_NAMES)) for v in f.values());assert residual<.001
        out['meter_residual_J'][s]=residual
        b=c[s];assert sha(OUT/b['signal_ledger_path'])==b['signal_ledger_sha256'];ledger=read(OUT/b['signal_ledger_path']);prog=0.
        for d in w['parameter_pack']['devices']:
            if not set(d['types'])&{'washer','dryer','dishwasher','ev'}:continue
            key=('Electric Equipment Electricity Energy',d['asset_id'].upper())
            prog=max(prog,max(abs(f[i][key]-power*600) for i,power in enumerate(ledger['signals'][d['asset_id']])))
        assert prog<.001;out['program_residual_J'][s]=prog
        spatial=ledger['spatial'];occupancy_error=0.;schedule_keys=[]
        for mid,byroom in spatial['resident_occupancy'].items():
            for rid,vs in byroom.items():
                if not any(vs):continue
                name='v19_person_'+mid.split('-')[-1]+'_'+rid
                key=('Schedule Value',name.upper());assert all(key in f[i] for i in range(n)),key
                occupancy_error=max(occupancy_error,max(abs(f[i][key]-vs[i]) for i in range(n)));schedule_keys.append(key)
        for mid,byroom in spatial['external_occupancy'].items():
            for rid,vs in byroom.items():
                key=('Schedule Value',spatial['external_occupancy_SQL_bindings'][mid][rid].upper())
                assert all(key in f[i]for i in range(n)),key
                occupancy_error=max(occupancy_error,max(abs(f[i][key]-vs[i])for i in range(n)))
        for rid,vs in spatial['lighting'].items():
            key=('Schedule Value',('v19_light_clock_'+rid).upper());assert all(key in f[i] for i in range(n)),key
            occupancy_error=max(occupancy_error,max(abs(f[i][key]-vs[i]) for i in range(n)))
        for rid in spatial['lighting']:
            expected=[sum(byroom[rid][i] for byroom in spatial['resident_occupancy'].values())+sum(byroom[rid][i] for byroom in spatial['external_occupancy'].values()) for i in range(n)]
            key=('Zone People Occupant Count',rid.upper())
            if any(expected):assert all(key in f[i] for i in range(n)),key
            occupancy_error=max(occupancy_error,max(abs(f[i].get(key,0.)-expected[i]) for i in range(n)))
        assert occupancy_error<1e-8
        out.setdefault('spatial_SQL_max_difference',{})[s]=occupancy_error
        out['spatial_count_source']='actual Zone People Occupant Count plus actual occupancy/light Schedule Value, compared with resident and visitor ledger'
        for label,(a,bound) in scopes.items():out['energy'].setdefault(label,{})[s]=sum(f[i]['Electricity:Facility',''] for i in range(a,bound))/3.6e6
        services={'program_and_handling_constraints':p['constraint_assessment']['constraint_flags'][s],
            'program_execution':[x for x in ledger['execution']['program_services'] if x['need_id'] in {n['need_id'] for n in p['needs_A']}],
            'operation_results':[x for x in ledger['execution']['operations'] if x['need_id'] in {n['need_id'] for n in p['needs_A']}],
            'post_operation_care_gaps':ledger['post_operation_care_gaps']}
        if any('water_heater' in d['types'] for d in w['parameter_pack']['devices']):
            vk=('Water Use Equipment Total Volume','SHOWERS_V16');tk=('Water Use Equipment Mixed Water Temperature','SHOWERS_V16');checks=[]
            for need in p['needs_A']:
                if need['kind']!='water_heater':continue
                a=base+need['release_min']//10;b=base+need['deadline_min']//10
                actual=sum(f[i][vk] for i in range(a,b))*1000;temp=min(f[i][tk] for i in range(a,b));assert abs(actual-need['quantity'])<.001
                checks.append({'need_id':need['need_id'],'requested_L':need['quantity'],'delivered_L':actual,'minimum_mixed_C':temp,'target_C':need['target_C'],'temperature_pass':temp>=need['target_C']-.5})
            services['hot_water']=checks
        ev=next((d for d in w['parameter_pack']['devices'] if 'ev' in d['types']),None)
        if ev:
            tripmap={n['absolute_min']//10:n for n in ledger['EV_diagnostics']}
            fullneeds,_,_,_=make_A(w,date,days=prior+3);planned_trips={n['trip_departure_min']//10:n for n in fullneeds if n['kind']=='ev'}
            cfg=ev['parameters'];soc=w['reference_initial_states']['EV_SOC'];before={};trips=[]
            key=('Electric Equipment Electricity Energy',ev['asset_id'].upper())
            for i in range(n):
                before[i]=soc
                if i in tripmap:
                    req=tripmap[i]['traction_delivered_kWh'];short=tripmap[i]['trip_energy_shortfall_kWh'];after=soc-req/cfg['capacity_kwh']
                    trips.append({'minute_relative_to_target':(i-base)*10,'required_kWh':planned_trips[i]['quantity'],'traction_delivered_kWh':req,'SOC_before':soc,'SOC_after':after,'shortfall_kWh':short,
                                  'trip_departed':tripmap[i]['trip_departed'],'departure_connection_conflict':tripmap[i]['departure_connection_conflict'],
                                  'reference_reserve_soc':cfg['min_soc'],'reference_reserve_pass':after>=cfg['min_soc']-1e-6});soc=after
                soc+=f[i][key]/3.6e6*cfg.get('efficiency',.92)/cfg['capacity_kwh'];assert -.00001<=soc<=1.00001
                assert abs(soc-ledger['EV_SOC_after_step'][ev['asset_id']][i])<1e-8
            goals=[]
            for need in p['needs_A']:
                if need['kind']!='ev':continue
                actual=before[base+need['deadline_min']//10]
                goals.append({'need_id':need['need_id'],'deadline_min':need['deadline_min'],'target_SOC':need['required_departure_soc'],'actual_SOC_before_any_trip_debit':actual,
                              'target_pass':actual>=need['required_departure_soc']-1e-6,'next_access_is_actual_trip':need['next_access_is_actual_trip']})
            services['EV']={'goals':goals,'trips':[t for t in trips if 0<=t['minute_relative_to_target']<p['service_tail_min'][1]],'battery_model':'analytic balance from actual EP charging meter and realized given trips; connection/SOC failure is explicit; alternative transport unknown'}
            out.setdefault('pre_event_EV_SOC',{})[s]=before[decision]
        temps=[]
        for d in w['parameter_pack']['devices']:
            if 'ac' not in d['types']:continue
            vals=[f[i]['Zone Mean Air Temperature',d['room_id'].upper()] for i in range(base+48,base+192)]
            temps.append({'room_id':d['room_id'],'min_C':min(vals),'max_C':max(vals)})
        circuit_peaks={k:0. for k in w['parameter_pack']['circuit_limit_kw']};home_peak=0.;nominal_exceedance=collections.Counter()
        for ix in range(base+48,base+p['service_tail_min'][1]//10):
            circuit=collections.defaultdict(float);ev_energy=0.
            for di,d in enumerate(w['parameter_pack']['devices']):
                if 'ac' in d['types']:
                    energy=f[ix]['Cooling Coil Electricity Energy',('v16_AC_'+str(di)+'_coil').upper()]+f[ix]['Fan Electricity Energy',('v16_AC_'+str(di)+'_fan').upper()]
                elif 'water_heater' in d['types']:energy=sum(v for (name,key),v in f[ix].items() if name=='Water Heater Electricity Energy')
                else:energy=f[ix]['Electric Equipment Electricity Energy',d['asset_id'].upper()]
                circuit[d['circuit']]+=energy/600000.
                if 'ev' in d['types']:ev_energy+=energy
                if energy/600000.>d['max_electric_kw']+1e-6:nominal_exceedance[d['asset_id']]+=1
            for name,kw in circuit.items():circuit_peaks[name]=max(circuit_peaks[name],kw)
            home_peak=max(home_peak,(f[ix]['Electricity:Facility','']-ev_energy)/600000.)
        services['power_limits']={'circuit_peak_kW':circuit_peaks,'given_circuit_limit_kW':w['parameter_pack']['circuit_limit_kw'],
            'circuit_exceeded':[k for k,v in circuit_peaks.items() if v>w['parameter_pack']['circuit_limit_kw'][k]+1e-6],
            'residential_peak_excluding_dedicated_EV_kW':home_peak,'given_home_limit_kW':w['parameter_pack']['home_service_limit_kw'],
            'home_exceeded':home_peak>w['parameter_pack']['home_service_limit_kw']+1e-6,
            'rated_point_metadata_exceeded_steps':dict(nominal_exceedance),'not_wiring_certification':True}
        from curve_observer import read_actual
        if c[s].get('curve_observation_meta'):services['AC_curve_boundary']=read_actual(OUT/runs[s]['SQL_path'],c[s]['curve_observation_meta'])
        else:services['AC_curve_boundary']={'status':'raw_curve_inputs_not_reported','manufacturer_or_fitted_domain_validated':False}
        services['room_air_by_scope']={}
        for label,(a,z) in scopes.items():
            services['room_air_by_scope'][label]=[{'room_id':d['room_id'],
                'min_C':min(f[i]['Zone Mean Air Temperature',d['room_id'].upper()] for i in range(a,z)),
                'max_C':max(f[i]['Zone Mean Air Temperature',d['room_id'].upper()] for i in range(a,z))}
                for d in [{'room_id':r['room_id']} for r in w['layout']['rooms'] if w['household_id'] in r['using_household_ids']]]
        services['room_air']=temps;services['personal_comfort_pass']=None;out['services'][s]=services
        out['pre_event_state'][s]={name+'|'+key:v for (name,key),v in f[decision-1].items() if name in ('Zone Mean Air Temperature','Water Heater Tank Temperature')}
        t=base+p['service_tail_min'][1]//10-1
        out['terminal_states'][s]={name+'|'+key:v for (name,key),v in f[t].items() if name in ('Zone Mean Air Temperature','Water Heater Tank Temperature')}
        if ev:out['terminal_states'][s]['EV_SOC']=ledger['EV_SOC_after_step'][ev['asset_id']][t]
    for e in out['energy'].values():e['A_minus_B_kWh']=e['A']-e['B']
    out['terminal_state_B_minus_A']={k:out['terminal_states']['B'][k]-v for k,v in out['terminal_states']['A'].items()}
    out['energy_comparison_scope']={'finite_window_only':True,'same_terminal_state_forced':False,'equal_service_net_saving_claim':False,
        'reason':'tail is a bounded observation of requested follow-up services; residual storage and unmet service remain explicit'}
    if ev:
        delta=out['terminal_state_B_minus_A']['EV_SOC']*ev['parameters']['capacity_kwh']
        out['terminal_EV_storage']={'B_minus_A_kWh':delta,'B_additional_grid_replenishment_to_A_if_negative_kWh':max(0.,-delta)/ev['parameters'].get('efficiency',.92),
            'replenishment_is_analytic_reference_not_simulated_recovery':True}
    save(OUT/'readback'/c['variant']/c['household_id']/f'{c["round_index"]:02d}.json',out)
    return out
def read_all(scope,workers):
    from ep_gate import require_reviewed_ep
    global _READBACK_LEASE
    _READBACK_LEASE=require_reviewed_ep('original50')
    rows=scoped_rows(scope);runs=read(OUT/f'EP_{scope}_REVIEW.json')['records'];index=check_run_coverage(rows,runs)
    jobs=[(c,{s:index[(c['household_id'],c['round_index'],c['variant'],s)] for s in ('A','B')}) for c in rows]
    results=[];fail=[]
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers,initializer=set_readback_lease,initargs=(_READBACK_LEASE,)) as pool:
        fs={pool.submit(pair_readback,*j):j[0] for j in jobs}
        for f in concurrent.futures.as_completed(fs):
            try:results.append(f.result())
            except Exception as e:c=fs[f];fail.append({'household_id':c['household_id'],'round_index':c['round_index'],'variant':c['variant'],'error':repr(e)})
    report={'requested_pairs':len(jobs),'checked_pairs':len(results),'failures':fail,
            'maximum_pre_notice_difference':max((r['pre_notice_max_difference'] for r in results),default=None),
            'maximum_meter_residual_J':max((max(r['meter_residual_J'].values()) for r in results),default=None),
            'warning_categories':{k:sum(r['warnings'][k] for r in runs) for k in ('psychrometric_domain','DX_airflow_domain','AHRI_curve_domain')},
            'A_hot_water_target_failures':sum(not x['temperature_pass'] for r in results for x in r['services']['A'].get('hot_water',[])),
            'A_EV_access_target_failures':sum(not x['target_pass'] for r in results for x in r['services']['A'].get('EV',{}).get('goals',[])),
            'A_EV_undelivered_trips':sum(not x['trip_departed'] for r in results for x in r['services']['A'].get('EV',{}).get('trips',[])),
            'A_EV_reserve_failures':sum(not x['reference_reserve_pass'] for r in results for x in r['services']['A'].get('EV',{}).get('trips',[])),
            'B_EV_reserve_failures':sum(not x['reference_reserve_pass'] for r in results for x in r['services']['B'].get('EV',{}).get('trips',[])),
            'B_hot_water_target_failures':sum(not x['temperature_pass'] for r in results for x in r['services']['B'].get('hot_water',[])),
            'B_EV_access_target_failures':sum(not x['target_pass'] for r in results for x in r['services']['B'].get('EV',{}).get('goals',[])),
            'AC_sides_with_bound_clipping':sum(r['services'][s]['AC_curve_boundary']['status']=='original_boundary_used' for r in results for s in ('A','B')),
            'physical_calibration':False,'human_answers':0,'maximum_spatial_SQL_difference':max((max(r['spatial_SQL_max_difference'].values()) for r in results),default=None),
            'A_circuit_exceeded_pairs':sum(bool(r['services']['A']['power_limits']['circuit_exceeded']) for r in results),'A_home_exceeded_pairs':sum(r['services']['A']['power_limits']['home_exceeded'] for r in results),
            'B_circuit_exceeded_pairs':sum(bool(r['services']['B']['power_limits']['circuit_exceeded']) for r in results),'B_home_exceeded_pairs':sum(r['services']['B']['power_limits']['home_exceeded'] for r in results)}
    if scope=='sensitivity' and not fail:
        by=collections.defaultdict(dict)
        for r in results:by[(r['household_id'],r['round_index'])][r['variant']]=r
        diffs=[]
        for key,variants in by.items():
            assert set(variants)==set(VARIANTS)
            for a,b,name in [('base7','prior14','7_vs_14_fixed15'),('seasonal7','seasonal14','7_vs_14_seasonal'),('base7','seasonal7','fixed15_vs_seasonal_prior7')]:
                diffs.append({'household_id':key[0],'round_index':key[1],'comparison':name,'living_day_A_energy_difference_kWh':variants[b]['energy']['living_day']['A']-variants[a]['energy']['living_day']['A'],
                              'A_minus_B_energy_difference_kWh':variants[b]['energy']['living_day']['A_minus_B_kWh']-variants[a]['energy']['living_day']['A_minus_B_kWh']})
        report['sensitivity']={'households':len(by),'comparisons':diffs,'maximum_absolute_A_minus_B_energy_difference_kWh':max(abs(d['A_minus_B_energy_difference_kWh']) for d in diffs)}
    report['expected_pairs']=len(rows)
    report['acceptance_passed']=not fail and len(results)==len(rows) and not any(report[k] for k in A_HARD_FAILURES)
    report['schema']='eb.current_ledger_physical_readback.v23'
    report['input_signature_at_readback']=_READBACK_LEASE.get('review',{}).get('input_signature')
    report['readback_code_sha256']=sha(OUT/'code/physics.py')
    report['compiled_scope_sha256']=digest(sorted(rows,key=row_key))
    report['run_receipts_sha256']=digest(sorted(runs,key=lambda r:(r['household_id'],r['round_index'],r['variant'],r['arm'])))
    report['original_households_checked']=len({r['household_id'] for r in rows})
    report['complete_expected_runs_verified']=len(runs)==2*len(rows)
    report['old_acceptance_report_reused']=False
    require_reviewed_ep('original50')
    save(OUT/f'READBACK_{scope}_REVIEW.json',report);print({k:v for k,v in report.items() if k!='sensitivity'},flush=True)
    if not report['acceptance_passed']:raise RuntimeError('A given service,power or SQL audit failed:'+str(fail[:8]))
def main():
    school_guard();a=argparse.ArgumentParser();a.add_argument('phase',choices=['compile','run','readback']);a.add_argument('--scope',choices=['first','sensitivity','all','model_form'],default='first');a.add_argument('--workers',type=int,default=16);args=a.parse_args()
    if args.phase=='compile':compile_all(args.workers)
    elif args.phase=='run':run_all(args.workers,args.scope)
    else:read_all(args.scope,args.workers)
if __name__=='__main__':main()
