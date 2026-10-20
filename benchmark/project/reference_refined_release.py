"""Restore the reviewed UI91 presentation over a sealed new-B release.

Preserve every frozen A/B case byte. Enrich profiles only with the identical
reviewed room geometry. Old cases, displays, prices and physics are never read.
The existing v69 response/storage protocol is distinct from the UI91 layout.
"""
import argparse
import copy
import json
import shutil
import subprocess
from pathlib import Path
from benchmark.ab_generation.common import digest, read, save, sha
from .questionnaire import COLLECTOR, HERE, UI

ASSETS=HERE/'refined91'
PRESENTATION='eb.questionnaire50.refined.v91.clean.v2'


def section(source, name, following):
    a=source.index('  function '+name+'(')
    b=source.index('  function '+following+'(',a) if following else len(source)
    return source[a:b]


def participant_renderer(source):
    """Refresh display only; source asset IDs, commands and results stay intact."""
    compare=(ASSETS/'compare_nodes.js').read_text()
    source=source.replace(section(source,'familyModel','serviceLines'),section(compare,'familyModel','sideBySide'))
    a=source.index('  function housingPreview(');b=source.index('  function sideBySide(',a)
    source=source[:a]+section(compare,'housingPreview','familyModel')+source[b:]
    a=source.index('  // UI91 presentation over frozen proposal data.');b=source.index('  function displayed(',a)
    source=source[:a]+(ASSETS/'pending_nodes.js').read_text()+'\n'+source[b:]
    a=source.index('  const deviceName = ');b=source.index('\n',a)
    source=source[:a]+"  const deviceName = d => d.types.map(k=>({washer:'洗衣机',dryer:'烘干机'}[k]||LABELS[k])).join('、');"+source[b:]
    a=source.index('  function deviceLabels(');b=source.index('  // One model',a)
    source=source[:a]+source[a:b].replace('for(const d of p.devices)', 'for(const d of displayDevices(p))')+source[b:]
    a=source.index('  function housingAnnotationPlan(');b=source.index('  function housingDrawing(',a)
    drawing=(ASSETS/'housing_drawing.js').read_text()
    source=source[:a]+section(drawing,'housingAnnotationPlan','housingDrawing')+source[b:]
    a=source.index("    result.schedule=");b=source.index('    return result;',a)
    source=source[:a]+"    result.schedule='';\n"+source[b:]
    if '  function renderPlans(' in source:
        a=source.index('  function renderPlans(');b=source.index('  function renderEffects(',a)
        source=source[:a]+source[b:]
    source='\n'.join(line for line in source.split('\n') if not line.strip().startswith("document.addEventListener('toggle',"))
    if "if(physical_review?.status==='computed'){q('score-note')" in source:
        a=source.index("if(physical_review?.status==='computed'){q('score-note')");b=source.index('renderFamily();',a)
        source=source[:a]+"q('score-note').textContent='1分很不合适，5分很合适；可填一位小数。';"+source[b:]
    source=source.replace("presentation_revision:'eb.questionnaire50.refined.v91.newAB.v1'", "presentation_revision:'"+PRESENTATION+"'")
    if "Number.isInteger(a[key])" not in source:source=source.replace("root.EBRequiredResponse(a);", "root.EBRequiredResponse(a);\n    for(const key of ['score','comfort_score','energy_score','vpp_score'])if(!Number.isInteger(a[key]))throw Error('四项评分均须为0—5的整数。');")
    source=source.replace('1分很不合适，5分很合适；可填一位小数。','0分很不合适，5分很合适。')
    return source


def participant_html(html):
    """Remove repeated display notes, keeping the form's required input contract."""
    import re
    html=re.sub(r'<small>[^<]*</small>', '', html)
    html=re.sub(r'<p class="section-note">A为原安排，B为调整后安排。</p>', '', html)
    html=re.sub(r'(<p id="score-note">).*?(</p>)', r'\g<1>1分很不合适，5分很合适；可填一位小数。\2', html)
    html=html.replace('给这次调整打分','给B方案打分')
    html=html.replace('请按给定家庭角色作答。展示结果不会改变现实电器的设置。','请按这户家庭的情况作答。')
    html=html.replace('1分很不合适，5分很合适；可填一位小数。','0分很不合适，5分很合适。')
    template=(ASSETS/'index.html').read_text()
    start='        <div class="rating-grid">';end='        <label class="field reason-label"'
    a=html.index(start);b=html.index(end,a)
    html=html[:a]+template[template.index(start):template.index(end)]+html[b:]
    return html


