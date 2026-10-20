"""Import frozen reference-50 A46 plans, never old B or physical outcomes.

Only A cases and the A-side household input packs are read. Original calendars,
needs, equipment and command values are retained. Added EV control need IDs are
lineage metadata with an explicit import ledger, not schedule changes.
"""
import argparse
import copy
import datetime as dt
from pathlib import Path
from .common import read,save,sha,seal,verify,bound,digest,code_hash
from .generate import binding
from .information import information_set
from .model import plan_commands
from .resources import authority,legacy_program_constraints
from .collection_thermal import AC_CONTRACT
from .collection_design import design


def context(pack,case,source):
    from .life_physics import collections_for_context
    cdate=case['date'];hid=case['household_id'];a=plan_commands(case['A']);annotations=[]
    needs=legacy_program_constraints(case['needs_A']);devices=copy.deepcopy(pack['world']['parameter_pack']['devices'])
    for d in devices:
        d['kind']='washer' if 'washer' in d['types'] else d['types'][0]
        d['parameters'].setdefault('nameplate_W',d['max_electric_kw']*1000)
    for row in a['controls']:
        if row['kind']=='ev_charge_window' and 'need_id' not in row:
            choices=[n for n in needs if n['kind']=='ev' and n['asset_id']==row['asset_id'] and
                     n['connection_start_min']==row['start_min']]
            if len(choices)!=1:raise ValueError('EV_CONNECTION_LINEAGE_AMBIGUOUS:'+hid+':'+cdate)
            row['need_id']=choices[0]['need_id'];annotations.append({'asset_id':row['asset_id'],'start_min':row['start_min'],'end_min':row['end_min'],'need_id':row['need_id']})
    original=plan_commands(case['A']);stripped=copy.deepcopy(a)
    for row in stripped['controls']:
        if any(row['asset_id']==x['asset_id'] and row['start_min']==x['start_min'] and row['end_min']==x['end_min'] for x in annotations):row.pop('need_id')
    if stripped!=original:raise ValueError('SOURCE_A_COMMAND_VALUES_CHANGED')
    windows,occupancy,reservations=collections_for_context(pack,cdate)
    for day,entry in pack['days'].items():
        off=(dt.date.fromisoformat(day)-dt.date.fromisoformat(cdate)).days*1440
        reservations.extend({'room_id':pack['world']['activity_contract']['room_map']['bath'],'start_min':off+t,'end_min':off+t+10} for t in entry['family']['bath_times_min'].values())
    span=[min(r['start_min'] for rs in a.values() for r in rs),max(r['end_min'] for rs in a.values() for r in rs)]
    steps=[];ev=next((d for d in devices if 'ev' in d['types']),None)
    if ev:
        base=(dt.date.fromisoformat(cdate)-dt.date.fromisoformat(pack['anchor'])).days*1440
        for e in pack['EV_battery_energy_events']:
            if e['kind']!='charge' or e['battery_kWh']<=0:continue
            start,end=e['start_min']-base,e['end_min']-base
            if start<span[0] or end>span[1]:continue
            count=(end-start)//10
            if count<=0 or (end-start)%10:raise ValueError('INVALID_SOURCE_EV_ENERGY_INTERVAL')
            for t in range(start,end,10):
                controls=[r for r in a['controls'] if r['asset_id']==ev['asset_id'] and r['kind']=='ev_charge_window' and r['start_min']<=t and t+10<=r['end_min']]
                if len(controls)!=1:raise ValueError('SOURCE_EV_CHARGE_OUTSIDE_CONNECTION')
                steps.append({'need_id':controls[0]['need_id'],'start_min':t,'end_min':t+10,'grid_kWh':e['battery_kWh']/ev['parameters']['efficiency']/count})
    pack_params=pack['world']['parameter_pack']
    c={'schema':'eb.ab_generation.context.v3','case_id':case['case_id'],'household_id':hid,'date':cdate,
       'decision_min':480,'horizon_min':[480,1920],'A':a,'needs':needs,'devices':devices,
       'operator_windows':windows,'occupancy':occupancy,'reservations':reservations,
       'events':[copy.deepcopy(design()['event'])],'event_meter_scope':'modeled_controlled_equipment',
       'tariff':[{'start_min':480,'end_min':1920,'price_per_kWh':pack['world']['tariff_reference']['flat_CNY_per_kWh']}],
       'tariff_provenance':{'origin':'retained_world_reference_tariff;not_live_or_observed'},
       'authority':authority(pack,windows),'assignment':{'mode':'fresh_candidates'},
       'electrical':{'schema':'eb.ab_site_capacity.v1','supply_W':pack_params['home_service_limit_kw']*1000,
                     'background_upper_W':pack_params['background_reserved_kw']*1000,'capacity_mode':'retained_reference_input_envelope',
                     'scope':'retained_target_meter_reference;not_new_household_electrical_measurement'},
       'source':{**source,'original_A_commands_sha256':digest(original),'EV_lineage_annotations':annotations,
                 'command_values_and_times_changed':False,'EV_energy_profile_scope':'uniform_native_A_charge_event_mean_split_to10min;not_meter_measurement',
                 'program_constraint_origin':'resources.legacy_program_constraints;explicit_inherited_A46_project_rules',
                 'source_B_or_physical_outcomes_used':False}}
    c['reference']={'binding':binding(c),'thermal':{},'ev_charging_steps':steps,
                    'information_set':information_set('offline_unexecuted_A_plan',480,span),
                    'baseline_admission':{'status':'frozen_A46_plan_import;not_new_physical_execution','physical_or_human_validity_inferred':False},
                    'provenance':'original_A46_commands_and_analytic_EV_input_energy;no_B_or_physical_result',
                    'ac_control_contract':copy.deepcopy(AC_CONTRACT)}
    return c


