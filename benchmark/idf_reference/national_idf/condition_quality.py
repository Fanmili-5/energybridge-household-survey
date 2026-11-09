"""Numerical probes for new geometry,with source schedule-only profile reuse.

The reusable library contributes native-interpreted fractional schedule
values only. Its appliance powers,water peaks,backgrounds and housing are
never copied. The complete CSV and each Schedule:File interpolation row must
be identical before reuse. Physical rows remain this request's own model.
"""
import copy
import datetime as dt
from pathlib import Path

from .common import ROOT, read, require, save
from .idf import Fields, objects, parse, render
from .program_resources import model_signature, plan_resources
from .reference_workflow import ref, schedule_dependency
from .source_adapter import source_file
from .source_numerics import building_numerical_replacement, validate_model_overlay, WARMUP_FIELDS


def schedule_equivalence(parent, library, *, root=ROOT):
    rows=parse(source_file(parent['model'],root).read_text())
    other=parse(source_file(library['model'],root).read_text())
    p=plan_resources(rows,parent['engine_schema'],parent['resource_pack'],root=root)
    q=plan_resources(other,library['engine_schema'],library['resource_pack'],root=root)
    require(parent['engine_schema']==library['engine_schema'],'CONDITION_PROFILE_ENGINE_MISMATCH')
    require(p['definition']['programs']==q['definition']['programs'],'CONDITION_PROFILE_PROGRAMME_MISMATCH')
    names={name for value in p['definition']['programs'].values() for name in value['schedules']}
    checks={}
    for name in names:
        a=next(r for r in objects(rows,'Schedule:File') if r[1]==name)
        b=next(r for r in objects(other,'Schedule:File') if r[1]==name)
        aa=copy.deepcopy(a);bb=copy.deepcopy(b);aa[3]=bb[3]='BOUND_CSV'
        require(aa==bb,'CONDITION_PROFILE_INTERPOLATION_CHANGED',name)
        def dependency(f,filename):
            return schedule_dependency(f['dependencies'],filename,root=root)
        left,right=dependency(parent,a[3]),dependency(library,b[3])
        require(left['sha256']==right['sha256'],'CONDITION_PROFILE_CSV_CHANGED',name)
        checks[name]={'same_full_CSV_sha256':left['sha256'],'same_column_interpolation_and_calendar_fields':True}
    # The independently observed2-minute programme agrees before borrowing
    # 1/5-minute readings of that exact same native schedule input.
    return {'schema':'national_idf.fractional_schedule_equivalence.v1','checks':checks,
            'appliance_power_water_peaks_and_backgrounds_copied':False,
            'source_library_not_a_house_or_device_performance_substitute':True}


def prepare(parent_ref,case,library_ref,folder,step,warmup,days,arm,identifier,*,root=ROOT,fixed_control_fields=()):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    parent=read(source_file(parent_ref,root));library=read(source_file(library_ref,root))
    require((step,warmup,days) in ((1,14,7),(2,14,7),(5,14,7),(2,28,7),(2,14,14))
            and arm in ('baseline','intervention'),'CONDITION_UNREGISTERED_NUMERIC_VARIANT')
    source=parse(source_file(parent['model'],root).read_text());rows=copy.deepcopy(source)
    fields=Fields(source_file(parent['engine_schema'],root));objects(rows,'Timestep')[0][1]=str(60//step)
    before,after=objects(source,'Building')[0],objects(rows,'Building')[0]
    protocol=read(root/'configs/study_protocol.json')
    fields.set(after,WARMUP_FIELDS[0],str(warmup))
    fields.set(after,WARMUP_FIELDS[1],str(protocol['warmup_max_days'][protocol['warmup_min_days'].index(warmup)]))
    changed=[k for k in WARMUP_FIELDS if fields.get(before,k)!=fields.get(after,k)]
    edits=building_numerical_replacement(before,after,changed,source_file(parent['engine_schema'],root),
        ref(root/'configs/study_protocol.json',root)) if changed else {}
    case=copy.deepcopy(case);start=dt.date.fromisoformat(case['run']['start_date']);end=start+dt.timedelta(days=days-1)
    case['run']['end_date']=end.isoformat()
    for key,value in {'end_month':end.month,'end_day_of_month':end.day,'end_year':end.year}.items():
        fields.set(objects(rows,'RunPeriod')[0],key,str(value))
    require(set(fixed_control_fields)<={'tank_target_C'},'CONDITION_UNREVIEWED_FIXED_CONTROL_FIELD')
    if arm=='baseline':
        case['controls']['dated_overrides']=[r for r in case['controls'].get('dated_overrides',[])
                                            if r['field'] in fixed_control_fields]
    (folder/'in.idf').write_text(render(rows))
    overlay={'schema':'national_idf.registered_model_numerical_overlay.v1','formal_admitted':False,
        'source_model':parent['model'],'target_model':ref(folder/'in.idf',root),'protocol':ref(root/'configs/study_protocol.json',root),
        'warmup_overlay':edits,'step_min':step,'days':days}
    save(folder/'OVERLAY.json',overlay)
    validate_model_overlay(rows,ref(folder/'in.idf',root),ref(folder/'OVERLAY.json',root),parent['engine_schema'],root=root)
    equivalence=schedule_equivalence(parent,library,root=root);save(folder/'SCHEDULE_EQUIVALENCE.json',equivalence)
    pack=copy.deepcopy(read(source_file(parent['resource_pack'],root)))
    profile=read(source_file(library['resource_pack'],root))['profiles'][str(step)]
    source_file(profile,root);pack['profiles']={str(step):profile};pack['binding_model_signature']=model_signature(rows)
    pack['source_evidence'] += [ref(folder/'SCHEDULE_EQUIVALENCE.json',root),ref(folder/'OVERLAY.json',root)]
    save(folder/'RESOURCE_PACK.json',pack)
    plan=plan_resources(rows,parent['engine_schema'],ref(folder/'RESOURCE_PACK.json',root),root=root)
    domain=read(source_file(parent['input_domain'],root))
    domain.update(physics_configuration_id=identifier,solver_step_min=step,command_grid_min=step,run_period=case['run'])
    for device,programme in plan['values']['programs'].items():
        domain['programs'][device].update(duration_min=programme['duration_min'],resource_pack=ref(folder/'RESOURCE_PACK.json',root))
    save(folder/'DOMAIN.json',domain);case.update(case_id=identifier)
    case['environment']['physics_configuration_id']=identifier;save(folder/'CASE.json',case)
    fixture=copy.deepcopy(parent);fixture.update(id=identifier,model=ref(folder/'in.idf',root),
        resource_pack=ref(folder/'RESOURCE_PACK.json',root),input_domain=ref(folder/'DOMAIN.json',root),
        registered_numerical_overlay=ref(folder/'OVERLAY.json',root))
    save(folder/'FIXTURE.json',fixture)
    return ref(folder/'FIXTURE.json',root),case
