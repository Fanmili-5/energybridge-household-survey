"""Eight-country household references with immutable survey facts."""
from pathlib import Path
from collections import Counter
from copy import deepcopy
import json
import math
import sys

BASE=Path(__file__).resolve().parent.parent
ROOT=Path(__file__).resolve().parent
OLD=BASE/'v7'
ADMITTED=BASE/'admitted'
sys.path.insert(0,str(ADMITTED))
import country_adapter as shared
from country_adapter import fact,save,sha,rank,write_rows,load_module,dumps
legacy,components,activity,weekend,control,services=(shared.legacy,shared.components,shared.activity,shared.weekend,shared.control,shared.services)
WORK=shared.WORK
KEY=shared.KEY
COUNTRIES=('CN','US','GB','ES','IN','MX','AU','DE')
ALLOCATION=json.loads((BASE/'COUNTRY_ROLE_ALLOCATION.json').read_text())
ROLE_QUOTAS={'A':166,'B':198,'C':125,'D':151,'E':156,'F':204}

def clean(value):
    return None if isinstance(value,float) and not math.isfinite(value) else value

def ordinary_kinship_issues(row):
    people=row['members_summary']['value']
    heads=[m for m in people if m['relationship_to_head']['value']==1]
    if len(heads)!=1:return [{'rule':'source_head_not_unique','head_count':len(heads)}]
    head=heads[0];year=head['birth_year']['value'];issues=[]
    if head['age_band']['value'][0]<18:issues.append({'rule':'head_is_minor_outside_current_anchor_adapter'})
    spouses=[m for m in people if m['relationship_to_head']['value']==2]
    for m in people:
        relation=m['relationship_to_head']['value'];born=m['birth_year']['value'];gap=year-born
        anchor=head
        if relation in (3,8):
            minimum=12 if relation==3 else 24
            if gap<minimum:issues.append({'rule':'parent_generation_age_requires_verification','person_key':m['person_key'],'relation':relation,'birth_year':born,'head_birth_year':year,'minimum_reference_generation_gap':minimum})
        elif relation in (5,9):
            minimum=12 if relation==5 else 24
            if born-year<minimum:issues.append({'rule':'child_generation_age_requires_verification','person_key':m['person_key'],'relation':relation,'birth_year':born,'head_birth_year':year,'minimum_reference_generation_gap':minimum})
        elif relation==4 and len(spouses)==1:
            partner=spouses[0]
            if partner['birth_year']['value']-born<12:issues.append({'rule':'spouse_parent_age_requires_verification','person_key':m['person_key']})
        elif relation==2 and m['age_band']['value'][0]<18:
            issues.append({'rule':'minor_spouse_outside_ordinary_reference_cohort','person_key':m['person_key']})
    return issues

