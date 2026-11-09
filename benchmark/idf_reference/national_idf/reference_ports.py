"""Rebind existing life channels after a proven enclosure/site transaction.

This preserves the already installed People, water consumers and schedules.
It grants no climate, equipment, physical or numerical acceptance.
"""
import copy

from .common import ROOT, read, require
from .program_resources import model_signature
from .source_adapter import source_file


def rebind(spec, before, after, derivation_ref, *, root=ROOT):
    receipt = read(source_file(spec['life_installation_receipt'], root))
    require(not spec.get('registered_numerical_overlay'), 'REFERENCE_PORT_OVERLAY_NOT_REPLAYED')
    require(receipt['ready'] and not receipt['formal_admitted']
            and receipt['installed_model_signature'] == model_signature(before),
            'REFERENCE_PORT_PARENT_NOT_BOUND')
    source_file(derivation_ref, root); source_file(receipt['pack'], root)
    mapping = receipt['mapping']; water = mapping['mixed_water']
    names = {p['object'] for p in mapping['people'].values()}
    names.update([water['delivered_object'], *water['distribution_waste_objects']])
    schedules = {water['flow_schedule'], water['target_schedule']}
    schedules.update(p[k] for p in mapping['people'].values() for k in ('count_schedule', 'activity_schedule'))
    def protected(row):
        return row[0] == 'People' or (len(row) > 1 and row[1] in names | schedules) or (
            row[0] == 'OtherEquipment' and 'general water' in row[1].casefold())
    require([r for r in before if protected(r)] == [r for r in after if protected(r)],
            'REFERENCE_PORT_PHYSICS_OR_SCHEDULE_CHANGED')
    result = copy.deepcopy(receipt)
    result.update(installed_model_signature=model_signature(after),
                  reference_transaction_parent=spec['life_installation_receipt'],
                  reference_transaction=derivation_ref,
                  life_ports_and_independent_water_background_unchanged=True)
    return result