def renderer(base):
    source=base
    compare=(ASSETS/'compare_nodes.js').read_text()
    family=section(compare,'familyModel','sideBySide')
    source=source.replace(section(source,'familyModel','requestModel'),family)
    source=source.replace(section(source,'changesModel','serviceLines'),'')
    source=source.replace(section(source,'impactModel','displayed'),'')
    source=source.replace(section(source,'requestModel','serviceLines'),'')
    additions='\n'.join([(ASSETS/'housing_drawing.js').read_text(),
        section(compare,'housingPreview','familyModel'),
        section(compare,'sideBySide',None),(ASSETS/'pending_nodes.js').read_text()])
    source=source.replace('  function displayed(c,p){', additions+'\n  function displayed(c,p){')
    source=source.replace("root.EBSimple50={revision:REVISION,", "root.EBSimple50={presentation_revision:'eb.questionnaire50.refined.v91.newAB.v1',housingGeometry,housingDrawing,presentationNodes:(c,p)=>({family:familyModel(c,p),request:requestModel(c),changes:changesModel(c,p),impacts:impactModel(c,p)}),revision:REVISION,")
    source=source.replace("['svg','path','circle','rect'].includes(n.tag)","['svg','g','defs','filter','feGaussianBlur','linearGradient','stop','line','path','circle','rect','polygon','text','title'].includes(n.tag)")
    source=source.replace("    q('plans-details').open=false;q('plans').replaceChildren();plansRendered=false;",'')
    source=source.replace("  q('plans-details').addEventListener('toggle',()=>{if(q('plans-details').open)renderPlans();root.EBCollection.observeSchedule(q('plans-details').open);});", "  document.addEventListener('toggle',e=>{if(e.target.id==='plans-details'&&e.target.isConnected)root.EBCollection.observeSchedule(e.target.open);},true);")
    # This bank has exactly one B per original date. Keep UI91/v69's date-valued
    # selector so the established next-question and resume protocol agree.
    source=source.replace("x.case_id===q('case-date').value","x.date===q('case-date').value")
    source=source.replace("const o=el('option',x.date+' · 方案'+(index.cases.filter(r=>r.household_id===x.household_id).indexOf(x)+1));o.value=x.case_id;", "const o=el('option',x.date);o.value=x.date;")
    source=source.replace("dates(params.get('case_id')||data.resume_case_id)", "dates(index.cases.find(x=>x.case_id===params.get('case_id'))?.date||params.get('date')||data.resume_date)")
    source=source.replace('let index,current,profile,row,serial=0,loading=true,plansRendered=false;', 'let index,current,profile,row,physicalReviews=null,serial=0,loading=true,plansRendered=false;')
    source=source.replace('profile=p;current=c;renderFamily();', "profile=p;const physical_review=physicalReviews?.cases[c.case_id];if(physical_review&&physical_review.source_frozen_pair_sha256!==c.bindings.source_pair_sha256)throw Error('仿真结果与本题方案不一致。');current=physical_review?{...c,physical_review}:c;q('score-note').textContent='1分很不合适，5分很合适；可填一位小数。';renderFamily();")
    source=source.replace("json('index.json').then(data=>{\n    index=data;", "json('index.json').then(async data=>{\n    index=data;if(data.physical_review_index)physicalReviews=await json(data.physical_review_index.path,data.physical_review_index.sha256);")
    return participant_renderer(source)


