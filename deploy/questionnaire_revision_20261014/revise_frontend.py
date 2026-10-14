"""Presentation-only update over accepted V27 frontend bytes, in a new directory."""
import argparse,hashlib,json,re,shutil
from pathlib import Path

HERE=Path(__file__).resolve().parent
VERSION='eb.household50.questionnaire.20261014.1'
FIELDS=('profile-data','source-cases-data','source-selection-data','joint-cases-data','visible-inputs-data','source-hashes-data')
RESPONDENT='''<section class="panel respondent-section" aria-labelledby="respondent-heading"><h2 id="respondent-heading">填写者本人信息（选填）</h2><p>请填写您本人的信息，不是所扮演家庭成员的信息。用于分析填写差异，不改变这户家庭的情境。</p><div class="respondent-grid"><label class="field" for="respondent-age">您本人的年龄（岁）<input id="respondent-age" type="number" min="1" max="120" step="1" inputmode="numeric" autocomplete="off" placeholder="可以留空"></label><label class="field" for="respondent-gender">您本人的性别<select id="respondent-gender"><option value="">可以留空</option><option value="female">女</option><option value="male">男</option><option value="other">其他</option><option value="prefer_not_to_say">不愿透露</option></select></label></div></section>'''
STYLE='''.respondent-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.respondent-section p{color:#536963;font-size:.94rem}.device-extra-times{margin-top:8px;font-size:.88rem}.device-extra-times summary{cursor:pointer;color:#536963}.device-extra-times p{margin:5px 0}@media(max-width:600px){.respondent-grid{grid-template-columns:1fr}}\n'''
HELPER='''function displayLabel(e){const short=label(e).split('（完整安排')[0].replace('程序请求','请求').replace('设定温度 ','设定 ').replace('允许加热，目标 ','加热目标 ');const left=Number.isFinite(e.source_start_abs_min)&&e.source_start_abs_min<e.start_abs_min?'← ':'';const right=Number.isFinite(e.source_end_abs_min)&&e.source_end_abs_min>e.end_abs_min?' →':'';return left+short+right;}
 function conciseEvents(events){const merged=[];for(const e of events){const prior=merged[merged.length-1];if(prior&&prior.end_abs_min===e.start_abs_min&&label(prior)===label(e)&&prior.operation_kind===e.operation_kind){prior.end_abs_min=e.end_abs_min;prior.source_end_abs_min=e.source_end_abs_min;prior.end_status=e.end_status;}else merged.push({...e});}return merged;}
 function appendConciseEvents(section,events,base){const merged=conciseEvents(events);for(const e of merged.slice(0,2))section.append(el('p',`${time(e.start_abs_min,base)}—${time(e.end_abs_min,base)} · ${displayLabel(e)}`));const carry=events.some(e=>e.source_start_abs_min<e.start_abs_min||e.source_end_abs_min>e.end_abs_min);if(merged.length>2||carry){const detail=el('details',null,'device-extra-times');detail.append(el('summary','查看完整时段与动作'));for(const e of events)detail.append(el('p',`${time(e.start_abs_min,base)}—${time(e.end_abs_min,base)} · ${label(e)}`));detail.addEventListener('toggle',()=>{if(currentInput&&presentedAt)currentInput.history.push({kind:'visible_context_observation',recorded_at:new Date().toISOString(),fields:snapshot()});});section.append(detail);}}
 '''
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def change(s,old,new):
    if s.count(old)!=1:raise RuntimeError('Expected unique production fragment: '+old[:80])
    return s.replace(old,new,1)
