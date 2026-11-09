"""Construct source-bound archetypes by rules, never by filling household gaps.

Rule families are data. A city selects a weather/site package, not a different
Python branch. Reference exposure experiments remain distinct from admission
of a model for a real household or a geographically representative stock.
"""
from __future__ import annotations

import copy
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .common import ROOT, digest, read, require, sha
from .idf import objects, parse

REQUEST_FIELDS = {'template_id', 'parameter_pack_id', 'site_id', 'use', 'housing'}
GEOMETRY_TYPES = {'Building', 'GlobalGeometryRules', 'Zone', 'ZoneList', 'ZoneGroup',
                  'BuildingSurface:Detailed', 'FenestrationSurface:Detailed'}
CATALOG = 'configs/housing_rules/catalog.json'


def artifact(ref, root=ROOT):
    from .source_adapter import source_file
    # A catalog is a logical versioned document. Earlier derivations retain
    # their canonical path and exact content hash after the active version is
    # extended. Only this catalog has a content-addressed archive resolver;
    # physical sources and component files never receive a fallback.
    if isinstance(ref, dict) and ref.get('path') == CATALOG and (root / CATALOG).exists() and ref.get('sha256') != sha(root / CATALOG):
        require(set(ref) == {'path', 'sha256'}, 'ARTIFACT_SHAPE')
        signature = ref.get('sha256')
        require(isinstance(signature, str) and len(signature) == 64
                and all(c in '0123456789abcdef' for c in signature), 'HOUSING_CATALOG_VERSION_INVALID')
        archived = {'path': 'data/housing_catalog_versions/' + signature + '.json', 'sha256': signature}
        require((root / archived['path']).is_file(), 'HOUSING_CATALOG_VERSION_NOT_ARCHIVED')
        return source_file(archived, root)
    return source_file(ref, root)


def parameter_row(row):
    return row[0].casefold().startswith(('material', 'windowmaterial:', 'construction')) or row[0] in (
        'FenestrationSurface:Detailed', 'ZoneInfiltration:DesignFlowRate', 'WindowShadingControl')


def topology(rows, *, numeric_equivalence=False):
    result = []
    for row in rows:
        if row[0] not in GEOMETRY_TYPES:
            continue
        item = copy.deepcopy(row)
        if item[0] in ('BuildingSurface:Detailed', 'FenestrationSurface:Detailed'):
            item[3] = '<construction-reference>'
        if numeric_equivalence:
            for i, value in enumerate(item):
                try:
                    number = Decimal(value)
                    if number.is_finite():
                        item[i] = str(number.normalize())
                except InvalidOperation:
                    pass
        result.append(item)
    return digest(result)


def choose(records, identifier, code):
    values = [r for r in records if r.get('id') == identifier]
    require(len(values) == 1, code, identifier)
    return values[0]


def geometry_family_signature(rows):
    """Ignore only the building's display name across complete source packs."""
    canonical = copy.deepcopy(rows)
    for row in objects(canonical, 'Building'):
        row[1] = '<source-building-display-name>'
    return topology(canonical, numeric_equivalence=True)


def complete_dwelling_source(template, pack, base, source, *, root):
    from .native_enclosures import bind_dwellings, geometry_identity
    family = geometry_family_signature(source)
    require(family == geometry_family_signature(base) == template['geometry_family_sha256']
            == pack['geometry_family_sha256'], 'HOUSING_COMPLETE_SOURCE_GEOMETRY_CONFLICT')
    require(pack['objects_sha256'] == digest(source) and pack['object_count'] == len(source),
            'HOUSING_COMPLETE_SOURCE_CHANGED')
    bundle = read(artifact(pack['native_bundle'], root))
    native_source = artifact(pack['native_source'], root)
    require(bundle['source_sha256'] == sha(native_source), 'HOUSING_COMPLETE_NATIVE_SOURCE_CONFLICT')
    review = read(artifact(template['dwelling_correspondence'], root))
    require(geometry_identity(bundle) == review['geometry_sha256'], 'HOUSING_COMPLETE_DWELLING_GEOMETRY_CONFLICT')
    if review.get('schema') == 'national_idf.source_apartment_correspondence.v1':
        from .apartment_dwellings import bind
        cards = bind(bundle, review, root=root)
    else:
        cards = bind_dwellings(bundle, review)
    card = choose(cards, template['dwelling_id'], 'HOUSING_COMPLETE_DWELLING_UNKNOWN')
    require(card == template['reviewed_dwelling'], 'HOUSING_COMPLETE_DWELLING_CARD_CHANGED')
    return copy.deepcopy(source), {'reviewed_dwelling': card,
        'native_source': pack['native_source'], 'native_bundle': pack['native_bundle'],
        'complete_source_model_kept': True, 'other_dwellings_removed': False}


