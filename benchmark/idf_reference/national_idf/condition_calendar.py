"""Bind another declared calendar window without rebuilding housing or devices."""
import copy
import datetime as dt
from pathlib import Path

from .common import ROOT,digest,read,require,save,AdmissionError
from .idf import Fields,objects,parse,render
from .program_resources import model_signature
from .reference_workflow import ref
from .source_adapter import source_file
from scripts.run_multicountry_season_windows import dated_case


def validate_window(window,source_window):
    require(set(window)=={'start_date','end_date'},'CONDITION_CALENDAR_UNSUPPORTED_FIELDS')
    try:
        begin=dt.date.fromisoformat(window['start_date']);end=dt.date.fromisoformat(window['end_date'])
        source=dt.date.fromisoformat(source_window['start_date'])
    except (ValueError,TypeError,KeyError):raise AdmissionError('CONDITION_CALENDAR_INVALID_DATE') from None
    require((end-begin).days==6,'CONDITION_CALENDAR_EXPECTED_SEVEN_DAYS')
    require(begin.year==end.year==source.year,'CONDITION_CALENDAR_SOURCE_YEAR_REQUIRED')
    require((begin+dt.timedelta(days=13)).year==source.year,'CONDITION_CALENDAR_RECOVERY_CROSSES_SOURCE_YEAR')
    return begin,end


def rows_for_window(source,fields,window,source_window):
    begin,end=validate_window(window,source_window);rows=copy.deepcopy(source)
    periods=objects(rows,'RunPeriod');require(len(periods)==1,'CONDITION_CALENDAR_SOURCE_CARDINALITY')
    for key,value in {'begin_year':begin.year,'begin_month':begin.month,'begin_day_of_month':begin.day,
        'end_year':end.year,'end_month':end.month,'end_day_of_month':end.day,
        'day_of_week_for_start_day':begin.strftime('%A')}.items():fields.set(periods[0],key,str(value))
    require([r for r in rows if r[0]!='RunPeriod']==[r for r in source if r[0]!='RunPeriod']
            and model_signature(rows)==model_signature(source),'CONDITION_CALENDAR_CHANGED_PHYSICS')
    return rows


def prepare(fixture_ref,case_ref,start_date,out,*,root=ROOT):
    parent=read(source_file(fixture_ref,root));case=read(source_file(case_ref,root))
    require(not parent.get('registered_numerical_overlay'),'CONDITION_CALENDAR_NUMERICAL_PARENT_NOT_BASE')
    source_window=copy.deepcopy(case['run']);begin=dt.date.fromisoformat(start_date);case=dated_case(case,begin)
    require((dt.date.fromisoformat(case['run']['end_date'])-begin).days==6,'CONDITION_CALENDAR_EXPECTED_SEVEN_DAYS')
    before=parse(source_file(parent['model'],root).read_text())
    fields=Fields(source_file(parent['engine_schema'],root))
    rows=rows_for_window(before,fields,case['run'],source_window)
    out=Path(out).resolve();require(out.is_relative_to(root) and not out.exists(),'CONDITION_CALENDAR_OUTPUT_EXISTS');out.mkdir(parents=True)
    identifier='condition_calendar_'+digest({'fixture':fixture_ref,'run':case['run']})[:24]
    (out/'in.idf').write_text(render(rows));domain=read(source_file(parent['input_domain'],root))
    domain.update(physics_configuration_id=identifier,run_period=case['run']);save(out/'DOMAIN.json',domain)
    fixture=copy.deepcopy(parent);fixture.update(id=identifier,model=ref(out/'in.idf',root),input_domain=ref(out/'DOMAIN.json',root))
    case['case_id']=identifier;case['environment']['physics_configuration_id']=identifier
    save(out/'FIXTURE.json',fixture);save(out/'CASE.json',case)
    save(out/'CALENDAR_TRANSACTION.json',{'schema':'national_idf.condition_calendar_transaction.v1',
        'source_fixture':fixture_ref,'source_CASE':case_ref,'target_fixture':ref(out/'FIXTURE.json',root),
        'run':case['run'],'model_rows_other_than_RunPeriod_exactly_equal':True,
        'complete_relative_engineering_life_and_control_dates_shifted':True,
        'physics_or_thresholds_changed':False,'household_generation_or_AB_changed':False,
        'weather_is_pinned_typical_year_not_measured_calendar_year':True,'model_admission_granted':False})
    return ref(out/'FIXTURE.json',root),case
