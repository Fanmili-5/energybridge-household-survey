"""Six input-only proposal mechanisms, fixed dates and immutable reference needs."""
import collections,copy,datetime as dt
from common import *
from plans import make_A,reserve
from checks import assess

GROUPS=['near_boundary','inconvenient_but_doable','cross_device','negotiation','constraint_challenge','service_risk']
def baseline(w,index):
    selected=w['random10_date_selection']['dates'][index];date=dt.date.fromisoformat(selected['date'])
    ns,A,ws,initial=make_A(w,date)
    p={'schema':'eb.profile_conditioned_pair.v18','case_id':w['household_id']+':'+date.isoformat(),
       'household_id':w['household_id'],'round_index':index+1,'date':date.isoformat(),'date_selection':selected,
       'world_sha256':w['world_content_sha256'],'parameter_pack_sha256':w['parameter_pack_sha256'],
       'decision_abs_min':1020,'event_window_min':[1080,1140],'horizon_min':4320,
       'primary_evaluation_min':[480,1920],'service_tail_min':[1920,max(3330,max((n['deadline_min'] for n in ns),default=0)+60)],
       'world':{'devices':copy.deepcopy(w['parameter_pack']['devices']),'operator_windows':ws,
                'circuit_limit_kw':w['parameter_pack']['circuit_limit_kw'],
                'home_service_limit_kw':w['parameter_pack']['home_service_limit_kw'],
                'background_reserved_kw':w['parameter_pack']['background_reserved_kw']},
       'devices_sha256':digest(w['parameter_pack']['devices']),'common_initialization_binding':initial,
       'needs_A':ns,'needs_B':copy.deepcopy(ns),'A':A,'B':copy.deepcopy(A),'A_frozen_before_B_sha256':digest(A),
       'human_adoption':None,'human_relative_preference':None,'simulated_consequences':None}
    return p
def finish(q,group,family,amount,assets,event,reason):
    q['event_window_min']=[event,event+60];q['decision_abs_min']=event-60
    q['B']['changed_controls']=[c for c in q['B']['controls'] if c not in q['A']['controls']]
    q['proposal']={'family':family,'amount':amount,'target_asset_ids':assets,'origin':'predeclared reference proposal rules',
                   'mechanism':group,'reason':reason,'energy_cost_or_human_outputs_consulted':False,'LLM_call_occurred':False}
    q['design_condition']=group;q['constraint_assessment']=assess(q)
    return q
def shifted(base,t,delta):
    q=copy.deepcopy(base)
    for x in q['B']['tasks']:
        if x['asset_id']==t['asset_id'] and t['start_min']<=x['start_min']<1440:x['start_min']+=delta;x['end_min']+=delta
    return q
def change_ac(q,c,event,increase):
    out=[]
    for x in q['B']['controls']:
        lo,hi=max(event,x['start_min']),min(event+60,x['end_min'])
        if x['asset_id']!=c['asset_id'] or x['kind']!='ac_setpoint' or lo>=hi:out.append(x);continue
        if x['start_min']<lo:out.append({**x,'end_min':lo})
        out.append({**x,'start_min':lo,'end_min':hi,'value_C':x['value_C']+increase})
        if hi<x['end_min']:out.append({**x,'start_min':hi})
    q['B']['controls']=out
