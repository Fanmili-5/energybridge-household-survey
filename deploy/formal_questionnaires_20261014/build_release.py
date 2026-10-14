"""Same mature UI, independently sealed formal50/formal950 release packages."""
import argparse,hashlib,json,re,shutil,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'questionnaire_revision_20261014'))
from revise_frontend import RESPONDENT,STYLE,HELPER,FIELDS,field

VERSION='eb.formal_role_questionnaire.20261014.1'
PANEL='''<section class="panel" id="formal-participation"><h2>参与说明与填写进度</h2><p id="formal-progress"></p><details><summary>阅读参与说明</summary><p id="formal-consent-text"></p></details><div id="formal-consent-controls"><label><input id="formal-consent-accept" type="checkbox"> 我已阅读说明，自愿参与，并理解需要按给定家庭角色作答。</label><p><button id="formal-consent-submit" type="button">确认参与</button></p></div><p id="formal-consent-status" role="status"></p><details><summary>恢复与撤回</summary><p>使用领取时保存的恢复码，可以在正式问卷入口恢复填写。撤回将排除本身份下的全部答卷。</p><button id="formal-withdraw" type="button">撤回全部答卷</button> <button id="formal-logout" type="button">退出当前身份</button></details></section>'''

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def canonical(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def once(s,a,b):
    if s.count(a)!=1:raise RuntimeError('expected exactly one UI source fragment: '+a[:90])
    return s.replace(a,b,1)
def build(source,out,batch,ids=None,world_version='V27',public_prefix=None):
    assert batch in ('formal50','formal950')and not out.exists()
    indexpath=next(source/name for name in('INDEX950.json','INDEX1000.json','INDEX50.json')if(source/name).exists());index=json.loads(indexpath.read_text())
    rows=[r for r in index['households']if ids is None or r['household_id']in ids];assert len(rows)==int(batch[6:])
    out.mkdir(parents=True);report=[];prefix=public_prefix or '/household'+batch[6:];assert re.fullmatch(r'/[a-z][a-z0-9-]{2,40}',prefix)
    for row in rows:
        old=source/'households'/row['household_id'];new=out/'households'/row['household_id'];shutil.copytree(old,new,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        page=(new/'index.html').read_text();before={k:field(page,k)for k in FIELDS};oldroute=row['route'];route=prefix+'-'+row['household_id']
        page=page.replace(oldroute+'/',route+'/')
        if 'id="respondent-age"'not in page:
            page=once(page,'<section class="panel" id="home-panel">',RESPONDENT+'\n<section class="panel" id="home-panel">')
            page=once(page,'<script src="'+route+'/joint-view.js" defer>','<script src="'+route+'/respondent-info.js" defer></script><script src="'+route+'/joint-view.js" defer>')
        page=once(page,'<section class="panel respondent-section"',PANEL+'\n<section class="panel respondent-section"')
        page=re.sub(r'<title>.*?</title>','<title>'+batch[6:]+'户正式问卷 · 家庭用电安排</title>',page,count=1)
        page=page.replace('家庭用电安排体验','家庭用电安排问卷').replace('合成家庭工程体验','参考家庭角色问卷')
        page=page.replace('选择测试家庭','返回正式问卷入口')
        page=page.replace('回答和问题报告会在线保存。','确认参与后，您的答卷会保存，可恢复填写或撤回。')
        page=once(page,'</body>','<script src="'+route+'/formal-client.js" defer></script></body>')
        assert before=={k:field(page,k)for k in FIELDS},'consumer data changed'
        (new/'index.html').write_text(page)
        js=(new/'joint-view.js').read_text()
        if 'function displayLabel(e)'not in js:
            js=once(js,'function renderPlans(c){',HELPER+'function renderPlans(c){')
            js=once(js,'original:a.events.map(e=>','original:conciseEvents(a.events).map(e=>')
            js=once(js,'proposal:b.get(a.asset_id).events.map(e=>','proposal:conciseEvents(b.get(a.asset_id).events).map(e=>')
            assert js.count('label:label(e)')==2;js=js.replace('label:label(e)','label:displayLabel(e)')
            js=once(js,"for(const e of events)section.append(el('p',`${time(e.start_abs_min,base)}—${time(e.end_abs_min,base)} · ${label(e)}`));",'appendConciseEvents(section,events,base);')
            js=once(js,'async function exportRecord(c,input,expected,answer,rendered,presentedAt){','async function exportRecord(c,input,expected,answer,rendered,presentedAt,respondent={age_years:null,gender:null}){')
            js=once(js,"schema:'eb.joint_b.local_test_export.v5',status:","schema:'eb.joint_b.local_test_export.v6',questionnaire_ui_version:'eb.household50.questionnaire.20261014.1',respondent:root.EBRespondentInfo.validate(respondent),status:")
            js=once(js,'const serialized=JSON.stringify({case_index:current,answer});','const respondent=root.EBRespondentInfo.read();const serialized=JSON.stringify({case_index:current,answer,respondent});')
            assert js.count('answer,snapshot(),presentedAt)')==2;js=js.replace('answer,snapshot(),presentedAt)','answer,snapshot(),presentedAt,respondent)')
        js=js.replace("schema:'eb.joint_b.local_test_export.v6'","schema:'eb.role_response.v1'").replace("questionnaire_ui_version:'eb.household50.questionnaire.20261014.1'","questionnaire_ui_version:'"+VERSION+"'")
        js=js.replace("status:'engineering_click_not_human_feedback'","status:'participant_submitted_role_response'")
        js=once(js,'test_feedback:clean','response:clean')
        js=js.replace('human_label_count:0,training_release:false,formal_export_eligible:false','human_label_count:1,training_release:false,collection_release:true')
        js=js.replace('保存工程试填','提交答卷').replace('工程试填已保存；回执编号：','答卷已提交；回执编号：').replace('。不计作正式人类反馈。','。可凭恢复码继续填写或撤回。')
        js=js.replace('合成家庭工程体验','参考家庭角色问卷').replace('回答和问题报告会在线保存。','确认参与后，您的答卷会保存，可恢复填写或撤回。')
        js=once(js,"else{const record=await exportRecord(cases[current],currentInput,hashes[current],answer,snapshot(),presentedAt,respondent);downloadJson(record,'joint-b-local-test.json');q('joint-status').textContent='已下载本地测试记录；未提交，不计作人类反馈。';}","else{throw Error('请从正式问卷入口进入，离线文件不保存答卷。');}")
        js=js.replace("status:'engineering_issue_submission'","status:'participant_issue_submission'")
        (new/'joint-view.js').write_text(js);shutil.copyfile(HERE.parent/'questionnaire_revision_20261014/respondent-info.js',new/'respondent-info.js');shutil.copyfile(HERE/'formal-client.js',new/'formal-client.js')
        css=new/'joint-view.css'
        with css.open('a')as f:f.write('\n'+STYLE+'\n.respondent-grid input,.respondent-grid select{min-height:42px;padding:9px 12px;border:1px solid #d5dfda;border-radius:8px;box-sizing:border-box;font:inherit;width:100%}#formal-participation details{margin:12px 0}#formal-consent-controls label{display:flex;align-items:flex-start;gap:10px}\n')
        report.append({**row,'route':route})
    shutil.copyfile(HERE/'formal-client.js',out/'formal-client.js')
    files={str(p.relative_to(out)):sha(p)for p in sorted(out.rglob('*'))if p.is_file()}
    manifest={'schema':'eb.formal_questionnaire.release.v1','batch':batch,'public_prefix':prefix,'source_world_version':world_version,'questionnaire_ui_version':VERSION,
        'human_collection_release':True,'training_release':False,'scientific_benchmark_validated':False,'households':report,'files':files,
        'preserved_consumer_cases':sum(len(field((out/'households'/r['household_id']/'index.html').read_text(),'joint-cases-data'))for r in report),
        'consumer_role_AB_physics_payload_unchanged':True,'source_index_sha256':sha(indexpath),'source_directory':str(source)}
    signature=hashlib.sha256(canonical(manifest).encode()).hexdigest();manifest['release_signature']=signature
    (out/'FORMAL_RELEASE.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'batch':batch,'households':len(report),'cases':manifest['preserved_consumer_cases'],'signature':signature}),flush=True)
    return manifest

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--batch',required=True);p.add_argument('--partitions',type=Path);p.add_argument('--world-version',default='V27');p.add_argument('--public-prefix');a=p.parse_args()
    ids=set(json.loads(a.partitions.read_text())[a.batch])if a.partitions else None;build(a.source,a.output,a.batch,ids,a.world_version,a.public_prefix)
