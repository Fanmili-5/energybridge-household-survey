"""Independent saved-control readback of daily fan service and room presence."""
import sys,collections,datetime as dt
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *

def genuine_anchor(case,assignment):
    anchor=assignment['activity_anchor_min'];rid=assignment['room_id'];label=assignment['activity_anchor'];day0=dt.date.fromisoformat(case['date'])
    calendars={}
    for day in case['days']:
        offset=(dt.date.fromisoformat(day['date'])-day0).days*1440
        for mid,seq in {**day['activity']['member_calendars'],**day['shared']['member_calendars']}.items():
            calendars.setdefault(mid,[]).extend({**x,'start_min':x['start_min']+offset,'end_min':x['end_min']+offset}for x in seq)
    if label=='return_to_room:first_occupied_slot_after_actual_return':
        act=next(d['activity']for d in case['days']if d['date']==case['date'])
        return any(s.get('arrival_min')is not None and s['arrival_min']<=anchor for s in act['member_specs'].values())
    for seq in calendars.values():
        seq.sort(key=lambda x:x['start_min'])
        for j,x in enumerate(seq):
            if x['room_id']!=rid or x['location']!='home':continue
            before=seq[j-1]if j else None;after=seq[j+1]if j+1<len(seq)else None
            state=lambda z:(z['activity'],z['room_id'],z['location'])if z else None
            if label=='evening_room_activity:sleep_start'and x['activity']=='sleep_rest'and x['start_min']==anchor and before is not None and state(before)!=state(x):return True
            if label=='wake_activity:sleep_end'and x['activity']=='sleep_rest'and x['end_min']==anchor and after is not None and state(after)!=state(x):return True
            if label=='wake_activity:personal_and_breakfast'and x['activity']=='personal_and_breakfast'and x['start_min']==anchor:return True
            if label=='evening_room_activity:dinner_end'and x['activity']=='dinner'and x['end_min']==anchor:return True
            if label.startswith('room_entry:')and x['start_min']==anchor and before is not None and state(before)!=state(x):return True
            if label=='return_to_room:actual_return'and x['start_min']==anchor and before is not None and before['location']=='outside':return True
    return False

def main():
    rows=read(OUT/'A_BINDINGS10000.json')['records'];old=BASE/'normal_A_v42_20261016';oldrows={r['household_id']:r for r in read(old/'A_BINDINGS10000.json')['records']}
    errors=[];counts=collections.Counter();shapes=collections.Counter();oldshapes=collections.Counter();hours=collections.Counter();examples={}
    for ri,row in enumerate(rows):
        w=read(OUT/row['A_world_path']);acs={d['asset_id']:d['room_id']for d in w['parameter_pack']['devices']if'ac'in d['types']};oldcases={x['date']:x for x in oldrows[row['household_id']]['cases']}
        for rr in row['cases']:
            c=read(OUT/rr['path']);prev=read(old/oldcases[rr['date']]['path']);counts['cases']+=1
            target=next(d for d in c['days']if d['date']==c['date']);assign={x['asset_id']:x for x in target['circulation_assignments']}
            op={(o['start_min'],o['operator_id']):None if o['kind'].startswith('EV_')else o['room_id']for o in c['A']['operations']}
            for aid,rid in acs.items():
                minutes=sorted(t for x in c['A']['controls']if x['kind']=='ac_setpoint'and x['asset_id']==aid and x['fan_operating_mode']==1 for t in range(max(480,x['start_min']),min(1920,x['end_min']),10))
                past=sorted(t for x in prev['A']['controls']if x['kind']=='ac_setpoint'and x['asset_id']==aid and x['fan_operating_mode']==1 for t in range(max(480,x['start_min']),min(1920,x['end_min']),10))
                q=assign[aid]
                if not genuine_anchor(c,q):errors.append([rr['case_id'],aid,'ANCHOR_NOT_AN_ACTUAL_ACTIVITY_TRANSITION'])
                counts['actual_activity_anchors_read_back']+=1
                counts['AC_asset_days']+=1;shapes[tuple(minutes)]+=1;oldshapes[tuple(past)]+=1;counts['changed_asset_days']+=minutes!=past
                if len(minutes)!=6 or len(set(minutes))!=6 or minutes!=q['selected_minutes']or not q['complete_service_day']:errors.append([rr['case_id'],aid,'DAILY_SERVICE_OR_LEDGER_MISMATCH'])
                counts['activity_anchor_fallbacks']+=q['fallback_to_actual_room_entry']
                for t in minutes:
                    day=c['date']if t<1440 else str(dt.date.fromisoformat(c['date'])+dt.timedelta(days=1));context=next(d for d in c['days']if d['date']==day);local=t%1440
                    occupied=False
                    for mid,seq in {**context['activity']['member_calendars'],**context['shared']['member_calendars']}.items():
                        x=next(x for x in seq if x['start_min']<=local<x['end_min'])
                        if x['location']=='home'and op.get((t,mid),x['room_id'])==rid:occupied=True;break
                    if not occupied:errors.append([rr['case_id'],aid,t,'FAN_WITHOUT_ACTUAL_PRESENCE'])
                    hours[str(t//60)]+=10
            if row['household_id']=='ordinary-v6-0001':examples[rr['case_id']]={'path':rr['path'],'assignments':target['circulation_assignments'],'previous_fan_minutes':{aid:sorted(t for x in prev['A']['controls']if x['kind']=='ac_setpoint'and x['asset_id']==aid and x['fan_operating_mode']==1 for t in range(max(480,x['start_min']),min(1920,x['end_min']),10))for aid in acs}}
        if(ri+1)%200==0:print({'circulation_households':ri+1,'errors':len(errors)},flush=True)
    r={'accepted':not errors and counts['cases']==10000,'rules_sha256':rules_id(),'counts':dict(counts),'errors':errors,'fan_minutes_by_service_hour':dict(hours),'top10_signatures':[(list(k),v)for k,v in shapes.most_common(10)],'previous_top10_signatures':[(list(k),v)for k,v in oldshapes.most_common(10)],'old1830_to1930_asset_days':oldshapes[(1110,1120,1130,1140,1150,1160)],'current1830_to1930_asset_days':shapes[(1110,1120,1130,1140,1150,1160)],'no_uniform_distribution_or_minimum_diversity_acceptance_threshold':True,'physical_acceptance':False}
    save(OUT/'CIRCULATION_REVIEW.json',r);save(OUT/'review/循环风活动依据与前后示例.json',examples);print(canonical(r))
    if not r['accepted']:raise SystemExit(2)
if __name__=='__main__':main()
