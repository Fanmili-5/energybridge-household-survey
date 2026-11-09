"""Source-driven IDF assembly with exact edits, EB bindings and fail-closed release.

This compiler creates review artifacts. It never starts EnergyPlus, generates
households, changes a control policy, or supplies missing physical values.
"""
from __future__ import annotations

import copy
import math
from datetime import date
from pathlib import Path
import shutil
import tempfile

from .common import ROOT, AdmissionError, digest, read, require, save, seal, sha
from .governance import DEVICE_CLASSES, REQUIRED_REVIEWS, configuration_failures
from .idf import Fields, objects, parse, render
from .source_numerics import building_numerical_replacement, effective_numerical_context
from .source_adapter import (ADAPTER, equipment_zone, housing_fingerprint, inspect_source, load_adapter,
                             normalized_version, protected, selected, selector, source_file)

REVIEW_DEPENDENCIES = {
    'source_applicability': ['source', 'site_weather'],
    'structure': ['housing', 'adapter', 'engine'],
    'source_baseline_run': ['source', 'source_dependencies', 'engine', 'numerics'],
    'conversion': ['source', 'changes', 'engine', 'adapter'],
    'equipment_applicability': ['housing', 'equipment', 'site_weather', 'eb_binding', 'engine'],
    'metering_and_energy_balances': ['source', 'source_dependencies', 'changes', 'equipment', 'eb_binding', 'engine'],
    'dynamic_response': ['source', 'source_dependencies', 'changes', 'equipment', 'site_weather', 'eb_binding', 'engine', 'numerics'],
    'numerical_convergence': ['source', 'source_dependencies', 'changes', 'equipment', 'site_weather', 'eb_binding', 'engine', 'numerics'],
    'parameter_inventory': ['source', 'source_dependencies', 'changes', 'equipment', 'site_weather', 'engine'],
    'modification_inventory': ['source', 'changes', 'adapter', 'eb_binding'],
    'weather_and_design_domain': ['housing', 'site_weather', 'equipment'],
    'life_and_control_support': ['source', 'source_dependencies', 'changes', 'equipment', 'eb_binding', 'site_weather', 'engine'],
}


def blueprint(identifier, root=ROOT, *, blueprint_ref=None):
    catalog = read(root / 'configs/assembly_catalog.json')
    if blueprint_ref is None:
        matches = [r for r in catalog['records'] if r['id'] == identifier]
        require(len(matches) == 1, 'ASSEMBLY_CONFIGURATION_NOT_REGISTERED', identifier)
        ref = matches[0]['blueprint']
    else:
        ref = blueprint_ref
    value = read(source_file(ref, root))
    require(value.get('schema') == 'national_idf.assembly_blueprint.v1'
            and value.get('id') == identifier, 'ASSEMBLY_BLUEPRINT_ID_OR_SCHEMA')
    required = {'schema', 'id', 'source_adapter', 'changes', 'legacy_group_policy',
                          'components', 'engine_schema', 'eb_mapping', 'eb_binding_implementation',
                          'site_weather', 'numerical_protocol', 'review_receipts', 'assembly_gaps',
                          'formal_release_gaps'}
    require(required <= set(value) <= required | {'dwelling_electricity_scope', 'life_installation_pack'}, 'ASSEMBLY_BLUEPRINT_FIELDS')
    return value, ref


def referenced_row(ref, root):
    rows = parse(source_file(ref['file'], root).read_text())
    return copy.deepcopy(selected(rows, ref['object']))


