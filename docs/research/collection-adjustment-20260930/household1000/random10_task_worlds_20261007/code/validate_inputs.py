"""Actual school-side contract checks, before small-batch EP execution."""
import collections, datetime as dt, platform
from common import *
from programs import trace,round_spec,schedules
from compile_physics import compile_idf

def main():
    if sys.platform!='linux':raise SystemExit('Interface validation belongs on school Linux')
    records=read(OUT/'WORLD_BINDINGS1000.json')['records'];counts=collections.Counter();sample=[]
    for binding in records:
        hid=binding['household_id'];path=OUT/binding['world_path'];w=read(path);content=dict(w);content.pop('world_content_sha256')
        assert sha(path)==binding['world_sha256'] and digest(content)==w['world_content_sha256']
        assert len(w['members'])==w['N'] and len({m['generation_level'] for m in w['members']})==w['G']
        assert set(w['assets'])=={'ac','washer','dishwasher','dryer','water_heater','ev'}
        selected=w['random10_date_selection']['dates'];dates=[s['date'] for s in selected]
        assert len(dates)==len(set(dates))==10 and dates==sorted(dates)
        assert set(s['quarter'] for s in selected)=={1,2,3,4}
        assert sorted(collections.Counter(s['quarter'] for s in selected).values())==[2,2,3,3]
        assert all(dt.date.fromisoformat(d).year==2025 for d in dates)
        for m in w['members']:
            for day in m['weekly_calendar']:
                intervals=day['intervals'];assert intervals[0]['start_h']==0 and intervals[-1]['end_h']==24
                assert all(a['end_h']==b['start_h'] for a,b in zip(intervals,intervals[1:]))
        for index in range(1,11):
            case=round_spec(w,index);origin=case['context']['episode_start_date'];a=trace(w,3,start_date=origin);b=trace(w,3,case,start_date=origin)
            decision=144+round(case['context']['decision_h']*6)
            assert len(a['rows'])==len(b['rows'])==432 and a['rows'][:decision]==b['rows'][:decision]
            assert all(c['EB_kernel_accepted'] for c in b['applied_commands'])
            assert all(j['finish_h']<=j['deadline_h']+1e-8 and j['start_h']>=j['release_h']-1e-8 for j in b['service'] if j['kind']!='ev')
            counts['target_dates']+=1;counts[case['applicability']]+=1
            if hid in ['ordinary-v6-0001','ordinary-v6-0002','ordinary-v6-0139','ordinary-v6-0216']:
                idf=OUT/'interface_idfs'/hid/f'{index:02d}.idf';physical=compile_idf(w,binding,schedules(w,a),idf,origin,case,b['rows'])
                rows=parse(idf);periods=[r for r in rows if r[0]=='RunPeriod'];assert len(periods)==1 and physical['days']==3
                assert not any(r[0]=='Schedule:File' for r in rows)
                sample.append({'household_id':hid,'round':index,'date':case['context']['date'],'IDF_sha256':physical['IDF_sha256']})
        assert sha(binding['weather']['path'])==binding['weather']['sha256']
        counts['residents']+=w['N'];counts['worlds']+=1
    report={'host':platform.node(),'platform':platform.platform(),'python':platform.python_version(),'engine_sha256':sha(ENGINE),
        'counts':dict(counts),'compiled_interface_samples':sample,'annual_runs_or_annual_padding':0,
        'check_scope':'input identity,roster/calendar closure,date sampling,native EB command acceptance,program-prefix equality,reference deadline feasibility,EP24.1 field construction;physical runtime follows',
        'scientific_population_or_human_validity_proven':False}
    save(OUT/'SCHOOL_INTERFACE_CHECKS.json',report);print({'host':platform.node(),**counts,'compiled_IDFs':len(sample)},flush=True)
if __name__=='__main__':main()
