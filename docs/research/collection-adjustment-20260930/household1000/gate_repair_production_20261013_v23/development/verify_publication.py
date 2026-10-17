"""School-side public source/CLI/protected-data availability verification."""
import ast,json,hashlib,subprocess,re,os,datetime,sys
from pathlib import Path
root=Path(sys.argv[1]).resolve();workspace=Path(sys.argv[2]).resolve();node=sys.argv[3];pub=root/'docs/household1000'
manifest=json.loads((pub/'SOURCE_SNAPSHOT.json').read_text());errors=[];python_checked=0;js_checked=0
for row in manifest['source_files']:
 p=root/row['path']
 if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=row['published_sha256']:errors.append({'check':'source_bytes','path':row['path']});continue
 if p.suffix=='.py':
  try:ast.parse(p.read_text(),filename=str(p));python_checked+=1
  except SyntaxError as e:errors.append({'check':'python310_AST','path':row['path'],'line':e.lineno,'error':e.msg})
 elif p.suffix=='.js':
  proc=subprocess.run([node,'--check',str(p)],capture_output=True,text=True);js_checked+=1
  if proc.returncode:errors.append({'check':'JS_syntax','path':row['path'],'error':proc.stderr[:1500]})
html=root/Path(manifest['active_stage'])
stage=root/'docs/research/collection-adjustment-20260930/household1000'/manifest['active_stage']
page=(stage/'frontend_snapshot/index.html').read_text();ids=['profile-data','source-cases-data','source-selection-data','joint-cases-data','visible-inputs-data','source-hashes-data']
for key in ids:
 m=re.search(r'<script[^>]+id="'+key+r'"[^>]*>(.*?)</script>',page,re.S)
 if not m or json.loads(m.group(1)) not in ({},[]):errors.append({'check':'case_free_template','script':key})
commands=[['status'],['stages'],['check-source'],['doctor'],['doctor','--workspace',str(workspace)],
 ['check-bindings','--workspace',str(workspace),'--scope','pilot50'],['check-bindings','--workspace',str(workspace),'--scope','static1000']]
cli=[]
for args in commands:
 proc=subprocess.run(['python3',str(root/'scripts/household1000.py')]+args,capture_output=True,text=True)
 item={'command':args,'returncode':proc.returncode}
 if proc.returncode:errors.append({'check':'read_only_CLI','command':args,'error':proc.stderr[-1500:]})
 try:
  result=json.loads(proc.stdout)
  if args[0]=='check-bindings':item['result']=result
  elif args[0]=='doctor':item['result']=result
 except Exception as e:errors.append({'check':'CLI_JSON','command':args,'error':str(e)})
 cli.append(item)
proc=subprocess.run(['python3','-m','unittest','discover','-s','tests','-p','test_household1000_entrypoint.py','-v'],cwd=root,capture_output=True,text=True)
if proc.returncode:errors.append({'check':'existing_entrypoint_tests','error':proc.stdout+proc.stderr})
links=0
docs=[root/'README.md',root/'docs/README.md']+list(pub.glob('*.md'))+[stage/'PRODUCTION_LOGIC_CHAIN.md',stage/'METHODS.md']
for p in docs:
 for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)',p.read_text()):
  target=target.strip('<>').split('#')[0]
  if not target or re.match(r'^[a-zA-Z]+:',target) or target.startswith('//'):continue
  links+=1
  if not (p.parent/target).resolve().exists():errors.append({'check':'local_document_link','path':str(p.relative_to(root)),'target':target})
pipeline=json.loads((pub/'PIPELINE.json').read_text())
for step in pipeline['steps']:
 for name in step['source_files']:
  if not (root/name).is_file():errors.append({'check':'pipeline_source','path':name})
report={'version':manifest['version'],'checked_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
 'host':'school Linux','source_integrity_files':len(manifest['source_files']),'python_AST_checked':python_checked,
 'python_AST_environment':sys.version,'javascript_files_checked':js_checked,'node':subprocess.check_output([node,'--version'],text=True).strip(),
 'frontend_case_JSON_payloads_removed':6,'read_only_CLI':cli,'entrypoint_tests':{'returncode':proc.returncode,'output':proc.stdout+proc.stderr},
 'local_markdown_links_checked':links,'errors':errors,'status':'fail' if errors else 'pass',
 'new_EP_runs':0,'human_answers_created':0,'fresh_private_raw_source_reconstruction':False,
 'scope':'public actual source bytes and prepared protected bindings;not field/human/algorithm validation'}
(pub/'PUBLICATION_CHECK.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
(pub/'SCHOOL_BINDING_CHECK.json').write_text(json.dumps({'version':manifest['version'],'host':'school Linux','checks':[c['result'] for c in cli if c['command'][0]=='check-bindings'],'new_EP_runs':0,'human_answers_created':0},ensure_ascii=False,indent=2)+'\n')
(pub/'ENTRYPOINT_TEST_CHECK.json').write_text(json.dumps({'version':manifest['version'],'host':'school Linux','returncode':proc.returncode,'output':proc.stdout+proc.stderr,'new_EP_runs':0},indent=2)+'\n')
(pub/'JS_SOURCE_CHECK.json').write_text(json.dumps({'version':manifest['version'],'host':'school Linux','node':'20.19.0','files':js_checked,'failures':[e for e in errors if e['check']=='JS_syntax']},indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k not in ('read_only_CLI','entrypoint_tests')},ensure_ascii=False,indent=2))
raise SystemExit(1 if errors else 0)
