"""Country-balanced role assignment under immutable survey constraints."""
from collections import defaultdict,Counter
from copy import deepcopy
import json,sys
from common import *

components,activity,weekend,control,services=libraries()


def make_case(row,role,pair=None):
    c=deepcopy({k:v for k,v in row.items() if k not in ('anchors','block')})
    ident=c['pool_id'];c.update(case_id='EB7-'+role+'-'+rank(ident,role)[:16],benchmark_role=role,
           role_card_id=components.seed.ROLE_NAMES[role],role_status='benchmark_assigned',
           schema_version='household_step1_v7',benchmark_view='household',source_pool_id=ident,
           previous_case_id='SOURCE:'+ident)
    c['care_context']=deepcopy(row.get('anchors',{}).get('E',fact(None,[],'unknown')))
    c['source']['catalogue_id']=c['source']['dataset']
    if c['source']['dataset']=='CRECS2012':
        c['source']['fieldwork_year']=None
        c['source_person']['source_person_basis']='first source roster member, not independently verified questionnaire respondent'
    c['role_anchor']=fact({'days_to_work_or_study':5,'definition':'conditional reference role, not inferred natural household type'},[],'benchmark_assigned')
    if role=='A':
        frequency=c['source_person'].get('commute_frequency',{}).get('value')
        if frequency is not None and frequency>0:c['role_anchor']=fact({'days_to_work_or_study':frequency},c['source_person']['commute_frequency']['fields'])
    c['attitudes']=fact({k:v for k,v in components.seed.ROLE_SPECS[role].items() if k not in ('core','routine','thermal_rule')},[],'benchmark_assigned',role_definition_source='original_EB_role_card')
    c['routine']=components.seed.routine(role,ident,c['role_anchor'],pair)
    c['conditions']=fact({'role_life_requirements':'checked against source-compatible members and reference week',
                         'care_is_observed_only_when_explicit_source_link_exists':True,
                         'EV_and_commute_are_reference_conditions_unless_separately_observed':True},[],'benchmark_assigned')
    c['evidence_scope']={'household_identity':'source_survey_household','role_and_attitudes':'controlled_experimental_assignment',
                        'population_weight':None,'source_survey_weights_used':False,'global_representativeness':False}
    c['family_constraints']={'required_services_must_be_preserved':True,'personal_schedule_does_not_imply_whole_house_vacancy':True,'role_definition_id':c['role_card_id']}
    c['card']=components.seed.effective_card(c)
    if pair:c['cd_pair_id']=pair;c['matching_block']=deepcopy(row['block'])
    return c


