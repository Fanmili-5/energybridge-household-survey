"""Consumer checks types and source identity; backend owns publish/hold decisions."""
from pathlib import Path
import json
import tempfile

from formal_source_consumer import sha
from joint_contract import bind, validate_case
from unified_pipeline import build

HERE=Path(__file__).resolve().parent
policy=HERE/'unified_consumer_policy.json'
direct=json.loads((HERE/'unified_direct_fixture_manifest.json').read_text())
receipt=json.loads((HERE/'unified_direct_fixture_release_receipt.json').read_text())

with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp)
    original_case=HERE/'unified_direct_engineering_fixture.json'
    manifest={**direct,'case_file':{'path':str(original_case),'sha256':sha(original_case)}}
    for status in ('held','published'):
        record={**receipt,'status':status,'role_states':{'engineering-rich-0001':{'status':status}}}
        rp=root/(status+'-receipt.json');rp.write_text(json.dumps(record))
        manifest['backend_release_receipt']={'path':str(rp),'sha256':sha(rp)}
        mp=root/(status+'-manifest.json');mp.write_text(json.dumps(manifest))
        build(mp,None,root/status,policy_path=policy)
        index=json.loads((root/status/'BUILD_INDEX.json').read_text())
        assert index['backend_release_status']==status

    bad={**receipt,'source_content_sha256':'0'*64}
    rp=root/'bad-receipt.json';rp.write_text(json.dumps(bad))
    manifest['backend_release_receipt']={'path':str(rp),'sha256':sha(rp)}
    mp=root/'bad-manifest.json';mp.write_text(json.dumps(manifest))
    try:build(mp,None,root/'bad',policy_path=policy)
    except ValueError as error:assert 'receipt identity/version/source mismatch' in str(error)
    else:raise AssertionError('Cross-source backend receipt was accepted')

    old=HERE/'unified_revision2_manifest.json'
    build(old,['cityrole-0012'],root/'single_class_historical',policy_path=policy)
    index=json.loads((root/'single_class_historical/BUILD_INDEX.json').read_text())
    assert index['backend_release_status'] is None and index['roles']['cityrole-0012']['case_count']==10

    case=json.loads(original_case.read_text())[0]
    case['physical']={'schema':'eb.joint_b.physical.v2','status':'partial','channels':[
        {'kind':'device_electricity','label':'测试','scope':'event','unit':'unknown',
         'A':{'value':1.0,'status':'computed'},'B':{'value':None,'status':'not_computed'},
         'evidence_sha256':'1'*64}],
         'hold_reason':None,'whole_house_net_import':None,'VPP_target_met':None}
    try:bind(case)
    except ValueError as error:assert 'physical channel/unit/scope' in str(error)
    else:raise AssertionError('Unknown physical unit was accepted')

print(json.dumps({'status':'PASS','backend_held_and_published_passed_through':True,
                  'old_single_class_displayed_without_consumer_research_gate':True,
                  'cross_source_receipt_rejected':True,'invalid_unit_rejected':True}))
