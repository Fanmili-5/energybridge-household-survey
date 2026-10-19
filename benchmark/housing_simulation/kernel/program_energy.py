"""Literal per-batch electrical power contract, with legacy constant fallback."""
import math


def program_watts(task, parameters):
    p = parameters.get(task['kind'], parameters)
    kw = task.get('power_kw', p['power_kw'])
    if type(kw) not in (int, float) or not math.isfinite(kw) or kw <= 0:
        raise ValueError('INVALID_BATCH_POWER')
    if kw * 1000 > p.get('nameplate_W', parameters.get('nameplate_W', float('inf'))) + 1e-8:
        raise ValueError('BATCH_POWER_EXCEEDS_NAMEPLATE')
    if 'cycle_energy_kWh' in task and abs(task['cycle_energy_kWh'] - kw * (task['end_min'] - task['start_min']) / 60) > 1e-8:
        raise ValueError('BATCH_ENERGY_POWER_DURATION_MISMATCH')
    return kw * 1000
