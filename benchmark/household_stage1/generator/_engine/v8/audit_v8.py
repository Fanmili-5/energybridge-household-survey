"""Independent eight-country source and reference-week admission checks."""
from pathlib import Path
from collections import Counter,defaultdict
from copy import deepcopy
from itertools import combinations
import importlib.util,json,sys,math,hashlib

BASE=Path(__file__).resolve().parent.parent
ROOT=Path(__file__).resolve().parent
OLD=BASE/'v7'
ADMITTED=BASE/'admitted'
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
prior=load('independent_admitted_250',ADMITTED/'audit_new_countries.py')
raw=load('independent_raw_eight',OLD/'audit_raw.py')
life,controls,service=prior.life,prior.controls,prior.service
need=prior.need
WORK=prior.WORK
F=prior.F
COUNTRIES=('CN','US','GB','ES','IN','MX','AU','DE')
ALLOCATION={'CN':dict(zip('ABCDEF',(21,25,15,19,20,25))),'US':dict(zip('ABCDEF',(21,25,16,18,19,26))),
 'GB':dict(zip('ABCDEF',(21,25,15,19,20,25))),'ES':dict(zip('ABCDEF',(20,25,16,19,20,25))),
 'IN':dict(zip('ABCDEF',(21,25,15,19,19,26))),'MX':dict(zip('ABCDEF',(20,25,16,19,19,26))),
 'AU':dict(zip('ABCDEF',(21,24,16,19,20,25))),'DE':dict(zip('ABCDEF',(21,24,16,19,19,26)))}

def raw_sources():
    s=raw.load_sources();extra=prior.raw_sources()
    s.update({k:v for k,v in extra.items() if k not in ('es','es_meta')})
    s['es_meta']=s['meta']
    return s

def cn_check(c,s):
    h=c['household'];x=s['china'][c['source']['household_key']];es=h['calendar']['weekly_events']
    # Reuse the frozen source decoder only on a source-interval view. Concrete
    # operational ages and missing respondent linkage are checked separately.
    view=deepcopy(c)
    for m in view['household']['members']:
        y=m['source_birth_year'];m['age_band']=[max(0,2011-y),2012-y]
    view['household']['source_respondent_member_id']=h['source_record_anchor_member_id']
    raw.audit_case(view,s)
    heads=[]
    for m in h['members']:
        slot=int(m['source_person_key'].split(':')[-1]);rel=int(x[f'a2_{slot}_a']);born=int(x[f'a2_{slot}_c'])
        need(m['relationship_to_head']==rel,'CN source kinship code changed')
        need(m['source_age_band']==[max(0,2011-born),2012-born],'CN source birth interval lost')
        need(m['source_age_band'][0]<=m['reference_age']<=m['source_age_band'][1],'CN concrete age incompatible with source birth year')
        if rel==1:heads.append(m)
    need(len(heads)==1 and heads[0]['reference_age']>=18,'CN unique adult record anchor missing')
    head=heads[0];year=head['source_birth_year'];sp=[m for m in h['members'] if m['relationship_to_head']==2]
    for m in h['members']:
        rel=m['relationship_to_head'];born=m['source_birth_year']
        if rel in (3,8):need(year-born>=(12 if rel==3 else 24),'CN upward generation age requires verification')
        if rel in (5,9):need(born-year>=(12 if rel==5 else 24),'CN downward generation age requires verification')
        if rel==4 and len(sp)==1:need(sp[0]['source_birth_year']-born>=12,'CN spouse parent age requires verification')
        if rel==2:need(m['reference_age']>=18,'CN ordinary-cohort spouse age')
    need(h['source_record_anchor_member_id']==head['id'] and h['source_respondent_member_id'] is None,'CN head falsely linked as interview respondent')
    need(h['source_respondent_binding']['status']=='not_linked','CN missing respondent linkage hidden')
    need(c['source']['household_key'] not in ('216','1102'),'CN known unresolved source record reintroduced')
    count=x['a3b'];count=None if count is None or not math.isfinite(count) else int(count)
    need(c['source_presence_details']['reported_teleworker_count']['value']==count,'CN teleworker source count changed')
    remote={e['member_id'] for e in es if e['kind']=='work' and e['location']=='home'}
    if count is not None:need(len(remote)==count,'CN reported teleworker count not preserved by reference allocation')
    reported=x['a3a'];reported=None if reported is None or not math.isfinite(reported) else int(reported)
    need(c['source_presence_details']['reported_usual_all_day_person_count']['value']==reported,'CN usual all-day count dropped')
    adults=[m['id'] for m in h['members'] if m['reference_age']>=18]
    for d in range(5):
        if x['a3']==1:need(any(life.home(es,mid,d*1440+540,d*1440+900) for mid in adults),'CN positive usual-home operational bridge lost')
        if x['a3']==2:need(not any(life.home(es,mid,d*1440+540,d*1440+1020) for mid in adults),'CN source not-all-day contradicted by full-home adult')
    need(h['calendar']['source_presence_compatibility']['CN_count_not_claimed_actual_reference_diary'],'CN usual count falsely claimed as person-day diary')