def enabled_europe_pools():
    import pyreadstat
    source=BASE/'v4/inputs/enable.sav'
    data,meta=pyreadstat.read_sav(source,output_format='dict')
    fields=[f'S1{s}c{age}' for s in 'AB' for age in (1,2,3)]
    assert meta.column_names_to_labels['S1Ac1'].startswith('Women')
    assert meta.column_names_to_labels['S1Bc1'].startswith('Men')
    out={'GB':[],'ES':[]}
    for values in zip(*data.values()):
        x={k:clean(v) for k,v in zip(data,values)}
        country={'United Kingdom':'GB','Spain':'ES'}.get(meta.variable_value_labels['Country'].get(x['Country']))
        if not country:continue
        counts=[x[f] for f in fields]
        if x['H1'] not in (1,2,3,4) or x['H3'] not in (1,2,3,4,5,6) or x['H11C'] not in (1,2,4):continue
        if not all(v is not None and v>=0 and v==int(v) for v in counts):continue
        if not 1<=sum(counts)<=8 or counts[1]+counts[4]<1:continue
        row=shared.base_row('ENABLE_EU',str(x['UID']),country,fact(int(sum(counts)),fields,'derived'),
             fact(meta.variable_value_labels['H1'][x['H1']],['H1'],code=int(x['H1'])),
             fact(meta.variable_value_labels['H3'][x['H3']],['H3'],measure='dwelling_area_band',code=int(x['H3'])),fact(True,['H11C'],code=int(x['H11C'])))
        for device,f in [('dishwasher_available','H11B'),('space_ac_available','H11E')]:
            row['devices'][device]=fact(x[f] in (1,2,4),[f]) if x[f] in (1,2,4,5) else fact(None,[f],'unknown')
        row['devices']['water_heater_available']=(fact(True,['H11G'],appliance_type='standalone_electric_boiler')
            if x['H11G'] in (1,2,4) else fact(None,['H11G'],'unknown',scope='electric-boiler subtype absence does not establish generic hot-water absence'))
        row['source_technology_presence']={'standalone_electric_water_heater':fact(x['H11G'] in (1,2,4),['H11G']) if x['H11G'] in (1,2,4,5) else fact(None,['H11G'],'unknown')}
        row['members_summary']=fact([dict(label=('Women' if f[2]=='A' else 'Men')+'_'+str(i%3),**fact(int(v),[f])) for i,(f,v) in enumerate(zip(fields,counts))],fields,'derived',scope='original_sex_and_age_bins')
        row['known_presence']=(fact({'source_respondent_home_constraint_item':int(x['C4G']),
             'scope':'respondent personal heating-context daytime-home constraint; not whole-house occupancy'},['C4G']) if x['C4G'] in (1,2,3,4,5) else fact(None,['C4G'],'unknown'))
        row['additional_devices']['fridge_available']=fact(x['H11D'] in (1,2,4),['H11D']) if x['H11D'] in (1,2,4,5) else fact(None,['H11D'],'unknown')
        job={1:'employed_full_time',2:'employed_part_time',3:'not_employed',4:'retired',5:'student',6:'not_employed'}.get(x['S3'])
        frequency=int(x['M1A']) if x['M1A'] is not None and 0<=x['M1A']<=7 and x['M3A1']==1 else None
        row['source_person']={'age':fact(None,(),'unknown'),'employment':fact(job,['S3'],'observed' if job else 'unknown'),
            'source_person':'survey_respondent','teleworking_household':fact(None,(),'unknown'),
            'commute_frequency':fact(frequency,['M1A','M3A1'],'observed' if frequency is not None else 'unknown')}
        birth=int(x['S4']) if x['S4'] is not None and x['S4']!=9999 and 1900<=x['S4']<=2019 else None
        sex={1:'male',2:'female'}.get(x['S5'])
        row['respondent_demographics']={'sex':fact(sex,['S5'],'observed' if sex else 'unknown'),'birth_year':fact(birth,['S4'],'observed' if birth else 'unknown')}
        row['geography']=fact(country,['Country'],'derived',scope='survey_country')
        row['source'].update(survey_year=None,survey_reference_year=None,release='Zenodo1.0,2019-10-31',release_year=2019,
              fieldwork_year=None,survey_year_semantics='release year is not individual interview year',url='https://zenodo.org/records/3523916')
        row['source_file_sha256']=sha(source);row['pool_id']='ENABLE_EU:'+str(x['UID'])
        row['block']=[country,int(x['H1']),int(x['H3']),*map(int,counts)]
        out[country].append(row)
    return out

