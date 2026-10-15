#!/usr/bin/env python3
"""Read-only entry to the current source snapshot and a prepared research workspace.

No command starts EnergyPlus, calls a model, or turns engineering fills into
human answers. Production scripts are listed explicitly rather than imported
because their imports can read protected inputs or write stage outputs.
"""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
PUBLIC = REPO / 'docs/household1000'
REL = Path('docs/research/collection-adjustment-20260930/household1000')


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def source_check():
    manifest = read(PUBLIC / 'SOURCE_SNAPSHOT.json')
    errors = []
    for row in manifest['source_files']:
        path = REPO / row['path']
        if not path.is_file() or sha(path) != row['published_sha256']:
            errors.append(row['path'])
    print(json.dumps({'checked_source_files': len(manifest['source_files']),
                      'failures': errors, 'scope': 'published bytes only;not physics or human validity'},
                     ensure_ascii=False, indent=2))
    return bool(errors)


def doctor(workspace):
    base = workspace / REL
    rows = []
    for name in ['CURRENT_STATIC_INPUTS.json', 'CURRENT_TEST50.json']:
        path = base / name
        row = {'input': str(REL / name), 'available': path.is_file()}
        if path.is_file():
            pointer = read(path)
            delivery_name=pointer.get('delivery_path') or pointer.get('delivery') or pointer.get('acceptance_summary')
            if delivery_name:
                delivery=base/delivery_name
                row['delivery_present']=delivery.is_file()
                if pointer.get('delivery_sha256'):
                    row['delivery_hash_matches']=delivery.is_file()and sha(delivery)==pointer['delivery_sha256']
            row['scope']=pointer.get('acceptance','historical static inputs')
        rows.append(row)
    stage = read(PUBLIC / 'STATUS.json')['active_stage']
    if stage=='contrast_repair_v29_20261015':
        names=['SELECTION1000.json','PARTITIONS.json','PROTOCOL_V29.json',
               'CONTRAST_FULL_RULE_DRY_RUN.json','PRE_EP_original50.json','PRE_EP_other950.json',
               'PRE_EP_weather_sensitivity.json','PHYSICS_original50_REVIEW.json',
               'PHYSICS_other950_REVIEW.json','PHYSICS_weather_sensitivity_REVIEW.json',
               'PUBLIC_CONTRAST_SUMMARY.json','PHYSICAL_PRODUCTION_COMPLETE.json']
    elif stage=='formal50_950_production_v28_20261014':
        names=['SELECTION1000.json','PARTITIONS.json','STATIC_PRODUCTION_COMPLETE.json',
               'PRE_EP_original50.json','PRE_EP_other950.json','PRE_EP_weather_sensitivity.json',
               'PHYSICS_original50_REVIEW.json','PHYSICS_other950_REVIEW.json',
               'PHYSICS_weather_sensitivity_REVIEW.json','PHYSICAL_PRODUCTION_COMPLETE.json']
    else:
        names=['SELECTION1000.json','SELECTION50.json','PRE_EP_SCIENTIFIC_REVIEW.json',
               'READBACK_all_REVIEW.json','FINAL_ACCEPTANCE.json','DELIVERY.json']
    for name in [stage+'/'+name for name in names]:
        rows.append({'input': str(REL / name), 'available': (base / name).is_file()})
    print(json.dumps({'workspace': str(workspace), 'inputs': rows,
                      'scope': 'availability only;public checkout excludes protected research inputs',
                      'EP_started': False}, ensure_ascii=False, indent=2))
    return 0


