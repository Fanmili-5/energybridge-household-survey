"""Preserve every prior ledger, add emitted actor IDs, prove unchanged IDFs."""
import os,shutil,subprocess
from common import *
from produce_static import compile_all,command
from prepare_sensitivity import main as prepare50

def main():
    school_guard();archive=OUT/'development/before_explicit_external_bindings';assert not archive.exists();archive.mkdir(parents=True)
    old={name:read(OUT/name)['records']for name in('COMPILED1000.json','COMPILED_SENSITIVITY50.json')}
    for name in list(old)+['PHYSICS_original50_REVIEW.json','PHYSICS_other950_REVIEW.json','PRE_EP_original50.json','PRE_EP_other950.json','EP_original50_RUNS.json','EP_other950_RUNS.json']:
        if(OUT/name).exists():shutil.copy2(OUT/name,archive/name)
    for p in(OUT/'input_ledgers').rglob('*.json'):
        q=archive/p.relative_to(OUT);q.parent.mkdir(parents=True,exist_ok=True);os.link(p,q)
    compile_all();prepare50()
    unchanged=0
    for name,previous in old.items():
        current=read(OUT/name)['records'];assert len(previous)==len(current)
        for a,b in zip(previous,current):
            assert(a['household_id'],a['round_index'],a['variant'])==(b['household_id'],b['round_index'],b['variant'])
            for side in('A','B'):
                assert all(a[side][k]==b[side][k]for k in('IDF_sha256','native_IDF_sha256','schedule_signal_sha256'))
                before=read(archive/a[side]['signal_ledger_path']);after=read(OUT/b[side]['signal_ledger_path']);derived=after['spatial'].pop('external_occupancy_SQL_bindings')
                assert before==after and set(derived)==set(before['spatial']['external_occupancy'])
                unchanged+=1
    current=read(OUT/'COMPILED1000.json')['records'];oldweather=read(OUT/'COMPILED_WEATHER_SENSITIVITY.json');lookup={(c['household_id'],c['round_index']):c for c in current}
    for c in oldweather['records']:
        for side in('A','B'):c[side]=lookup[c['household_id'],c['round_index']][side]
    save(OUT/'COMPILED_WEATHER_SENSITIVITY.json',oldweather)
    for module in ['audit_idfs.py','mechanism_controls.py','vehicle_causal_controls.py','audit_reference_model.py','audit_physical_inputs.py','structural_zero_controls.py']:command(module)
    save(OUT/'EXTERNAL_SQL_BINDING_REVIEW.json',{'status':'pass','IDF_sides_proved_unchanged':unchanged,'same_physics_all_households':True,
        'only_ledger_change':'explicit external actor to actually emitted SQL schedule name map','previous_ledgers_preserved_by_atomic_replacement_and_hardlinks':True,
        'every_external_actor_schedule_verified_during_readback':True,'households_dates_types_hardware_AB_unchanged':True,'EP_started':0})
    print({'external_SQL_binding_repair':'pass','unchanged_IDF_sides':unchanged,'fresh_cohort_review_required':True},flush=True)

if __name__=='__main__':main()
