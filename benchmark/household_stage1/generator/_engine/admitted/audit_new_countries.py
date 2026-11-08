"""Independent raw-fact, calendar, authority and six-service admission review."""
from pathlib import Path
from collections import Counter
from itertools import combinations
from zipfile import ZipFile
import hashlib
import importlib.util
import json
import re
import sys
import xml.etree.ElementTree as ET

BASE=Path(__file__).resolve().parent.parent
ROOT=Path(__file__).resolve().parent
V7=BASE/'v7'
WORK={'employed','employed_full_time','employed_part_time'}
F=('AC','WM','DR','DW','WH','EV')
AU_FILE=BASE/'public_sources/eca2025/eca_jun2025_data.xlsx'
DE_FILE=BASE/'v4/inputs/enable.sav'
PIN={'AU':'ceb26da8c07a06983254dc1d19a1d21f119fd9d9dcfe76730e0a141f3a3c3a07',
     'DE':'9e9d466dd932f79db63dde742a823ab84025e24dc69abd90915f12cc53e15aff'}
AU_FIELD_COLUMNS={'age_band':4,'sex':5,'state':8,'region':9,'energy_decision_responsibility':11,
 'employment':13,'household_composition':16,'children':18,'adults':19,'working_adults':20,
 'off_street_parking':45,'air_conditioner':46,'cars':47,'personal_wfh_days':49,'work_hours_category':50,
 'never_commutes':58,'tenure':60,'dwelling_type':63,'water_heater_fuel':70,'home_ev_charger':152,
 'battery_electric_vehicle':153,'automation':155,'dishwasher_time_shifting':308,'heater_time_shifting':309,
 'hot_water_time_shifting':310,'dryer_time_shifting':311,'washer_time_shifting':312,'ac_time_shifting':313,'life_support':353}
for day in range(7):
    for offset,who in enumerate(('respondent','other','no_one')):AU_FIELD_COLUMNS[f'presence.day{day}.{who}']=21+3*day+offset

def need(value,message):
    if not value:raise ValueError(message)

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);mod=importlib.util.module_from_spec(spec)
    sys.modules[name]=mod;spec.loader.exec_module(mod);return mod

life=load('independent_life_new_countries',V7/'audit_life.py')
controls=load('independent_controls_new_countries',V7/'audit_controls.py')
service=load('independent_services_new_countries',V7/'audit_services.py')

def raw_sources():
    import pyreadstat
    from math import isfinite
    for co,path in [('AU',AU_FILE),('DE',DE_FILE)]:
        need(hashlib.sha256(path.read_bytes()).hexdigest()==PIN[co],'raw source hash mismatch '+co)
    data,meta=pyreadstat.read_sav(DE_FILE,output_format='dict')
    need(meta.column_names_to_labels['S1Ac1'].startswith('Women') and meta.column_names_to_labels['S1Bc1'].startswith('Men'),'ENABLE sex-bin field labels changed')
    need('Refrigerator' in meta.column_names_to_labels['H11D'] and 'Cooker' in meta.column_names_to_labels['H11A'],'ENABLE background device mapping')
    need('I spend' in meta.column_names_to_labels['C4G'],'ENABLE home constraint must remain respondent-specific')
    german={str(x['UID']):x for x in (dict(zip(data,vs)) for vs in zip(*data.values()))
            if meta.variable_value_labels['Country'].get(x['Country'])=='Germany'}
    ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with ZipFile(AU_FILE) as z:
        strings=[''.join(t.text or '' for t in si.findall('.//m:t',ns))
                 for si in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('m:si',ns)]
        rows=[]
        for row in ET.fromstring(z.read('xl/worksheets/sheet1.xml')).findall('m:sheetData/m:row',ns):
            out={}
            for c in row.findall('m:c',ns):
                letters=re.match('[A-Z]+',c.attrib['r'])[0];ix=0
                for ch in letters:ix=ix*26+ord(ch)-64
                v=c.find('m:v',ns)
                if c.attrib.get('t')=='s':value=strings[int(v.text)] if v is not None else None
                elif c.attrib.get('t')=='inlineStr':value=''.join(t.text or '' for t in c.findall('.//m:t',ns))
                else:value=v.text if v is not None else None
                out[ix-1]=value
            rows.append(out)
    australian={x[1]:x for x in rows[1:]}
    need(len(australian)==4106 and len(german)==711,'independent source row counts')
    return {'AU':australian,'DE':german,'es':german,'es_meta':meta,'au_header':rows[0]}

