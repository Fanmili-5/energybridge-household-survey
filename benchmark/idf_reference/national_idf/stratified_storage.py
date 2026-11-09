"""Observe source tank storage independently of its reported net-energy sum."""
import bisect
import math
import re

from .common import finite, require

THERMAL_OUTPUTS = {
    'heating_J': 'Water Heater Heating Energy',
    'use_J': 'Water Heater Use Side Heat Transfer Energy',
    'source_J': 'Water Heater Source Side Heat Transfer Energy',
    'loss_J': 'Water Heater Heat Loss Energy',
    'off_parasitic_J': 'Water Heater Off Cycle Parasitic Tank Heat Transfer Energy',
    'on_parasitic_J': 'Water Heater On Cycle Parasitic Tank Heat Transfer Energy',
    'vent_J': 'Water Heater Venting Heat Transfer Energy',
    'net_J': 'Water Heater Net Heat Transfer Energy',
}


class PostResetStorageBalance:
    """A diagnostic interval starting at a common, actually observed checkpoint.

    End-of-warmup reporting variables may precede the native tank reset. Do
    not infer a new initial temperature from a setpoint or subtract storage
    from a grid meter. Retain the original full-period ledger separately.
    """
    def __init__(self, calculator, checkpoint_s):
        require(finite(checkpoint_s) and checkpoint_s > 0, 'POST_RESET_CHECKPOINT_INVALID')
        self.calculator, self.checkpoint_s = calculator, checkpoint_s
        self.last_s = 0.
        self.initial_storage = self.final_storage = None
        self.external_J = 0.
        self.steps = 0

    def observe(self, row, elapsed_s):
        require(finite(elapsed_s) and elapsed_s > self.last_s
            and abs(elapsed_s-self.last_s-row['dt_s']) < 1e-6, 'POST_RESET_OBSERVATION_CLOCK')
        self.last_s = elapsed_s
        if self.initial_storage is None:
            require(elapsed_s <= self.checkpoint_s+1e-6, 'POST_RESET_CHECKPOINT_NOT_OBSERVED')
            if abs(elapsed_s-self.checkpoint_s) < 1e-6:
                temperatures = [row[f'node_{i}_C'] for i in range(1, self.calculator.nodes+1)]
                self.initial_storage = self.final_storage = self.calculator.storage(temperatures)
            return
        temperatures = [row[f'node_{i}_C'] for i in range(1, self.calculator.nodes+1)]
        self.final_storage = self.calculator.storage(temperatures)
        self.external_J += row['external_sum_J']
        self.steps += 1

    def report(self):
        require(self.initial_storage is not None and self.steps > 0, 'POST_RESET_INTERVAL_INCOMPLETE')
        change = self.final_storage-self.initial_storage
        return {'reference_checkpoint_s': self.checkpoint_s, 'end_s': self.last_s,
            'observed_interval_s': self.last_s-self.checkpoint_s, 'steps': self.steps,
            'reference_storage_J': self.initial_storage, 'final_storage_J': self.final_storage,
            'sensible_storage_change_J': change, 'native_signed_external_sum_J': self.external_J,
            'storage_residual_J': change-self.external_J,
            'reference_state_observed_not_assigned': True,
            'diagnostic_prefix_excluded_s': self.checkpoint_s,
            'electricity_meter_prefix_excluded_s': 0,
            'original_numerical_acceptance_modified': False,
            'scope': 'Post-reset observed diagnostic interval only; not a full-period storage or electricity correction',
            'formal_admitted': False}


