"""Derive a clean UI91 information version without regenerating any case."""
import argparse
import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path
from benchmark.ab_generation.common import read,save,sha,digest
from .questionnaire import COLLECTOR,HERE
from .reference_refined_release import ASSETS,PRESENTATION,participant_renderer,participant_html


def build(parent_release,out):
    parent_release,out=map(lambda p:Path(p).resolve(),(parent_release,out))
    sys.path.insert(0,str(COLLECTOR))
    from release import Release
    # The sealed input can bind an older collector runtime. Its bytes and
    # signature are still verified; only this new release uses current code.
    parent=Release(parent_release,verify_code=False)
    if parent.manifest['schema']!='eb.reference_benchmark.release.v2':raise ValueError('BOUND_PHYSICS_RELEASE_REQUIRED')
    pins=read(ASSETS/'SOURCE.json')
    for name,expected in pins['files'].items():
        if sha(ASSETS/name)!=expected:raise ValueError('UI91_ASSET_CHANGED:'+name)
    shutil.copytree(parent_release,out)
    public=out/'public'
    view=public/'view.js';view.write_text(participant_renderer(view.read_text()))
    html=public/'index.html';html.write_text(participant_html(html.read_text()))
    for name in ('view.css','required-response.js'):(public/name).write_bytes((ASSETS/name).read_bytes())
    (public/'collection-client.js').write_bytes((COLLECTOR/'collection-client.js').read_bytes())
    instructions=read(out/'ANSWER_INSTRUCTIONS.json')
    instructions.update(decimal_places=0,score_values=[0,1,2,3,4,5],range=[0,5],anchors={'0':'很不合适','5':'很合适'})
    save(out/'ANSWER_INSTRUCTIONS.json',instructions)
    index=copy.deepcopy(parent.index);index['presentation_revision']=PRESENTATION
    save(public/'index.json',index)
    for name in ('DISPLAY_MODELS.json','DISPLAY_MODELS50.json'):(out/name).unlink(missing_ok=True)
    run=subprocess.run(['node',str(HERE/'verify_refined_display.js'),str(out)],capture_output=True,text=True)
    if run.returncode:raise ValueError(run.stderr[-5000:])
    save(out/'DISPLAY_MODELS50.json',read(out/'DISPLAY_MODELS.json'))
    index['ui_assets_sha256']={p.name:sha(p) for p in public.iterdir() if p.is_file()}
    save(out/'INDEX50.json',index)
    m=copy.deepcopy(parent.manifest)
    m.update(presentation_revision=PRESENTATION,production_deployed=False,
             cohort_id=parent.manifest['cohort_id']+'-display-v2')
    m['source_pins'].update(parent_information_release_sha256=parent.signature,
                            participant_presentation_builder_sha256=sha(Path(__file__)),
                            participant_presentation_sources_sha256=sha(ASSETS/'SOURCE.json'))
    m['presentation_update']={'case_bytes_unchanged':True,'profiles_unchanged':True,'new_EP_runs':0,
        'answers_copied':False,'complete_schedule_available':False,
        'score_values':[0,1,2,3,4,5],
        'laundry_display':'separate_washer_and_dryer_programmes;original_asset_ids_retained',
        'engineering_diagnostics':'retained_in_case_data;not_displayed_as_participant_advice'}
    m['implementation_files']={p.name:sha(p) for p in sorted(COLLECTOR.iterdir()) if p.is_file() and p.suffix!='.pyc'}
    (out/'FORMAL_RELEASE.json').unlink()
    m['files']={str(p.relative_to(out)):sha(p) for p in sorted(out.rglob('*')) if p.is_file()}
    m['release_sha256']=digest({k:v for k,v in m.items() if k!='release_sha256'})
    save(out/'FORMAL_RELEASE.json',m)
    updated=Release(out)
    assert updated.records==parent.records
    assert updated.index['profiles_sha256']==parent.index['profiles_sha256']
    for row in parent.records.values():
        assert (public/row['path']).read_bytes()==(parent_release/'public'/row['path']).read_bytes()
    return {'passed':True,'release_sha256':updated.signature,'parent_release_sha256':parent.signature,
            'presentation_revision':PRESENTATION,'cases_unchanged':len(updated.records),
            'profiles_unchanged':len(updated.households),'new_EP_runs':0,'online_changed':False}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--parent-release',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();print(json.dumps(build(a.parent_release,a.out),ensure_ascii=False))
