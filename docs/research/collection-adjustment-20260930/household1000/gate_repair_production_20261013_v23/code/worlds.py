"""Source anchors unchanged; replace the common activity/resource foundation."""
import collections,copy,datetime as dt
from common import *
from activity_model import configure,dated,ranges
from joint_age import project
USAGE_KEYS={'earliest_h','preferred_h','latest_h','arrival_h','departure_h','daily_drive_kwh'}
merge_ranges=ranges
PROTOCOL={'schema':'eb.coherent_reference_rules.v22','population':'unchanged city ordinary residential household anchors; towns/rural excluded',
    'living_day':[480,1920],'time_grid_min':10,'source_work_unknown_preserved':True,
    'activity_selection':'declared balanced eligible reference levels; not fitted Chinese joint diary probabilities',
    'source_registry':'RULE_EVIDENCE.json','room_calendar_single_authority':True,
    'WHO_under5_sleep_bounds':'normative healthy reference bounds, not observed distributions',
    'EB_hardware_parameter_contract':'V18 native generic bundle retained; transport/service usage is a separate given contract',
    'joint_age':'source joint five-year gap block; exact ages are projected design; parentage subtype remains unknown',
    'service_bounds':'independent purpose before A, no operator windows; explicit given experimental contracts',
    'request_and_realization':'finite-state execution separate from proposed instructions',
    'fixed_original_dates':True,'same_original50_only_EP':True,'human_answers':0}
def build(src):
    w=copy.deepcopy(src);hid=w['household_id'];oldhash=w.pop('world_content_sha256')
    w['source_V19_world_content_sha256']=oldhash
    w=project(w)
    w['source_V18_activity_evidence']={'weekly_calendar':[{'member_id':m['member_id'],'scenario':m['reference_activity_role']} for m in w['members']],
        'not_active_calendar':True,'audit':'design_realism_audit_20261008_v1'}
    if 'control_defaults' in w['parameter_pack']:w['source_EB_control_defaults_evidence']=w['parameter_pack'].pop('control_defaults')
    w=configure(w)
    for d in w['parameter_pack']['devices']:
        if 'ac' in d['types']:d['max_power_status']='rated-point reference metadata; actual offdesign circuit power is separately checked in original50 SQL'
    w['given_external_services']['childcare']=copy.deepcopy(w['care_contract'])
    w['given_external_services']['transport']='dated journey and resource contract; no fixed daily trip imputed from employment unknown'
    w['routine'].pop('EV_daily_trip_kWh',None);w['routine'].pop('EV_trip_days',None)
    w['routine']['stable_habit_variation_level']=rank(hid,'stable-habits')%3
    w['routine']['time_source']='activity_model.dated -> one member/room/care calendar -> service,operations,A/B,IDF and displayed dated role'
    w['service_semantics']['mandatory_services']['transport']='dated given traction energy; separate retained85% access target; idle dates allowed'
    w['service_semantics']['mandatory_services']['cooling']='given26C occupied-room control, including given sleeping/nap service; subjective comfort unknown'
    w['service_semantics']['usual_arrangements']['family_meals_and_baths']='dated age/care/resource context, not an observed weekly diary'
    w['service_semantics']['negotiable_conditions']['extra_handling']='same dated operator and care commitments; additional action and extra help willingness remain unknown'
    w['active_clock_authority']='dated activity model + episode absolute ledger; no legacy flat or weekly calendar drives dated generation'
    w['baseline_assistance_contract']={'provider_id':hid+':given_baseline_handling_service','window_min':[600,1260],
        'authorization':'only exact A appointments pre-booked before B; additional B appointments require negotiation',
        'kind':'given experimental resource; not observed availability or nationwide service', 'cost':None}
    w['parameter_pack_sha256']=digest(w['parameter_pack'])
    exemplar=[dated(w,dt.date(2025,2,17)+dt.timedelta(days=i)) for i in range(7)]
    for m in w['members']:
        mid=m['member_id'];m['weekly_calendar']=[{'weekday':i,'example_date':x['date'],'day_type':x['day_type'],'intervals':x['member_calendars'][mid]} for i,x in enumerate(exemplar)]
        m['daily_reference_specs']=[{'weekday':i,'example_date':x['date'],**x['member_specs'][mid]} for i,x in enumerate(exemplar)]
        m['weekly_calendar_is_exemplar_not_date_authority']=True
    for o in w['operating_context']['operators']:
        o['weekly_windows_min']={str(i):x['operator_windows_min'][o['operator_id']] for i,x in enumerate(exemplar)}
        o['evidence']='example windows only; actual operator/room/care constraints come from saved dated activity day'
    w['routine']['weekly_family_context']=[{'weekday':i,'example_date':x['date'],**x['family_context']} for i,x in enumerate(exemplar)]
    w['profile_to_world_reason_trace']={'source':'same roster/relationship/housing/date/device coverage; work evidence remains source-aware',
        'activity':'source eligibility + declared activity/care scenario and normative age bounds + dated national/prototype school calendar',
        'room':'single person location in each10min slot, with actual handling visits; accessible household rooms only',
        'operator':'same dated calendar minus work/commitments/meals/sleep/care',
        'services':'dated rooms,bathing appointments,journeys and handling -> common needs and fixed A',
        'B':'same needs/assets/care contracts; intervention only after notice; bad plans retained, no actor labels',
        'physics':'same dated occupancy, lighting and control authority for compiled pairs and actual SQL checks'}
    w['schema']='eb.coherent_reference_world.v22';w['repair_rules_sha256']=digest(PROTOCOL);w['world_content_sha256']=digest(w)
    return w

def main():
    school_guard();sel=read(SOURCE/'SELECTION1000.json');rows=[];roles=collections.Counter();care=collections.Counter();ev=collections.Counter()
    for h in sel['records']:
        src=read(SOURCE/h['world_path']);w=build(src);path=OUT/'worlds'/f'{w["household_id"]}.json';save(path,w)
        assert all(w[k]==src[k] for k in ('N','G','H6','H7','random10_date_selection','ego_relationships'))
        assert all(w['layout'][k]==src['layout'][k] for k in ('rooms','access','metric_outer_rect_m'))
        roles.update(m['reference_activity_role'] for m in w['members'])
        care['resident_home_care']+=bool(w['care_contract']['caregiver_is_resident'])
        care['given_external_home_care']+=bool(w['care_contract']['home_care_child_ids'] and not w['care_contract']['caregiver_is_resident'])
        if 'given_transport_contract' in w:ev[w['given_transport_contract']['mode']]+=1
        rows.append({**{k:copy.deepcopy(v) for k,v in h.items() if k not in ('rounds','world_sha256','parameter_pack_sha256')},
            'world_path':str(path.relative_to(OUT)),'world_sha256':sha(path),'parameter_pack_sha256':w['parameter_pack_sha256'],
            'source_V19_world_sha256':sha(SOURCE/h['world_path'])})
    save(OUT/'WORLD_BINDINGS1000.json',{'households':len(rows),'records':rows});save(OUT/'PROTOCOL.json',PROTOCOL)
    save(OUT/'WORLD_BUILD_REVIEW.json',{'households':len(rows),'members':sum(roles.values()),'activity_scenarios':dict(roles),
        'transport_contracts':dict(ev),'home_care_contracts':dict(care),'anchors_and_dates_preserved':True,
        'joint_age_changed_members':sum(read(OUT/x['world_path'])['joint_age_evidence']['changed_members'] for x in rows),
        'scientific_joint_diary_calibration':False,'human_answers':0})
    print(read(OUT/'WORLD_BUILD_REVIEW.json'),flush=True)
if __name__=='__main__':main()
