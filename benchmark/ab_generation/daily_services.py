
"""EB daily service cardinality, independent of physical/native acceptance."""
import datetime as dt
from collections import Counter
from .common import digest

FUNCTIONS={'AC':'ac','WM':'washer','DR':'dryer','DW':'dishwasher','WH':'water_heater','EV':'ev'}
REVERSE={v:k for k,v in FUNCTIONS.items()}
PROGRAMMES={'WM','DR','DW'}

def compile_daily_contract(case,date):
    dt.date.fromisoformat(date)
    h=case['household'];controlled=set(h['controlled_function_ids'])
    if 'AC' not in controlled:raise ValueError('DAILY_POLICY_REQUIRES_CONTROLLED_AC')
    programmes=[];services=[]
    for aid,asset in sorted(h['service_asset_registry'].items()):
        for raw in sorted(set(asset['functions'])):
            function=raw if raw in FUNCTIONS else REVERSE.get(raw)
            if function is None:continue
            item={'asset_id':aid,'function':function,'kind':FUNCTIONS[function],
                  'mode':'controllable' if function in controlled else 'fixed_routine',
                  'service_date':date,'origin':'EB_benchmark_daily_task_setting;not_survey_usage_frequency'}
            if function in PROGRAMMES:
                programmes.append({**item,'required_complete_programmes':1})
            else:
                services.append({**item,'required_daily_service':True})
    if not any(x['function']=='AC' for x in services):raise ValueError('REGISTERED_DAILY_AC_MISSING')
    result={'schema':'eb.daily_service_requirements.v1','date':date,
            'household_case_sha256':digest(case),'programme_requirements':programmes,'other_daily_services':services,
            'legacy_weekly_experimental_frequency_overrides_daily_tasks':False,
            'fixed_services_cannot_be_dropped':True,
            'technical_initialization_recovery_days_are_not_extra_daily_questions':True,
            'A_B_same_daily_service_requirements':True}
    result['sha256']=digest(result)
    return result

def audit_programme_cardinality(contract,plan,service_date_by_need):
    counts=Counter();unknown=[]
    for task in plan['tasks']:
        if task['kind'] not in ('washer','dryer','dishwasher'):continue
        date=service_date_by_need.get(task['need_id'])
        if date is None:unknown.append(task['need_id']);continue
        if date==contract['date']:counts[(task['asset_id'],task['kind'])]+=1
    errors=[]
    expected={(r['asset_id'],r['kind']):r['required_complete_programmes'] for r in contract['programme_requirements']}
    for key in sorted(set(expected)|set(counts)):
        if counts[key]!=expected.get(key,0):
            errors.append({'code':'DAILY_PROGRAMME_COUNT_MISMATCH','asset_id':key[0],'kind':key[1],
                           'required':expected.get(key,0),'actual':counts[key]})
    if unknown:errors.append({'code':'PROGRAMME_SERVICE_DATE_UNBOUND','need_ids':unknown})
    return {'schema':'eb.daily_programme_cardinality_audit.v1','passed':not errors,'errors':errors,
            'daily_contract_sha256':contract['sha256'],'native_or_physical_execution_proven':False}

def audit_context_daily_services(case,context):
    contract=compile_daily_contract(case,context['date'])
    bindings=context.get('programme_service_date_by_need')
    if not isinstance(bindings,dict):
        return {'schema':'eb.daily_programme_cardinality_audit.v1','passed':False,
                'errors':[{'code':'DAILY_SERVICE_DATE_BINDING_MISSING'}],
                'daily_contract_sha256':contract['sha256'],'native_or_physical_execution_proven':False}
    return audit_daily_plan({**context,'daily_service_requirements':contract},context['A'])

def audit_daily_plan(context,plan):
    """Daily tasks and declared service commands; not physical service success."""
    contract=context['daily_service_requirements']
    result=audit_programme_cardinality(contract,plan,context.get('programme_service_date_by_need',{}))
    errors=result['errors'];controls=plan.get('controls',[])
    for service in contract['other_daily_services']:
        aid=service['asset_id'];function=service['function']
        if function in ('AC','WH'):
            kind='ac_setpoint' if function=='AC' else 'tank_setpoint'
            if not any(r.get('asset_id')==aid and r.get('kind')==kind and r['start_min']<1440 and r['end_min']>0 for r in controls):
                errors.append({'code':'DAILY_SERVICE_CONTROL_MISSING','function':function,'asset_id':aid})
        if function=='EV':
            connections=context.get('physical_ev_connections',[])
            if not connections:errors.append({'code':'DAILY_EV_CONNECTION_MISSING','asset_id':aid})
            device=next((d for d in context.get('devices',[]) if d['asset_id']==aid),None)
            params=device.get('parameters',{}) if device else {}
            required={'target_soc','capacity_kwh','initial_energy_kwh','efficiency'}
            if not required<=params.keys():
                errors.append({'code':'DAILY_EV_INITIAL_STATE_MISSING','asset_id':aid});continue
            needed=max(0,params['target_soc']*params['capacity_kwh']-params['initial_energy_kwh'])/params['efficiency']
            need_ids={x['need_id'] for x in connections}
            declared=sum(r['grid_kWh'] for r in context.get('reference',{}).get('ev_charging_steps',[]) if r['need_id'] in need_ids)
            if declared+1e-5<needed:errors.append({'code':'DAILY_EV_ENERGY_REQUIREMENT_UNBOUND','asset_id':aid})
            if needed>1e-8 and not any(r.get('asset_id')==aid and r.get('kind')=='ev_charge_window' and r.get('need_id') in need_ids for r in controls):
                errors.append({'code':'DAILY_SERVICE_CONTROL_MISSING','function':'EV','asset_id':aid})
    result['passed']=not errors
    result['scope']='complete_daily_programme_counts_and_declared_service_commands;native_execution_and_physics_separate'
    return result
