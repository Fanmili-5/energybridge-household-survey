"""Independent readback: calendar truth, indoor holds, hardware envelope and fixed A routines."""
import sys,collections,datetime as dt
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *
def merge(xs):
    out=[]
    for a,b in sorted(xs):
        if out and a<=out[-1][1]:out[-1][1]=max(b,out[-1][1])
        elif a<b:out.append([a,b])
    return out

def main():
    parent=BASE/'normal_A_v44_20261017';old={r['household_id']:r for r in read(parent/'A_BINDINGS10000.json')['records']};counts=collections.Counter();bad=[];examples={}
    for ri,row in enumerate(read(OUT/'A_BINDINGS10000.json')['records']):
        w=read(OUT/row['A_world_path']);oldcases={x['date']:x for x in old[row['household_id']]['cases']}
        for rr in row['cases']:
            c=read(OUT/rr['path']);previous=read(parent/oldcases[rr['date']]['path']);counts['cases']+=1;context=c['thermal_control_context']
            # Preserve every manual operation and nonthermal program/permission.
            part=lambda p:{'tasks':p['tasks'],'operations':p['operations'],'controls':[x for x in p['controls']if x['kind']!='ac_setpoint']}
            if part(c['A'])!=part(previous['A']):bad.append([c['case_id'],'NONTHERMAL_ROUTINE_CHANGED'])
            ops={(o['start_min'],o['operator_id']):(None if o['kind'].startswith('EV_')else o['room_id'])for o in c['A']['operations']};home=collections.defaultdict(set);room=collections.defaultdict(lambda:collections.defaultdict(set))
            for day in c['days']:
                base=(dt.date.fromisoformat(day['date'])-dt.date.fromisoformat(c['date'])).days*1440
                for mid,seq in {**day['activity']['member_calendars'],**day['shared']['member_calendars']}.items():
                    for item in seq:
                        if item['location']!='home':continue
                        for t in range(base+item['start_min'],base+item['end_min'],10):home[mid].add(t);room[ops.get((t,mid),item['room_id'])][mid].add(t)
            for aid,z in context.items():
                counts['asset_days']+=1;actual=set().union(*room[z['room_id']].values());saved={t for a,b in z['actual_occupied_intervals_min']for t in range(a,b,10)}
                if actual!=saved:bad.append([c['case_id'],aid,'OCCUPANCY_CONTEXT_NOT_CALENDAR_TRUTH'])
                spans=merge([[t,t+10]for t in actual]);expected=set(actual);filled=[]
                for left,right in zip(spans,spans[1:]):
                    a,b=left[1],right[0]
                    if not 0<b-a<=20:continue
                    who=[mid for mid,xs in room[z['room_id']].items()if a-10 in xs and b in xs and all(t in home[mid]for t in range(a,b,10))]
                    if who:expected.update(range(a,b,10));filled.append([a,b])
                permission={t for x in c['A']['controls']if x['kind']=='ac_setpoint'and x['asset_id']==aid for t in range(max(480,x['start_min']),min(1920,x['end_min']),10)}
                target={t for t in expected if 480<=t<1920}
                if permission!=target:bad.append([c['case_id'],aid,'PERMISSION_NOT_OCCUPANCY_PLUS_JUSTIFIED_HOLD'])
                counts['held_minutes']+=len(permission-{t for t in actual if 480<=t<1920})*10
                counts['justified_closed_gaps']+=sum(480<=a and b<=1920 for a,b in filled)
                if z['hardware_request_intervals_min']!=[[480,1920]]or not z['request_requires_human_agreement']:bad.append([c['case_id'],aid,'HARDWARE_ENVELOPE_OR_CONSENT_CHANGED'])
            oldact=next(d['activity']for d in previous['days']if d['date']==c['date']);act=next(d['activity']for d in c['days']if d['date']==c['date'])
            if act!=oldact:bad.append([c['case_id'],'REAL_LIFE_CALENDAR_RANDOMLY_CHANGED'])
            if c['case_id']=='ordinary-v6-0001__2025-03-15':
                aid=next(iter(context));assert all(t in{t for x in c['A']['controls']if x['kind']=='ac_setpoint'and x['asset_id']==aid for t in range(x['start_min'],x['end_min'],10)}for t in(1180,))
                examples[c['case_id']]={'path':rr['path'],'bath19_40_to19_50_held':True,'context':context}
        if(ri+1)%200==0:print({'thermal_context_households':ri+1,'errors':len(bad)},flush=True)
    r={'accepted':not bad and counts['cases']==10000,'rules_sha256':rules_id(),'counts':dict(counts),'errors':bad,'given20minute_threshold_not_population_fact':True,'actual_occupancy_never_fabricated':True,'physical_acceptance':False}
    save(OUT/'THERMAL_CONTEXT_REVIEW.json',r);save(OUT/'review/短离房温控与可调范围示例.json',examples);print(canonical(r))
    if not r['accepted']:raise SystemExit(2)
if __name__=='__main__':main()