def transform(spec, manifest, source_rows, root=ROOT):
    """Edits always refer to the unchanged source, so ordering cannot shift selectors."""
    changes, deleted, replacements, added, numerical_buildings = [], set(), {}, [], []
    for op in spec['changes']:
        require(op.get('action') in ('remove', 'replace', 'add', 'replace_numerics') and bool(op.get('reason'))
                and isinstance(op.get('affected_meters'), list), 'MODIFICATION_INVENTORY_INCOMPLETE')
        expected_fields = {'action', 'reason', 'evidence', 'affected_meters'}
        if op['action'] != 'add': expected_fields.add('object')
        if op['action'] != 'remove': expected_fields.add('after')
        if op['action'] == 'replace_numerics': expected_fields.add('fields')
        require(set(op) == expected_fields, 'UNDECLARED_MODIFICATION_FIELD')
        source_file(op['evidence'], root)
        before, index = None, None
        if op['action'] != 'add':
            before = selected(source_rows, op['object'])
            index = op['object']['index']
            require(index not in deleted and index not in replacements, 'CONFLICTING_SOURCE_EDITS', index)
            if op['action'] != 'replace_numerics':
                require(not protected(before) and before[0].casefold() != 'version', 'HOUSING_OR_VERSION_EDIT_FORBIDDEN')
        after = referenced_row(op['after'], root) if op['action'] != 'remove' else None
        numerical_fields = None
        if op['action'] == 'replace_numerics':
            require(op['affected_meters'] == ['*'], 'BUILDING_NUMERICS_AFFECT_ALL_RESULTS')
            numerical_fields = building_numerical_replacement(before, after, op['fields'],
                source_file(spec['engine_schema'], root), spec['numerical_protocol'], root)
            numerical_buildings.append(before)
        elif after:
            require(not protected(after) and after[0].casefold() != 'version', 'HOUSING_OR_VERSION_EDIT_FORBIDDEN')
        if op['action'] == 'remove':
            deleted.add(index)
        elif op['action'] in ('replace', 'replace_numerics'):
            replacements[index] = after
        else:
            added.append(after)
        changes.append({'action': op['action'], 'source_index': index, 'before': before, 'after': after,
                        'reason': op['reason'], 'evidence': op['evidence'], 'affected_meters': op['affected_meters']})
        if numerical_fields:
            changes[-1]['numerical_fields'] = numerical_fields
    policies = spec.get('legacy_group_policy', {})
    require(set(policies) == set(manifest.get('legacy_groups', {})), 'LEGACY_DISPOSITION_INCOMPLETE')
    for name, group in manifest.get('legacy_groups', {}).items():
        policy = policies[name]
        indices = {s['index'] for s in group}
        require(policy in ('keep', 'remove', 'replace', 'replace_via_whole_plug_pack', 'replace_via_hvac_pack'), 'LEGACY_DISPOSITION_UNKNOWN', name)
        if policy == 'keep':
            require(not indices.intersection(deleted | set(replacements)), 'KEPT_SYSTEM_CHANGED', name)
        elif policy == 'replace_via_whole_plug_pack':
            refs = [spec['components'][device].get('whole_plug_load_replacement') for device in ('washer', 'dryer', 'dishwasher')]
            require(all(refs) and all(ref == refs[0] for ref in refs), 'WHOLE_PLUG_POLICY_PACK_NOT_BOUND')
            pack = read(source_file(refs[0], root))
            require(group == [pack['remove_aggregate']] and not indices.intersection(deleted | set(replacements)),
                    'WHOLE_PLUG_POLICY_WRONG_LEGACY_GROUP')
        elif policy == 'replace_via_hvac_pack':
            ref = spec['components']['air_conditioner'].get('joint_installation_pack')
            require(ref and ref == spec['components']['ev'].get('joint_installation_pack'), 'HVAC_POLICY_JOINT_PACK_NOT_BOUND')
            joint_pack = read(source_file(ref, root))
            pack = read(source_file(joint_pack.get('hvac_network'), root))
            require(pack['target_model'] == manifest['model'] and pack['retire_objects'] == group
                and not indices.intersection(deleted | set(replacements)), 'HVAC_POLICY_RETIREMENT_NOT_BOUND')
        else:
            require(indices <= deleted, 'OLD_SYSTEM_NOT_FULLY_REMOVED', name)
    # The file bytes are retained; only the relative file reference is relocated.
    dependencies = []
    for dep in manifest.get('schedule_files', []):
        i = dep['object']['index']
        require(i not in deleted and i not in replacements, 'SCHEDULE_FILE_EDIT_REQUIRES_NEW_ADAPTER')
        source = source_file(dep['file'], root)
        target = 'assets/' + dep['file']['sha256'] + source.suffix
        after = copy.deepcopy(source_rows[i]); after[3] = target
        replacements[i] = after
        dependencies.append({'source': dep['file'], 'output_path': target})
        changes.append({'action': 'replace', 'source_index': i, 'before': source_rows[i], 'after': after,
                        'reason': 'Relocate pinned schedule dependency; bytes and values unchanged',
                        'evidence': dep['file'], 'affected_meters': []})
    result = [copy.deepcopy(replacements.get(i, row)) for i, row in enumerate(source_rows) if i not in deleted] + added
    # Source housing hashes still protect the entire Building row. Only the
    # explicitly validated warmup replacement is normalized for this comparison.
    housing_rows = copy.deepcopy(result)
    for before in numerical_buildings:
        indices = [i for i, row in enumerate(housing_rows) if row[0] == 'Building' and row[1] == before[1]]
        require(len(indices) == 1, 'BUILDING_NUMERICAL_REPLACEMENT_IDENTITY')
        housing_rows[indices[0]] = copy.deepcopy(before)
    require(housing_fingerprint(housing_rows) == manifest['housing_sha256'], 'HOUSING_CHANGED_DURING_ASSEMBLY')
    require(parse(render(result)) == result, 'IDF_RENDER_ROUNDTRIP_CHANGED_VALUES')
    inventory = [{'action': 'keep', 'source_index': i, 'object': selector(source_rows, i)}
                 for i in range(len(source_rows)) if i not in deleted and i not in replacements] + changes
    return result, inventory, dependencies