def build_source_pools(source_cache=None):
    source_module=load_module('portable_source_fact_reader',Path(__file__).resolve().parent.parent/'v7/build_sources.py');source_module.ROOT=OLD
    china=source_module.china_rows()
    import pyreadstat
    data,_=pyreadstat.read_dta(OLD/'inputs/CRECS2012.dta',output_format='dict')
    raw={str(int(v['index'])):{k:clean(x) for k,x in v.items()} for v in (dict(zip(data,vals)) for vals in zip(*data.values()))}
    admitted=[];quarantine=[]
    for row in china:
        issues=ordinary_kinship_issues(row);x=raw[row['source']['household_key']]
        workers=sum(d['employment']['value'] in WORK for d in row['source_member_details'].values())
        remote=x['a3b'];remote_count=int(remote) if remote is not None and remote==int(remote) and 0<=remote<=8 else None
        if remote_count is not None and remote_count>workers:issues.append({'rule':'teleworker_count_exceeds_members_with_reported_work','reported':remote_count,'working_members':workers})
        if issues:
            quarantine.append({'source_key':row['source']['household_key'],'pool_id':'CRECS2012:'+row['source']['household_key'],'issues':issues});continue
        head=next(m for m in row['members_summary']['value'] if m['relationship_to_head']['value']==1)
        details=row['source_member_details'][head['person_key']]
        row['source_person'].update(source_person=head['person_key'],employment=deepcopy(details['employment']),
            source_person_basis='source head is a data anchor; actual interview respondent identity is not linked',
            teleworking_household=fact(remote_count>0,['a3b']) if remote_count is not None else fact(None,['a3b'],'unknown'))
        row['source_head_person_key']=head['person_key']
        count=x['a3a'];reported=int(count) if count is not None and count==int(count) and 0<=count<=8 else None
        row['source_presence_details']={'reported_usual_all_day_person_count':fact(reported,['a3a'],'observed' if reported is not None else 'unknown'),
            'reported_teleworker_count':fact(remote_count,['a3b'],'observed' if remote_count is not None else 'unknown'),
            'interpretation':'usual household statement, not an identified-person travel diary; reference operational bridge declared separately'}
        row['pool_id']='CRECS2012:'+row['source']['household_key'];admitted.append(row)
    pools={'CN':admitted,'US':[],'IN':[],'MX':[]}
    with (OLD/'inputs/candidate_pool.jsonl').open() as f:
        for line in f:
            row=json.loads(line);country=row['source']['country']
            if country in ('US','IN','MX'):pools[country].append(row)
    pools.update(enabled_europe_pools())
    # Add only source-supported IRES frequency/capacity facts; preserve raw survey scope.
    if source_cache is None:source_cache=components.sources.load_sources()
    for row in pools['IN']:
        x=source_cache['india'][row['source']['household_key']]
        frequency=components.seed.num(x['q473_wash_mach_week_use_no'])
        row['source_laundry_weekly_uses']=fact(int(frequency),['q473_wash_mach_week_use_no']) if 1<=frequency<=21 else fact(None,['q473_wash_mach_week_use_no'],'unknown')
        if row['source_laundry_weekly_uses']['value'] is not None:row['source_laundry_cycles_per_week']=int(frequency)
        cap=components.seed.num(x['q455_geyser_most_cap_ltr'])
        row['source_device_details']={'water_heater_storage_capacity_litres':fact(cap,['q455_geyser_most_cap_ltr']) if 0<cap<=500 and cap!=99 else fact(None,['q455_geyser_most_cap_ltr'],'unknown',raw=x['q455_geyser_most_cap_ltr'])}
    save(ROOT/'output/CN_SOURCE_QUARANTINE.json',{'checked':len(china),'admitted_to_source_pool':len(admitted),
        'quarantined':quarantine,'policy':'exclude pending verification; source records unchanged; ordinary adult-head/generation scope, unusual families are not declared false',
        'original_six_card_problem_keys_excluded':all(k in {q['source_key'] for q in quarantine} for k in ['216','1102'])})
    write_rows(ROOT/'inputs/candidate_pool.jsonl',[row for co in COUNTRIES if co in pools for row in pools[co]])
    save(ROOT/'output/SOURCE_POOL_REPORT.json',{'country_candidates':{co:len(v) for co,v in pools.items()},
      'source_pool_sha256':sha(ROOT/'inputs/candidate_pool.jsonl'),'AU_DE_fixed_admitted_households':250,
      'source_unknowns_are_not_false':True,'source_pool_not_all_role_eligible':True})
    return pools

