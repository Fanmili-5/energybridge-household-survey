"""Registered month/day windows with source-year calendar,unchanged EB physics."""
import argparse
import copy
import datetime as dt

from national_idf.common import ROOT,read,save,require,digest
from national_idf.idf import parse,render,Fields,objects
from national_idf.program_resources import model_signature
from national_idf.reference_workflow import ref
from national_idf.source_adapter import source_file,selector
from national_idf.assembly import compile_assembly
from national_idf.joint_case_runtime import compile_joint_case,run_joint_case
from scripts.validate_multicountry_life import validate

OUT=ROOT/'reports/multicountry_envelope_review_20261108'


def dated_case(case,start):
    before=dt.date.fromisoformat(case['run']['start_date']);end=dt.date.fromisoformat(case['run']['end_date'])
    delta=start-before;result=copy.deepcopy(case)
    shift=lambda value:(dt.date.fromisoformat(value)+delta).isoformat()
    result['run']={'start_date':start.isoformat(),'end_date':(end+delta).isoformat()}
    for item in result['controls']['dated_overrides']:item['date']=shift(item['date'])
    for group,key in [('controls','program_start_overrides'),('controls','ev_window_overrides'),('life','mixed_water_overrides')]:
        result[group][key]={shift(k):v for k,v in result[group][key].items()}
    return result


def execute(season):
    parent=ROOT/'reports/multicountry_joint_review_20261108/ES_fixture_normalization'
    original=read(parent/'FIXTURE.json');source=parse(source_file(original['model'],ROOT).read_text())
    fields=Fields(source_file(original['engine_schema'],ROOT));case=read(parent/'STRESS_CASE.json')
    protocol=read(ROOT/'configs/study_protocol.json');registered=dt.date.fromisoformat(protocol['seasons'][season])
    year=dt.date.fromisoformat(case['run']['start_date']).year;start=dt.date(year,registered.month,registered.day)
    case=dated_case(case,start);folder=OUT/('ES_'+season+'_normalized_draw');folder.mkdir(exist_ok=True)
    identifier=f'ES_Madrid_{season}_{year}_'+digest({'source':original['model']['sha256'],
        'weather':original['weather']['sha256'],'window':case['run']})[:32]
    blueprint=read(parent/'BLUEPRINT.json');blueprint['id']=identifier
    adapter=read(source_file(blueprint['source_adapter'],ROOT));adapter_rows=parse(source_file(adapter['model'],ROOT).read_text())
    before=objects(adapter_rows,'RunPeriod')[0];after=copy.deepcopy(before)
    for label,prefix in [('start_date','begin'),('end_date','end')]:
        date=dt.date.fromisoformat(case['run'][label])
        for key,value in zip(('year','month','day_of_month'),(date.year,date.month,date.day)):
            fields.set(after,prefix+'_'+key,str(value))
    fields.set(after,'day_of_week_for_start_day',start.strftime('%A'))
    (folder/'CALENDAR.idf').write_text(render([after]))
    scope={'schema':'national_idf.fixed_source_year_season_window.v1','source_fixture':ref(parent/'FIXTURE.json'),
        'source_CASE':ref(parent/'STRESS_CASE.json'),'registered_month_day_protocol':ref(ROOT/'configs/study_protocol.json'),
        'source_calendar_year_preserved':year,'season':season,'target_window':case['run'],
        'weather_housing_devices_person_physics_and_programmes_changed':False,
        'only_absolute_dates_shifted_daily_times_and_relative_events_unchanged':True,
        'household_generator_or_AB_changed':False,'formal_admitted':False}
    save(folder/'SCOPE.json',scope)
    blueprint['changes'].append({'action':'replace','object':selector(adapter_rows,adapter_rows.index(before)),
        'after':{'file':ref(folder/'CALENDAR.idf'),'object':selector([after],0)},
        'reason':'Registered seasonal month/day,source year;keep command-relative times and all physical inputs',
        'evidence':ref(folder/'SCOPE.json'),'affected_meters':['*']})
    save(folder/'BLUEPRINT.json',blueprint)
    if not (folder/'assembly').exists():compile_assembly(identifier,folder/'assembly',mode='engineering_reference',blueprint_ref=ref(folder/'BLUEPRINT.json'))
    rows=parse((folder/'assembly/in.idf').read_text())
    require([r for r in rows if r[0]!='RunPeriod']==[r for r in source if r[0]!='RunPeriod']
        and model_signature(rows)==model_signature(source),'SEASON_CHANGED_NON_CALENDAR_INPUTS')
    domain=read(source_file(original['input_domain'],ROOT));domain.update(physics_configuration_id=identifier,run_period=case['run'])
    save(folder/'DOMAIN.json',domain)
    fixture=copy.deepcopy(original);fixture.update(id=identifier,model=ref(folder/'assembly/in.idf'),input_domain=ref(folder/'DOMAIN.json'),
        dependencies=read(folder/'assembly/ASSEMBLY.json')['dependencies'])
    save(folder/'FIXTURE.json',fixture)
    case['environment']['physics_configuration_id']=identifier;case['case_id']=identifier+'__fixed_engineering_commands';save(folder/'CASE.json',case)
    save(folder/'PREPARATION.json',{'schema':'national_idf.season_reference_preparation.v1','scope':ref(folder/'SCOPE.json'),
        'runtime_fixture':ref(folder/'FIXTURE.json'),'formal_admitted':False})
    if not (folder/'compiled').exists():compile_joint_case(ref(folder/'FIXTURE.json'),case,folder/'compiled',mode='engineering_reference')
    if not (folder/'run').exists():run_joint_case(folder/'compiled',folder/'run',mode='engineering_reference')
    checks=validate(folder/'run',fixture,case)
    print(season,'same physical configuration executed',checks['native_facility_kWh'],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--season',choices=['winter','transition'],required=True);execute(p.parse_args().season)
