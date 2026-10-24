"""Household-only acceptance: pair seeds/loadings, then 50 shadow portraits.

Reads declared facts/calendars/services. Original A/B and outcomes are hash
protected, never executed, selected, repaired or used to sample preferences.
"""
import argparse
from collections import Counter,defaultdict
import copy
import gzip
import json
from pathlib import Path

from .core import HERE,read,save,sha,digest,require,seal
from .device_persona import generate_personas,preference_input,render_family,from_declared_family
from .portrait_inputs import from_formal
from .joint_sampling import VERSION,VERSION2,apply_to_life
from .portrait_v2 import audit,render_dated

PAIR=('ordinary-v6-0696','ordinary-v6-0756')
SEEDS=tuple(range(8))
LOADINGS=(0,.35,.7,.9)


def configured(c,mode,seed=0,loading=.7):
    result=copy.deepcopy(c)
    result.setdefault('energy_preferences',{})['preference_sampling']={'mode':mode,'seed':seed,'loading':loading}
    return result


def signature(p,exclude_kinds=()):
    """Exclude IDs/prose/clocks/temperature amounts/AC counts and latent floats."""
    rows=set()
    for d in p['devices']:
        if d['kind'] in exclude_kinds:continue
        r=d['sampled_preferences']
        if d['kind'] in ('washer','dryer','dishwasher'):
            timing=r.get('time_preference',{})
            active=(r['routine_sensitive'],r['handling_change_sensitive'],
                    'explicit_clock' if timing.get('declared_stable_clock_min') is not None else timing.get('stable_direction'))
        elif d['kind']=='ac':active=(r['coordinates']['comfort_sensitivity']>=.5,)
        elif d['kind']=='water_heater':active=(r['readiness_priority']>=.5,)
        else:active=(r['routine_sensitive'],r['readiness_priority']>=.5)
        rows.add((d['kind'],r['authorization_preference'],active))
    return digest(sorted(rows,key=str))


def brief(p):
    result=[]
    for d in p['devices']:
        r=d['sampled_preferences']
        result.append({'asset_id':d['asset_id'],'kind':d['kind'],'routine_sensitive':r['routine_sensitive'],
                       'handling_change_sensitive':r['handling_change_sensitive'],'machine_shift_soft_min':r['preferred_shift_limit_min'],
                       'machine_shift_soft_raw_min':r['preferred_shift_limit_min_raw'],
                       'cooling_preferred_C':r.get('cooling_preferred_C'),'readiness_priority':r.get('readiness_priority'),
                       'stable_direction':r.get('time_preference',{}).get('stable_direction'),
                       'dated_targets':r.get('time_preference',{}).get('per_service'),
                       'A_projection':r.get('time_preference',{}).get('A_projection')})
    return result


def compile_checked(c):
    original=digest(c);p=generate_personas(c);s=preference_input(c);check=audit(p,s)
    require(digest(c)==original,'PORTRAIT_SOURCE_MUTATED')
    require(p==generate_personas(c),'PORTRAIT_REPLAY_FAILED')
    changed=copy.deepcopy(c);changed['days']=changed['days'][-1:]
    changed.update(plans={'A':'unread','B':'unread'},outcomes='unread',answers='unread')
    require(p==generate_personas(changed),'PORTRAIT_CASE_OR_OUTCOME_LEAKAGE')
    # Compare all latent coordinates with v1, not merely a change of seed label.
    old=generate_personas(configured(c,VERSION,c['energy_preferences']['preference_sampling']['seed'],c['energy_preferences']['preference_sampling']['loading']))
    require(p['joint_sampling']['shared_coordinates']==old['joint_sampling']['shared_coordinates'],'LATENT_STREAM_CHANGED')
    for d,b in zip(p['devices'],old['devices']):
        require(d['sampled_preferences']['coordinates']==b['sampled_preferences']['coordinates'],'DEVICE_LATENT_CHANGED')
        require(set(d['authorization']['standing_consent_actions'])<=set(b['authorization']['standing_consent_actions']),'PERMISSION_EXPANDED')
        require(d['authorization']==b['authorization'],'AUTHORIZATION_CHANGED_FROM_SAME_STREAM_BASELINE')
        require(d['decision_conditions']==b['decision_conditions'],'ORIGINAL_SERVICE_OR_OPERATOR_FACTS_CHANGED')
    require(not check['engineering_errors'],'PORTRAIT_SEMANTIC_ERRORS:'+str(check['engineering_errors']))
    return p,old,check


