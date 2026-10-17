"""Read-only witnesses using frozen V19, stored SQL and actual browser export.

No production module is imported, no input is rewritten and no EP is launched.
"""
import collections, hashlib, json, sqlite3, sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1]
N = OUT.parent / 'evidence_conditioned_production_20261009_v19'
def read(p): return json.loads(p.read_text())
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def save(name, value): (OUT/name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')

def sql_values(receipt, asset):
    path = N/receipt['SQL_path']
    assert sha(path) == receipt['SQL_sha256']
    db = sqlite3.connect('file:'+str(path)+'?mode=ro', uri=True)
    values = [r[0] for r in db.execute('SELECT r.Value FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE t.WarmupFlag=0 AND d.ReportingFrequency="Zone Timestep" AND d.Name="Electric Equipment Electricity Energy" AND upper(d.KeyValue)=? ORDER BY t.TimeIndex', (asset.upper(),))]
    db.close()
    assert len(values) == 1440
    return values

def main():
    if sys.platform != 'linux': raise RuntimeError('School Linux only')
    counts = collections.Counter(); early_examples = []; storage_examples = []; air_examples = []
    for h in read(N/'SELECTION50.json')['records']:
        w = read(N/h['world_path'])
        ev = next((d for d in w['parameter_pack']['devices'] if 'ev' in d['types']), None)
        for r in h['rounds']:
            p = read(N/r['pair_path']); out = read(N/'readback/base7'/h['household_id']/f"{r['round_index']:02d}.json")
            early = [o for o in p['B']['operations'] if o['kind']=='unload' and any(t['need_id'] in (o['need_id'],o['need_id']+':dry') and t['end_min']>o['start_min'] for t in p['B']['tasks'])]
            if early:
                receipt = read(N/'runs/base7'/h['household_id']/f"{r['round_index']:02d}_B/RUN_RECORD.json")
                subsequent = False
                for o in early:
                    chain = [t for t in p['B']['tasks'] if t['need_id'] in (o['need_id'],o['need_id']+':dry')]
                    values = sql_values(receipt, chain[0]['asset_id'])
                    a = 7*144+o['end_min']//10; b = 7*144+max(t['end_min'] for t in chain)//10
                    energy = sum(values[a:b])/3.6e6
                    if energy>1e-6:
                        subsequent=True
                        if len(early_examples)<4: early_examples.append({'case_id':p['case_id'],'round_index':r['round_index'],'unload':o,'programme_chain':chain,'actual_EP_programme_grid_kWh_after_premature_unload':energy,'SQL_sha256':receipt['SQL_sha256'],'interpretation':'bad requested unload is retained; later scheduled programme power is computed independently of whether that unload can occur'})
                counts['actual_SQL_cases_with_programme_power_after_premature_unload'] += subsequent
            ac_changed = any(c['kind']=='ac_setpoint' for c in p['B']['changed_controls'])
            if ac_changed:
                counts['original50_AC_changed_cases']+=1
                rows = {s:{x['room_id']:x for x in out['services'][s]['room_air']} for s in ('A','B')}
                delta = max((abs(rows['A'][rid][v]-rows['B'][rid][v]) for rid in rows['A'] for v in ('min_C','max_C')),default=0.)
                c = read(N/'consumers'/h['household_id']/f"{r['round_index']:02d}.json")
                exposed = any(('空气温度' in i['description'] or '室温' in i['description']) for i in c['impacts'])
                if delta>.05 and not exposed:
                    counts['AC_changed_with_temperature_range_difference_over_0_05C_not_in_impacts']+=1
                    if len(air_examples)<3: air_examples.append({'case_id':p['case_id'],'room_air':rows,'max_range_endpoint_A_B_difference_C':delta,'personal_comfort_pass':out['services']['A']['personal_comfort_pass'],'temperature_outcome_in_consumer_impacts':False})
            if not ev: continue
            cfg=ev['parameters']; soc={}
            for side in ('A','B'):
                receipt=read(N/'runs/base7'/h['household_id']/f"{r['round_index']:02d}_{side}/RUN_RECORD.json")
                values=sql_values(receipt,ev['asset_id']); a=7*144+p['decision_abs_min']//10; b=7*144+p['service_tail_min'][1]//10
                soc[side]=out['pre_event_EV_SOC'][side]+sum(values[a:b])/3.6e6*cfg.get('efficiency',.92)/cfg['capacity_kwh']-sum(t['required_kWh'] for t in out['services'][side]['EV']['trips'] if p['decision_abs_min']<=t['minute_relative_to_target']<p['service_tail_min'][1]) / cfg['capacity_kwh']
            if abs(soc['A']-soc['B'])>.01:
                storage_examples.append({'case_id':p['case_id'],'round_index':r['round_index'],'service_tail_min':p['service_tail_min'],'terminal_EV_SOC':soc,'battery_capacity_kWh':cfg['capacity_kwh'],'terminal_battery_stored_energy_A_minus_B_kWh':(soc['A']-soc['B'])*cfg['capacity_kwh'],'event_energy':out['energy']['event'],'living_day_and_service_tail_energy':out['energy']['living_day_and_service_tail'],'threshold_is_audit_description_not_predeclared_acceptance':True})
    save('SQL_WITNESSES.json',{'counts':dict(counts),'premature_unload_examples':early_examples,'terminal_EV_examples':storage_examples,'AC_outcome_examples':air_examples,'EP_started':0,'production_modified':False,'SQL_hash_checked':True})
    export=read(OUT/'evidence/SYNTHETIC_EXPORT_LEAK_WITNESS.json')
    roots=list((N/'frontend_release/households').iterdir()); js=[sha(x/'joint-view.js') for x in roots]
    assert len(roots)==50 and len(set(js))==1
    code=(roots[0]/'household-view.js').read_text(); assert 'member.local_id' not in code and 'member.member_id' not in code
    score=export['input']['fields']['score-question']
    assert all(x+' 分' in score for x in ('1.2','2.3','4.5','5'))
    save('FRONTEND_RESPONSE_LEAK_AUDIT.json',{'case_id':export['audit']['source_case']['identity']['case_id'],'export_sha256':sha(OUT/'evidence/SYNTHETIC_EXPORT_LEAK_WITNESS.json'),'frontend_bundles_with_identical_export_code':50,'joint_view_sha256':js[0],'leaked_model_input_field':'score-question','actual_export_field_text':score,'synthetic_test_feedback':export['test_feedback'],'human_label_count':0,'status':export['status'],'hidden_weather_and_state_fields_empty_at_export':all(export['input']['fields'][k]=='' for k in ('joint-weather','joint-state')),'closed_plan_details_fields_empty_at_export':all(export['input']['fields'][k]=='' for k in ('joint-plan-A','joint-plan-B')),'member_local_id_mapping_absent_from_member_cards':True,'scope':'one actual UI-filled exported witness; identical faulty exporter in all50 bundles, not50 browser-filled tests','screenshot':'evidence/score_leak.jpg','production_modified':False,'EP_started':0})
    print({'counts':dict(counts),'EV_examples':storage_examples,'frontend_bundles':len(roots),'EP_started':0},flush=True)
if __name__=='__main__': main()
