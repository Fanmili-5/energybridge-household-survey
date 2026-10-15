"""Scoped byte gates;950 waits for final original50 contrast acceptance."""
from common import *
from contrast_core import metrics,invariant_errors
from execution import realize
from type_model import permission_audit
ENGINE=Path('/home/hku_user3/energybridge-compute/EnergyPlus-24-1-0/energyplus')
PARENT=BASE/'contrast_repair_v29_20261015'

def scoped_rows(scope):
    frozen=read(PARENT/'SELECTION1000.json')['records'];parts=read(OUT/'PARTITIONS.json')
    if scope=='weather_sensitivity':
        affected={h['household_id']for h in frozen if h['weather'].get('quality_control')}
        expected={(h['household_id'],r['round_index'],'weather_linear7'):r['date']for h in frozen if h['household_id']in affected for r in h['rounds']}
        rows=read(OUT/'COMPILED_WEATHER_SENSITIVITY.json')['records']
    else:
        ids=set(parts[{'original50':'formal50','other950':'formal950'}[scope]])
        expected={(h['household_id'],r['round_index'],'base7'):r['date']for h in frozen if h['household_id']in ids for r in h['rounds']}
        rows=[c for c in read(OUT/'COMPILED1000.json')['records']if c['household_id']in ids]
        if scope=='original50':
            assert len(ids)==50
            for h in frozen:
                if h['household_id']not in ids:continue
                rr=next(r for r in h['rounds']if 7<=int(r['date'][5:7])<=9)
                for v in('prior14','seasonal7','seasonal14','temperature_flat7'):expected[h['household_id'],rr['round_index'],v]=rr['date']
            rows+=read(OUT/'COMPILED_SENSITIVITY50.json')['records']
        else:assert len(ids)==950
    keys=[(c['household_id'],c['round_index'],c['variant'])for c in rows]
    assert len(keys)==len(set(keys))and set(keys)==set(expected)
    assert all(c['date']==expected[c['household_id'],c['round_index'],c['variant']]for c in rows)
    return sorted(rows,key=lambda c:(c['household_id'],c['round_index'],c['variant']))

def input_signature(scope='original50'):
    rows=scoped_rows(scope);paths={n:OUT/n for n in('PROTOCOL_V29.json','EB_AC_SOURCE_REVIEW.json','PARTITIONS.json','LEGACY_CONTRAST_QUEUE.json')}
    for p in(OUT/'code').iterdir():
        if p.is_file()and p.suffix in('.py','.js','.cjs'):paths[str(p.relative_to(OUT))]=p
    paths['external:engine']=ENGINE;paths['external:parent_selection']=PARENT/'SELECTION1000.json'
    batch='formal50'if scope=='original50'else'formal950'
    paths['CONTRAST_'+batch+'_INPUT.json']=OUT/f'CONTRAST_{batch}_INPUT.json'
    for c in rows:
        for key in('world_path','pair_path'):paths[c[key]]=OUT/c[key]
        context=OUT/'A_context'/c['household_id']/f'{c["round_index"]:02d}.json'
        paths[str(context.relative_to(OUT))]=context
        for side in('A','B'):
            for key in('IDF_path','native_IDF_path','signal_ledger_path'):paths[c[side][key]]=OUT/c[side][key]
        paths['external:weather:'+c['weather']['path']]=Path(c['weather']['path'])
    actual={name:sha(path)for name,path in sorted(paths.items())}
    ids={c['household_id']for c in rows};selected=[h for h in read(OUT/'SELECTION1000.json')['records']if h['household_id']in ids]
    actual['virtual:scope_selection']=digest(selected);actual['virtual:compiled_scope']=digest(rows)
    return digest(actual),actual

