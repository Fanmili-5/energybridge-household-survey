"""Frozen new-collection A/B -> paired housing-physics input jobs.

No reselection, outcome filtering or old-B read. Unsupported input worlds stay
in the complete 500-row ledger with their original requests and a reason.
"""
import argparse
import copy
import datetime as dt
import json
import shutil
from collections import Counter
from pathlib import Path
from benchmark.ab_generation.common import bound, digest, read, save, seal, sha, verify
from benchmark.ab_generation.model import plan_commands, plan_hash
from benchmark.ab_generation.sampling import command_hash
from benchmark.ab_generation.export import attach_legacy_requirements


def initial_ev(pack, annual, date):
    device=next((d for d in pack['world']['parameter_pack']['devices'] if 'ev' in d['types']),None)
    if device is None:return {'status':'not_installed'}
    p=device['parameters'];decision=(dt.date.fromisoformat(date)-dt.date.fromisoformat(pack['anchor'])).days*1440+480
    energy=annual['initial_states']['EV_SOC']*p['capacity_kwh']
    for e in annual['EV_battery_energy_events']:
        if e['kind']=='traction':
            if e['start_min']<decision:energy+=e['battery_kWh']
        elif e['kind']=='charge':
            energy+=e['battery_kWh']*max(0,min(1,(decision-e['start_min'])/(e['end_min']-e['start_min'])))
        else:raise ValueError('UNKNOWN_A_BATTERY_EVENT')
    if not -1e-7<=energy<=p['capacity_kwh']+1e-7:raise ValueError('INVALID_A_DECISION_ENERGY')
    return {'status':'installed','asset_id':device['asset_id'],'initial_energy_kWh':energy,
        'capacity_kWh':p['capacity_kwh'],'charger_kW':p['charger_kw'],'efficiency':p['efficiency'],
        'target_SOC':p['target_soc'],'minimum_SOC':p['min_soc'],
        'initial_state_basis':'integrated original annual A ledger immediately before 08:00;not an old B outcome'}


