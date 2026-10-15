"""Fresh content-bound original50-only lease. Full1000 remains unconditionally held."""
from common import *

REPORTS=['IMPLEMENTATION_CONTRACT.json','PROTOCOL.json','RULE_EVIDENCE.json',
 'REFERENCE_PHYSICS_CONTRACT.json','WORLD_BINDINGS50.json','TYPE_ASSIGNMENT50.json',
 'SELECTION50.json','STATIC_REVIEW.json','INPUT_AUDIT.json','CALENDAR_AUDIT.json',
 'FIELD_EVIDENCE50.json','ACTUAL_FEATURES50.json','CLUSTER_COVERAGE50_REVIEW.json',
 'IDF_BINDINGS1000.json','IDF_INPUT_AUDIT.json','BATH_COMMITMENT_AUDIT.json',
 'MECHANISM_NEGATIVE_CONTROLS.json','VEHICLE_CAUSAL_NEGATIVE_CONTROLS.json',
 'COMPILED50.json','MODEL_FORM_INPUTS.json','PHYSICAL_INPUT_AUDIT.json','EXTERNAL_INPUT_LOCK.json','REFERENCE_MODEL_AUDIT.json',
 'ACTOR_BINDINGS.json','CONSUMER_BINDINGS.json','FRONTEND_BINDINGS_REVIEW.json','FRONTEND_CLOCK_REVIEW.json','FRONTEND_BROWSER_REVIEW.json']


def input_signature():
    paths={n:OUT/n for n in REPORTS}
    for folder in ('code','worlds','pairs','idfs','input_ledgers','actors','consumers','collection_materials','frontend_release'):
        for p in (OUT/folder).rglob('*'):
            if p.is_file()and '__pycache__'not in p.parts and p.suffix!='.pyc':paths[str(p.relative_to(OUT))]=p
    external={str(ENGINE):ENGINE} if (ENGINE:=Path('/home/hku_user3/energybridge-compute/EnergyPlus-24-1-0/energyplus')).is_file()else {}
    for h in read(OUT/'SELECTION50.json')['records']:external[h['weather']['path']]=Path(h['weather']['path'])
    for name,p in external.items():paths['external:'+name]=p
    actual={k:sha(p)for k,p in sorted(paths.items())}
    for h in read(OUT/'SELECTION50.json')['records']:
        assert actual[h['world_path']]==h['world_sha256']
        assert actual['external:'+h['weather']['path']]==h['weather']['sha256']
        for p in h['rounds']:assert actual[p['pair_path']]==p['pair_sha256']
    for c in read(OUT/'COMPILED50.json')['records']+read(OUT/'MODEL_FORM_INPUTS.json')['records']:
        for arm in ('A','B'):
            b=c[arm]
            for p,k in [('IDF_path','IDF_sha256'),('native_IDF_path','native_IDF_sha256'),('signal_ledger_path','signal_ledger_sha256')]:assert actual[b[p]]==b[k]
    return digest(actual),actual


def require_reviewed_ep(scope='original50'):
    if scope!='original50':raise RuntimeError('EP hold: full1000 is unconditionally outside this pilot')
    p=OUT/'PRE_EP_SCIENTIFIC_REVIEW.json'
    if not p.is_file():raise RuntimeError('EP hold: fresh original50 review missing')
    review=read(p);current,files=input_signature()
    if current!=review['input_signature']:raise RuntimeError('EP hold: code/actual inputs changed after review')
    if not review['reference_production_accepted']or review['critical_reference_findings']:raise RuntimeError('EP hold: pre-EP findings')
    if review['full1000_EP_allowed']or review['national_behavior_validated']or review['formal_benchmark_release']:raise RuntimeError('EP hold: unsupported scope/claim')
    return {'review':review,'files':files,'review_sha256':sha(p),
            'compiled_rows':{(c['household_id'],c['round_index'],c['variant']):digest(c)for c in read(OUT/'COMPILED50.json')['records']+read(OUT/'MODEL_FORM_INPUTS.json')['records']}}


