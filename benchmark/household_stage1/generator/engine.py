"""Explicit bindings for the ported, versioned V9 generation kernel."""
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
import hashlib,json,sys

HERE=Path(__file__).resolve().parent
CODE=HERE/'_engine'
FILES={'CRECS2012':'v7/inputs/CRECS2012.dta','ENABLE_EU':'v4/inputs/enable.sav',
 'RECS2020_v7':'public_sources/recs2020/recs2020_public_v7.csv','IRES2020':'public_sources/ires-data.tab',
 'ENASIC2022':'public_sources/mexico_enasic_2022/enasic.zip','ENIGH2024_hogares':'public_sources/mexico_enigh_2024/hogares.zip',
 'ENIGH2024_viviendas':'public_sources/mexico_enigh_2024/viviendas.zip','ECA2025':'public_sources/eca2025/eca_jun2025_data.xlsx'}

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()

def load_engine(seed=None):
    for sub in ('v4','v5','v7','admitted','v8'):
        sys.path.insert(0,str(CODE/sub))
    import adapter_v8 as a
    import audit_v8 as audit
    if seed is not None:
        seed=str(seed)
        a.shared.SEED='portable-shared:'+seed
        a.components.DESIGN_SEED='portable-members:'+seed
        a.activity.SEED='portable-activities:'+seed
        a.components.seed.SEED='portable-roles:'+seed
        a.components.seed.src.SEED='portable-source-selection:'+seed
        a.legacy.rank=lambda *v:hashlib.sha256(json.dumps(['portable-case',seed,*v],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return SimpleNamespace(a=a,audit=audit,life=audit.life,controls=audit.controls,services=audit.service)

def bind_sources(engine,config_file,workspace):
    cfg=json.loads(Path(config_file).read_text());paths={}
    pins=json.loads((HERE.parent/'SOURCES.json').read_text())['raw_source_sha256_by_filename']
    root=Path(workspace)/'source_layout';root.mkdir(parents=True,exist_ok=True)
    for name,rel in FILES.items():
        value=cfg['files'].get(name)
        if not value:raise ValueError('SOURCE_FILE_REQUIRED:'+name)
        p=Path(value).expanduser()
        if not p.is_absolute():p=Path(config_file).resolve().parent/p
        p=p.resolve(strict=True)
        expected=cfg.get('expected_sha256',{}).get(name,pins.get(Path(rel).name))
        if not expected or digest(p)!=expected:raise ValueError('SOURCE_VERSION_HASH_MISMATCH:'+name)
        target=root/rel;target.parent.mkdir(exist_ok=True,parents=True)
        if target.is_symlink():
            if target.resolve()!=p:raise ValueError('SOURCE_BINDING_ALREADY_DIFFERS:'+name)
        elif target.exists():raise ValueError('SOURCE_LAYOUT_PATH_OCCUPIED:'+name)
        else:target.symlink_to(p)
        paths[name]=p
    a=engine.a;raw=engine.audit.raw;prior=engine.audit.prior
    raw.BASE=root;raw.ROOT=root/'v4';raw.CURRENT=root/'v7'
    prior.AU_FILE=paths['ECA2025'];prior.DE_FILE=paths['ENABLE_EU']
    prior.PIN={'AU':digest(paths['ECA2025']),'DE':digest(paths['ENABLE_EU'])}
    a.shared.AU_SOURCE=paths['ECA2025'];a.shared.DE_SOURCE=paths['ENABLE_EU']
    a.shared.AU_SHA=prior.PIN['AU'];a.shared.DE_SHA=prior.PIN['DE']
    sources=engine.audit.raw_sources()
    source_cache=a.components.sources.CACHE;source_cache.clear()
    source_cache.update(recs2020=sources['recs'],es=sources['es'],es_meta=sources['meta'],india=sources['india'],
       mxpeople=sources['people'],mxcare=sources['carejobs'],mxhomes=sources['mxhomes'],mxhouses=sources['mxhouses'])
    src=a.components.seed.src;src.FILES.update({k:p for k,p in paths.items() if k in src.FILES})
    a.components.seed.RECS=paths['RECS2020_v7']
    a.BASE=root;a.OLD=root/'v7'
    return paths,root,sources

def initialize(engine,row,role,ordinal,alternative=0,pair=None):
    a=engine.a;fixture=row.get('synthetic_fixture') is True
    input_row=deepcopy(row)
    if fixture:
        if input_row['source']['dataset']!='SYNTHETIC':raise ValueError('FIXTURE_MUST_NOT_IMPERSONATE_SURVEY_DATASET')
        input_row['source']['dataset']='ENABLE_EU'
        input_row['source']['country']='GB'
    c=a.make_case(input_row,role,pair)
    if input_row['source']['dataset']=='ECA2025':a.shared.initialize(c,ordinal,alternative)
    else:a.initialize(c,ordinal,alternative)
    if fixture:
        c['source']=deepcopy(row['source']);c['source']['catalogue_id']='SYNTHETIC'
        c['household']['country']=row['source']['country']
        c['evidence_scope']['household_identity']='public_synthetic_reference_not_survey_household'
    a.legacy.role_checks(c)
    return c

def build_final(engine,baseline,mask,ordinal,pair_counts):
    a=engine.a;c=deepcopy(baseline);a.control.configure(c,mask)
    if c['source']['dataset']=='ECA2025':a.shared.build_week(c,ordinal)
    else:a.build_week(c,ordinal)
    a.legacy.role_checks(c);a.control.blueprint(c,pair_counts);a.services.attach(c)
    h=c['household']
    if h.get('ev'):h['decision_authorization']['ev_driver_id']=h['ev']['vehicle_user_member_id']
    h['cohort_generation_policy']={'policy_id':'eb.household_stage1.ac_required.v1','required_control_functions':['AC'],
       'AC_source_ownership_not_inferred':True,'source_households_and_roles_fixed_from_v8':False,
       'physical_installation_verification':'pending_next_stage'}
    h['control_configuration_scope']['required_control_functions']=['AC']
    a.activity.tag(c['household_provenance'],'cohort_generation_policy','portable generator requires AC present and controlled; raw ownership remains separate')
    return c

def check_case(engine,c,baseline,raw_sources=None):
    if raw_sources is not None and not c.get('synthetic_fixture'):
        engine.audit.check_case(c,raw_sources,baseline)
    else:
        engine.life.check(c,{},baseline)
        if 'control_inventory' in c['household']:
            engine.controls.check_revision(c,baseline);engine.services.check(c)
    return True
