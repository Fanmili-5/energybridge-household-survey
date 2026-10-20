"""Deterministic candidate order for uncomputable formal slots.

Only engineering computability may trigger this procedure. It never optimizes
VPP response, savings, service completion or human labels. A new case is a slice
of the already generated annual A, not a rewrite of a household's life to force
an opportunity. All failed attempts must remain in the production ledger.
"""
import copy
import datetime as dt
from benchmark.ab_generation.common import digest

TIME_KEYS=('start_min','end_min','release_min','deadline_min','delivery_deadline_min','connection_start_min','departure_min','actual_charge_end_min','load_min','unload_min')


def candidate_dates(household,slot,excluded,seed=20261020):
    dates=[str(dt.date(2025,1,1)+dt.timedelta(days=i))for i in range(365)]
    return sorted((d for d in dates if d not in excluded),key=lambda d:digest([seed,household,slot,d]))


def annual_case(world,annual,date,annual_path,annual_sha256):
    day=dt.date.fromisoformat(date);anchor=dt.date(2024,12,15)
    base=(day-anchor).days*1440;lo=base-1440;hi=base+3*1440
    def relative(item):
        r=copy.deepcopy(item)
        for k in TIME_KEYS:
            if k in r:r[k]-=base
        return r
    controls=[c for entry in annual['days'].values()for c in entry['controls']if c['start_min']<hi and c['end_min']>lo]
    operations=[o for o in annual['operations']if lo<=o['start_min']<hi]
    tasks=[t for t in annual['tasks']if t['start_min']<hi and t['end_min']>lo]
    ids={r['need_id']for r in tasks+operations+controls if 'need_id'in r}
    needs=[n for entry in annual['days'].values()for n in entry['needs']if n['need_id']in ids or lo<=n['release_min']<hi]
    contexts=[copy.deepcopy(annual['days'][str(day+dt.timedelta(days=i))])for i in range(-1,3)]
    for entry in contexts:
        entry['needs']=[relative(n)for n in entry['needs']];entry['controls']=[relative(c)for c in entry['controls']]
    return {'schema':'eb.normal_A_case.annual_slice.v1','case_id':world['household_id']+'__'+date,
        'household_id':world['household_id'],'date':date,'days':contexts,'needs_A':[relative(n)for n in needs],
        'A':{'tasks':[relative(t)for t in tasks],'operations':[relative(o)for o in operations],
             'controls':[relative(c)for c in controls],'changed_controls':[]},
        'year_A_path':annual_path,'year_A_sha256':annual_sha256,
        'production_scope':'new date sliced from unchanged pre-existing annual A;not an alteration to the failed case'}


def select_request(rows,retained,seed,slot):
    """Diminishing-return coverage and duplicate avoidance before native results."""
    from benchmark.ab_generation.collection_selection import view,tokens
    views=[view(r)for r in retained];seen={v['signature']for v in views}
    counts={}
    for v in views:
        for t in tokens(v):counts[t]=counts.get(t,0)+1
    def rank(row):
        v=view(row)
        roots=[t for t in tokens(v)if t.startswith('root=')]
        tradeoffs=[t for t in tokens(v)if t.startswith('tradeoff.')]
        gain=sum(1/(1+counts.get(t,0))for t in roots)/max(1,len(roots))
        gain+=sum(1/(1+counts.get(t,0))for t in tradeoffs)/max(1,len(tradeoffs))
        return (v['signature']in seen,-gain,digest([seed,slot,row['id']]))
    if not rows:raise ValueError('NO_ENGINEERING_ADMISSIBLE_REQUEST')
    return min(rows,key=rank)


def first_computable(order,engineering_reviews):
    """Never skip an untested earlier candidate for a favorable later result."""
    required=('both_native_arms_complete','native_numerical_pass','weather_pass','paired_integrity_pass')
    for ident in order:
        check=engineering_reviews.get(ident)
        if check is None:return None
        if any(type(check.get(k))is not bool for k in required):raise ValueError('INCOMPLETE_ENGINEERING_REVIEW')
        if all(check[k]for k in required):return ident
    return None