def guard_job(c,side,lease):
    if sha(OUT/'PRE_EP_SCIENTIFIC_REVIEW.json')!=lease['review_sha256']:raise RuntimeError('review changed during batch')
    if lease['compiled_rows'].get((c['household_id'],c['round_index'],c['variant']))!=digest(c):raise RuntimeError('unregistered or changed compiled job')
    b=c[side];names=[c['world_path'],c['pair_path'],b['IDF_path'],b['signal_ledger_path']]
    names += [str(p.relative_to(OUT))for p in (OUT/'code').rglob('*')if p.is_file()and '__pycache__'not in p.parts]
    for name in names:
        if sha(OUT/name)!=lease['files'].get(name):raise RuntimeError('actual input changed:'+name)
    for name in [c['weather']['path'],'/home/hku_user3/energybridge-compute/EnergyPlus-24-1-0/energyplus']:
        if sha(name)!=lease['files'].get('external:'+name):raise RuntimeError('external input changed')


def review():
    school_guard();checks={}
    original=read(PILOT/'SELECTION50.json')['records'];sel=read(OUT/'SELECTION50.json')['records']
    checks['same_original50_and_dates']={(h['household_id'],r['round_index'],r['date'])for h in original for r in h['rounds']}=={(h['household_id'],r['round_index'],r['date'])for h in sel for r in h['rounds']}and len(sel)==50
    checks['500_pairs_source_policy_normal_A']=read(OUT/'INPUT_AUDIT.json')['status']=='pass'and read(OUT/'STATIC_REVIEW.json')['pairs']==500
    checks['dated_calendars']=not read(OUT/'CALENDAR_AUDIT.json')['failures']
    checks['actual_six_type_reference_coverage']=read(OUT/'CLUSTER_COVERAGE50_REVIEW.json')['accepted_for_original50_reference_development']
    checks['1000_static_IDF_signals']=not read(OUT/'IDF_INPUT_AUDIT.json')['failures']
    for name in ['BATH_COMMITMENT_AUDIT.json','MECHANISM_NEGATIVE_CONTROLS.json','VEHICLE_CAUSAL_NEGATIVE_CONTROLS.json','PHYSICAL_INPUT_AUDIT.json']:
        checks[name]=read(OUT/name)['status']=='pass'
    checks['native_reference_model']=read(OUT/'REFERENCE_MODEL_AUDIT.json')['status']=='pass'
    for name in ['FRONTEND_BINDINGS_REVIEW.json','FRONTEND_CLOCK_REVIEW.json','FRONTEND_BROWSER_REVIEW.json']:
        checks[name]=read(OUT/name)['status']=='pass'
    # Engine lock is consumed by original independent SQL/run-coverage verifier.
    engine='/home/hku_user3/energybridge-compute/EnergyPlus-24-1-0/energyplus'
    external={engine:sha(engine)}
    for h in sel:external[h['weather']['path']]=sha(h['weather']['path'])
    save(OUT/'EXTERNAL_INPUT_LOCK.json',{'engine_sha256':external[engine],
        'files':[{'path':k,'sha256':v}for k,v in external.items()]})
    critical=[k for k,v in checks.items()if not v];signature,files=input_signature()
    report={'schema':'eb.type_pilot_pre_EP_review.v27','checks':checks,'critical_reference_findings':critical,
        'input_signature':signature,'input_files':files,'reference_production_accepted':not critical,
        'purpose_recheck_passed':not critical,'allowed_EP_scopes':['original50']if not critical else [],
        'full1000_EP_allowed':False,'national_behavior_validated':False,'formal_benchmark_release':False,
        'source_preferences_are_observed':False,'human_answers':0,'accepted_scope':'source/contract coherent reference original50;fresh physical output pending'}
    save(OUT/'PRE_EP_SCIENTIFIC_REVIEW.json',report);print({k:v for k,v in report.items()if k!='input_files'},flush=True)
    if critical:raise RuntimeError('pre-EP review failed')


if __name__=='__main__':review()
