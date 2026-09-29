"""Build an isolated file-openable fixture page; never changes online v5."""
from copy import deepcopy
from pathlib import Path
import argparse,json,re,sys,hashlib
from joint_contract import bind,canonical,digest,apply_commands,visible_input,require
HERE=Path(__file__).resolve().parent
ROOT=next(p for p in HERE.parents if (p/'realtime_pilot').is_dir())
BASE=ROOT/'artifacts/benchmark_rebuild_20260929/static-experience-v5'
DATA=ROOT/'artifacts/benchmark_rebuild_20260929/current-source-display-v6.json'

def fixtures():
    data=json.loads(DATA.read_text());role='cityrole-0019';scene=data['cases_by_role'][role][2];profile=data['profiles'][role]
    day=scene['artifact']['day_index'];base=day*1440
    A={'role_id':role,'date':scene['artifact']['date'],'window_start_abs_min':base,'window_end_abs_min':base+2880,'rows':[]}
    for row in scene['model_schedule_48h']:
        events=[]
        for n,span in enumerate(row['original']):
            e={'start_abs_min':base+round(span['start_h']*60),'end_abs_min':base+round(span['end_h']*60)}
            if span.get('event_id'):
                original=next(e for e in scene['source_A']['timeline_48h']if e['event_id']==span['event_id'])
                e.update({k:original[k]for k in ('event_id','operation_kind','start_abs_min','end_abs_min')})
            else:e.update(setpoint_C=span['setpoint_C'])
            events.append(e)
        A['rows'].append({'asset_id':row['device_id'],'device_class':row['icon_device_id'],'schedule_complete':True,'events':events})
    commands=[]
    # These adjustments are only explicit UI/validator test fixtures, not proposed research cases.
    for row in A['rows']:
        if row['device_class'] in ('dishwasher','electric_water_heater'):
            for event in row['events']:
                delta=20 if row['device_class']=='dishwasher' else -20
                commands.append({'command_id':f'fixture-command-{len(commands)+1}','asset_id':row['asset_id'],'device_class':row['device_class'],
                    'kind':'event_shift','event_id':event['event_id'],'A_start_abs_min':event['start_abs_min'],'A_end_abs_min':event['end_abs_min'],
                    'start_abs_min':event['start_abs_min']+delta,'end_abs_min':event['end_abs_min']+delta,'source_A_sha256':digest(A),
                    'reason_text':'测试多事件安排的显示；效果尚未计算。','effect_path_status':'fixture_not_evaluated'})
        if row['device_class']=='ac':
            event=row['events'][0]
            commands.append({'command_id':f'fixture-command-{len(commands)+1}','asset_id':row['asset_id'],'device_class':'ac','kind':'ac_setpoint',
                'start_abs_min':event['start_abs_min'],'end_abs_min':event['start_abs_min']+30,'from_setpoint_C':event['setpoint_C'],
                'to_setpoint_C':event['setpoint_C']+.5,'source_A_sha256':digest(A),'reason_text':'测试事件内温度设定变化；效果尚未计算。','effect_path_status':'fixture_not_evaluated'})
    B=apply_commands(A,commands,profile)
    case={'schema':'eb.joint_b.consumer.v1','identity':{'case_id':'engineering-joint-fixture-001','role_id':role,'round_index':None,'split':None,'date':scene['artifact']['date'],'day_index':day},
        'status':'engineering_fixture','prototype_only':True,'human_label_count':0,'training_release':False,
        'profile':profile,'context':{**scene['context'],'pre_event_state':{'status':'not_provided'},'description':'仅用于检验多设备、多事件展示的本地测试。'},
        'vpp':{'event_id':'fixture-vpp-001','start_abs_min':base+20*60,'end_abs_min':base+22*60,'notice_abs_min':base+12*60,
            'household_request':{'scope':'household','text':'测试请求：比较这两小时内的家庭用电安排。','quantity':None,'unit':None},
            'incentive':{'definition_id':'fixture-incentive-definition-001','text':'测试激励：按测试规则完成请求可获得2元；尚未判断是否符合条件。'},'evidence_status':'engineering_fixture'},
        'commands':commands,'plans':{'A':A,'B':B},'quantities':[{'label':'整屋用电','A':{'value':None,'unit':'kWh','status':'not_computed'},'B':{'value':None,'unit':'kWh','status':'not_computed'}}],
        'impacts':[],'display_assignment':{'left':'A','right':'B'},
        'bindings':{'canonical_sha256':data['source_contract_sha256'],'source_display_sha256':hashlib.sha256(DATA.read_bytes()).hexdigest(),'source_case_sha256':digest(scene)}}
    bind(case);other=deepcopy(case);other['identity']['case_id']='engineering-joint-fixture-002';other['vpp']['incentive']=None;other['display_assignment']={'left':'B','right':'A'};bind(other)
    return [case,other]

