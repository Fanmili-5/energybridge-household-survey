"""Transactional, source-bound enclosure adaptation for reference experiments.

Clone constructions and materials at explicitly selected faces. The source
objects, geometry, adjacency and all unselected uses remain unchanged. This is
an extension of source preparation, not permission to override formal runs.
"""
from __future__ import annotations

import copy
import math

from .common import ROOT, digest, finite, read, require
from .idf import Fields, objects
from .source_adapter import selected, source_file

MATERIAL_FIELDS = ('roughness', 'thickness', 'conductivity', 'density', 'specific_heat',
                   'thermal_absorptance', 'solar_absorptance', 'visible_absorptance')


def layer_properties(row, fields):
    kind = row[0].casefold()
    if kind == 'material':
        values = {key: fields.get(row, key) for key in MATERIAL_FIELDS}
        require(values['roughness'] in ('VeryRough', 'Rough', 'MediumRough', 'MediumSmooth',
                                      'Smooth', 'VerySmooth'), 'ENVELOPE_ROUGHNESS_MISSING')
        for key in MATERIAL_FIELDS[1:]:
            require(values[key] != '', 'ENVELOPE_EFFECTIVE_DEFAULT_UNREVIEWED', [row[1], key])
            try:
                values[key] = float(values[key])
            except (ValueError, TypeError):
                require(False, 'ENVELOPE_NONNUMERIC_PROPERTY', [row[1], key])
            require(finite(values[key]), 'ENVELOPE_NONFINITE_PROPERTY', [row[1], key])
            require(values[key] > 0 if key in MATERIAL_FIELDS[1:5] else 0 <= values[key] <= 1,
                    'ENVELOPE_PROPERTY_RANGE', [row[1], key])
        return {'row': row, 'values': values,
                'R_m2K_W': values['thickness'] / values['conductivity'],
                'C_areal_J_m2K': values['thickness'] * values['density'] * values['specific_heat']}
    if kind in ('material:nomass', 'material:airgap'):
        r = float(fields.get(row, 'thermal_resistance'))
        require(math.isfinite(r) and r > 0, 'ENVELOPE_INVALID_RESISTANCE', row[1])
        return {'row': row, 'values': None, 'R_m2K_W': r, 'C_areal_J_m2K': 0.0,
                'massless_as_explicitly_declared_by_source': True}
    require(False, 'ENVELOPE_LAYER_MODEL_NOT_SUPPORTED', row[:2])


def construction_properties(rows, construction, fields):
    """Layer-only R and total heat capacity, not dynamic admittance or ground U."""
    materials = {r[1].casefold(): r for r in rows if r[0].casefold().startswith('material')}
    layers = []
    for name in construction[2:]:
        if not name:
            continue
        require(name.casefold() in materials, 'ENVELOPE_MATERIAL_REFERENCE_MISSING', name)
        layers.append(layer_properties(materials[name.casefold()], fields))
    require(bool(layers), 'ENVELOPE_EMPTY_CONSTRUCTION')
    return {'layer_order': 'outside_to_inside', 'layers': layers,
            'R_layers_m2K_W': sum(v['R_m2K_W'] for v in layers),
            'C_layers_J_m2K': sum(v['C_areal_J_m2K'] for v in layers),
            'surface_films_included': False, 'dynamic_admittance_claimed': False}


def insulation_thickness(target_U, film_R, existing_R, conductivity):
    """Design a positive uniform layer, never infer an unknown existing wall."""
    for value in (target_U, film_R, existing_R, conductivity):
        require(type(value) in (int, float) and finite(value) and value > 0,
                'ENVELOPE_DESIGN_INPUT_INVALID')
    thickness = conductivity * (1 / target_U - film_R - existing_R)
    require(thickness > 0, 'ENVELOPE_NO_POSITIVE_INSULATION_REQUIRED')
    return thickness


