"""Same design forcing and programme functions;original energy/temperature targets."""
from collections import defaultdict
import sqlite3

from national_idf.common import ROOT, read, save, require
from national_idf.reference_workflow import ref

OUT = ROOT / 'reports/multicountry_release_review_20261108'


def channel(folder, variable, key):
    with sqlite3.connect((folder / 'output/eplusout.sql').resolve().as_uri() + '?mode=ro', uri=True) as db:
        rows = db.execute('''SELECT e.EnvironmentName,t.Hour,t.Minute,t.Interval,r.Value
            FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex)
            JOIN Time t USING(TimeIndex) JOIN EnvironmentPeriods e USING(EnvironmentPeriodIndex)
            WHERE e.EnvironmentType=1 AND COALESCE(t.WarmupFlag,0)=0
            AND lower(d.Name)=lower(?) AND lower(d.KeyValue)=lower(?)''', (variable, key)).fetchall()
    require(rows, 'DESIGN_STEP_CHANNEL_MISSING', [variable, key])
    data = defaultdict(lambda: defaultdict(lambda: [0., 0.]))
    for env, hour, minute, interval, value in rows:
        end = (hour - 1) * 60 + minute; group = int((end - 1e-6) // 10)
        item = data[env][group]
        item[0] += value * interval if variable.endswith('Temperature') else value
        item[1] += interval
    return {env: {k: v[0] / v[1] if variable.endswith('Temperature') else v[0] for k, v in groups.items()} for env, groups in data.items()}


def compare(label, a, b):
    criteria = read(ROOT / 'configs/study_protocol.json')['numerical_criteria']; checks = {}
    for branch in ('independent_ideal_load', 'installed_heatpump'):
        for variable, key in [('Zone Mean Air Temperature', 'conditioned space'),
            ('Heating Coil Electricity Energy', 'mshp htg coil'), ('Cooling Coil Electricity Energy', 'mshp clg coil'),
            ('Fan Electricity Energy', 'mshp supply fan')]:
            aa, bb = [channel(base / branch, variable, key) for base in (a, b)]
            require(set(aa) == set(bb), 'DESIGN_STEP_ENVIRONMENT_CONFLICT')
            for env in aa:
                require(set(aa[env]) == set(bb[env]) and len(aa[env]) == 144, 'DESIGN_STEP_DAY_GRID_CONFLICT')
                if variable.endswith('Temperature'):
                    error = sum(abs(aa[env][k] - bb[env][k]) for k in aa[env]) / 144
                    limit = criteria['zone_mean_absolute_C']
                else:
                    error = abs(sum(aa[env].values()) - sum(bb[env].values())) / 3.6e6
                    limit = criteria['per_arm_energy_relative'] * max(abs(sum(bb[env].values()) / 3.6e6), 1e-9)
                checks[branch + '|' + env + '|' + variable] = {'error': error, 'limit': limit, 'passed': error <= limit}
    report = {'schema': 'national_idf.reference_design_step_comparison.v1', 'two_min_scope': ref(a / 'SCOPE.json'),
        'one_min_scope': ref(b / 'SCOPE.json'), 'checks': checks, 'all_existing_checks_pass': all(v['passed'] for v in checks.values()),
        'registered_criteria': ref(ROOT / 'configs/study_protocol.json'), 'formal_admitted': False}
    save(OUT / (label + '_DESIGN_NUMERICS.json'), report)
    print(label, report['all_existing_checks_pass'], flush=True)


if __name__ == '__main__':
    compare('US_cold', OUT / 'US_apartment_no_internal', OUT / 'US_apartment_no_internal_s1')
    compare('US_programs', OUT / 'US_apartment_public_programs', OUT / 'US_apartment_public_programs_s1')
    previous = ROOT / 'reports/multicountry_envelope_review_20261108'
    compare('ES_cold', previous / 'ES_no_internal_service', OUT / 'ES_no_internal_s1')
    compare('ES_programs', previous / 'ES_three_person_source_windows', OUT / 'ES_public_programs_s1')
