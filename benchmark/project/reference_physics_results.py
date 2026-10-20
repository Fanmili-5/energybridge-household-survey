"""Read paired physics into a version-bound, complete 500-case result ledger.

Keep unrun/unsupported/failed rows as null. This sidecar never edits an already
sealed questionnaire or retrospectively changes a respondent's information.
"""
import argparse
import json
import re
from collections import Counter
from pathlib import Path
from benchmark.ab_generation.common import read, save, sha, verify, seal
from benchmark.ab_generation.outcomes import consequences
from benchmark.ab_generation.model import plan_hash


def integrity_failures(check):
    """Engineering readback invariants; service/comfort failures remain outcomes."""
    critical={'same_channel_set','pre_notice_trajectory_equal','shared_shell_weather','readback_complete'}
    endings=('_complete_finite_timeline','_required_zone_channels','_required_tank_nodes','_meter_closure','_program_energy','_EV_meter')
    return [k for k,v in check['checks'].items() if not v and (k in critical or k.endswith(endings))]


def native_numerical_failures(error_text):
    """A normal process exit does not certify the internal iterative solution.

    Gate explicit nonconvergence/severe/fatal messages across the supplied
    history, main day and recovery. Range warnings from intermediate wet-bulb
    iteration guesses alone remain disclosed warnings, not an invented failure.
    """
    patterns={'wetbulb_iteration_not_converged':r'WetBulb not converged',
              'native_severe_error':r'\*\*\s+Severe\s+\*\*',
              'native_fatal_error':r'\*\*\s+Fatal\s+\*\*'}
    return [name for name,pattern in patterns.items() if re.search(pattern,error_text,re.I)]


def mixed_water_delivery(meta,trace,lo=480,hi=1920):
    """Native aggregate mixed outlet; no invented individual allocation/pass label."""
    if not meta.get('tank_name') or meta.get('hot_water_model')!='native_mixed_water_plant':return None
    volumes={k.split('|',1)[1]:c for k,c in trace.items() if k.startswith('Water Use Equipment Total Volume|')}
    temperatures={k.split('|',1)[1]:c for k,c in trace.items() if k.startswith('Water Use Equipment Mixed Water Temperature|')}
    if not volumes or set(volumes)!=set(temperatures):return {'status':'unavailable','reason':'native outlet channels missing'}
    if any(c['unit']!='m3'or c.get('native_aggregation')!='Sum' for c in volumes.values()) or any(c['unit']!='C' for c in temperatures.values()):return {'status':'unavailable','reason':'native volume aggregation/units not verified'}
    needs=[n for n in meta['water_needs'] if n['release_min']<hi and n['deadline_min']>lo]
    requested=sum(n['quantity']*max(0,min(hi,n['deadline_min'])-max(lo,n['release_min']))/(n['deadline_min']-n['release_min']) for n in needs)
    targets=sorted({n.get('target_C',n.get('minimum_C')) for n in needs if n.get('target_C',n.get('minimum_C'))is not None})
    total=weighted=0.;active=[]
    for key,c in volumes.items():
        v=dict(c['values']);temp=dict(temperatures[key]['values'])
        if not all(t in v and t in temp for t in range(lo,hi,10)):return {'status':'unavailable','reason':'incomplete outlet timeline'}
        for t in range(lo,hi,10):
            if v[t]<0:return {'status':'unavailable','reason':'negative native outlet volume'}
            total+=v[t];weighted+=v[t]*temp[t]
            if v[t]>0:active.append(temp[t])
    return {'status':'computed','interval_min':[lo,hi],'requested_mixed_liters':requested,'delivered_mixed_liters':total*1000,
        'declared_target_C':targets,'volume_weighted_reported_temperature_C':weighted/total if total>0 else None,
        'minimum_active_10min_mean_C':min(active)if active else None,
        'scope':'whole_modeled_dwelling_mixed_outlet;10min_report;no_individual_allocation_or_personal_comfort_inference',
        'service_pass_inferred':False}


