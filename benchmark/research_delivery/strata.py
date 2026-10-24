"""Descriptive class/date/configuration coverage; never feeds topic selection."""
import argparse
import csv
import datetime as dt
from collections import Counter,defaultdict
from pathlib import Path
from benchmark.ab_generation.common import read,save,digest,canonical,sha


def roster(collection):
    """Use the original date slots, including slots without a selected case."""
    collection=Path(collection)
    pins=read(collection/'PRE_GENERATION.json')['source_sha256'];checked=set()
    for p,h in pins.items():
        if not p.endswith('.json'):continue
        data=read(p)
        if data.get('schema')!='eb.unified.inputs.v1':continue
        if sha(p)!=h:raise ValueError('STRATA_SOURCE_ROSTER_CHANGED')
        records=[]
        for record in data['records']:
            row=dict(record)
            for name in ('context_path','portrait_path'):
                if row.get(name):
                    path=Path(row[name]);row[name]=str(path if path.is_absolute() else Path(p).parent/path)
                    if row[name] not in checked:
                        if row[name] not in pins or sha(row[name])!=pins[row[name]]:
                            raise ValueError('STRATA_FROZEN_SOURCE_CHANGED_OR_UNPINNED')
                        checked.add(row[name])
            records.append(row)
        return records
    raise ValueError('STRATA_ORIGINAL_ROSTER_MISSING')


def build(out,collections=None,coverage_root=None):
    out=Path(out);out.mkdir(parents=True,exist_ok=True);case_rows=[];conditioned=[];sources={}
    if any((out/name).exists() for name in ('STRATA_CASES.csv','CLASS_DEVICE_COVERAGE.csv','STRATA_COVERAGE.json')):
        raise ValueError('STRATA_REPORT_ALREADY_EXISTS;USE_NEW_OUTPUT_DIRECTORY')
    collections=collections or {'FIFTY':out/'fifty','PUBLIC_FRESH':out/'fresh-public/collection'}
    coverage_root=Path(coverage_root or out)
    for label,collection in collections.items():
        collection=Path(collection);roles={}
        for name in ('PRE_GENERATION.json','MATERIALS.json.gz','GENERATION.json'):
            sources[str(collection/name)]=sha(collection/name)
        chosen={(m['household_id'],m['date']):m for m in read(collection/'MATERIALS.json.gz')}
        generation={(r['household_id'],r['date']):r for r in read(collection/'GENERATION.json')}
        for source in roster(collection):
            h,d=source['household_id'],source['date'];m=chosen.get((h,d))
            profile=read(source['portrait_path']) if source.get('portrait_path') else {};role=profile.get('role','unknown');roles[h]=role
            devices=read(source['context_path'])['devices'];config=Counter()
            for v in devices:
                kind=v.get('kind')
                if kind=='washer' and {'washer','dryer'}<=set(v.get('types',[])):kind='automatic_washer_dryer'
                config[kind]+=1
            proposal=m['proposal'] if m else None
            components=proposal['components'] if proposal else [];levels=sorted({c['relative_level'] for c in components})
            families=Counter(c['family'] for c in components)
            shared={'device_preferences':[{k:d.get(k) for k in ('kind','routine_sensitive','handling_change_sensitive','preferred_shift_limit_min','cooling_preferred_C','authorization_preference')}
                for d in profile.get('joint_sampling',{}).get('devices',[])]}
            row=dict(dataset=label,household_id=h,date=d,selected=m is not None,
                generation_status=generation.get((h,d),{}).get('status','generation_record_missing'),
                six_class=role,month=int(d[5:7]),
                day_type='weekend' if dt.date.fromisoformat(d).weekday()>=5 else 'weekday',
                equipment_configuration=canonical(dict(config)),within_class_stable_profile_signature=digest(shared),
                independent_tasks=proposal['independent_units'] if proposal else None,
                changed_physical_devices=len(proposal['changed_assets']) if proposal else None,
                device_families=len(families) if proposal else None,
                same_family_multibatch=any(n>1 for f,n in families.items() if f in ('washer','dryer','dishwasher')) if proposal else None,
                relative_action_positions=';'.join(levels) if proposal else None,
                life_or_service_pressure=bool(proposal['issues']) if proposal else None,
                soft_preference_tension=any(j['soft_preference_tension'] for j in proposal['judgment_context']) if proposal else None,
                member_disagreement=any(j.get('member_opinions_differ') for j in proposal['judgment_context']) if proposal else None,
                consent_obtained=False,physical_status='not_computed')
            case_rows.append(row)
        ledger_path=coverage_root/(label+'_INPUT_OPPORTUNITY_COVERAGE.json.gz');sources[str(ledger_path)]=sha(ledger_path)
        ledger=read(ledger_path);groups=defaultdict(list)
        for day in ledger:
            for e in day['mechanisms']:groups[(roles[day['household_id']],e['family'])].append(e)
        for (role,family),es in sorted(groups.items()):
            potential=[e for e in es if e['status']=='potential']
            conditioned.append(dict(dataset=label,six_class=role,family=family,
                potential_mechanisms=len(potential),direct_candidate_witnesses=sum(bool(e['candidate_witness_ids']) for e in potential),
                selected_direct_witnesses=sum(bool(e['selected_witness_ids']) for e in potential),
                evidence_unknown=sum(e['status']=='unknown' for e in es),inapplicable=sum(e['status']=='inapplicable' for e in es)))
    for name,rows in [('STRATA_CASES.csv',case_rows),('CLASS_DEVICE_COVERAGE.csv',conditioned)]:
        if not rows:continue
        with (out/name).open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    summary={}
    for label in collections:
        rows=[r for r in case_rows if r['dataset']==label]
        selected=[r for r in rows if r['selected']]
        summary[label]=dict(date_slots=len(rows),cases=len(selected),unselected_slots=len(rows)-len(selected),
            generation_statuses=dict(Counter(r['generation_status'] for r in rows)),
            households=len({r['household_id'] for r in rows}),six_classes=dict(Counter(r['six_class'] for r in rows)),
            months=dict(Counter(r['month'] for r in rows)),day_types=dict(Counter(r['day_type'] for r in rows)),
            unique_equipment_configurations=len({r['equipment_configuration'] for r in rows}),
            stable_profile_signatures=len({r['within_class_stable_profile_signature'] for r in rows}),
            joint_tasks=dict(Counter(r['independent_tasks'] for r in selected)),
            changed_physical_devices=dict(Counter(r['changed_physical_devices'] for r in selected)),
            same_family_multibatch_cases=sum(r['same_family_multibatch'] for r in selected),
            relative_positions=dict(Counter(p for r in selected for p in r['relative_action_positions'].split(';') if p)))
    if any(sha(p)!=h for p,h in sources.items()):raise ValueError('STRATA_INPUT_CHANGED_DURING_READ')
    save(out/'STRATA_COVERAGE.json',dict(datasets=summary,source_sha256=sources,
        descriptive_only=True,new_selection_targets_or_quotas=False,primary_denominator_not_changed=True,
        calendar_month_is_not_weather_or_measured_season=True,
        profile_hash_diversity_is_not_human_meaningful_diversity=True,
        slot_denominator_from_original_roster=True,unselected_not_encoded_as_no_opportunity=True,
        independent_tasks_are_not_physical_device_count=True,
        class_proportions_are_not_population_estimates=True))
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--collections');p.add_argument('--coverage-root')
    a=p.parse_args();print(build(a.out,read(a.collections) if a.collections else None,a.coverage_root))
