"""Invented HTTP-protocol cases only: no survey rows, EP results or human labels."""
import json
from pathlib import Path
from build import build,sha,write
from release import digest

def make(root,households=50):
    root=Path(root);source=root/'invented_source';source.mkdir(parents=True)
    index={'schema':'eb.invented_protocol.index.v1','households':[],'cases':[],'profiles_sha256':{},'version':'INVENTED PROTOCOL FIXTURE'}
    models={}
    for number in range(households):
        hid=f'invented-fixture-{number:04}';index['households'].append(hid)
        profile=source/f'public/households/{hid}.json';profile.parent.mkdir(parents=True,exist_ok=True)
        write(profile,{'schema':'eb.invented_profile.v1','household_id':hid,'fixture_only':True})
        index['profiles_sha256'][hid]=sha(profile)
        for day in range(1,11):
            date=f'2025-01-{day:02}';case_id=hid+'__'+date;path=f'cases/{hid}/{date}.json'
            case={'schema':'eb.invented_protocol_case.v1','fixture_only':True,'household_id':hid,'case_id':case_id,'date':date,
                  'plans':{'A':{},'B':{}},'bindings':{'fixture_only':True},'impact':{'fixture_only':True},'response':None,
                  'VPP_requests':[{'event_id':'invented','fixture_only':True}],
                  'VPP_results':[{'event_id':'invented','target_met':False,'fixture_only':True}]}
            target=source/'public'/path;target.parent.mkdir(parents=True,exist_ok=True);write(target,case)
            index['cases'].append({'household_id':hid,'case_id':case_id,'date':date,'path':path,'sha256':sha(target)})
            models[case_id]={'family':'虚构家庭，仅测试协议。','request':'虚构请求。','changes':'虚构变化。','impacts':'虚构结果，不是仿真。','schedule':'虚构排程。'}
    write(source/'INDEX50.json',index);write(source/'DISPLAY_MODELS50.json',models)
    m={'households':households,'cases':households*10,'fixture_only':True,'source_pins':{'fixture_only':True},'type_counts':{},
       'A_stage':'invented_fixture_A','B_stage':'invented_fixture_B','physical_stage':'no_physics','impact_stage':'invented_not_EP',
       'files':{str(p.relative_to(source)):sha(p)for p in sorted(source.rglob('*'))if p.is_file()}}
    m['release_sha256']=digest(m);write(source/'FORMAL_RELEASE.json',m)
    output=root/'release';build(source,output,'protocol_fixture');return output