class SourceWaterProperties:
    """Piecewise-linear tables from the frozen official source, without fit.

    Sensible storage is the integral of its liquid-water cp table at fixed
    source node mass. This is not a measured tank or a compressible-fluid U.
    """
    def __init__(self, fluid_text, constants_text):
        def values(name):
            found = re.search(r'\b' + name + r'\s*=\s*\{([^}]+)\}', fluid_text)
            require(found is not None, 'SOURCE_WATER_TABLE_MISSING', name)
            return [float(x.strip()) for x in found[1].split(',') if x.strip()]
        self.temperatures = values('DefaultGlycolTemps')
        self.cp_values = values('DefaultWaterCpData')
        self.rho_values = values('DefaultWaterRhoData')
        require(len(self.temperatures) == len(self.cp_values) == len(self.rho_values)
                and len(self.temperatures) > 1 and self.temperatures == sorted(set(self.temperatures)),
                'SOURCE_WATER_TABLE_SHAPE')
        found = re.search(r'\bInitConvTemp\s*=\s*([-+\d.]+)\s*;', constants_text)
        require(found is not None, 'SOURCE_WATER_MASS_REFERENCE_MISSING')
        self.mass_reference_C = float(found[1])

    def _segment(self, temperature, values):
        valid = [i for i, value in enumerate(values) if value > 0]
        require(finite(temperature) and self.temperatures[valid[0]] <= temperature <= self.temperatures[valid[-1]],
                'SOURCE_WATER_PROPERTY_OUTSIDE_DOMAIN', temperature)
        i = min(max(bisect.bisect_right(self.temperatures, temperature) - 1, valid[0]), valid[-1] - 1)
        require(values[i] > 0 and values[i + 1] > 0, 'SOURCE_WATER_PROPERTY_UNDEFINED', temperature)
        return i

    def property(self, temperature, values):
        i = self._segment(temperature, values)
        x, y = self.temperatures[i:i + 2]
        return values[i] + (values[i + 1] - values[i]) * (temperature - x) / (y - x)

    def cp(self, temperature):
        return self.property(temperature, self.cp_values)

    def density(self, temperature):
        return self.property(temperature, self.rho_values)

    def sensible_enthalpy(self, temperature):
        self._segment(temperature, self.cp_values)
        require(temperature >= 0, 'SOURCE_WATER_SENSIBLE_REFERENCE_DOMAIN', temperature)
        points = [0.0] + [x for x in self.temperatures if 0 < x < temperature] + [temperature]
        return math.fsum((b - a) * (self.cp(a) + self.cp(b)) / 2 for a, b in zip(points, points[1:]))


