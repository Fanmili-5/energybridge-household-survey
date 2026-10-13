"""Content-bound original50 gate. It never grants full1000 execution."""
import concurrent.futures
from common import *
INPUT_REPORTS = ['RULE_EVIDENCE.json','REFERENCE_PHYSICS_CONTRACT.json','PURPOSE_CONTRACT.json',
 'WORLD_BINDINGS1000.json','SELECTION1000.json','SELECTION50.json','PROTOCOL.json',
 'IDF_BINDINGS20000.json','STATIC_REVIEW.json','INPUT_AUDIT.json','CALENDAR_AUDIT.json',
 'IDF_INPUT_AUDIT.json','BATH_COMMITMENT_AUDIT.json','VEHICLE_CAUSAL_NEGATIVE_CONTROLS.json',
 'MECHANISM_NEGATIVE_CONTROLS.json','SOURCE_GAP_FOLD_DIAGNOSTIC.json','STRUCTURAL_GROUP_MANIFEST.json',
 'FIELD_EVIDENCE1000.json','MATERIALS_AUDIT.json','FRONTEND_BROWSER_REVIEW.json',
 'COMPILED50.json','PHYSICAL_INPUT_AUDIT.json','ACTOR_BINDINGS.json','CONSUMER_BINDINGS.json',
 'FRONTEND_CLOCK_REVIEW.json','FRONTEND_BINDINGS_REVIEW.json','REFERENCE_MODEL_AUDIT.json',
 'ACCEPTANCE_NEGATIVE_CONTROLS.json','EXTERNAL_INPUT_LOCK.json','REVISION_PROVENANCE.json','MODEL_FORM_INPUTS.json']
DATA_DIRS = ['worlds','pairs','idfs','input_ledgers','actors','consumers','collection_materials','frontend_release']
OUTPUT_FILES={'PRE_EP_SCIENTIFIC_REVIEW.json','DELIVERY.json','FINAL_ACCEPTANCE.json','EXECUTION_BOARD.json',
 'MODEL_FORM_SENSITIVITY.json','WEATHER_SOLVER_REVIEW.json','RESULT_REUSE_REVIEW.json','PUBLIC_SUMMARY.json'}
def input_paths():
    paths={n:OUT/n for n in INPUT_REPORTS}
    for p in OUT.glob('*.json'):
        if p.name not in OUTPUT_FILES and not p.name.startswith(('EP_','READBACK_','FINAL_')):
            paths[p.name]=p
    for name in DATA_DIRS+['code']:
        for p in (OUT/name).rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc':
                paths[str(p.relative_to(OUT))]=p
    for p in OUT.glob('*.md'):paths[p.name]=p
    for row in read(OUT/'EXTERNAL_INPUT_LOCK.json')['files']:
        paths['external:'+row['path']]=Path(row['path'])
    return paths
def declared_bindings():
    expected={}
    def put(path,checksum):
        if path in expected and expected[path]!=checksum:raise RuntimeError('Conflicting binding: '+path)
        expected[path]=checksum
    for h in read(OUT/'SELECTION1000.json')['records']:
        put(h['world_path'],h['world_sha256'])
        for c in h['rounds']:put(c['pair_path'],c['pair_sha256'])
    for h in read(OUT/'IDF_BINDINGS20000.json')['households']:
        for c in h['records']:
            for s in ('A','B'):
                b=c[s];put(b['IDF_path'],b['IDF_sha256']);put(b['signal_ledger_path'],b['signal_ledger_sha256'])
    for c in read(OUT/'COMPILED50.json')['records']+read(OUT/'MODEL_FORM_INPUTS.json')['records']:
        put(c['world_path'],c['world_sha256']);put(c['pair_path'],c['pair_sha256'])
        for s in ('A','B'):
            b=c[s];put(b['IDF_path'],b['IDF_sha256']);put(b['native_IDF_path'],b['native_IDF_sha256'])
            put(b['signal_ledger_path'],b['signal_ledger_sha256'])
    for file,pkey,hkey in [('ACTOR_BINDINGS.json','actor_path','actor_sha256'),('CONSUMER_BINDINGS.json','consumer_path','consumer_sha256')]:
        for r in read(OUT/file)['records']:put(r[pkey],r[hkey])
    for r in read(OUT/'EXTERNAL_INPUT_LOCK.json')['files']:put('external:'+r['path'],r['sha256'])
    return expected
def input_signature():
    paths=input_paths()
    def one(k):
        p=paths[k]
        if not p.is_file():raise RuntimeError('Missing registered input: '+k)
        return k,sha(p)
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        actual=dict(pool.map(one,sorted(paths)))
    bad=[k for k,v in declared_bindings().items() if actual.get(k)!=v]
    if bad:raise RuntimeError('Actual input binding changed: '+str(bad[:8]))
    return digest(actual),actual
def require_reviewed_ep(scope='original50'):
    if scope!='original50':raise RuntimeError('EP hold: full1000 scope is not authorized')
    path=OUT/'PRE_EP_SCIENTIFIC_REVIEW.json'
    if not path.exists():raise RuntimeError('EP hold: scientific review has not passed')
    review=read(path);current,files=input_signature()
    if review['input_signature']!=current:raise RuntimeError('EP hold: actual inputs/code changed since review')
    if not (review['purpose_recheck_passed'] and review['reference_production_accepted'] and not review['critical_reference_findings']):
        raise RuntimeError('EP hold: review failed')
    if scope not in review['allowed_EP_scopes'] or review['full1000_EP_allowed']:
        raise RuntimeError('EP hold: scope not accepted')
    if review['national_behavior_validated'] or review['formal_benchmark_release']:
        raise RuntimeError('EP hold: unsupported empirical claim')
    return {'review':review,'files':files,'review_sha256':sha(path),
            'compiled_rows':{(r['household_id'],r['round_index'],r['variant']):digest(r) for r in read(OUT/'COMPILED50.json')['records']+read(OUT/'MODEL_FORM_INPUTS.json')['records']}}
def guard_job(c,side,lease):
    """Full batch check before/after; each job rehashes its actual inputs."""
    if sha(OUT/'PRE_EP_SCIENTIFIC_REVIEW.json')!=lease['review_sha256']:raise RuntimeError('Review changed during batch')
    key=(c['household_id'],c['round_index'],c['variant'])
    if lease['compiled_rows'].get(key)!=digest(c):raise RuntimeError('Unregistered or changed job')
    b=c[side]
    names=[c['world_path'],c['pair_path'],b['IDF_path'],b['signal_ledger_path']]
    names += [str(p.relative_to(OUT)) for p in (OUT/'code').rglob('*.py')]
    names += ['PURPOSE_CONTRACT.json','REFERENCE_PHYSICS_CONTRACT.json','RULE_EVIDENCE.json']
    external=[c['weather']['path'],'/home/hku_user3/energybridge-compute/EnergyPlus-24-1-0/energyplus']
    for k in names:
        if sha(OUT/k)!=lease['files'].get(k):raise RuntimeError('Input changed before job: '+k)
    for k in external:
        if sha(k)!=lease['files'].get('external:'+k):raise RuntimeError('External input changed before job: '+k)

