"""Inventory/control adapter for the same condition→source→EB compiler chain."""
import argparse
import copy
from pathlib import Path
import time

from .common import ROOT,read,require,save,digest
from .case_commands import CaseTimeline
from .condition_inventory import make_pack,require_no_absent_demands,project_engineering_case
from .condition_controls import bind,validate as validate_control,fixed_control_fields
from .housing_pipeline import validate_entry
from .reference_scenarios import FUNCTIONS,inventory
from .reference_workflow import ref
from .source_adapter import source_file


def expected_id(fixture,installed):
    return fixture['id'] if len(installed)==6 else 'condition_inventory_'+digest({'parent_model':fixture['model'],'installed':sorted(installed)})[:24]


def run(preparation,equipment,case,out,libraries_ref,*,contract_ref=None,numerical_method_ref=None):
    entry=read(source_file(preparation['cache_entry'],ROOT));fixture=validate_entry(entry)
    require(preparation['fixture']==entry['fixture'],'CONDITION_ACTION_PREPARATION_CONFLICT')
    inv=inventory(equipment);require(not inv['unknown_presence'],'CONDITION_ACTION_PRESENCE_UNKNOWN')
    require(set(inv['installed'])>={'air_conditioner','water_heater'} and 4<=len(inv['installed'])<=6,'CONDITION_ACTION_UNSUPPORTED_NETWORK')
    uncontrolled=set(inv['installed'])-set(inv['controlled'])
    shared=any(a!=b and equipment[a]['physically_present'] and equipment[b]['physically_present']
        and equipment[a]['asset_id']==equipment[b]['asset_id'] for a in equipment for b in equipment)
    require(not(uncontrolled or shared) or contract_ref is not None,'CONDITION_ACTION_FIXED_SHARED_CONTRACT_REQUIRED')
    case=copy.deepcopy(case)
    out=Path(out).resolve();require(out.is_relative_to(ROOT) and not out.exists(),'CONDITION_ACTION_OUTPUT_EXISTS');out.mkdir(parents=True)
    original_domain=read(source_file(fixture['input_domain'],ROOT));calendar_transaction=None
    from .condition_calendar import validate_window,prepare as prepare_calendar
    validate_window(case['run'],original_domain['run_period'])
    if case['run']!=original_domain['run_period']:
        fixture_ref,_=prepare_calendar(entry['fixture'],entry['engineering_case'],case['run']['start_date'],out/'calendar')
        fixture=read(source_file(fixture_ref,ROOT))
        require(read(source_file(fixture['input_domain'],ROOT))['run_period']==case['run'],'CONDITION_ACTION_CALENDAR_CONFLICT')
        entry=copy.deepcopy(entry);entry['fixture']=fixture_ref
        calendar_transaction=ref(out/'calendar/CALENDAR_TRANSACTION.json')
    if numerical_method_ref:
        method=read(source_file(numerical_method_ref,ROOT))
        require(method['schema']=='national_idf.condition_numerical_method.v1'
            and method['algorithm']=='AnalyticalSolution' and method['requires_own_CASE_quality'] is True,
            'CONDITION_ACTION_UNREVIEWED_NUMERICAL_METHOD')
        require(method['engine_schema']==fixture['engine_schema'],'CONDITION_ACTION_METHOD_ENGINE_CONFLICT')
        for evidence in method['independent_checks']:
            quality=read(source_file(evidence,ROOT))
            require(quality['quality_passed'] and quality['curve_domain_passed'],'CONDITION_ACTION_METHOD_EVIDENCE_FAILED')
        # Derive a versioned method configuration,leaving the cached housing,
        # original failed outputs and every physical parameter unchanged.
        parent=out/'method_parent';parent.mkdir()
        save(parent/'FIXTURE.json',fixture)
        method_case=copy.deepcopy(case);method_case['environment']['physics_configuration_id']=fixture['id']
        save(parent/'CASE.json',method_case)
        from scripts.prepare_condition_solver import execute as apply_method
        apply_method(parent,out/'method')
        entry=copy.deepcopy(entry);entry['fixture']=ref(out/'method/FIXTURE.json')
        fixture=read(out/'method/FIXTURE.json')
    identifier=expected_id(fixture,inv['installed'])
    require(case['environment'].get('physics_configuration_id') in (None,identifier),'CONDITION_ACTION_CONFIGURATION_CONFLICT')
    case['environment']['physics_configuration_id']=identifier
    domain=read(source_file(fixture['input_domain'],ROOT));domain['physics_configuration_id']=identifier
    timeline=CaseTimeline(case,domain)
    control=None;bound_contract=None
    if contract_ref:
        bound_contract=bind(contract_ref,case,identifier,out)
        control=validate_control(case,timeline,equipment,bound_contract);save(out/'CONTROL_CHECKS.json',control)
    save(out/'CASE.json',case);save(out/'FIXTURE.json',fixture);save(out/'EQUIPMENT.json',equipment)
    start=time.monotonic()
    if len(inv['installed'])==6:
        from .joint_case_runtime import compile_joint_case,run_joint_case
        compile_joint_case(entry['fixture'],case,out/'compiled',mode='engineering_reference');run_joint_case(out/'compiled',out/'run',mode='engineering_reference')
        from scripts.validate_multicountry_life import validate
        native=validate(out/'run',fixture,case)
        from scripts.check_condition_housing import execute
        execute(out,libraries_ref);quality_ref=ref(out/'numerics/QUALITY.json')
        numeric_roots=[v/'parent' for v in (out/'numerics').iterdir() if v.is_dir()]
    else:
        # The old compiler actuates fixed services as well as user-controlled
        # tasks. Permission validation above is an independent requirement.
        make_pack(entry['fixture'],equipment,out/'inventory',fixed_service_contract_validated=control is not None)
        pack_ref=ref(out/'inventory/PACK.json');pack=read(source_file(pack_ref,ROOT));require_no_absent_demands(case,pack)
        from .reference_inventory import compile_case,run as run_inventory
        compile_case(entry['fixture'],pack_ref,case,out/'compiled');run_inventory(out/'compiled',out/'run')
        from scripts.validate_multicountry_life import validate
        native=validate(out/'run',fixture,case,inv['installed'],out/'compiled/DOMAIN.json')
        # Create numerical parents without rerunning six physical devices.
        # Each projected child is then compiled/executed by the old adapter.
        base=out/'quality_parent';base.mkdir();save(base/'FIXTURE.json',fixture)
        parent_case=copy.deepcopy(case);parent_case['environment']['physics_configuration_id']=fixture['id'];save(base/'CASE.json',parent_case)
        from .condition_quality import prepare
        libraries=read(source_file(libraries_ref,ROOT))
        for step,warmup,days in [(1,14,7),(2,14,7),(5,14,7),(2,28,7),(2,14,14)]:
            for arm in ('baseline','intervention'):
                tag=f's{step}_w{warmup}_d{days}_{arm}'
                prepare(entry['fixture'],case,libraries['fixtures'][str(step)],base/'numerics'/tag/'parent',step,warmup,days,arm,
                    'action_'+digest({'fixture':entry['fixture'],'case':case,'variant':tag})[:24],
                    fixed_control_fields=fixed_control_fields(equipment))
        backend={k:{**v,'control_enabled':v['physically_present']} for k,v in equipment.items()}
        save(out/'BACKEND_EQUIPMENT.json',backend)
        from scripts.check_condition_inventory import execute
        execute(base,ref(out/'BACKEND_EQUIPMENT.json'),out/'inventory_quality')
        quality_ref=ref(out/'inventory_quality/QUALITY.json')
        numeric_roots=[v/'compiled' for v in (out/'inventory_quality/numerics').iterdir() if v.is_dir()]
    # The same contract is checked on every diagnostic instruction as well.
    numeric_controls={}
    if bound_contract:
        for i,folder in enumerate(numeric_roots):
            c=read(folder/'CASE.json')
            if (folder/'DOMAIN.json').exists():d=read(folder/'DOMAIN.json')
            else:d=read(source_file(read(folder/'FIXTURE.json')['input_domain'],ROOT))
            location=out/'numeric_contracts'/str(i);location.mkdir(parents=True)
            contract=bind(bound_contract,c,c['environment']['physics_configuration_id'],location,recovery_extension=True,diagnostic_parent_id=identifier)
            numeric_controls[str(i)]=validate_control(c,CaseTimeline(c,d),equipment,contract)
    q=read(source_file(quality_ref,ROOT))
    result={'schema':'national_idf.condition_action_execution.v1','source_preparation':preparation,
        'fixture':entry['fixture'],'equipment':ref(out/'EQUIPMENT.json'),'physics_configuration_id':identifier,
        'native_component_life_checks_pass':native['passed_input_and_component_checks'],
        'quality':quality_ref,'quality_passed':q['quality_passed'] and q['curve_domain_passed'],
        'installed_devices':inv['installed'],'controlled_devices':inv['controlled'],
        'control_contract_checks':control,'numerical_contract_checks':numeric_controls,
        'seconds_including_new_case_quality':time.monotonic()-start,
        'explicit_numerical_method':numerical_method_ref,
        'calendar_transaction':calendar_transaction,
        'old_EB_and_source_compilers_used':True,'combined_machine_product_physics_claimed':False,
        'model_admission_granted':False,'household_generation_or_final_AB_changed':False}
    save(out/'EXECUTION.json',result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--preparation',type=Path,required=True);p.add_argument('--equipment',type=Path,required=True)
    p.add_argument('--case',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--libraries',type=Path,required=True);p.add_argument('--contract',type=Path);p.add_argument('--numerical-method',type=Path)
    a=p.parse_args();run(read(a.preparation),read(a.equipment),read(a.case),a.out,ref(a.libraries),contract_ref=ref(a.contract) if a.contract else None,numerical_method_ref=ref(a.numerical_method) if a.numerical_method else None)
