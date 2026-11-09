"""Frozen life inputs under the unchanged clock, warmup and tail protocol."""
import argparse
import copy
import datetime as dt
from pathlib import Path

from national_idf.common import ROOT, read, require, save
from national_idf.idf import Fields, objects, parse, render
from national_idf.joint_case_runtime import compile_joint_case, run_joint_case
from national_idf.program_resources import model_signature, plan_resources
from national_idf.reference_workflow import ref
from national_idf.source_adapter import source_file
from national_idf.source_numerics import building_numerical_replacement, validate_model_overlay, WARMUP_FIELDS
from scripts.run_multicountry_life_inventories import scoped_fixture
from scripts.validate_multicountry_life import OUT

VARIANTS=[(1,14,7),(2,14,7),(5,14,7),(2,28,7),(2,14,14)]


def execute(label, step, warmup, days, arm, *, base_folder=None, output_label=None, case_file=None):
    folder=OUT/'numerics_life'/f'{output_label or label}_s{step}_w{warmup}_d{days}_{arm}'
    if (folder/'run/RUNTIME.json').is_file():return
    base=Path(base_folder).resolve() if base_folder else OUT/label
    fixture_path=base/'FIXTURE.json' if base_folder else scoped_fixture(base)[0]
    parent=read(fixture_path)
    protocol=read(ROOT/'configs/study_protocol.json')
    require((step,warmup,days) in VARIANTS and arm in ('baseline','intervention'),'LIFE_NUMERIC_UNREGISTERED_PROBE')
    folder.mkdir(parents=True,exist_ok=True)
    source=parse(source_file(parent['model'],ROOT).read_text());rows=copy.deepcopy(source)
    fields=Fields(source_file(parent['engine_schema'],ROOT))
    objects(rows,'Timestep')[0][1]=str(60//step)
    before=objects(source,'Building')[0];after=objects(rows,'Building')[0]
    fields.set(after,WARMUP_FIELDS[0],str(warmup))
    fields.set(after,WARMUP_FIELDS[1],str(protocol['warmup_max_days'][protocol['warmup_min_days'].index(warmup)]))
    changed=[k for k in WARMUP_FIELDS if fields.get(before,k)!=fields.get(after,k)]
    edits=building_numerical_replacement(before,after,changed,source_file(parent['engine_schema'],ROOT),
        ref(ROOT/'configs/study_protocol.json')) if changed else {}
    case=read(case_file or base/'CASE.json');begin=dt.date.fromisoformat(case['run']['start_date']);end=begin+dt.timedelta(days=days-1)
    case['run']['end_date']=end.isoformat()
    for key,value in {'end_month':end.month,'end_day_of_month':end.day,'end_year':end.year}.items():
        fields.set(objects(rows,'RunPeriod')[0],key,str(value))
    if arm=='baseline':case['controls']['dated_overrides']=[]
    (folder/'in.idf').write_text(render(rows))
    overlay={'schema':'national_idf.registered_model_numerical_overlay.v1','formal_admitted':False,
        'source_model':parent['model'],'target_model':ref(folder/'in.idf'),
        'protocol':ref(ROOT/'configs/study_protocol.json'),'warmup_overlay':edits,'step_min':step,'days':days}
    save(folder/'OVERLAY.json',overlay)
    validate_model_overlay(rows,ref(folder/'in.idf'),ref(folder/'OVERLAY.json'),parent['engine_schema'])
    # Reuse the source-interpreted whitegoods resources at the requested step.
    # Life changes only the separately owned general fixture demand schedules.
    if label=='US_apartment':library_root=ROOT/'reports/multicountry_idf_20261107/US_apartment_source_v2'
    elif step==1:library_root=ROOT/'reports/eb_six_joint_20261031'
    else:library_root=ROOT/'reports/public_originals_joint_steps_20261101'
    library=read(library_root/f'summer_{step}min/FIXTURE.json')
    original=parse(source_file(library['model'],ROOT).read_text())
    receipt=read(source_file(parent['life_installation_receipt'],ROOT))
    general={v['after'][1] for v in receipt['water_modifications']}
    plan=plan_resources(original,library['engine_schema'],library['resource_pack'])
    for kind in ('ElectricEquipment','WaterUse:Equipment','WaterUse:Connections'):
        require([r for r in objects(original,kind) if r[1] not in general]==
                [r for r in objects(rows,kind) if r[1] not in general], 'LIFE_NUMERICAL_RESOURCE_SOURCE_CHANGED',kind)
    # The library has a retired zero-valued HPXML tank correction. It is not a
    # whitegoods resource channel; the complete EB replacement stays untouched.
    schedules={s for p in plan['definition']['programs'].values() for s in p['schedules']}
    gains=lambda model:[r for r in objects(model,'OtherEquipment') if fields.get(r,'schedule_name') in schedules]
    require(gains(original)==gains(rows),'LIFE_NUMERICAL_WHITEGOODS_GAIN_SOURCE_CHANGED')
    pack=read(source_file(library['resource_pack'],ROOT));pack['binding_model_signature']=model_signature(rows)
    pack['source_evidence']+=[ref(base/'PREPARATION.json'),ref(folder/'OVERLAY.json')]
    save(folder/'RESOURCE_PACK.json',pack)
    identifier=parent['id']+'__'+folder.name
    domain=read(source_file(parent['input_domain'],ROOT));domain.update(physics_configuration_id=identifier,
        solver_step_min=step,command_grid_min=step,run_period=case['run'])
    for device,program in plan['values']['programs'].items():
        domain['programs'][device].update(duration_min=program['duration_min'],resource_pack=ref(folder/'RESOURCE_PACK.json'))
    save(folder/'DOMAIN.json',domain)
    case['case_id']=identifier;case['environment']['physics_configuration_id']=identifier;save(folder/'CASE.json',case)
    fixture=copy.deepcopy(parent);fixture.update(id=identifier,model=ref(folder/'in.idf'),
        resource_pack=ref(folder/'RESOURCE_PACK.json'),input_domain=ref(folder/'DOMAIN.json'),
        registered_numerical_overlay=ref(folder/'OVERLAY.json'))
    save(folder/'FIXTURE.json',fixture)
    compile_joint_case(ref(folder/'FIXTURE.json'),case,folder/'compiled',mode='engineering_reference')
    run_joint_case(folder/'compiled',folder/'run',mode='engineering_reference')
    print(folder.name,'native run complete',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--label',choices=['US','ES','US_apartment'],required=True)
    p.add_argument('--base-folder');p.add_argument('--output-label');p.add_argument('--case-file');args=p.parse_args()
    label=args.label
    for step,warmup,days in VARIANTS:
        for arm in ('baseline','intervention'):execute(label,step,warmup,days,arm,
            base_folder=args.base_folder,output_label=args.output_label,case_file=args.case_file)