def build(proposal_release, frontend_source, out):
    proposal_release,frontend_source,out=map(lambda p:Path(p).resolve(),(proposal_release,frontend_source,out))
    import sys
    sys.path.insert(0,str(COLLECTOR))
    from release import Release
    parent=Release(proposal_release)
    if parent.manifest.get('outcome_status')!='not_computed':raise ValueError('PENDING_NEW_B_RELEASE_REQUIRED')
    if len({(r['household_id'],r['date']) for r in parent.records.values()})!=len(parent.records):raise ValueError('ONE_B_PER_DATE_REQUIRED_BY_UI91_COLLECTION')
    reviewed=read(frontend_source/'UI_RELEASE.json');pins=read(ASSETS/'SOURCE.json')
    if reviewed['release_sha256']!=pins['source_release_sha256'] or digest({k:v for k,v in reviewed.items() if k!='release_sha256'})!=reviewed['release_sha256']:raise ValueError('UI91_SOURCE_IDENTITY_CHANGED')
    for relative,expected in pins['files'].items():
        if sha(ASSETS/relative)!=expected:raise ValueError('UI91_ASSET_CHANGED:'+relative)
    shutil.copytree(proposal_release,out)
    public=out/'public'
    html=(ASSETS/'index.html').read_text()
    html=html.replace('同源50户 · 本地预览','50户正式问卷')
    html=html.replace('<button id="show-recovery" class="text-button" type="button">保存与恢复</button>','')
    html=html[:html.index('<dialog id="recovery-dialog"')]+html[html.index('<footer>'):]
    html=html.replace(' hidden id="collection-', ' id="collection-')
    html=html.replace(' id="vpp-request" class="request-note" hidden',' id="vpp-request" class="request-note"')
    html=html.replace('VPP达标结果已单独列出。','实际用电、费用、室温和VPP达标情况尚未计算，请根据提议安排判断。')
    html=html.replace('<div class="score-heading"><h3>给这次调整打分</h3><p>','<div class="score-heading"><h3>给这次调整打分</h3><p id="score-note">')
    html=html.replace('室温与生活变化是否适合这户家庭','温控请求与生活安排是否适合这户家庭')
    html=html.replace('用电时段与费用变化是否适合这户家庭','用电时段与设备安排是否适合这户家庭')
    html=html.replace('此入口为本地预览。','凭恢复码可换设备续填。')
    (public/'index.html').write_text(participant_html(html))
    (public/'view.css').write_bytes((ASSETS/'view.css').read_bytes())
    (public/'required-response.js').write_bytes((ASSETS/'required-response.js').read_bytes())
    (public/'view.js').write_text(renderer((public/'view.js').read_text()))
    instructions=read(out/'ANSWER_INSTRUCTIONS.json')
    instructions['scores']['energy_score']['label']='用电与费用'
    instructions.update(decimal_places=0,score_values=[0,1,2,3,4,5],range=[0,5],anchors={'0':'很不合适','5':'很合适'})
    save(out/'ANSWER_INSTRUCTIONS.json',instructions)
    housing_index=read(frontend_source/'public/display-index.json')
    if sha(frontend_source/'public/display-index.json')!=reviewed['files']['public/display-index.json']:raise ValueError('UI91_HOUSING_INDEX_CHANGED')
    index=read(out/'INDEX50.json');profile_review=[]
    for hid in index['households']:
        original=read(public/'households'/(hid+'.json'))
        if sha(frontend_source/'public/households'/(hid+'.json'))!=index['profiles_sha256'][hid]:raise ValueError('UI91_AND_NEW_B_FAMILY_DIFFER:'+hid)
        ref=housing_index['households'][hid];source=frontend_source/'public'/ref['path']
        if sha(source)!=ref['sha256'] or reviewed['files'].get('public/'+ref['path'])!=ref['sha256']:raise ValueError('UI91_HOUSING_CHANGED:'+hid)
        enriched={**original,'display_housing':read(source)}
        save(public/'households'/(hid+'.json'),enriched)
        profile_review.append({'household_id':hid,'original_profile_sha256':index['profiles_sha256'][hid],
            'UI91_housing_sha256':ref['sha256'],'original_fields_unchanged':{k:v for k,v in enriched.items() if k!='display_housing'}==original})
        index['profiles_sha256'][hid]=sha(public/'households'/(hid+'.json'))
    index['presentation_revision']=PRESENTATION
    save(public/'index.json',index)
    save(out/'PROFILE_GEOMETRY_REVIEW.json',{'records':profile_review,'old_physical_results_read':False})
    for n in ['DISPLAY_MODELS.json','DISPLAY_MODELS50.json']:
        (out/n).unlink(missing_ok=True)
    run=subprocess.run(['node',str(HERE/'verify_refined_display.js'),str(out)],capture_output=True,text=True)
    if run.returncode:raise ValueError(run.stderr[-4000:])
    save(out/'DISPLAY_MODELS50.json',read(out/'DISPLAY_MODELS.json'))
    index['ui_assets_sha256']={p.name:sha(p) for p in public.iterdir() if p.is_file()};save(out/'INDEX50.json',index)
    manifest=copy.deepcopy(parent.manifest)
    manifest.update(presentation_revision=index['presentation_revision'],production_deployed=False)
    manifest['cohort_id']='reference50-v4-ui91-proposal-20261020'
    manifest['source_pins'].update(parent_proposal_release_sha256=parent.signature,UI91_release_sha256=reviewed['release_sha256'],
        presentation_builder_sha256=sha(Path(__file__)))
    manifest['profile_extension']='Only display_housing added from the reviewed UI91; all original family/device fields unchanged.'
    (out/'FORMAL_RELEASE.json').unlink()
    manifest['files']={str(p.relative_to(out)):sha(p) for p in sorted(out.rglob('*')) if p.is_file()}
    manifest['release_sha256']=digest({k:v for k,v in manifest.items() if k!='release_sha256'})
    save(out/'FORMAL_RELEASE.json',manifest)
    checked=Release(out)
    assert all(sha(public/r['path'])==r['sha256'] for r in parent.index['cases'])
    return {'release_sha256':checked.signature,'cases':len(checked.records),'unchanged_case_bytes':len(parent.records),
        'housing_layouts':len(profile_review),'presentation_revision':index['presentation_revision'],'new_EP_runs':0,'online_changed':False}