class StratifiedStorageObserver:
    """Read final instantaneous node temperatures on accepted system steps.

    All signed external terms are read separately. Their native sum identity
    is distinguished from the independently reconstructed storage change.
    """
    def __init__(self, name, volume_m3, nodes, properties):
        require(isinstance(name, str) and name and finite(volume_m3) and volume_m3 > 0
                and type(nodes) is int and nodes >= 1, 'STRATIFIED_STORAGE_DEFINITION')
        self.name, self.nodes, self.properties = name, nodes, properties
        self.mass_kg = volume_m3 * properties.density(properties.mass_reference_C)
        self.node_mass_kg = self.mass_kg / nodes
        self.handles = {}
        self.initial_temperatures = self.previous_temperatures = None
        self.steps, self.seconds = 0, 0.0
        self.totals = {k: 0.0 for k in THERMAL_OUTPUTS}
        self.max_term_identity_residual_J = 0.0
        self.max_storage_residual_J = 0.0
        self.absolute_storage_residual_J = 0.0
        self.thermal_throughput_J = 0.0

    def request_outputs(self, exchange, state):
        for variable in list(THERMAL_OUTPUTS.values()) + [f'Water Heater Final Temperature Node {i}' for i in range(1, self.nodes + 1)]:
            exchange.request_variable(state, variable, self.name)

    def initialize(self, exchange, state):
        variables = {**THERMAL_OUTPUTS, **{f'node_{i}_C': f'Water Heater Final Temperature Node {i}' for i in range(1, self.nodes + 1)}}
        pending = {k: exchange.get_variable_handle(state, v, self.name) for k, v in variables.items()}
        require(all(h >= 0 for h in pending.values()), 'STRATIFIED_STORAGE_OUTPUT_MISSING',
                [variables[k] for k, v in pending.items() if v < 0])
        self.handles = pending

    def temperatures(self, exchange, state):
        result = [float(exchange.get_variable_value(state, self.handles[f'node_{i}_C'])) for i in range(1, self.nodes + 1)]
        require(all(finite(v) for v in result), 'STRATIFIED_STORAGE_NONFINITE')
        return result

    def storage(self, temperatures):
        require(len(temperatures) == self.nodes, 'STRATIFIED_STORAGE_NODE_COUNT')
        return self.node_mass_kg * math.fsum(self.properties.sensible_enthalpy(t) for t in temperatures)

    def begin(self, exchange, state):
        require(self.handles and self.previous_temperatures is None, 'STRATIFIED_STORAGE_INITIAL_STATE_ORDER')
        self.initial_temperatures = self.temperatures(exchange, state)
        self.storage(self.initial_temperatures)
        self.previous_temperatures = self.initial_temperatures[:]

    def observe_system(self, exchange, state, seconds):
        require(self.previous_temperatures is not None and finite(seconds) and seconds > 0, 'STRATIFIED_STORAGE_CLOCK_OR_INITIAL_STATE')
        temperatures = self.temperatures(exchange, state)
        terms = {k: float(exchange.get_variable_value(state, self.handles[k])) for k in THERMAL_OUTPUTS}
        require(all(finite(v) for v in terms.values()), 'STRATIFIED_STORAGE_NONFINITE')
        external = math.fsum(v for k, v in terms.items() if k != 'net_J')
        change = self.storage(temperatures) - self.storage(self.previous_temperatures)
        residual = change - external
        self.steps += 1
        self.seconds += seconds
        for key, value in terms.items():
            self.totals[key] += value
        self.max_term_identity_residual_J = max(self.max_term_identity_residual_J, abs(external - terms['net_J']))
        self.max_storage_residual_J = max(self.max_storage_residual_J, abs(residual))
        self.absolute_storage_residual_J += abs(residual)
        self.thermal_throughput_J += math.fsum(abs(v) for k, v in terms.items() if k != 'net_J')
        self.previous_temperatures = temperatures
        return {**terms, 'dt_s': seconds, 'storage_change_J': change, 'external_sum_J': external,
                'storage_residual_J': residual, **{f'node_{i + 1}_C': t for i, t in enumerate(temperatures)}}

    def report(self):
        require(self.steps > 0, 'STRATIFIED_STORAGE_NO_OBSERVATIONS')
        change = self.storage(self.previous_temperatures) - self.storage(self.initial_temperatures)
        external = math.fsum(v for k, v in self.totals.items() if k != 'net_J')
        return {'schema': 'national_idf.stratified_storage_balance.v1', 'steps': self.steps, 'seconds': self.seconds,
            'source_node_mass_kg': self.node_mass_kg, 'source_total_mass_kg': self.mass_kg,
            'mass_conversion_reference_C': self.properties.mass_reference_C,
            'initial_node_C': self.initial_temperatures, 'final_node_C': self.previous_temperatures,
            'terms_J': self.totals, 'sensible_storage_change_J': change, 'signed_external_sum_J': external,
            'integrated_storage_residual_J': change - external,
            'max_step_storage_residual_J': self.max_storage_residual_J,
            'sum_absolute_step_storage_residual_J': self.absolute_storage_residual_J,
            'thermal_throughput_J': self.thermal_throughput_J,
            'absolute_step_residual_over_throughput': self.absolute_storage_residual_J / self.thermal_throughput_J if self.thermal_throughput_J else None,
            'max_native_term_identity_residual_J': self.max_term_identity_residual_J,
            'initial_state_observed_not_assigned': True, 'formal_admitted': False,
            'scope': 'Source fixed-mass liquid sensible storage reconstructed from all instantaneous nodes and official cp table; not measured calorimetry or whole-house acceptance'}