def check_provenance(layer, original, after, fields, root):
    require(after[0] == original[0] == 'Material', 'ENVELOPE_MATERIAL_CLASS_CHANGE_UNSUPPORTED')
    require(set(layer.get('field_provenance', {})) == set(MATERIAL_FIELDS), 'ENVELOPE_FIELD_PROVENANCE_MISSING')
    layer_properties(after, fields)
    for key, origin in layer['field_provenance'].items():
        if origin.get('method') == 'inherit_source':
            require(fields.get(after, key) == fields.get(original, key), 'ENVELOPE_INHERITED_FIELD_CHANGED', key)
        else:
            require(origin.get('method') in ('published_value', 'published_range_instance', 'design_derived')
                    and origin.get('locator') and origin.get('units'), 'ENVELOPE_PARAMETER_EVIDENCE_MISSING', key)
            source_file(origin['evidence'], root)
            if origin['method'] == 'published_range_instance':
                value = float(fields.get(after, key))
                require(origin['range'][0] <= value <= origin['range'][1] and origin.get('selection_basis'),
                        'ENVELOPE_RANGE_INSTANCE_UNJUSTIFIED', key)
            if origin['method'] == 'design_derived':
                require(origin.get('equation') and origin.get('inputs'), 'ENVELOPE_DERIVATION_INCOMPLETE')


