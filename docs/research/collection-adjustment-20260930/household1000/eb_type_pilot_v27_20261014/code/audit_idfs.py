"""All static bindings and realized control prerequisites; EP remains original50."""
import collections,concurrent.futures,datetime as dt
from common import *
from activity_model import dated

def one(h):
    selection=next(x for x in SELECTION if x['household_id']==h['household_id']);w=read(OUT/selection['world_path']);counts=collections.Counter();errors=[]
    for r in h['records']:
        p=read(OUT/'pairs'/h['household_id']/f'{r["round_index"]:02d}.json');ids={n['need_id'] for n in p['needs_A']};prefix=None
        for side in ('A','B'):
            b=r[side];lp=OUT/b['signal_ledger_path'];ip=OUT/b['IDF_path']
            if sha(lp)!=b['signal_ledger_sha256'] or sha(ip)!=b['IDF_sha256']:errors.append([r['case_id'],side,'FILE_BINDING']);continue
            ledger=read(lp)
            if digest(ledger['signals'])!=b['schedule_signal_sha256'] or b['parameter_pack_sha256']!=w['parameter_pack_sha256']:errors.append([r['case_id'],side,'SIGNAL_PARAMETER_BINDING'])
            origin=ledger['prior_days']*1440;end=origin+p['decision_abs_min'];n=(ledger['prior_days']+3)*144
            if any(len(v)!=n for v in ledger['signals'].values()):errors.append([r['case_id'],side,'CLOCK_LENGTH'])
            for x in ledger['execution']['program_services']:
                if x['need_id'] in ids:
                    counts[side+'_batch_services']+=1
                    if not x['delivered_before_given_bound']:
                        counts[side+'_undelivered']+=1
                        if side=='A':errors.append([r['case_id'],side,'A_COMPILED_SERVICE'])
            for gap in ledger['post_operation_care_gaps']:
                if origin+480<=gap['start_min']<origin+p['service_tail_min'][1]:
                    counts[side+'_care_gap_slots']+=1
                    if side=='A':errors.append([r['case_id'],side,'A_COMPILED_CARE'])
            ev=next((d for d in w['parameter_pack']['devices'] if 'ev' in d['types']),None)
            if ev:
                aid=ev['asset_id'];start=dt.date.fromisoformat(ledger['start_date']);successes=[t for t in ledger['EV_diagnostics'] if t['trip_departed']]
                for i,power in enumerate(ledger['signals'][aid]):
                    if power<=1e-9:continue
                    minute=i*10;connection=any(c['asset_id']==aid and c['start_min']<=minute<c['end_min'] for c in ledger['execution']['connections'])
                    away=False
                    for trip in successes:
                        day=(dt.date.fromisoformat(trip['date'])-start).days
                        activity=next(d for d in p['dated_activity_days'] if d['date']==trip['date']) if trip['date'] in {d['date'] for d in p['dated_activity_days']} else dated(w,trip['date'])
                        if activity and activity['transport'] and trip['absolute_min']<=minute<day*1440+activity['transport']['arrival_min']:away=True
                    if not connection or away:errors.append([r['case_id'],side,'EV_POWER_WITHOUT_CONNECTION_OR_PRESENCE']);break
            # Actual target A/B signals before notice must be identical.
            prior={'signals':{k:v[:end//10] for k,v in ledger['signals'].items()},
                'residents':{m:{rid:vs[:end//10] for rid,vs in by.items()} for m,by in ledger['spatial']['resident_occupancy'].items()},
                'visitors':{m:{rid:vs[:end//10] for rid,vs in by.items()} for m,by in ledger['spatial']['external_occupancy'].items() if any(any(vs[:end//10]) for vs in by.values())},
                'lighting':{rid:vs[:end//10] for rid,vs in ledger['spatial']['lighting'].items()}}
            if prefix is None:prefix=digest(prior)
            elif prefix!=digest(prior):errors.append([r['case_id'],'ACTUAL_PREFIX_SIGNAL_CHANGE'])
            counts['IDFs']+=1
    return {'household_id':h['household_id'],'failures':errors,'counts':dict(counts)}

SELECTION=read(OUT/'SELECTION50.json')['records'] if (OUT/'SELECTION50.json').exists() else []
def main():
    school_guard();manifest=read(OUT/'IDF_BINDINGS1000.json');counts=collections.Counter();rows=[];fail=[]
    assert manifest['failed']==[] and manifest['IDF_count']==1000 and len(manifest['households'])==50
    with concurrent.futures.ProcessPoolExecutor(max_workers=16) as pool:
        for r in pool.map(one,manifest['households']):
            rows.append(r);counts.update(r['counts']);fail.extend(r['failures'])
    save(OUT/'IDF_CHECKS1000.json',rows);save(OUT/'IDF_INPUT_AUDIT.json',{'counts':dict(counts),'failures':fail,
        'all_source_file_and_signal_bindings_checked':True,'EP_executed_by_this_audit':0,'field_calibration':False})
    print({'counts':dict(counts),'failures':len(fail),'examples':fail[:6]},flush=True)
    if fail:raise RuntimeError('static IDF gate failed')
if __name__=='__main__':main()
