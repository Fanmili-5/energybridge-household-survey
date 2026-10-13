"""Read saved actor/consumer files independently from production render functions."""
import collections,datetime as dt
from common import *
def main():
 school_guard();sel=read(OUT/'SELECTION1000.json');fail=[];counts=collections.Counter();sizes=[]
 for h in sel['records']:
  w=read(OUT/h['world_path']);a=read(OUT/'actors'/f"{h['household_id']}.json");prof=a['profile'];hh=prof['household']
  for key,val in [('family_size',w['N']),('generation_count',w['G']),('h6_design_building_area_m2',w['H6']),('natural_rooms_H7',w['H7'])]:
   if hh[key]!=val:fail.append([h['household_id'],'PROFILE_ANCHOR',key])
  if hh['comfort_importance_1_5'] is not None or hh['saving_importance_1_5'] is not None:fail.append([h['household_id'],'PREFERENCE_IMPUTED'])
  if a['world_content_sha256']!=w['world_content_sha256']:fail.append([h['household_id'],'ACTOR_WORLD_BINDING'])
  counts['actor_cards']+=1
  if w['N']==1 and w['members'][0]['age_years']<18:
   counts['minor_only_guardian_worlds']+=1
   if not all(o.get('roleplay_representative')=='adult guardian answers on behalf of this reference household' for o in prof['operating_context']['operators']):fail.append([h['household_id'],'GUARDIAN_NOT_DECLARED'])
  for old,new in zip(w['members'],prof['members']):
   if any(old[k]!=new[k] for k in ('member_id','age_years','sex','employment_status','current_work_source_proxy')):fail.append([h['household_id'],'MEMBER_BINDING'])
  for row in h['rounds']:
   q=read(OUT/row['pair_path']);c=read(OUT/'consumers'/h['household_id']/f"{row['round_index']:02d}.json");counts['consumer_tasks']+=1
   if c['bindings']['source_pair_sha256']!=row['pair_sha256'] or c['profile']['source_world_sha256']!=w['world_content_sha256']:fail.append([q['case_id'],'CONSUMER_BINDING'])
   if not c['commands'] or c['plans']['A']==c['plans']['B']:fail.append([q['case_id'],'NO_VISIBLE_REQUEST'])
   if c['human_label_count']!=0 or c['collection_release'] or c['training_release']:fail.append([q['case_id'],'EARLY_RELEASE'])
   for side in ('A','B'):
    if c['plans'][side]['window_start_abs_min']!=480 or c['plans'][side]['window_end_abs_min']!=1920:fail.append([q['case_id'],'WINDOW_CHANGED'])
    if c['plans'][side].get('semantics')!='requested instructions; executed program and service delivery are separately reported':fail.append([q['case_id'],'REQUEST_AS_EXECUTION'])
   texts='\n'.join(c['context']['daily_need_texts']);sizes.append(len(texts))
   for day in q['dated_activity_days']:
    if day['date'] not in texts:fail.append([q['case_id'],'FUTURE_DATE_MISSING',day['date']])
    if day['transport'] and str(day['transport']['traction_kWh']) not in texts:fail.append([q['case_id'],'JOURNEY_DOSE_MISSING'])
   for m in c['profile']['profile']['members']:
    if len(m['dated_context_calendars'])!=3 or m['local_id'] not in {x['local_id'] for x in w['members']}:fail.append([q['case_id'],'MEMBER_CONTEXT'])
   if any('ac' in d['types'] for d in w['parameter_pack']['devices']) and not any(i['status']=='given_reference_model_boundary' for i in c['impacts']):fail.append([q['case_id'],'DX_BOUNDARY_HIDDEN'])
   if c['physical']['status']=='pending':counts['physical_pending_tasks']+=1
   elif c['physical']['status']!='computed_reference':fail.append([q['case_id'],'OVERSTATED_PHYSICS_STATUS'])
 index=read(OUT/'frontend_release/INDEX50.json');counts['original_frontend_households']=len(index['households'])
 for h in index['households']:
  page=(OUT/'frontend_release/households'/h['household_id']/'index.html').read_text()
  for token in ['name="source_decision"','id="score-question"','id="joint-comment"','id="joint-needs"','id="joint-plan-details"']:
   if token not in page:fail.append([h['household_id'],'ORIGINAL_UI_ELEMENT_MISSING',token])
  if 'constraint_assessment' in page or 'design_condition' in page:fail.append([h['household_id'],'HIDDEN_DIAGNOSTIC_IN_PAGE'])
 sizes.sort();save(OUT/'MATERIALS_AUDIT.json',{'status':'fail' if fail else 'pass','counts':dict(counts),'failures':fail,
  'needs_text_character_lengths':{'min':sizes[0],'median':sizes[len(sizes)//2],'max':sizes[-1]},
  'readability_empirically_validated':False,'actor_responses':0,'assertions':'same saved household,needs,dates,requested plans,unknown preference,model boundaries and original questions'})
 print(dict(counts),'failures',len(fail),'first',fail[:5],flush=True)
 if fail:raise RuntimeError(str(fail[:5]))
if __name__=='__main__':main()

