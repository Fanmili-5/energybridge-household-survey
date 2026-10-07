"""Local Chinese questionnaire preview;no network/storage/auto-human labels."""
from common import *
def main():
 guard();bindings=read(OUT/'COLLECTION_BINDINGS1000.json')['records'];public=[]
 for b in bindings:
  p=read(OUT/b['packet_path']);public.append({'role_id':b['household_id'],'card':(OUT/b['card_path']).read_text(),'material_sha256':b['card_sha256'],'questionnaire':read(OUT/b['questionnaire_path']),'task_type':b['task_type']})
 template=(OUT/'code/preview_template.html').read_text();payload=json.dumps(public,ensure_ascii=False,allow_nan=False).replace('<','\\u003c');(OUT/'questionnaire_preview.html').write_text(template.replace('/*PUBLIC_PACKETS*/',payload))
 save(OUT/'PREVIEW_INTEGRITY.json',{'roles':len(public),'file':'questionnaire_preview.html','contains_only_public_cards_and_blank_questionnaires':True,'private_or_postevent_model_labels_embedded':False,'calls_remote_API':False,'persists_submissions_without_explicit_export':False,'formal_answer_import_or_collection_started':False})
 print({'preview_roles':len(public),'formal_answers':0})
if __name__=='__main__':main()