def validate_objects(rows, schema_path):
    schema = read(schema_path)
    fields = Fields(schema_path)
    expected = schema['properties']['Version']['patternProperties']['.*']['properties']['version_identifier']['default']
    require(normalized_version(objects(rows, 'Version')[0][1]) == normalized_version(expected), 'IDF_SCHEMA_VERSION_MISMATCH')
    named = set()
    for row in rows:
        require(row[0] in schema['properties'], 'OBJECT_TYPE_OUTSIDE_ENGINE_SCHEMA', row[0])
        names = fields.names(row[0])
        if names and names[0] == 'name':
            key = row[0].casefold(), row[1].casefold()
            require(key not in named, 'DUPLICATE_NAMED_OBJECT', key)
            named.add(key)
        for field in names:
            if ('file_name' in field or 'filename' in field) and row[0] != 'Schedule:File':
                require(not fields.get(row, field), 'UNSUPPORTED_EXTERNAL_DEPENDENCY', [row[0], field])
    return fields


def eb_bindings(rows, mapping, fields, *, root=ROOT):
    """Check the existing EB ApplianceBinding contract without creating devices."""
    def one(kind, name):
        found = [r for r in objects(rows, kind) if r[1].casefold() == name.casefold()]
        require(len(found) == 1, 'EB_OBJECT_MAPPING_MISSING_OR_AMBIGUOUS', [kind, name])
        return found[0]
    equipment = mapping['equipment']
    require(set(equipment) >= {'washer', 'dryer', 'dishwasher', 'ev'}, 'EB_SIX_DEVICE_MAPPING_INCOMPLETE')
    claimed, controls, meters = set(), set(), {}
    for device in ['washer', 'dryer', 'dishwasher', 'ev']:
        row = one('ElectricEquipment', equipment[device]['equipment'])
        require(row[1].casefold() not in claimed, 'DEVICE_METER_DOUBLE_ASSIGNMENT', row[1])
        claimed.add(row[1].casefold())
        power = float(fields.get(row, 'design_level'))
        require(fields.get(row, 'design_level_calculation_method').casefold() == 'equipmentlevel'
                and math.isfinite(power) and power > 0, 'EB_DESIGN_POWER_MISSING', device)
        equipment_zone(rows, fields.get(row, 'zone_or_zonelist_or_space_or_spacelist_name'), fields)
        control = fields.get(row, 'schedule_name')
        schedule_kind = equipment[device].get('schedule_kind', 'Schedule:Constant')
        require(schedule_kind in ('Schedule:Constant', 'Schedule:Compact', 'Schedule:File'),
                'EB_POWER_SCHEDULE_KIND_UNSUPPORTED', schedule_kind)
        one(schedule_kind, control)
        require(control.casefold() not in controls, 'DEVICE_CONTROL_DOUBLE_ASSIGNMENT', control)
        controls.add(control.casefold())
        if device == 'ev':
            require(all(float(fields.get(row, k, 0)) == value for k, value in
                        [('fraction_latent', 0), ('fraction_radiant', 0), ('fraction_lost', 1)]), 'EV_INDOOR_GAINS_NOT_ZERO')
        meters[device] = {'variable': 'Electric Equipment Electricity Energy', 'key': row[1]}
    tank = one('WaterHeater:Stratified', mapping['water_heater'])
    one('Schedule:Constant', fields.get(tank, 'heater_1_setpoint_temperature_schedule_name'))
    meters['water_heater'] = {'variable': 'Water Heater Electricity Energy', 'key': tank[1]}
    hvac = mapping['hvac']
    from .hvac_ports import validate_ports
    ports = validate_ports(rows, mapping, fields)
    dwelling = None
    if mapping.get('retained_ideal_context'):
        from .retained_context import verify_retained
        context = verify_retained(rows, mapping['retained_ideal_context'], fields, root=root)
        require(context['target_zone'] == hvac['zone'], 'EB_CONTEXT_TARGET_ZONE_MISMATCH')
        require(mapping.get('dwelling_electricity_scope'), 'EB_CONTEXT_NEEDS_DWELLING_METER_SCOPE')
        from .dwelling_metering import verify as verify_dwelling
        dwelling = verify_dwelling(rows, mapping['dwelling_electricity_scope'], fields, root=root)
        require(dwelling['retained_context']['context'] == mapping['retained_ideal_context'],
                'EB_CONTEXT_AND_METER_SCOPE_MISMATCH')
    else:
        require(not objects(rows, 'ZoneHVAC:IdealLoadsAirSystem'), 'IDEAL_LOADS_REMAIN_WITH_SIX_DEVICE_BINDING')
    meters['air_conditioner'] = {'meters': ['Cooling:Electricity', 'Heating:Electricity', 'Fans:Electricity'],
                               'scope': 'source HVAC system; component separation still requires review'}
    return {'devices': meters, 'total_meter': dwelling['household_meter'] if dwelling else 'Electricity:Facility',
            **({'HVAC_ports': ports, 'whole_home_service_verified': False} if mapping.get('additional_hvac') else {}),
            **({'dwelling_scope': dwelling, 'facility_meter': 'Electricity:Facility',
                'facility_meter_is_not_household': True} if dwelling else {}),
            'native_EWH_electricity_only': True, 'EV_indoor_gains_zero': True,
            'energy_balance_verified': False, 'physical_device_evidence_verified': False}