def initialize(c,ordinal,alternative=0):
    h={};p={};c['household']=h;c['household_provenance']=p;ds=c['source']['dataset'];role=c['benchmark_role']
    if ds=='CRECS2012':
        ms=[]
        for item in c['members_summary']['value']:
            mid='M'+str(len(ms)+1).zfill(2);lo,hi=item['age_band']['value'];detail=c['source_member_details'][item['person_key']]
            job=detail['employment']['value'] or ('not_in_workforce' if hi<18 else 'not_employed')
            if hi<18 and job in WORK:raise ValueError('source working minor excluded from reference schooling cohort')
            m={'id':mid,'age_band':[lo,hi],'source_person_key':item['person_key'],'source_birth_year':item['birth_year']['value'],
               'employment':job,'school_enrolled':6<=lo and hi<18,'activity':'home_activity','work_mode':'not_applicable'}
            if item['sex_code']['value'] in (1,2):m['sex_from_source']='male' if item['sex_code']['value']==1 else 'female'
            ms.append(m);components.from_fact(p,f'members.{mid}.age_band',item['age_band'])
            components.from_fact(p,f'members.{mid}.employment',detail['employment'])
            activity.tag(p,f'members.{mid}.school_enrolled','reference education status; enrollment not measured')
        respondent=ms[0];actor=respondent
    else:
        ms,actor,respondent=components.roster(c,p)
    adults=[m for m in ms if m['age_band'][0]>=18]
    if ds=='ENABLE_EU':
        demo=c['respondent_demographics'];sex=demo['sex']['value'];birth=demo['birth_year']['value']
        # Broad CORDIS727524 project-period screen; individual interview year remains unknown.
        choices=[m for m in adults if m.get('sex_from_source')==sex and (birth is None or max(m['age_band'][0],2015-birth)<=min(m['age_band'][1],2019-birth))]
        if not choices:raise ValueError('ENABLE sex/birth-year incompatible with adult roster')
        bound=next((m for m in choices if m['id']==respondent['id']),choices[0])
        if bound is not respondent:
            bound['employment']=respondent['employment'];p[f"members.{bound['id']}.employment"]=deepcopy(p[f"members.{respondent['id']}.employment"])
            respondent['employment']='not_employed';respondent['school_enrolled']=False
            activity.tag(p,f"members.{respondent['id']}.employment",'unmeasured co-resident pending joint coverage-design')
        respondent=bound;respondent['source_birth_year']=birth
        if respondent['employment']=='student':respondent['school_enrolled']=True
        activity.tag(p,'source_respondent_binding','sex/age-bin compatibility under broad2016-2019 project-period screen; individual interview year and identity among compatible slots unverified',['S5','S4'],'benchmark_assigned')
    h.update(members=ms,decision_maker_id=actor['id'],source_respondent_member_id=respondent['id'],country=c['source']['country'],
             equipment=components.equipment(c,p),calendar={},routine={},care_arrangements=[],ev={},attitudes=deepcopy(c['attitudes']['value']),
             role_id=c['role_card_id'],role_name=c['card']['core'],medical_service_must_not_be_interrupted=c['source_person'].get('medical_device',{}).get('value') is True)
    if ds=='CRECS2012':
        area=c['dwelling']['size']['value'];lo=area['lower_m2'];hi=area['upper_m2'];ref=round((lo+hi)/2,1) if hi else 280
        h['dwelling']={'type':'reference_apartment','reference_area_m2':ref,'source_size_measure':'crecs_gross_floor_area_band','area_is_reference_input':True}
        activity.tag(p,'dwelling.type','urban apartment reference; building height is not measured morphology',['b2'])
        activity.tag(p,'dwelling.reference_area_m2','within-band reference area; interval midpoint is not observed area',['b13'])
    else:h['dwelling']=components.dwelling(c,p)
    if h['dwelling']['reference_area_m2']<25:raise ValueError('reference dwelling below25m2; six-function installation layout unsupported in this cohort')
    activity.jointly_assign(c,ordinal,alternative)
    def known(m):return p[f"members.{m['id']}.employment"]['status'] in ('observed','survey_imputed')
    if role in 'AF':
        def working_age(m):
            if m.get('observed_age') is not None:return 18<=m['observed_age']<65
            if ds=='CRECS2012':return 18<=m['age_band'][0] and m['age_band'][1]<65
            if not 18<=m['age_band'][0]<65:return False
            if ds=='ENABLE_EU' and m['id']==respondent['id'] and m.get('source_birth_year'):
                y=m['source_birth_year'];return max(m['age_band'][0],2015-y)<=min(64,m['age_band'][1],2019-y)
            return True
        options=[m for m in adults if working_age(m) and not m['school_enrolled'] and (m['employment'] in WORK or not known(m)) and not(m['id']==respondent['id'] and c['source_person'].get('commute_frequency',{}).get('value')==0)]
        options.sort(key=lambda m:(not known(m),m['id']))
        if not options:raise ValueError('commuting role lacks source-compatible working-age actor')
        actor=options[0]
        if actor.get('observed_age') is None and actor['age_band'][1]>64:
            actor['age_band']=[actor['age_band'][0],64]
            activity.tag(p,f"members.{actor['id']}.age_band",'reference working-age sub-band inside source coarse group; exact age unmeasured')
        if not known(actor):
            actor['employment']='employed_full_time';activity.tag(p,f"members.{actor['id']}.employment",'joint coverage-design: reference working commuter; source employment unmeasured')
        actor.update(work_mode='onsite',activity='work',school_enrolled=False)
    elif role in 'BE':
        options=[m for m in adults if not m['school_enrolled'] and (m['employment'] not in WORK or not known(m))]
        if role=='E' and c['care_context']['value']:
            actual=c['care_context']['value']['adult_caregiver_key'];options=[m for m in options if m.get('source_person_key')==actual]
        options.sort(key=lambda m:(not known(m),m['id']))
        if not options:raise ValueError('home/care role lacks source-compatible resident actor')
        actor=options[0]
        if not known(actor):
            actor['employment']='home_caregiver' if role=='E' else 'not_employed'
            activity.tag(p,f"members.{actor['id']}.employment",'joint coverage-design: explicit reference home/care actor, source employment unmeasured')
        actor.update(work_mode='not_applicable',activity='care' if role=='E' else 'home_activity',school_enrolled=False)
    else:actor=respondent if respondent['age_band'][0]>=18 else adults[0]
    h['decision_maker_id']=actor['id']
    activity.tag(p,'decision_maker_id','eligible experimental role actor; source respondent remains separately identified')
    if role=='A' and actor['id']!=respondent['id']:
        c['role_anchor']=fact({'days_to_work_or_study':5,'definition':'reference commute of the assigned actor; respondent commute is separate'},[],'benchmark_assigned')
        c['routine']=components.seed.routine(role,c['pool_id'],c['role_anchor'])
    if role=='E':
        children=[m for m in ms if m['age_band'][1]<18]
        if not children:raise ValueError('care role requires source-supported co-resident child')
        child=(next(m for m in children if m.get('source_person_key')==c['care_context']['value']['child_key'])
               if c['care_context']['value'] else min(children,key=lambda m:m['age_band'][0]))
        if child['age_band'][1]>=12 and p[f"members.{child['id']}.age_band"]['status']=='benchmark_assigned':
            child['age_band']=[6,11];activity.tag(p,f"members.{child['id']}.age_band",'reference school-age care sub-band inside source child group; exact age not observed')
        if child['age_band'][1]>=12 and not c['care_context']['value']:raise ValueError('no supported younger-child care condition')
        h['role_care_binding']={'caregiver_id':actor['id'],'child_id':child['id'],'status':'observed' if c['care_context']['value'] else 'benchmark_assigned',
                                'not_inferred_from_country':True,'reference_responsibility_is_not_source_care_measurement':not bool(c['care_context']['value'])}
    activity.equipment_detail(c)
    h['comfort']={'preferred_cooling_c':[24,25] if role=='B' else [24,26],'allowed_short_adjustment_c':{'A':1,'B':0.5,'C':1,'D':2,'E':0.5,'F':1}[role],'comfort_ceiling_c':26} if h['equipment']['space_ac_available']['present'] else {}
    activity.tag(p,'comfort','original EB reference role bounds, not measured preference')
    h['routine']={'laundry_cycles_per_week':c.get('source_laundry_cycles_per_week') or 3,'laundry_must_complete_whole_cycles':True,
                  'care_protection_windows':c['routine'].get('care_protection_windows_minutes',[])}
    activity.tag(p,'routine.laundry_cycles_per_week','reference whole-cycle weekly demand; source frequency retained separately')
    if h['equipment']['home_vehicle_charging']['present'] or role=='F':
        charger=c['source_person'].get('charger_type',fact(None,[],'unknown'));typ=charger['value'] or 'Level_2'
        h['ev']={'reference_powertrain':'battery_electric','charger_type':typ,'reference_charger_kw':1.44 if typ=='Level_1' else 3.6,'reference_battery_kwh':60,
                 'arrival_soc':0.5,'departure_soc_target':0.8,'charge_efficiency':0.9,'vehicle_user_member_id':actor['id'],
                 'commute_use':'conditional_personal_mobility_experiment','charging_contiguity':'one_continuous_session_is_required_for_base_need'}
        if charger['value']:components.from_fact(p,'ev.charger_type',charger)
        else:activity.tag(p,'ev.charger_type','reference charger, not inferred from absent survey field')
    h['role_condition_binding']={'role':role,'actor_id':actor['id'],'actor_employment_status':p[f"members.{actor['id']}.employment"]['status'],
                                'source_actual_role_measured':False,'country_used_to_choose_role':False,
                                'conditional_reference_EV':role=='F','source_home_EV_observed':c['devices']['home_vehicle_charging']['value'] is True}
    return c