def import_A(source_a,physical_inputs,out):
    from .collection_design import validate_context
    aroot=Path(source_a).resolve();proot=Path(physical_inputs).resolve();out=Path(out).resolve()
    subset=read(aroot/'SUBSET50.json')['records'];homes=read(proot/'INPUT_MANIFEST.json')['records']
    if len(subset)!=50 or len(homes)!=50:raise ValueError('EXACT_REFERENCE50_FRAME_REQUIRED')
    by_id={h['household_id']:h for h in homes};out.mkdir(parents=True,exist_ok=False);records=[]
    save(out/'PRE_IMPORT.json',{'source_A_subset_sha256':sha(aroot/'SUBSET50.json'),
         'source_household_inputs_manifest_sha256':sha(proot/'INPUT_MANIFEST.json'),'households':50,'expected_cases':500,
         'fixed_VPP':[1080,1140],'A_or_dates_changed':False,'B_or_physical_results_read':False,'new_engine_runs':0})
    for entry in subset:
        hid=entry['household_id'];home=by_id[hid];ppath=bound(proot,home['path'])
        if sha(ppath)!=home['sha256']:raise ValueError('HOUSEHOLD_INPUT_HASH_CHANGED')
        pack=read(ppath)
        if pack['source_A_world_sha256']!=entry['A_world_sha256'] or pack['source_annual_A_sha256']!=entry['annual_A_sha256']:raise ValueError('REFERENCE_A_LINEAGE_MISMATCH')
        if len(entry['cases'])!=10:raise ValueError('TEN_ORIGINAL_DATES_REQUIRED')
        for item in entry['cases']:
            path=bound(aroot,item['path'])
            if sha(path)!=item['sha256']:raise ValueError('ORIGINAL_A_CASE_HASH_CHANGED')
            raw=read(path);source={'A_case_sha256':item['sha256'],'household_input_sha256':home['sha256'],
                                 'world_sha256':entry['A_world_sha256'],'annual_A_sha256':entry['annual_A_sha256']}
            c=context(pack,raw,source);validate_context(c);name='contexts/'+raw['case_id']+'.json.gz';save(out/name,c)
            records.append({'household_id':hid,'case_id':raw['case_id'],'date':raw['date'],'path':name,'sha256':sha(out/name),'source':source})
        print('已导入原50户A '+hid,flush=True)
    save(out/'BATCH.json',{'schema':'eb.reference50.offline_A_contexts.v1','records':records,'households':50,'cases':len(records)})
    seal(out,{'schema':'eb.reference50.offline_A_contexts.v1','code_sha256':code_hash(),'new_engine_runs':0,'source_B_or_physical_outcomes_used':False})
    return {'households':50,'cases':len(records),'new_engine_runs':0}


