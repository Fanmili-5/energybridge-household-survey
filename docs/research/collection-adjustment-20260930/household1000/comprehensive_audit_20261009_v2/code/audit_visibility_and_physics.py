"""Read-only checks of complete-day visibility and stored original50 SQL.

Synthetic negative controls are evaluated in memory; no EP job, production
input modification, proposal reselection or actor answer is created.
"""
import collections,concurrent.futures,copy,hashlib,json,os,sqlite3,sys
from pathlib import Path

OUT=Path(__file__).resolve().parents[1];N=OUT.parent/'evidence_conditioned_production_20261009_v19'
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(name,value):(OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')

def visible_one(h):
    counts=collections.Counter();examples=collections.defaultdict(list)
    for r in h['rounds']:
        p=read(N/r['pair_path']);c=read(N/'consumers'/h['household_id']/f"{r['round_index']:02d}.json");days=p['dated_activity_days'];text='\n'.join(c['context']['daily_need_texts'])
        firstids={n['need_id'] for n in p['needs_A'] if n['release_min']<1440}
        future=[o for side in ('A','B') for o in p[side]['operations'] if o['need_id'] in firstids and o['start_min']>=1440]
        if future:
            counts['first_date_service_needs_future_operator_context']+=1
            if days[1]['date'] not in text:
                counts['future_operator_context_not_displayed']+=1
                if len(examples['future_operator_context_not_displayed'])<2:examples['future_operator_context_not_displayed'].append({'case_id':p['case_id'],'future_operations':future[:2],'needed_date':days[1]['date'],'needed_day_type':days[1]['day_type']})
        following=[n for n in p['needs_A'] if 1440<=n['release_min']<1920 and n['kind'] in ('washer','dishwasher','water_heater','ev')]
        if following:
            counts['next_date_needs_inside_complete_day_missing_from_need_text']+=1
            if len(examples['next_date_needs_inside_complete_day_missing_from_need_text'])<2:examples['next_date_needs_inside_complete_day_missing_from_need_text'].append({'case_id':p['case_id'],'needs':[{'kind':n['kind'],'need_id':n['need_id'],'release_min':n['release_min']} for n in following[:3]]})
        trip=days[1]['transport']
        current=[n for n in p['needs_A'] if n['kind']=='ev' and n['release_min']<1440 and n['next_access_is_actual_trip']]
        if current and trip:
            counts['next_trip_required_for_first_date_EV_decision']+=1
            if current[0]['quantity']!=trip['traction_kWh']:
                counts['next_trip_dose_differs_from_displayed_past_trip']+=1
                if len(examples['next_trip_dose_differs_from_displayed_past_trip'])<2:examples['next_trip_dose_differs_from_displayed_past_trip'].append({'case_id':p['case_id'],'displayed_past_trip_kWh':current[0]['quantity'],'next_trip_kWh':trip['traction_kWh'],'next_trip_departure_abs_min':1440+trip['departure_min']})
    return dict(counts),dict(examples)

def physical_one(h):
    w=read(N/h['world_path']);ev=next((d for d in w['parameter_pack']['devices'] if 'ev' in d['types']),None);counts=collections.Counter();examples=[];maximum={'air_C':0.,'tank_C':0.,'EV_SOC':0.}
    for r in h['rounds']:
        p=read(N/r['pair_path']);out=read(N/'readback/base7'/h['household_id']/f"{r['round_index']:02d}.json")
        assert out['pair_sha256']==r['pair_sha256'] and out['world_sha256']==h['world_sha256']
        diffs={key:abs(value-out['terminal_states']['B'][key]) for key,value in out['terminal_states']['A'].items()}
        air=max((v for k,v in diffs.items() if k.startswith('Zone Mean Air Temperature|')),default=0.);tank=max((v for k,v in diffs.items() if k.startswith('Water Heater Tank Temperature|')),default=0.)
        maximum['air_C']=max(maximum['air_C'],air);maximum['tank_C']=max(maximum['tank_C'],tank)
        counts['checked_pairs']+=1;counts['terminal_air_difference_over_0_05C']+=air>.05;counts['terminal_tank_difference_over_0_5C']+=tank>.5
        early=[o for o in p['B']['operations'] if o['kind']=='unload' and any(t['need_id'] in (o['need_id'],o['need_id']+':dry') and t['end_min']>o['start_min'] for t in p['B']['tasks'])]
        if early:
            counts['B_early_unload_actual_SQL_cases']+=1
            receipt=read(N/'runs/base7'/h['household_id']/f"{r['round_index']:02d}_B/RUN_RECORD.json")
            assert sha(N/receipt['SQL_path'])==receipt['SQL_sha256']
            db=sqlite3.connect('file:'+str(N/receipt['SQL_path'])+'?mode=ro',uri=True)
            for o in early:
                chain=[t for t in p['B']['tasks'] if t['need_id'] in (o['need_id'],o['need_id']+':dry')]
                aid=chain[0]['asset_id'];values=[x[0] for x in db.execute('SELECT r.Value FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE t.WarmupFlag=0 AND d.ReportingFrequency="Zone Timestep" AND d.Name="Electric Equipment Electricity Energy" AND upper(d.KeyValue)=? ORDER BY t.TimeIndex',(aid.upper(),))]
                index=7*144+o['start_min']//10
                if values[index]>1e-6:
                    counts['early_unload_steps_with_actual_EP_program_power']+=1
                    if len(examples)<2:examples.append({'case_id':p['case_id'],'operation':o,'program_end_min':max(t['end_min'] for t in chain),'actual_program_energy_J_during_unload':values[index]})
            db.close()
        if ev:
            cfg=ev['parameters'];SOC={}
            for side in ('A','B'):
                receipt=read(N/'runs/base7'/h['household_id']/f"{r['round_index']:02d}_{side}/RUN_RECORD.json")
                assert sha(N/receipt['SQL_path'])==receipt['SQL_sha256']
                db=sqlite3.connect('file:'+str(N/receipt['SQL_path'])+'?mode=ro',uri=True)
                values=[x[0] for x in db.execute('SELECT r.Value FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE t.WarmupFlag=0 AND d.ReportingFrequency="Zone Timestep" AND d.Name="Electric Equipment Electricity Energy" AND upper(d.KeyValue)=? ORDER BY t.TimeIndex',(ev['asset_id'].upper(),))];db.close()
                assert len(values)==10*144
                a=7*144+p['decision_abs_min']//10;b=7*144+p['service_tail_min'][1]//10
                SOC[side]=out['pre_event_EV_SOC'][side]+sum(values[a:b])/3.6e6*cfg.get('efficiency',.92)/cfg['capacity_kwh']-sum(t['required_kWh'] for t in out['services'][side]['EV']['trips'] if p['decision_abs_min']<=t['minute_relative_to_target']<p['service_tail_min'][1])/cfg['capacity_kwh']
                assert not any(t['shortfall_kWh']>1e-6 for t in out['services'][side]['EV']['trips'])
            delta=abs(SOC['A']-SOC['B']);maximum['EV_SOC']=max(maximum['EV_SOC'],delta);counts['terminal_EV_SOC_difference_over_0_01']+=delta>.01
    return dict(counts),examples,maximum

def main():
    if sys.platform!='linux':raise RuntimeError('Run audit on school Linux')
    counts=collections.Counter();examples=collections.defaultdict(list)
    with concurrent.futures.ProcessPoolExecutor(max_workers=16) as pool:
        for c,e in pool.map(visible_one,read(N/'SELECTION1000.json')['records']):
            counts.update(c)
            for k,v in e.items():examples[k].extend(v[:max(0,6-len(examples[k]))])
    save('COMPLETE_DAY_VISIBILITY_AUDIT.json',{'counts':dict(counts),'examples':dict(examples),'scope':'all10000 frozen pairs and their actual consumer text','production_modified':False,'EP_started':0})
    pc=collections.Counter();pe=[];pm={'air_C':0.,'tank_C':0.,'EV_SOC':0.}
    with concurrent.futures.ProcessPoolExecutor(max_workers=16) as pool:
        for c,e,m in pool.map(physical_one,read(N/'SELECTION50.json')['records']):
            pc.update(c);pe.extend(e[:max(0,8-len(pe))])
            for k,v in m.items():pm[k]=max(pm[k],v)
    save('STORED_SQL_SERVICE_AND_TAIL_AUDIT.json',{'counts':dict(pc),'examples':pe,'max_terminal_A_B_difference':pm,'SQL_hash_checked':True,'thresholds_are_audit_descriptions_not_recovery_acceptance_criteria':True,'EP_started':0,'source_delivery_sha256':sha(N/'DELIVERY.json')})
    # Compiler negative controls: existing published hardware and fixed needs;
    # evaluate only temporary in-memory B records, never rewrite production files.
    sys.path.insert(0,str(N/'code'));os.environ['EB_EP_ROOT']='/home/hku_user3/energybridge-compute/EnergyPlus-24-1-0'
    from compile_inputs import signals
    selected=read(N/'SELECTION50.json')['records'];program_result=ev_result=None
    for h in selected:
        w=read(N/h['world_path'])
        for r in h['rounds']:
            p=read(N/r['pair_path'])
            if program_result is None and p['B']['tasks']:
                q=copy.deepcopy(p);q['B']['operations']=[]
                base=signals(w,p,'B')[0];changed=signals(w,q,'B')[0]
                program_assets={t['asset_id'] for t in p['B']['tasks']}
                program_result={'case_id':p['case_id'],'removed_all_target_B_operations':True,'program_power_signals_unchanged':all(base[k]==changed[k] for k in program_assets),'is_synthetic_negative_control':True,'not_an_actor_answer':True}
            if ev_result is None and 'given_transport_contract' in w and p['dated_activity_days'][1]['transport']:
                ev=next(d for d in w['parameter_pack']['devices'] if 'ev' in d['types']);trip=p['dated_activity_days'][1]['transport'];a=1440+trip['departure_min'];q=copy.deepcopy(p)
                q['B']['controls']=[c for c in q['B']['controls'] if c['asset_id']!=ev['asset_id']]
                q['B']['controls'].append({'asset_id':ev['asset_id'],'kind':'ev_charge_window','start_min':a,'end_min':a+20})
                sig=signals(w,q,'B')[0][ev['asset_id']];ix=7*144+a//10
                ev_result={'case_id':p['case_id'],'charge_window_abs_min':[a,a+20],'vehicle_journey_abs_min':[a,1440+trip['arrival_min']],'charged_grid_kWh_while_vehicle_away':sum(sig[ix:ix+2])/6000,'is_synthetic_negative_control':True,'not_an_actor_answer':True}
            if program_result and ev_result:break
        if program_result and ev_result:break
    save('COMPILER_NEGATIVE_CONTROLS.json',{'program':program_result,'EV':ev_result,'production_modified':False,'EP_started':0,'interpretation':'execution gating absent; synthetic witnesses do not assert away-charging occurs in current frozen valid EV proposals'})
    print({'visibility_counts':dict(counts),'stored_SQL_counts':dict(pc),'max_terminal_difference':pm,'compiler_negative_controls':{'program':program_result,'EV':ev_result}},flush=True)
if __name__=='__main__':main()
