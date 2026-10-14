"""Fresh two-step authorization: original50 first, remaining950 after its readback."""
from common import *

ENGINE=Path('/home/hku_user3/energybridge-compute/EnergyPlus-24-1-0/energyplus')
REPORTS=['BOOTSTRAP.json','CHRONOLOGY_RULE_REPAIR.json','R_SCOPE_ADAPTER.json','COHORT_GATE_INSTALLATION.json','MATERIAL_SCOPE_ADAPTER.json','PARTITIONS.json','WORLD_BINDINGS1000.json','WORLD_BUILD_REVIEW.json',
 'SELECTION1000.json','STATIC_REVIEW.json','INPUT_AUDIT.json','CALENDAR_AUDIT.json','ACTUAL_FEATURES1000.json',
 'CLUSTER_COVERAGE1000_REVIEW.json','BATH_COMMITMENT_AUDIT.json','COMPILED1000.json','IDF_BINDINGS1000.json','IDF_INPUT_AUDIT.json',
 'MECHANISM_NEGATIVE_CONTROLS.json','VEHICLE_CAUSAL_NEGATIVE_CONTROLS.json','REFERENCE_MODEL_AUDIT.json','PHYSICAL_INPUT_AUDIT.json','STATIC_PRODUCTION_COMPLETE.json','COMPILED_SENSITIVITY50.json','SENSITIVITY_INPUT_AUDIT.json','WEATHER_QC_REVIEW.json','COMPILED_WEATHER_SENSITIVITY.json','STRUCTURAL_ZERO_CONTROLS.json','EXTERNAL_SQL_BINDING_REVIEW.json']

def scoped_rows(scope):
    if scope=='weather_sensitivity':
        rows=read(OUT/'COMPILED_WEATHER_SENSITIVITY.json')['records']
        affected={h['household_id']for h in read(OUT/'SELECTION1000.json')['records']if h['weather'].get('quality_control')}
        # derive dates independently from the frozen source selection
        expected={(h['household_id'],r['round_index'],r['date'])for h in read(SOURCE/'SELECTION1000.json')['records']if h['household_id']in affected for r in h['rounds']}
        assert len(rows)==len(expected)==len(affected)*10 and all(c['variant']=='weather_linear7'for c in rows)
        assert {(c['household_id'],c['round_index'],c['date'])for c in rows}==expected
        return sorted(rows,key=lambda c:(c['household_id'],c['round_index']))
    key={'original50':'formal50','other950':'formal950'}[scope];partitions=read(OUT/'PARTITIONS.json');ids=set(partitions[key])
    original=read(SOURCE/'SELECTION1000.json')['records'];dates={(h['household_id'],r['round_index']):r['date']for h in original if h['household_id']in ids for r in h['rounds']}
    rows=[c for c in read(OUT/'COMPILED1000.json')['records']if c['household_id']in ids]
    keys=[(c['household_id'],c['round_index'])for c in rows]
    assert len(ids)==(50 if scope=='original50'else 950)and len(keys)==10*len(ids)
    assert len(keys)==len(set(keys))and set(keys)==set(dates)
    assert all(c['variant']=='base7'and c['date']==dates[c['household_id'],c['round_index']]for c in rows)
    if scope=='original50':
        extras=read(OUT/'COMPILED_SENSITIVITY50.json')['records'];source={h['household_id']:h for h in original if h['household_id']in ids}
        summer={hid:next(r['round_index']for r in h['rounds']if 7<=int(r['date'][5:7])<=9)for hid,h in source.items()}
        expected={(hid,i,v)for hid,i in summer.items()for v in('prior14','seasonal7','seasonal14','temperature_flat7')}
        actual=[(c['household_id'],c['round_index'],c['variant'])for c in extras]
        assert len(extras)==len(set(actual))==200 and set(actual)==expected and all(c['date']==dates[c['household_id'],c['round_index']]for c in extras)
        rows+=extras
    return sorted(rows,key=lambda c:(c['household_id'],c['round_index'],c['variant']))

def input_signature():
    paths={n:OUT/n for n in REPORTS}
    for folder in ('code','worlds','pairs','idfs','input_ledgers'):
        for p in(OUT/folder).rglob('*'):
            if p.is_file()and'__pycache__'not in p.parts and p.suffix!='.pyc':paths[str(p.relative_to(OUT))]=p
    paths['external:engine']=ENGINE;paths['external:frozen_composition']=BASE/'eb_type_pilot_v27_20261014/FROZEN_COMPOSITION1000.json';paths['external:source_selection']=SOURCE/'SELECTION1000.json'
    for h in read(OUT/'SELECTION1000.json')['records']:paths['external:'+h['weather']['path']]=Path(h['weather']['path'])
    for c in read(OUT/'COMPILED_WEATHER_SENSITIVITY.json')['records']:paths['external:'+c['weather']['path']]=Path(c['weather']['path'])
    for f in read(OUT/'WEATHER_QC_REVIEW.json')['records']:paths['external:raw:'+f['original_path']]=Path(f['original_path'])
    actual={name:sha(path)for name,path in sorted(paths.items())}
    for h in read(OUT/'SELECTION1000.json')['records']:
        assert actual[h['world_path']]==h['world_sha256']and actual['external:'+h['weather']['path']]==h['weather']['sha256']
        for r in h['rounds']:assert actual[r['pair_path']]==r['pair_sha256']
    for c in read(OUT/'COMPILED1000.json')['records']+read(OUT/'COMPILED_SENSITIVITY50.json')['records']:
        for side in('A','B'):
            for name,key in [('IDF_path','IDF_sha256'),('native_IDF_path','native_IDF_sha256'),('signal_ledger_path','signal_ledger_sha256')]:assert actual[c[side][name]]==c[side][key]
    return digest(actual),actual