def home_minutes(events,mid,day,start=540,end=1020):
    lo=day*1440+start;hi=day*1440+end
    segments=sorted((max(lo,e['start']),min(hi,e['end'])) for e in events if e['member_id']==mid and e['location']=='away'
                    and max(lo,e['start'])<min(hi,e['end']))
    gone=0;right=lo
    for a,b in segments:gone+=max(0,b-max(a,right));right=max(right,b)
    return end-start-gone

def check_source(c,s):
    h=c['household'];p=c['household_provenance'];co=c['source']['country'];key=c['source']['household_key']
    need(co in ('AU','DE') and key in s[co],'country/source key binding')
    need(c['source_file_sha256']==PIN[co],'case source hash binding')
    need(c['role_status']=='benchmark_assigned' and c['evidence_scope']['role_and_attitudes']=='controlled_experimental_assignment','assigned role relabelled observed')
    need(not c['evidence_scope']['global_representativeness'],'unsupported representativeness')
    ms=h['members'];actor=next(m for m in ms if m['id']==h['decision_maker_id'])
    need(actor['age_band'][0]>=18,'minor decision maker')
    if co=='DE':
        raw=s['DE'][key];fields=[f'S1{sex}c{age}' for sex in 'AB' for age in (1,2,3)]
        expected=[int(raw[f]) for f in fields]
        need([x['value'] for x in c['members_summary']['value']]==expected,'DE member count bins altered')
        need(len(ms)==sum(expected)==c['household_size']['value'],'DE source population counts')
        need(c['dwelling']['observed_type']['code']==int(raw['H1']) and c['dwelling']['size']['code']==int(raw['H3']),'DE dwelling code binding')
        need(c['devices']['washer_available']['value'] is True and raw['H11C'] in (1,2,4),'DE washer source claim')
        sex_counts=Counter(m.get('sex_from_source') for m in ms)
        need(sex_counts['female']==sum(expected[:3]) and sex_counts['male']==sum(expected[3:]),'DE source sex totals reversed')
        bands=[]
        for count,band in zip(expected,[(0,18),(18,65),(66,None)]*2):bands.extend([list(band)]*count)
        for member,band in zip(ms,bands):
            need(member['source_age_band']==band and member['reference_age']>=band[0]
                 and (band[1] is None or member['reference_age']<=band[1]),'DE reference age outside source count-group')
        respondent=h['source_respondent_member_id']
        val=raw['C4G'];daily=[home_minutes(h['calendar']['weekly_events'],respondent,d)>=270 for d in range(5)]
        if val==5:need(all(daily),'DE respondent high home constraint not respected')
        if val in (1,2):need(sum(daily)<=2,'DE respondent low home constraint not respected')
        need(c['additional_devices']['fridge_available']['value']==(raw['H11D'] in (1,2,4))
             if raw['H11D'] in (1,2,4,5) else c['additional_devices']['fridge_available']['value'] is None,'DE cooker confused with refrigerator')
        need(c['additional_devices']['fridge_available']['fields']==['H11D'],'DE refrigerator bound to cooker column')
        need(c['source_technology_presence']['standalone_electric_water_heater']['value']==(raw['H11G'] in (1,2,4))
             if raw['H11G'] in (1,2,4,5) else c['source_technology_presence']['standalone_electric_water_heater']['value'] is None,'DE electric-boiler subtype negative lost')
        need(c['devices']['water_heater_available']['value']==(True if raw['H11G'] in (1,2,4) else None),'DE electric-boiler absence promoted to generic hot-water absence')
    else:
        x=s['AU'][key];children,adults,working=[int(float(x[i])) for i in (18,19,20)]
        need(c['source_record_fields']=={name:x.get(ix) for name,ix in AU_FIELD_COLUMNS.items()},'AU stored source answers changed or bound to wrong columns')
        need(c['household_size']['value']==children+adults==len(ms),'AU household size derived incorrectly')
        need(sum(m['age_band'][1]<18 for m in ms)==children and sum(m['age_band'][0]>=18 for m in ms)==adults,'AU adult/child source count changed')
        need(sum(m['employment'] in WORK for m in ms)==working,'AU observed working-adult total changed')
        bound=next(m for m in ms if m['id']==h['source_respondent_member_id'])
        jobs={'Working full time':'employed_full_time','Working part time':'employed_part_time','Working casually':'employed_part_time',
              'Unemployed':'not_employed','Retired':'retired','Full-time student':'student','Full time home / parent duties':'home_caregiver'}
        need(bound['employment']==jobs[x[13]] and p[f"members.{bound['id']}.employment"]['status']=='observed','AU respondent job binding')
        need(bound.get('sex_from_source')=={'Male':'male','Female':'female','Another gender':'another_gender'}[x[5]],'AU respondent sex binding')
        a=re.fullmatch(r'(\d+)-(\d+)',x[4]);source_band=list(map(int,a.groups())) if a else [int(x[4][:-1]),None]
        need(bound['source_age_band']==source_band and bound['age_band'][0]>=source_band[0]
             and (source_band[1] is None or bound['age_band'][1]<=source_band[1]),'AU age-bin narrowing outside source')
        need(c['dwelling']['size']['value'] is None and c['dwelling']['observed_type']['value']==x[63],'AU unmeasured area or observed type changed')
        need(p['dwelling.reference_area_m2']['status']=='benchmark_assigned','AU reference area relabelled observed/matched')
        need(c['devices']['space_ac_available']['value']==(x[46]=='Yes'),'AU AC yes/no altered')
        need(x[312] in ('Rarely','Sometimes','Regularly') and c['devices']['washer_available']['status']=='derived','AU functional washer use promoted to ownership')
        for device,ix in [('dryer_available',311),('dishwasher_available',308)]:
            f=c['devices'][device]
            need(f['value']==(True if x[ix] in ('Rarely','Sometimes','Regularly') else None),'AU Never/not-relevant silently converted to absence')
        if x[70] in ('Electricity','Gas'):
            need(c['devices']['water_heater_available']['energy_carrier']==('electricity' if x[70]=='Electricity' else 'non_electric'),'AU actual hot-water fuel altered')
        ev=x[152]=='You already have this' and x[153]=='You already have this' and x[45]=='Yes'
        need(c['devices']['home_vehicle_charging']['value']==(True if ev else None),'AU BEV/charger/parking binding')
        need(h['medical_service_must_not_be_interrupted']==(x[353]=='Yes'),'AU life-support service lost')
        events=h['calendar']['weekly_events'];respondent=h['source_respondent_member_id']
        for d in range(7):
            me,other,nobody=[x[21+d*3+i]=='Yes' for i in range(3)]
            need(nobody!=(me or other),'AU incompatible presence row admitted')
            own=home_minutes(events,respondent,d);other_minutes=[home_minutes(events,m['id'],d) for m in ms if m['id']!=respondent]
            need(own>=270 if me else own<=240,'AU personal source day presence')
            need(any(v>=270 for v in other_minutes) if other else not any(v>240 for v in other_minutes),'AU other-member source day presence')
        if bound['employment'] in WORK:
            expected_wfh=0 if x[49]=='Don’t usually work from home' else 5 if x[49]=='5 days or more per week' else int(x[49][0])
            works=[e for e in events if e['member_id']==respondent and e['kind']=='work']
            need(len(works)==5 and sum(e['location']=='home' for e in works)==expected_wfh,'AU personal WFH frequency changed')
            if x[58]=='Yes':need(all(e['location']=='home' for e in works),'AU never-commutes respondent sent to office')
        if 'EV' in h.get('controlled_function_ids',[]):need(x[45]=='Yes','known no parking converted to household EV access')
        # No unmeasured family graph is converted into source relationships.
        for m in ms:
            if m['id']!=respondent:
                need('sex_from_source' not in m and 'source_birth_year' not in m and 'relationship_to_head' not in m,'AU nonexistent member detail asserted observed')
                need(p[f"members.{m['id']}.age_band"]['status']=='benchmark_assigned','AU constructed member ages relabelled source')
    return True

