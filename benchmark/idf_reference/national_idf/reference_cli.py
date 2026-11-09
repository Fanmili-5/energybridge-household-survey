"""Reference extension CLI; leaves the strict/formal household entry unchanged."""
import argparse
from pathlib import Path

from .common import ROOT, read, save, require, seal
from .reference_workflow import compile_case, prepare, ref, run


def validate_reference_request_shape(request):
    required={'schema','purpose','country','survey_dwelling','reference_selection','equipment'}
    require(required<=set(request)<=required|{'request_id','source_input_receipt','upstream_reference_dwelling'},'REFERENCE_REQUEST_UNKNOWN_OR_MISSING_FIELDS')
    require(set(request['reference_selection'])<={'physics_configuration_id','housing_class','acknowledge_reference_not_survey_home'},
            'REFERENCE_PHYSICAL_OVERRIDE_OR_UNKNOWN_SELECTION_FIELD')


def main():
    p = argparse.ArgumentParser(description=__doc__); sub = p.add_subparsers(dest='action', required=True)
    q = sub.add_parser('prepare'); q.add_argument('--workflow', type=Path, required=True); q.add_argument('--out', type=Path, required=True)
    q = sub.add_parser('compile'); q.add_argument('--preparation', type=Path, required=True); q.add_argument('--case', type=Path, required=True); q.add_argument('--out', type=Path, required=True)
    q = sub.add_parser('run'); q.add_argument('--compiled', type=Path, required=True); q.add_argument('--out', type=Path, required=True)
    q = sub.add_parser('inventory-compile'); q.add_argument('--fixture', type=Path, required=True)
    q.add_argument('--inventory', type=Path, required=True); q.add_argument('--case', type=Path, required=True); q.add_argument('--out', type=Path, required=True)
    q = sub.add_parser('life-prepare'); q.add_argument('--blueprint', type=Path, required=True)
    q.add_argument('--fixture', type=Path, required=True); q.add_argument('--out', type=Path, required=True)
    q.add_argument('--supply-receipt', type=Path)
    q = sub.add_parser('source-case-compile'); q.add_argument('--blueprint', type=Path, required=True)
    q.add_argument('--fixture', type=Path, required=True); q.add_argument('--case', type=Path, required=True)
    q.add_argument('--control-contract', type=Path); q.add_argument('--out', type=Path, required=True)
    q = sub.add_parser('resolve'); q.add_argument('--request', type=Path, required=True); q.add_argument('--catalog', type=Path, required=True); q.add_argument('--out', type=Path, required=True)
    q = sub.add_parser('screen-households'); q.add_argument('--projection', type=Path, required=True)
    q.add_argument('--catalog', type=Path, required=True); q.add_argument('--out', type=Path, required=True)
    q = sub.add_parser('reviewed-compile'); q.add_argument('--release', type=Path)
    q.add_argument('--catalog',type=Path,default=ROOT/'configs/multicountry_reference_catalog.json')
    q.add_argument('--case', type=Path, required=True); q.add_argument('--out', type=Path, required=True)
    q.add_argument('--control-contract', type=Path)
    q = sub.add_parser('reviewed-run'); q.add_argument('--compiled', type=Path, required=True)
    q.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    if a.action == 'prepare': prepare(ref(a.workflow), a.out)
    elif a.action == 'compile': compile_case(ref(a.preparation), read(a.case), a.out)
    elif a.action == 'run':
        if read(a.compiled/'MANIFEST.json')['schema'] == 'national_idf.compiled_inventory_reference.v1':
            from .reference_inventory import run as run_inventory
            run_inventory(a.compiled, a.out)
        else:run(a.compiled, a.out)
    elif a.action == 'inventory-compile':
        from .reference_inventory import compile_case as compile_inventory
        compile_inventory(ref(a.fixture), ref(a.inventory), read(a.case), a.out)
    elif a.action == 'life-prepare':
        from .reference_life import prepare as prepare_life
        prepare_life(ref(a.blueprint), ref(a.fixture), a.out,
                     supply_receipt_ref=ref(a.supply_receipt) if a.supply_receipt else None)
    elif a.action == 'source-case-compile':
        from .assembly import plan_assembly
        from .idf import parse
        from .source_adapter import source_file
        from .joint_case_runtime import compile_joint_case
        fixture, case = read(a.fixture), read(a.case)
        plan = plan_assembly(fixture['id'], blueprint_ref=ref(a.blueprint))
        require(plan['engineering_compilation_ready'] and plan['new_model_rows'] ==
                parse(source_file(fixture['model']).read_text()), 'REFERENCE_SOURCE_COMPILER_MODEL_MISMATCH')
        control = None
        if a.control_contract:
            from .reference_controls import validate
            from .case_commands import CaseTimeline
            control = validate(case, CaseTimeline(case, read(source_file(fixture['input_domain']))), ref(a.control_contract))
        metadata = compile_joint_case(ref(a.fixture), case, a.out, mode='engineering_reference')
        save(a.out/'SOURCE_COMPILATION.json', {'blueprint': ref(a.blueprint), 'fixture': ref(a.fixture),
                                             'exact_source_compiler_rows_checked': True, 'control_contract': control,
                                             'formal_admitted': False})
        if a.control_contract:save(a.out/'CONTROL_CONTRACT.json', read(a.control_contract))
        seal(a.out, {k:v for k,v in metadata.items() if k!='files'})
    elif a.action == 'screen-households':
        from .household_reference_interface import screen
        save(a.out,screen(ref(a.projection),ref(a.catalog)))
    elif a.action == 'reviewed-compile':
        from .reference_release import compile_case as compile_reviewed
        case=read(a.case)
        if a.release:release_ref=ref(a.release)
        else:
            matches=[r for r in read(a.catalog)['records'] if r['id']==case['environment']['physics_configuration_id']]
            require(len(matches)==1 and matches[0].get('reviewed') and matches[0].get('reference_release'),
                    'REFERENCE_CONFIGURATION_NOT_REGISTERED_OR_REVIEWED')
            release_ref=matches[0]['reference_release']
        compile_reviewed(release_ref,case,a.out,
                         control_contract=ref(a.control_contract) if a.control_contract else None)
    elif a.action == 'reviewed-run':
        from .reference_release import run_case
        run_case(a.compiled,a.out)
    else:
        from .reference_scenarios import resolve
        request=read(a.request);validate_reference_request_shape(request)
        save(a.out, resolve(request, ref(a.catalog)))


if __name__ == '__main__': main()