def build(request, *, catalog_ref=None, root=ROOT):
    require(isinstance(request, dict) and set(request) == REQUEST_FIELDS, 'HOUSING_RULE_REQUEST_FIELDS')
    require(request['use'] in ('reference_climate_experiment', 'household_matching'), 'HOUSING_RULE_USE')
    path = artifact(catalog_ref, root) if catalog_ref else root / CATALOG
    catalog = read(path)
    require(catalog.get('schema') == 'national_idf.housing_rule_catalog.v1', 'HOUSING_RULE_CATALOG_SCHEMA')
    template = read(artifact(choose(catalog['templates'], request['template_id'], 'HOUSING_TEMPLATE_UNKNOWN')['artifact'], root))
    pack = read(artifact(choose(catalog['parameter_packs'], request['parameter_pack_id'], 'HOUSING_PARAMETER_PACK_UNKNOWN')['artifact'], root))
    site = read(artifact(choose(catalog['sites'], request['site_id'], 'HOUSING_SITE_UNKNOWN')['artifact'], root))
    rule = read(artifact(choose(catalog['combinations'], template['combination_rule_id'], 'HOUSING_COMBINATION_RULE_UNKNOWN')['artifact'], root))
    require(template.get('schema') == 'national_idf.housing_template.v1' and
            pack.get('schema') == 'national_idf.housing_parameter_pack.v1' and
            site.get('schema') == 'national_idf.housing_site_pack.v1' and
            rule.get('schema') == 'national_idf.housing_combination.v1', 'HOUSING_RULE_PACKAGE_SCHEMA')
    require(template['id'] == request['template_id'] and pack['id'] == request['parameter_pack_id']
            and site['id'] == request['site_id'], 'HOUSING_RULE_PACKAGE_ID')
    require(pack['family'] == template['family'] == rule['family'] and
            template['id'] in rule['template_ids'] and pack['id'] in rule['parameter_pack_ids'],
            'HOUSING_COMBINATION_NOT_SUPPORTED')
    complete = rule['method'] == 'source_complete_model_with_reviewed_dwelling.v1'
    require(complete or rule['method'] == 'source_complete_parameter_partition.v1', 'HOUSING_RULE_METHOD_UNKNOWN')
    for entry in template['evidence'] + pack['evidence'] + site['evidence'] + rule['evidence']:
        artifact(entry, root)
    base = parse(artifact(template['model'], root).read_text())
    source = parse(artifact(pack['model'], root).read_text())
    extra = {}
    if complete:
        require([pack['id'], site['id']] in rule['parameter_site_pairs'], 'HOUSING_SOURCE_SITE_COMBINATION_UNSUPPORTED')
        rows, extra = complete_dwelling_source(template, pack, base, source, root=root)
        expected, invariant_count = source, 0
    else:
        require(topology(base) == template['topology_sha256'] and topology(source) == pack['topology_sha256']
                and topology(base, numeric_equivalence=True) == topology(source, numeric_equivalence=True),
                'HOUSING_PARAMETER_PACK_TOPOLOGY_CONFLICT')
        invariant = lambda rows: [r for r in rows if not parameter_row(r)]
        require(invariant(base) == invariant(source), 'HOUSING_PARAMETER_PACK_INVARIANT_CONFLICT')
        expected = [r for r in source if parameter_row(r)]
        require(pack['objects_sha256'] == digest(expected) and pack['object_count'] == len(expected),
                'HOUSING_PARAMETER_PARTITION_CHANGED')
        # A complete source partition travels together; no per-field mixing.
        template_objects = iter(copy.deepcopy(invariant(base)))
        rows = [copy.deepcopy(row) if parameter_row(row) else next(template_objects) for row in source]
        invariant_count = len(invariant(rows))
    require(rows == source, 'HOUSING_SOURCE_RECONSTRUCTION_NOT_EXACT')
    housing = request['housing']
    require(isinstance(housing, dict) and set(housing) == set(template['housing_conditions']),
            'HOUSING_REQUEST_MISSING_OR_EXTRA_FIELDS')
    for name, value in housing.items():
        require(value is not None and value == template['housing_conditions'][name],
                'HOUSING_CONDITION_CONFLICT_OR_UNKNOWN', name)
    require(site['weather_QC_passed'] is True, 'HOUSING_WEATHER_QC_MISSING')
    weather = artifact(site['weather'], root)
    from .weather import audit
    weather_audit = audit(weather, site['weather_identity'])
    require(weather_audit['admitted'], 'HOUSING_WEATHER_QC_FAILED', weather_audit.get('errors'))
    require(weather_audit['identity'] == site['audited_identity'], 'HOUSING_WEATHER_IDENTITY_CHANGED')
    # Geographic stock applicability is separate from an explicit experiment
    # exposing this unchanged archetype to a particular station's weather.
    gaps = template['household_release_gaps'] + pack['household_release_gaps'] + site['household_release_gaps']
    if request['use'] == 'household_matching':
        require(not gaps and site['climate_zone'] in rule['household_climate_zones'],
                'HOUSING_HOUSEHOLD_DOMAIN_UNSUPPORTED', gaps)
    require(site['climate_zone'] in rule['reference_weather_climate_zones'], 'HOUSING_WEATHER_OUTSIDE_RULE_DOMAIN')
    return rows, {
        'schema': 'national_idf.housing_rule_derivation.v1',
        'request': request, 'catalog': catalog_ref or {'path': str(path.relative_to(root)), 'sha256': sha(path)},
        'template': template['id'], 'parameter_pack': pack['id'], 'site': site['id'],
        'template_source': template['model'], 'parameter_source': pack['model'],
        'topology_sha256': topology(rows), 'source_reconstruction_exact': True,
        'parameter_objects': [{'kind': r[0], 'name': r[1], 'row_sha256': digest(r)} for r in expected],
        'invariant_object_count': invariant_count,
        'site_weather': site['weather'], 'site_identity': site['audited_identity'],
        'weather_audit': weather_audit,
        'ground_boundary': pack['ground_boundary'] if complete else template['ground_boundary'],
        'household_release_gaps': list(dict.fromkeys(gaps)),
        'Chinese_stock_or_household_applicability_established': not gaps,
        'formal_admitted': False, 'physical_values_invented': False,
        'geometry_scaling_performed': False, 'family_or_AB_generated': False,
        'implementation': {'path': 'national_idf/housing_rules.py', 'sha256': sha(Path(__file__))}, **extra}