def derive_ui91_proposal(parent_root,fresh_root,out):
    """Keep reviewed UI91 and unchanged packets; add newly frozen date slices."""
    import shutil,subprocess,sys
    from pathlib import Path
    from benchmark.ab_generation.common import read,save,sha
    from .questionnaire import COLLECTOR,HERE
    sys.path.insert(0,str(COLLECTOR))
    from release import Release
    parent_root,fresh_root,out=map(lambda p:Path(p).resolve(),(parent_root,fresh_root,out))
    parent,fresh=Release(parent_root,verify_code=False),Release(fresh_root)
    assert parent.manifest['presentation_revision']=='eb.questionnaire50.refined.v91.newAB.v1'
    assert set(parent.households)==set(fresh.households)
    shutil.copytree(parent_root,out);index=copy.deepcopy(parent.index);cases=[];changed=[]
    for row in fresh.index['cases']:
        old=parent.records.get(row['case_id'])
        if old is not None:
            _,a=parent.case(row['case_id'],row['household_id']);_,b=fresh.case(row['case_id'],row['household_id'])
            if any(a[k]!=b[k]for k in ('plans','changes','context','collection_life_lines','VPP_requests')):
                raise ValueError('RETAINED_CASE_PRESENTATION_CHANGED')
            cases.append(old)
        else:
            target=out/'public'/row['path'];target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(fresh_root/'public'/row['path'],target);cases.append(row);changed.append(row['case_id'])
    paths={r['path']for r in cases}
    for row in parent.index['cases']:
        if row['path']not in paths:(out/'public'/row['path']).unlink()
    index['cases']=cases;save(out/'public/index.json',index)
    for name in ('SOURCE_IDENTITY.json','PLAN_REVIEW.json'):
        shutil.copyfile(fresh_root/name,out/name)
    source=read(out/'SOURCE_IDENTITY.json');source.update(same_50_households_and_10_original_dates=False,
        unchanged_annual_A=True,new_date_slices=len(changed),original_failed_cases_preserved_in_parent=True);save(out/'SOURCE_IDENTITY.json',source)
    for name in ('DISPLAY_MODELS.json','DISPLAY_MODELS50.json'):(out/name).unlink(missing_ok=True)
    run=subprocess.run(['node',str(HERE/'verify_refined_display.js'),str(out)],capture_output=True,text=True)
    if run.returncode:raise ValueError(run.stderr[-4000:])
    save(out/'DISPLAY_MODELS50.json',read(out/'DISPLAY_MODELS.json'))
    index['ui_assets_sha256']={p.name:sha(p)for p in (out/'public').iterdir()if p.is_file()};save(out/'INDEX50.json',index)
    m=copy.deepcopy(parent.manifest);m['cohort_id']='reference50-v4-ui91-replenished-proposal-20261020'
    m['A_stage']='normal_A_v46_unchanged_annual_calendar_with_logged_new_date_slices'
    m['source_case_definition']='497 identical parent proposal packets and three newly frozen annual-A date slices;original failed packets preserved'
    m['source_pins'].update(parent_UI91_proposal_release_sha256=parent.signature,fresh_proposal_release_sha256=fresh.signature,
        replenishment_builder_sha256=sha(Path(__file__)))
    m['implementation_files']={p.name:sha(p)for p in sorted(COLLECTOR.iterdir())if p.is_file()and p.suffix!='.pyc'}
    (out/'FORMAL_RELEASE.json').unlink();m['files']={str(p.relative_to(out)):sha(p)for p in sorted(out.rglob('*'))if p.is_file()}
    m['release_sha256']=digest({k:v for k,v in m.items()if k!='release_sha256'});save(out/'FORMAL_RELEASE.json',m)
    release=Release(out)
    return {'release_sha256':release.signature,'new_date_slices':len(changed),'unchanged_parent_cases':500-len(changed),'UI91_assets_unchanged':True}
