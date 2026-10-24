"""Read-only staged validation, explicit denominators and literal walkthroughs."""
import argparse
import copy
import datetime as dt
from collections import Counter,defaultdict
from pathlib import Path
from ..common import read,save,digest,sha,bound
from .contract import config,dates
from .pipeline import build

PAIR=('ordinary-v6-0696','ordinary-v6-0756')


def frozen_inputs(contexts,portraits,out,roster):
    """The accepted portrait roster defines the 50; exclude stray context copies."""
    contexts=Path(contexts);portraits=Path(portraits);out=Path(out);records=[]
    declared={(r['household_id'],r['date']) for r in read(roster)['cases']}
    for p in sorted(portraits.glob('*.json')):
        hid=p.stem;profile=read(p)
        if profile.get('household_id')!=hid:continue
        selected=[]
        for cpath in sorted(contexts.glob(hid+'__*.json.gz')):
            c=read(cpath)
            if c['household_id']!=hid:raise ValueError('CONTEXT_ID_MISMATCH')
            selected.append(dict(household_id=hid,date=c['date'],context_path=str(cpath.resolve()),portrait_path=str(p.resolve())))
        # Canonical filenames are authoritative; backup names cannot add dates.
        selected=[r for r in selected if Path(r['context_path']).name==hid+'__'+r['date']+'.json.gz' and (hid,r['date']) in declared]
        if len(selected)!=10:raise ValueError('FROZEN_TEN_DATES:'+hid+':'+str(len(selected)))
        records.extend(selected)
    if len({r['household_id'] for r in records})!=50:raise ValueError('EXPECTED_ACCEPTED_FIFTY')
    out.mkdir(parents=True,exist_ok=False)
    for name,rs in [('fifty',records),('pair',[r for r in records if r['household_id'] in PAIR])]:
        save(out/(name+'.json'),dict(schema='eb.unified.inputs.v1',mode='audit_frozen',records=rs))
    return dict(households=50,slots=len(records),pair_slots=20)


def portrait_matrix(accepted,out):
    """All predeclared 2x8x4 cells, not a best-looking seed selection."""
    from benchmark.family_generation.validate_portrait_v3 import configured,compile_checked,signature
    from benchmark.family_generation.joint_sampling import VERSION3
    accepted=Path(accepted);out=Path(out);rows=[];fifty=[]
    for loading in (0,.35,.7,.9):
        for seed in range(8):
            for hid in PAIR:
                source=read(accepted/'inputs'/(hid+'.json'))
                p,old,check=compile_checked(configured(source,VERSION3,seed,loading))
                original=read(accepted/'pair'/('loading-'+str(loading))/('seed-'+str(seed))/(hid+'.json'))
                save(out/'profiles'/('loading-'+str(loading))/('seed-'+str(seed))/(hid+'.json'),p)
                rows.append(dict(household_id=hid,seed=seed,loading=loading,profile_sha256=digest(p),
                    accepted_replay=p==original,signature=signature(p),checks=check))
    for f in sorted((accepted/'inputs').glob('*.json')):
        source=read(f);original=read(accepted/'profiles50'/f.name);cfg=original['joint_sampling']['configuration']
        p,old,check=compile_checked(configured(source,VERSION3,cfg['seed'],cfg['loading']))
        fifty.append(dict(household_id=f.stem,profile_sha256=digest(p),accepted_replay=p==original,
            role=p['role'],signature=signature(p),checks=check))
    save(out/'PAIR_MATRIX.json',rows);save(out/'FIFTY_PROFILES.json',fifty)
    summary=dict(pair_cells=len(rows),all_fixed_seeds=list(range(8)),loadings=[0,.35,.7,.9],
        all_pair_replay=all(r['accepted_replay'] for r in rows),fifty=len(fifty),all_fifty_replay=all(r['accepted_replay'] for r in fifty),
        pair_signatures={h:{str(l):len({r['signature'] for r in rows if r['household_id']==h and r['loading']==l}) for l in (0,.35,.7,.9)} for h in PAIR},
        fifty_unique_signatures=len({r['signature'] for r in fifty}),
        scope='unchanged_v3_portrait_replay_and_semantics;not_new_A_generation_or_human_validity')
    save(out/'SUMMARY.json',summary);return summary