def candidates(w,p):
    out=[];ns={n['need_id']:n for n in p['needs_A']}
    first=[t for t in p['A']['tasks'] if 540<=t['start_min']<1440 and t['kind'] in ('washer','dishwasher')]
    ac=[c for c in p['A']['controls'] if c['kind']=='ac_setpoint' and c['start_min']<1440 and c['end_min']>550]
    for t in first:
        last=max((z for z in p['A']['tasks'] if z['asset_id']==t['asset_id'] and t['start_min']<=z['start_min']<1440),key=lambda z:z['end_min'])
        event=t['start_min'];slack=ns[last['need_id']]['deadline_min']-last['end_min']
        for delta in sorted(set([20,40,80])):
            if delta<slack:
                q=shifted(p,t,delta);out.append(finish(q,'inconvenient_but_doable','program_time_tradeoff',delta,[t['asset_id']],event,
                    'same service and retrieval; habitual start changes, individual inconvenience remains unknown'))
        if slack>=20:
            delta=slack-10;q=shifted(p,t,delta);out.append(finish(q,'near_boundary','program_near_deadline',delta,[t['asset_id']],event,'same program finishes ten minutes before given bound'))
        for late in [10,50]:
            delta=slack+late;q=shifted(p,t,delta);out.append(finish(q,'constraint_challenge','program_deadline_overrun',late,[t['asset_id']],event,'given program deadline retained; actor decides how to respond to conflict'))
        q=shifted(p,t,20);old=next(o for o in q['B']['operations'] if o['kind']=='unload' and o['need_id']==t['need_id'])
        q['B']['operations'].remove(old);end=last['end_min']+20
        try:
            new=reserve(q['B']['operations'],q['world']['operator_windows'],'unload',t['need_id'],max(end,event),ns[t['need_id']]['delivery_deadline_min'],end+10,old['operator_id'])
            if new!=old:
                out.append(finish(q,'negotiation','program_and_retrieval_negotiation',20,[t['asset_id']],event,
                    'same service; requests handling at a different available time, which requires actor negotiation rather than assumed willingness'))
        except ValueError:pass
        other=next((z for z in first if z['asset_id']!=t['asset_id'] and z['start_min']>=event-60),None)
        if other:
            q=shifted(shifted(p,t,40),other,20)
            out.append(finish(q,'cross_device','two_programs_joint_shift',[40,20],[t['asset_id'],other['asset_id']],event,'joint changes inherit each device service and shared handling constraints'))
        c=next((c for c in ac if c['start_min']<=event<c['end_min']),None)
        if c:
            q=shifted(p,t,40);change_ac(q,c,event,.8)
            out.append(finish(q,'cross_device','program_and_AC_joint',[40,.8],[t['asset_id'],c['asset_id']],event,'same occupied-room control service and program; joint tradeoff, no preassigned comfort or acceptance'))
    for c in ac:
        event=max(540,c['start_min'])
        if event>=min(1440,c['end_min']):continue
        for group,delta in [('near_boundary',.9),('inconvenient_but_doable',.4),('constraint_challenge',1.2)]:
            q=copy.deepcopy(p);change_ac(q,c,event,delta)
            out.append(finish(q,group,'AC_control_tradeoff',delta,[c['asset_id']],event,'reference control bound retained; subjective temperature tolerance remains unknown'))
    for c in p['A']['controls']:
        if c['start_min']>=1440 or c['kind']=='ac_setpoint':continue
        event=max(540,c['start_min'])
        if c['kind']=='tank_setpoint':
            for group,delta in [('inconvenient_but_doable',40),('near_boundary',80)]:
                q=copy.deepcopy(p);z=next(z for z in q['B']['controls'] if z==c);z['start_min']+=delta
                out.append(finish(q,group,'hotwater_preheat_tradeoff',delta,[c['asset_id']],event,'bath appointment and volume unchanged; changed preheat may have modeled consequences, not a validated service success'))
            q=copy.deepcopy(p);z=next(z for z in q['B']['controls'] if z==c);z['value_C']=35.
            out.append(finish(q,'service_risk','hotwater_low_heat_target',35.,[c['asset_id']],event,'mixed-water target retained; stored heat and delivered temperature require physical readback'))
        if c['kind']=='ev_charge_window':
            delta=c['end_min']-240-c['start_min']
            if delta>=10:
                q=copy.deepcopy(p);z=next(z for z in q['B']['controls'] if z==c);z['start_min']+=delta
                out.append(finish(q,'near_boundary','EV_charge_near_energy_window',delta,[c['asset_id']],event,'reference240min remaining window compared with25kWh replenishment; actual inherited SOC still read back'))
            q=copy.deepcopy(p);z=next(z for z in q['B']['controls'] if z==c);z['start_min']+=40
            if z['start_min']<z['end_min']:
                out.append(finish(q,'inconvenient_but_doable','EV_charge_delay',40,[c['asset_id']],event,'same trip and access target; charging permission starts later'))
            q=copy.deepcopy(p);z=next(z for z in q['B']['controls'] if z==c);z['end_min']=z['start_min']+40
            out.append(finish(q,'service_risk','EV_short_charge_window',40,[c['asset_id']],event,'given trip energy and85% access target retained and evaluated separately'))
    if not out:
        # Preserve quiet winter/rest dates rather than resample or invent assets.
        # An additional request is not a new mandatory service or presumed consent.
        d=next((d for d in w['parameter_pack']['devices'] if 'ac' in d['types']),None)
        q=copy.deepcopy(p)
        if d:
            event=1140;q['B']['controls'].append({'asset_id':d['asset_id'],'kind':'ac_setpoint','start_min':event,'end_min':event+60,'value_C':27.})
            out.append(finish(q,'negotiation','additional_AC_request_without_cooling_need',27.,[d['asset_id']],event,
                             'no cooling service on this frozen date; additional activation request for actor to evaluate, not an invented need'))
        else:
            d=next((d for d in w['parameter_pack']['devices'] if 'ev' in d['types']),None)
            if d:
                nid=p['date']+':optional_EV_request'
                plug=reserve(q['B']['operations'],q['world']['operator_windows'],'EV_plug',nid,1080,1260,1140,d['operator_id'])
                unplug=reserve(q['B']['operations'],q['world']['operator_windows'],'EV_unplug',nid,plug['end_min']+40,1380,plug['end_min']+60,d['operator_id'])
                event=plug['start_min'];q['B']['controls'].append({'asset_id':d['asset_id'],'kind':'ev_charge_window','start_min':plug['end_min'],'end_min':unplug['start_min']})
                out.append(finish(q,'negotiation','additional_EV_handling_without_trip_need',60,[d['asset_id']],event,
                                 'no given trip on this frozen rest date; additional plug/unplug request and charging permission, actual SOC may mean zero charging energy'))
    return out
