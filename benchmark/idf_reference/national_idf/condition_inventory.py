"""Data-selected inventory projections for condition-generated reference houses.

Only isolated consumers are retired. All physical editing,life ports and EB
execution delegate to the existing inventory/source compilers. Logical user
control permissions stay separate from the backend's fixed-service actuation.
"""
import copy
from pathlib import Path

from .common import ROOT,digest,read,require,save
from .idf import Fields,objects,parse,render
from .program_resources import plan_resources
from .reference_scenarios import FUNCTIONS,inventory
from .reference_workflow import ref
from .source_adapter import source_file,selector


def make_pack(fixture_ref,equipment,out,*,root=ROOT,fixed_service_contract_validated=False):
    inv=inventory(equipment)
    require(not inv['unknown_presence'],'CONDITION_INVENTORY_PRESENCE_UNKNOWN',inv['unknown_presence'])
    require(set(inv['installed'])>={'air_conditioner','water_heater'} and 4<=len(inv['installed'])<=6,
            'CONDITION_INVENTORY_NETWORK_OR_COUNT_UNSUPPORTED')
    require(set(inv['controlled'])==set(inv['installed']) or fixed_service_contract_validated,
            'CONDITION_FIXED_BACKGROUND_CONTRACT_REQUIRED')
    parent=read(source_file(fixture_ref,root));rows=parse(source_file(parent['model'],root).read_text())
    fields=Fields(source_file(parent['engine_schema'],root));programmes=plan_resources(rows,parent['engine_schema'],parent['resource_pack'],root=root)
    absent=set(FUNCTIONS.values())-set(inv['installed'])
    require(absent<={'washer','dryer','dishwasher','ev'},'CONDITION_INVENTORY_NONISOLATED_COMPONENT')
    out=Path(out).resolve();require(out.is_relative_to(root) and not out.exists(),'CONDITION_INVENTORY_OUTPUT_EXISTS');out.mkdir(parents=True)
    # Backend actuation includes fixed/background services;it is not a grant
    # of user permission. Actual flags and shared resources are checked by the
    # independent control contract before compilation/execution.
    backend={k:{'physically_present':v in inv['installed'],'control_enabled':v in inv['installed'],
        'presence_basis':'Explicit reference installation from declared inventory;not inferred from control permission',
        'asset_id':'source-reference-'+k if v in inv['installed'] else None} for k,v in FUNCTIONS.items()}
    declaration={'schema':'national_idf.condition_inventory_design.v1','source_fixture':fixture_ref,
        'installed_devices':inv['installed'],'requested_equipment':equipment,
        'backend_actuation_not_user_control_permission':True}
    save(out/'DECLARATION.json',declaration)
    retired={}
    for device in absent:
        if device=='ev':retired[device]=[parent['EB_mapping']['equipment']['ev']['equipment']]
        else:
            p=programmes['definition']['programs'][device]
            retired[device]=[r[1] for r in rows if
                r[0]=='ElectricEquipment' and r[1]==p['equipment'] or
                r[0] in ('OtherEquipment','WaterUse:Equipment') and
                fields.get(r,'schedule_name' if r[0]=='OtherEquipment' else 'flow_rate_fraction_schedule_name') in p['schedules']]
    names={name for values in retired.values() for name in values}
    water={r[1] for r in objects(rows,'WaterUse:Equipment') if r[1] in names}
    changes=[];replacements=[]
    for i,row in enumerate(rows):
        if row[0] in ('ElectricEquipment','OtherEquipment','WaterUse:Equipment','Output:Variable') and row[1] in names:
            op={'action':'remove'}
        elif row[0]=='WaterUse:Connections' and any(name in row[2:] for name in water):
            replacements.append([v for v in row if v not in water]);op={'action':'replace','replacement_index':len(replacements)-1}
        else:continue
        op.update(object=selector(rows,i),reason='Declared physical absence;retire only its exact native consumers',
                  evidence=ref(out/'DECLARATION.json',root),affected_meters=['Electricity:Facility','InteriorEquipment:Electricity','Water'])
        changes.append(op)
    if replacements:
        (out/'REPLACEMENTS.idf').write_text(render(replacements))
        for op in changes:
            if 'replacement_index' in op:
                i=op.pop('replacement_index');op['after']={'file':ref(out/'REPLACEMENTS.idf',root),'object':selector(replacements,i)}
    identifier='condition_inventory_'+digest({'parent_model':parent['model'],'installed':sorted(inv['installed'])})[:24]
    pack={'schema':'national_idf.reference_inventory_pack.v1','id':identifier,'parent_model':parent['model'],
          'equipment':backend,'changes':changes,'retired_physical_object_names':retired}
    save(out/'PACK.json',pack);return ref(out/'PACK.json',root)


def project_engineering_case(case,pack):
    """Declare a new component-test demand;never silently repair a user CASE."""
    value=copy.deepcopy(case);value['case_id']=pack['id']+'__engineering'
    value['environment']['physics_configuration_id']=pack['id']
    absent=set(FUNCTIONS.values())-set(inventory(pack['equipment'])['installed'])
    for device in absent-{'ev'}:
        value['life']['services_daily'][device]['cycles']=0
        value['controls']['program_starts_daily'][device]=[]
        for entry in value['controls']['program_start_overrides'].values():entry[device]=[]
    if 'ev' in absent:
        value['life']['ev_connection_daily']=[]
        value['life']['ev_daily'].update(traction_kWh=0,required_departure_SOC=0)
        value['controls'].update(ev_daily_windows=[],ev_window_overrides={},ev_target_SOC=0)
    value['life']['basis']='Explicit fixed component-test inventory projection;not generated household demand or finalAB'
    return value


def _require_no_absent_demands_v2(case,pack):
    absent=set(FUNCTIONS.values())-set(inventory(pack['equipment'])['installed'])
    for device in absent-{'ev'}:
        require(case['life']['services_daily'][device]['cycles']==0 and not case['controls']['program_starts_daily'][device]
            and all(not v.get(device,[]) for v in case['controls']['program_start_overrides'].values()),
            'CONDITION_ABSENT_DEVICE_DEMAND',device)
    if 'ev' in absent:
        require(not case['life']['ev_connection_daily'] and case['life']['ev_daily']['traction_kWh']==0
            and case['life']['ev_daily']['required_departure_SOC']==0 and case['controls']['ev_target_SOC']==0
            and not case['controls']['ev_daily_windows'] and not case['controls']['ev_window_overrides'],
            'CONDITION_ABSENT_HOME_EV_DEMAND')


def require_no_absent_demands(case,pack):
    _require_no_absent_demands_v2(case,pack)
    if case.get('schema')=='national_idf.case.v3':
        from .dated_case import view,dates
        for date in dates(case):_require_no_absent_demands_v2(view(case,date),pack)
