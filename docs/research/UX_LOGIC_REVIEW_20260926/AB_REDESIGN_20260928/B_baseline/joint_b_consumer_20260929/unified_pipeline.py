"""Manifest-driven local consumer: one case schema and one static renderer."""
from pathlib import Path
from copy import deepcopy
import argparse
import json

from build_local import write_page
from formal_source_consumer import case_from_source, sha
from joint_contract import bind, digest, require, validate_case, UNIFIED_SCHEMA
from legacy_case_adapter import normalize_v1

HERE=Path(__file__).resolve().parent
STATIC_HOME=HERE/'unified_household_view.js'
STATIC_JOINT=HERE/'unified_joint_view.js'
STATIC_FEEDBACK=HERE/'unified_source_draft.js'


def reference(ref,base):
    require(isinstance(ref,dict) and ref.get('path') and ref.get('sha256'), 'Unpinned manifest reference')
    path=Path(ref['path'])
    if not path.is_absolute():path=base/path
    require(path.is_file() and sha(path)==ref['sha256'], 'Manifest file hash mismatch: '+str(path))
    return path


def load_cases(manifest,manifest_path,roles):
    adapter=manifest['adapter'];base=manifest_path.parent
    if adapter in {'legacy_case_json','engineering_fixture_json','unified_case_json'}:
        path=reference(manifest['case_file'],base)
        data=json.loads(path.read_text())
        require(isinstance(data,list),'Case file must be a list')
        selected=[c for c in data if not roles or c['identity']['role_id'] in roles]
        require(selected,'No selected cases')
        return selected
    require(adapter=='formal_source_lock','Unknown batch adapter')
    require(isinstance(manifest.get('proposal_schemas'),list) and manifest['proposal_schemas'],
            'Formal proposal schemas must be declared in manifest')
    snapshot_path=reference(manifest['source_snapshot'],base)
    snapshot=json.loads(snapshot_path.read_text())
    lock_path=reference(snapshot['source_lock'],snapshot_path.parent)
    lock=json.loads(lock_path.read_text())
    for name in ('build_readback','source_revision2_readback'):
        if name in snapshot:reference(snapshot[name],snapshot_path.parent)
    rows={r['role_id']:r for r in snapshot['roles']}
    require(len(rows)==snapshot['household_count']==manifest['expected']['source_households'] and
            len(lock['proposals'])==snapshot['selected_B_count']==manifest['expected']['selected_B_slots'],
            'Formal source counts differ from batch manifest')
    selected_roles=roles or sorted(rows)
    proposals={r:[] for r in selected_roles}
    for proposal in lock['proposals']:
        if proposal['role_id'] in proposals:proposals[proposal['role_id']].append(proposal)
    cases=[]
    for role in selected_roles:
        require(role in rows,'Selected role absent from source')
        row=rows[role]
        if not row['ordinary_A_eligible'] or not proposals[role]:continue
        annual=json.loads(reference(row['annual'],snapshot_path.parent).read_text())
        profile=json.loads(reference(row['profile'],snapshot_path.parent).read_text())
        for proposal in sorted(proposals[role],key=lambda x:x['round_index']):
            cases.append(case_from_source(proposal,annual,profile,row['profile']['sha256'],
                                          row['annual']['sha256'],snapshot['source_lock']['sha256'],
                                          manifest['proposal_schemas']))
    require(cases,'No source cases for selected roles')
    return cases


