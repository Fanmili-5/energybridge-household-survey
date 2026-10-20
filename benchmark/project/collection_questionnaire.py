"""Frozen ten-day collection -> existing v69 read-only materials, never deploy."""
import subprocess
from pathlib import Path
from benchmark.ab_generation.common import read,save,seal,verify,sha,bound,digest
from benchmark.ab_generation.sampling import command_hash
from .questionnaire import HERE,COLLECTOR,UI,preview_assets,profile_and_lines,display_plans,changes,verify_questionnaire


def build_collection_questionnaire(collection,source,out):
    collection=Path(collection).resolve();source=Path(source).resolve();out=Path(out).resolve()
    verify(collection);verify(source);verify(source/'families')
    assignment=read(collection/'ASSIGNMENT.json')
    if assignment['schema']!='eb.collection.assignment.v4':raise ValueError('V4_COLLECTION_REQUIRED')
    out.mkdir(parents=True,exist_ok=False);preview_assets(out)
    js=out/'public/view.js';code=js.read_text();anchor="      const shown = axes?.length ? axes : ['heating_setpoint_C','cooling_setpoint_C','fan_operating_mode'];"
    if code.count(anchor)!=1:raise ValueError('V69_CONTROL_ADAPTER_ANCHOR_CHANGED')
    code=code.replace(anchor,"      if(kind==='ac_setpoint' && x._eb_cooling_stop_fallback) return '暂停制冷请求（实际运行未计算）';\n"+anchor)
    js.write_text(code)
    family_records={r['household_id']:r for r in read(source/'families/SUMMARY.json')['records']}
    index={'schema':'eb.project.v69_index.v1','ui_revision':UI,'adapter_revision':'eb.collection.v69_adapter.v1',
           'households':[],'cases':[],'profiles_sha256':{},'mode':'read_only_material_preview',
           'new_EP_runs':0,'human_collection_release':False,'training_release':False}
    audit=[];profiles={}
    for ident in assignment['selected_ids']:
        pair=read(collection/'pairs'/(ident+'.json'));row=pair['row'];hid=row['household_id'];date=row['date']
        c=read(collection/'contexts'/(row['case_id']+'.json.gz'))
        family_path=bound(source/'families',family_records[hid]['path']);family=read(family_path)
        if sha(family_path)!=c['source']['family_sha256']:raise ValueError('COLLECTION_FAMILY_BINDING_MISMATCH')
        life_root=source/'connected/life_A'/hid;verify(life_root)
        life=read(bound(life_root,read(life_root/'MANIFEST.json')['records'][0]['path']))
        world=read(life_root/'WORLD_INPUT.json')['households'][0];layout_path=source/'connected/shells'/hid/'layout.json';layout=read(layout_path)
        household={'members':world['members'],'devices':world['devices'],'A':c['A'],
                   'calendars':life['days'][date]['calendars'],
                   'housing':{'rooms':layout['rooms'],'access':layout['access'],'outer_rect_m':layout['metric_outer_rect_m'],
                              'gross_area_m2':layout['whole_unit_building_area_m2'],'usable_area_m2':layout['usable_total_area_m2'],
                              'source':'declared_reference_geometry;not_surveyed_floorplan','shared_households':layout['shared_household_count_design'],
                              'shell_status':'compiled','paired_idf_status':'not_prepared'}}
        profile,lines=profile_and_lines(family,household,c)
        if hid not in profiles:
            profiles[hid]=profile;save(out/'public/households'/(hid+'.json'),profile)
            index['households'].append(hid);index['profiles_sha256'][hid]=sha(out/'public/households'/(hid+'.json'))
        elif digest(profile)!=digest(profiles[hid]):raise ValueError('TEN_DAY_HOUSEHOLD_PROFILE_CHANGED')
        plans=display_plans(pair)
        # Typed presentation metadata only; original A/B, including raw 40C
        # fallback commands, stay unchanged in the content-bound source pair.
        contract=c['reference'].get('ac_control_contract',{})
        if contract.get('encoding')=='cooling_threshold_fallback;not_native_availability_off':
            for side in ('A','B'):
                for control in plans[side]['controls']:
                    if control['kind']=='ac_setpoint' and control.get('cooling_setpoint_C')==contract['cooling_off_fallback_C']:
                        control['_eb_cooling_stop_fallback']=True
        cid=row['case_id']+'__'+ident
        case={'schema':'eb.project.v69_case.v1','case_id':cid,'household_id':hid,'date':date,'window_min':[480,1920],
              'plans':plans,'changes':changes(plans),'project_presentation':{'family_lines':lines},
              'outcome_status':'not_computed','impact':None,'VPP_results':None,'response':None,
              'VPP_requests':[dict(e,notification_min=c['decision_min']) for e in c['events']],
              'bindings':{'sample_id':ident,'source_pair_sha256':sha(collection/'pairs'/(ident+'.json')),
                          'family_sha256':sha(family_path),'A_commands_sha256':command_hash(pair['A']),
                          'B_commands_sha256':command_hash(pair['B']),'housing_layout_sha256':sha(layout_path),
                          'information_set':c['reference']['information_set'],'selection_sha256':sha(collection/'ASSIGNMENT.json')}}
        relative='cases/'+hid+'/'+ident+'.json';save(out/'public'/relative,case)
        index['cases'].append({'household_id':hid,'case_id':cid,'date':date,'path':relative,'sha256':sha(out/'public'/relative)})
        audit.append({'sample_id':ident,'case_id':cid,'static_valid':not row['issues'],'static_issues':row['issues'],
                      'physical_results':'not_computed','retained':True})
    save(out/'public/index.json',index)
    run=subprocess.run(['node',str(HERE/'verify_display.js'),str(out)],capture_output=True,text=True)
    if run.returncode:raise ValueError('V69_COLLECTION_DISPLAY_REJECTED:'+run.stderr[-2000:])
    models=read(out/'DISPLAY_MODELS.json')
    if any('制冷40' in x['changes']+x['schedule'] for x in models.values()):raise ValueError('FALLBACK_DISPLAYED_AS_COMFORT_TEMPERATURE')
    save(out/'AUDIT.json',{'records':audit,'all_selected_retained':len(audit)==len(assignment['selected_ids']),
                         'failed_project_slots':[],'physical_outcomes_fabricated':False,'reroll_or_replacement':False})
    summary={'schema':'eb.project.v69_preview.v1','ui_revision':UI,'adapter_revision':index['adapter_revision'],
             'households':len(profiles),'cases':len(audit),'outcomes_not_computed':len(audit),
             'invalid_retained':sum(not x['static_valid'] for x in audit),'unchanged_controls_retained':0,
             'source_project_manifest_sha256':sha(source/'MANIFEST.json'),'source_collection_manifest_sha256':sha(collection/'MANIFEST.json'),
             'source_v69_assets':{str(p.relative_to(HERE.parent.parent)):sha(p) for p in sorted(COLLECTOR.iterdir()) if p.is_file()},
             'adapter_sources':{str(p.relative_to(HERE.parent.parent)):sha(p) for p in [Path(__file__),HERE/'questionnaire.py',HERE/'preview-client.js',HERE/'verify_display.js']},
             'question_text_and_scales_changed':False,'new_EP_runs':0,'production_deployed':False,'human_collection_release':False,
             'training_release':False,'online_questionnaire_changed':False}
    save(out/'SUMMARY.json',summary);seal(out,{'schema':summary['schema'],'ui_revision':UI,'new_EP_runs':0})
    verify_questionnaire(out);return summary