def export(collection, stage, original_a, out):
    collection,stage,original_a,out=map(lambda p:Path(p).resolve(),(collection,stage,original_a,out))
    verify(collection);assignment=read(collection/'ASSIGNMENT.json')
    if assignment['schema']!='eb.collection.assignment.v4' or len(assignment['selected_ids'])!=500:raise ValueError('EXACT_FROZEN_NEW_500_REQUIRED')
    homes={r['household_id']:r for r in read(stage/'INPUT_MANIFEST.json')['records']}
    originals={r['household_id']:r for r in read(original_a/'SUBSET50.json')['records']}
    if set(homes)!=set(originals) or len(homes)!=50:raise ValueError('REFERENCE50_FRAME_MISMATCH')
    out.mkdir(parents=True,exist_ok=False);resources=out/'resources';fixed={}
    for name in ('inputs/schema_fields.json.gz','inputs/native_rows.json.gz','THERMAL_ENVIRONMENT_POLICY.json'):
        destination=resources/name;destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(bound(stage,name),destination);fixed[name]=sha(destination)
    cache={};groups={};records=[]
    for ident in assignment['selected_ids']:
        frozen_path=collection/'pairs'/(ident+'.json');frozen=read(frozen_path);row=frozen['row'];hid=row['household_id'];date=row['date']
        context=read(collection/'contexts'/(row['case_id']+'.json.gz'))
        if plan_hash(frozen['A'])!=plan_hash(context['A']) or row['engineering_issues']:raise ValueError('FROZEN_A_OR_ENGINEERING_ADMISSION_CHANGED')
        if hid not in cache:
            h=homes[hid];source=bound(stage,h['path'])
            if sha(source)!=h['sha256'] or h['sha256']!=context['source']['household_input_sha256']:raise ValueError('HOUSEHOLD_INPUT_CHANGED')
            entry=originals[hid];annual_path=bound(original_a,entry['annual_A_path'])
            if sha(annual_path)!=entry['annual_A_sha256']:raise ValueError('ANNUAL_A_CHANGED')
            annual=read(annual_path);pack=attach_legacy_requirements(read(source),annual_path)
            home_path='inputs/homes/'+hid+'.json.gz';save(resources/home_path,pack)
            weather=bound(stage,pack['weather']);destination=resources/pack['weather'];destination.parent.mkdir(parents=True,exist_ok=True)
            if sha(weather)!=pack['weather_sha256']:raise ValueError('WEATHER_CHANGED')
            if not destination.exists():shutil.copyfile(weather,destination)
            fixed[pack['weather']]=pack['weather_sha256']
            zones=[d['room_id'] for d in pack['world']['parameter_pack']['devices'] if 'ac' in d['types']]
            unsupported='MULTIPLE_INDEPENDENT_AC_IN_ONE_ZONE_UNSUPPORTED' if len(zones)!=len(set(zones)) else None
            cache[hid]=(pack,annual,home_path,unsupported)
        pack,annual,home_path,unsupported=cache[hid]
        raw_case=next(r for r in originals[hid]['cases'] if r['date']==date);raw_path=bound(original_a,raw_case['path'])
        if sha(raw_path)!=context['source']['A_case_sha256']:raise ValueError('ORIGINAL_A_CASE_CHANGED')
        original=read(raw_path)['A'];check=plan_commands(frozen['A'])
        for r in check['controls']:
            if any(r['asset_id']==n['asset_id'] and r['start_min']==n['start_min'] and r['end_min']==n['end_min'] for n in context['source']['EV_lineage_annotations']):r.pop('need_id')
        if check!=plan_commands(original):raise ValueError('ORIGINAL_A_COMMANDS_CHANGED')
        pair={'case_id':row['case_id']+'__v4__'+ident[:16],'household_id':hid,'date':date,'decision_min':480,
            'A':plan_commands(frozen['A']),'B':plan_commands(frozen['B']),
            'needs_A':copy.deepcopy(context['needs']),'needs_B':copy.deepcopy(context['needs']),
            'VPP_events':copy.deepcopy(context['events']),'EV_continuous_reference':initial_ev(pack,annual,date),
            'primary_evaluation_min':[480,1920],
            'AB_generation':{'source_frozen_pair_sha256':sha(frozen_path),'selection_sha256':sha(collection/'ASSIGNMENT.json'),
                'event_meter_scope':context['event_meter_scope'],'retained_plan_issues':row['issues'],
                'old_B_outcomes_read':False,'physical_results_used_to_reselect':False}}
        pair['schedule_hashes']={s:digest(pair[s]) for s in ('A','B')};pair['source_pair_sha256']=digest(pair)
        pname='inputs/pairs/'+ident+'.json.gz';save(resources/pname,pair)
        history=min(112,(dt.date.fromisoformat(date)-dt.date.fromisoformat(pack['anchor'])).days)
        tail=9
        entry={'id':ident,'case_id':pair['case_id'],'household':{'path':home_path,'sha256':sha(resources/home_path)},
            'pair':{'path':pname,'sha256':sha(resources/pname)}}
        reason=unsupported
        if dt.date.fromisoformat(date)+dt.timedelta(days=tail)>dt.date.fromisoformat(pack['end_exclusive']):reason='INSUFFICIENT_FROZEN_RECOVERY_CALENDAR'
        record={**entry,'household_id':hid,'date':date,'source_frozen_pair_sha256':sha(frozen_path),
            'A_commands_sha256':command_hash(pair['A']),'B_commands_sha256':command_hash(pair['B']),
            'A_execution_plan_sha256':plan_hash(pair['A']),'B_execution_plan_sha256':plan_hash(pair['B']),
            'history_days':history,'tail_days':tail,'history_scope':'explicit available original A calendar capped at112days;shorter histories not newly convergence-validated',
            'status':'unsupported_world' if reason else 'input_prepared','reason':reason,'retained_plan_issues':row['issues'],
            'actual_outcomes':None,'IDFs_compiled':False,'engine_runs':0}
        records.append(record)
        if reason is None:groups.setdefault((history,tail),[]).append(entry)
    jobs=[]
    for (history,tail),entries in sorted(groups.items()):
        name=f'physics_job_history_{history}_tail_{tail}.json'
        save(out/name,{'schema':'eb.housing_physics.input.v1','resource_root':'resources','resources':fixed,
            'settings':{'history_days':history,'tail_days':tail,'reference_ach':.35,'portal_flow_scale':1.,'simulation_timestep_min':5,'airflow_model':'reference_mixing'},'pairs':entries});jobs.append(name)
    save(out/'JOBS.json',{'jobs':jobs,'automatic_execution':False,'no_replacement_of_unsupported_requests':True})
    review={'schema':'eb.reference50.frozen_collection_physics_input.v1','cases':len(records),'households':len(cache),
        'statuses':dict(Counter(r['status'] for r in records)),'reasons':dict(Counter(r['reason'] for r in records if r['reason'])),
        'physics_jobs':jobs,'records':records,'new_EP_runs':0,'old_B_outcomes_read':False,'full1000_deferred':True}
    save(out/'INPUT_REVIEW500.json',review)
    seal(out,{'schema':review['schema'],'selection_sha256':sha(collection/'ASSIGNMENT.json'),
        'source_input_manifest_sha256':sha(stage/'INPUT_MANIFEST.json'),'new_EP_runs':0,'actual_outcomes':None})
    return {k:v for k,v in review.items() if k not in ('records','physics_jobs')}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--collection',required=True);p.add_argument('--stage',required=True);p.add_argument('--original-a',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();print(json.dumps(export(a.collection,a.stage,a.original_a,a.out),ensure_ascii=False))