def bind(collection, exported, compiled, runs, audit, out):
    collection,exported,compiled,runs,audit,out=map(lambda p:Path(p).resolve(),(collection,exported,compiled,runs,audit,out))
    verify(collection);em=verify(exported);cm=verify(compiled);rm=verify(runs);am=verify(audit)
    if em['selection_sha256']!=sha(collection/'ASSIGNMENT.json'):raise ValueError('RESULT_SELECTION_MISMATCH')
    if rm['compiled_manifest_sha256']!=sha(compiled/'MANIFEST.json') or am['runs_manifest_sha256']!=sha(runs/'MANIFEST.json') or am['compiled_manifest_sha256']!=sha(compiled/'MANIFEST.json'):raise ValueError('RESULT_RUN_AUDIT_MISMATCH')
    cases=read(exported/'INPUT_REVIEW500.json')['records'];compiled_rows={r['id']:r for r in cm['records']};audits={r['id']:r for r in am['records']}
    if not set(compiled_rows)<={r['id'] for r in cases}:raise ValueError('UNKNOWN_COMPILED_COLLECTION_CASE')
    rows=[]
    for item in cases:
        ident=item['id'];row={**item,'actual_outcomes':None,'questionnaire_payload_changed':False}
        frozen_path=collection/'pairs'/(ident+'.json');frozen=read(frozen_path)
        if sha(frozen_path)!=item['source_frozen_pair_sha256']:raise ValueError('RESULT_FROZEN_PLAN_CHANGED')
        if any(item[s+'_commands_sha256']!=frozen['review'][s+'_commands_sha256'] for s in ('A','B')):raise ValueError('RESULT_COLLECTION_COMMAND_HASH_MISMATCH')
        if item['status']=='unsupported_world':rows.append(row);continue
        if ident not in compiled_rows:
            row['status']='not_computed';rows.append(row);continue
        if compiled_rows[ident]['status']!='compiled':
            row.update(status='compile_failed',reason='See preserved compiler log');rows.append(row);continue
        if compiled_rows[ident]['pair_sha256']!=item['pair']['sha256'] or compiled_rows[ident]['household_sha256']!=item['household']['sha256']:raise ValueError('RESULT_COMPILED_INPUT_MISMATCH')
        paths={s:runs/ident/s/'RESULT.json' for s in ('A','B')}
        if not all(p.exists() for p in paths.values()):
            row.update(status='incomplete_pair',reason='Both A and B receipts are required');rows.append(row);continue
        results={s:read(p) for s,p in paths.items()}
        if any(r['status']!='completed' for r in results.values()):
            row.update(status='execution_failed',reason='Preserved engine failure;no replacement B');rows.append(row);continue
        pair_path=exported/'resources'/item['pair']['path']
        if sha(pair_path)!=item['pair']['sha256']:raise ValueError('RESULT_EXPORTED_PAIR_CHANGED')
        pair=read(pair_path);metas={s:read(compiled/ident/s/'INPUT.json.gz') for s in ('A','B')}
        if any(plan_hash(pair[s])!=plan_hash(frozen[s]) for s in ('A','B')):raise ValueError('RESULT_EXECUTED_PLAN_DIFFERS_FROM_FROZEN_COLLECTION')
        traces={}
        for side in ('A','B'):
            result=results[side];meta=metas[side];trace_path=runs/ident/side/'TRACE.json.gz';sql=runs/ident/side/'out/eplusout.sql'
            if meta['source_pair_sha256']!=pair['source_pair_sha256'] or meta['source_schedule_hash']!=pair['schedule_hashes'][side] or result['idf_sha256']!=meta['idf_sha256'] or result['trace_sha256']!=sha(trace_path) or result['SQL_sha256']!=sha(sql):raise ValueError('RESULT_ARM_BINDING_MISMATCH')
            traces[side]=read(trace_path)
        check=audits.get(ident)
        if check is None:
            row.update(status='audit_missing',reason='No complete paired audit;outcomes remain null');rows.append(row);continue
        numerical={s:{'failures':native_numerical_failures((runs/ident/s/'out/eplusout.err').read_text(errors='replace')),
                      'error_log_sha256':sha(runs/ident/s/'out/eplusout.err')} for s in ('A','B')}
        row.update(audit_status=check['status'],
            failed_checks=[k for k,v in check['checks'].items() if not v],
            native_numerical_convergence={'passed':not any(v['failures']for v in numerical.values()),'arms':numerical,
                'scope':'entire_supplied_history_primary_day_and_recovery;conservative_admission_not_a_claim_that_all_times_are_corrupt'},
            engine_warnings={s:results[s].get('warnings',[]) for s in ('A','B')},
            model_scope={s:{k:metas[s].get(k) for k in ('history_days','simulation_timestep_min','reference_air_changes_per_hour','multi_AC_execution','air_exchange_scope')} for s in ('A','B')},
            engine_runs=2,IDFs_compiled=True,
            receipts={s:{k:results[s][k] for k in ('engine_sha256','idf_sha256','SQL_sha256','trace_sha256')} for s in ('A','B')})
        if not row['native_numerical_convergence']['passed']:
            row['failed_checks'] += [s+'_native_numerical_convergence'for s in ('A','B')if numerical[s]['failures']]
            row.update(status='audit_failed',reason='Native internal solver reported nonconvergence/severe/fatal error despite process completion;paired consequences remain unknown;original SQL and diagnostic estimates preserved without rerun or reselection')
            rows.append(row);continue
        if integrity_failures(check):
            row.update(status='audit_failed',reason='Paired engineering integrity check failed;diagnostic results preserved without presenting them as reliable outcomes',
                failed_checks=integrity_failures(check),audit_status=check['status'],engine_runs=2,IDFs_compiled=True)
            rows.append(row);continue
        context=read(collection/'contexts'/(frozen['row']['case_id']+'.json.gz'))
        home=read(exported/'resources'/item['household']['path'])
        rate=home['world']['tariff_reference']['flat_CNY_per_kWh']
        if context['tariff_provenance']['origin']=='retained_world_reference_tariff;not_live_or_observed' and all(t['price_per_kWh']==rate for t in context['tariff']):
            context={**context,'tariff_provenance':{**context['tariff_provenance'],'currency':'CNY','unit':'CNY/kWh'}}
        actual=consequences(pair,metas,traces,check,context)
        actual['native_mixed_water_delivery']={s:mixed_water_delivery(metas[s],traces[s]) for s in ('A','B')}
        row.update(status='computed',actual_outcomes=actual,
            audit_status=check['status'],failed_checks=[k for k,v in check['checks'].items() if not v],
            engine_warnings={s:results[s].get('warnings',[]) for s in ('A','B')},
            model_scope={s:{k:metas[s].get(k) for k in ('history_days','simulation_timestep_min','reference_air_changes_per_hour','multi_AC_execution','air_exchange_scope')} for s in ('A','B')},
            engine_runs=2,IDFs_compiled=True,
            receipts={s:{k:results[s][k] for k in ('engine_sha256','idf_sha256','SQL_sha256','trace_sha256')} for s in ('A','B')})
        rows.append(row)
    out.mkdir(parents=True,exist_ok=False)
    summary={'cases':len(rows),'statuses':dict(Counter(r['status'] for r in rows)),
        'engine_arms_in_this_bound_run':sum('side'in r for r in rm['records']),'collection_answers_or_payloads_changed':False,
        'old_B_results_used':False,'reselection_after_results':False,'full1000_deferred':True}
    save(out/'RESULT_INDEX500.json',{'schema':'eb.reference50.bound_physics_results.v1',**summary,'records':rows})
    seal(out,{'schema':'eb.reference50.bound_physics_results.v1','source_selection_sha256':sha(collection/'ASSIGNMENT.json'),
        'export_manifest_sha256':sha(exported/'MANIFEST.json'),'compiled_manifest_sha256':sha(compiled/'MANIFEST.json'),
        'runs_manifest_sha256':sha(runs/'MANIFEST.json'),'audit_manifest_sha256':sha(audit/'MANIFEST.json'),
        'readback_code_sha256':sha(Path(__file__))})
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('collection','exported','compiled','runs','audit','out'):p.add_argument('--'+name,required=True)
    a=p.parse_args();print(json.dumps(bind(a.collection,a.exported,a.compiled,a.runs,a.audit,a.out),ensure_ascii=False))
