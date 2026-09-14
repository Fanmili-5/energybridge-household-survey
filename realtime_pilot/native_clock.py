"""Synchronize live appliance integration/writes with EnergyPlus zone steps.

The native agent still plans in continuous hours and runs its own callbacks.
Only live appliance execution is sampled at the physical zone boundary; HVAC
substeps must not advance a zone-step appliance model repeatedly or discard
the first part of a task before ElectricEquipment recalculates its load.
"""
from contextlib import contextmanager
from copy import deepcopy
from unittest.mock import patch

VERSION = 'eb.appliance_zone_clock.v1'
TIME_TOLERANCE_H = 1e-9


@contextmanager
def synchronized_appliances(runner, suite_class, loops):
    original_step = suite_class.step
    original_writer = runner._write_appliance_actuators
    audit = {'version': VERSION, 'planning_changed': False,
             'execution_policy': 'first_zone_boundary_at_or_after_scheduled_time',
             'substep_policy': 'hold_last_device_power_and_actuator_values',
             'comparison_tolerance_h': TIME_TOLERANCE_H,
             'zone_step_hours': [], 'model_steps': 0, 'held_substeps': 0,
             'power_transitions': [], 'ev_state_trace': [], 'task_state_trace': []}

    def step(suite, sim_h, dt_h):
        if not any(getattr(loop, 'appliance_suite', None) is suite for loop in loops):
            return original_step(suite, sim_h, dt_h)
        tick = round(sim_h / dt_h)
        if abs(sim_h - tick * dt_h) > 1e-7 or getattr(suite, '_eb_zone_tick', None) == tick:
            audit['held_substeps'] += 1
            return deepcopy(getattr(suite, '_eb_zone_power', {}))
        suite._eb_zone_tick = tick
        if dt_h not in audit['zone_step_hours']:
            audit['zone_step_hours'].append(dt_h)
        # Avoid losing an entire step to e.g. 18:10 represented just below
        # 18.166666666666668. This is 3.6 microseconds, not a schedule edit.
        ev=getattr(suite,'_ev',None)
        observe_ev=ev is not None and ev.present
        if observe_ev:
            before_soc=ev._soc
            departed_before=set(ev._departed)
        powers = original_step(suite, tick * dt_h + TIME_TOLERANCE_H, dt_h)
        tasks={name:{'completed':app._days[0].completed} for name,app in getattr(suite,'_shiftable',{}).items() if app.present}
        if tasks:audit['task_state_trace'].append({'start_h':tick*dt_h,'end_h':(tick+1)*dt_h,'first_day_tasks':tasks})
        if observe_ev:
            audit['ev_state_trace'].append({
                'start_h':tick*dt_h,'end_h':(tick+1)*dt_h,
                'soc_before':before_soc,'soc_after':ev._soc,
                'departure_occurred':bool(set(ev._departed)-departed_before),
                'target_soc':ev.target_soc,'arrival_h':ev.arrival_h,'departure_h':ev.departure_h})
        if powers != getattr(suite, '_eb_zone_power', {}):
            audit['power_transitions'].append({'sim_h': tick * dt_h, 'power_kw': deepcopy(powers)})
        suite._eb_zone_power = deepcopy(powers)
        audit['model_steps'] += 1
        return powers

    def writer(ex, state, loop, powers, sim_h):
        dt_h = ex.zone_time_step(state)
        tick = round(sim_h / dt_h)
        if abs(sim_h - tick * dt_h) > 1e-7 or getattr(loop, '_eb_zone_write_tick', None) == tick:
            for handle, value in getattr(loop, '_eb_zone_actuators', {}).items():
                ex.set_actuator_value(state, handle, value)
            return
        loop._eb_zone_write_tick = tick
        values = {}

        class Exchange:
            def __getattr__(self, key):
                return getattr(ex, key)

            def set_actuator_value(self, state, handle, value):
                values[handle] = value
                return ex.set_actuator_value(state, handle, value)

        original_writer(Exchange(), state, loop, powers, tick * dt_h + TIME_TOLERANCE_H)
        loop._eb_zone_actuators = values

    with patch.object(suite_class, 'step', new=step), \
         patch.object(runner, '_write_appliance_actuators', new=writer):
        yield audit