def check_bindings(workspace, scope):
    stage = read(PUBLIC / 'STATUS.json')['active_stage']
    base = workspace / REL / stage
    modern = (base / 'PARTITIONS.json').is_file()
    selection_path = base / ('SELECTION1000.json' if scope == 'static1000' or modern else 'SELECTION50.json')
    if not selection_path.is_file():
        print(json.dumps({'status': 'missing_prepared_inputs', 'selection': str(selection_path),
                          'instruction': 'See docs/household1000/INPUTS.md;no data are downloaded automatically.'}))
        return 2
    selection = read(selection_path)
    if modern and scope == 'pilot50':
        ids = set(read(base / 'PARTITIONS.json')['formal50'])
        selection['records'] = [h for h in selection['records'] if h['household_id'] in ids]
    expected = 1000 if scope == 'static1000' else 50
    errors, pairs, residents = [], 0, 0
    if len(selection['records']) != expected:
        errors.append('selection_household_count')
    for household in selection['records']:
        world_path = base / household['world_path']
        world = read(world_path)
        residents += world['N']
        if sha(world_path) != household['world_sha256']:
            errors.append(household['household_id'] + ':world_file_hash')
        if len(world['members']) != world['N']:
            errors.append(household['household_id'] + ':roster_count')
        if len(household['rounds']) != 10:
            errors.append(household['household_id'] + ':round_count')
        for record in household['rounds']:
            pair_path = base / record['pair_path']
            pair = read(pair_path)
            pairs += 1
            if sha(pair_path) != record['pair_sha256']:
                errors.append(pair['case_id'] + ':pair_file_hash')
            checks = {
                'world_binding': pair['world_sha256'] == world['world_content_sha256'],
                'parameter_binding': pair['parameter_pack_sha256'] == world['parameter_pack_sha256'],
                'same_needs': pair['needs_A'] == pair['needs_B'],
                'A_frozen': pair['A_frozen_before_B_sha256'] == canonical_sha(pair['A']),
                'date_binding': pair['date'] == record['date'],
                'household_binding': pair['household_id'] == world['household_id'],
            }
            errors.extend(pair['case_id'] + ':' + key for key, value in checks.items() if not value)
    print(json.dumps({'scope': scope, 'households': len(selection['records']),
                      'residents': residents, 'pairs': pairs, 'failures': errors,
                      'EP_started': False, 'human_answers_created': 0,
                      'claim': 'file and common-input binding integrity only'}, ensure_ascii=False, indent=2))
    return bool(errors)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('status')
    sub.add_parser('stages')
    sub.add_parser('check-source')
    generation_parser=sub.add_parser('require-generation')
    generation_parser.add_argument('--workspace',type=Path,default=REPO)
    generation_parser.add_argument('--scope',choices=['static1000','full1000EP'],default='static1000')
    doctor_parser = sub.add_parser('doctor')
    doctor_parser.add_argument('--workspace', type=Path, default=REPO)
    binding_parser = sub.add_parser('check-bindings')
    binding_parser.add_argument('--workspace', type=Path, required=True)
    binding_parser.add_argument('--scope', choices=['static1000', 'pilot50'], default='pilot50')
    args = parser.parse_args()
    if args.command == 'status':
        print((PUBLIC / 'STATUS.json').read_text())
        return 0
    if args.command == 'stages':
        print((PUBLIC / 'PIPELINE.json').read_text())
        return 0
    if args.command == 'check-source':
        return source_check()
    if args.command == 'require-generation':
        base=args.workspace.resolve()/REL
        pointer=read(base/'CURRENT_GENERATION_REQUIREMENTS.json')
        entry=base/pointer['gate_entry']
        if not entry.is_file():
            print(json.dumps({'generation_allowed':False,'EP_allowed':False,'reason':'prepared generation entry missing'}))
            return 2
        if pointer.get('gate_kind') in ('v28_readonly_cohort_receipts','v29_readonly_contrast_receipts'):
            stage = base / pointer['stage']
            if not (stage / 'SELECTION1000.json').is_file():
                print(json.dumps({'generation_allowed': False, 'EP_started': False,
                                  'reason': 'protected current school inputs missing'}))
                return 2
            code = '''import sys,json
from pathlib import Path
stage=Path(sys.argv[1]);sys.path.insert(0,str(stage/'code'))
from cohort_gate import require_reviewed_ep
scopes=['original50'] if sys.argv[2]=='static1000' else ['original50','other950','weather_sensitivity']
for scope in scopes:
    lease=require_reviewed_ep(scope)
    report=json.loads((stage/('PHYSICS_'+scope+'_REVIEW.json')).read_text())
    assert report['acceptance_passed'] and not report['failures']
    assert report['input_signature_at_readback']==lease['review']['input_signature']
if (stage/'PROTOCOL_V29.json').exists():
    from cohort_gate import require_original50_acceptance
    require_original50_acceptance()
    import hashlib
    for name in ('ORIGINAL50_CONTRAST_ACCEPTANCE.json','OTHER950_CONTRAST_ACCEPTANCE.json'):
        accepted=json.loads((stage/name).read_text());assert accepted['passed']
        for file,digest in accepted['evidence'].items():assert hashlib.sha256((stage/file).read_bytes()).hexdigest()==digest
    final=json.loads((stage/'PHYSICAL_PRODUCTION_COMPLETE.json').read_text())
    assert final['passed'] and final['verified_input_bound_run_sides']==21440
print(json.dumps({'current_content_bound_reference_receipts':'pass','scopes':scopes,'EP_started':False,'human_answers_created':0}))
'''
            return subprocess.run([sys.executable, '-B', '-c', code, str(stage), args.scope],
                                  cwd=args.workspace.resolve()).returncode
        # The school gate verifies actual accepted bytes and frozen allocation;
        # no JSON status flag admits generation. This command starts no engine.
        return subprocess.run([sys.executable,str(entry),args.scope],cwd=args.workspace.resolve()).returncode
    if args.command == 'doctor':
        return doctor(args.workspace.resolve())
    return check_bindings(args.workspace.resolve(), args.scope)


if __name__ == '__main__':
    sys.exit(main())