def _generate_case(job):
    from .collection_candidates import generate_day
    source,target,item,config=job
    source=Path(source);target=Path(target);c=read(bound(source,item['path']))
    result=generate_day(c,config)
    save(target/'catalogues'/(c['case_id']+'.json.gz'),result)
    return {'household_id':c['household_id'],'date':c['date'],
            **{k:v for k,v in result.items() if k not in ('rows','quarantined_requests','engineering_diagnostics','relevance_diagnostics','control_record')},
            'quarantine_count':len(result['quarantined_requests']),
            'quarantine_reasons':dict(__import__('collections').Counter(i for r in result['quarantined_requests'] for i in r['gate_issues']))}


def generate_catalogue(context_root,out,workers=4):
    import shutil
    from concurrent.futures import ProcessPoolExecutor,as_completed
    source=Path(context_root).resolve();out=Path(out).resolve();verify(source)
    batch=read(source/'BATCH.json');records=batch['records'];code=code_hash()
    if len(records)!=500 or batch['households']!=50:raise ValueError('EXACT_REFERENCE50_FRAME_REQUIRED')
    config=design({'households':sorted({r['household_id'] for r in records}),'ac_axes':['cooling','heating'],'solver_node_limit':400})
    out.mkdir(parents=True,exist_ok=False);shutil.copytree(source/'contexts',out/'contexts')
    save(out/'DESIGN.json',config);save(out/'SOURCE_A_FRAME.json',batch)
    save(out/'PRE_GENERATION.json',{'schema':'eb.reference50.pre_generation.v4','source_contexts_manifest_sha256':sha(source/'MANIFEST.json'),
         'code_sha256':code,'selection_policy':'eb.collection.selection_policy.v4','source_B_or_physical_outcomes_used':False,
         'future_A_scope':'complete_imported_original_case_A_and_analytic_EV_plan;not_future_thermal_state',
         'new_engine_runs':0,'online_questionnaire_changed':False,'master1000_started':False,
         'declared_limitation':'heating_event_requests_supported;heating_preconditioning_not_encoded_in_cooling_fallback_contract'})
    save(out/'HOUSEHOLDS.json',[{'household_id':h,'evidence_kind':'inherited_original_reference50;not_new_population_sample'} for h in config['households']])
    daily=[];errors=[]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        jobs={pool.submit(_generate_case,(str(source),str(out),item,config)):item for item in records}
        for future in as_completed(jobs):
            item=jobs[future]
            try:daily.append(future.result());print('新版B目录 '+str(len(daily))+'/500 '+item['case_id'],flush=True)
            except Exception as e:
                errors.append({'case_id':item['case_id'],'error':type(e).__name__+':'+str(e),'A_changed':False,'rerolled':False})
                save(out/'ENGINEERING_IMPORT_FAILURES.json',errors);print('诊断保留 '+item['case_id']+' '+str(e),flush=True)
    if errors:raise ValueError('REFERENCE50_CASE_FAILURES_RETAINED:'+str(len(errors)))
    daily.sort(key=lambda x:(x['household_id'],x['date']));save(out/'GENERATION.json',daily)
    source_life={r['household_id']:r['source']['annual_A_sha256'] for r in records}
    save(out/'REVIEW.json',{'source_life_payloads':source_life,'scope':'preselection_A_source_identity;not_selected_B_review'})
    if code_hash()!=code:raise ValueError('CODE_CHANGED_DURING_REFERENCE50_GENERATION')
    seal(out,{'schema':'eb.reference50.frozen_request_catalogue.v4','code_sha256':code,'cases':len(daily),'new_engine_runs':0})
    return {'cases':len(daily),'households':50,'new_engine_runs':0,'catalogue_frozen':True}


if __name__=='__main__':
    import json
    p=argparse.ArgumentParser();p.add_argument('--source-a');p.add_argument('--physical-inputs');p.add_argument('--contexts');p.add_argument('--workers',type=int,default=4);p.add_argument('--out',required=True);args=p.parse_args()
    if args.contexts:result=generate_catalogue(args.contexts,args.out,args.workers)
    elif args.source_a and args.physical_inputs:result=import_A(args.source_a,args.physical_inputs,args.out)
    else:p.error('supply --contexts, or both --source-a and --physical-inputs')
    print(json.dumps(result,ensure_ascii=False))
