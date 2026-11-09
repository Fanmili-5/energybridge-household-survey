"""Observe native water delivery alongside EB without estimating bath success."""
import math

from .common import require

VARIABLES = {
    'hot_kg_s': 'Water Use Equipment Hot Water Mass Flow Rate',
    'cold_kg_s': 'Water Use Equipment Cold Water Mass Flow Rate',
    'total_kg_s': 'Water Use Equipment Total Mass Flow Rate',
    'hot_C': 'Water Use Equipment Hot Water Temperature',
    'cold_C': 'Water Use Equipment Cold Water Temperature',
    'target_C': 'Water Use Equipment Target Water Temperature',
    'mixed_C': 'Water Use Equipment Mixed Water Temperature',
}


class WaterServiceObserver:
    """Read once per accepted system reporting step, excluding sizing/warmup.

    Mass mixing is checked on the native system clock. Temperature shortfall is
    reported against the native demand target; no comfort threshold, heat
    capacity, bathing routine or physical success flag is supplied here.
    """
    def __init__(self, uses):
        require(isinstance(uses, list) and uses and all(isinstance(x, str) and x for x in uses)
                and len({x.casefold() for x in uses}) == len(uses), 'WATER_SERVICE_USE_MAPPING')
        self.uses = uses
        self.handles = {}
        self.accounts = {use: {'steps': 0, 'total_kg': 0.0, 'hot_kg': 0.0, 'cold_kg': 0.0,
            'mass_weighted_delivery_C_kg': 0.0, 'temperature_shortfall_K_kg': 0.0,
            'max_mass_balance_residual_kg_s': 0.0, 'max_mixing_residual_kg_K_s': 0.0,
            'min_active_delivery_C': None, 'max_active_delivery_C': None} for use in uses}

    def request_outputs(self, exchange, state):
        for use in self.uses:
            for variable in VARIABLES.values():
                exchange.request_variable(state, variable, use)

    def initialize(self, exchange, state):
        pending = {}
        for use in self.uses:
            pending[use] = {}
            for field, variable in VARIABLES.items():
                handle = exchange.get_variable_handle(state, variable, use)
                require(handle >= 0, 'WATER_SERVICE_NATIVE_OUTPUT_MISSING', [use, variable])
                pending[use][field] = handle
        self.handles = pending

    def observe_system(self, exchange, state, seconds):
        require(self.handles and type(seconds) in (int, float) and math.isfinite(seconds) and seconds > 0,
                'WATER_SERVICE_STEP_OR_HANDLES')
        values = {use: {key: float(exchange.get_variable_value(state, handle)) for key, handle in fields.items()}
                  for use, fields in self.handles.items()}
        # Validate the whole step before adding any of its mass or service data.
        for use, row in values.items():
            require(all(math.isfinite(x) for x in row.values()) and all(row[k] >= 0 for k in
                    ('hot_kg_s', 'cold_kg_s', 'total_kg_s')), 'WATER_SERVICE_INVALID_NATIVE_VALUE', use)
        for use, row in values.items():
            a = self.accounts[use]
            a['steps'] += 1
            for field in ('total', 'hot', 'cold'):
                a[field + '_kg'] += row[field + '_kg_s'] * seconds
            a['max_mass_balance_residual_kg_s'] = max(a['max_mass_balance_residual_kg_s'],
                abs(row['total_kg_s'] - row['hot_kg_s'] - row['cold_kg_s']))
            a['max_mixing_residual_kg_K_s'] = max(a['max_mixing_residual_kg_K_s'],
                abs(row['total_kg_s'] * row['mixed_C'] - row['hot_kg_s'] * row['hot_C']
                    - row['cold_kg_s'] * row['cold_C']))
            mass = row['total_kg_s'] * seconds
            a['mass_weighted_delivery_C_kg'] += mass * row['mixed_C']
            a['temperature_shortfall_K_kg'] += mass * max(row['target_C'] - row['mixed_C'], 0)
            if mass > 0:
                for field, operation in [('min_active_delivery_C', min), ('max_active_delivery_C', max)]:
                    a[field] = row['mixed_C'] if a[field] is None else operation(a[field], row['mixed_C'])
        return values

    def report(self):
        result = {}
        for use, a in self.accounts.items():
            result[use] = {**a, 'mass_weighted_delivery_C': (a['mass_weighted_delivery_C_kg'] / a['total_kg']
                                                          if a['total_kg'] > 0 else None)}
        return {'schema': 'national_idf.native_water_service.v1', 'uses': result,
                'clock': 'accepted HVAC system reporting timestep', 'bath_service_success': None,
                'comfort_tolerance_C': None, 'formal_admitted': False,
                'scope': 'Native demand/delivery observations only; no generated routine or inferred readiness'}
