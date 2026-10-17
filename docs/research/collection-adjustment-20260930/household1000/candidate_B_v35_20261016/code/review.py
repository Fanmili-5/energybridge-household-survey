"""Independent readback: lineage, actual commands, retained failures, subset parity."""
import collections
from common import *
from assess import assess,integrity

def independent_signals(p):
    for aid,signal in p['HVAC_signals_B'].items():
        if set(map(len,signal.values()))!={576}:return False
        commands=[x for x in p['B']['controls']if x['kind']=='ac_setpoint'and x['asset_id']==aid]
        for i in range(576):
            t=-1440+i*10;active=[x for x in commands if x['start_min']<=t<x['end_min']]
            if len(active)>1:return False
            c=active[0]if active else None
            expected={'available':int(c is not None),'fan_mode':int(c is not None),'heat_sp':c['heating_setpoint_C']if c else 5.,'cool_sp':c['cooling_setpoint_C']if c else 50.}
            if any(signal[k][i]!=v for k,v in expected.items()):return False
    return True

def controls(w,c):
    results=[]
    def test(name,edit,predicate):
        plan=copy.deepcopy(c['A']);edit(plan);result=assess(w,c,plan);results.append({'name':name,'rejected_or_flagged':predicate(result)})
    def fake(p):p['operations'].append({**p['operations'][0],'operation_id':'fake','kind':'EV_plug','need_id':'invented_service'})
    # This structural corruption is checked without attempting execution.
    p=copy.deepcopy(c['A']);fake(p);results.append({'name':'extra_plug_without_service','rejected_or_flagged':bool(integrity(w,c,p))})
    def past(p):
        x=next(x for x in p['controls']if x['start_min']<480);x['start_min']-=10
    test('change_common_past',past,lambda x:'PREDECISION_HISTORY_CHANGED'in x['integrity_errors'])
    if any(x['kind']=='dryer'for x in c['A']['tasks']):
        p=copy.deepcopy(c['A']);next(x for x in p['tasks']if x['kind']=='dryer')['start_min']+=10
        results.append({'name':'broken_wash_dry_dependency','rejected_or_flagged':'BROKEN_AUTOMATIC_WASH_DRY_CHAIN'in integrity(w,c,p)})
    ev=next((x for x in c['A']['controls']if x['kind']=='ev_charge_window'and x['start_min']>=480 and not x.get('automatic_segment_count')),None)
    if ev:
        def empty_charge(p):
            x=next(x for x in p['controls']if x==ev);x['end_min']=x['start_min']+10;x['actual_charge_end_min']=x['end_min'];x['last_step_power_fraction']=1.
        test('real_connection_insufficient_energy_is_kept',empty_charge,lambda x:not x['integrity_errors']and any(f['code']=='EV_TARGET_ENERGY_IMPOSSIBLE_IN_WINDOW'for f in x['constraint_flags']))
    return results