def public_inputs(source,out):
    """Six already constructed public families. Never read source questionnaire B."""
    from benchmark.project.context import plan_context
    from benchmark.family_generation.device_persona import from_declared_family
    from benchmark.family_generation.joint_sampling import VERSION3
    from ..collection_thermal import AC_CONTRACT
    source=Path(source);out=Path(out);out.mkdir(parents=True,exist_ok=False);records=[]
    tariff=read(source/'INPUT.json')['tariff'];roles=[]
    for row in read(source/'families/SUMMARY.json')['records']:
        if row['status']!='family_constructed':raise ValueError('PUBLIC_FAMILY_CONSTRUCTION_FAILED')
        hid=row['household_id'];fpath=bound(source/'families',row['path']);family=read(fpath);roles.append(family['archetype'])
        candidate=copy.deepcopy(family);candidate.setdefault('energy_preferences',{})['preference_sampling']=dict(mode=VERSION3,seed=0,loading=.7)
        portrait=from_declared_family(candidate);pp=out/'profiles'/(hid+'.json');save(pp,portrait)
        root=source/'connected/life_A'/hid;manifest=read(root/'MANIFEST.json')
        life=read(bound(root,manifest['records'][0]['path']));world=read(root/'WORLD_INPUT.json')['households'][0]
        chosen=sorted(life['days'])[:10]  # preregistered first ten; no opportunity/outcome filtering
        if len(chosen)!=10:raise ValueError('PUBLIC_TEN_DATES_REQUIRED')
        for date in chosen:
            c=plan_context(life,world,dict(date=date,case_id=hid+'__'+date+'__unified',events=[config()['event']],tariff=tariff),sha(fpath))
            c['reference']['ac_control_contract']=copy.deepcopy(AC_CONTRACT)
            offset=(dt.date.fromisoformat(date)-dt.date.fromisoformat(life['anchor'])).days*1440
            c['physical_ev_connections']=[{**copy.deepcopy(p),'start_min':p['start_min']-offset,'end_min':p['end_min']-offset} for p in life['EV']['connections']]
            cp=out/'contexts'/(hid+'__'+date+'.json.gz');save(cp,c)
            records.append(dict(household_id=hid,date=date,context_path=str(cp.resolve()),portrait_path=str(pp.resolve())))
    if set(roles)!=set('ABCDEF'):raise ValueError('PUBLIC_SIX_CLASSES_REQUIRED')
    save(out/'INPUTS.json',dict(schema='eb.unified.inputs.v1',mode='audit_frozen',records=records));return dict(slots=len(records),roles=roles)


def coverage_report(root):
    """Four-stage ledger independent of candidate-only selection coverage."""
    root=Path(root);selected=set(read(root/'SELECTION.json')['selected_ids']);rows=[];totals=Counter()
    for day in read(root/'GENERATION.json'):
        result=read(root/day['path']);chosen=[r for r in result.get('rows',[]) if r['id'] in selected]
        covered_selected=[]
        descriptors=result.get('factors',[]);domain=result.get('native_domains',[])
        for row in chosen:
            ids=set(row['component_ids']);assignment=[]
            for vals,desc in zip(domain,descriptors):
                v=next((i for i,r in enumerate(vals) if r and r['id'] in ids),0)
                assignment.append(next(k for k,d in enumerate(desc) if v in d['ids']))
            covered_selected.append(assignment)
        for target in result.get('coverage',{}).get('coverage',[]):
            status=target['status'];feasible=status=='feasible';in_selected=any(all(a[i]==v for i,v in target['target']) for a in covered_selected)
            gap=None if in_selected else 'structure_impossible_in_declared_grammar' if status=='infeasible' else 'search_or_evidence_unresolved' if not feasible else 'ten_slot_selection_tradeoff'
            rows.append(dict(household_id=day['household_id'],date=day['date'],target=target['target'],
                conditional_opportunity_status=status,witness=target['witness_row'] is not None,
                candidate_present=feasible,selected=in_selected,gap=gap,scope='declared_finite_native_grammar'))
            totals.update([status,'selected' if in_selected else 'not_selected'])
    save(root/'CONDITIONAL_COVERAGE.json.gz',rows)
    result=dict(targets=len(rows),counts=dict(totals),full_conditioned_denominator_retained=True,
        population_representativeness_claimed=False,missing_is_not_infeasible=True)
    f=totals['feasible'];u=totals['unknown']+totals['unexplored'];s=totals['selected']
    result['selected_coverage_bounds']=dict(lower=s/(f+u) if f+u else None,
        upper=s/f if f else None,known_feasible=f,unknown=u,selected=s,
        meaning='uncertain denominator;not a population statistic;raw grid only')
    save(root/'COVERAGE_SUMMARY.json',result);return result


def clock(t):
    offset,t=divmod(t,1440);return (('次日' if offset==1 else str(offset)+'日' if offset else '')+f'{t//60:02d}:{t%60:02d}')


