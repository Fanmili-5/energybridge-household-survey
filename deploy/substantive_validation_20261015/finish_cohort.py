"""Close actual source/physics/UI/protocol evidence before opening the next cohort."""
import argparse,datetime,json,pathlib,subprocess,sys
REPO=pathlib.Path(__file__).resolve().parents[2]
STAGE=REPO/'docs/research/collection-adjustment-20260930/household1000/substantive_repair_v30_20261015'
BASE=REPO/'deploy/formal_questionnaires_20261014'
RUN=REPO.parents[1]
NODE=RUN/'node-v20.19.0-linux-x64/bin/node'
TOOLS=RUN/'tools_v27'

def run(batch):
    sys.path.insert(0,str(STAGE/'code'))
    from common import read,save,sha
    from cohort_gate import require_reviewed_ep,require_original50_acceptance
    scope='original50'if batch=='formal50'else'other950';count=int(batch[6:])
    if count==950:require_original50_acceptance()
    lease=require_reviewed_ep(scope)
    for name in (f'SUBSTANTIVE_{scope}_REVIEW.json',f'CONTROL_SQL_{scope}_REVIEW.json'):
        r=read(STAGE/name);assert r['passed']and r['input_signature']==lease['review']['input_signature']
    root=STAGE/f'formal_release{count}';logdir=STAGE/'validation_logs';logdir.mkdir(exist_ok=True)
    # The real browser hashes JS numbers, not Python's 1.0 representation.
    # Bind before sealing the formal package; never disable the verifier.
    subprocess.run([str(NODE),str(STAGE/'code/bind_frontend.js'),str(STAGE/f'frontend_release{count}')],check=True)
    index=STAGE/f'frontend_release{count}'/f'INDEX{count}.json'
    if root.exists()and read(root/'FORMAL_RELEASE.json')['source_index_sha256']!=sha(index):
        archive=STAGE/'development/superseded_formal_packages'/read(root/'FORMAL_RELEASE.json')['release_signature']
        archive.parent.mkdir(parents=True,exist_ok=True);assert not archive.exists();root.rename(archive)
    steps=[]
    if not root.exists():steps.append(('build',[str(BASE/'build_release.py'),'--source',str(STAGE/f'frontend_release{count}'),'--output',str(root),'--batch',batch,'--world-version','V30']))
    steps.extend([
      ('case',[str(BASE/'release_acceptance.py'),'--release',str(root),'--stage',str(STAGE),'--output',str(STAGE/f'FORMAL_{batch}_CASE_REVIEW.json'),'--node',str(NODE)]),
      ('case_negative',[str(BASE/'test_release_acceptance.py'),'--release',str(root),'--stage',str(STAGE)]),
      ('fixture',[str(BASE/'make_protocol_fixture.py'),'--release',str(root),'--output',str(STAGE/f'PROTOCOL_{batch}_FIXTURE_PRIVATE.json')]),
      ('HTTP',[str(BASE/'test_protocol.py'),'--release',str(root),'--fixture',str(STAGE/f'PROTOCOL_{batch}_FIXTURE_PRIVATE.json')]),
      ('browser',[str(pathlib.Path(__file__).with_name('browser_fixture.py')),'--release',str(root),'--output',str(STAGE/f'BROWSER_{batch}_REVIEW.json'),'--node',str(NODE),'--tools',str(TOOLS),'--maximum-households',str(50 if count==50 else 100)]),
      ('final_contrast',[str(STAGE/'code/final_contrast.py'),'--batch',batch])])
    for label,args in steps:
        print({'batch':batch,'phase':label,'started':datetime.datetime.now(datetime.timezone.utc).isoformat()},flush=True)
        path=logdir/f'{batch}_{label}.log'
        with path.open('w')as output:r=subprocess.run([sys.executable,*args],stdout=output,stderr=subprocess.STDOUT)
        if r.returncode:print(path.read_text()[-7000:],flush=True);raise RuntimeError('Cohort held at '+label)
        if label in ('case_negative','HTTP'):
            result=json.loads(path.read_text().splitlines()[-1]);save(STAGE/(f'CASE_NEGATIVE_{batch}.json'if label=='case_negative'else f'HTTP_{batch}_REVIEW.json'),result)
        print({'batch':batch,'phase':label,'passed':True},flush=True)
    name=('ORIGINAL50'if count==50 else'OTHER950')+'_CONTRAST_ACCEPTANCE.json'
    acceptance=read(STAGE/name)
    for evidence in (f'SUBSTANTIVE_{scope}_REVIEW.json',f'ACTUAL_CONTROL_BINDINGS_{scope}.json',f'CONTROL_SQL_{scope}_REVIEW.json'):
        acceptance['evidence'][evidence]=sha(STAGE/evidence)
    browser=read(STAGE/f'BROWSER_{batch}_REVIEW.json');assert browser['visible_modeled_consequences_match_source']and browser['consequence_cases_checked']==(500 if count==50 else 1000)
    acceptance.update(substantive_decision_contrast_passed=True,actual_IDF_and_SQL_controls_verified=True,
        actor_visible_consequences_checked=True,conditional_reference_only_not_human_validity=True,
        accepted_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    save(STAGE/name,acceptance)
    if count==50:require_original50_acceptance()
    print({'batch':batch,'full_acceptance':True,'cases':count*10,'same_displayed_outcomes':read(STAGE/f'CONTRAST_{batch}_RELEASE_REVIEW.json')['counts']['same_displayed_outcomes'],
        'acceptance_sha256':sha(STAGE/name),'next950_unlocked':count==50,'full1000_EP_started':False},flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--batch',choices=['formal50','formal950'],required=True);run(p.parse_args().batch)
