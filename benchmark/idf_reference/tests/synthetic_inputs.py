"""Public software-only inputs; no household records or physical calibration."""

def case():
    return {'schema': 'national_idf.case.v2', 'case_id': 'synthetic-request-only',
        'environment': {'physics_configuration_id': 'synthetic-unregistered'},
        'run': {'start_date': '2007-01-01', 'end_date': '2007-01-02'},
        'life': {'basis': 'synthetic software test, not family data', 'maximum_persons': 2,
            'occupancy': [{'room_id': 'conditioned space', 'start_min': 0, 'end_min': 1440, 'persons': 2, 'activity_W': 108}],
            'lighting_W_m2': 1, 'misc_W_m2': 0, 'people_values_basis': 'synthetic test only',
            'mixed_water_daily': [{'start_min': 420, 'duration_min': 10, 'liters': 40, 'target_C': 40}],
            'services_daily': {key: {'cycles': 1, 'release_min': 0, 'deadline_min': 1440} for key in ['washer', 'dryer', 'dishwasher']},
            'ev_initial_SOC': .3, 'ev_connection_daily': [{'start_min': 0, 'end_min': 480}, {'start_min': 1080, 'end_min': 1440}],
            'ev_daily': {'departure_min': 480, 'return_min': 1080, 'traction_kWh': 12, 'required_departure_SOC': .8}},
        'controls': {'basis': 'synthetic software test only', 'heating_C': 20, 'cooling_C': 26, 'hvac_available': True,
            'tank_target_C': 55, 'ev_target_SOC': .8, 'daily_overrides': [],
            'program_starts_daily': {'washer': [600], 'dryer': [700], 'dishwasher': [800]},
            'ev_daily_windows': [{'start_min': 0, 'end_min': 1440}]}}


def domain():
    return {'schema': 'national_idf.runtime_support_domain.v1', 'physics_configuration_id': 'synthetic-unregistered',
        'thermal_zones': ['conditioned space'], 'solver_step_min': 5, 'command_grid_min': 10,
        'run_period': {'start_date': '2007-01-01', 'end_date': '2007-01-04'},
        'maximum_persons': 3, 'max_water_flow_L_min': 10, 'fixed_life_values': {'lighting_W_m2': 1, 'misc_W_m2': 0},
        'bounds': {'heating_C': [15, 25], 'cooling_C': [20, 32], 'tank_target_C': [40, 75],
                   'ev_target_SOC': [0, 1], 'water_target_C': [20, 60], 'activity_W': [72, 300]},
        'programs': {key: {'duration_min': 60, 'model_key': 'synthetic', 'version': 'test'} for key in ['washer', 'dryer', 'dishwasher']}}