def review(scope):
    school_guard();assert scope in('original50','other950','weather_sensitivity')
    static=read(OUT/'STATIC_PRODUCTION_COMPLETE.json');selection=read(OUT/'SELECTION1000.json');partition=read(OUT/'PARTITIONS.json')
    checks={'static_production_complete':static['passed'],'1000_households_10000_pairs':selection['households']==1000 and selection['pairs']==10000,
      'source_policy_and_normal_A':read(OUT/'INPUT_AUDIT.json')['status']=='pass','all_member_calendars':not read(OUT/'CALENDAR_AUDIT.json')['failures'],
      'actual_type_coverage':read(OUT/'CLUSTER_COVERAGE1000_REVIEW.json')['accepted_for_frozen1000_reference_production'],
      '20000_static_IDFs':not read(OUT/'IDF_INPUT_AUDIT.json')['failures'],
      'disjoint50_950':len(partition['formal50'])==50 and len(partition['formal950'])==950 and not(set(partition['formal50'])&set(partition['formal950']))}
    for name in ['BATH_COMMITMENT_AUDIT.json','MECHANISM_NEGATIVE_CONTROLS.json','VEHICLE_CAUSAL_NEGATIVE_CONTROLS.json','REFERENCE_MODEL_AUDIT.json','PHYSICAL_INPUT_AUDIT.json','SENSITIVITY_INPUT_AUDIT.json','WEATHER_QC_REVIEW.json','STRUCTURAL_ZERO_CONTROLS.json','EXTERNAL_SQL_BINDING_REVIEW.json']:checks[name]=read(OUT/name)['status']=='pass'
    frozen=read(BASE/'eb_type_pilot_v27_20261014/FROZEN_COMPOSITION1000.json')
    checks['frozen_composition_recovered']=read(OUT/'INPUT_AUDIT.json')['actual_type_counts']==frozen['counts']
    parent=None
    if scope in('other950','weather_sensitivity'):
        parent=OUT/'PHYSICS_original50_REVIEW.json';checks['new_original50_physically_accepted']=parent.exists()and read(parent)['acceptance_passed']and read(parent)['baseline_pairs_checked']==500 and read(parent)['sensitivity_pairs_checked']==200
    critical=[k for k,v in checks.items()if not v];signature,files=input_signature();rows=scoped_rows(scope)
    save(OUT/'EXTERNAL_INPUT_LOCK.json',{'engine_sha256':sha(ENGINE)})
    result={'schema':'eb.fresh_cohort_pre_EP_review.v28','scope':scope,'allowed_households':sorted({c['household_id']for c in rows}),
        'expected_pairs':len(rows),'expected_sides':len(rows)*2,'input_signature':signature,'input_files':files,'checks':checks,
        'critical_findings':critical,'reference_production_accepted':not critical,'user_requested_formal50_and_formal950':True,
        'other950_requires_new_original50_acceptance':True,'parent_physics_review_sha256':sha(parent)if parent and parent.exists()else None,
        'national_behavior_validated':False,'scientific_benchmark_validated':False,'field_calibration':False,'human_answers':0}
    save(OUT/f'PRE_EP_{scope}.json',result);print({k:v for k,v in result.items()if k not in('input_files','allowed_households')},flush=True)
    if critical:raise RuntimeError('EP held: '+str(critical))
    return result

def require_reviewed_ep(scope='original50'):
    if scope not in('original50','other950','weather_sensitivity'):raise RuntimeError('EP scope not authorized')
    path=OUT/f'PRE_EP_{scope}.json'
    if not path.is_file():raise RuntimeError('EP hold: fresh cohort review missing')
    r=read(path);signature,files=input_signature()
    if signature!=r['input_signature']or r['critical_findings']or not r['reference_production_accepted']:raise RuntimeError('EP hold: stale or failed actual input review')
    if scope in('other950','weather_sensitivity'):
        parent=OUT/'PHYSICS_original50_REVIEW.json'
        if not parent.is_file()or sha(parent)!=r['parent_physics_review_sha256']or not read(parent)['acceptance_passed']:raise RuntimeError('EP hold: current original50 physical acceptance missing/changed')
    rows=scoped_rows(scope)
    return {'scope':scope,'review':r,'files':files,'review_sha256':sha(path),'review_path':str(path),
        'allowed_households':set(r['allowed_households']),'compiled_rows':{(c['household_id'],c['round_index'],c['variant']):digest(c)for c in rows}}

def guard_job(c,side,lease):
    if lease is None or sha(lease['review_path'])!=lease['review_sha256']:raise RuntimeError('EP review changed or missing')
    if c['household_id']not in lease['allowed_households']or lease['compiled_rows'].get((c['household_id'],c['round_index'],c['variant']))!=digest(c):raise RuntimeError('unregistered or changed cohort job')
    names=[c['world_path'],c['pair_path'],c[side]['IDF_path'],c[side]['signal_ledger_path']]
    names.extend(str(p.relative_to(OUT))for p in(OUT/'code').rglob('*')if p.is_file()and'__pycache__'not in p.parts and p.suffix!='.pyc')
    for name in names:
        if sha(OUT/name)!=lease['files'].get(name):raise RuntimeError('actual EP input changed: '+name)
    if sha(ENGINE)!=lease['files'].get('external:engine')or sha(c['weather']['path'])!=lease['files'].get('external:'+c['weather']['path']):raise RuntimeError('external EP input changed')

if __name__=='__main__':
    import argparse
    a=argparse.ArgumentParser();a.add_argument('--scope',choices=['original50','other950','weather_sensitivity'],required=True);args=a.parse_args();review(args.scope)
