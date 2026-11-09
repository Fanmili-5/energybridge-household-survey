"""Read-only native curve observations using the existing public method policy."""
import argparse
import copy
import csv
from pathlib import Path

from national_idf.common import ROOT, read, save, require, digest, sha
from national_idf.idf import Fields, objects, parse, render
from national_idf.joint_case_runtime import compile_joint_case, run_joint_case
from national_idf.program_resources import model_signature
from national_idf.reference_workflow import ref
from national_idf.source_adapter import source_file
from national_idf.curve_domain import assess, reviewed_policy
from scripts.run_multicountry_life_inventories import scoped_fixture
from scripts.analyze_whitegoods_shift import series
from scripts.validate_multicountry_life import OUT


def execute(label, *, base_folder=None, output_folder=None):
    parent=Path(base_folder).resolve() if base_folder else OUT/label
    fixture_path,prior_run=(parent/'FIXTURE.json',parent/'run') if base_folder else scoped_fixture(parent)
    fixture=read(fixture_path)
    source=parse(source_file(fixture['model'],ROOT).read_text());rows=copy.deepcopy(source)
    fields=Fields(source_file(fixture['engine_schema'],ROOT))
    lists={r[1]:r[2:] for r in objects(rows,'Table:IndependentVariableList')}
    axes={r[1]:r for r in objects(rows,'Table:IndependentVariable')};tables={}
    for row in objects(rows,'Table:Lookup'):
        name=row[1];table_axes=[]
        for axis_name in lists[fields.get(row,'independent_variable_list_name')]:
            axis=axes[axis_name];points=[float(v) for v in axis[11:]]
            table_axes.append({'name':axis_name,'grid_values':points,'grid_range':[min(points),max(points)],
                               'extrapolation':fields.get(axis,'extrapolation_method')})
        tables[name]={'source_row_sha256':digest(row),'axes':table_axes}
        for variable in ['Performance Curve Output Value',*[f'Performance Curve Input Variable {i} Value' for i in range(1,len(table_axes)+1)]]:
            rows.append(['Output:Variable',name,variable,'Timestep'])
    require(tables and model_signature(source)==model_signature(rows),'CURVE_OBSERVER_CHANGED_PHYSICS')
    folder=Path(output_folder).resolve() if output_folder else parent/'curve_observed'
    require(folder.is_relative_to(ROOT),'CURVE_OUTPUT_OUTSIDE_PROJECT');folder.mkdir(parents=True,exist_ok=True)
    (folder/'in.idf').write_text(render(rows));fixture['model']=ref(folder/'in.idf');save(folder/'FIXTURE.json',fixture)
    save(folder/'TABLES.json',tables)
    policy=ref(ROOT/'reports/public_method_scope_20261103/WET_BULB_POLICY.json')
    # This release uses the exact same public HPXML HVAC implementation already
    # covered by the project's indoor-wetbulb constant-extension review.
    definition=read(source_file(policy,ROOT))
    require(definition['source_code']['sha256']==sha(ROOT/'work/p1_hpxml_004ca3ce/HPXMLtoOpenStudio/resources/hvac.rb'),
            'CURVE_REFERENCE_PUBLIC_METHOD_VERSION_MISMATCH')
    allowed=reviewed_policy(policy,tables,rows,fields)
    if not (folder/'compiled').exists():compile_joint_case(ref(folder/'FIXTURE.json'),read(parent/'CASE.json'),folder/'compiled',mode='engineering_reference')
    if not (folder/'run').exists():run_joint_case(folder/'compiled',folder/'run',mode='engineering_reference')
    before=list(csv.DictReader((prior_run/'TRACE.csv').open()));after=list(csv.DictReader((folder/'run/TRACE.csv').open()))
    require(before==after,'CURVE_REPORTING_CHANGED_NATIVE_TRACE')
    data=series(folder/'run')
    def get(variable,key,unit):return data[variable,key.removeprefix('HP_AC_').casefold()]
    report=assess(tables,get,reviewed_axes=allowed)
    report.update(unchanged_existing_curve_method_policy=policy,
        heating_at_this_window_empirically_validated=False,
        heating_observations_present=any(a['active_observations']>0 for a in report['axes'] if 'Heat-' in a['curve']),
        curve_reporting_native_trace_unchanged=True,
        source_table_inputs_are_source_model_grid_not_measured_product_domain=True,formal_admitted=False)
    save(folder/'CURVE_CHECKS.json',report)
    print(label,'curve observations',report['unreviewed_outside_count'],'unreviewed excursions',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--label',choices=['US','ES','US_apartment'],required=True)
    p.add_argument('--base-folder');p.add_argument('--out');args=p.parse_args()
    execute(args.label,base_folder=args.base_folder,output_folder=args.out)
