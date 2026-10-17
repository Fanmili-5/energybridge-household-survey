"""Independent full-population readback of calendars, actual bounds and event energy."""
import sys,collections,math
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *
from proposals import command_signature

def ol(a,b,c,d):return max(0,min(b,d)-max(a,c))
def known_energy(plan,assets,lo,hi):
    total=0.
    for x in plan['tasks']:
        p=assets[x['asset_id']]['parameters'];kw=p.get(x['kind'],p)['power_kw']
        total+=kw*ol(x['start_min'],x['end_min'],lo,hi)/60
    for x in plan['controls']:
        if x['kind']!='ev_charge_window':continue
        kw=assets[x['asset_id']]['parameters']['charger_kw'];end=x['actual_charge_end_min'];start=x['start_min']
        if end>start:
            total+=kw*(ol(start,end-10,lo,hi)+x['last_step_power_fraction']*ol(end-10,end,lo,hi))/60
    return total

def main():
    rows=read(OUT/'PAIR_BINDINGS10000.json')['records'];oldstage=BASE/'candidate_B_v41_20261016';oldrows={r['household_id']:r for r in read(oldstage/'PAIR_BINDINGS10000.json')['records']}
    counts=collections.Counter();mechanisms=collections.Counter();hist=collections.Counter();oldconflicts=collections.Counter();newconflicts=collections.Counter();errors=[];examples={};doses=collections.Counter()
    for ri,row in enumerate(rows):
        oldcases={c['date']:c for c in oldrows[row['household_id']]['rounds']};w=None;sigs=[]
        for r in row['rounds']:
            p=read(OUT/r['path']);old=read(oldstage/oldcases[p['date']]['path']);q=p['proposal'];counts['cases']+=1;mechanisms[q['realized_mechanism']]+=1;doses[q['actual_unique_dose_count']]+=1
            if w is None:w=read(A_STAGE/p['A_source']['world_path']);assets={d['asset_id']:d for d in w['parameter_pack']['devices']}
            act=next(d['activity']for d in p['days']if d['date']==p['date']);oldact=next(d['activity']for d in old['days']if d['date']==old['date']);sigs.append(canonical(act['member_calendars']))
            counts['member_calendar_cases_changed']+=act['member_calendars']!=oldact['member_calendars']
            counts['A_command_cases_unchanged']+=command_signature(p['A'])==command_signature(old['A'])
            if act['family_context']['member_dinners_min']!=oldact['family_context']['member_dinners_min']:errors.append([p['case_id'],'UNEXPECTED_DINNER_CHANGE'])
            for mid,journeys in act['protected_travel_ledger'].items():
                seq=act['member_calendars'][mid]
                for trip in journeys:
                    for t in range(trip['start_min'],trip['end_min'],10):
                        actual=next(x for x in seq if x['start_min']<=t<x['end_min'])
                        if actual['activity']!=trip['activity']or actual['location']!='outside':errors.append([p['case_id'],'TRAVEL_LOST'])
            if q['fallback_reason']or q['requested_mechanism']!=q['realized_mechanism']:errors.append([p['case_id'],'FALLBACK_REMAINS'])
            if p['VPP_events']!=old['VPP_events']:errors.append([p['case_id'],'EXOGENOUS_VPP_CHANGED'])
            if p['physical_results']is not None or any(v is not None for v in p['human_response'].values()):errors.append([p['case_id'],'FABRICATED_OUTCOMES'])
            evops=lambda plan:[x for x in plan['operations']if x['kind'].startswith('EV_')]
            if evops(p['A'])!=evops(p['B']):errors.append([p['case_id'],'EV_FILLER_OR_MOVED_VISIT'])
            counts['B_constraint_conflicts_kept']+=not p['assessment_B']['given_constraints_feasible'];counts['no_command_change_kept']+=q['same_command_as_A']
            for ch in q['changes']:
                if ch.get('selected_event_id')not in{e['event_id']for e in p['VPP_events']}:errors.append([p['case_id'],'ACTION_HAS_NO_EXACT_EVENT_BINDING'])
                if ch['device_family']!='ac':continue
                if ch['indoor_state_available']or ch['response_status']!='uncertain_pending_physics':errors.append([p['case_id'],'UNSUPPORTED_INDOOR_STATE'])
                counts['thermal_changes_read_back']+=1
                direction=ch['effective_request_direction']
                if ch['paused_minutes']:continue
                for aid in ch['affected_asset_ids']:
                    for t in range(ch['start_min'],ch['end_min'],10):
                        a=next((x for x in p['A']['controls']if x['kind']=='ac_setpoint'and x['asset_id']==aid and x['start_min']<=t<x['end_min']),None)
                        b=next((x for x in p['B']['controls']if x['kind']=='ac_setpoint'and x['asset_id']==aid and x['start_min']<=t<x['end_min']),None)
                        if a is None or b is None:continue
                        dh=b['heating_setpoint_C']-a['heating_setpoint_C'];dc=b['cooling_setpoint_C']-a['cooling_setpoint_C']
                        if b['cooling_setpoint_C']-b['heating_setpoint_C']<2.-1e-8:errors.append([p['case_id'],'ACTUAL_DEADBAND_BELOW2'])
                        if(direction=='up'and(dh< -1e-8 or dc>1e-8))or(direction=='down'and(dh>1e-8 or dc< -1e-8)):errors.append([p['case_id'],'ACTUAL_BOUND_DIRECTION_ERROR'])
            calculated=[]
            for e,ref in zip(p['VPP_events'],p['VPP_response_reference']['events']):
                aa=known_energy(p['A'],assets,e['start_min'],e['end_min']);bb=known_energy(p['B'],assets,e['start_min'],e['end_min']);sign=1 if e['direction']=='down'else-1
                response=sign*(aa-bb)*60/(e['end_min']-e['start_min']);calculated.append((e['event_id'],response));counts['event_windows_independently_integrated']+=1
                if abs(aa-ref['A_requested_known_kWh'])>1e-8 or abs(bb-ref['B_requested_known_kWh'])>1e-8 or abs(response-ref['requested_known_response_average_kw'])>1e-8:errors.append([p['case_id'],'KNOWN_ENERGY_REFERENCE_DISAGREES'])
            if len(calculated)>1:
                policy=q['multi_event_policy'];counts[policy]+=1
                if policy=='joint_all_events'and set(q['joint_event_ids_considered'])!={e['event_id']for e in p['VPP_events']}:errors.append([p['case_id'],'EVENT_NOT_CONSIDERED'])
                fv=next(v for eid,v in calculated if eid==q['focus_VPP_event_id']);ov=[v for eid,v in calculated if eid!=q['focus_VPP_event_id']]
                if fv>1e-8 and any(v<-1e-8 for v in ov):
                    newconflicts[policy]+=1;newconflicts[policy+'_'+q['requested_intensity_design']]+=1
                    deliberate=any(x.get('boundary_variant')in('opposing_or_excessive_response','beyond_deadline_overreaction')for x in q['changes'])
                    if deliberate:newconflicts[policy+'_explicit_adverse_variant']+=1
                    examples.setdefault('new_known_window_conflict_'+policy,{'case_id':p['case_id'],'path':r['path'],'requested_level':q['requested_intensity_design'],'changes':q['changes'],'responses':calculated})
                oldrefs=old['VPP_response_reference']['events'];oldfocus=old['proposal']['focus_VPP_event_id'];oldf=next(x['requested_known_response_average_kw']for x in oldrefs if x['event_id']==oldfocus)
                if oldf>1e-8 and any(x['requested_known_response_average_kw']<-1e-8 for x in oldrefs if x['event_id']!=oldfocus):oldconflicts['all']+=1
            if p['case_id']in('ordinary-v6-0001__2025-03-15','ordinary-v6-0251__2025-09-25','ordinary-v6-0369__2025-12-01'):
                examples[p['case_id']]={'path':r['path'],'meal_appointments':act['meal_appointments'],'proposal':q,'known_event_responses':calculated,'constraint_flags':p['assessment_B']['constraint_flags']}
        hist[len(set(sigs))]+=1
        if(ri+1)%200==0:print({'four_point_households':ri+1,'errors':len(errors)},flush=True)
    original_ids={r['household_id']for r in read(MASTER/'SUBSET50.json')['records']};subset=read(OUT/'SUBSET50.json');new_ids={r['household_id']for r in subset['records']}
    main_byid={r['household_id']:r for r in rows}
    if original_ids!=new_ids or any(r!=main_byid[r['household_id']]for r in subset['records']):errors.append(['SUBSET_NOT_EXACT_MASTER_RECORDS'])
    report={'accepted':not errors and counts['cases']==10000,'counts':dict(counts),'errors':errors,'realized_mechanisms':dict(mechanisms),'household_actual_member_calendar_shapes':dict(hist),'actual_unique_dose_counts':dict(doses),'previous_B41_known_focus_positive_other_negative':dict(oldconflicts),'current_known_focus_positive_other_negative':dict(newconflicts),'subset50_exact_main_records':not original_ids.symmetric_difference(new_ids),'subset50_type_counts':subset['type_counts'],'rules_sha256':rules_id(),'full_physical_acceptance':False,'review_scope':'actual commands and analytical fixed-program/EV projection;not HVAC/tank/full-B-state physics'}
    save(OUT/'FOUR_POINT_REVIEW.json',report);save(OUT/'review/四项修改前后具体案例.json',examples);print(canonical(report))
    if not report['accepted']:raise SystemExit(2)
if __name__=='__main__':main()