def check_case(c,s,old=None):
    if old is None:old=c
    life.check(c,s,old)
    check_source(c,s)
    h=c['household'];es=h['calendar']['weekly_events'];actor=h['decision_maker_id']
    for m in h['members']:
        need(m['age_band']==[m['reference_age'],m['reference_age']],'operational age is not concrete reference age')
        need(c['household_provenance'][f"members.{m['id']}.reference_age"]['status']=='benchmark_assigned','reference age relabelled observed')
    role=c['benchmark_role']
    if role in 'AF':need(any(e['member_id']==actor and e['kind']=='work' and e['location']=='away' for e in es),'commuting role without actual reference commute')
    if role in 'BE':need(all(life.home(es,actor,d*1440+540,d*1440+900) for d in range(5)),'home/care actor actually away')
    if role=='E':
        link=h['role_care_binding'];need(link['caregiver_id']==actor and link['status']=='benchmark_assigned','invented observed care link')
        need(any(m['id']==link['child_id'] and m['age_band'][1]<12 for m in h['members']),'E child not age-compatible')
    if role=='C':
        starts=[min((e['start']%1440 for e in es if e['member_id']==actor and e['start']//1440==d and e['kind'] in ('work','community_program')),default=None) for d in range(5)]
        need(len(set(t for t in starts if t is not None))>=2,'C variable schedule exists only in its description')
    template=c['routine'].get('personal_commute_scenario')
    if template:
        e=next((e for e in es if e['member_id']==actor and e['kind']=='work' and e['location']=='away'),None)
        if e:need([template['depart_minutes'],template['return_minutes']]==[e['start']%1440,e['end']%1440],'legacy commute template differs from final calendar')
    for day in h['routine']['daily_services']:
        need(day['manual_operation_opportunities'],'missing usable manual operation opportunities')
        for op in day['manual_operation_opportunities']:
            a,b=[day['day']*1440+op[k] for k in ('start','end')];mid=op['member_id']
            need(day['flexible_chore_window'][0]<=op['start']<op['end']<=day['flexible_chore_window'][1]
                 and mid in day['chore_member_ids'],'manual operation outside declared opportunity')
            need(b-a>=10 and life.available(es,mid,a,b),'manual operation collides with work/bathing/travel')
            for meal in day['meals']:
                if mid in meal['participants']:need(not life.intersects(a,b,day['day']*1440+meal['start'],day['day']*1440+meal['end']),'manual operation collides with meal')
            for e in es:
                if e['member_id']==mid and e['kind']=='escort':need(not life.intersects(a,b,e['start']-15,e['end']+15),'manual operation in escort buffer')
    auth=h['decision_authorization']
    need(auth['status']=='benchmark_assigned' and not auth['real_family_consent_observed'],'reference authority relabelled actual consent')
    if h.get('ev'):need(auth['ev_driver_id']==h['ev']['vehicle_user_member_id'] and auth['ev_adjustment_authorization'],'EV actor/driver authority missing')
    if 'control_inventory' in h:
        need(old is not c,'control audit requires pre-intervention household')
        controls.check_revision(c,old)
        service.check(c)
    return True

def check_population(rows,allocation):
    need(len(rows)==250,'new-country cohort must have250 households')
    need(len({c['case_id'] for c in rows})==250,'duplicate case IDs')
    need(len({(c['source']['dataset'],c['source']['household_key']) for c in rows})==250,'source household reused across roles')
    all_masks={tuple(x) for n in (4,5,6) for x in combinations(F,n)}
    pairs={}
    for co in ('AU','DE'):
        current=[c for c in rows if c['source']['country']==co]
        need(len(current)==125 and Counter(c['benchmark_role'] for c in current)==Counter(allocation[co]),'country/role quota differs')
        need({tuple(c['household']['controlled_function_ids']) for c in current}==all_masks,'country missing a control-function configuration')
        for role in 'ABCDEF':
            cell=[c for c in current if c['benchmark_role']==role]
            sizes=Counter(c['household']['controlled_function_count'] for c in cell)
            need(set(sizes)=={4,5,6} and max(sizes.values())-min(sizes.values())<=1,'cell4/5/6 design imbalanced')
            exposure=Counter(f for c in cell for f in c['household']['controlled_function_ids'])
            need(set(exposure)==set(F) and min(exposure.values())>=2,'cell function exposure missing')
        for pair in combinations(F,2):
            need({tuple(int(f in c['household']['controlled_function_ids']) for f in pair) for c in current}=={(0,0),(0,1),(1,0),(1,1)},'country pair-state coverage missing')
    for c in rows:
        if c.get('cd_pair_id'):pairs.setdefault(c['cd_pair_id'],[]).append(c)
    need(len(pairs)==32 and all(len(v)==2 for v in pairs.values()),'C/D matching pair count')
    for pair in pairs.values():
        need({c['benchmark_role'] for c in pair}=={'C','D'},'wrong pair roles')
        need(pair[0]['household']['controlled_function_ids']==pair[1]['household']['controlled_function_ids'],'paired control configurations differ')
        need(pair[0]['matching_block']==pair[1]['matching_block'],'paired source-background block differs')
    return True