def main():
    school_guard();bindings=read(OUT/'WORLD_BINDINGS1000.json');records=[];counts=collections.Counter();flags=collections.Counter();a_flags=collections.Counter();fail=[];fallback=collections.Counter()
    for h in bindings['records']:
        w=read(OUT/h['world_path']);rounds=[];used=collections.Counter()
        for i in range(10):
            p=baseline(w,i);pool=candidates(w,p);good=[q for q in pool if not q['constraint_assessment']['integrity_errors']]
            wanted=GROUPS[(i+rank(w['household_id'],'v18-coverage'))%len(GROUPS)]
            appropriate=[q for q in good if q['design_condition']==wanted]
            if not appropriate:appropriate=good;fallback[wanted]+=1
            if not appropriate:fail.append({'case_id':p['case_id'],'error':'NO_REPRESENTABLE_CANDIDATE'});continue
            q=min(appropriate,key=lambda q:(used[q['proposal']['family']],rank(p['case_id'],q['proposal'])))
            used[q['proposal']['family']]+=1;q['coverage_assignment']={'desired_mechanism':wanted,'realized_mechanism':q['design_condition'],'applicable_candidates':len(good),'unavailable_design_level_not_new_assets_or_dates':not any(x['design_condition']==wanted for x in good)}
            q['source_rules_sha256']=sha(Path(__file__));q['pair_content_sha256']=digest(q)
            path=OUT/'pairs'/w['household_id']/f'{i+1:02d}.json';save(path,q)
            counts[q['design_condition']]+=1;flags.update(q['constraint_assessment']['constraint_flags']['B']);a_flags.update(q['constraint_assessment']['constraint_flags']['A'])
            rounds.append({'case_id':q['case_id'],'date':q['date'],'round_index':i+1,'pair_path':str(path.relative_to(OUT)),'pair_sha256':sha(path),'A':None,'B':None,'EP_results':None})
        records.append({**h,'rounds':rounds})
    save(OUT/'SELECTION1000.json',{'households':len(records),'pairs':sum(len(h['rounds']) for h in records),'records':records})
    selected={h['household_id'] for h in read(PILOT/'SELECTION50.json')['records']}
    rows=[h for h in records if h['household_id'] in selected];assert len(rows)==50
    save(OUT/'SELECTION50.json',{'households':50,'pairs':sum(len(h['rounds']) for h in rows),'records':rows,'selection':'same original50 identifiers; no outcome selection'})
    report={'households':len(records),'pairs':sum(len(h['rounds']) for h in records),'integrity_failures':fail,
            'proposal_mechanisms':dict(counts),'B_constraint_flags':dict(flags),'A_constraint_flags':dict(a_flags),
            'unavailable_requested_mechanisms':dict(fallback),'all_original_dates_retained':not fail,
            'human_labels_generated':0,'new_EP_executed':False,'bad_proposals_retained':True}
    save(OUT/'STATIC_REVIEW.json',report);print(report,flush=True)
    if fail:raise RuntimeError('static failures')
if __name__=='__main__':main()