def validate_derivation(manifest, rows, *, root=ROOT):
    ref = manifest['rule_construction']
    receipt = read(artifact(ref, root))
    implementation = receipt['implementation']
    require(implementation['path'] == 'national_idf/housing_rules.py', 'HOUSING_RULE_IMPLEMENTATION_PATH')
    live = root / implementation['path']
    if sha(live) != implementation['sha256']:
        archived = {'path': 'data/compiler_versions/' + implementation['sha256'] + '.py',
                    'sha256': implementation['sha256']}
        artifact(archived, root)
    rebuilt, expected = build(receipt['request'], catalog_ref=receipt['catalog'], root=root)
    # A pinned earlier compiler is retained byte-for-byte. Current code must
    # reconstruct the same entire model and derivation; only its own identity
    # may differ. No physical evidence hash receives this historical fallback.
    expected['implementation'] = implementation
    require(rebuilt == rows and expected == receipt, 'HOUSING_RULE_DERIVATION_CHANGED')
    require(manifest['package_id'] == 'rule:' + digest({
        'catalog': receipt['catalog'], 'request': receipt['request']}),
        'HOUSING_RULE_PACKAGE_ID_CHANGED')
    return receipt


def screen(request, *, root=ROOT):
    _, result = build(request, root=root)
    return {k: value for k, value in result.items() if k != 'parameter_objects'}


