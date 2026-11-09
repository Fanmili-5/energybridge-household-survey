"""Native life-port and existing device-ledger checks on explicit test inputs."""
import csv
from collections import defaultdict

from national_idf.common import ROOT, read, require, save
from national_idf.case_commands import CaseTimeline
from national_idf.idf import objects, parse
from national_idf.source_adapter import source_file
from scripts.analyze_multicountry_reference import analyze

OUT = ROOT/'reports/multicountry_life_20261108'
SIX = ['air_conditioner', 'washer', 'dryer', 'dishwasher', 'water_heater', 'ev']


def validate(folder, fixture, case, installed=SIX, domain_path=None):
    folder=folder.resolve()
    components=analyze(folder, fixture, installed)
    domain=read(domain_path or source_file(fixture['input_domain'], ROOT))
    timeline=CaseTimeline(case, domain)
    trace=list(csv.DictReader((folder/'TRACE.csv').open()))
    system=list(csv.DictReader((folder/'LIFE_SYSTEM.csv').open()))
    require(len(trace)==timeline.steps, 'LIFE_TEST_ZONE_CLOCK')
    maximum=lambda values:max((abs(v) for v in values), default=0)
    people_error=maximum(float(r['native_people_persons'])-float(r['requested_persons']) for r in trace)
    watts_error=maximum(float(r['native_people_total_W'])-float(r['requested_activity_total_W']) for r in trace)
    energy_error=maximum(float(r['native_people_total_J'])-float(r['native_people_sensible_J'])-
                         float(r['native_people_latent_J']) for r in trace)
    frames=defaultdict(lambda: {'L':0., 'seconds':0.})
    for r in system:
        frame=frames[int(r['frame_index'])]
        frame['L']+=float(r['EB_WATER_dhw fixtures:total_m3'])*1000
        frame['seconds']+=float(r['seconds'])
    require(set(frames)==set(range(timeline.steps)), 'LIFE_TEST_SYSTEM_FRAME_COVERAGE')
    liters_error=maximum(frames[i]['L']-timeline.frame(i)['mixed_water']['requested_volume_L'] for i in frames)
    clock_error=maximum(frames[i]['seconds']-timeline.frame(i)['duration_min']*60 for i in frames)
    service=read(folder/'WATER_SERVICE.json')
    mass_error=maximum(r['max_mass_balance_residual_kg_s'] for r in service['uses'].values())
    mix_error=maximum(r['max_mixing_residual_kg_K_s'] for r in service['uses'].values())
    passed=people_error<1e-12 and watts_error<1e-8 and energy_error<1e-7 and liters_error<1e-9 and clock_error<1e-6 and mass_error<1e-12 and mix_error<1e-12
    report={'schema':'national_idf.reference_life_native_validation.v1',
        'passed_input_and_component_checks':passed and components['passed_component_checks'],
        'zone_steps':len(trace), 'system_steps':len(system),
        'native_people_count_max_error':people_error, 'native_people_power_max_error_W':watts_error,
        'people_heat_partition_max_residual_J':energy_error,
        'per_frame_mixed_water_max_error_L':liters_error,
        'per_frame_system_clock_max_error_s':clock_error,
        'native_mixed_water_total_L':sum(v['L'] for v in frames.values()),
        'native_water_mass_balance_max_kg_s':mass_error,
        'native_water_mixing_max_kg_K_s':mix_error,
        'native_temperature_shortfall_K_kg':service['uses']['EB_WATER_dhw fixtures']['temperature_shortfall_K_kg'],
        'installed_devices':installed, 'native_facility_kWh':components['facility_kWh'],
        'public_source_fixture_peak_is_reference_normalization_not_shower_capacity':True,
        'event_room_heat_moisture_effect_supported':False,
        'numerical_acceptance':False, 'formal_admitted':False}
    save(folder/'LIFE_CHECKS.json', report)
    require(passed, 'LIFE_TEST_NATIVE_CONSEQUENCES_FAILED', report)
    return report


if __name__=='__main__':
    for label in ('US','ES','US_apartment'):
        folder=OUT/label
        result=validate(folder/'run',read(folder/'FIXTURE.json'),read(folder/'CASE.json'))
        print(label,'native life input checks passed',result['native_mixed_water_total_L'])