def build_review_preview(release, results, out):
    """Separate read-only review; never change the sealed collection condition."""
    release,results,out=map(lambda p:Path(p).resolve(),(release,results,out))
    from benchmark.ab_generation.common import verify,seal
    verify(results);m=read(release/'FORMAL_RELEASE.json');rows=read(results/'RESULT_INDEX500.json')['records']
    shutil.copytree(release/'public',out);index=read(out/'index.json');by={r['case_id']:r for r in index['cases']};reviews={}
    for r in rows:
        case=read(out/by[r['case_id']]['path'])
        if case['bindings']['source_pair_sha256']!=r['source_frozen_pair_sha256']:raise ValueError('REVIEW_CASE_RESULT_MISMATCH')
        if r['status']=='computed' and r['actual_outcomes']['simulated_facility_cost']['currency']!='CNY':raise ValueError('REVIEW_COST_CURRENCY_UNDECLARED')
        reviews[r['case_id']]={k:r.get(k) for k in ('status','actual_outcomes','reason','audit_status','source_frozen_pair_sha256')}
    save(out/'physical-review.json',{'cases':reviews})
    index['physical_review_index']={'path':'physical-review.json','sha256':sha(out/'physical-review.json')};save(out/'index.json',index)
    html=(out/'index.html').read_text().replace('src="collection-client.js"','src="preview-client.js"').replace('50户正式问卷','UI91 · 方案与仿真核对').replace('<div class="collection-toolbar">','<div class="collection-toolbar" hidden>')
    html=html.replace('草稿自动保存，提交后生成回执。凭恢复码可换设备续填。','只读核对页：按本题版本显示仿真状态，不保存正式答卷。')
    (out/'index.html').write_text(html)
    client=(HERE/'preview-client.js').read_text().replace('资料预览：后果未计算；可检查填写交互，内容不会提交到正式采集库。','资料预览：后果状态按本题资料标注；内容不会提交到正式采集库。')
    (out/'preview-client.js').write_text(client)
    return {'parent_collection_release_sha256':m['release_sha256'],'result_manifest_sha256':sha(results/'MANIFEST.json'),
        'cases':len(reviews),'formal_collection':False,'answers_written':0}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--proposal-release',required=True);p.add_argument('--frontend-source',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();print(json.dumps(build(a.proposal_release,a.frontend_source,a.out),ensure_ascii=False))
