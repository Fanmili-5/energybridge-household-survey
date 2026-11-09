"""Read pinned native IDFs and explicit dependencies; never infer a dwelling."""
from __future__ import annotations

from pathlib import Path

from .common import ROOT, digest, locked, read, require
from .idf import objects, parse

ADAPTER = 'native_idf_objects.v1'
HOUSING_TYPES = {
    'building', 'globalgeometryrules', 'zone', 'zonelist', 'zonegroup', 'space', 'spacelist',
    'buildingsurface:detailed', 'fenestrationsurface:detailed', 'internalmass',
    'shading:building:detailed', 'shading:site:detailed', 'shading:zone:detailed',
    'shading:overhang', 'shading:fin', 'surfaceproperty:exposedfoundationperimeter',
}
SYSTEM_PREFIXES = ('zonehvac:', 'airloophvac:', 'hvactemplate:', 'coil:', 'fan:',
                   'waterheater:', 'wateruse:', 'boiler:', 'district', 'plantloop')
LOAD_TYPES = {'electricequipment', 'gasequipment', 'otherequipment', 'hotwaterequipment',
              'steamequipment', 'lights', 'people', 'zonecontrol:thermostat'}


def source_file(ref, root=ROOT):
    require(isinstance(ref, dict) and set(ref) == {'path', 'sha256'}, 'ARTIFACT_SHAPE')
    path = (root / ref['path']).resolve()
    require(path.is_relative_to(root.resolve()), 'ARTIFACT_OUTSIDE_PROJECT', ref['path'])
    return locked(ref, root)


def normalized_version(value):
    parts = str(value).split('.')
    while len(parts) > 2 and parts[-1] == '0':
        parts.pop()
    return parts


def equipment_zone(rows, target, fields):
    """Resolve an explicit Zone or Space target; never infer a household."""
    zones = [r for r in objects(rows, 'Zone') if r[1].casefold() == target.casefold()]
    spaces = [r for r in objects(rows, 'Space') if r[1].casefold() == target.casefold()]
    require(len(zones)+len(spaces) == 1, 'EQUIPMENT_TARGET_MISSING_AMBIGUOUS_OR_MULTIZONE', target)
    if zones:
        return zones[0][1]
    zone = fields.get(spaces[0], 'zone_name')
    parent = [r for r in objects(rows, 'Zone') if r[1].casefold() == zone.casefold()]
    require(len(parent) == 1, 'EQUIPMENT_SPACE_ZONE_MISSING', target)
    return parent[0][1]


def protected(row):
    kind = row[0].casefold()
    return (kind in HOUSING_TYPES or kind.startswith(('material', 'windowmaterial:', 'construction',
            'surfaceproperty:', 'foundation:', 'windowproperty:', 'shading:',
            'wall:', 'roof', 'ceiling:', 'floor:', 'window', 'door', 'glazeddoor')))


def housing_fingerprint(rows):
    return digest([r for r in rows if protected(r)])


def selector(rows, index):
    row = rows[index]
    return {'index': index, 'kind': row[0], 'name': row[1] if len(row) > 1 else '',
            'row_sha256': digest(row)}


def selected(rows, spec):
    require(isinstance(spec, dict) and set(spec) == {'index', 'kind', 'name', 'row_sha256'},
            'OBJECT_SELECTOR_SHAPE')
    i = spec['index']
    require(type(i) is int and 0 <= i < len(rows), 'OBJECT_INDEX_OUTSIDE_SOURCE', i)
    require(selector(rows, i) == spec, 'SOURCE_OBJECT_PRECONDITION', spec)
    return rows[i]


def load_adapter(ref, root=ROOT):
    manifest = read(source_file(ref, root))
    require(manifest.get('schema') == 'national_idf.source_adapter.v1'
            and manifest.get('adapter') == ADAPTER, 'SOURCE_ADAPTER_UNSUPPORTED')
    require(bool(manifest.get('package_id')), 'SOURCE_PACKAGE_MISSING')
    model = source_file(manifest['model'], root)
    rows = parse(model.read_text())
    if manifest.get('rule_construction'):
        from .housing_rules import validate_derivation
        validate_derivation(manifest, rows, root=root)
    versions = objects(rows, 'Version')
    require(len(versions) == 1 and normalized_version(versions[0][1]) ==
            normalized_version(manifest['engine_version']), 'SOURCE_ENGINE_VERSION_MISMATCH')
    require(housing_fingerprint(rows) == manifest['housing_sha256'], 'SOURCE_HOUSING_CHANGED')
    # Dependencies are explicit and hash locked. Relative paths in a source ZIP
    # do not become permission to read arbitrary local files.
    dependencies = manifest.get('schedule_files', [])
    seen = set()
    for item in dependencies:
        row = selected(rows, item['object'])
        require(row[0].casefold() == 'schedule:file' and row[3] == item['original_filename'],
                'SCHEDULE_DEPENDENCY_MISMATCH')
        require(item['object']['index'] not in seen, 'DUPLICATE_SCHEDULE_DEPENDENCY')
        seen.add(item['object']['index'])
        source_file(item['file'], root)
    require(seen == {i for i, r in enumerate(rows) if r[0].casefold() == 'schedule:file'},
            'SCHEDULE_DEPENDENCY_MISSING')
    # Other file-reading objects require a dedicated adapter, not an ignored dependency.
    require(not any(':file' in r[0].casefold() and r[0].casefold() not in ('schedule:file', 'outputcontrol:files')
                    or r[0].casefold().startswith(('externalinterface', 'pythonplugin:')) for r in rows),
            'UNSUPPORTED_EXTERNAL_DEPENDENCY')
    zones = {r[1].casefold() for r in objects(rows, 'Zone')}
    require(all(z.casefold() in zones for z in manifest.get('thermal_zones', [])), 'MAPPED_ZONE_MISSING')
    for group in manifest.get('legacy_groups', {}).values():
        require(isinstance(group, list) and bool(group), 'EMPTY_LEGACY_GROUP')
        for item in group:
            selected(rows, item)
    return manifest, rows


def inspect_source(ref, root=ROOT):
    manifest, rows = load_adapter(ref, root)
    result = {'adapter': ADAPTER, 'source_id': manifest['id'], 'package_id': manifest['package_id'],
            'engine_version': manifest['engine_version'], 'model': manifest['model'],
            'housing_sha256': housing_fingerprint(rows), 'objects': len(rows),
            'zones': [r[1] for r in objects(rows, 'Zone')],
            'schedule_file_dependencies': len(manifest.get('schedule_files', [])),
            'source_loads_and_systems': [selector(rows, i) for i, r in enumerate(rows)
                                       if r[0].casefold() in LOAD_TYPES or r[0].casefold().startswith(SYSTEM_PREFIXES)],
            'support_conditions': manifest.get('support_conditions'),
            'source_scope_gaps': manifest.get('source_scope_gaps', []),
            'formal_admitted': False, 'household_boundary_inferred': False}
    if manifest.get('rule_construction'):
        result['rule_construction'] = manifest['rule_construction']
    return result