def build_week(c,ordinal,rotation=0):
    events,targets,nights=activity.build_activities(c)
    events=weekend.apply(c,events,targets,ordinal+rotation)
    activity.schooling_and_care(c,events);activity.accompany_school_runs(c,events);activity.build_services(c,events);activity.refresh_supervision(c,events);activity.finalize_calendar(c,events,targets,nights)
    return c


def role_checks(c):
    h=c['household'];actor=next(m for m in h['members'] if m['id']==h['decision_maker_id']);es=h['calendar']['weekly_events'];role=c['benchmark_role']
    if actor['age_band'][0]<18:raise ValueError('decision maker must be an adult')
    if role in 'AF' and not(actor['employment'] in WORK and any(e['member_id']==actor['id'] and e['kind']=='work' and e['location']=='away' for e in es)):raise ValueError('reference commuter is not actually commuting')
    if role in 'BE' and any(not activity.at_home(es,actor['id'],d*1440+540,d*1440+900) for d in range(5)):raise ValueError('reference home/care actor not available across weekday daytime')
    if c['source']['dataset']=='CRECS2012' and (c['known_presence']['value'] or {}).get('normally_someone_home_all_day'):
        for d in range(5):
            if not any(activity.at_home(es,m['id'],d*1440+540,d*1440+900) for m in h['members'] if m['age_band'][0]>=18):raise ValueError('source all-day presence unsupported by reference week')




