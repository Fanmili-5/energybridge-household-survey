"""Load-dependent batch energy; declared curves are not population calibration."""
import math
from .common import digest, read
from pathlib import Path

MODEL = read(Path(__file__).with_name('LAUNDRY_MODEL.json'))


def task_power(task, parameters):
    p = parameters.get(task['kind'], parameters)
    watts = task.get('power_kw', p['power_kw'])
    if type(watts) not in (int, float) or not math.isfinite(watts) or watts <= 0:
        raise ValueError('INVALID_BATCH_POWER')
    if watts * 1000 > p.get('nameplate_W', parameters.get('nameplate_W', float('inf'))) + 1e-8:
        raise ValueError('BATCH_POWER_EXCEEDS_NAMEPLATE')
    if 'cycle_energy_kWh' in task and abs(task['cycle_energy_kWh'] - watts * (task['end_min'] - task['start_min']) / 60) > 1e-8:
        raise ValueError('BATCH_ENERGY_POWER_DURATION_MISMATCH')
    return watts


def batch_energy(need, policy, hardware, model=None):
    model = MODEL if model is None else model
    mode = policy.get('energy_model', 'load_curve')
    if mode == 'legacy_constant_power' or need['kind'] not in model['curves']:
        return {}
    if mode != 'load_curve':
        raise ValueError('UNKNOWN_BATCH_ENERGY_MODEL')
    mass, capacity = need['quantity'], need['batch_capacity_kg']
    if not 0 < mass <= capacity or not math.isfinite(mass + capacity):
        raise ValueError('INVALID_BATCH_MASS_OR_CAPACITY')
    points = model['curves'][need['kind']]['points']
    if (len(points) < 2 or points[0][0] != 0 or points[-1][0] != 1
            or any(len(p) != 2 or not all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in p) for p in points)
            or any(a[0] >= b[0] for a, b in zip(points, points[1:]))):
        raise ValueError('INVALID_LOAD_ENERGY_CURVE')
    fraction = mass / capacity
    a, b = next((a, b) for a, b in zip(points, points[1:]) if a[0] <= fraction <= b[0])
    factor = a[1] + (b[1] - a[1]) * (fraction - a[0]) / (b[0] - a[0])
    reference_min = model['curves'][need['kind']]['reference_duration_min']
    energy = hardware['power_kw'] * reference_min / 60 * factor
    power = energy * 60 / policy['duration_min']
    if power * 1000 > hardware.get('nameplate_W', hardware['power_kw'] * 1000) + 1e-8:
        raise ValueError('BATCH_ENERGY_EXCEEDS_NAMEPLATE_DURATION')
    return {'power_kw': power, 'cycle_energy_kWh': energy, 'load_fraction': fraction,
            'energy_model': {'schema': model['schema'], 'model_sha256': digest(model),
                'mass_kg': mass, 'capacity_kg': capacity, 'reference_duration_min': reference_min,
                'scope': 'piecewise_linear_batch_energy;flat_cycle_mean_power;not_motor_inrush_or_wash_quality'}}
