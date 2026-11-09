"""Bind fresh native validation to the current versioned reference rule domain.

The original publisher and its native admission signatures stay unchanged.
Its original receipt is kept separately; this layer only checks active package
membership and reports scope. It cannot change any numerical output status.
"""
from pathlib import Path
import copy

from .common import ROOT, read, require, save, sha
from .reference_workflow import ref
from .source_adapter import source_file
from .native_build_runtime import catalog_path

DOMAIN = 'configs/condition_reference_domain_v3.json'


def publish(execution_path, out, requested=None):
    from .condition_outputs import publish as native_publish
    out = Path(out)
    execution = read(execution_path); preparation = execution['source_preparation']
    domain = read(ROOT / DOMAIN); catalog = read(ROOT / catalog_path())
    require(domain['housing_catalogs'][catalog_path()] == ref(ROOT / catalog_path()), 'REFERENCE_ACTIVE_DOMAIN_CATALOG_CHANGED')
    require(domain['sites'] == catalog['sites'] and domain['housing_condition_families'] == catalog['families'],
            'REFERENCE_ACTIVE_DOMAIN_MEMBERSHIP_CHANGED')
    for item in domain['housing_catalogs'].values(): source_file(item, ROOT)
    source_file(domain['envelope_recipes'], ROOT)
    fixture = read(source_file(execution['fixture'], ROOT))
    weather = fixture['weather']
    sites = [s for s in catalog['sites'] if read(source_file(s['site_pack'], ROOT))['weather'] == weather]
    require(len(sites) == 1, 'REFERENCE_ACTIVE_DOMAIN_SITE_UNBOUND')
    house = preparation['reference_housing']; family = catalog['families'].get(house['kind'], {})
    require(house['vertical_context'] in family.get('vertical_contexts', {}), 'REFERENCE_ACTIVE_DOMAIN_HOUSING_UNBOUND')
    from .regional_profile import audit
    regional = audit(fixture, sites[0]['country'], sites[0]['id'])
    receipt = native_publish(execution_path, out / 'source_checks', requested)
    # The active catalogs can add unrelated locations/classes. Freeze their
    # exact content beside this result so an addition does not invalidate an
    # unchanged physical model or make its old domain references go stale.
    frozen = copy.deepcopy(domain)
    for name, binding in frozen['housing_catalogs'].items():
        path = out / 'domain_sources' / Path(name).name
        save(path, read(source_file(binding, ROOT))); frozen['housing_catalogs'][name] = ref(path)
    for key in ('envelope_recipes', 'regional_enclosure_packages', 'enclosure_classes'):
        if key in frozen:
            path = out / 'domain_sources' / Path(frozen[key]['path']).name
            save(path, read(source_file(frozen[key], ROOT))); frozen[key] = ref(path)
    save(out / 'DOMAIN.json', frozen)
    original_status = receipt['outputs']
    receipt = {**receipt, 'source_validation_receipt': ref(out / 'source_checks/RESULT.json'),
               'frozen_domain': ref(out / 'DOMAIN.json'), 'active_site': sites[0],
               'active_domain_is_rule_membership_not_blanket_model_admission': True,
               'regional_reference_enclosure': regional,
               'implementation': {**receipt['implementation'], __name__.replace('.', '/') + '.py': sha(ROOT / 'national_idf/reference_domain_outputs.py')}}
    require(receipt['outputs'] == original_status, 'REFERENCE_DOMAIN_OUTPUT_STATUS_CHANGED')
    save(out / 'RESULT.json', receipt)
    return receipt