def review_plan(fingerprints, receipts, root=ROOT, today=None):
    today = today or date.today()
    result = {}
    require(set(REVIEW_DEPENDENCIES) == set(REQUIRED_REVIEWS), 'REVIEW_DEPENDENCY_COVERAGE')
    for phase, dependencies in REVIEW_DEPENDENCIES.items():
        expected = {k: fingerprints[k] for k in dependencies}
        reusable = False
        if phase in receipts:
            try:
                r = read(source_file(receipts[phase], root))
                reusable = (r.get('phase') == phase and r.get('status') == 'passed'
                            and r.get('dependency_fingerprints') == expected and bool(r.get('scope'))
                            and isinstance(r.get('checks'), dict) and bool(r['checks'])
                            and all(v is True for v in r['checks'].values())
                            and date.fromisoformat(r['valid_until']) >= today)
            except (AdmissionError, KeyError, OSError, TypeError, ValueError):
                reusable = False
        result[phase] = {'action': 'reuse_bound_evidence' if reusable else 'review_required',
                         'dependency_fingerprints': expected}
    return result


def coupling_gaps(device, component, root=ROOT):
    """Carry a partial source review into the existing compiler without admitting it.

    This optional record adds constraints; it cannot replace component approval,
    IDF object bindings or validation receipts. A complete physical component
    requires a new reviewed implementation, not editing this record to 'ready'.
    """
    ref = component.get('coupling_review')
    if ref is None:
        return []
    value = read(source_file(ref, root))
    require(value.get('schema') == 'national_idf.partial_appliance_coupling.v1'
            and value.get('device') == device, 'COUPLING_REVIEW_IDENTITY')
    require(value.get('formal_admitted') is False and value.get('physical_model_complete') is False,
            'PARTIAL_COUPLING_CANNOT_GRANT_ADMISSION')
    require(value.get('evidence') and value.get('unresolved'), 'PARTIAL_COUPLING_REVIEW_INCOMPLETE')
    for evidence in value['evidence']:
        source_file(evidence, root)
    if value.get('resource_profile'):
        from .appliance_profile import load_profile
        load_profile(value['resource_profile'], device=device, root=root)
    water = value['connections']['water']
    if water['inlet'] in ('cold_only', 'none'):
        require(type(water['external_hot_water_L_per_cycle']) in (int, float)
                and water['external_hot_water_L_per_cycle'] == 0,
                'COLD_ONLY_APPLIANCE_CANNOT_DRAW_HOT_WATER', device)
    if water['inlet'] == 'cold_only':
        require(value['connections']['water_heating_electricity_owner'] == device,
                'INTERNAL_WATER_HEAT_DOUBLE_COUNT', device)
    require(value['room_sensible_heat_W'] is None and value['room_moisture_kg_s'] is None,
            'PARTIAL_COUPLING_HEAT_MOISTURE_NOT_IDENTIFIED')
    return [{'code': 'APPLIANCE_COUPLING_UNRESOLVED', 'component': device,
             'source_review': ref, 'missing': value['unresolved']}]