def materialize_ages(c):
    h=c['household'];p=c['household_provenance'];ds=c['source']['dataset'];respondent=h['source_respondent_member_id']
    source_bands=[]
    if ds=='ENABLE_EU':bounds=[(0,18),(18,65),(66,None)]*2
    elif ds=='IRES2020':bounds=[(0,17),(18,40),(41,60),(61,None)]
    elif ds.startswith('RECS'):bounds=[(0,17),(18,64),(65,None)]
    else:bounds=[]
    if bounds:
        for group,band in zip(c['members_summary']['value'],bounds):source_bands.extend([list(band)]*group['value'])
    for i,m in enumerate(h['members']):
        lo,hi=m['age_band'];mid=m['id'];observed=m.get('observed_age')
        if ds=='CRECS2012':source_band=[max(0,2011-m['source_birth_year']),2012-m['source_birth_year']]
        elif ds=='ENASIC2022':source_band=[observed,None if observed==98 else observed]
        else:source_band=source_bands[i]
        if observed is not None:age=observed
        elif ds=='ENABLE_EU' and mid==respondent and m.get('source_birth_year') is not None:
            y=m['source_birth_year'];possible=list(range(max(lo,2015-y),min(hi,2019-y)+1))
            if not possible:raise ValueError('respondent birth year incompatible with reference age')
            age=possible[len(possible)//2]
        elif ds=='CRECS2012':age=lo
        elif hi<18:
            choices=[x for x in (7,9,11,13,15,17) if lo<=x<=hi]
            age=choices[int(rank(c['pool_id'],'reference_child',mid)[:8],16)%len(choices)] if choices else lo
        elif lo>=65:
            choices=[x for x in (67,70,73,76,79,90) if lo<=x<=hi]
            age=choices[int(rank(c['pool_id'],'reference_older',mid)[:8],16)%len(choices)] if choices else lo
        else:
            choices=[x for x in (28,35,42,49,56,62) if lo<=x<=min(hi,64 if m['employment'] in WORK else hi)]
            age=choices[int(rank(c['pool_id'],'reference_adult',mid)[:8],16)%len(choices)] if choices else (lo+hi)//2
        m['source_age_band']=source_band;m['reference_age']=int(age);m['age_band']=[int(age),int(age)]
        if ds=='ENASIC2022' and observed==98:m['observed_age_is_censored_lower_bound']=True
        fields=p.get(f'members.{mid}.age_band',{}).get('source_fields',[])
        activity.tag(p,f'members.{mid}.source_age_band','source age interval/count group or source censoring; does not establish unmeasured member identity',fields,status='derived')
        activity.tag(p,f'members.{mid}.reference_age','observed exact age adopted when available; otherwise explicit source-compatible reference age, no population imputation',fields,
                     status='observed' if observed is not None and not(ds=='ENASIC2022' and observed==98) else 'benchmark_assigned')
        activity.tag(p,f'members.{mid}.age_band','operational reference age; original source interval remains separate',fields,
                     status='observed' if observed is not None and not(ds=='ENASIC2022' and observed==98) else 'benchmark_assigned')
    h['reference_age_design']={'source_intervals_retained':True,'exact_source_ages_not_replaced':True,
        'reference_ages_not_population_estimates':True,'CN_age_reference_year':2012 if ds=='CRECS2012' else None}

def prepare_china(c):
    h=c['household'];p=c['household_provenance']
    roster={item['person_key']:item for item in c['members_summary']['value']}
    for m in h['members']:
        m['relationship_to_head']=roster[m['source_person_key']]['relationship_to_head']['value']
        activity.tag(p,f"members.{m['id']}.relationship_to_head",'observed CRECS relationship code; not inferred from age',roster[m['source_person_key']]['relationship_to_head']['fields'],status='observed')
    head=next(m for m in h['members'] if m['source_person_key']==c['source_head_person_key'])
    h['source_record_anchor_member_id']=head['id']
    h['source_respondent_member_id']=None
    h['source_respondent_binding']={'status':'not_linked','source_head_is_data_anchor_not_interview_respondent':True}
    activity.tag(p,'source_respondent_binding','source head bound only as data anchor; actual interview respondent not independently linked')

def china_remote_and_presence(c,events):
    h=c['household'];p=c['household_provenance'];adult=[m for m in h['members'] if m['age_band'][0]>=18]
    remote=c['source_presence_details']['reported_teleworker_count']['value']
    workers=[m for m in adult if m['employment'] in WORK]
    if remote is not None:
        workers=sorted(workers,key=lambda m:(m['id']==h['decision_maker_id'] and c['benchmark_role'] in 'AF',rank(c['case_id'],'remote_member',m['id'])))
        if remote>len(workers):raise ValueError('reported teleworker count exceeds employed reference members')
        wanted={m['id'] for m in workers[:remote]}
        for m in workers:
            es=[e for e in events if e['member_id']==m['id'] and e['kind']=='work']
            for j,e in enumerate(es):
                use_home=m['id'] in wanted and (m['id']!=h['decision_maker_id'] or c['benchmark_role'] not in 'AF' or j==len(es)-1)
                was_home=e['location']=='home'
                if use_home and not was_home:e['location']='home';e['end']-=e['commute_roundtrip_minutes'];e['commute_roundtrip_minutes']=0
                elif not use_home and was_home:e['location']='away';e['end']+=40;e['commute_roundtrip_minutes']=40
                e['worksite_start']=e['start']+e['commute_roundtrip_minutes']/2;e['worksite_end']=e['end']-e['commute_roundtrip_minutes']/2
            m['work_mode']='home_based' if es and all(e['location']=='home' for e in es) else 'hybrid' if any(e['location']=='home' for e in es) else 'onsite'
            activity.tag(p,f"members.{m['id']}.work_mode",'experimental allocation preserves reported household teleworker total; individual teleworker identities unmeasured',['a3b'])
    known=c['known_presence']['value'] or {};positive=known.get('normally_someone_home_all_day')
    for day in range(5):
        for m in adult:
            mid=m['id'];base=day*1440
            if positive is False and activity.at_home(events,mid,base+540,base+1020):
                if mid==h['decision_maker_id'] and c['benchmark_role'] in 'BE':
                    a,b=base+900,base+960
                else:
                    delta=[0,60,-30,45,-60][day] if mid==h['decision_maker_id'] and c['benchmark_role']=='C' else 0
                    a,b=base+600+delta,base+720+delta
                if not activity.free(events,mid,a,b,care=True):raise ValueError('cannot honor negative usual all-day presence without work collision')
                activity.add(events,mid,'community_program',a,b,'away',activity_reason='explicit reference outside activity; source says not usually at home all day, not zero occupied hours')
        if positive is True and not any(activity.at_home(events,m['id'],base+540,base+900) for m in adult):
            raise ValueError('source usual all-day presence lacks compatible reference daytime adult')

def check_presence(c,events):
    if c['source']['dataset']=='ENABLE_EU':shared.presence_check(c,events)
    elif c['source']['dataset']=='CRECS2012':
        val=(c['known_presence']['value'] or {}).get('normally_someone_home_all_day')
        adult=[m for m in c['household']['members'] if m['age_band'][0]>=18]
        for d in range(5):
            if val is True and not any(activity.at_home(events,m['id'],d*1440+540,d*1440+900) for m in adult):raise ValueError('positive source daytime-home condition lost')
            if val is False and any(activity.at_home(events,m['id'],d*1440+540,d*1440+1020) for m in adult):raise ValueError('negative usual all-day home answer lost')

def enrich(c):
    shared.enrich_interfaces(c)
    h=c['household'];p=c['household_provenance']
    h['calendar']['source_presence_compatibility']['CN_source_scope']='a3 is usual all-day residence; false is not whole-house vacancy; a3a usual count retained without pretending identified-person diary'
    if c['source']['dataset']=='CRECS2012':
        h['calendar']['source_presence_compatibility']['CN_reported_usual_all_day_person_count']=c['source_presence_details']['reported_usual_all_day_person_count']['value']
        h['calendar']['source_presence_compatibility']['CN_count_not_claimed_actual_reference_diary']=True
    if c['source']['dataset']=='IRES2020' and c['source_laundry_weekly_uses']['value'] is not None:
        h['routine']['laundry_cycles_per_week']=c['source_laundry_weekly_uses']['value']
        h['routine']['source_laundry_weekly_uses']=deepcopy(c['source_laundry_weekly_uses'])
        activity.tag(p,'routine.laundry_cycles_per_week','observed usual weekly machine-use count adopted as reference number of whole-cycle needs; exact programmes remain experimental',['q473_wash_mach_week_use_no'],status='derived')
    if h.get('ev') and h.get('control_inventory',{}).get('EV',{}).get('enabled'):
        h['decision_authorization']['ev_driver_id']=h['ev']['vehicle_user_member_id']

def build_week(c,ordinal):
    events,targets,nights=activity.build_activities(c)
    if c['source']['dataset']=='ENABLE_EU':shared.set_de_targets(c,events)
    if c['source']['dataset']=='CRECS2012':china_remote_and_presence(c,events)
    original=deepcopy(events);events=weekend.apply(c,events,targets,ordinal)
    try:check_presence(c,events)
    except ValueError:
        events=original;c['household']['weekend_design'].update(actual_added_outings=0,blocks=[],fallback_to_existing_commitments=True)
    activity.schooling_and_care(c,events)
    for e in events:
        member=next(m for m in c['household']['members'] if m['id']==e['member_id'])
        if e['kind']=='extended_school_care' and member['age_band'][0]>=12:
            e['kind']='school_waiting';e['provider']='experimental school waiting/study; no young-child care claim'
    activity.accompany_school_runs(c,events);activity.build_services(c,events);activity.refresh_supervision(c,events)
    activity.finalize_calendar(c,events,targets,nights)
    check_presence(c,events);enrich(c)
    return c

def initialize(c,ordinal,alternative=0):
    legacy.initialize(c,ordinal,alternative)
    if c['source']['dataset']=='ENABLE_EU':
        for m in c['household']['members']:
            status=c['household_provenance'][f"members.{m['id']}.employment"]['status']
            if m['age_band'][0]>=66 and status not in ('observed','survey_imputed'):
                m.update(employment='retired',school_enrolled=False,work_mode='not_applicable',activity='home_activity')
                activity.tag(c['household_provenance'],f"members.{m['id']}.employment",'joint coverage-design: retired older reference member; source job unmeasured')
        # No work-from-home implication may replace measured ES commute frequency.
        shared.prepare_german_respondent_constraint(c)
    if c['source']['dataset']=='CRECS2012':prepare_china(c)
    materialize_ages(c)
    return build_week(c,ordinal)

def make_case(row,role,pair=None):
    c=shared.make_case(row,role,pair)
    c['extension_contract']='eight-country-household-step1-v8'
    if c['source']['dataset']=='CRECS2012':c['source_person']['source_person_basis']='source head is a data anchor; actual interview respondent identity is not linked'
    # Legacy effective_card iterates sets: explicit order is part of the frozen
    # input bytes, even though prose order does not change source semantics.
    for key in ('confirmed_equipment','unknown_equipment'):
        c['card'][key]=sorted(c['card'][key])
    c['card']['device_clauses']=sorted(c['card']['device_clauses'],key=lambda item:item['device'])
    return c
