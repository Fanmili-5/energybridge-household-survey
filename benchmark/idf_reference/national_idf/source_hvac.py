"""Isolate an existing HVAC availability control without changing source physics."""
import copy

from .common import require
from .idf import objects
from .source_adapter import housing_fingerprint


def isolate_hvac_availability(rows, fields, *, manager, unitary, schedule_name):
    """Clone the source constant, then rewire only the two named HVAC controls.

    A shared Always On schedule must never be actuated: other loads and source
    EMS can depend on it. Curves, sizing, coil/fan and all EMS objects stay intact.
    This exact overlay is an integration artifact, not a physical release.
    """
    result = copy.deepcopy(rows)

    def one(kind, name):
        found = [r for r in objects(result, kind) if r[1].casefold() == name.casefold()]
        require(len(found) == 1, 'HVAC_CONTROL_OBJECT_MISSING_OR_AMBIGUOUS', [kind, name])
        return found[0]

    require(schedule_name and not any(r[0].casefold().startswith('schedule:')
            and r[1].casefold() == schedule_name.casefold() for r in result),
            'HVAC_CONTROL_SCHEDULE_COLLISION', schedule_name)
    managed = one('AvailabilityManager:Scheduled', manager)
    system = one('AirLoopHVAC:UnitarySystem', unitary)
    original_name = fields.get(managed, 'schedule_name')
    require(fields.get(system, 'availability_schedule_name').casefold() == original_name.casefold(),
            'HVAC_SOURCE_AVAILABILITY_MISMATCH')
    original = one('Schedule:Constant', original_name)
    require(float(fields.get(original, 'hourly_value')) == 1, 'HVAC_SOURCE_NOT_ALWAYS_AVAILABLE')
    require(not any(r[2].casefold() in {manager.casefold(), unitary.casefold(), original_name.casefold()}
                    for r in objects(result, 'EnergyManagementSystem:Actuator')),
            'HVAC_CONTROL_CONFLICTS_WITH_SOURCE_EMS')
    revised = copy.deepcopy(original)
    revised[1] = schedule_name
    changes = []
    for row, field in [(managed, 'schedule_name'), (system, 'availability_schedule_name')]:
        before = copy.deepcopy(row)
        fields.set(row, field, schedule_name)
        changes.append({'action': 'replace', 'before': before, 'after': copy.deepcopy(row),
                        'reason': 'Dedicated EB HVAC switch; preserve shared source schedule'})
    result.append(revised)
    changes.append({'action': 'add', 'before': None, 'after': revised,
                    'reason': 'Exact clone of source constant; no new physical parameter'})
    require(housing_fingerprint(result) == housing_fingerprint(rows), 'HVAC_OVERLAY_CHANGED_HOUSING')
    require([r for r in result if r[0].startswith('EnergyManagementSystem:')]
            == [r for r in rows if r[0].startswith('EnergyManagementSystem:')],
            'HVAC_OVERLAY_CHANGED_SOURCE_EMS')
    return result, changes