def write_profile(folder,p):
    save(folder.with_suffix('.json'),p)
    folder.with_suffix('.family.md').write_text(render_family(p))
    folder.with_suffix('.dated.md').write_text(render_dated(p))


def validate(artifacts,out,pair_inputs=None,v1_reference=None):
    artifacts,out=Path(artifacts).resolve(),Path(out).resolve()
    require(not out.is_relative_to(artifacts) and not out.is_relative_to(HERE),'OUTPUT_MUST_BE_INDEPENDENT')
    out.mkdir(parents=True,exist_ok=False)
    locks={}
    def load(path):
        path=Path(path).resolve();locks[str(path)]=sha(path)
        if path.suffix=='.gz':
            with gzip.open(path,'rt') as f:return json.load(f)
        return read(path)
    methods={str(p.relative_to(HERE)):sha(p) for p in HERE.glob('*.py')}
    methods.update({str(p.relative_to(HERE)):sha(p) for p in HERE.glob('*.json') if p.name!='PACKAGE_MANIFEST.json'})
    release=artifacts/'release-complete500-ui91-physics-v5-rounds';raw=artifacts/'A-source-complete500-v1'
    index=load(release/'INDEX50.json');formal=load(release/'FORMAL_RELEASE.json')
    require(digest({k:v for k,v in formal.items() if k!='release_sha256'})==formal['release_sha256'],'FORMAL_RELEASE_SIGNATURE')
    require(sha(release/'INDEX50.json')==formal['files']['INDEX50.json'],'FORMAL_INDEX_HASH')
    subset={r['household_id']:r for r in load(raw/'SUBSET50.json')['records']}
    contexts={};source_records={};neighbor_calendars={}
    def context(hid):
        if hid in contexts:return contexts[hid]
        profile=load(release/'public/households'/f'{hid}.json')
        require(sha(release/'public/households'/f'{hid}.json')==index['profiles_sha256'][hid],'FORMAL_PROFILE_HASH')
        source=subset[hid];hardware=load(raw/source['A_world_path'])
        require(sha(raw/source['A_world_path'])==source['A_world_sha256'],'FORMAL_HARDWARE_HASH')
        cases=[r for r in index['cases'] if r['household_id']==hid]
        require(len(cases)==10,'TEN_ORIGINAL_DATES_REQUIRED')
        rows={r['date']:r for r in source['cases']};days=[];cs=[];protected=[];neighbors={}
        for case in cases:
            row=rows[case['date']];packet=load(raw/row['path'])
            require(sha(raw/row['path'])==row['sha256'],'RAW_CALENDAR_HASH')
            for d in packet['days']:
                a=d['activity'];value={'date':d['date'],'calendars':a['member_calendars'],'operator_windows':a['operator_windows_min']}
                require(d['date'] not in neighbors or neighbors[d['date']]==value,'SOURCE_NEIGHBOR_CALENDARS_DISAGREE')
                neighbors[d['date']]=value
            day=next(d for d in packet['days'] if d['date']==case['date'])['activity']
            days.append({'date':case['date'],'calendars':day['member_calendars'],'operator_windows':day['operator_windows_min']})
            c=load(artifacts/'collection-complete500-v1/contexts'/f"{hid}__{case['date']}.json.gz")
            require(c['source']['A_case_sha256']==row['sha256'],'SOURCE_A_LINEAGE')
            path=release/'public'/case['path'];locks[str(path)]=sha(path)
            require(locks[str(path)]==case['sha256'],'FORMAL_CASE_HASH')
            cs.append(c);protected.append({'case_id':case['case_id'],'sha256':locks[str(path)],'date':case['date']})
        result=from_formal(profile,days,source['type'],cs)
        if pair_inputs and hid in PAIR:
            original=load(Path(pair_inputs)/f'{hid}.json')
            require(result==original,'PAIR_INPUT_CONTEXT_DRIFT')
        contexts[hid]=result
        neighbor_calendars[hid]=neighbors
        hardware_key=digest(sorted(digest({k:d.get(k) for k in ('types','parameters','model_family','max_electric_kw')}) for d in hardware['parameter_pack']['devices']))
        source_records[hid]={'role':source['type'],'hardware_signature':hardware_key,'original_case_files':protected,'original_dates':sorted(d['date'] for d in days)}
        return result
    # Exactly the two declared households first. No ranking or seed search.
    pair_rows=[];paired={};pair_failures=[];replay=[]
    for hid in PAIR:
        c=context(hid)
        for loading in LOADINGS:
            for seed in SEEDS:
                spec=configured(c,VERSION2,seed,loading)
                try:
                    p,old,check=compile_checked(spec)
                    path=Path('pair')/f'loading-{loading:g}'/f'seed-{seed}'/hid
                    write_profile(out/path,p);paired[hid,loading,seed]=p
                    old_path=out/'pair-before'/f'loading-{loading:g}'/f'seed-{seed}'/f'{hid}.json';save(old_path,old)
                    if v1_reference:
                        ref=load(Path(v1_reference)/f'loading-{loading:g}'/f'seed-{seed}'/f'{hid}.json')
                        require(old==ref,'V1_ARCHIVED_PROFILE_REPLAY_MISMATCH')
                        replay.append({'household_id':hid,'loading':loading,'seed':seed,'full_v1_profile_identical':True})
                    pair_rows.append({'household_id':hid,'loading':loading,'seed':seed,'path':str(path.with_suffix('.json')),
                                      'signature':signature(p),'devices':brief(p),'semantic_audit':check})
                except (ValueError,KeyError,TypeError) as error:
                    pair_failures.append({'household_id':hid,'loading':loading,'seed':seed,'reason':str(error),'status':'engineering_diagnostic_retained'})
    require(source_records[PAIR[0]]['role']==source_records[PAIR[1]]['role'] and source_records[PAIR[0]]['hardware_signature']==source_records[PAIR[1]]['hardware_signature'],'PAIR_NOT_SAME_CLASS_AND_HARDWARE')
    save(out/'PAIR_MATRIX.json',pair_rows);save(out/'PAIR_ENGINEERING_DIAGNOSTICS.json',pair_failures);save(out/'V1_REPLAY.json',replay)
    # Full denominator: all 50 originals, one predeclared seed0 and loading0.7.
    rows=[];profiles={};full_checks=[];baseline=[]
    for hid in index['households']:
        c=context(hid)
        save(out/'inputs'/f'{hid}.json',c)
        try:
            p,old,check=compile_checked(configured(c,VERSION2))
            write_profile(out/'profiles50'/hid,p);profiles[hid]=p;full_checks.append(check)
            rows.append({'household_id':hid,'role':c['role'],'status':'portrait_semantics_checked','signature':signature(p),
                         'missing_targets':len(check['missing_targets']),'negotiation_items':len(check['member_negotiations']),
                         'pending_A_projection_items':len(check['pending_A_projection']),'original_dates':source_records[hid]['original_dates']})
            if hid in PAIR:
                save(out/'before'/f'{hid}.json',old)
                (out/'before'/f'{hid}.family.md').write_text(render_family(old))
            for d,b in zip(p['devices'],old['devices']):
                if d['kind'] in ('washer','dishwasher','ev'):
                    baseline.append({'household_id':hid,'role':c['role'],'asset_id':d['asset_id'],'kind':d['kind'],
                                     'v1_soft_shift_min':b['sampled_preferences']['preferred_shift_limit_min'],
                                     'v2_soft_shift_min':d['sampled_preferences']['preferred_shift_limit_min'],
                                     'same_latent_coordinates':d['sampled_preferences']['coordinates']==b['sampled_preferences']['coordinates']})
        except (ValueError,KeyError,TypeError) as error:
            rows.append({'household_id':hid,'role':c['role'],'status':'engineering_diagnostic_retained','reason':str(error)})
    groups=defaultdict(list)
    for hid,p in profiles.items():groups[(p['role'],signature(p))].append(hid)
    diversity={'by_role':{role:{'households':sum(p['role']==role for p in profiles.values()),'qualitative_signatures':sum(r==role for r,sig in groups),
                              'qualitative_signatures_without_AC':len({signature(p,('ac',)) for p in profiles.values() if p['role']==role}),
                              'largest_equal_group':max([len(ids) for (r,sig),ids in groups.items() if r==role] or [0])} for role in 'ABCDEF'},
               'equal_groups':[{'role':r,'households':ids} for (r,sig),ids in groups.items() if len(ids)>1],
               'signature_meaning':'active per-device semantics only:program routine/handling/direction,AC comfort sensitivity,water readiness,EV routine/readiness,and confirmation;excludes unused latent dimensions,prose,IDs,exact clock/temperature,AC count and continuous values',
               'uniqueness_quota':None,'population_frequency_claim':False}
    matched=defaultdict(list)
    for hid,p in profiles.items():matched[(p['role'],tuple(sorted({d['kind'] for d in p['devices']})))].append(hid)
    diversity['same_class_same_device_classes']=[{'role':role,'device_classes':list(kinds),'households':ids,
        'qualitative_signatures':len({signature(profiles[h]) for h in ids}),'without_AC':len({signature(profiles[h],('ac',)) for h in ids})}
        for (role,kinds),ids in matched.items() if len(ids)>1]
    missing=[{'household_id':c['household_id'],**v} for c in full_checks for v in c['missing_targets']]
    negotiations=[{'household_id':c['household_id'],**v} for c in full_checks for v in c['member_negotiations']]
    pending=[{'household_id':c['household_id'],**v} for c in full_checks for v in c['pending_A_projection']]
    # Diagnose absence using already declared neighbor calendars and existing
    # qualified people. These are information checks, never a substituted actor
    # or a regeneration/selection of any A/B or preference sample.
    missing_diagnostics=[]
    from .portrait_v2 import local_domain
    for item in missing:
        if item['kind']!='washer':continue
        hid=item['household_id'];c=preference_input(contexts[hid]);c['days']=list(neighbor_calendars[hid].values())
        need=next(n for n in c['declared_service_contracts'] if n['need_id']==item['need_id'])
        values,reason=local_domain(c,need);rights=c['asset_authority']['assets'][need['asset_id']]
        other=[]
        for mid in rights['authorized_operator_ids']:
            if mid==rights.get('registered_operator_id'):continue
            alternative=copy.deepcopy(c);alternative['asset_authority']['assets'][need['asset_id']]['registered_operator_id']=mid
            v,r=local_domain(alternative,need)
            other.append({'member_id':mid,'local_candidate_count':len(v),'cooperation_not_assumed':True})
        missing_diagnostics.append({'household_id':hid,'need_id':need['need_id'],'primary_known_neighbor_candidate_count':len(values),
                                   'primary_reason_with_known_neighbor_evidence':reason,'other_originally_qualified_members':other,
                                   'original_profile_and_primary_handler_changed':False,
                                   'diagnosis':'neighbor_calendar_available_in_source_but_not_portrait_context' if values else 'primary_handler_has_no_complete_local_chain_with_known_neighbors',
                                   'interpretation':'retain missing target;source neighbor context may resolve it' if values else 'other qualified member has local opportunity only;cooperation not assumed'})
    require(all(sha(p)==h for p,h in locks.items()),'ORIGINAL_SOURCE_CHANGED')
    require(all(sha(HERE/p)==h for p,h in methods.items()),'METHOD_CHANGED_DURING_VALIDATION')
    report={'version':VERSION2,'households_requested':50,'households_checked':len(profiles),'pair_requested':64,'pair_compiled':len(pair_rows),
            'pair_engineering_diagnostics':pair_failures,'seed':0,'pair_seeds':list(SEEDS),'loadings':list(LOADINGS),
            'v1_full_profile_replays':len(replay),'source_files_verified_unchanged':len(locks),'original_cases_hash_protected':sum(len(r['original_case_files']) for r in source_records.values()),
            'class_core_violations':0 if len(profiles)==50 and not pair_failures else None,
            'semantic_engineering_diagnostics':[r for r in rows if r['status']!='portrait_semantics_checked'],
            'missing_targets':len(missing),'missing_reason_counts':dict(Counter(r['reason'] for r in missing)),
            'member_negotiation_items':len(negotiations),'pending_A_projection_items':len(pending),'diversity':diversity,
            'missing_root_needs_diagnosed':len(missing_diagnostics),
            'missing_root_diagnosis_counts':dict(Counter(d['diagnosis'] for d in missing_diagnostics)),
            'source_hashes':locks,'method_hashes':methods,'all_original_profiles_calendars_hardware_A_B_and_outcomes_unchanged':True,
            'mature_sampler_and_latent_stream_unchanged':True,'A_B_algorithm_changed':False,'A_B_generated':0,'UI91_changed':False,'EP_runs':0,
            'online_changed':False,'population1000_started':False,'main_updated':False,
            'scope':'household portrait engineering/semantic acceptance only;not A_B or questionnaire readiness or measured behavior validity'}
    save(out/'REPORT.json',report);save(out/'CHECKS50.json',rows);save(out/'SEMANTIC_CHECKS50.json',full_checks)
    save(out/'SOURCE_RECORDS.json',source_records);save(out/'MISSING.json',missing);save(out/'NEGOTIATIONS.json',negotiations);save(out/'PENDING_A_INTERFACE.json',pending)
    save(out/'MACHINE_HANDLING_COMPARISON.json',baseline);save(out/'DIVERSITY.json',diversity)
    save(out/'MISSING_DIAGNOSIS.json',missing_diagnostics)
    save(out/'SUMMARY.json',{'requested':50,'constructed':len(profiles),'records':rows})
    text=['# 两户补前补后（固定种子0、载荷0.7，同一随机流）']
    for hid in PAIR:
        if (hid,.7,0) in paired:
            text+=['## '+hid,'### 补前：v1',render_family(read(out/'before'/f'{hid}.json')),
                   '### 补后：v2',render_family(paired[hid,.7,0]),'### 逐日候选（不是长期习惯或已生成A）',render_dated(paired[hid,.7,0])]
    (out/'BEFORE_AFTER.md').write_text('\n\n'.join(text)+'\n')
    seal(out,{'version':VERSION2,'EP_runs':0,'online_changed':False,'A_B_generated':0})
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--artifacts',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--pair-inputs',type=Path);p.add_argument('--v1-reference',type=Path)
    a=p.parse_args();r=validate(a.artifacts,a.out,a.pair_inputs,a.v1_reference)
    print(json.dumps({k:r[k] for k in ('households_checked','pair_compiled','pair_engineering_diagnostics','v1_full_profile_replays','missing_targets','missing_reason_counts','member_negotiation_items','pending_A_projection_items','semantic_engineering_diagnostics','diversity')},ensure_ascii=False))


if __name__=='__main__':main()