def match(query, *, root=ROOT):
    """List rule candidates from declared housing fields, never infer a pack."""
    require(isinstance(query, dict) and set(query) == {'site_id', 'use', 'housing'},
            'HOUSING_RULE_QUERY_FIELDS')
    require(query['use'] in ('reference_climate_experiment', 'household_matching') and
            isinstance(query['housing'], dict), 'HOUSING_RULE_QUERY_USE')
    catalog = read(root / CATALOG)
    site_entry = choose(catalog['sites'], query['site_id'], 'HOUSING_SITE_UNKNOWN')
    site = read(artifact(site_entry['artifact'], root))
    candidates, conflicts = [], []
    templates = [read(artifact(item['artifact'], root)) for item in catalog['templates']]
    known = set().union(*(set(t['housing_conditions']) for t in templates))
    require(set(query['housing']) <= known, 'HOUSING_QUERY_UNSUPPORTED_FIELDS')
    for item, template in zip(catalog['templates'], templates):
        conditions = template['housing_conditions']
        mismatches = [key for key, value in query['housing'].items()
                      if value is not None and (key not in conditions or value != conditions[key])]
        if mismatches:
            conflicts.append({'template_id': item['id'], 'fields': mismatches})
            continue
        missing = [key for key in conditions if query['housing'].get(key) is None]
        rule = read(artifact(choose(catalog['combinations'], template['combination_rule_id'],
                                   'HOUSING_COMBINATION_RULE_UNKNOWN')['artifact'], root))
        for pack_id in rule['parameter_pack_ids']:
            if rule.get('parameter_site_pairs') is not None and [pack_id, query['site_id']] not in rule['parameter_site_pairs']:
                conflicts.append({'template_id': item['id'], 'parameter_pack_id': pack_id,
                    'fields': ['site_id'], 'code': 'HOUSING_SOURCE_SITE_COMBINATION_UNSUPPORTED'})
                continue
            request = {'template_id': item['id'], 'parameter_pack_id': pack_id,
                       'site_id': query['site_id'], 'use': 'reference_climate_experiment',
                       'housing': conditions}
            _, proof = build(request, root=root)
            candidates.append({'template_id': item['id'], 'parameter_pack_id': pack_id,
                'site_id': query['site_id'], 'missing_housing_fields': missing,
                'household_release_gaps': proof['household_release_gaps'],
                'conditional_reference_eligible': not missing,
                'household_eligible': not missing and not proof['household_release_gaps']
                    and site['climate_zone'] in rule['household_climate_zones']})
    eligibility = 'household_eligible' if query['use'] == 'household_matching' else 'conditional_reference_eligible'
    ready = [r for r in candidates if r[eligibility]]
    return {'schema': 'national_idf.housing_rule_candidates.v1', 'query': query,
            'candidates': candidates, 'conflicts': conflicts,
            'selection_status': 'ambiguous' if len(ready) > 1 else 'one_candidate' if ready else 'unresolved',
            'selected_parameter_pack': ready[0]['parameter_pack_id'] if len(ready) == 1 else None,
            'formal_admitted': False, 'execution_ready': False, 'no_defaults_or_nearest_city_used': True}


def household_lineage(housing, city, *, root=ROOT):
    """Formal rule lineage must pass household domain, not experimental scope."""
    derivation = read(artifact(housing['rule_construction'], root))
    request = derivation['request']
    require(request['use'] == 'household_matching', 'CONDITIONAL_REFERENCE_IS_NOT_HOUSEHOLD_LINEAGE')
    rows, rebuilt = build(request, catalog_ref=derivation['catalog'], root=root)
    manifest = {'rule_construction': housing['rule_construction'], 'package_id': housing['package_id']}
    validate_derivation(manifest, rows, root=root)
    require(rows == parse(artifact(housing['model'], root).read_text()), 'HOUSEHOLD_RULE_MODEL_CHANGED')
    catalog = read(artifact(derivation['catalog'], root))
    entry = choose(catalog['sites'], request['site_id'], 'HOUSING_SITE_UNKNOWN')
    site = read(artifact(entry['artifact'], root))
    require(city == site['weather_identity']['city'], 'HOUSEHOLD_RULE_SITE_CITY_CONFLICT')
    require(not rebuilt['household_release_gaps'], 'HOUSEHOLD_RULE_EVIDENCE_MISSING')
    return True
