"""Read-only frozen hardware/plan/IDF/gate audit; no engine or selection calls."""
import argparse
import json
from pathlib import Path
from benchmark.ab_generation.common import read,save,sha,verify
from benchmark.housing_simulation.kernel.core_tools import parse_idf


def check(exported,compiled,runs,out):
    exported,compiled,runs,out=map(lambda p:Path(p).resolve(),(exported,compiled,runs,out))
    verify(exported);cm=verify(compiled);verify(runs)
    entries=read(exported/'INPUT_REVIEW500.json')['records'];rows={r['id']:r for r in cm['records']}
    fields=read(exported/'resources/inputs/schema_fields.json.gz');multi=0;arms=0;different_gates=0
    for entry in entries:
        pack=read(exported/'resources'/entry['household']['path']);pair=read(exported/'resources'/entry['pair']['path']);rid=entry['id']
        if rows[rid]['status']!='compiled':continue
        for side in ('A','B'):
            source=compiled/rid/side;meta=read(source/'INPUT.json.gz');idf=parse_idf((source/'model.idf').read_text())
            by={(r[0],r[1]):r for r in idf if len(r)>1}
            if meta['source_schedule_hash']!=pair['schedule_hashes'][side]:raise ValueError('COMPILED_PLAN_CHANGED')
            if sorted(r[1] for r in idf if r[0]=='Zone')!=sorted(r['room_id']for r in pack['world']['layout']['rooms']):raise ValueError('ROOM_ADDED_OR_REMOVED')
            gates={d['asset_id']:d['coil_gate_schedules'] for room in meta['multi_AC_execution'] for d in room['devices']}
            for package in pack['HVAC']:
                for expected in package['rows']:
                    actual=by[(expected[0],expected[1])];wanted=list(map(str,expected))
                    if package['asset_id'] in gates and expected[0].startswith(('Coil:Heating:','Coil:Cooling:')):
                        key='heating'if expected[0].startswith('Coil:Heating:')else'cooling'
                        wanted[fields[expected[0]].index('availability_schedule_name')+1]=gates[package['asset_id']][key]
                    if actual!=wanted:raise ValueError('NATIVE_HARDWARE_OR_CURVE_CHANGED:'+package['asset_id'])
            result=read(runs/rid/side/'RESULT.json')
            if gates and result['status']=='completed':
                trace=read(runs/rid/side/'TRACE.json.gz');names=[n for g in gates.values()for n in g.values()]
                if len(names)!=len(set(names)):raise ValueError('GATES_SHARED_ACROSS_UNITS')
                for name in names:
                    values=trace['Schedule Value|'+name.upper()]['values']
                    if not values or any(not 0<=v<=1 for t,v in values):raise ValueError('GATE_READBACK_INVALID')
                for room in meta['multi_AC_execution']:
                    for key in ('heating','cooling'):
                        a,b=[trace['Schedule Value|'+d['coil_gate_schedules'][key].upper()]['values'] for d in room['devices'][:2]]
                        different_gates+=int(any(abs(x[1]-y[1])>1e-8 for x,y in zip(a,b)))
                multi+=1
            arms+=1
    summary={'schema':'eb.reference50.physics_input_selfcheck.v1','cases':len(entries),'compiled_arms_checked':arms,
        'multi_AC_completed_arms_with_individual_gate_readback':multi,'independent_gate_pairs_observed_different':different_gates,
        'all_original_native_hardware_parameters_and_curves_preserved':True,'all_original_physical_rooms_preserved':True,
        'source_schedule_hashes_unchanged':True,'only_native_coil_availability_fields_derived_for_multi_AC':True,
        'source_export_manifest_sha256':sha(exported/'MANIFEST.json'),'compiled_manifest_sha256':sha(compiled/'MANIFEST.json'),
        'runs_manifest_sha256':sha(runs/'MANIFEST.json'),'engine_runs_started':0,'selections_changed':0}
    save(out,summary);return summary


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('exported','compiled','runs','out'):p.add_argument('--'+name,required=True)
    a=p.parse_args();print(json.dumps(check(a.exported,a.compiled,a.runs,a.out),ensure_ascii=False))