def write_page(cases,out):
    out.mkdir(exist_ok=True)
    pinned={}
    for name in ('style.css','candidate.css','plan-view.js','source-draft.js'):
        raw=(BASE/name).read_bytes();pinned[name]=hashlib.sha256(raw).hexdigest()
        if name=='plan-view.js':
            renderer=raw.decode().replace("day===0?'当天':day===1?'次日':`第${day+1}天`","day===-1?'前日':day===0?'当天':day===1?'次日':`第${day+1}天`")
            renderer=renderer.replace('Math.floor(m%1440/60)','Math.floor(((m%1440)+1440)%1440/60)').replace("String(m%60)","String(((m%60)+60)%60)")
            start=renderer.index("    const shade=n('span',undefined,'event-shade')");end=renderer.index('\n',start)
            renderer=renderer[:start]+"    for(const event of c.event_windows||[{start_h:c.event_start_h,end_h:c.event_end_h}]){const shade=n('span',undefined,'event-shade');shade.style.left=pct(event.start_h,c)+'%';shade.style.width=(pct(event.end_h,c)-pct(event.start_h,c))+'%';shade.setAttribute('aria-hidden','true');track.append(shade);}"+renderer[end:]
            renderer=renderer.replace("[[options.eventLabel||'错峰',`${clock(c.event_start_h)}—${clock(c.event_end_h)}`],['展示时段',`${clock(c.start_h,true)}—${clock(c.end_h,true)}`]]","[...(c.event_windows||[{start_h:c.event_start_h,end_h:c.event_end_h}]).map((e,i)=>[(options.eventLabel||'错峰')+' '+(i+1),`${clock(e.start_h)}—${clock(e.end_h)}`]),['展示时段',`${clock(c.start_h,true)}—${clock(c.end_h,true)}`]]")
            raw=renderer.encode()
        (out/name).write_bytes(raw)
    candidate=(BASE/'candidate.js').read_text();home=candidate[:candidate.index('function feedback()')]
    (out/'household-view.js').write_text(home)
    for name in ('joint-view.js','joint-view.css'):(out/name).write_bytes((HERE/name).read_bytes())
    profiles={c['identity']['role_id']:c['profile']for c in cases}
    data_tags=''
    for id,value in [('profile-data',profiles),('source-selection-data',{}),('source-cases-data',{}),('joint-cases-data',cases),('visible-inputs-data',[visible_input(c)for c in cases]),('source-hashes-data',[digest(c)for c in cases])]:
        data_tags+=f'<script type="application/json" id="{id}">'+canonical(value).replace('<','\\u003c')+'</script>'
    html=(HERE/'template.html').read_text().replace('__DATA_TAGS__',data_tags)
    (out/'index.html').write_text(html)
    return pinned,{p.name:hashlib.sha256(p.read_bytes()).hexdigest()for p in sorted(out.iterdir())}

def build(case_file=None,expected_case_sha256=None):
    fixture_cases=fixtures();(HERE/'fixtures.json').write_text(canonical(fixture_cases)+'\n')
    imported_path=Path(case_file)if case_file else HERE/'IMPORTED_A_CASES.json'
    imported_sha=hashlib.sha256(imported_path.read_bytes()).hexdigest()if imported_path.exists()else None
    require(not case_file or expected_case_sha256==imported_sha,'Case file needs matching exact SHA')
    imported=json.loads(imported_path.read_text())if imported_path.exists()else []
    require(imported and all(c['status']=='source_bound_candidate'for c in imported),'Source-bound cases required for preview')
    cases=fixture_cases+imported
    pinned,files=write_page(cases,HERE/'page')
    _,preview_files=write_page(imported,HERE/'preview_page')
    physical_pairs=sum('physical_readback'in c for c in imported)
    meta={'status':'isolated_fixtures_and_source_bound_prototypes','fixture_source_A_actual_case':'cityrole-0019 round 3, 2025-01-16','fixture_cases':sum(c['status']=='engineering_fixture'for c in cases),'imported_A_prototypes':sum(c['status']=='source_bound_candidate'for c in cases),'commands_per_case':[len(c['commands'])for c in cases],
        'human_answers':0,'physical_pairs_displayed':physical_pairs,'training_release':False,'source_A_sample_not_new_quota':True,'pinned_upstream_assets':pinned,'isolated_renderer_changes':['multiple event windows','previous-day clock'],
        'upstream_v5_manifest_sha256':hashlib.sha256((BASE.parent/'static-experience-v5.manifest.json').read_bytes()).hexdigest(),
        'files':files,'preview_files':preview_files,'preview_cases':len(imported),'preview_contains_engineering_fixtures':False,
        'active_case_file_sha256':imported_sha,'active_case_file':str(imported_path)}
    (HERE/'BUILD_MANIFEST.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(meta,ensure_ascii=False))
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--case-file',type=Path);parser.add_argument('--expected-case-sha256');args=parser.parse_args()
    build(args.case_file,args.expected_case_sha256)