def plan_assembly(identifier, root=ROOT, *, blueprint_ref=None):
    spec, ref = blueprint(identifier, root, blueprint_ref=blueprint_ref)
    manifest, original = load_adapter(spec['source_adapter'], root)
    rows, inventory, dependencies = transform(spec, manifest, original, root)
    gaps = list(spec.get('assembly_gaps', []))
    require(set(spec['components']) == DEVICE_CLASSES, 'SIX_COMPONENTS_REQUIRED')
    load_replacement = None
    replacements = [spec['components'][device].get('whole_plug_load_replacement') for device in ('washer', 'dryer', 'dishwasher')]
    if any(replacements):
        require(all(replacements) and all(ref == replacements[0] for ref in replacements), 'LOAD_REPLACEMENT_NOT_JOINTLY_BOUND')
        from .load_replacement import apply as replace_plugs
        rows, load_replacement, extra_dependencies = replace_plugs(rows, replacements[0], spec['engine_schema'], root=root)
        dependencies.extend(extra_dependencies)
        require(load_replacement['empty_enclosure_installation'] or
                any(policy == 'replace_via_whole_plug_pack' for policy in spec['legacy_group_policy'].values()),
                'WHOLE_PLUG_REPLACEMENT_NEEDS_EXPLICIT_LEGACY_POLICY')
        inventory.append({'action': 'install_sourced_plugs_into_empty_enclosure' if load_replacement['empty_enclosure_installation']
                          else 'replace_whole_plug_load_aggregate', 'before': load_replacement['removed_whole_aggregate'],
            'after': [item['after'] for item in load_replacement['inserted']], 'evidence': replacements[0],
            'affected_meters': ['Electricity:Facility'], 'reason': 'Declared complete experimental replacement; no inferred old fractions or residual'})
    mains = None
    if spec['components']['water_heater'].get('mains_boundary'):
        from .weather_mains import apply as apply_mains
        rows, mains = apply_mains(rows, spec['components']['water_heater']['mains_boundary'], root=root)
        inventory.append({'action': 'bind_weather_derived_mains', 'before': mains['before'], 'after': mains['after'],
            'evidence': mains['boundary'], 'affected_meters': ['WaterHeater', 'WaterUse:Equipment'],
            'reason': mains['basis']})
    supply = None
    if spec['components']['water_heater'].get('supply_package'):
        from .supply_network import apply as apply_supply
        rows, supply, extra_dependencies = apply_supply(rows,
            spec['components']['water_heater']['supply_package'], spec['engine_schema'], root=root)
        dependencies.extend(extra_dependencies)
        inventory.append({'action': 'install_dependency_closed_supply_network', 'before': None,
            'after': [item['after'] for item in supply['source_objects']], 'evidence': supply['pack'],
            'affected_meters': ['WaterSystems:Electricity', 'InteriorEquipment:Electricity', 'Water'],
            'reason': 'Complete public stratified plant, four water uses and source correction; no Python heater electricity'})
    joint = None
    joint_refs = [spec['components'][device].get('joint_installation_pack') for device in ('air_conditioner', 'ev')]
    if any(joint_refs):
        require(all(joint_refs) and joint_refs[0] == joint_refs[1], 'HVAC_EV_INSTALLATION_NOT_JOINTLY_BOUND')
        if read(source_file(joint_refs[0], root)).get('hvac_network_group'):
            group = read(source_file(read(source_file(joint_refs[0], root))['hvac_network_group'], root))
            for port in group['ports']:
                air = read(source_file(port['network'], root))
                require(air.get('source_operation_replacement') and not air['retire_objects'],
                    'EMPTY_HVAC_INSTALLATION_CANNOT_HAVE_RETIREMENT')
        if read(source_file(joint_refs[0], root)).get('hvac_network'):
            air = read(source_file(read(source_file(joint_refs[0], root))['hvac_network'], root))
            if air.get('source_operation_replacement'):
                require(not air['retire_objects'], 'EMPTY_HVAC_INSTALLATION_CANNOT_HAVE_RETIREMENT')
            else:
                require('replace_via_hvac_pack' in spec['legacy_group_policy'].values(),
                        'HVAC_INSTALLATION_NEEDS_EXPLICIT_RETIREMENT_POLICY')
        from .joint_installation import apply as apply_joint
        rows, joint = apply_joint(rows, joint_refs[0], spec['engine_schema'], root=root)
        gaps.extend(joint['gaps'])
        inventory.append({'action': 'bind_complete_source_hvac_and_outdoor_EV', 'evidence': joint_refs[0],
            'before': None, 'after': joint['HVAC_changes']+joint['EV_inserted'],
            'affected_meters': ['Electricity:Facility', 'InteriorEquipment:Electricity', 'Heating:Electricity', 'Cooling:Electricity', 'Fans:Electricity'],
            'reason': 'Existing EB source controls; no HVAC transfer claimed when source context does not match'})
    from .installation import assembly_installation, installation_receipt
    installation = assembly_installation(spec, manifest, original, rows, root=root)
    if installation is not None:
        rows = installation['new_model_rows']
        gaps.extend(installation['gaps'])
    dwelling_metering = None
    if spec.get('dwelling_electricity_scope'):
        from .dwelling_metering import install as install_dwelling_metering
        rows, dwelling_metering = install_dwelling_metering(rows, spec['dwelling_electricity_scope'],
            spec['engine_schema'], root=root)
        inventory.append({'action': 'install_source_bound_dwelling_context_meters',
            'evidence': spec['dwelling_electricity_scope'], 'before': None,
            'after': dwelling_metering['native_meter_objects'], 'affected_meters': [
                dwelling_metering['household_meter'], dwelling_metering['context_meter']],
            'reason': 'Retain native whole-building meter and separately reconcile source-defined dwelling'})
    life_installation = None
    if spec.get('life_installation_pack'):
        from .life_installation import install as install_life
        rows, life_installation = install_life(rows, spec['life_installation_pack'], spec['engine_schema'], root=root)
        inventory.append({'action': 'install_source_people_and_fixture_CASE_channels',
            'evidence': spec['life_installation_pack'], 'before': None,
            'after': life_installation['water_modifications']+life_installation['additions'],
            'affected_meters': ['WaterSystems:Electricity', 'Water'],
            'reason': 'Source People physics and existing native water plant; explicit single-zone engineering port'})
    for name, component in spec['components'].items():
        gaps.extend(coupling_gaps(name, component, root))
        if component.get('status') not in ('engineering_reference', 'reviewed') or not component.get('evidence'):
            gaps.append({'code': 'COMPONENT_EVIDENCE_MISSING', 'component': name})
        else:
            source_file(component['evidence'], root)
    fields, mapping, meters = None, None, None
    if spec.get('engine_schema'):
        fields = validate_objects(rows, source_file(spec['engine_schema'], root))
    else:
        gaps.append({'code': 'MATCHING_OFFICIAL_ENGINE_SCHEMA_MISSING'})
    if spec.get('eb_mapping'):
        mapping = read(source_file(spec['eb_mapping'], root))
        source_file(spec['eb_binding_implementation'], root)
        if fields:
            meters = eb_bindings(rows, mapping, fields, root=root)
            if mapping.get('additional_hvac') or (joint and joint.get('HVAC_ports')):
                require(joint and joint.get('HVAC_ports') == [mapping['hvac']]+mapping.get('additional_hvac', []),
                    'EB_HVAC_GROUP_INSTALLATION_MAPPING_MISMATCH')
    else:
        gaps.append({'code': 'EB_OBJECT_MAPPING_MISSING'})
    from .program_resources import assembly_resources
    resources = assembly_resources(rows, spec, root=root)
    # Location/weather references are data, never branches in the compiler.
    for ref_item in spec.get('site_weather', {}).get('artifacts', []):
        source_file(ref_item, root)
    numerical_ref = spec['numerical_protocol']
    source_file(numerical_ref, root)
    require(numerical_ref['sha256'] == sha(root / 'configs/study_protocol.json'), 'NUMERICAL_PROTOCOL_CHANGED')
    numerical_context = (effective_numerical_context(rows, source_file(spec['engine_schema'], root), numerical_ref)
                         if fields else {'protocol': numerical_ref, 'effective_model_context': None})
    fingerprints = {
        'source': digest({'model': manifest['model'], 'source_baseline': manifest.get('source_baseline')}),
        'housing': manifest['housing_sha256'], 'source_dependencies': digest(manifest.get('schedule_files', [])),
        'adapter': digest({'manifest': spec['source_adapter'], 'code': sha(Path(__file__).with_name('source_adapter.py')),
                           **({'housing_rules': manifest['rule_construction']} if manifest.get('rule_construction') else {})}),
        'equipment': digest(spec['components']), 'site_weather': digest(spec.get('site_weather')),
        'changes': digest({'operations': spec['changes'], 'legacy_group_policy': spec['legacy_group_policy'],
                           'compiler_code': sha(__file__), 'installation': installation_receipt(installation),
                           'whole_plug_load_replacement': load_replacement, 'weather_mains': mains,
                           **({'supply_network': supply} if supply is not None else {}),
                           **({'joint_installation': joint} if joint is not None else {}),
                           **({'dwelling_metering': dwelling_metering} if dwelling_metering is not None else {}),
                           **({'life_installation': life_installation} if life_installation is not None else {})}),
        'engine': digest({'version': manifest['engine_version'], 'schema': spec.get('engine_schema')}),
        'numerics': digest(numerical_context),
        'eb_binding': digest({'mapping': spec.get('eb_mapping'), 'implementation': spec.get('eb_binding_implementation'),
            **({'additional_HVAC_port_binding': sha(Path(__file__).with_name('hvac_ports.py'))}
               if mapping and mapping.get('additional_hvac') else {})}),
    }
    return {'schema': 'national_idf.assembly_plan.v1', 'id': identifier, 'blueprint': ref,
            'source': inspect_source(spec['source_adapter'], root), 'adapter': ADAPTER,
            'engineering_compilation_ready': not gaps, 'assembly_gaps': gaps,
            'formal_release_gaps': manifest.get('source_scope_gaps', []) + spec.get('formal_release_gaps', []),
            'modifications': inventory, 'dependencies': dependencies, 'eb_mapping': mapping,
            'metering': meters, 'installation': installation_receipt(installation),
            'whole_plug_load_replacement': load_replacement, 'weather_mains': mains,
            **({'supply_network': supply} if supply is not None else {}),
            **({'joint_installation': joint} if joint is not None else {}),
            **({'dwelling_metering': dwelling_metering} if dwelling_metering is not None else {}),
            **({'life_installation': life_installation} if life_installation is not None else {}),
            'program_resources': resources, 'fingerprints': fingerprints,
            'validation_plan': review_plan(fingerprints, spec.get('review_receipts', {}), root),
            'formal_admitted': False, 'physical_values_invented': False,
            'household_or_AB_generated': False, 'new_model_rows': rows}


