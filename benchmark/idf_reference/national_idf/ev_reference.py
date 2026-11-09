"""Load frozen EV reference hardware without inventing life or initial inputs."""
from .common import ROOT, read, require
from .source_adapter import source_file


def hardware_parameters(pack_ref, root=ROOT):
    pack = read(source_file(pack_ref, root))
    require(pack.get('schema') == 'national_idf.eb_ev_component_reference.v1'
            and pack.get('id') == 'eb_ev_ochre_0bf05035_BEV100', 'EV_REFERENCE_IDENTITY')
    require(pack.get('formal_admitted') is False and pack.get('gaps'), 'EV_REFERENCE_CANNOT_GRANT_RELEASE')
    source_file(pack['source_archive'], root)
    source = source_file(pack['source_module'], root)
    proof = read(source_file(pack['charging_kernel_comparison'], root))
    source_file(proof['source_module'], root)
    source_file(proof['EB_module'], root)
    require(proof['source_module'] == pack['source_module']
            and proof['source_commit'] == pack['source_commit']
            and proof['source_generator_calls'] == 0, 'EV_REFERENCE_PROOF_NOT_BOUND')
    expected = proof['reference_inputs']
    hardware = {'capacity_kwh': expected['capacity_kWh'], 'charger_kw': expected['max_power_kW'],
                'efficiency': expected['charging_efficiency']}
    require(pack['hardware'] == hardware and expected['vehicle_type'] == 'BEV'
            and expected['range_miles'] == 100, 'EV_REFERENCE_PARAMETER_SPLICE')
    require(pack['EB_module'] == proof['EB_module'], 'EV_REFERENCE_EB_IMPLEMENTATION_CHANGED')
    require(all(r['max_power_difference_kW'] < 1e-10 and r['max_SOC_difference'] < 1e-12
                for r in proof['records']) and {r['step_minutes'] for r in proof['records']} == {1, 2, 5},
            'EV_REFERENCE_CHARGING_COMPARISON_INCOMPLETE')
    return {'hardware': hardware, 'source_model': pack['id'],
            'required_separate_inputs': ['initial_SOC', 'plug_state', 'travel_energy_demand', 'charge_window', 'target_SOC'],
            'outside_indoor_heat_balance': True, 'formal_admitted': False,
            'scope': 'One frozen constant-efficiency public reference; no inferred routines, climates or product performance'}
