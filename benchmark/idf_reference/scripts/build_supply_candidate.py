"""Register a separate cold-condensing/stratified A1 review, never admit it."""
import copy
from collections import Counter

from national_idf.assembly import plan_assembly
from national_idf.common import ROOT, read, require, save, sha
from national_idf.idf import parse, render
from national_idf.source_adapter import selector
from national_idf.supply_network import ZONE_REFS, closure, items
from scripts.build_supply_source import OUT, ref

ID = 'tengchong_a1_condensing_stratified_supply_20261031'


def main():
    require(not (OUT / 'DELIVERY_MANIFEST.json').exists(), 'SEALED_DELIVERY_CANNOT_BE_REBUILT')
    model = OUT / 'source_model/run/in.idf'
    schema_path = ROOT / 'data/source/china_parameter_pack_20261028/official_25_2/Energy+.schema.epJSON'
    rows, schema = parse(model.read_text()), read(schema_path)
    auxiliary = ['water heater energy adjustment1', 'general water latent', 'general water sensible']
    indices = closure(rows, schema, 'dhw loop', auxiliary)
    ports = sorted({rows[i][p] for i in indices for p, name, meta in items(rows[i], schema)
                    if set(meta.get('object_list', [])) & ZONE_REFS and rows[i][p]})
    pack = {'schema': 'national_idf.sourced_supply_network.v1', 'id': ID,
        'source_model': ref(model), 'source_loop': 'dhw loop', 'prefix': 'EB_WATER_',
        'source_auxiliary_equipment': auxiliary, 'source_thermal_ports': ports,
        'installation_zone': 'Main_Zone', 'source_objects': [selector(rows, i) for i in indices],
        'water_use_heating_energy_added_to_grid': False, 'Python_heater_electricity_added': False,
        'basis': ref(OUT / 'SOURCE_RECEIPT.json'),
        'thermal_port_relocation': 'Declared experimental indoor installation; no inference of actual Chinese plumbing',
        'unknown': ['actual local plumbing losses', 'actual local pump power', 'local measured mains temperatures'],
        'source_simplifications': ['adiabatic pipes', 'zero-power pump', 'published generic fixtures and distribution waste'],
        'formal_admitted': False}
    path = ROOT / f'configs/installation_packs/{ID}.json'; save(path, pack)
    replacement = read(ROOT / 'configs/installation_packs/tengchong_a1_whole_plug_reference_20261031.json')
    replacement['id'] = ID+'_whole_plugs'
    old_rows = parse((ROOT / replacement['components']['washer']['model']['path']).read_text())
    for value in replacement['components'].values():
        old = old_rows[value['equipment']['index']]
        found = [i for i, row in enumerate(rows) if row[:2] == old[:2]]
        require(len(found) == 1, 'SOURCE_EQUIPMENT_NOT_UNIQUE')
        value['equipment'] = selector(rows, found[0]); value['model'] = ref(model)
        value['schedule_file'] = ref(model.parent / 'in.schedules.csv')
        if value.get('EMS_controller'):
            value['EMS_controller'] = [selector(rows, next(i for i, row in enumerate(rows)
                if row[:2] == [entry['kind'], entry['name']])) for entry in value['EMS_controller']]
    replacement_path = path.with_name(ID+'_whole_plugs.json'); save(replacement_path, replacement)
    spec = copy.deepcopy(read(ROOT / 'configs/assembly_blueprints/tengchong_a1_reference_boundary_review_20261031.json'))
    spec['id'] = ID
    spec['assembly_gaps'] = [g for g in spec['assembly_gaps'] if g['code'] != 'EXTERNAL_HOT_WATER_PLANT_NOT_ASSEMBLED']
    spec['assembly_gaps'] += [{'code': 'STRATIFIED_TANK_JOINT_NUMERICAL_ACCEPTANCE_PENDING'},
        {'code': 'SOURCE_IDEAL_HVAC_STILL_PRESENT_NOT_SIX_DEVICE_EXPERIMENT'}]
    for device in ('washer', 'dryer', 'dishwasher'):
        spec['components'][device]['evidence'] = ref(replacement_path)
        spec['components'][device]['whole_plug_load_replacement'] = ref(replacement_path)
    spec['components']['water_heater'].update(status='engineering_reference', evidence=ref(path),
        supply_package=ref(path), model_key='hpxml_004ca3ce_native_stratified_reference', version='source_004ca3ce')
    specpath = ROOT / f'configs/assembly_blueprints/{ID}.json'; save(specpath, spec)
    catalog_path = ROOT / 'configs/assembly_catalog.json'; catalog = read(catalog_path)
    catalog['records'] = [item for item in catalog['records'] if item['id'] != ID]
    catalog['records'].append({'id': ID, 'blueprint': ref(specpath)}); save(catalog_path, catalog)
    plan = plan_assembly(ID); model_rows = plan.pop('new_model_rows')
    save(OUT / 'A1_CANDIDATE_PLAN.json', plan)
    review = OUT / 'A1_candidate_review'; review.mkdir(exist_ok=True)
    (review / 'in.idf').write_text(render(model_rows))
    import shutil
    for dependency in plan['dependencies']:
        target = review / dependency['output_path']; target.parent.mkdir(exist_ok=True)
        shutil.copyfile(ROOT / dependency['source']['path'], target)
    save(review / 'SUPPLY_NETWORK.json', plan['supply_network'])
    save(OUT / 'IMPORT_SUMMARY.json', {'source_objects': len(indices), 'types': dict(Counter(rows[i][0] for i in indices)),
        'source_thermal_ports': ports, 'target_zone': 'Main_Zone', 'water_use_count': 4,
        'engineering_compilation_ready': plan['engineering_compilation_ready'], 'formal_admitted': False,
        'actual_China_simulation_started': False, 'remaining_gaps': plan['assembly_gaps']})
    print(f'{len(indices)} water objects installed into A1 review; unsupported China execution remains blocked')


if __name__ == '__main__': main()