def compile_assembly(identifier, out, *, mode='formal', root=ROOT, blueprint_ref=None):
    require(mode in ('formal', 'engineering_reference'), 'UNKNOWN_EXECUTION_MODE')
    release=None
    if mode == 'formal':
        require(blueprint_ref is None, 'FORMAL_INLINE_BLUEPRINT_FORBIDDEN')
        from .release import reviewed_assembly
        record,plan,release=reviewed_assembly(identifier,root)
    else:
        plan = plan_assembly(identifier, root, blueprint_ref=blueprint_ref)
    require(plan['engineering_compilation_ready'], 'ASSEMBLY_EVIDENCE_BLOCKED', plan['assembly_gaps'])
    out = Path(out).absolute()
    require(not out.exists() and not out.is_symlink(), 'OUTPUT_EXISTS', str(out))
    # All validation and source reads precede any output directory creation.
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.idf-assembly-', dir=out.parent) as temporary:
        stage = Path(temporary) / 'build'; stage.mkdir()
        (stage / 'in.idf').write_text(render(plan.pop('new_model_rows')))
        for dep in plan['dependencies']:
            target = stage / dep['output_path']; target.parent.mkdir(exist_ok=True)
            shutil.copyfile(source_file(dep['source'], root), target)
        save(stage / 'MODIFICATIONS.json', plan['modifications'])
        save(stage / 'EB_MAPPING.json', plan['eb_mapping'])
        save(stage / 'METERING.json', plan['metering'])
        for key, filename in [('whole_plug_load_replacement', 'LOAD_REPLACEMENT.json'), ('weather_mains', 'WEATHER_MAINS.json'), ('supply_network', 'SUPPLY_NETWORK.json'), ('joint_installation', 'JOINT_INSTALLATION.json'), ('dwelling_metering', 'DWELLING_METERING.json'), ('life_installation', 'LIFE_INSTALLATION.json')]:
            if plan.get(key) is not None:
                save(stage / filename, plan[key])
        if plan['installation'] is not None:
            save(stage / 'INSTALLATION.json', plan['installation'])
        from .program_resources import write_resources
        write_resources(stage, plan['program_resources'], root=root)
        save(stage / 'VALIDATION_PLAN.json', plan['validation_plan'])
        save(stage / 'ASSEMBLY.json', plan)
        if release:save(stage / 'SOURCE_COMPILER_RELEASE.json',release)
        metadata={'schema': 'national_idf.assembled_reference.v1', 'id': identifier,
                  'execution_mode': mode, 'formal_admitted': False,
                  'physical_validation_passed': False, 'engine_started': False}
        if release:metadata.update(source_compilation_reviewed=True,physics_configuration_id=identifier)
        receipt = seal(stage, metadata)
        require(not out.exists() and not out.is_symlink(), 'OUTPUT_EXISTS', str(out))
        stage.rename(out)
    return receipt
