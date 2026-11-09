"""Prepare the existing registered numerical overlay without launching six devices.

Inventory adapters can then use the unchanged projection compiler. Source
profiles and all physical coefficients are retained;only the registered clock,
warmup and calendar settings vary.
"""
import copy
import datetime as dt
from pathlib import Path

from .common import ROOT, read, require, save
from .idf import Fields, objects, parse, render
from .program_resources import model_signature, plan_resources
from .reference_workflow import ref
from .source_adapter import source_file
from .source_numerics import building_numerical_replacement, validate_model_overlay, WARMUP_FIELDS


def prepare(parent_ref, case, library_label, folder, step, warmup, days, arm, identifier, *, root=ROOT):
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    parent = read(source_file(parent_ref, root)); protocol = read(root / 'configs/study_protocol.json')
    require((step, warmup, days) in ((1,14,7),(2,14,7),(5,14,7),(2,28,7),(2,14,14))
            and arm in ('baseline','intervention'), 'REFERENCE_UNREGISTERED_NUMERIC_VARIANT')
    source = parse(source_file(parent['model'], root).read_text()); rows = copy.deepcopy(source)
    fields = Fields(source_file(parent['engine_schema'], root)); objects(rows, 'Timestep')[0][1] = str(60 // step)
    before, after = objects(source, 'Building')[0], objects(rows, 'Building')[0]
    fields.set(after, WARMUP_FIELDS[0], str(warmup))
    fields.set(after, WARMUP_FIELDS[1], str(protocol['warmup_max_days'][protocol['warmup_min_days'].index(warmup)]))
    changed = [key for key in WARMUP_FIELDS if fields.get(before, key) != fields.get(after, key)]
    overlay_fields = building_numerical_replacement(before, after, changed, source_file(parent['engine_schema'], root),
        ref(root / 'configs/study_protocol.json', root)) if changed else {}
    case = copy.deepcopy(case); start = dt.date.fromisoformat(case['run']['start_date']); end = start + dt.timedelta(days=days-1)
    case['run']['end_date'] = end.isoformat()
    for key, value in {'end_month':end.month, 'end_day_of_month':end.day, 'end_year':end.year}.items():
        fields.set(objects(rows, 'RunPeriod')[0], key, str(value))
    if arm == 'baseline': case['controls']['dated_overrides'] = []
    (folder / 'in.idf').write_text(render(rows))
    overlay = {'schema':'national_idf.registered_model_numerical_overlay.v1','formal_admitted':False,
        'source_model':parent['model'],'target_model':ref(folder / 'in.idf',root),
        'protocol':ref(root / 'configs/study_protocol.json',root),'warmup_overlay':overlay_fields,'step_min':step,'days':days}
    save(folder / 'OVERLAY.json', overlay)
    validate_model_overlay(rows, ref(folder / 'in.idf',root), ref(folder / 'OVERLAY.json',root), parent['engine_schema'],root=root)
    if library_label == 'US_apartment': library_root = root / 'reports/multicountry_idf_20261107/US_apartment_source_v2'
    else:
        require(library_label == 'US', 'REFERENCE_RESOURCE_LIBRARY_UNKNOWN')
        library_root = root / ('reports/eb_six_joint_20261031' if step == 1 else 'reports/public_originals_joint_steps_20261101')
    library = read(library_root / f'summer_{step}min/FIXTURE.json')
    original = parse(source_file(library['model'],root).read_text())
    life = read(source_file(parent['life_installation_receipt'],root)); general = {v['after'][1] for v in life['water_modifications']}
    plan = plan_resources(original,library['engine_schema'],library['resource_pack'],root=root)
    for kind in ('ElectricEquipment','WaterUse:Equipment','WaterUse:Connections'):
        require([r for r in objects(original,kind) if r[1] not in general] ==
                [r for r in objects(rows,kind) if r[1] not in general], 'REFERENCE_NUMERIC_RESOURCE_OWNERS_CHANGED',kind)
    schedules = {name for p in plan['definition']['programs'].values() for name in p['schedules']}
    gains = lambda model:[r for r in objects(model,'OtherEquipment') if fields.get(r,'schedule_name') in schedules]
    require(gains(original) == gains(rows),'REFERENCE_NUMERIC_RESOURCE_GAINS_CHANGED')
    pack = read(source_file(library['resource_pack'],root)); pack['binding_model_signature'] = model_signature(rows)
    pack['source_evidence'].append(ref(folder / 'OVERLAY.json',root)); save(folder / 'RESOURCE_PACK.json',pack)
    domain = read(source_file(parent['input_domain'],root))
    domain.update(physics_configuration_id=identifier,solver_step_min=step,command_grid_min=step,run_period=case['run'])
    for device, value in plan['values']['programs'].items():
        domain['programs'][device].update(duration_min=value['duration_min'],resource_pack=ref(folder / 'RESOURCE_PACK.json',root))
    save(folder / 'DOMAIN.json',domain); case['case_id']=identifier; case['environment']['physics_configuration_id']=identifier
    save(folder / 'CASE.json',case)
    fixture=copy.deepcopy(parent);fixture.update(id=identifier,model=ref(folder / 'in.idf',root),
        resource_pack=ref(folder / 'RESOURCE_PACK.json',root),input_domain=ref(folder / 'DOMAIN.json',root),
        registered_numerical_overlay=ref(folder / 'OVERLAY.json',root))
    save(folder / 'FIXTURE.json',fixture)
    return ref(folder / 'FIXTURE.json',root), case