def apply_sidecar(cases,sidecar_path,sidecar_sha,adapter):
    if sidecar_path is None:return cases
    path=reference({'path':str(sidecar_path),'sha256':sidecar_sha},Path.cwd())
    sidecar=json.loads(path.read_text())
    require(sidecar['schema']=='eb.joint_b.physical_sidecar.v1','Wrong physical sidecar schema')
    engineering=sidecar.get('engineering_fixture_only') is True
    require(not engineering or adapter=='engineering_fixture_json',
            'Engineering physical fixture cannot enter a source batch')
    entries={x['case_id']:x for x in sidecar['entries']}
    require(len(entries)==len(sidecar['entries']),'Duplicate physical sidecar case')
    selected={c['identity']['case_id']:c for c in cases}
    for case_id,entry in entries.items():
        require(case_id in selected,'Physical sidecar case outside selection')
        case=selected[case_id]
        source_case_sha=case['audit'].get('consumer_source_case_sha256') or case['audit']['source_binding'].get('original_case_sha256')
        require(entry['source_case_sha256']==source_case_sha,
                'Physical sidecar has wrong source case')
        required=('profile_sha256','A_plan_sha256','B_plan_sha256','commands_sha256','vpp_sha256')
        require(all(entry.get('source_bindings',{}).get(key)==case['bindings'][key] for key in required),
                'Physical sidecar input binding differs from visible source')
        if not engineering:
            files=entry.get('evidence_files')
            require(isinstance(files,list) and files,'Real physical readback needs pinned output files')
            for ref in files:reference(ref,path.parent)
        require(case['physical']['status']=='not_computed','Physical sidecar would overwrite source result')
        case['physical']=entry['physical']
        if 'impacts' in entry:
            require(case['impacts']==[] and isinstance(entry['impacts'],list),
                    'Physical sidecar would overwrite source impacts')
            case['impacts']=entry['impacts']
        if 'after_horizon' in entry:
            require(case['after_horizon']['status']=='not_provided',
                    'Physical sidecar would overwrite after-horizon evidence')
            case['after_horizon']=entry['after_horizon']
        case['audit']['physical_binding']={'sidecar_sha256':sidecar_sha,
                                          'sidecar_entry_sha256':digest(entry)}
        bind(case)
    return cases


def read_backend_release(manifest,manifest_path):
    ref=manifest.get('backend_release_receipt')
    if ref is None:return None
    path=reference(ref,manifest_path.parent)
    receipt=json.loads(path.read_text())
    source_ref=manifest.get('source_snapshot') or manifest.get('case_file')
    require(receipt.get('schema')=='eb.joint_b.backend_release_receipt.v1' and
            receipt.get('source_version')==manifest['source_version'] and
            receipt.get('source_content_sha256')==source_ref['sha256'] and
            isinstance(receipt.get('status'),str) and receipt['status'] and
            isinstance(receipt.get('role_states',{}),dict),
            'Backend release receipt identity/version/source mismatch')
    for role,state in receipt.get('role_states',{}).items():
        require(isinstance(role,str) and isinstance(state,dict) and
                isinstance(state.get('status'),str) and state['status'],
                'Backend role release state lacks a status')
    return receipt


