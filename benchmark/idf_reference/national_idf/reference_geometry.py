"""Check source-defined whole-home geometry against native EnergyPlus readback.

Exploded HPXML surfaces retain area/orientation/volume semantics. This module
does not reinterpret them as a closed measured floor plan or a legal area.
"""
from collections import Counter
import copy
import csv
from decimal import Decimal, ROUND_HALF_UP
import xml.etree.ElementTree as ET

from .common import ROOT, require
from .idf import Fields, objects, parse
from .source_adapter import source_file


def check(fixture, source_idf_ref, xml_ref, eio_ref, *, root=ROOT):
    rows = parse(source_file(fixture['model'], root).read_text())
    source = parse(source_file(source_idf_ref, root).read_text())
    fields = Fields(source_file(fixture['engine_schema'], root))
    kinds = {'GlobalGeometryRules', 'Zone', 'Space', 'InternalMass', 'BuildingSurface:Detailed',
             'FenestrationSurface:Detailed', 'SurfaceProperty:ExposedFoundationPerimeter'}
    def geometry(model):
        result = []
        for row in model:
            if row[0] not in kinds and not row[0].startswith('Shading:'): continue
            value = copy.deepcopy(row)
            if row[0] == 'BuildingSurface:Detailed': fields.set(value, 'construction_name', 'BOUND_SEPARATELY')
            result.append(value)
        return Counter(tuple(r) for r in result)
    require(geometry(rows) == geometry(source), 'REFERENCE_SOURCE_GEOMETRY_CHANGED')
    surfaces = {r[1]: r for r in objects(rows, 'BuildingSurface:Detailed')}
    pair_names = []
    for row in surfaces.values():
        if fields.get(row, 'outside_boundary_condition') != 'Surface': continue
        other = surfaces.get(fields.get(row, 'outside_boundary_condition_object'))
        require(other is not None and fields.get(other, 'outside_boundary_condition') == 'Surface'
                and fields.get(other, 'outside_boundary_condition_object') == row[1], 'REFERENCE_ADJACENCY_NOT_RECIPROCAL')
        pair_names.append([row[1], other[1]])
    tree = ET.parse(source_file(xml_ref, root))
    for item in tree.iter(): item.tag = item.tag.split('}')[-1]
    construction = tree.find('.//BuildingSummary/BuildingConstruction')
    require(construction is not None, 'REFERENCE_XML_CONSTRUCTION_MISSING')
    floor = Decimal(construction.findtext('ConditionedFloorArea')) * Decimal('0.09290304')
    volume = Decimal(construction.findtext('ConditionedBuildingVolume')) * Decimal('0.028316846592')
    zone = fixture['EB_mapping']['hvac']['zone']
    native, header = [], None
    with source_file(eio_ref, root).open() as stream:
        for row in csv.reader(stream):
            if not row: continue
            row = [value.strip() for value in row]
            if row[0] == '! <Zone Information>': header = row[1:]
            elif row[0] == 'Zone Information':
                require(header is not None, 'REFERENCE_EIO_ZONE_HEADER_MISSING')
                native.append(dict(zip(header, row[1:])))
    matching = [r for r in native if r['Zone Name'].casefold() == zone.casefold()]
    require(len(matching) == 1, 'REFERENCE_NATIVE_ZONE_NOT_UNIQUE'); actual = matching[0]
    def at_precision(value, printed):
        return value.quantize(Decimal(1).scaleb(Decimal(printed).as_tuple().exponent), rounding=ROUND_HALF_UP) == Decimal(printed)
    require(at_precision(floor, actual['Floor Area {m2}']) and at_precision(volume, actual['Volume {m3}']),
            'REFERENCE_NATIVE_AREA_VOLUME_CONFLICT')
    require(actual['Zone Multiplier'] == actual['Zone List Multiplier'] == '1', 'REFERENCE_NATIVE_MULTIPLIER_CONFLICT')
    native_zone = next(r for r in objects(rows, 'Zone') if r[1] == zone)
    require(Decimal(fields.get(native_zone, 'volume')) == volume, 'REFERENCE_EXPLICIT_AIR_VOLUME_CONFLICT')
    return {'schema': 'national_idf.source_native_reference_geometry.v1',
        'source_idf': source_idf_ref, 'source_xml': xml_ref, 'fixture_model': fixture['model'], 'native_eio': eio_ref,
        'source_geometry_orientation_air_volume_and_boundary_rows_unchanged': True,
        'complete_source_context_retained': True, 'native_area_volume_and_multipliers_match_source': True,
        'conditioned_area_m2': float(floor), 'conditioned_air_volume_m3': float(volume),
        'native_conditioned_zone': actual, 'all_native_zones': native, 'reciprocal_surface_references': pair_names,
        'boundary_counts': dict(Counter(fields.get(r, 'outside_boundary_condition') for r in surfaces.values())),
        'source_housing_type': construction.findtext('ResidentialFacilityType'),
        'source_vertical_surroundings': tree.findtext('.//BuildingSummary/Site/VerticalSurroundings'),
        'area_basis': 'HPXML conditioned floor area,not survey/legal/net measurement',
        'geometry_representation': 'Published area/orientation/explicit-volume method;not closed measured layout',
        'neighbor_temperatures_invented': False, 'formal_admitted': False}