def field(page,id):return json.loads(re.search(r'<script[^>]+id="'+id+r'"[^>]*>(.*?)</script>',page,re.S).group(1))
def build(source,out):
    if out.exists():raise RuntimeError('new release directory required')
    shutil.copytree(source,out,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    index=json.loads((out/'INDEX50.json').read_text());assert len(index['households'])==50
    for n in ['serve50.py','unified_live_server.py','respondent.py']:shutil.copyfile(HERE/'runtime'/n,out/n)
    records=[]
    for row in index['households']:
        p=out/'households'/row['household_id'];page=(p/'index.html').read_text();before={k:field(page,k)for k in FIELDS}
        assert '生活与用电影响'in page and 'id="joint-results"'in page
        page=change(page,'<section class="panel" id="home-panel">',RESPONDENT+'\n<section class="panel" id="home-panel">')
        page=change(page,'家庭用电安排 · 本地体验','家庭用电安排问卷')
        route=row['route'];page=change(page,'<script src="'+route+'/joint-view.js" defer>', '<script src="'+route+'/respondent-info.js" defer></script><script src="'+route+'/joint-view.js" defer>')
        (p/'index.html').write_text(page);assert before=={k:field(page,k)for k in FIELDS}
        js=(p/'joint-view.js').read_text()
        js=change(js,'function renderPlans(c){',HELPER+'function renderPlans(c){')
        js=change(js,'original:a.events.map(e=>','original:conciseEvents(a.events).map(e=>')
        js=change(js,'proposal:b.get(a.asset_id).events.map(e=>','proposal:conciseEvents(b.get(a.asset_id).events).map(e=>')
        assert js.count('label:label(e)')==2
        js=js.replace('label:label(e)','label:displayLabel(e)')
        js=change(js,"for(const e of events)section.append(el('p',`${time(e.start_abs_min,base)}—${time(e.end_abs_min,base)} · ${label(e)}`));",'appendConciseEvents(section,events,base);')
        js=change(js,'async function exportRecord(c,input,expected,answer,rendered,presentedAt){',"async function exportRecord(c,input,expected,answer,rendered,presentedAt,respondent={age_years:null,gender:null}){")
        js=change(js,"schema:'eb.joint_b.local_test_export.v5',status:","schema:'eb.joint_b.local_test_export.v6',questionnaire_ui_version:'"+VERSION+"',respondent:root.EBRespondentInfo.validate(respondent),status:")
        js=change(js,'const serialized=JSON.stringify({case_index:current,answer});','const respondent=root.EBRespondentInfo.read();const serialized=JSON.stringify({case_index:current,answer,respondent});')
        assert js.count('answer,snapshot(),presentedAt)')==2
        js=js.replace('answer,snapshot(),presentedAt)','answer,snapshot(),presentedAt,respondent)')
        (p/'joint-view.js').write_text(js);shutil.copyfile(HERE/'respondent-info.js',p/'respondent-info.js')
        with(p/'joint-view.css').open('a')as f:f.write('\n'+STYLE)
        records.append({'household_id':row['household_id'],'case_count':len(before['joint-cases-data']),'consumer_data_unchanged':True})
    index['questionnaire_ui_version']=VERSION;index['source_world_version']='V27';index['human_collection_release']=False;index['training_release']=False
    (out/'INDEX50.json').write_text(json.dumps(index,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n')
    files={str(p.relative_to(out)):sha(p)for p in sorted(out.rglob('*'))if p.is_file()}
    signature=hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    (out/'DEPLOY_MANIFEST.json').write_text(json.dumps({'schema':'eb.questionnaire_release.v1','questionnaire_ui_version':VERSION,'manifest_sha256':signature,'files':files,'source_world_version':'V27','source_frontend_index_sha256':sha(source/'INDEX50.json'),'preserved_consumer_cases':sum(r['case_count']for r in records),'effects_preserved':True,'respondent_fields_separate_from_role_and_model_input':True,'full1000_EP_launched':False},ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'release':str(out),'signature':signature,'households':50,'cases':500,'worlds_AB_physics_data_changed':False,'questionnaire_ui_version':VERSION}),flush=True)
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--source',type=Path,required=True);a.add_argument('--output',type=Path,required=True);args=a.parse_args();build(args.source,args.output)