def main():
    verify_inputs();b=read(OUT/'PAIR_BINDINGS10000.json');sig=rules_id();fail=[];counts=collections.Counter();intensities=collections.Counter();cross=collections.Counter();flags=collections.Counter();types=collections.defaultdict(collections.Counter)
    lookup={r['household_id']:r for r in read(A_STAGE/'A_BINDINGS10000.json')['records']};cases=0;feasible=0;fallback=0;negative=[];deltas=collections.Counter()
    for ix,row in enumerate(b['records']):
        src=lookup[row['household_id']];w=read(A_STAGE/src['A_world_path'])
        if row['A_record_sha256']!=digest(src):fail.append([row['household_id'],'A_RECORD_CHANGED'])
        sourcecases={x['case_id']:x for x in src['cases']}
        if set(sourcecases)!={x['case_id']for x in row['rounds']}:fail.append([row['household_id'],'DATES_CHANGED'])
        for r in row['rounds']:
            path=OUT/r['path'];p=read(path);c=read(A_STAGE/sourcecases[r['case_id']]['path']);cases+=1
            if sha(path)!=r['sha256']or sha(A_STAGE/sourcecases[r['case_id']]['path'])!=sourcecases[r['case_id']]['sha256']:fail.append([p['case_id'],'PAIR_OR_SOURCE_BYTES_CHANGED'])
            content=copy.deepcopy(p);claimed=content.pop('pair_content_sha256')
            if claimed!=digest(content):fail.append([p['case_id'],'PAIR_CONTENT_CHANGED'])
            if p['A']!=c['A']or p['A_frozen_sha256']!=digest(c['A'])or p['needs_A']!=c['needs_A']or p['needs_B']!=c['needs_A']or p['days']!=c['days']:fail.append([p['case_id'],'FAMILY_NEEDS_OR_A_CHANGED'])
            if p['A_source']['case_sha256']!=sourcecases[r['case_id']]['sha256']or p['source_world_content_sha256']!=w['world_content_sha256']or p['parameter_pack_sha256']!=w['parameter_pack_sha256']:fail.append([p['case_id'],'SOURCE_BINDING'])
            a=assess(w,c,p['A']);z=assess(w,c,p['B'])
            if a!=p['assessment_A']or z!=p['assessment_B']or a['constraint_flags']or a['integrity_errors']or z['integrity_errors']:fail.append([p['case_id'],'ASSESSMENT_MISMATCH'])
            if not independent_signals(p):fail.append([p['case_id'],'B_SIGNAL_NOT_REQUEST'])
            if p['HVAC_signals_A']!=c['HVAC_signals']or p['human_response']!={'accepted':None,'scores':None,'reason':None}or p['physical_results']is not None or p['selection_or_regeneration_based_on_B_outcome']:fail.append([p['case_id'],'FABRICATED_LABEL_RESULT_OR_FILTER'])
            proposal=p['proposal'];m=proposal['realized_mechanism'];l=proposal['intensity_design'];counts[m]+=1;intensities[l]+=1;cross[(m,l)]+=1;types[row['type']][m]+=1
            flags.update(set(f['code']for f in z['constraint_flags']));feasible+=z['given_constraints_feasible'];fallback+=proposal['requested_mechanism']!=m
            for change in proposal['changes']:
                if 'delta_C'in change:deltas['warmer_setpoint'if change['delta_C']>0 else'cooler_setpoint'if change['delta_C']<0 else'fan_or_pause']+=1
            if not negative and any(x['kind']=='dryer'for x in c['A']['tasks'])and any(x['kind']=='ev_charge_window'and x['start_min']>=480 for x in c['A']['controls']):negative=controls(w,c)
        if(ix+1)%100==0:print({'B_households_read_back':ix+1,'failures':len(fail)},flush=True)
    subset=read(OUT/'SUBSET50.json');allrows={r['household_id']:r for r in b['records']};ids={r['household_id']for r in read(MASTER/'SUBSET50.json')['records']}
    subsetok=ids=={r['household_id']for r in subset['records']}and all(r==allrows[r['household_id']]for r in subset['records'])
    if not subsetok:fail.append(['SUBSET_NOT_IDENTICAL_MASTER_RECORDS'])
    coverageok=set(counts)==set(MECHANISMS)and set(intensities)==set(LEVELS)and all(cross[(m,l)]>0 for m in MECHANISMS for l in LEVELS)
    accepted=not fail and cases==10000 and len(b['records'])==1000 and coverageok and 0<feasible<cases and negative and all(x['rejected_or_flagged']for x in negative)
    accepted=accepted and b['rules_sha256']==sig and read(OUT/'A_REAUDIT.json')['accepted']
    report={'schema':'eb.alternative_static_acceptance.v35','accepted':bool(accepted),'households':len(b['records']),'cases':cases,'failures':fail,
            'rules_sha256':sig,'bindings_sha256':sha(OUT/'PAIR_BINDINGS10000.json'),'mechanisms':dict(counts),'intensity_design':dict(intensities),
            'mechanism_by_intensity':{m:{l:cross[(m,l)]for l in LEVELS}for m in MECHANISMS},'mechanism_by_type':dict(types),'mechanism_fallback_count':fallback,
            'given_constraints_feasible_cases':feasible,'given_constraint_conflict_cases_kept':cases-feasible,'constraint_flag_case_counts':dict(flags),
            'thermal_direction_counts':dict(deltas),'negative_controls':negative,'subset50_identical_master_records':subsetok,'subset50_type_counts':subset['type_counts'],
            'actual_acceptance_labels_generated':0,'B_better_than_A_filter':False,'full_physical_acceptance':False,'questionnaire_released':False}
    save(OUT/'ACCEPTANCE.json',report);print(canonical(report))
    if not accepted:raise SystemExit(2)

if __name__=='__main__':main()