def audit_inputs(scope):
    selected={h['household_id']:h for h in read(OUT/'SELECTION1000.json')['records']};old={h['household_id']:h for h in read(PARENT/'SELECTION1000.json')['records']};rows=scoped_rows(scope);fail=[]
    for c in rows:
        h=selected[c['household_id']];w=read(OUT/h['world_path']);rr=next(r for r in h['rounds']if r['round_index']==c['round_index']);p=read(OUT/rr['pair_path']);origrr=next(r for r in old[h['household_id']]['rounds']if r['round_index']==rr['round_index']);orig=read(PARENT/origrr['pair_path'])
        errors=invariant_errors(p,orig,w,old[h['household_id']]['world_sha256'])
        assert c['pair_sha256']==rr['pair_sha256']==sha(OUT/rr['pair_path'])
        assert c['world_sha256']==h['world_sha256']==sha(OUT/h['world_path'])
        for side in('A','B'):
            assert realize(w,p[side],p['world']['operator_windows'],p['needs_A'])==p['service_execution_reference'][side]
            b=c[side]
            for path,hash_ in [('IDF_path','IDF_sha256'),('native_IDF_path','native_IDF_sha256'),('signal_ledger_path','signal_ledger_sha256')]:assert sha(OUT/b[path])==b[hash_]
            assert digest(read(OUT/b['signal_ledger_path'])['signals'])==b['schedule_signal_sha256']
        assert p['policy_assessment']==permission_audit(w,p)
        from zone_controls import idf_bindings
        idf_bindings(w,p,c)
        from decision_contrast import source_evidence
        context=read(OUT/'A_context'/c['household_id']/f'{c["round_index"]:02d}.json')
        assert source_evidence(w,p,context)[0]==p['decision_contrast_source']
        assert p['decision_contrast_source']['passed']
        if errors:fail.append([p['case_id'],errors])
    return {'passed':not fail,'failures':fail,'pairs':len(rows),'A_needs_roster_policy_hardware_dates_unchanged':True,'independent_execution_and_actual_compiled_bytes_checked':True}

def require_original50_acceptance():
    path=OUT/'ORIGINAL50_CONTRAST_ACCEPTANCE.json'
    if not path.exists():raise RuntimeError('950 held: final original50 contrast/physics/material/browser acceptance missing')
    r=read(path);lease=require_reviewed_ep('original50')
    if not r.get('substantive_decision_contrast_passed'):raise RuntimeError('950 held: substantive original50 acceptance missing')
    if not r['passed']or r['input_signature']!=lease['review']['input_signature']:raise RuntimeError('950 held: stale original50 acceptance')
    for name,value in r['evidence'].items():
        if sha(OUT/name)!=value:raise RuntimeError('950 held: original50 evidence changed:'+name)
    return r

def review(scope):
    school_guard()
    if scope!='original50':require_original50_acceptance()
    audit=audit_inputs(scope);assert audit['passed'],audit['failures'][:3]
    signature,files=input_signature(scope);rows=scoped_rows(scope)
    r={'schema':'eb.contrast_scope_pre_EP.v29','scope':scope,'reference_production_accepted':True,'critical_findings':[],
       'input_signature':signature,'input_files':files,'expected_pairs':len(rows),'expected_sides':len(rows)*2,
       'allowed_households':sorted({c['household_id']for c in rows}),'source_and_compiled_input_audit':audit,
       'original50_final_acceptance_sha256':sha(OUT/'ORIGINAL50_CONTRAST_ACCEPTANCE.json')if scope!='original50'else None,
       'human_perceptual_validity_proven':False,'fullEP_requires_original50_final_acceptance':True}
    save(OUT/f'PRE_EP_{scope}.json',r);print({k:v for k,v in r.items()if k not in('input_files','allowed_households')},flush=True);return r

def require_reviewed_ep(scope='original50'):
    if scope not in('original50','other950','weather_sensitivity'):raise RuntimeError('unknown scope')
    if scope!='original50':require_original50_acceptance()
    path=OUT/f'PRE_EP_{scope}.json'
    if not path.exists():raise RuntimeError('fresh scoped review missing')
    r=read(path);signature,files=input_signature(scope)
    if signature!=r['input_signature']or not r['reference_production_accepted']or r['critical_findings']:raise RuntimeError('stale or failed scoped byte review')
    rows=scoped_rows(scope)
    return {'scope':scope,'review':r,'files':files,'review_path':str(path),'review_sha256':sha(path),
       'allowed_households':set(r['allowed_households']),'compiled_rows':{(c['household_id'],c['round_index'],c['variant']):digest(c)for c in rows}}

def guard_job(c,side,lease):
    if lease is None or sha(lease['review_path'])!=lease['review_sha256']:raise RuntimeError('review receipt missing/changed')
    if c['household_id']not in lease['allowed_households']or lease['compiled_rows'].get((c['household_id'],c['round_index'],c['variant']))!=digest(c):raise RuntimeError('unreviewed job')
    names=[c['world_path'],c['pair_path'],c[side]['IDF_path'],c[side]['signal_ledger_path']]
    names += [str(p.relative_to(OUT))for p in(OUT/'code').iterdir()if p.is_file()and p.suffix in('.py','.js','.cjs')]
    for name in names:
        if sha(OUT/name)!=lease['files'].get(name):raise RuntimeError('input changed:'+name)
    if sha(ENGINE)!=lease['files']['external:engine']or sha(c['weather']['path'])!=c['weather']['sha256']:raise RuntimeError('external engine/weather changed')

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--scope',choices=['original50','other950','weather_sensitivity'],default='original50');a=p.parse_args();review(a.scope)
