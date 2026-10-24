"""Prespecified portrait-only pair/sensitivity validation; no EP or re-selection."""
import argparse
from collections import Counter
import copy
import datetime as dt
import gzip
import json
from pathlib import Path

from .core import HERE, digest, read, save, seal, sha, verify, require, generate
from .device_persona import generate_personas, render_family
from .joint_sampling import VERSION, RULES, coordinates
from .persona_checks import audit_case

EXAMPLES=('ordinary-v6-0696','ordinary-v6-0756')
SEEDS=tuple(range(8))
LOADINGS=(0,.35,.7,.9)


def signature(p):
    return digest([{k:d.get(k) for k in ('kind','tradeoff','cooling_preferred_C','preferred_shift_limit_min','readiness_priority','time_preference','authorization_preference')}
                   for d in p['joint_sampling']['devices']])


def compact(p):
    result=[]
    for d in p['joint_sampling']['devices']:
        result.append({'asset_id':d['asset_id'],'kind':d['kind'],'tradeoff':d['tradeoff'],
                       'soft_shift_limit_min':d['preferred_shift_limit_min'],
                       'cooling_preferred_C':d.get('cooling_preferred_C'),
                       'readiness_priority':d.get('readiness_priority'),
                       'preferred_start_min':d.get('time_preference',{}).get('preferred_start_min'),
                       'missing_time_rows':sum(r.get('preferred_start_min') is None for r in d.get('time_preference',{}).get('per_service',[]))})
    return result


def soft_audit(case, p):
    """New preference tensions are never engineering errors or rejection labels."""
    results=[]; date=case['date']
    lookup={(d['asset_id'],d['kind']):d for d in p['joint_sampling']['devices']}
    a={t['task_id']:t for t in case['plans']['A']['tasks']}
    for arm in ('A','B'):
        for t in case['plans'][arm]['tasks']:
            if not t['need_id'].startswith(date+':'):continue
            d=lookup.get((t['asset_id'],t['kind']))
            if d is None:continue
            pref=next((r for r in d.get('time_preference',{}).get('per_service',[]) if r['need_id']==t['need_id']),None)
            if pref and pref['preferred_start_min'] is not None and t['start_min']!=pref['preferred_start_min']:
                results.append({'arm':arm,'category':'soft_preference_tension','code':'ORIGINAL_PLAN_DIFFERS_FROM_CANDIDATE_SOFT_START',
                                'task_id':t['task_id'],'original_start_min':t['start_min'],'candidate_preferred_start_min':pref['preferred_start_min']})
            if arm=='B' and t['task_id'] in a and d['preferred_shift_limit_min'] is not None and abs(t['start_min']-a[t['task_id']]['start_min'])>d['preferred_shift_limit_min']:
                results.append({'arm':arm,'category':'soft_preference_tension','code':'SHIFT_ABOVE_CANDIDATE_SOFT_PREFERENCE',
                                'task_id':t['task_id'],'candidate_soft_limit_min':d['preferred_shift_limit_min']})
    return results


def mathematical_check():
    import numpy as np
    from scipy.special import ndtri
    from statistics import NormalDist
    rules=read(RULES); rows=[]; max_cdf_error=0
    # These are sampler-unit random vectors, not generated families or physics.
    for loading in LOADINGS:
        pairs=[]
        for seed in range(2048):
            cfg={'mode':VERSION,'seed':seed,'loading':loading}
            x=coordinates(cfg,'sampler-math-only',['a'],rules)['routine_stability']
            y=coordinates(cfg,'sampler-math-only',['b'],rules)['routine_stability']
            pairs.append((float(ndtri(x)),float(ndtri(y))))
            max_cdf_error=max(max_cdf_error,abs(NormalDist().cdf(float(ndtri(x)))-x))
        corr=float(np.corrcoef(np.array(pairs).T)[0,1]); expected=loading**2
        require(abs(corr-expected)<.08,'JOINT_LATENT_CORRELATION_IMPLEMENTATION_CHECK_FAILED')
        rows.append({'loading':loading,'analytic_latent_correlation':expected,'observed_latent_correlation':corr,'absolute_tolerance':.08,'sampler_vectors':2048})
    require(max_cdf_error<1e-12,'JOINT_CDF_REFERENCE_MISMATCH')
    return {'checks':rows,'cdf_reference_max_error':max_cdf_error,'not_household_production_or_empirical_fit':True}