def europe_check(c,s):
    raw.audit_case(c,s)
    h=c['household'];x=s['es'][c['source']['household_key']];meta=s['meta'];ms=h['members']
    need(meta.column_names_to_labels['S1Ac1'].startswith('Women') and meta.column_names_to_labels['S1Bc1'].startswith('Men'),'ENABLE primary sex-bin semantics')
    expected=[int(x[f'S1{sex}c{age}']) for sex in 'AB' for age in (1,2,3)]
    bands=[];sexes=[]
    for i,count in enumerate(expected):
        bands.extend([[(0,18),(18,65),(66,None)][i%3]]*count);sexes.extend(['female' if i<3 else 'male']*count)
    need([m.get('sex_from_source') for m in ms]==sexes,'ENABLE sex-bin mapping reversed')
    for m,b in zip(ms,bands):need(m['source_age_band']==list(b) and m['reference_age']>=b[0] and (b[1] is None or m['reference_age']<=b[1]),'ENABLE age-bin semantics')
    fridge=c['additional_devices']['fridge_available'];v=x['H11D']
    need(fridge['fields']==['H11D'] and fridge['value']==(v in (1,2,4) if v in (1,2,4,5) else None),'ENABLE fridge incorrectly bound to cooker')
    v=x['H11G'];need(c['source_technology_presence']['standalone_electric_water_heater']['value']==(v in (1,2,4) if v in (1,2,4,5) else None),'ENABLE subtype negative erased')
    need(c['devices']['water_heater_available']['value']==(True if v in (1,2,4) else None),'ENABLE no electric boiler inferred no generic hot water')
    mid=h['source_respondent_member_id'];daily=[prior.home_minutes(h['calendar']['weekly_events'],mid,d)>=270 for d in range(5)]
    if x['C4G']==5:need(all(daily),'ENABLE personal high-home answer not respected')
    if x['C4G'] in (1,2):need(sum(daily)<=2,'ENABLE personal low-home answer not respected')
    if x['C4G'] in (1,2,3,4,5):need(c['known_presence']['value']['source_respondent_home_constraint_item']==int(x['C4G']),'ENABLE personal item rewritten as household presence')
    else:need(c['known_presence']['value'] is None and c['known_presence']['status']=='unknown','ENABLE missing personal home item invented')
    need(c['source']['survey_year'] is None and c['source']['release_year']==2019,'ENABLE release falsely labelled interview year')

def check_source(c,s):
    co=c['source']['country']
    if co in ('AU','DE'):return prior.check_source(c,s)
    if co=='CN':cn_check(c,s)
    elif co in ('GB','ES'):europe_check(c,s)
    else:raw.audit_case(c,s)
    if co=='IN':
        x=s['india'][c['source']['household_key']];frequency=int(raw.n(x['q473_wash_mach_week_use_no']))
        need(c['source_laundry_weekly_uses']['value']==frequency==c['household']['routine']['laundry_cycles_per_week'],'IRES measured weekly washer-use count overwritten by default')
        need(c['household_provenance']['routine.laundry_cycles_per_week']['status']=='derived','IRES operational cycles claimed exact observed programme diary')
    for m in c['household']['members']:
        band=m['source_age_band'];need(m['reference_age']>=band[0] and (band[1] is None or m['reference_age']<=band[1]),'reference age outside source interval')
        if co=='MX' and m.get('observed_age')==98:need(m['observed_age_is_censored_lower_bound'] and band==[98,None],'Mexico top-coded age asserted exact')
    return True