def walkthrough(root,out):
    root=Path(root);materials=read(root/'MATERIALS.json.gz');lines=['# 两户十天逐项核对','',
        '固定VPP为18:00—19:00。A为原封存计划；B为新版独立候选选题，不覆盖原题。所有物理后果均未计算，不复用旧结果。','']
    for hid in PAIR:
        lines.extend(['## '+hid,'','| 日期 | A→B的具体变化 | 入选后覆盖与取舍 |','|---|---|---|'])
        bydate={r['date']:r for r in materials if r['household_id']==hid}
        for day in [d for d in read(root/'GENERATION.json') if d['household_id']==hid]:
            r=bydate.get(day['date'])
            if not r:lines.append('| '+day['date']+' | 无正式候选 | '+day['status']+'，保留诊断 |');continue
            row=r['proposal'];changes=[]
            for component in row['components']:
                own=[]
                for p in component['patches']:
                    if p['type']=='rows':
                        for z in p['rows']:
                            a=next(x for x in r['A'][p['collection']] if x[p['identity']]==z[p['identity']])
                            if a['start_min']!=z['start_min'] or a['end_min']!=z['end_min']:
                                own.append(z.get('kind','程序')+' '+clock(a['start_min'])+'—'+clock(a['end_min'])+'→'+clock(z['start_min'])+'—'+clock(z['end_min']))
                    elif p['type']=='control_pause':own.append('暂停请求 '+clock(p['start_min'])+'—'+clock(p['end_min']))
                    else:
                        a=next(x for x in r['A']['controls'] if x['asset_id']==p['asset_id'] and x['kind']==p['kind'] and x['start_min']<=p['start_min']<x['end_min'])
                        own.append(clock(p['start_min'])+'—'+clock(p['end_min'])+' '+','.join(k+':'+str(a.get(k))+'→'+str(v) for k,v in p['values'].items()))
                changes.append(component['family']+'('+component['asset_id']+')：'+'；'.join(own))
            why=' / '.join(row['features']['mechanisms'])+'；'+str(row['independent_units'])+'个任务；名义事件变化='+str(round(row['known_event_reduction_kWh'],4))+'kWh'
            if row['unknown_thermal_response']:why+='（热控实际响应未知）'
            why+='；'+('冲突：'+','.join(row['issues']) if row['issues'] else '无已识别计划冲突')
            why+='；'+row['consent_status']
            lines.append('| '+day['date']+' | '+'<br>'.join(changes)+' | '+why+' |')
        lines.append('')
    Path(out).write_text('\n'.join(lines)+'\n');return dict(days=len(materials),path=str(out))


def immutable(before,out):
    files=read(before);changed=[p for p,h in files.items() if not Path(p).is_file() or sha(p)!=h]
    result=dict(checked=len(files),changed=changed,unchanged=not changed);save(out,result);return result


def baseline_audit(inputs,out):
    from .independent import audit
    from .candidates import prepare
    rows=[]
    for item in read(inputs)['records']:
        c=read(item['context_path']);p=read(item['portrait_path']);view=prepare(c,config())
        errors=audit(c,c['A'],c['A'])
        rows.append(dict(household_id=item['household_id'],date=item['date'],role=p['role'],
            original_A_sha256=digest(c['A']),engineering_errors=errors,
            retained_tasks=len(c['A']['tasks']),retained_operations=len(c['A']['operations']),
            outside_window_boundary_missing_chain=[o['need_id'] for o in c['A']['operations'] if o['kind']=='load' and o['start_min']>=c['horizon_min'][1] and not any(t['need_id']==o['need_id'] for t in c['A']['tasks'])],
            profile_is_new_causal_source_of_old_A=False,
            thermal_response=None,actual_outcomes_read=False))
    save(Path(out)/'SLOTS.json',rows)
    result=dict(households=len({r['household_id'] for r in rows}),slots=len(rows),
        engineering_error_slots=sum(bool(r['engineering_errors']) for r in rows),
        errors=dict(Counter(e for r in rows for e in r['engineering_errors'])),
        boundary_evidence_incomplete_slots=sum(bool(r['outside_window_boundary_missing_chain']) for r in rows),
        scope='frozen_A_literal_baseline_only;not_completed_B_shadow_acceptance',
        physical_runs=0,online_changed=False)
    save(Path(out)/'SUMMARY.json',result);return result


def main():
    p=argparse.ArgumentParser();s=p.add_subparsers(dest='stage',required=True)
    f=s.add_parser('frozen-inputs');f.add_argument('--contexts',required=True);f.add_argument('--portraits',required=True);f.add_argument('--out',required=True);f.add_argument('--roster',required=True)
    m=s.add_parser('portraits');m.add_argument('--accepted',required=True);m.add_argument('--out',required=True)
    b=s.add_parser('public-inputs');b.add_argument('--source',required=True);b.add_argument('--out',required=True)
    c=s.add_parser('report');c.add_argument('--root',required=True)
    i=s.add_parser('immutable');i.add_argument('--before',required=True);i.add_argument('--out',required=True)
    z=s.add_parser('baselines');z.add_argument('--inputs',required=True);z.add_argument('--out',required=True)
    a=p.parse_args()
    if a.stage=='frozen-inputs':r=frozen_inputs(a.contexts,a.portraits,a.out,a.roster)
    elif a.stage=='portraits':r=portrait_matrix(a.accepted,a.out)
    elif a.stage=='public-inputs':r=public_inputs(a.source,a.out)
    elif a.stage=='immutable':r=immutable(a.before,a.out)
    elif a.stage=='baselines':r=baseline_audit(a.inputs,a.out)
    else:r={'coverage':coverage_report(a.root),'walkthrough':walkthrough(a.root,Path(a.root)/'TWO_HOUSE_TEN_DAY.md')}
    print(__import__('json').dumps(r,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
