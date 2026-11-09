"""Readback for official builder geometries serialized in imperial/metric units.

Geometry rows must match their pinned translator output exactly. Area/volume
checks use the decimal precision actually written by that translator/engine,
as the existing EIO readback already does. No thermal or numerical error
criterion is changed and no caller-supplied tolerance is accepted.
"""
from collections import Counter
import copy
import csv
import math
from decimal import Decimal, ROUND_HALF_UP
import xml.etree.ElementTree as ET

from .common import ROOT, require
from .idf import Fields, objects, parse
from .source_adapter import source_file


def written_equal(value, printed):
    quantum = Decimal(1).scaleb(Decimal(printed).as_tuple().exponent)
    return value.quantize(quantum, rounding=ROUND_HALF_UP) == Decimal(printed)


def check(fixture, source_idf_ref, xml_ref, eio_ref, *, root=ROOT, envelope_transaction=None):
    rows = parse(source_file(fixture['model'], root).read_text())
    source = parse(source_file(source_idf_ref, root).read_text())
    fields = Fields(source_file(fixture['engine_schema'], root))
    bound_transaction = fixture.get('declared_envelope_geometry_transaction')
    require(not envelope_transaction or not bound_transaction or envelope_transaction == bound_transaction,
            'CONDITION_ENVELOPE_TRANSACTION_CONFLICT')
    envelope_transaction = envelope_transaction or bound_transaction
    declared_window_overrides = set()
    if envelope_transaction:
        from .envelope_adaptation import apply
        parent = parse(source_file(envelope_transaction['source_model'], root).read_text())
        expected, modifications = apply(parent, envelope_transaction['pack'], fixture['engine_schema'], root=root)
        expected_windows = {r[1]: r for r in objects(expected, 'FenestrationSurface:Detailed')}
        for row in objects(rows, 'FenestrationSurface:Detailed'):
            require(row == expected_windows.get(row[1]), 'CONDITION_DECLARED_WINDOW_TRANSACTION_MISMATCH')
        declared_window_overrides = {v['before'][1] for v in modifications['modifications']
                                     if v['before'][0] == 'FenestrationSurface:Detailed'}
    kinds = {'GlobalGeometryRules', 'Zone', 'Space', 'InternalMass', 'BuildingSurface:Detailed',
             'FenestrationSurface:Detailed', 'SurfaceProperty:ExposedFoundationPerimeter'}
    def geometry(model):
        values = []
        for row in model:
            if row[0] not in kinds and not row[0].startswith('Shading:'): continue
            value = copy.deepcopy(row)
            if row[0] == 'BuildingSurface:Detailed' or (row[0] == 'FenestrationSurface:Detailed' and row[1] in declared_window_overrides):
                fields.set(value, 'construction_name', 'BOUND_SEPARATELY')
            values.append(tuple(value))
        return Counter(values)
    require(geometry(rows) == geometry(source), 'CONDITION_SOURCE_GEOMETRY_CHANGED')
    surfaces = {r[1]: r for r in objects(rows, 'BuildingSurface:Detailed')}
    pairs = []
    for row in surfaces.values():
        if fields.get(row, 'outside_boundary_condition') != 'Surface': continue
        other = surfaces.get(fields.get(row, 'outside_boundary_condition_object'))
        require(other is not None and fields.get(other, 'outside_boundary_condition') == 'Surface'
                and fields.get(other, 'outside_boundary_condition_object') == row[1], 'CONDITION_ADJACENCY_NOT_RECIPROCAL')
        pairs.append([row[1], other[1]])
    tree = ET.parse(source_file(xml_ref, root))
    for item in tree.iter(): item.tag = item.tag.split('}')[-1]
    construction = tree.find('.//BuildingSummary/BuildingConstruction')
    require(construction is not None, 'CONDITION_XML_CONSTRUCTION_MISSING')
    area = Decimal(construction.findtext('ConditionedFloorArea')) * Decimal('0.09290304')
    volume = Decimal(construction.findtext('ConditionedBuildingVolume')) * Decimal('0.028316846592')
    native, header = [], None
    with source_file(eio_ref, root).open() as stream:
        for row in csv.reader(stream):
            row = [v.strip() for v in row]
            if row and row[0] == '! <Zone Information>': header = row[1:]
            elif row and row[0] == 'Zone Information':
                require(header is not None, 'CONDITION_EIO_HEADER_MISSING')
                native.append(dict(zip(header, row[1:])))
    zone = fixture['EB_mapping']['hvac']['zone']
    matching = [v for v in native if v['Zone Name'].casefold() == zone.casefold()]
    require(len(matching) == 1, 'CONDITION_NATIVE_ZONE_NOT_UNIQUE'); actual = matching[0]
    # The public builder rounds surface areas and its foundation exporter
    # constructs polygons from perimeter constraints. The input HPXML CFA and
    # EnergyPlus polygon floor area are therefore distinct source quantities.
    # Check the actual source polygons independently;report their discrepancy
    # from requested CFA rather than inventing a tolerance or altering either.
    polygon_area = 0.0
    for row in surfaces.values():
        if fields.get(row,'surface_type')!='Floor' or fields.get(row,'zone_name')!=zone: continue
        start=fields.index(row[0],'number_of_vertices')+1
        values=list(map(float,row[start:]));points=[values[i:i+3] for i in range(0,len(values),3)]
        require(len(points)>=3 and all(len(v)==3 for v in points),'CONDITION_FLOOR_VERTEX_COUNT')
        normal=[0.0,0.0,0.0]
        for a,b in zip(points,points[1:]+points[:1]):
            normal=[normal[0]+a[1]*b[2]-a[2]*b[1],normal[1]+a[2]*b[0]-a[0]*b[2],normal[2]+a[0]*b[1]-a[1]*b[0]]
        polygon_area+=math.sqrt(sum(v*v for v in normal))/2
    require(written_equal(Decimal(str(polygon_area)), actual['Floor Area {m2}']) and written_equal(volume, actual['Volume {m3}']),
            'CONDITION_NATIVE_AREA_VOLUME_CONFLICT')
    require(actual['Zone Multiplier'] == actual['Zone List Multiplier'] == '1', 'CONDITION_NATIVE_MULTIPLIER')
    zone_row = next(r for r in objects(rows, 'Zone') if r[1] == zone)
    printed_volume = fields.get(zone_row, 'volume')
    require(written_equal(volume, printed_volume), 'CONDITION_EXPLICIT_VOLUME_CONFLICT')
    return {'schema': 'national_idf.condition_native_geometry.v1', 'source_idf': source_idf_ref,
        'source_xml': xml_ref, 'fixture_model': fixture['model'], 'native_eio': eio_ref,
        'source_geometry_rows_exactly_preserved': True, 'complete_source_context_retained': True,
        'native_area_volume_and_multipliers_match_source': True,
        'declared_window_construction_transaction': envelope_transaction,
        'conditioned_area_m2': float(area), 'conditioned_air_volume_m3': float(volume),
        'source_conditioned_floor_polygon_area_m2':polygon_area,
        'native_conditioned_floor_area_m2':actual['Floor Area {m2}'],
        'source_CFA_minus_polygon_floor_area_m2':float(area)-polygon_area,
        'exact_survey_floor_area_equivalence_claimed':False,
        'source_CFA_and_polygon_area_are_distinct':True,
        'source_area_algorithm':{'path':'work/p1_hpxml_004ca3ce/HPXMLtoOpenStudio/resources/geometry.rb',
                                'locator':'apply_conditioned_floor_area and foundation/slab exporter'},
        'explicit_native_air_volume_m3': printed_volume, 'exact_XML_converted_volume_m3': str(volume),
        'unit_conversion_serialization_residual_m3': str(Decimal(printed_volume) - volume),
        'comparison_precision_basis': 'Exact source-IDF geometry equality,then XML-unit conversion at translator written precision and nativeEIO written precision;no user tolerance',
        'boundary_counts': dict(Counter(fields.get(r, 'outside_boundary_condition') for r in surfaces.values())),
        'reciprocal_surface_references': pairs, 'all_native_zones': native,
        'area_basis': 'Declared reference conditioned area,not surveyed net or legal area',
        'geometry_representation': 'Official source area/orientation/volume exporter,not measured room layout',
        'numerical_protocol_or_thermal_error_standards_changed': False, 'formal_admitted': False}
