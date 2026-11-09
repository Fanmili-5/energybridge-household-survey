"""Reporting-only curve instrument shared by source inventory adapters."""
import copy

from .common import ROOT, digest, read, require, sha
from .idf import objects
from .program_resources import model_signature
from .reference_workflow import ref
from .source_adapter import source_file
from .curve_domain import reviewed_policy, assess


def instrument(rows, fields):
    result = copy.deepcopy(rows); tables = {}
    lists = {r[1]: r[2:] for r in objects(rows, 'Table:IndependentVariableList')}
    axes = {r[1]: r for r in objects(rows, 'Table:IndependentVariable')}
    for row in objects(rows, 'Table:Lookup'):
        coordinates = []
        for name in lists[fields.get(row, 'independent_variable_list_name')]:
            axis = axes[name]; values = [float(v) for v in axis[11:]]
            coordinates.append({'name': name, 'grid_values': values, 'grid_range': [min(values), max(values)],
                                'extrapolation': fields.get(axis, 'extrapolation_method')})
        tables[row[1]] = {'source_row_sha256': digest(row), 'axes': coordinates}
        for variable in ['Performance Curve Output Value', *[f'Performance Curve Input Variable {i} Value' for i in range(1, len(coordinates) + 1)]]:
            result.append(['Output:Variable', row[1], variable, 'Timestep'])
    require(tables and model_signature(rows) == model_signature(result), 'CURVE_INSTRUMENT_CHANGED_MODEL')
    return result, tables


def report(rows, tables, fields, native_folder, *, root=ROOT):
    from scripts.analyze_whitegoods_shift import series
    policy = ref(root / 'reports/public_method_scope_20261103/WET_BULB_POLICY.json', root)
    definition = read(source_file(policy, root))
    require(definition['source_code']['sha256'] == sha(root / 'work/p1_hpxml_004ca3ce/HPXMLtoOpenStudio/resources/hvac.rb'),
            'CURVE_SOURCE_VERSION_CHANGED')
    allowed = reviewed_policy(policy, tables, rows, fields)
    data = series(native_folder)
    def get(variable, key, unit): return data[variable, key.removeprefix('HP_AC_').casefold()]
    result = assess(tables, get, reviewed_axes=allowed)
    result.update(unchanged_source_curve_method_policy=policy, source_table_grid_is_not_product_test_domain=True,
                  empirical_product_performance_validated=False, formal_admitted=False)
    return result