def check_case(c,s,old=None):
    if c['source']['country'] in ('AU','DE'):return prior.check_case(c,s,old)
    if old is None:old=c
    check_source(c,s);life.check(c,s,old)
    h=c['household'];es=h['calendar']['weekly_events'];actor=h['decision_maker_id']
    for m in h['members']:need(m['age_band']==[m['reference_age']]*2,'operational age not concrete')
    role=c['benchmark_role']
    if role in 'AF':need(any(e['member_id']==actor and e['kind']=='work' and e['location']=='away' for e in es),'commuting role without commute')
    if role in 'BE':need(all(life.home(es,actor,d*1440+540,d*1440+900) for d in range(5)),'home/care actor away during role window')
    if role=='E':
        link=h['role_care_binding'];expected='observed' if c.get('care_context',{}).get('value') else 'benchmark_assigned'
        need(link['caregiver_id']==actor and link['status']==expected,'care role binding')
        need(any(m['id']==link['child_id'] and m['reference_age']<12 for m in h['members']),'care role no age-compatible child')
    if role=='C':
        starts=[min((e['start']%1440 for e in es if e['member_id']==actor and e['start']//1440==d and e['kind'] in ('work','community_program')),default=None) for d in range(5)]
        need(len(set(v for v in starts if v is not None))>=2,'variable role has fixed reference week')
    template=c['routine'].get('personal_commute_scenario')
    if template:
        e=next((e for e in es if e['member_id']==actor and e['kind']=='work' and e['location']=='away'),None)
        if e:need([template['depart_minutes'],template['return_minutes']]==[e['start']%1440,e['end']%1440],'commute template and calendar differ')
    for day in h['routine']['daily_services']:
        need(day['manual_operation_opportunities'],'no usable manual operation opportunity')
        for op in day['manual_operation_opportunities']:
            a,b=[day['day']*1440+op[k] for k in ('start','end')];mid=op['member_id']
            need(b-a>=10 and life.available(es,mid,a,b),'manual operation collides with commitment')
            need(day['flexible_chore_window'][0]<=op['start']<op['end']<=day['flexible_chore_window'][1] and mid in day['chore_member_ids'],'manual opportunity outside declared window/actor')
            for meal in day['meals']:
                if mid in meal['participants']:need(not life.intersects(a,b,day['day']*1440+meal['start'],day['day']*1440+meal['end']),'manual operation collides with meal')
            for e in es:
                if e['member_id']==mid and e['kind']=='escort':need(not life.intersects(a,b,e['start']-15,e['end']+15),'manual operation in escort buffer')
    auth=h['decision_authorization'];need(auth['status']=='benchmark_assigned' and not auth['real_family_consent_observed'],'reference authority claimed actual consent')
    if h.get('ev'):need(auth['ev_driver_id']==h['ev']['vehicle_user_member_id'] and auth['ev_adjustment_authorization'],'EV authority missing')
    if 'control_inventory' in h:
        need(old is not c,'control audit needs pre-intervention baseline');controls.check_revision(c,old);service.check(c)
    return True

def check_population(rows):
    need(len(rows)==1000 and len({c['case_id'] for c in rows})==1000,'unified 1000 unique case IDs')
    need(len({(c['source']['dataset'],c['source']['household_key']) for c in rows})==1000,'survey household reused')
    need(set(c['source']['country'] for c in rows)==set(COUNTRIES),'eight-country set')
    for c in rows:
        need(not any(k in c for k in ('acceptance_label','observed_response','human_answer','population_acceptance_probability')),'human/outcome labels in household input')
    for co in COUNTRIES:
        cs=[c for c in rows if c['source']['country']==co]
        need(len(cs)==125 and Counter(c['benchmark_role'] for c in cs)==Counter(ALLOCATION[co]),'country-role quota '+co)
        for r in 'ABCDEF':
            cell=[c for c in cs if c['benchmark_role']==r];sizes=Counter(c['household']['controlled_function_count'] for c in cell)
            need(set(sizes)=={4,5,6} and max(sizes.values())-min(sizes.values())<=1,'country-role 4/5/6 balance '+co+r)
            exposure=Counter(f for c in cell for f in c['household']['controlled_function_ids']);need(set(exposure)==set(F) and min(exposure.values())>=2,'cell target-function exposure '+co+r)
    report=controls.check_population(rows)
    frozen={c['case_id']:c for c in (json.loads(x) for x in (ADMITTED/'output/household_cases.jsonl').read_text().splitlines())}
    need(all(c==frozen[c['case_id']] for c in rows if c['source']['country'] in ('AU','DE')),'admitted AU/DE changed')
    return report