def pipeline_check(root):
    """Six public scenarios only: same facts, seed and original scheduler."""
    from .connect import connect
    from benchmark.ab_generation.common import read as read_life
    cfg=read(HERE/'examples/batch_joint.json');save(root/'REFERENCE_POOL.json',read(HERE/'examples/REFERENCE_POOL.json'))
    results={};families={}
    for mode in ('legacy','joint'):
        spec=copy.deepcopy(cfg)
        if mode=='legacy':spec.pop('preference_sampling')
        save(root/f'{mode}.json',spec);generate(root/f'{mode}.json',root/mode/'families')
        results[mode]=connect(root/mode/'families',root/mode/'connected')
        require(results[mode]['requested']==6 and len(results[mode]['records'])==6,'JOINT_PIPELINE_DENOMINATOR')
        families[mode]=read(root/mode/'families/SUMMARY.json')
    rows=[]
    for old,new in zip(results['legacy']['records'],results['joint']['records']):
        hid=new['household_id'];require(old['household_id']==hid,'JOINT_PUBLIC_IDENTITIES_CHANGED')
        before=read(root/'legacy/families/families'/f'{hid}.json');after=read(root/'joint/families/families'/f'{hid}.json')
        require(all(before[k]==after[k] for k in ('facts','world','shell','life')),'JOINT_FACTS_OR_ORIGINAL_LIFE_CHANGED')
        row={'household_id':hid,'legacy_status':old['status'],'joint_status':new['status'],'facts_hardware_and_original_life_identical':True}
        if old['status']=='A_constructed' and new['status']=='A_constructed':
            runs={}
            for mode in ('legacy','joint'):
                folder=root/mode/'connected/life_A'/hid; index=read(folder/'SUMMARY.json')
                runs[mode]=read_life(folder/index['records'][0]['path'])
            inputs=read(root/'joint/connected/life_inputs'/hid/'LIFE_INPUT.json')['households'][0]
            policy={p['service_id']:p for p in inputs['program_policies']}
            matches=0
            for n in runs['joint']['requirements']:
                if 'service_policy_id' not in n:continue
                date=n['need_id'][:10]; period='weekend' if dt.date.fromisoformat(date).weekday()>=5 else 'weekday'
                base=(dt.date.fromisoformat(date)-dt.date.fromisoformat(runs['joint']['anchor'])).days*1440
                require(n['preferred_start_min']==base+policy[n['service_policy_id']]['preferred_start_min'][period],'JOINT_PREFERENCE_NOT_CONSUMED_BY_ORIGINAL_A')
                matches+=1
            portrait=read(root/'joint/connected'/new['energy_portrait'])
            require(portrait['family_device_profile']['joint_sampling']==after['energy_use_profile']['joint_sampling'],'JOINT_PROFILE_REDRAWN_AFTER_A')
            row.update(preference_requirements_verified=matches,actual_A_changed=digest(runs['legacy']['A'])!=digest(runs['joint']['A']),
                       legacy_unserved=len(runs['legacy']['unserved']),joint_unserved=len(runs['joint']['unserved']),frozen_profile_reused=True)
        rows.append(row)
    return {'records':rows,'new_joint_A_constructed':results['joint']['constructed'],
            'legacy_A_constructed':results['legacy']['constructed'],'EP_runs':0,'old_50_cases_used':False}