def apply(rows, pack_ref, schema_ref, *, root=ROOT):
    pack = read(source_file(pack_ref, root))
    if pack.get('schema') == 'national_idf.complete_reference_enclosure_adaptation.v1':
        from .reference_enclosure import apply as complete_enclosure
        return complete_enclosure(rows, pack_ref, schema_ref, root=root)
    require(pack.get('schema') == 'national_idf.envelope_adaptation.v1', 'ENVELOPE_PACK_SCHEMA')
    require(pack.get('source_rows_sha256') == digest(rows), 'ENVELOPE_SOURCE_CONTEXT_CHANGED')
    require(pack.get('representation_kind') == 'controlled_reference', 'ENVELOPE_REFERENCE_SCOPE_REQUIRED')
    require(pack.get('country') and pack.get('scope') and pack.get('source_differences'),
            'ENVELOPE_APPLICABILITY_UNDECLARED')
    fields, result = Fields(source_file(schema_ref, root)), copy.deepcopy(rows)
    names = {(r[0].casefold(), r[1].casefold()) for r in rows if len(r) > 1}
    changed, inventory, additions = set(), [], []
    for assignment in pack['assignments']:
        surface = selected(rows, assignment['surface'])
        require(surface[0] == 'BuildingSurface:Detailed', 'ENVELOPE_FACE_KIND_UNSUPPORTED')
        index = assignment['surface']['index']
        require(index not in changed, 'ENVELOPE_FACE_EDIT_CONFLICT')
        construction = selected(rows, assignment['construction'])
        require(construction[0] == 'Construction' and fields.get(surface, 'construction_name') == construction[1],
                'ENVELOPE_CONSTRUCTION_PRECONDITION')
        require(assignment.get('outside_boundary_condition') == fields.get(surface, 'outside_boundary_condition')
                and assignment.get('surface_type') == fields.get(surface, 'surface_type'),
                'ENVELOPE_BOUNDARY_SCOPE_MISMATCH')
        require(len(assignment['layers']) == len(construction[2:]), 'ENVELOPE_LAYER_COUNT_CHANGED')
        new_construction = copy.deepcopy(construction)
        new_construction[1] = f"{pack['id']} construction {index}"
        require(('construction', new_construction[1].casefold()) not in names, 'ENVELOPE_NAME_COLLISION')
        names.add(('construction', new_construction[1].casefold()))
        material_inventory = []
        for slot, layer in enumerate(assignment['layers']):
            original = selected(rows, layer['source_material'])
            require(original[1] == construction[slot+2], 'ENVELOPE_LAYER_ORDER_MISMATCH')
            if layer.get('after') is None:
                require(layer.get('basis') == 'unchanged_complete_source_layer', 'ENVELOPE_LAYER_BASIS_MISSING')
                continue
            after = copy.deepcopy(layer['after'])
            check_provenance(layer, original, after, fields, root)
            after[1] = f"{pack['id']} material {index} {slot}"
            require(('material', after[1].casefold()) not in names, 'ENVELOPE_NAME_COLLISION')
            names.add(('material', after[1].casefold()))
            additions.append(after); new_construction[slot+2] = after[1]
            material_inventory.append({'slot_outside_to_inside': slot, 'before': original, 'after': after,
                                       'field_provenance': layer['field_provenance']})
        inserted = []
        for insertion_index, layer in enumerate(assignment.get('insert_layers', [])):
            slot = layer.get('after_source_layer_index')
            require(type(slot) is int and -1 <= slot < len(construction[2:]), 'ENVELOPE_INSERT_POSITION')
            # Insertion positions refer to the untouched source order, not to
            # an order that changes during this transaction.
            original = selected(rows, layer['source_material'])
            after = copy.deepcopy(layer['after'])
            check_provenance(layer, original, after, fields, root)
            require(layer.get('purpose') == 'design_derived_uniform_insulation', 'ENVELOPE_INSERT_PURPOSE')
            derivation = layer.get('thermal_design', {})
            source_file(derivation['evidence'], root)
            require(derivation.get('locator') and derivation.get('not_existing_stock_claim') is True,
                    'ENVELOPE_DESIGN_SCOPE')
            old_R = construction_properties(rows, construction, fields)['R_layers_m2K_W']
            expected = insulation_thickness(derivation['target_U_W_m2K'], derivation['film_R_m2K_W'],
                                            old_R, float(fields.get(after, 'conductivity')))
            require(math.isclose(float(fields.get(after, 'thickness')), expected, rel_tol=1e-12),
                    'ENVELOPE_DESIGN_THICKNESS_MISMATCH')
            require(not material_inventory and len(assignment['insert_layers']) == 1,
                    'ENVELOPE_COMBINED_DESIGN_NOT_SUPPORTED')
            after[1] = f"{pack['id']} inserted material {index} {insertion_index}"
            require(('material', after[1].casefold()) not in names, 'ENVELOPE_NAME_COLLISION')
            names.add(('material', after[1].casefold())); additions.append(after)
            inserted.append((slot, after[1]))
            material_inventory.append({'inserted_after_source_slot': slot, 'reference_material': original,
                'after': after, 'field_provenance': layer['field_provenance'], 'thermal_design': derivation})
        for slot, name in sorted(inserted, reverse=True):
            new_construction.insert(slot + 3, name)
        require(bool(material_inventory), 'ENVELOPE_EMPTY_ASSIGNMENT')
        additions.append(new_construction)
        fields.set(result[index], 'construction_name', new_construction[1]); changed.add(index)
        inventory.append({'surface': assignment['surface'], 'before': surface, 'after': result[index],
                          'construction_before': construction, 'construction_after': new_construction,
                          'materials': material_inventory,
                          'before_properties': construction_properties(rows, construction, fields),
                          'after_properties': construction_properties(rows+additions, new_construction, fields)})
    require(bool(changed), 'ENVELOPE_NO_FACES_SELECTED')
    # Exact no-leak check, including every interior/adjacent use of shared layers.
    for index, (before, after) in enumerate(zip(rows, result)):
        if index in changed:
            check = copy.deepcopy(after); fields.set(check, 'construction_name', fields.get(before, 'construction_name'))
            require(check == before, 'ENVELOPE_GEOMETRY_OR_ADJACENCY_CHANGED')
        else:
            require(before == after, 'ENVELOPE_UNSELECTED_OBJECT_CHANGED')
    result.extend(additions)
    return result, {'schema': 'national_idf.envelope_modifications.v1', 'pack': pack_ref,
                    'source_rows_sha256': digest(rows), 'result_rows_sha256': digest(result),
                    'modifications': inventory, 'geometry_and_adjacency_unchanged': True,
                    'unselected_objects_unchanged': True, 'source_materials_retained': True,
                    'physical_validation_passed': False, 'formal_admitted': False}