def build(manifest_path,roles,out_root,sidecar_path=None,sidecar_sha=None,policy_path=None):
    manifest_path=Path(manifest_path)
    manifest_sha=sha(manifest_path);manifest=json.loads(manifest_path.read_text())
    require(manifest['schema']=='eb.joint_b.batch_manifest.v1','Wrong consumer manifest schema')
    require(manifest['adapter'] in {'legacy_case_json','formal_source_lock','engineering_fixture_json','unified_case_json'},
            'Unknown consumer adapter')
    policy=None;policy_sha=None
    if policy_path:
        policy_sha=sha(policy_path)
        policy=json.loads(Path(policy_path).read_text())
        require(policy['schema']=='eb.joint_b.consumer_policy.v1','Wrong policy schema')
        require(manifest.get('source_version') in policy['accepted_source_versions'],
                'Source version not admitted by policy')
        require(manifest.get('policy_version')==policy.get('version') and
                manifest.get('policy_sha256')==policy_sha,
                'Batch source is not bound to this consumer version policy')
    else:
        require(not manifest.get('requires_policy'),'Batch requires a pinned research policy')
    original=load_cases(manifest,manifest_path,roles)
    release=read_backend_release(manifest,manifest_path)
    if manifest['adapter']=='unified_case_json':
        require(release is not None,'Direct unified source needs a pinned backend release receipt')
    if release and 'role_states' in release:
        require(all(c['identity']['role_id'] in release['role_states'] for c in original),
                'Backend release receipt misses a selected household')
    if not roles and manifest['adapter']=='formal_source_lock':
        require(len(original)==manifest['expected']['selected_B_slots'],
                'Full formal source did not yield every selected B slot')
    if not roles and 'case_count' in manifest.get('expected',{}):
        require(len(original)==manifest['expected']['case_count'] and
                len({c['identity']['role_id'] for c in original})==manifest['expected']['households'],
                'Case/household count differs from batch manifest')
    if manifest['adapter']=='unified_case_json':
        cases=[]
        for raw in original:
            require(raw.get('schema')==UNIFIED_SCHEMA,'Direct source must use unified case schema')
            validate_case(raw)
            case=deepcopy(raw)
            case['audit']['consumer_source_case_sha256']=digest(raw)
            case['audit']['consumer_manifest_sha256']=manifest_sha
            cases.append(bind(case))
    else:
        cases=[normalize_v1(c,manifest_sha) for c in original]
    for case in cases:
        case['audit']['consumer_version_policy']={'version':policy.get('version') if policy else None,
                                                   'sha256':policy_sha}
        case['audit']['backend_release']=(release.get('role_states',{}).get(case['identity']['role_id'])
                                          if 'role_states' in release else release['status']) if release else None
        bind(case)
    apply_sidecar(cases,sidecar_path,sidecar_sha,manifest['adapter'])
    by_role={}
    for case in cases:by_role.setdefault(case['identity']['role_id'],[]).append(case)
    index_path=out_root/'BUILD_INDEX.json'
    previous=json.loads(index_path.read_text()) if index_path.exists() else {}
    previous_roles=previous.get('roles',{}) if previous.get('manifest_sha256')==manifest_sha else {}
    entries=dict(previous_roles);changes={}
    for role,group in by_role.items():
        output=out_root/role;output.mkdir(parents=True,exist_ok=True)
        write_page(group,output)
        (output/'household-view.js').write_bytes(STATIC_HOME.read_bytes())
        (output/'joint-view.js').write_bytes(STATIC_JOINT.read_bytes())
        (output/'source-draft.js').write_bytes(STATIC_FEEDBACK.read_bytes())
        files={p.name:sha(p) for p in sorted(output.iterdir()) if p.is_file()}
        prior=previous_roles.get(role,{}).get('files',{})
        changes[role]=[name for name,digest0 in files.items() if prior.get(name)!=digest0]
        entries[role]={'case_count':len(group),'case_ids':[c['identity']['case_id'] for c in group],
                       'files':files,'physical_statuses':{s:sum(c['physical']['status']==s for c in group)
                           for s in ('not_computed','partial','complete','failed')}}
    require(sha(manifest_path)==manifest_sha and
            (policy_path is None or sha(policy_path)==policy_sha),
            'Manifest or policy changed during build')
    index={'schema':'eb.joint_b.build_index.v1','manifest_sha256':manifest_sha,
           'policy_sha256':policy_sha,'physical_sidecar_sha256':sidecar_sha,
           'source_version':manifest['source_version'],'status':'local_engineering_preview',
           'manifest_population_verified':not bool(roles),
           'backend_release_status':release['status'] if release else None,
           'backend_release_receipt_sha256':manifest.get('backend_release_receipt',{}).get('sha256'),
           'roles':entries,'rebuilt_roles':sorted(by_role),'changed_files':changes,
           'human_feedback':0,'collection_release':False}
    index_path.parent.mkdir(parents=True,exist_ok=True)
    index_path.write_text(json.dumps(index,ensure_ascii=False,indent=2)+'\n')
    return {'roles':len(by_role),'cases':len(cases),'changed_files':sum(map(len,changes.values())),
            'index_sha256':sha(index_path)}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--roles',nargs='*');parser.add_argument('--out-root',type=Path,required=True)
    parser.add_argument('--physical-sidecar',type=Path);parser.add_argument('--physical-sidecar-sha256')
    parser.add_argument('--policy',type=Path)
    args=parser.parse_args()
    print(json.dumps(build(args.manifest,args.roles,args.out_root,args.physical_sidecar,
                           args.physical_sidecar_sha256,args.policy),ensure_ascii=False))