def validate(source_pair, artifacts, output):
    source_pair,artifacts,output=map(lambda p:Path(p).resolve(),(source_pair,artifacts,output))
    require(not output.is_relative_to(source_pair) and not output.is_relative_to(artifacts),'JOINT_OUTPUT_MUST_BE_SEPARATE')
    verify(source_pair); prior=read(source_pair/'REPORT.json')
    require(prior['same_role_and_exact_hardware_parameters'] and prior['checked_original_AB_pairs']==20,'JOINT_PAIR_SOURCE_REQUIRED')
    require(all(sha(p)==h for p,h in prior['source_hashes'].items()),'JOINT_ORIGINAL_SOURCE_CHANGED')
    methods={str(p.relative_to(HERE)):sha(p) for p in HERE.glob('*.py')}
    methods.update({str(p.relative_to(HERE)):sha(p) for p in HERE.glob('*.json') if p.name!='PACKAGE_MANIFEST.json'})
    output.mkdir(parents=True,exist_ok=False)
    records=[]; all_seed_profiles={}; full_matrix=[]; default_counts={}; missing=[]; audits=[]
    for hid in EXAMPLES:
        context=read(source_pair/'inputs'/f'{hid}.json'); original=digest(context)
        legacy=generate_personas(context);save(output/'before'/f'{hid}.json',legacy)
        (output/'before'/f'{hid}.md').write_text(render_family(legacy,brief=True))
        input_device_keys={(d['asset_id'],k) for d in context['devices'] for k in d['types']}
        per_loading={}
        for loading in LOADINGS:
            signatures=[]
            for seed in SEEDS:
                sampled=copy.deepcopy(context)
                sampled.setdefault('energy_preferences',{})['preference_sampling']={'mode':VERSION,'seed':seed,'loading':loading}
                p=generate_personas(sampled);joint=p['joint_sampling']
                require(p==generate_personas(sampled),'JOINT_NOT_REPRODUCIBLE')
                require(input_device_keys=={(d['asset_id'],d['kind']) for d in p['devices']},'JOINT_INVENTORY_CHANGED')
                require(joint['retry_count']==0 and all(m['role']==context['role'] for m in joint['member_preferences'].values()),'JOINT_CLASS_OR_RETRY_VIOLATION')
                expected=read(HERE/'DEVICE_PERSONA_RULES.json')['EB_roles'][context['role']]['source_path'].rsplit('/',1)[-1][:-5]
                require(all(m['persona_id']==expected for m in p['household_preferences']['member_profiles']),'JOINT_MEMBER_CROSSED_CLASS')
                for d,old in zip(p['devices'],legacy['devices']):
                    require(set(d['authorization']['standing_consent_actions'])<=set(old['authorization']['standing_consent_actions']),'JOINT_EXPANDED_STANDING_PERMISSION')
                    for row in d['sampled_preferences'].get('time_preference',{}).get('per_service',[]):
                        if row['preferred_start_min'] is None:missing.append({'household_id':hid,'loading':loading,'seed':seed,'kind':d['kind'],**row})
                wash=next(d for d in joint['devices'] if d['kind']=='washer')
                dry=next(d for d in joint['devices'] if d['kind']=='dryer')
                roots={r['need_id']:r for r in wash['time_preference']['per_service']}
                durations={n['need_id']:n['duration_min'] for n in context['declared_service_contracts'] if 'duration_min' in n}
                for r in dry['time_preference']['per_service']:
                    if r['preferred_start_min'] is not None:
                        require(r['preferred_start_min']==roots[r['upstream_need_id']]['preferred_start_min']+durations[r['upstream_need_id']],'JOINT_COMBO_LINK_BROKEN')
                relative=f'profiles/loading-{loading:g}/seed-{seed}/{hid}.json';save(output/relative,p)
                if loading==.7:
                    all_seed_profiles[(hid,seed)]=p
                    (output/relative.replace('.json','.md')).write_text(render_family(p,brief=True))
                row={'household_id':hid,'seed':seed,'loading':loading,'path':relative,'profile_sha256':joint['profile_sha256'],'signature':signature(p),'devices':compact(p)}
                signatures.append(row['signature']);full_matrix.append(row)
            per_loading[str(loading)]=len(set(signatures))
        default_counts[hid]=per_loading
        # Seed zero is declared before seeing results, never a selected nice seed.
        p=all_seed_profiles[(hid,0)]
        release=artifacts/'release-complete500-ui91-physics-v5-rounds';index=read(release/'INDEX50.json')
        public=read(release/'public/households'/f'{hid}.json')
        daymap={d['date']:d for d in context.get('habit_days',context['days'])}
        for item in [r for r in index['cases'] if r['household_id']==hid]:
            case=read(release/'public'/item['path'])
            cpath=artifacts/'collection-complete500-v1/contexts'/f"{hid}__{case['date']}.json.gz"
            with gzip.open(cpath,'rt') as f:c=json.load(f)
            audit=audit_case(case,c,public,p,daymap)
            audit['findings']+=soft_audit(case,p);audits.append(audit)
        require(digest(context)==original,'JOINT_SOURCE_CONTEXT_MUTATED')
        records.append({'household_id':hid,'role':context['role'],'status':'candidate_profile_validated',
                        'input_sha256':original,'seed_zero_profile':next(r['path'] for r in full_matrix if r['household_id']==hid and r['seed']==0 and r['loading']==.7)})
    public_rows=[]; public_unavailable=[]; fixtures=read(HERE/'examples/energy_portrait/input.json')['households']
    for c in fixtures:
        for seed in SEEDS:
            item=copy.deepcopy(c);item.setdefault('energy_preferences',{})['preference_sampling']={'mode':VERSION,'seed':seed}
            p=generate_personas(item);path=f"public-six/{c['role']}/{c['household_id']}/seed-{seed}.json";save(output/path,p)
            public_rows.append({'household_id':c['household_id'],'role':c['role'],'seed':seed,'path':path,'retry_count':p['joint_sampling']['retry_count']})
            for d in p['joint_sampling']['devices']:
                if d['kind'] in ('washer','dryer','dishwasher') and not d['time_preference']['preferred_start_min'] and not any(r['preferred_start_min'] is not None for r in d['time_preference']['per_service']):
                    public_unavailable.append({'household_id':c['household_id'],'role':c['role'],'seed':seed,'asset_id':d['asset_id'],'kind':d['kind'],'reason':d['time_preference']['reason'] or 'missing_feasible_time_or_declared_handler'})
    require(len(public_rows)==len(fixtures)*len(SEEDS) and {r['role'] for r in public_rows}==set('ABCDEF'),'JOINT_PUBLIC_SIX_DENOMINATOR')
    counts={arm:dict(Counter((f['category']+':'+f['code']) for a in audits for f in a['findings'] if f['arm']==arm)) for arm in ('A','B')}
    math_check=mathematical_check(); pipeline=pipeline_check(output/'public-pipeline')
    require(all(sha(p)==h for p,h in prior['source_hashes'].items()),'JOINT_ORIGINAL_SOURCE_CHANGED')
    require(all(sha(HERE/p)==h for p,h in methods.items()),'JOINT_METHOD_CHANGED_DURING_VALIDATION')
    report={'version':VERSION,'seeds':list(SEEDS),'loadings':list(LOADINGS),'pair_portraits':len(full_matrix),'public_six_portraits':len(public_rows),'public_fixture_count':len(fixtures),
            'same_role_and_exact_hardware_parameters':True,'distinct_preference_signatures_by_loading':default_counts,
            'missing_or_no_opportunity_rows':len(missing),'public_unavailable_device_seed_rows':len(public_unavailable),'checked_original_AB_pairs':len(audits),'finding_counts':counts,
            'source_hashes':prior['source_hashes'],'method_hashes':methods,'original_sources_unchanged':True,
            'mathematical_check':math_check,'public_pipeline_check':pipeline,'EP_runs':0,'online_changed':False,'population1000_started':False,'main_updated':False,
            'limits':['unfitted synthetic preference distributions','two-household shadow audit,not population validation','soft conflict is not observed rejection','old A/B and outcomes are not regenerated']}
    save(output/'REPORT.json',report);save(output/'SEED_MATRIX.json',full_matrix);save(output/'MISSING_ROWS.json',missing);save(output/'AB_CHECKS20.json',audits)
    save(output/'PUBLIC_SIX.json',public_rows);save(output/'PUBLIC_UNAVAILABLE.json',public_unavailable);save(output/'SUMMARY.json',{'requested':2,'constructed':2,'records':records})
    text=['# 两户补前补后（固定种子0，载荷0.7；候选画像）','全部种子0—7及四种载荷均保存；这里不挑选其他种子。']
    for hid in EXAMPLES:
        text+=['## '+hid,'### 补前：上一版本的确定性画像',(output/'before'/f'{hid}.md').read_text(),
               '### 补后：类内联合随机画像',render_family(all_seed_profiles[(hid,0)],brief=True)]
    (output/'BEFORE_AFTER.md').write_text('\n\n'.join(text))
    seal(output,{'version':VERSION,'EP_runs':0,'source_pair_manifest_sha256':sha(source_pair/'MANIFEST.json'),'method_hashes':methods})
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source-pair',required=True,type=Path);p.add_argument('--artifacts',required=True,type=Path);p.add_argument('--out',required=True,type=Path)
    a=p.parse_args();r=validate(a.source_pair,a.artifacts,a.out)
    print(json.dumps({k:r[k] for k in ('pair_portraits','public_six_portraits','distinct_preference_signatures_by_loading','missing_or_no_opportunity_rows','checked_original_AB_pairs','finding_counts')},ensure_ascii=False))


if __name__=='__main__':main()
